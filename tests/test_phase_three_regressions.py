from sixfiveohtwo import CPU, CPUState, IndexRegisters, StatusFlags


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
    assert state.status.zero is False
