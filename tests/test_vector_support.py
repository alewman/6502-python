from __future__ import annotations

import pytest

from sixfiveohtwo import CPU
from tests.vector_support import (
    VectorMemory,
    VectorValidationError,
    adapt_vector,
    parse_vector_record,
)

VECTOR = {
    "name": "representative-lda",
    "initial": {
        "pc": 0x8000,
        "s": 0xF0,
        "a": 0x12,
        "x": 0x34,
        "y": 0x56,
        "p": 0xED,
        "ram": [[0x8000, 0xA9], [0x8001, 0x7F], [0x1234, 0x99]],
    },
    "final": {
        "pc": 0x8002,
        "s": 0xF0,
        "a": 0x7F,
        "x": 0x34,
        "y": 0x56,
        "p": 0x6D,
        "ram": [[0x8000, 0xA9], [0x8001, 0x7F], [0x1234, 0x99]],
    },
    "cycles": [
        [0x8000, 0xA9, "read"],
        [0x8001, 0x7F, "read"],
        [0x1234, 0x99, "write"],
    ],
}


def test_adapt_vector_initializes_cpu_registers_and_status():
    vector = parse_vector_record(VECTOR, source="inline.json", index=3)

    cpu, memory = adapt_vector(vector)

    assert isinstance(cpu, CPU)
    assert cpu.state.a.value == 0x12
    assert cpu.state.x.value == 0x34
    assert cpu.state.y.value == 0x56
    assert cpu.state.pc.value == 0x8000
    assert cpu.state.sp.value == 0xF0
    assert cpu.state.status.negative is True
    assert cpu.state.status.overflow is True
    assert cpu.state.status.decimal is True
    assert cpu.state.status.interrupt_disable is True
    assert cpu.state.status.zero is False
    assert cpu.state.status.carry is True
    assert cpu.state.cycles == 0
    assert memory.operations == []


def test_adapt_vector_provides_full_64k_address_space_and_initial_ram():
    vector = parse_vector_record(VECTOR)
    _, memory = adapt_vector(vector)

    assert memory.read_byte(0x0000) == 0
    assert memory.read_byte(0xFFFF) == 0
    assert memory.read_byte(0x8000) == 0xA9
    assert memory.read_byte(0x8001) == 0x7F
    assert memory.read_byte(0x1234) == 0x99
    with pytest.raises(ValueError, match="address must fit in 16 bits"):
        memory.read_byte(0x10000)


def test_vector_memory_observes_writes_without_losing_written_value():
    memory = VectorMemory()

    memory.write_byte(0xFFFF, 0xA5)

    assert memory.operations == [("write", 0xFFFF, 0xA5)]
    assert memory.read_byte(0xFFFF) == 0xA5
    assert memory.operations[-1] == ("read", 0xFFFF)


def test_parse_vector_record_converts_cycles_to_typed_tuples():
    vector = parse_vector_record(VECTOR, source="inline.json", index=3)

    assert vector.cycles == (
        (0x8000, 0xA9, "read"),
        (0x8001, 0x7F, "read"),
        (0x1234, 0x99, "write"),
    )


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({"name": "bad"}, "initial must be an object"),
        (
            {**VECTOR, "cycles": [[0x8000, 0xA9, "DMA"]]},
            "cycles[0] direction must be 'read' or 'write'",
        ),
        (
            {
                **VECTOR,
                "initial": {**VECTOR["initial"], "ram": [[0x10000, 0x00]]},
            },
            "initial.ram[0] address must be between 0 and 65535",
        ),
        (
            {**VECTOR, "final": {**VECTOR["final"], "p": "0x00"}},
            "final.p must be an integer",
        ),
    ],
)
def test_malformed_inline_records_report_source_and_record_context(record, message):
    with pytest.raises(VectorValidationError) as error:
        parse_vector_record(record, source="inline.json", index=7)

    assert str(error.value) == f"inline.json: record 7: {message}"
