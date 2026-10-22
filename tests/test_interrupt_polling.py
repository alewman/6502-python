"""When an interrupt raised from inside a bus callback is taken: the poll's timing.

The chip polls its interrupt detectors in an instruction's last cycle, so the
requests that count are the ones standing at the end of the second-to-last
cycle (NESdev, "CPU interrupts", "Detailed interrupt behavior", which works
from the visual6502 transistor-level simulation). BRK and interrupt entries do
not poll, and the vector of BRK or an IRQ entry is chosen after its cycle 4,
so an NMI by then takes it over ("Interrupt hijacking").

A board raises interrupts from inside the bus callbacks, at the cycle its
device changes the line, so these tests do the same: ``ScriptedHost`` runs an
action after the callback of a chosen access of the current step.
SingleStepTests runs one instruction from a register image and cannot see any
of this; the board-level judges are blargg's ``cpu_interrupts_v2`` and
AccuracyCoin (famicom-python).
"""

from collections.abc import Callable

import pytest

from sixfiveohtwo import MOS6502, CPUState, next_boundary
from sixfiveohtwo.debug import BoundaryKind, DebugSession
from tests.conftest import Host

NOP, INX, BRK = 0xEA, 0xE8, 0x00
IRQ_HANDLER, NMI_HANDLER = 0x0300, 0x0400


class ScriptedHost(Host):
    """A Host that runs ``actions[k]`` after the callback of the step's k-th access (from 1)."""

    def __init__(self, program: tuple[int, ...]) -> None:
        super().__init__()
        self.memory[0x0200:0x0300] = bytes((NOP,)) * 0x100
        self.memory[0x0200 : 0x0200 + len(program)] = bytes(program)
        self.memory[IRQ_HANDLER : IRQ_HANDLER + 0x10] = bytes((INX,)) * 0x10
        self.memory[NMI_HANDLER : NMI_HANDLER + 0x10] = bytes((INX,)) * 0x10
        self.memory[0xFFFA:0x10000] = bytes((0x00, 0x04, 0x00, 0x05, 0x00, 0x03))
        self.actions: dict[int, Callable[[MOS6502], None]] = {}
        self.cpu.s = 0xFF
        self.cpu.p = 0x20  # I clear

    def _after_access(self) -> None:
        action = self.actions.get(len(self.accesses))
        if action is not None:
            action(self.cpu)

    def read_byte(self, address: int) -> int:
        value = super().read_byte(address)
        self._after_access()
        return value

    def write_byte(self, address: int, value: int) -> None:
        super().write_byte(address, value)
        self._after_access()

    def step(self, **actions: Callable[[MOS6502], None]) -> int:
        self.actions = {int(name.removeprefix("cycle_")): act for name, act in actions.items()}
        try:
            return super().step()
        finally:
            self.actions = {}


def raise_irq(cpu: MOS6502) -> None:
    cpu.request_maskable_interrupt()


def release_irq(cpu: MOS6502) -> None:
    cpu.clear_maskable_interrupt()


def raise_nmi(cpu: MOS6502) -> None:
    cpu.request_non_maskable_interrupt()


def _set(**values: int) -> Callable[[ScriptedHost], None]:
    def setup(machine: ScriptedHost) -> None:
        for name, value in values.items():
            if name.startswith("m"):
                machine.memory[int(name[1:], 16)] = value
            else:
                setattr(machine.cpu, name, value)

    return setup


# name: (program at $0200, setup, cycles, where the next instruction is)
SHAPES: dict[str, tuple[tuple[int, ...], Callable[[ScriptedHost], None], int, int]] = {
    "NOP": ((NOP,), _set(), 2, 0x0201),
    "LDA #imm": ((0xA9, 0x01), _set(), 2, 0x0202),
    "LDA zp": ((0xA5, 0x10), _set(), 3, 0x0202),
    "LDA abs": ((0xAD, 0x34, 0x12), _set(), 4, 0x0203),
    "LDA abs,X across a page": ((0xBD, 0xF0, 0x12), _set(x=0x20), 5, 0x0203),
    "LDA (zp),Y across a page": ((0xB1, 0x10), _set(y=0x20, m0010=0xF0, m0011=0x12), 6, 0x0202),
    "STA abs": ((0x8D, 0x34, 0x12), _set(), 4, 0x0203),
    "INC abs": ((0xEE, 0x34, 0x12), _set(), 6, 0x0203),
    "PHA": ((0x48,), _set(), 3, 0x0201),
    "PLA": ((0x68,), _set(s=0xFE), 4, 0x0201),
    "JMP abs": ((0x4C, 0x10, 0x02), _set(), 3, 0x0210),
    "JSR": ((0x20, 0x10, 0x02), _set(), 6, 0x0210),
    "RTS": ((0x60,), _set(s=0xFD, m01FE=0x0F, m01FF=0x02), 6, 0x0210),
    "RTI": ((0x40,), _set(s=0xFC, m01FD=0x20, m01FE=0x10, m01FF=0x02), 6, 0x0210),
    "BNE not taken": ((0xD0, 0x10), _set(p=0x22), 2, 0x0202),
}
CASES = [
    pytest.param(name, cycle, id=f"{name}-cycle{cycle}")
    for name, (_, _, cycles, _) in SHAPES.items()
    for cycle in range(1, cycles + 1)
]


@pytest.mark.parametrize(("shape", "cycle"), CASES)
def test_irq_raised_by_the_penultimate_cycle_is_taken_after_this_instruction(
    shape: str, cycle: int
) -> None:
    program, setup, cycles, after = SHAPES[shape]
    machine = ScriptedHost(program)
    setup(machine)
    cpu = machine.cpu
    assert machine.step(**{f"cycle_{cycle}": raise_irq}) == cycles
    assert cpu.pc == after
    if cycle < cycles:
        assert machine.step() == 7, "raised by the end of the second-to-last cycle"
        assert cpu.pc == IRQ_HANDLER
    else:
        assert machine.step() == 2, "raised in the last cycle: the next instruction runs first"
        assert cpu.pc == after + 1
        assert machine.step() == 7
        assert cpu.pc == IRQ_HANDLER


@pytest.mark.parametrize(("shape", "cycle"), CASES)
def test_nmi_latched_by_the_penultimate_cycle_is_taken_after_this_instruction(
    shape: str, cycle: int
) -> None:
    program, setup, cycles, after = SHAPES[shape]
    machine = ScriptedHost(program)
    setup(machine)
    cpu = machine.cpu
    cpu.p |= 0x04  # I set: NMI ignores it
    machine.step(**{f"cycle_{cycle}": raise_nmi})
    if cycle < cycles:
        assert machine.step() == 7
        assert cpu.pc == NMI_HANDLER
    else:
        assert machine.step() == 2
        assert cpu.pc == after + 1
        assert machine.step() == 7
        assert cpu.pc == NMI_HANDLER


def test_irq_seen_at_the_penultimate_cycle_is_taken_though_released_in_the_last() -> None:
    # An instruction ending in the read that acknowledges the device: the
    # poll has already seen the line ($4015 and the APU frame IRQ on a NES).
    machine = ScriptedHost((0xAD, 0x34, 0x12))  # LDA abs, 4 cycles
    assert machine.step(cycle_1=raise_irq, cycle_4=release_irq) == 4
    assert not machine.cpu.maskable_interrupt_pending
    assert machine.step() == 7
    assert machine.cpu.pc == IRQ_HANDLER


def test_irq_released_by_the_penultimate_cycle_is_not_taken() -> None:
    machine = ScriptedHost((0xAD, 0x34, 0x12))
    assert machine.step(cycle_1=raise_irq, cycle_3=release_irq) == 4
    assert machine.step() == 2  # the NOP after it; the IRQ is gone


def test_nmi_during_the_first_four_cycles_of_an_irq_entry_takes_it_over() -> None:
    for cycle in (1, 2, 3, 4):
        machine = ScriptedHost((NOP,))
        machine.cpu.request_maskable_interrupt()
        assert machine.step(**{f"cycle_{cycle}": raise_nmi}) == 7
        assert machine.cpu.pc == NMI_HANDLER, f"NMI at cycle {cycle}"
        assert machine.memory[0x01FD] & 0x10 == 0, "the IRQ's frame: B clear"
        assert not machine.cpu.non_maskable_interrupt_pending


@pytest.mark.parametrize("cycle", [5, 6, 7])
def test_nmi_after_cycle_four_of_an_irq_entry_waits_for_one_handler_instruction(
    cycle: int,
) -> None:
    machine = ScriptedHost((NOP,))
    cpu = machine.cpu
    cpu.request_maskable_interrupt()
    assert machine.step(**{f"cycle_{cycle}": raise_nmi}) == 7
    assert cpu.pc == IRQ_HANDLER
    assert next_boundary(cpu.capture_state()) is BoundaryKind.INSTRUCTION
    assert machine.step() == 2  # INX: the entry did not poll
    assert (cpu.pc, cpu.x) == (IRQ_HANDLER + 1, 1)
    assert machine.step() == 7
    assert cpu.pc == NMI_HANDLER


def test_nmi_hijacks_brk_up_to_cycle_four_and_not_after() -> None:
    for cycle, vector in ((3, NMI_HANDLER), (4, NMI_HANDLER), (5, IRQ_HANDLER)):
        machine = ScriptedHost((BRK, 0xFF))
        assert machine.step(**{f"cycle_{cycle}": raise_nmi}) == 7
        assert machine.cpu.pc == vector, f"NMI at cycle {cycle}"
        assert machine.memory[0x01FD] & 0x10, "BRK's frame: B set"


def test_nmi_during_brks_last_cycles_waits_for_one_handler_instruction() -> None:
    machine = ScriptedHost((BRK, 0xFF))
    cpu = machine.cpu
    machine.step(cycle_6=raise_nmi)
    assert cpu.pc == IRQ_HANDLER
    assert machine.step() == 2
    assert machine.step() == 7
    assert cpu.pc == NMI_HANDLER


def test_a_request_between_steps_is_taken_at_the_next_boundary() -> None:
    machine = ScriptedHost((NOP,))
    machine.step()
    machine.cpu.request_maskable_interrupt()
    assert next_boundary(machine.cpu.capture_state()) is BoundaryKind.IRQ
    assert machine.step() == 7


def test_a_request_between_steps_after_an_entry_waits_for_one_handler_instruction() -> None:
    machine = ScriptedHost((NOP,))
    cpu = machine.cpu
    cpu.request_maskable_interrupt()
    machine.step()
    cpu.clear_maskable_interrupt()
    cpu.request_non_maskable_interrupt()
    assert machine.step() == 2  # the IRQ handler's first INX
    assert machine.step() == 7
    assert cpu.pc == NMI_HANDLER


def test_reset_does_not_poll() -> None:
    machine = ScriptedHost(())
    cpu = machine.cpu
    cpu.request_reset()
    machine.step(cycle_2=raise_nmi)
    assert cpu.pc == 0x0500
    machine.memory[0x0500] = NOP
    assert machine.step() == 2
    assert machine.step() == 7
    assert cpu.pc == NMI_HANDLER


def test_capture_and_restore_carry_a_request_the_poll_has_not_seen() -> None:
    machine = ScriptedHost((NOP, NOP))
    machine.step(cycle_2=raise_irq)  # in NOP's last cycle
    state = machine.cpu.capture_state()
    assert state.maskable_interrupt_pending
    assert state.polled_maskable_interrupt is False
    assert next_boundary(state) is BoundaryKind.INSTRUCTION

    other = ScriptedHost((NOP, NOP))
    other.cpu.restore_state(state)
    assert other.cpu.capture_state() == state
    assert other.step() == 2
    assert other.step() == 7


def test_capture_and_restore_carry_a_skipped_poll() -> None:
    machine = ScriptedHost((NOP,))
    machine.cpu.request_maskable_interrupt()
    machine.step()
    machine.cpu.clear_maskable_interrupt()
    state = machine.cpu.capture_state()
    assert state.skipped_poll
    other = ScriptedHost((NOP,))
    other.cpu.restore_state(state)
    other.cpu.request_non_maskable_interrupt()
    assert next_boundary(other.cpu.capture_state()) is BoundaryKind.INSTRUCTION
    assert other.step() == 2


def test_a_default_state_takes_its_requests_at_the_next_boundary() -> None:
    machine = ScriptedHost((NOP,))
    machine.cpu.restore_state(CPUState(pc=0x0200, p=0x20, maskable_interrupt_pending=True))
    assert machine.step() == 7


def test_replacing_the_bus_callables_keeps_the_sampling() -> None:
    machine = ScriptedHost((NOP, NOP))
    session = DebugSession(machine.cpu, track_accesses=True)
    assert machine.cpu.read_byte is not machine.read_byte
    machine.step(cycle_2=raise_irq)
    assert machine.step() == 2, "still the last cycle: one more instruction first"
    assert machine.step() == 7
    session.close()
    assert machine.cpu.read_byte == machine.read_byte


# Branches poll at the end of cycle 1, and a taken one that crosses a page
# also at the end of cycle 3; seen at either, the interrupt is taken (NESdev,
# "Branch instructions and interrupts"). blargg's 5-branch_delays_irq and
# AccuracyCoin's "Interrupt Flag Latency" judge this on a board.
BNE_SAME_PAGE = ((0xD0, 0x10), _set(p=0x20), 3, 0x0212)  # Z clear: taken, to $0212
BNE_ACROSS = ((0xD0, 0xF0), _set(p=0x20, m01F2=NOP), 4, 0x01F2)  # back across to $01F2


@pytest.mark.parametrize(("cycle", "taken_after"), [(1, True), (2, False), (3, False)])
def test_a_taken_branch_on_the_same_page_polls_only_at_the_end_of_cycle_1(
    cycle: int, taken_after: bool
) -> None:
    program, setup, cycles, after = BNE_SAME_PAGE
    machine = ScriptedHost(program)
    setup(machine)
    assert machine.step(**{f"cycle_{cycle}": raise_irq}) == cycles
    assert machine.cpu.pc == after
    if taken_after:
        assert machine.step() == 7
    else:
        assert machine.step() == 2, "the branch delays the IRQ by one instruction"
        assert machine.step() == 7
    assert machine.cpu.pc == IRQ_HANDLER


@pytest.mark.parametrize(("cycle", "taken_after"), [(1, True), (2, True), (3, True), (4, False)])
def test_a_taken_branch_across_a_page_polls_at_the_end_of_cycle_1_or_3(
    cycle: int, taken_after: bool
) -> None:
    program, setup, cycles, after = BNE_ACROSS
    machine = ScriptedHost(program)
    setup(machine)
    assert machine.step(**{f"cycle_{cycle}": raise_irq}) == cycles
    assert machine.cpu.pc == after
    assert machine.step() == (7 if taken_after else 2)


def test_an_irq_seen_only_at_cycle_1_of_a_branch_across_a_page_is_taken() -> None:
    program, setup, cycles, _ = BNE_ACROSS
    machine = ScriptedHost(program)
    setup(machine)
    assert machine.step(cycle_1=raise_irq, cycle_2=release_irq) == cycles
    assert machine.step() == 7, "detected at the first polling point only"


def test_an_irq_released_in_cycle_2_of_a_same_page_branch_is_still_taken() -> None:
    program, setup, cycles, _ = BNE_SAME_PAGE
    machine = ScriptedHost(program)
    setup(machine)
    assert machine.step(cycle_1=raise_irq, cycle_2=release_irq) == cycles
    assert machine.step() == 7


def test_an_nmi_in_cycle_2_of_a_same_page_branch_waits_one_instruction() -> None:
    program, setup, _, after = BNE_SAME_PAGE
    machine = ScriptedHost(program)
    setup(machine)
    machine.cpu.p |= 0x04
    machine.step(cycle_2=raise_nmi)
    assert machine.step() == 2
    assert machine.cpu.pc == after + 1
    assert machine.step() == 7
    assert machine.cpu.pc == NMI_HANDLER


class StallingHost(ScriptedHost):
    """A ScriptedHost whose k-th read of a step is stalled (RDY low, a DMA) and runs
    ``stalls[k]`` during the stall, before the access, then calls ``note_stall``."""

    def __init__(self, program: tuple[int, ...]) -> None:
        super().__init__(program)
        self.stalls: dict[int, Callable[[MOS6502], None]] = {}

    def read_byte(self, address: int) -> int:
        stall = self.stalls.get(len(self.accesses) + 1)
        if stall is not None:
            # A four-cycle stall (a DMC DMA), the request raised in its second.
            cpu = self.cpu
            cpu.note_stall()
            for halted in range(4):
                if halted == 1:
                    stall(cpu)
                cpu.note_stall()
        return super().read_byte(address)


STALL_SHAPES = {
    **SHAPES,
    "BEQ taken": ((0xF0, 0x10), _set(p=0x22), 3, 0x0212),
    "BEQ taken across a page": ((0xF0, 0xF0), _set(p=0x22), 4, 0x01F2),
}


def _read_cycles(shape: str) -> list[int]:
    program, setup, _, _ = STALL_SHAPES[shape]
    machine = ScriptedHost(program)
    setup(machine)
    machine.step()
    return [k for k, access in enumerate(machine.accesses, 1) if access[0] == "r"]


STALL_CASES = [
    pytest.param(name, cycle, id=f"{name}-cycle{cycle}")
    for name in STALL_SHAPES
    for cycle in _read_cycles(name)
]


@pytest.mark.parametrize(("shape", "cycle"), STALL_CASES)
def test_nmi_latched_during_a_stalled_read_is_taken_after_this_instruction(
    shape: str, cycle: int
) -> None:
    # perfect6502 with RDY held low for four cycles: an NMI that falls while
    # the chip is halted is taken at the next boundary whichever read was
    # stalled, the last one and a taken branch's included.
    program, setup, cycles, after = STALL_SHAPES[shape]
    machine = StallingHost(program)
    setup(machine)
    cpu = machine.cpu
    machine.stalls = {cycle: raise_nmi}
    assert machine.step() == cycles
    machine.stalls = {}
    assert cpu.pc == after
    assert machine.step() == 7
    assert cpu.pc == NMI_HANDLER


def test_a_taken_branch_ignores_a_request_raised_in_the_last_cycle_of_its_next_read_stall() -> None:
    # AccuracyCoin "Interrupt flag latency" test A (its hardware answer key):
    # a DMC DMA stalls the taken branch's third cycle and raises the DMC IRQ
    # in its last cycle; the IRQ waits for the next instruction. perfect6502
    # agrees for an NMI (in the last halted cycle of that read: not polled).
    program, setup, cycles, after = STALL_SHAPES["BEQ taken"]
    machine = ScriptedHost(program)
    setup(machine)
    cpu = machine.cpu
    original = machine.read_byte

    def read_byte(address: int) -> int:
        if len(machine.accesses) + 1 == 3:  # the next-opcode read
            cpu.note_stall()
            for halted in range(4):
                if halted == 3:
                    cpu.request_maskable_interrupt()
                cpu.note_stall()
        return original(address)

    cpu.read_byte = read_byte
    assert machine.step() == cycles
    assert cpu.pc == after
    assert machine.step() == 2, "the next instruction runs first"
    assert machine.step() == 7
    assert cpu.pc == IRQ_HANDLER
