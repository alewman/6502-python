"""Exhaustive, file-level execution of the SingleStepTests 6502 corpus."""

from __future__ import annotations

from pathlib import Path

import pytest

from sixfiveohtwo import pack_status_byte
from tests.vector_support import adapt_vector, iter_vector_file

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_VECTOR_ROOT = _PROJECT_ROOT / "tests" / "6502_test_vectors" / "6502"


def _vector_files() -> tuple[Path, ...]:
    """Discover corpus files while keeping every path inside this checkout."""
    project_root = _PROJECT_ROOT.resolve()
    root = _VECTOR_ROOT.resolve()
    try:
        root.relative_to(project_root)
    except ValueError:
        return ()
    if not root.is_dir():
        return ()
    files = []
    for candidate in root.rglob("*"):
        if candidate.suffix.lower() != ".json" or not candidate.is_file():
            continue
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        files.append(resolved)
    return tuple(sorted(files, key=lambda path: path.relative_to(root).as_posix()))


_SOURCES = _vector_files()
_FILE_CASES: tuple[Path | None, ...] = _SOURCES or (None,)
_FILE_IDS = [
    f"vector:6502/{path.relative_to(_VECTOR_ROOT.resolve()).as_posix()}"
    for path in _SOURCES
] or ["vector corpus missing"]


def _context(vector, opcode):
    return (
        f"{vector.source} [record {vector.index}, {vector.name}, "
        f"opcode 0x{opcode:02X}]"
    )


def _assert_field(context, field, actual, expected):
    message = f"{context}: {field}: expected {expected!r}, got {actual!r}"
    assert actual == expected, message


def _assert_post_state(vector, cpu, memory, result):
    initial_ram = dict(vector.initial["ram"])
    expected_ram = dict(vector.final["ram"])
    opcode = initial_ram.get(vector.initial["pc"], 0)
    context = _context(vector, opcode)
    state = cpu.state

    _assert_field(context, "cycles (step)", result.cycles, len(vector.cycles))
    _assert_field(context, "cycles (state total)", state.cycles, len(vector.cycles))
    for field, actual, expected in (
        ("a", state.a.value, vector.final["a"]),
        ("x", state.x.value, vector.final["x"]),
        ("y", state.y.value, vector.final["y"]),
        ("pc", state.pc.value, vector.final["pc"]),
        ("sp", state.sp.value, vector.final["s"]),
    ):
        _assert_field(context, field, actual, expected)

    actual_status = pack_status_byte(state.status)
    _assert_field(context, "status byte (p)", actual_status, vector.final["p"])
    flag_bits = {
        "negative": 0x80,
        "overflow": 0x40,
        "decimal": 0x08,
        "interrupt_disable": 0x04,
        "zero": 0x02,
        "carry": 0x01,
    }
    for name, bit in flag_bits.items():
        _assert_field(
            context,
            f"status flag {name}",
            getattr(state.status, name),
            bool(vector.final["p"] & bit),
        )

    # The corpus RAM sections are sparse snapshots; compare every oracle address
    # and reject emulator state that introduces an extra sparse entry.
    _assert_field(context, "memory addresses", set(memory.bytes), set(expected_ram))
    for address, expected in sorted(expected_ram.items()):
        _assert_field(
            context, f"memory[0x{address:04X}]", memory.bytes[address], expected
        )
    expected_mutations = {
        address: value
        for address, value in expected_ram.items()
        if initial_ram.get(address) != value
    }
    actual_mutations = {
        address: memory.bytes[address]
        for address in memory.bytes
        if initial_ram.get(address) != memory.bytes[address]
    }
    _assert_field(context, "memory mutations", actual_mutations, expected_mutations)


@pytest.mark.parametrize("source", _FILE_CASES, ids=_FILE_IDS)
def test_6502_vectors(source: Path | None):
    if source is None:
        pytest.skip(
            "SingleStepTests vectors are missing; run scripts/fetch_test_vectors.py"
        )

    for vector in iter_vector_file(source):
        cpu, memory = adapt_vector(vector)
        result = cpu.step()
        _assert_post_state(vector, cpu, memory, result)
