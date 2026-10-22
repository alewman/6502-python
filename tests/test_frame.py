"""The frame's subclassing surface (docs/api-stability.md), held by a toy CPU.

``65816-python`` subclasses :class:`~sixfiveohtwo.frame.CPUFrame` directly. The
toy here does the same, with no NMOS code at all, so that a refactor which
breaks that surface fails in this repository first: the four hooks, the
confirming bus wrappers, the poll at the second-to-last cycle, an extra
request bit taken through ``_boundary_interrupt``, and the state helpers.
"""

from dataclasses import dataclass

from sixfiveohtwo.frame import IRQ_LINE, NMI_LATCH, NO_POLL, CPUFrame

ABORT = 0x08  # an extra request bit, as a 65C816 core adds one
SECOND = 0x0100  # every toy instruction's second cycle reads here
LAST = 0x0200  # and its third and last cycle here


@dataclass(frozen=True)
class ToyState:
    pc: int
    p: int
    halted: bool
    reset_pending: bool
    maskable_interrupt_pending: bool
    non_maskable_interrupt_pending: bool
    polled_i: bool | None
    polled_maskable_interrupt: bool | None
    polled_non_maskable_interrupt: bool | None
    skipped_poll: bool


class Toy(CPUFrame):
    """Opcode 0 is a three-cycle NOP; 1 clears I like CLI; 2 halts. Entries log their kind.

    Every instruction's cycles read the opcode, then $0100, then $0200, so a
    test can act in a chosen cycle.
    """

    def __init__(self, read_byte, write_byte) -> None:
        super().__init__(read_byte, write_byte)
        self.pc = 0
        self.p = 0x04  # I set, in bit 2 as the frame requires
        self.entered: list[str] = []

    def _execute(self) -> int:
        opcode = self._read(self.pc)
        self.pc += 1
        if opcode == 1:
            self._polled_i = self.p & 0x04  # I changes after the poll
            self.p &= ~0x04
        elif opcode == 2:
            self.halted = True
        self._read(SECOND)
        self._read(LAST)
        return 3

    def _enter_interrupt(self, kind: int) -> int:
        self._requests &= ~(NMI_LATCH | ABORT)
        self.entered.append({NMI_LATCH: "nmi", IRQ_LINE: "irq", ABORT: "abort"}[kind])
        self._read(0xFFFF)
        self._polled = NO_POLL
        self._deferred = None
        return 1

    def _accept_reset(self) -> int:
        self._reset_pending = False
        self.halted = False
        self.entered.append("reset")
        return 1

    def _halted(self) -> int:
        self._read(0xFFFF)
        return 1

    def _boundary_interrupt(self) -> int:
        if self._requests & ABORT:
            return ABORT
        return super()._boundary_interrupt()

    def request_abort(self) -> None:
        self._request(self._requests | ABORT)

    def capture(self) -> ToyState:
        return ToyState(pc=self.pc, p=self.p, **self._poll_fields())


def toy(program: bytes, on_read=None) -> Toy:
    memory = bytearray(0x10000)
    memory[: len(program)] = program

    def read(address: int) -> int:
        if on_read is not None:
            on_read(address)
        return memory[address]

    return Toy(read, memory.__setitem__)


def test_step_runs_the_instruction_hook_and_returns_its_cycles() -> None:
    cpu = toy(bytes([0, 0]))
    assert cpu.step() == 3
    assert cpu.pc == 1
    assert cpu.entered == []


def test_a_request_between_steps_is_taken_at_the_next_boundary() -> None:
    cpu = toy(bytes([1, 0, 0]))  # CLI first, so the IRQ is not masked
    cpu.step()
    cpu.step()  # the boundary after CLI still decides on the old I
    cpu.request_maskable_interrupt()
    assert cpu.step() == 1
    assert cpu.entered == ["irq"]


def test_nmi_wins_over_irq_and_is_taken_whatever_i_says() -> None:
    cpu = toy(bytes([0, 0]))
    cpu.request_maskable_interrupt()
    cpu.request_non_maskable_interrupt()
    cpu.step()
    assert cpu.entered == ["nmi"]


def test_a_request_in_the_last_cycle_waits_one_more_instruction() -> None:
    cpu: Toy

    def on_read(address: int) -> None:
        if address == LAST and cpu.pc == 1 and not cpu.non_maskable_interrupt_pending:
            cpu.request_non_maskable_interrupt()  # during the first instruction's last cycle

    cpu = toy(bytes([0, 0, 0, 0]), on_read)
    cpu.step()
    cpu.step()
    assert cpu.entered == []  # the poll at the end of cycle two missed it
    cpu.step()
    assert cpu.entered == ["nmi"]


def test_a_request_before_the_last_cycle_is_taken_at_the_boundary() -> None:
    cpu: Toy

    def on_read(address: int) -> None:
        if address == SECOND and not cpu.non_maskable_interrupt_pending:
            cpu.request_non_maskable_interrupt()  # during the second-to-last cycle

    cpu = toy(bytes([0, 0]), on_read)
    cpu.step()
    cpu.step()
    assert cpu.entered == ["nmi"]  # the poll saw it: taken at the first boundary


def test_an_extra_request_bit_goes_through_the_boundary_hook() -> None:
    cpu = toy(bytes([0, 0]))
    cpu.request_abort()
    cpu.step()
    assert cpu.entered == ["abort"]


def test_reset_and_halted_hooks_run_in_order() -> None:
    cpu = toy(bytes([2, 0]))
    cpu.step()
    assert cpu.halted
    assert cpu.step() == 1  # the halted hook, not an instruction
    cpu.request_reset()
    cpu.step()
    assert cpu.entered == ["reset"] and not cpu.halted


def test_poll_fields_round_trip_through_a_foreign_state_class() -> None:
    cpu = toy(bytes([1, 0, 0]))
    cpu.step()  # CLI: polled_i remembers the old I
    cpu.request_maskable_interrupt()
    state = cpu.capture()
    assert state.polled_i is True and state.maskable_interrupt_pending
    other = toy(bytes([1, 0, 0]))
    other.pc, other.p = state.pc, state.p
    other._restore_poll(state)
    assert other.capture() == state
    other.step()  # the old I still decides this boundary
    assert other.entered == []
    other.step()
    assert other.entered == ["irq"]
