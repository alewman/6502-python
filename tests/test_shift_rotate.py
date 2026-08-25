import pytest

from sixfiveohtwo import CPU, CPUState, IndexRegisters, StatusFlags
from sixfiveohtwo.core import OFFICIAL_OPCODES


class Bus:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.operations = []

    def read_byte(self, address):
        self.operations.append(("read", address))
        return self.values.get(address, 0)

    def write_byte(self, address, value):
        self.operations.append(("write", address, value))
        self.values[address] = value


SHIFT_OPCODES = {
    "ASL": (0x0A, 0x06, 0x16, 0x0E, 0x1E),
    "LSR": (0x4A, 0x46, 0x56, 0x4E, 0x5E),
    "ROL": (0x2A, 0x26, 0x36, 0x2E, 0x3E),
    "ROR": (0x6A, 0x66, 0x76, 0x6E, 0x7E),
}


@pytest.mark.parametrize("mnemonic,opcodes", SHIFT_OPCODES.items())
def test_shift_rotate_catalog_contains_all_official_encodings(mnemonic, opcodes):
    definitions = [
        definition
        for definition in OFFICIAL_OPCODES.values()
        if definition.mnemonic == mnemonic
    ]
    assert {definition.opcode for definition in definitions} == set(opcodes)


@pytest.mark.parametrize(
    "mnemonic,value,carry_in,expected,carry_out",
    [
        ("ASL", 0x80, False, 0x00, True),
        ("ASL", 0x40, True, 0x80, False),
        ("LSR", 0x01, False, 0x00, True),
        ("LSR", 0x80, True, 0x40, False),
        ("ROL", 0x80, False, 0x00, True),
        ("ROL", 0x40, True, 0x81, False),
        ("ROR", 0x01, False, 0x00, True),
        ("ROR", 0x80, True, 0xC0, False),
    ],
)
def test_accumulator_shifts_consume_and_produce_carry_and_update_nz(
    mnemonic, value, carry_in, expected, carry_out
):
    opcode = SHIFT_OPCODES[mnemonic][0]
    state = CPUState(
        accumulator=value,
        status=StatusFlags(
            negative=True,
            overflow=True,
            decimal=True,
            interrupt_disable=True,
            zero=False,
            carry=carry_in,
        ),
    )

    result = CPU(Bus({0: opcode}), state=state).step()

    assert result.cycles == 2
    assert state.a.value == expected
    assert state.status.negative is bool(expected & 0x80)
    assert state.status.zero is (expected == 0)
    assert state.status.carry is carry_out
    assert state.status.overflow is True
    assert state.status.decimal is True
    assert state.status.interrupt_disable is True


@pytest.mark.parametrize(
    "mnemonic,value,carry_in,expected,carry_out",
    [
        ("ASL", 0x81, False, 0x02, True),
        ("LSR", 0x02, True, 0x01, False),
        ("ROL", 0x01, True, 0x03, False),
        ("ROR", 0x02, True, 0x81, False),
    ],
)
def test_memory_shifts_are_read_modify_write_and_use_memory_cycles(
    mnemonic, value, carry_in, expected, carry_out
):
    opcode = SHIFT_OPCODES[mnemonic][1]
    address = 0x20
    bus = Bus({0: opcode, 1: address, address: value})
    state = CPUState(status=StatusFlags(carry=carry_in))

    result = CPU(bus, state=state).step()

    assert result.cycles == 5
    assert bus.values[address] == expected
    assert bus.operations[-2:] == [
        ("write", address, value),
        ("write", address, expected),
    ]
    assert state.status.carry is carry_out
    assert state.status.negative is bool(expected & 0x80)
    assert state.status.zero is (expected == 0)


@pytest.mark.parametrize("opcode", [0x1E, 0x5E, 0x3E, 0x7E])
def test_absolute_x_shift_timing_is_seven_cycles_even_on_page_cross(opcode):
    bus = Bus({0: opcode, 1: 0xFF, 2: 0x20, 0x2100: 0x01})
    state = CPUState(index=IndexRegisters(x=1))

    result = CPU(bus, state=state).step()

    assert result.cycles == 7
    assert bus.values[0x2100] in (0x00, 0x02)
