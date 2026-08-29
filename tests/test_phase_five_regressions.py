import pytest

from sixfiveohtwo import CPU, CPUState, IndexRegisters
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
    ("opcode", "mnemonic", "mode", "cycles"),
    [
        (0x8B, "ANE", "IMMEDIATE", 2),
        (0xAB, "LXA", "IMMEDIATE", 2),
        (0x9B, "TAS", "ABSOLUTE_Y", 5),
        (0xBB, "LAS", "ABSOLUTE_Y", 4),
        (0x93, "SHA", "INDIRECT_INDEXED", 6),
        (0x9F, "SHA", "ABSOLUTE_Y", 5),
        (0x9E, "SHX", "ABSOLUTE_Y", 5),
        (0x9C, "SHY", "ABSOLUTE_X", 5),
    ],
)
def test_high_byte_opcode_catalog(opcode, mnemonic, mode, cycles):
    definition = OFFICIAL_OPCODES[opcode]
    assert (
        definition.mnemonic,
        definition.addressing_mode.name,
        definition.cycles,
    ) == (mnemonic, mode, cycles)


def test_ane_and_lxa_use_the_deterministic_unstable_mask_and_update_nz():
    bus = Bus({0: 0x8B, 1: 0x11})
    state = CPUState(accumulator=0x40)
    assert CPU(bus, state=state).step().cycles == 2
    assert state.a.value == 0x00
    assert state.status.zero is True
    assert state.status.negative is False

    bus = Bus({0: 0xAB, 1: 0xF1})
    state = CPUState(accumulator=0x10)
    assert CPU(bus, state=state).step().cycles == 2
    assert state.a.value == state.x.value == 0xF0
    assert state.status.negative is True
    assert state.status.zero is False


def test_tas_sets_stack_pointer_and_stores_high_byte_masked_value():
    bus = Bus({0: 0x9B, 1: 0xFF, 2: 0x12})
    state = CPUState(accumulator=0xF3, index=IndexRegisters(x=0x0F, y=1))
    result = CPU(bus, state=state).step()
    assert result.cycles == 5
    assert state.sp.value == 0x03
    assert bus.values[0x0300] == 0x03


def test_las_loads_sp_intersection_into_a_x_and_sp_across_page():
    bus = Bus({0: 0xBB, 1: 0xFF, 2: 0x12, 0x1200: 0xAA, 0x1300: 0x3C})
    state = CPUState(stack_pointer=0xF0, index=IndexRegisters(y=1))
    result = CPU(bus, state=state).step()
    assert result.cycles == 5
    assert (state.a.value, state.x.value, state.sp.value) == (0x30, 0x30, 0x30)
    assert state.status.negative is False
    assert state.status.zero is False
    assert ("read", 0x1200) in bus.operations


@pytest.mark.parametrize(
    ("opcode", "index", "register", "expected"),
    [(0x9E, 1, "x", 0x14), (0x9C, 1, "y", 0x14)],
)
def test_shx_and_shy_use_effective_address_high_byte_plus_one(
    opcode, index, register, expected
):
    bus = Bus({0: opcode, 1: 0xFF, 2: 0x12, 0x1200: 0x00})
    state = CPUState(index=IndexRegisters(x=index, y=index if opcode == 0x9E else 0xF7))
    if opcode == 0x9E:
        state.x.value = 0xF7
    result = CPU(bus, state=state).step()
    assert result.cycles == 5
    assert bus.values[0x1300] == 0x13
    assert ("read", 0x1200) in bus.operations


def test_sha_indirect_and_absolute_y_store_register_intersection_and_dummy_read():
    for opcode, operand, setup in (
        (0x93, (0x20,), {0x20: 0xFF, 0x21: 0x12}),
        (0x9F, (0xFF, 0x12), {}),
    ):
        bus = Bus({0: opcode, **dict(enumerate(operand, start=1)), **setup, 0x1200: 0})
        state = CPUState(accumulator=0xF7, index=IndexRegisters(x=0x3F, y=1))
        result = CPU(bus, state=state).step()
        assert result.cycles == (6 if opcode == 0x93 else 5)
        assert bus.values[0x1300] == 0x13
        assert ("read", 0x1200) in bus.operations
