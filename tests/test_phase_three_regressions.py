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


def test_instruction_sequence_wraps_program_counter_at_top_of_memory():
    bus = Bus({0xFFFE: 0xA9, 0xFFFF: 0x42, 0x0000: 0x85, 0x0001: 0x10})
    state = CPUState(program_counter=0xFFFE)
    cpu = CPU(bus, state=state)

    first = cpu.step()
    second = cpu.step()

    assert first.cycles == 2
    assert second.cycles == 3
    assert state.a.value == 0x42
    assert state.pc.value == 0x0002
    assert bus.values[0x0010] == 0x42


def test_instruction_sequence_wraps_zero_page_indexed_addressing():
    bus = Bus({0x0100: 0xA2, 0x0101: 0x03, 0x0102: 0xB5, 0x0103: 0xFE, 0x0001: 0x7E})
    state = CPUState(program_counter=0x0100, index=IndexRegisters())
    cpu = CPU(bus, state=state)

    load_x = cpu.step()
    load_a = cpu.step()

    assert load_x.cycles == 2
    assert load_a.cycles == 4
    assert state.x.value == 0x03
    assert state.a.value == 0x7E
    assert state.pc.value == 0x0104


def test_indexed_read_page_cross_penalty_differs_from_indexed_store():
    bus = Bus(
        {
            0x00: 0xA2,
            0x01: 0x01,
            0x02: 0xBD,
            0x03: 0xFF,
            0x04: 0x20,
            0x05: 0x9D,
            0x06: 0xFF,
            0x07: 0x20,
            0x2100: 0xA5,
        }
    )
    cpu = CPU(bus, state=CPUState(index=IndexRegisters()))

    load_x = cpu.step()
    indexed_read = cpu.step()
    indexed_store = cpu.step()

    assert (load_x.cycles, indexed_read.cycles, indexed_store.cycles) == (2, 5, 5)
    assert cpu.state.cycles == 12
    assert cpu.state.a.value == 0xA5
    assert bus.values[0x2100] == 0xA5


def test_read_modify_write_sequence_preserves_old_and_new_memory_state():
    address = 0x20
    bus = Bus(
        {0: 0xA9, 1: 0x81, 2: 0x06, 3: address, 4: 0x26, 5: address, address: 0x81}
    )
    cpu = CPU(bus, state=CPUState())

    load = cpu.step()
    arithmetic_shift = cpu.step()
    rotate = cpu.step()

    assert (load.cycles, arithmetic_shift.cycles, rotate.cycles) == (2, 5, 5)
    assert bus.values[address] == 0x05
    assert bus.operations[4:7] == [
        ("read", address),
        ("write", address, 0x81),
        ("write", address, 0x02),
    ]
    assert bus.operations[9:] == [
        ("read", address),
        ("write", address, 0x02),
        ("write", address, 0x05),
    ]
    assert cpu.state.status.carry is False
    assert cpu.state.status.zero is False


def test_load_and_store_families_preserve_unrelated_status_bits():
    bus = Bus({0: 0x38, 1: 0xB8, 2: 0xF8, 3: 0xA9, 4: 0x80, 5: 0x85, 6: 0x10})
    state = CPUState(status=StatusFlags(overflow=True, interrupt_disable=True))
    cpu = CPU(bus, state=state)

    cpu.step()  # SEC
    cpu.step()  # CLV
    cpu.step()  # SED
    cpu.step()  # LDA #$80
    cpu.step()  # STA $10

    assert state.status == StatusFlags(
        negative=True,
        decimal=True,
        interrupt_disable=True,
        carry=True,
    )
    assert bus.values[0x10] == 0x80


def test_subroutine_stack_and_return_sequence_restores_accumulator_and_pc():
    bus = Bus(
        {
            0x0000: 0x20,
            0x0001: 0x06,
            0x0002: 0x00,
            0x0003: 0xA2,
            0x0004: 0x03,
            0x0006: 0x48,
            0x0007: 0xA9,
            0x0008: 0x00,
            0x0009: 0x68,
            0x000A: 0x60,
        }
    )
    state = CPUState(accumulator=0xA5, stack_pointer=0xFD)
    cpu = CPU(bus, state=state)

    steps = [cpu.step() for _ in range(5)]

    assert [step.cycles for step in steps] == [6, 3, 2, 4, 6]
    assert state.a.value == 0xA5
    assert state.x.value == 0
    assert state.pc.value == 0x0003
    assert state.sp.value == 0xFD
    assert state.cycles == 21


def test_decimal_adc_sets_carry_used_by_following_branch():
    bus = Bus(
        {
            0x0000: 0xF8,  # SED
            0x0001: 0x18,  # CLC
            0x0002: 0xA9,
            0x0003: 0x45,
            0x0004: 0x69,
            0x0005: 0x55,
            0x0006: 0xB0,
            0x0007: 0x04,
            0x0008: 0xA9,  # skipped by BCS
            0x0009: 0xFF,
            0x000C: 0xA9,
            0x000D: 0x42,
        }
    )
    state = CPUState()
    cpu = CPU(bus, state=state)

    steps = [cpu.step() for _ in range(6)]

    assert [step.cycles for step in steps] == [2, 2, 2, 2, 3, 2]
    assert state.a.value == 0x42
    assert state.pc.value == 0x000E
    assert state.status.carry is True
    assert state.status.decimal is True


@pytest.mark.parametrize(
    ("mnemonic", "opcodes"),
    [
        ("SAX", (0x83, 0x87, 0x8F, 0x97)),
        ("LAX", (0xA3, 0xA7, 0xAF, 0xB3, 0xB7, 0xBF)),
        ("DCP", (0xC3, 0xC7, 0xCF, 0xD3, 0xD7, 0xDB, 0xDF)),
        ("ISC", (0xE3, 0xE7, 0xEF, 0xF3, 0xF7, 0xFB, 0xFF)),
    ],
)
def test_load_store_compare_catalog_contains_all_composite_encodings(mnemonic, opcodes):
    definitions = [
        definition
        for definition in OFFICIAL_OPCODES.values()
        if definition.mnemonic == mnemonic
    ]
    assert {definition.opcode for definition in definitions} == set(opcodes)


def test_sax_stores_a_and_x_intersection_without_changing_flags():
    state = CPUState(
        accumulator=0xCD,
        index=IndexRegisters(x=0x6F),
        status=StatusFlags(negative=True, overflow=True, decimal=True, carry=True),
    )
    bus = Bus({0: 0x97, 1: 0x20})

    result = CPU(bus, state=state).step()

    assert result.cycles == 4
    assert bus.values[0x20] == 0x4D
    assert state.status == StatusFlags(
        negative=True, overflow=True, decimal=True, carry=True
    )


def test_lax_indexed_indirect_loads_a_and_x_and_updates_nz():
    bus = Bus({0: 0xB3, 1: 0x20, 0x20: 0x00, 0x21: 0x21, 0x2101: 0x80})
    state = CPUState(index=IndexRegisters(y=1))

    result = CPU(bus, state=state).step()

    assert result.cycles == 5
    assert state.a.value == state.x.value == 0x80
    assert state.status.negative is True
    assert state.status.zero is False


@pytest.mark.parametrize(
    ("opcode", "initial", "expected", "cycles"),
    [(0xC7, 0x00, 0xFF, 5), (0xDF, 0x00, 0xFF, 7)],
)
def test_dcp_decrements_memory_then_compares_without_changing_accumulator(
    opcode, initial, expected, cycles
):
    address_bytes = (0x20,) if opcode == 0xC7 else (0xFF, 0x20)
    address = 0x20 if opcode == 0xC7 else 0x2100
    bus = Bus({0: opcode, **dict(enumerate(address_bytes, start=1)), address: initial})
    state = CPUState(accumulator=0xFF, index=IndexRegisters(x=1))

    result = CPU(bus, state=state).step()

    assert result.cycles == cycles
    assert state.a.value == 0xFF
    assert bus.values[address] == expected
    assert bus.operations[-2:] == [
        ("write", address, initial),
        ("write", address, expected),
    ]
    assert state.status.carry is True
    assert state.status.zero is True


def test_isc_increments_memory_then_subtracts_with_sbc_flags():
    bus = Bus({0: 0xE7, 1: 0x20, 0x20: 0x0F})
    state = CPUState(accumulator=0x10, status=StatusFlags(carry=True))

    result = CPU(bus, state=state).step()

    assert result.cycles == 5
    assert bus.values[0x20] == 0x10
    assert state.a.value == 0x00
    assert state.status.carry is True
    assert state.status.zero is True
