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


@pytest.mark.parametrize("opcode", [0x0B, 0x2B])
def test_anc_and_updates_negative_zero_and_carry(opcode):
    state = CPUState(accumulator=0xC0)
    cpu = CPU(Bus({0: opcode, 1: 0x81}), state=state)

    result = cpu.step()

    assert result.cycles == 2
    assert state.a.value == 0x80
    assert state.status.negative is True
    assert state.status.zero is False
    assert state.status.carry is True


def test_alr_ands_then_logically_shifts_with_bit_zero_carry():
    state = CPUState(accumulator=0xCF)
    cpu = CPU(Bus({0: 0x4B, 1: 0x0F}), state=state)

    result = cpu.step()

    assert result.cycles == 2
    assert state.a.value == 0x07
    assert state.status.carry is True
    assert state.status.negative is False
    assert state.status.zero is False


@pytest.mark.parametrize(
    ("decimal", "accumulator", "operand", "carry", "expected", "flags"),
    [
        (False, 0xFF, 0xFF, False, 0x7F, (False, False, True)),
        (True, 0x30, 0x39, True, 0x98, (True, False, False)),
    ],
)
def test_arr_binary_and_decimal_results_and_flags(
    decimal, accumulator, operand, carry, expected, flags
):
    state = CPUState(
        accumulator=accumulator,
        status=StatusFlags(decimal=decimal, carry=carry),
    )
    cpu = CPU(Bus({0: 0x6B, 1: operand}), state=state)

    result = cpu.step()

    assert result.cycles == 2
    assert state.a.value == expected
    assert (state.status.negative, state.status.overflow, state.status.carry) == flags
    assert state.status.zero is (expected == 0)


def test_sbx_subtracts_immediate_from_a_and_x_intersection():
    state = CPUState(accumulator=0x0F, index=IndexRegisters(x=0x07))
    cpu = CPU(Bus({0: 0xCB, 1: 0x03}), state=state)

    result = cpu.step()

    assert result.cycles == 2
    assert state.x.value == 0x04
    assert state.status.carry is True
    assert state.status.zero is False
    assert state.status.negative is False


def test_usbc_is_decimal_sbc_alias():
    state = CPUState(
        accumulator=0x50,
        status=StatusFlags(decimal=True, carry=True),
    )
    cpu = CPU(Bus({0: 0xEB, 1: 0x01}), state=state)

    result = cpu.step()

    assert result.cycles == 2
    assert state.a.value == 0x49
    assert state.status.carry is True


def test_stable_immediate_illegal_opcode_catalog_entries():
    assert {
        opcode: (OFFICIAL_OPCODES[opcode].mnemonic, OFFICIAL_OPCODES[opcode].cycles)
        for opcode in (0x0B, 0x2B, 0x4B, 0x6B, 0xCB, 0xEB)
    } == {
        0x0B: ("ANC", 2),
        0x2B: ("ANC", 2),
        0x4B: ("ALR", 2),
        0x6B: ("ARR", 2),
        0xCB: ("SBX", 2),
        0xEB: ("USBC", 2),
    }
