"""Traces: JSON Lines round-trip, strict schema, and first-divergence diagnosis.

A trace is what two cores compare, so the tests plant one difference and
check it is found where it is and nowhere else, that session-local sequence
numbers never count as a difference, and that a record written without
disassembly text (as a port in another language would) decodes from its bytes.
"""

from collections.abc import Iterator
from dataclasses import fields, replace
from io import StringIO

import pytest

from sixfiveohtwo import (
    TRACE_SCHEMA_VERSION,
    BoundaryKind,
    CPUState,
    DebugSession,
    StepRecord,
    TraceDifference,
    compare_step_records,
    first_session_divergence,
    first_trace_divergence,
    iter_session_steps,
    iter_trace_divergences,
    read_trace,
    step_record_from_dict,
    step_record_to_dict,
    write_trace,
)
from tests.conftest import Host

NOP, INX, DEX = 0xEA, 0xE8, 0xCA


def _session(*program: int, track_accesses: bool = False) -> DebugSession:
    machine = Host(program)
    return DebugSession(machine.cpu, peek_byte=machine.peek, track_accesses=track_accesses)


def _history(*program: int, track_accesses: bool = False) -> tuple[StepRecord, ...]:
    session = _session(*program, track_accesses=track_accesses)
    session.run(max_steps=2)
    return session.history


def _round_trip(records: tuple[StepRecord, ...]) -> tuple[StepRecord, ...]:
    stream = StringIO()
    assert write_trace(iter(records), stream) == len(records)
    stream.seek(0)
    return tuple(read_trace(stream))


def test_equal_traces_ignore_session_local_sequence_numbers() -> None:
    left = _history(NOP, NOP)
    right = tuple(replace(record, sequence=record.sequence + 100) for record in left)

    assert compare_step_records(left[0], right[0]) == ()
    assert first_trace_divergence(left, right) is None
    assert tuple(iter_trace_divergences(left, right)) == ()


def test_first_divergence_finds_a_planted_instruction_difference() -> None:
    left = _history(NOP, INX)
    right = _history(NOP, DEX)

    divergence = first_trace_divergence(left, right)

    assert divergence is not None and divergence.position == 1
    differences = {item.path: (item.left, item.right) for item in divergence.differences}
    assert differences == {
        "instruction.data": ("e8", "ca"),
        "instruction.mnemonic": ("INX", "DEX"),
        "after.x": (0x01, 0xFF),
        "after.p": (0x24, 0xA4),  # N set by DEX
    }
    assert divergence.as_dict()["position"] == 1


def test_every_cpu_state_field_participates_in_comparison() -> None:
    record = _history(NOP, NOP)[0]
    for field in fields(CPUState):
        current = getattr(record.before, field.name)
        if field.name == "polled_i":
            changed = True
        elif type(current) is bool:
            changed = not current
        else:
            changed = current ^ 1
        other = replace(record, before=replace(record.before, **{field.name: changed}))
        paths = [item.path for item in compare_step_records(record, other)]
        assert paths == [f"before.{field.name}"]


def test_one_sided_exhaustion_is_reported_as_a_missing_record() -> None:
    records = _history(NOP, NOP)
    (divergence,) = iter_trace_divergences(records[:1], records)
    assert (divergence.position, divergence.left, divergence.right) == (1, None, records[1])
    assert divergence.differences == (TraceDifference("record", None, "present"),)


def test_first_divergence_stops_consuming_after_the_unequal_pair() -> None:
    records = _history(NOP, NOP)
    consumed: list[int] = []

    def right() -> Iterator[StepRecord]:
        consumed.append(0)
        yield replace(records[0], cycles=3)
        consumed.append(1)
        yield records[1]

    assert first_trace_divergence(records, right()) is not None
    assert consumed == [0]


def test_live_sessions_stop_at_the_first_divergence() -> None:
    left = _session(NOP, INX, NOP)
    right = _session(NOP, DEX, NOP)

    divergence = first_session_divergence(left, right, max_steps=3)

    assert divergence is not None and divergence.position == 1
    assert (left.total_steps, right.total_steps) == (2, 2)
    assert left.history[0] == right.history[0]
    with pytest.raises(ValueError, match="max_steps"):
        tuple(iter_session_steps(left, max_steps=0))


def test_accesses_are_compared_only_when_both_records_carry_them() -> None:
    tracked = _history(0xA5, 0x10, track_accesses=True)[0]  # LDA $10
    plain = _history(0xA5, 0x10)[0]
    assert compare_step_records(tracked, plain) == ()

    altered = step_record_to_dict(tracked)
    altered["accesses"][2][2] = 0x41  # type: ignore[index]
    paths = [item.path for item in compare_step_records(tracked, step_record_from_dict(altered))]
    assert paths == ["accesses"]


def test_json_lines_round_trip_is_deterministic_and_keeps_accesses() -> None:
    records = _history(0xA9, 0x2A, 0x85, 0x10, track_accesses=True)
    lifecycle = replace(records[0], kind=BoundaryKind.RESET, instruction=None, cycles=7)
    first, second = StringIO(), StringIO()
    write_trace(records, first)
    write_trace(records, second)
    assert first.getvalue() == second.getvalue()
    assert f'"version":{TRACE_SCHEMA_VERSION}' in first.getvalue()

    restored = _round_trip((*records, lifecycle))

    assert first_trace_divergence(restored, (*records, lifecycle)) is None
    assert restored[1].accesses == (("r", 0x0202, 0x85), ("r", 0x0203, 0x10), ("w", 0x10, 0x2A))
    assert [step_record_to_dict(record) for record in restored] == [
        step_record_to_dict(record) for record in (*records, lifecycle)
    ]
    assert restored[2] == lifecycle
    assert "accesses" not in step_record_to_dict(_history(NOP)[0])


def test_read_trace_restores_records_equal_to_those_written() -> None:
    records = _history(0xA9, 0x2A, 0xB1, 0x12)  # LDA #$2A; LDA ($12),Y
    assert _round_trip(records) == records


def _native() -> dict[str, object]:
    return step_record_to_dict(_history(0xA9, 0x2A, track_accesses=True)[0])


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.pop("version"), "missing"),
        (lambda value: value.__setitem__("version", 999), "version"),
        (lambda value: value.__setitem__("unknown", 1), "unknown"),
        (lambda value: value.__setitem__("kind", "halt_idle"), "boundary kind"),
        (lambda value: value.__setitem__("cycles", 0), "cycles"),
        (lambda value: value.__setitem__("sequence", -1), "sequence"),
        (lambda value: value["before"].pop("polled_i"), "before fields"),
        (lambda value: value["after"].__setitem__("p", 0x34), "after CPU state"),
        (lambda value: value["after"].__setitem__("pc", 0x10000), "after CPU state"),
        (lambda value: value["instruction"].__setitem__("data", "not hex"), "hexadecimal"),
        (lambda value: value["instruction"].pop("operands"), "instruction fields"),
        (lambda value: value.__setitem__("accesses", [["x", 0, 0]]), "accesses"),
        (lambda value: value.__setitem__("accesses", [["r", 0]]), "accesses"),
        (lambda value: value.__setitem__("accesses", [["r", 0x10000, 0]]), "accesses"),
    ],
)
def test_schema_rejects_missing_unknown_and_invalid_fields(mutate, message: str) -> None:
    value = _native()
    mutate(value)
    with pytest.raises(ValueError, match=message):
        step_record_from_dict(value)


def test_read_trace_reports_the_malformed_line_number_lazily() -> None:
    record = _history(NOP)[0]
    stream = StringIO()
    write_trace((record,), stream)
    stream.write("\n{bad json}\n")
    stream.seek(0)
    records = read_trace(stream)

    assert next(records) == record
    with pytest.raises(ValueError, match="line 3"):
        next(records)


def _external(data: str, address: int = 0x0200) -> dict[str, object]:
    value = _native()
    value["instruction"] = {"address": address, "data": data}
    return value


def test_instruction_text_is_derived_from_the_bytes_when_omitted() -> None:
    record = step_record_from_dict(_external("b112", 0x1234))
    assert record.instruction is not None
    assert (record.instruction.text, record.instruction.address) == ("LDA ($12),Y", 0x1234)
    assert record.instruction.mode == "indirect_indexed"

    native = step_record_from_dict(_native())
    assert compare_step_records(native, step_record_from_dict(_external("a92a"))) == ()
    differences = compare_step_records(native, step_record_from_dict(_external("a22a")))
    assert {item.path: (item.left, item.right) for item in differences} == {
        "instruction.data": ("a92a", "a22a"),
        "instruction.mnemonic": ("LDA", "LDX"),
    }


@pytest.mark.parametrize(
    ("data", "message"),
    [("eaea", "exactly one instruction"), ("ad34", "decodable"), ("", "decodable")],
)
def test_derived_instruction_must_be_exactly_one_whole_encoding(data: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        step_record_from_dict(_external(data))


def test_trace_values_and_inputs_are_validated() -> None:
    record = _history(NOP)[0]
    with pytest.raises(ValueError, match="unequal"):
        TraceDifference("pc", 1, 1)
    with pytest.raises(TypeError, match="StepRecord"):
        compare_step_records(record, object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="traces"):
        tuple(iter_trace_divergences((record,), (object(),)))  # type: ignore[arg-type]
