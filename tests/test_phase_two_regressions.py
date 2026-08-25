import pytest

from sixfiveohtwo import (
    CPU,
    AddressingMode,
    AddressingResult,
    CPUState,
    IndexRegisters,
    InterruptBoundary,
    InterruptLines,
    IRQStep,
    NMIStep,
    ResetStep,
    StatusFlags,
)


class Bus:
    """Independent sparse host bus used as the regression suite's oracle surface."""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def read_byte(self, address):
        return self.values.get(address, 0)

    def write_byte(self, address, value):
        self.values[address] = value


@pytest.mark.parametrize(
    ("mode", "operand", "state", "values", "expected"),
    [
        (
            AddressingMode.ACCUMULATOR,
            (),
            CPUState(accumulator=0xA5),
            {},
            AddressingResult(AddressingMode.ACCUMULATOR, None, 0xA5),
        ),
        (
            AddressingMode.IMPLIED,
            (),
            CPUState(),
            {},
            AddressingResult(AddressingMode.IMPLIED, None, None),
        ),
        (
            AddressingMode.IMMEDIATE,
            (0xA5,),
            CPUState(),
            {},
            AddressingResult(AddressingMode.IMMEDIATE, None, 0xA5),
        ),
        (
            AddressingMode.ZERO_PAGE,
            (0xFE,),
            CPUState(),
            {0x00FE: 0x11},
            AddressingResult(AddressingMode.ZERO_PAGE, 0xFE, 0x11),
        ),
        (
            AddressingMode.ZERO_PAGE_X,
            (0xFE,),
            CPUState(index=IndexRegisters(x=3)),
            {0x0001: 0x12},
            AddressingResult(AddressingMode.ZERO_PAGE_X, 0x01, 0x12),
        ),
        (
            AddressingMode.ZERO_PAGE_Y,
            (0xFE,),
            CPUState(index=IndexRegisters(y=3)),
            {0x0001: 0x13},
            AddressingResult(AddressingMode.ZERO_PAGE_Y, 0x01, 0x13),
        ),
        (
            AddressingMode.ABSOLUTE,
            (0x34, 0x12),
            CPUState(),
            {0x1234: 0x14},
            AddressingResult(AddressingMode.ABSOLUTE, 0x1234, 0x14),
        ),
        (
            AddressingMode.ABSOLUTE_X,
            (0xFF, 0xFF),
            CPUState(program_counter=0x1000, index=IndexRegisters(x=1)),
            {0x0000: 0x15},
            AddressingResult(AddressingMode.ABSOLUTE_X, 0x0000, 0x15, True),
        ),
        (
            AddressingMode.ABSOLUTE_Y,
            (0xFF, 0x20),
            CPUState(index=IndexRegisters(y=1)),
            {0x2100: 0x16},
            AddressingResult(AddressingMode.ABSOLUTE_Y, 0x2100, 0x16, True),
        ),
        (
            AddressingMode.INDIRECT,
            (0xFF, 0x12),
            CPUState(),
            {0x12FF: 0x34, 0x1200: 0x56, 0x5634: 0x17},
            AddressingResult(AddressingMode.INDIRECT, 0x5634, 0x17),
        ),
        (
            AddressingMode.INDEXED_INDIRECT,
            (0xFF,),
            CPUState(program_counter=0x1000, index=IndexRegisters(x=1)),
            {0x0000: 0x34, 0x0001: 0x12, 0x1234: 0x18},
            AddressingResult(AddressingMode.INDEXED_INDIRECT, 0x1234, 0x18),
        ),
        (
            AddressingMode.INDIRECT_INDEXED,
            (0xFF,),
            CPUState(program_counter=0x1000, index=IndexRegisters(y=1)),
            {0x00FF: 0xFF, 0x0000: 0x20, 0x2100: 0x19},
            AddressingResult(AddressingMode.INDIRECT_INDEXED, 0x2100, 0x19, True),
        ),
        (
            AddressingMode.RELATIVE,
            (0xFB,),
            CPUState(program_counter=0x1000),
            {},
            AddressingResult(AddressingMode.RELATIVE, 0x0FFC, -5, True, 0x1001),
        ),
    ],
)
def test_phase_two_addressing_modes_have_independent_boundary_oracles(
    mode, operand, state, values, expected
):
    values = dict(values)
    start_pc = state.pc.value
    values.update(dict(enumerate(operand, start=start_pc)))
    cpu = CPU(Bus(values), state=state)

    assert cpu.resolve_addressing(mode) == expected
    if mode is AddressingMode.RELATIVE:
        assert cpu.state.pc.value == expected.sequential_pc
    else:
        assert cpu.state.pc.value == (start_pc + len(operand)) & 0xFFFF


@pytest.mark.parametrize(
    ("reset", "irq", "nmi", "interrupt_disable", "result_type", "vector"),
    [
        (True, True, True, False, ResetStep, 0x1000),
        (False, True, True, False, NMIStep, 0x2000),
        (False, True, False, False, IRQStep, 0x3000),
    ],
)
def test_boundary_priority_selects_reset_then_nmi_then_unmasked_irq(
    reset, irq, nmi, interrupt_disable, result_type, vector
):
    bus = Bus(
        {
            0xFFFC: 0x00,
            0xFFFD: 0x10,
            0xFFFA: 0x00,
            0xFFFB: 0x20,
            0xFFFE: 0x00,
            0xFFFF: 0x30,
        }
    )
    lines = InterruptLines()
    cpu = CPU(
        bus,
        lines=lines,
        state=CPUState(status=StatusFlags(interrupt_disable=interrupt_disable)),
    )
    lines.set_reset(reset)
    lines.set_irq(irq)
    if nmi:
        lines.signal_nmi()

    result = cpu.step()

    assert isinstance(result, result_type)
    assert result.vector == vector
    assert result.boundary == InterruptBoundary(reset, irq, nmi)


def test_masked_irq_is_sampled_but_deferred_until_interrupts_are_enabled():
    bus = Bus({0: 0xEA, 0xFFFE: 0x00, 0xFFFF: 0x40})
    cpu = CPU(bus, state=CPUState(status=StatusFlags(interrupt_disable=True)))
    cpu.set_irq(True)

    instruction = cpu.step()
    assert instruction.boundary.irq is True
    assert not isinstance(instruction, IRQStep)
    assert cpu.state.pc.value == 1

    cpu.state.status.interrupt_disable = False
    interrupt = cpu.step()
    assert isinstance(interrupt, IRQStep)
    assert interrupt.vector == 0x4000


@pytest.mark.parametrize(
    ("setup", "expected_b"),
    [
        ("brk", True),
        ("php", True),
        ("irq", False),
        ("nmi", False),
    ],
)
def test_stack_status_b_bit_is_operation_context_not_processor_state(setup, expected_b):
    values = {0xFFFA: 0x00, 0xFFFB: 0x40, 0xFFFE: 0x00, 0xFFFF: 0x40}
    if setup == "brk":
        values.update({0: 0x00, 1: 0xEA})
    elif setup == "php":
        values[0] = 0x08
    lines = InterruptLines()
    cpu = CPU(
        Bus(values),
        lines=lines,
        state=CPUState(status=StatusFlags(carry=True), stack_pointer=0xFD),
    )
    if setup == "irq":
        cpu.set_irq(True)
    elif setup == "nmi":
        cpu.signal_nmi()

    cpu.step()

    stack_address = 0x01FD if setup == "php" else 0x01FB
    assert bool(cpu.memory.values[stack_address] & 0x10) is expected_b
    assert cpu.state.status.to_byte() & 0x10 == 0


@pytest.mark.parametrize(
    ("opcode", "stack_pointer", "stack_values", "expected_pc"),
    [
        (0x28, 0xFC, {0x01FD: 0xFF}, None),
        (0x40, 0xFA, {0x01FB: 0xFF, 0x01FC: 0x34, 0x01FD: 0x12}, 0x1234),
    ],
)
def test_plp_and_rti_normalize_stacked_status_and_never_persist_b(
    opcode, stack_pointer, stack_values, expected_pc
):
    values = {0: opcode, **stack_values}
    cpu = CPU(Bus(values), state=CPUState(stack_pointer=stack_pointer))

    cpu.step()

    assert cpu.state.status == StatusFlags(
        negative=True,
        overflow=True,
        decimal=True,
        interrupt_disable=True,
        zero=True,
        carry=True,
    )
    assert cpu.state.status.to_byte() == 0xEF
    if expected_pc is not None:
        assert cpu.state.pc.value == expected_pc


def test_nmi_during_brk_hijacks_vector_after_preserving_brk_frame():
    class NmiOnStatusPush(Bus):
        def __init__(self, lines):
            super().__init__(
                {
                    0: 0x00,
                    1: 0xEA,
                    0xFFFE: 0x00,
                    0xFFFF: 0x30,
                    0xFFFA: 0x00,
                    0xFFFB: 0x40,
                }
            )
            self.lines = lines

        def write_byte(self, address, value):
            super().write_byte(address, value)
            if address == 0x01FB:
                self.lines.set_nmi(True)

    lines = InterruptLines()
    cpu = CPU(
        NmiOnStatusPush(lines),
        lines=lines,
        state=CPUState(program_counter=0x0000, stack_pointer=0xFD),
    )

    result = cpu.step()

    assert result.accepted_events == ("BRK", "NMI")
    assert result.vector == 0x4000
    assert cpu.memory.values[0x01FD] == 0x00
    assert cpu.memory.values[0x01FC] == 0x02
    assert cpu.memory.values[0x01FB] & 0x10


def test_irq_held_during_nmi_is_accepted_after_rti():
    bus = Bus({0xFFFA: 0x00, 0xFFFB: 0x40, 0xFFFE: 0x00, 0xFFFF: 0x50, 0x4000: 0x40})
    cpu = CPU(bus, state=CPUState(program_counter=0x2345))
    cpu.set_irq(True)
    cpu.signal_nmi()

    nmi = cpu.step()
    rti = cpu.step()
    irq = cpu.step()

    assert isinstance(nmi, NMIStep)
    assert rti.cycles == 6
    assert isinstance(irq, IRQStep)
    assert nmi.accepted_events == ("NMI",)
    assert irq.accepted_events == ("IRQ",)
