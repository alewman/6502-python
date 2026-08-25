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


@pytest.mark.parametrize(
    "mnemonic,opcodes,modes",
    [
        ("CMP", (0xC9, 0xC5, 0xD5, 0xCD, 0xDD, 0xD9, 0xC1, 0xD1), 8),
        ("CPX", (0xE0, 0xE4, 0xEC), 3),
        ("CPY", (0xC0, 0xC4, 0xCC), 3),
    ],
)
def test_compare_catalog_contains_all_legal_modes(mnemonic, opcodes, modes):
    definitions = [
        definition
        for definition in OFFICIAL_OPCODES.values()
        if definition.mnemonic == mnemonic
    ]
    assert len(definitions) == modes
    assert {definition.opcode for definition in definitions} == set(opcodes)


@pytest.mark.parametrize(
    "register,opcode,expected_cycles",
    [("a", 0xC9, 2), ("x", 0xE0, 2), ("y", 0xC0, 2)],
)
def test_compare_sets_borrow_flags_from_eight_bit_subtraction_and_preserves_v(
    register, opcode, expected_cycles
):
    state = CPUState(
        accumulator=0x00,
        index=IndexRegisters(x=0x00, y=0x00),
        status=StatusFlags(negative=False, overflow=True, zero=False, carry=True),
    )
    cpu = CPU(Bus({0: opcode, 1: 0x01}), state=state)

    result = cpu.step()

    assert result.cycles == expected_cycles
    assert state.status == StatusFlags(
        negative=True, overflow=True, zero=False, carry=False
    )


@pytest.mark.parametrize(
    "opcode,value,expected", [(0xC9, 0x40, 0x00), (0xC9, 0x3F, 0x01)]
)
def test_cmp_carry_and_zero_boundaries(opcode, value, expected):
    state = CPUState(accumulator=0x40)
    cpu = CPU(Bus({0: opcode, 1: value}), state=state)

    cpu.step()

    assert state.status.carry is (value <= 0x40)
    assert state.status.zero is (expected == 0)


@pytest.mark.parametrize(
    "opcode,address,operand,initial,index,cycles",
    [
        (0xE6, 0x20, (0x20,), 0xFF, (0, 0), 5),
        (0xF6, 0x00, (0xFF,), 0xFF, (1, 0), 6),
        (0xEE, 0x1234, (0x34, 0x12), 0xFF, (0, 0), 6),
        (0xFE, 0x2100, (0xFF, 0x20), 0xFF, (1, 0), 7),
        (0xC6, 0x20, (0x20,), 0x00, (0, 0), 5),
        (0xD6, 0x01, (0x00,), 0x00, (1, 0), 6),
        (0xCE, 0x1234, (0x34, 0x12), 0x00, (0, 0), 6),
        (0xDE, 0x2101, (0x00, 0x21), 0x00, (1, 0), 7),
    ],
)
def test_memory_inc_dec_wraps_updates_nz_and_performs_read_modify_write(
    opcode, address, operand, initial, index, cycles
):
    values = {
        0x100: opcode,
        **dict(enumerate(operand, start=0x101)),
        address: initial,
    }
    state = CPUState(
        program_counter=0x100, index=IndexRegisters(x=index[0], y=index[1])
    )
    cpu = CPU(Bus(values), state=state)

    result = cpu.step()

    expected = (initial + (1 if opcode in (0xE6, 0xF6, 0xEE, 0xFE) else -1)) & 0xFF
    assert result.cycles == cycles
    assert cpu.memory.values[address] == expected
    assert cpu.memory.operations[-2:] == [
        ("write", address, initial),
        ("write", address, expected),
    ]
    assert state.status.zero is (expected == 0)
    assert state.status.negative is bool(expected & 0x80)


@pytest.mark.parametrize(
    "opcode,register,initial,expected",
    [
        (0xE8, "x", 0xFF, 0x00),
        (0xC8, "y", 0xFF, 0x00),
        (0xCA, "x", 0x00, 0xFF),
        (0x88, "y", 0x00, 0xFF),
    ],
)
def test_register_inc_dec_wraps_updates_nz_and_preserves_other_flags(
    opcode, register, initial, expected
):
    state = CPUState(
        index=IndexRegisters(
            x=initial if register == "x" else 0,
            y=initial if register == "y" else 0,
        ),
        status=StatusFlags(
            negative=False, overflow=True, zero=False, carry=True, decimal=True
        ),
    )
    cpu = CPU(Bus({0: opcode}), state=state)

    result = cpu.step()

    assert result.cycles == 2
    assert getattr(state, register).value == expected
    assert state.status.overflow is True
    assert state.status.carry is True
    assert state.status.decimal is True
    assert state.status.negative is (expected & 0x80 != 0)
    assert state.status.zero is (expected == 0)
