import pytest

from sixfiveohtwo import CPU, AddressingMode, CPUState, IndexRegisters


class Bus:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def read_byte(self, address):
        return self.values.get(address, 0)

    def write_byte(self, address, value):
        self.values[address] = value


@pytest.mark.parametrize(
    ("mode", "operand", "state", "values", "address", "value", "crossed"),
    [
        (
            AddressingMode.ZERO_PAGE_X,
            (0xFF,),
            CPUState(index=IndexRegisters(x=2)),
            {1: 0xA1},
            1,
            0xA1,
            False,
        ),
        (
            AddressingMode.ZERO_PAGE_Y,
            (0xFF,),
            CPUState(index=IndexRegisters(y=2)),
            {1: 0xA2},
            1,
            0xA2,
            False,
        ),
        (
            AddressingMode.ABSOLUTE_X,
            (0xFF, 0x20),
            CPUState(index=IndexRegisters(x=1)),
            {0x2100: 0xA3},
            0x2100,
            0xA3,
            True,
        ),
        (
            AddressingMode.INDIRECT_INDEXED,
            (0xFF,),
            CPUState(index=IndexRegisters(y=1)),
            {0xFF: 0xFF, 0: 0x20, 0x2100: 0xA4},
            0x2100,
            0xA4,
            True,
        ),
    ],
)
def test_addressing_resolves_operands_and_reports_crossing(
    mode, operand, state, values, address, value, crossed
):
    start = 0x1000
    values.update(dict(enumerate(operand, start=start)))
    state.pc.value = start
    result = CPU(Bus(values), state=state).resolve_addressing(mode)

    assert result.address == address
    assert result.value == value
    assert result.page_crossed is crossed


def test_indirect_jmp_uses_nmos_same_page_high_byte_wrap():
    bus = Bus({0x1000: 0xFF, 0x1001: 0x12, 0x12FF: 0x34, 0x1200: 0x56, 0x5634: 0xB5})

    result = CPU(bus, state=CPUState(program_counter=0x1000)).resolve_addressing(
        AddressingMode.INDIRECT
    )

    assert result.address == 0x5634
    assert result.value == 0xB5


def test_relative_resolution_wraps_target_and_preserves_sequential_pc():
    cpu = CPU(Bus({0xFFFF: 0x02}), state=CPUState(program_counter=0xFFFF))

    result = cpu.resolve_addressing(AddressingMode.RELATIVE)

    assert result.address == 2
    assert result.value == 2
    assert result.sequential_pc == 0
    assert cpu.state.pc.value == 0
