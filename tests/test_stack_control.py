from sixfiveohtwo import CPU, CPUState, StatusFlags


class Bus:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def read_byte(self, address):
        return self.values.get(address, 0)

    def write_byte(self, address, value):
        self.values[address] = value


def test_pha_pla_move_a_through_stack_and_update_nz():
    bus = Bus({0: 0x48, 1: 0xA9, 2: 0x00, 3: 0x68})
    state = CPUState(program_counter=0, accumulator=0x80, stack_pointer=0x00)
    cpu = CPU(bus, state=state)

    assert cpu.step().cycles == 3
    assert state.sp.value == 0xFF
    assert bus.values[0x0100] == 0x80
    cpu.step()
    assert state.a.value == 0
    cpu.step()

    assert state.a.value == 0x80
    assert state.status.negative is True
    assert state.status.zero is False
    assert state.sp.value == 0x00


def test_php_plp_preserve_status_and_discard_stack_b_bit():
    bus = Bus({0: 0x08, 1: 0x28})
    status = StatusFlags(
        negative=True, overflow=True, decimal=True, interrupt_disable=True, carry=True
    )
    state = CPUState(program_counter=0, stack_pointer=0xFD, status=status)
    cpu = CPU(bus, state=state)

    assert cpu.step().cycles == 3
    assert bus.values[0x01FD] == 0xFD
    state.status = StatusFlags()
    assert cpu.step().cycles == 4
    assert state.status == status
    assert state.sp.value == 0xFD


def test_jsr_rts_use_next_instruction_minus_one_and_support_nested_calls():
    bus = Bus(
        {
            0x8000: 0x20,
            0x8001: 0x00,
            0x8002: 0x90,
            0x9000: 0x20,
            0x9001: 0x00,
            0x9002: 0xA0,
            0x9003: 0x60,
            0xA000: 0x60,
        }
    )
    state = CPUState(program_counter=0x8000, stack_pointer=0xFD)
    cpu = CPU(bus, state=state)

    assert cpu.step().cycles == 6
    assert state.pc.value == 0x9000
    assert state.sp.value == 0xFB
    assert bus.values[0x01FD] == 0x80
    assert bus.values[0x01FC] == 0x02
    cpu.step()
    assert state.pc.value == 0xA000
    assert state.sp.value == 0xF9
    cpu.step()
    assert state.pc.value == 0x9003
    assert state.sp.value == 0xFB
    cpu.step()
    assert state.pc.value == 0x8003
    assert state.sp.value == 0xFD


def test_jmp_indirect_uses_nmos_pointer_page_wrap():
    bus = Bus({0: 0x6C, 1: 0xFF, 2: 0x12, 0x12FF: 0x34, 0x1200: 0x56})
    cpu = CPU(bus, state=CPUState(program_counter=0))

    result = cpu.step()

    assert result.cycles == 5
    assert cpu.state.pc.value == 0x5634


def test_brk_fetches_padding_byte_pushes_return_address_and_uses_irq_vector():
    bus = Bus({0x1000: 0x00, 0x1001: 0xEA, 0xFFFE: 0x00, 0xFFFF: 0x40})
    state = CPUState(program_counter=0x1000, stack_pointer=0xFD)
    cpu = CPU(bus, state=state)

    result = cpu.step()

    assert result.cycles == 7
    assert result.vector == 0x4000
    assert state.pc.value == 0x4000
    assert state.sp.value == 0xFA
    assert bus.values[0x01FD] == 0x10
    assert bus.values[0x01FC] == 0x02
    assert bus.values[0x01FB] & 0x30 == 0x30
    assert state.status.interrupt_disable is True


def test_rti_restores_pc_and_persistent_flags_without_restoring_b():
    bus = Bus({0: 0x40, 0x01FB: 0xFF, 0x01FC: 0x34, 0x01FD: 0x12})
    state = CPUState(program_counter=0, stack_pointer=0xFA)
    cpu = CPU(bus, state=state)

    result = cpu.step()

    assert result.cycles == 6
    assert state.pc.value == 0x1234
    assert state.sp.value == 0xFD
    assert state.status == StatusFlags(
        negative=True,
        overflow=True,
        decimal=True,
        interrupt_disable=True,
        zero=True,
        carry=True,
    )
    assert state.status.to_byte() & 0x10 == 0
