import pytest

from sixfiveohtwo import CPU, CPUState, IndexRegisters
from sixfiveohtwo.core import AddressingMode, decode_opcode


class LoggingBus:
    def __init__(self, values):
        self.values = dict(values)
        self.operations = []

    def read_byte(self, address):
        self.operations.append(("read", address))
        return self.values.get(address, 0)

    def write_byte(self, address, value):
        self.operations.append(("write", address, value))
        self.values[address] = value


@pytest.mark.parametrize(
    ("opcode", "mode", "cycles"),
    [
        (opcode, AddressingMode.IMPLIED, 2)
        for opcode in (0x1A, 0x3A, 0x5A, 0x7A, 0xDA, 0xFA)
    ]
    + [
        (opcode, AddressingMode.IMMEDIATE, 2)
        for opcode in (0x80, 0x82, 0x89, 0xC2, 0xE2)
    ]
    + [
        (opcode, mode, cycles)
        for opcode, mode, cycles in (
            (0x04, AddressingMode.ZERO_PAGE, 3),
            (0x0C, AddressingMode.ABSOLUTE, 4),
            (0x14, AddressingMode.ZERO_PAGE_X, 4),
            (0x1C, AddressingMode.ABSOLUTE_X, 4),
            (0xFC, AddressingMode.ABSOLUTE_X, 4),
        )
    ],
)
def test_undocumented_nop_metadata_and_dummy_reads(opcode, mode, cycles):
    bus = LoggingBus({0x1000: opcode, 0x1001: 0x20, 0x1002: 0x10, 0x1003: 0xA5})
    state = CPUState(program_counter=0x1000, index=IndexRegisters(x=1))
    result = CPU(bus, state=state).step()

    assert decode_opcode(opcode).addressing_mode is mode
    assert result.cycles == cycles
    assert state.pc.value == 0x1000 + decode_opcode(opcode).length
    assert bus.operations[0] == ("read", 0x1000)
    expected_reads = decode_opcode(opcode).length + int(
        mode not in {AddressingMode.IMPLIED, AddressingMode.IMMEDIATE}
    )
    assert len(bus.operations) == expected_reads


@pytest.mark.parametrize(
    "opcode",
    [0x02, 0x12, 0x22, 0x32, 0x42, 0x52, 0x62, 0x72, 0x92, 0xB2, 0xD2, 0xF2],
)
def test_jam_halts_and_repeats_without_further_bus_activity(opcode):
    bus = LoggingBus({0x2000: opcode, 0x2001: 0xA5})
    state = CPUState(program_counter=0x2000, cycles=7)
    cpu = CPU(bus, state=state)

    first = cpu.step()
    operation_count = len(bus.operations)
    second = cpu.step()

    assert first.cycles == 11
    assert first.total_cycles == 18
    assert cpu.halted
    assert state.pc.value == 0x2001
    assert second.cycles == 0
    assert state.cycles == 18
    assert len(bus.operations) == operation_count
