import pytest

from sixfiveohtwo import CPU, CPUState, InterruptLines, StatusFlags


class Bus:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def read_byte(self, address):
        return self.values.get(address, 0)

    def write_byte(self, address, value):
        self.values[address] = value


@pytest.mark.parametrize(
    ("opcode", "attribute", "expected"),
    [
        (0x18, "carry", False),
        (0xD8, "decimal", False),
        (0x58, "interrupt_disable", False),
        (0xB8, "overflow", False),
        (0x38, "carry", True),
        (0xF8, "decimal", True),
        (0x78, "interrupt_disable", True),
    ],
)
def test_status_control_instructions_modify_only_their_flag(
    opcode, attribute, expected
):
    initial = StatusFlags(
        negative=True,
        overflow=True,
        decimal=True,
        interrupt_disable=True,
        zero=True,
        carry=True,
    )
    state = CPUState(program_counter=0x200, status=initial)
    cpu = CPU(Bus({0x200: opcode}), state=state)

    result = cpu.step()

    assert result.cycles == 2
    assert state.pc.value == 0x201
    assert getattr(state.status, attribute) is expected
    for name in (
        "negative",
        "overflow",
        "decimal",
        "interrupt_disable",
        "zero",
        "carry",
    ):
        if name != attribute:
            assert getattr(state.status, name) is True


@pytest.mark.parametrize("opcode", [0xEA])
def test_nop_advances_one_byte_without_changing_registers_or_status(opcode):
    status = StatusFlags(
        negative=True,
        overflow=True,
        decimal=True,
        interrupt_disable=True,
        zero=True,
        carry=True,
    )
    state = CPUState(
        accumulator=0xA5,
        program_counter=0xFFFF,
        stack_pointer=0x42,
        status=status,
    )
    cpu = CPU(Bus({0xFFFF: opcode, 0x0000: 0xEA}), state=state)

    result = cpu.step()

    assert result.cycles == 2
    assert result.total_cycles == 2
    assert state.pc.value == 0x0000
    assert state.a.value == 0xA5
    assert state.sp.value == 0x42
    assert state.status == status

    assert cpu.step().cycles == 2
    assert state.pc.value == 0x0001


def test_cli_uses_boundary_interrupt_sampling_before_enabling_interrupts():
    lines = InterruptLines(irq=True)
    state = CPUState(
        program_counter=0x100,
        status=StatusFlags(interrupt_disable=True),
    )
    bus = Bus({0x100: 0x58, 0xFFFE: 0x00, 0xFFFF: 0x80})
    cpu = CPU(bus, lines=lines, state=state)

    instruction = cpu.step()

    assert instruction.cycles == 2
    assert instruction.boundary.irq is True
    assert state.status.interrupt_disable is False
    assert state.pc.value == 0x101

    interrupt = cpu.step()

    assert interrupt.cycles == 7
    assert interrupt.irq is True
    assert state.pc.value == 0x8000


def test_sei_takes_effect_after_the_current_boundary_sample():
    lines = InterruptLines()
    state = CPUState(program_counter=0x100)
    cpu = CPU(Bus({0x100: 0x78, 0x101: 0xEA}), lines=lines, state=state)

    instruction = cpu.step()
    lines.set_irq(True)

    assert instruction.cycles == 2
    assert instruction.boundary.irq is False
    assert state.status.interrupt_disable is True
    assert cpu.step().cycles == 2
    assert state.pc.value == 0x102
