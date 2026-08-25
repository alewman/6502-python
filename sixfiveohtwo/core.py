"""Embeddable, machine-neutral NMOS 6502 core shell."""

from __future__ import annotations

from dataclasses import dataclass

from .cpu import CPUState
from .interrupts import InterruptBoundary, InterruptLines
from .memory import MemoryBus


def _require_cycles(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("cycles must be an integer")
    if value < 0:
        raise ValueError("cycles must not be negative")
    return value


def _normalize_byte_address(address: int) -> int:
    """Wrap an address to the 8-bit address range."""
    if isinstance(address, bool) or not isinstance(address, int):
        raise TypeError("address must be an integer")
    return address & 0xFF


def _normalize_word_address(address: int) -> int:
    """Wrap an address to the 16-bit address range."""
    if isinstance(address, bool) or not isinstance(address, int):
        raise TypeError("address must be an integer")
    return address & 0xFFFF


@dataclass(frozen=True)
class InstructionContext:
    """Dispatch input prepared at one instruction boundary."""

    state: CPUState
    boundary: InterruptBoundary
    opcode_address: int
    opcode: int

    @property
    def pc(self) -> int:
        """The address from which the opcode was fetched."""
        return self.opcode_address


@dataclass(frozen=True)
class InstructionStep:
    """The boundary context and cycles accounted for by a single step."""

    context: InstructionContext
    cycles: int
    total_cycles: int

    @property
    def opcode(self) -> int:
        return self.context.opcode

    @property
    def boundary(self) -> InterruptBoundary:
        return self.context.boundary


class CPU:
    """Own CPU state while delegating memory and input lines to the host.

    :meth:`step` prepares a dispatch context but does not implement instruction
    semantics or interrupt sequencing. Hosts retain ownership of memory maps and
    devices.
    """

    __slots__ = ("_memory", "_state", "_lines")

    def __init__(
        self,
        memory: MemoryBus,
        *,
        lines: InterruptLines | None = None,
        state: CPUState | None = None,
    ) -> None:
        if not isinstance(memory, MemoryBus):
            raise TypeError("memory must implement MemoryBus")
        if lines is not None and not isinstance(lines, InterruptLines):
            raise TypeError("lines must be InterruptLines")
        if state is not None and not isinstance(state, CPUState):
            raise TypeError("state must be CPUState")
        self._memory = memory
        self._lines = lines if lines is not None else InterruptLines()
        self._state = state if state is not None else CPUState()

    @property
    def memory(self) -> MemoryBus:
        """The host-provided memory implementation."""
        return self._memory

    @property
    def state(self) -> CPUState:
        """The mutable register state owned by this core."""
        return self._state

    @property
    def lines(self) -> InterruptLines:
        """The host-driven RESET, IRQ, and NMI inputs."""
        return self._lines

    @property
    def reset(self) -> bool:
        """Whether RESET is currently asserted."""
        return self._lines.reset

    @property
    def irq(self) -> bool:
        """Whether IRQ is currently asserted."""
        return self._lines.irq

    @property
    def nmi(self) -> bool:
        """Whether NMI is currently high."""
        return self._lines.nmi

    @property
    def nmi_pending(self) -> bool:
        """Whether a latched NMI edge awaits boundary sampling."""
        return self._lines.nmi_pending

    def set_reset(self, asserted: bool) -> None:
        """Drive the RESET line without performing reset sequencing."""
        self._lines.set_reset(asserted)

    def set_irq(self, asserted: bool) -> None:
        """Drive the IRQ line."""
        self._lines.set_irq(asserted)

    def set_nmi(self, high: bool) -> None:
        """Drive the NMI line, latching a rising edge."""
        self._lines.set_nmi(high)

    def signal_nmi(self) -> None:
        """Latch one NMI signal without requiring a persistent line level."""
        self._lines.signal_nmi()

    def pending_interrupt_boundary(self) -> InterruptBoundary:
        """Inspect current input state without consuming a pending NMI."""
        return self._lines.pending_interrupt_boundary()

    def sample_instruction_boundary(self) -> InterruptBoundary:
        """Sample and consume input state at an instruction boundary."""
        return self._lines.sample_instruction_boundary()

    def record_cycles(self, cycles: int) -> int:
        """Record cycles consumed by dispatched execution and return the total."""
        cycles = _require_cycles(cycles)
        self._state.cycles += cycles
        return self._state.cycles

    @staticmethod
    def _validate_fetched_byte(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("memory read must return an integer byte")
        if not 0x00 <= value <= 0xFF:
            raise ValueError("memory read must return a byte")
        return value

    def _fetch_byte(self) -> int:
        """Read one instruction byte and advance the PC with 16-bit wrapping."""
        address = _normalize_word_address(self._state.pc.value)
        value = self._validate_fetched_byte(self._memory.read_byte(address))
        self._state.pc.value = _normalize_word_address(address + 1)
        return value

    def _fetch_word(self) -> int:
        """Read a little-endian word from the instruction stream."""
        low = self._fetch_byte()
        high = self._fetch_byte()
        return low | (high << 8)

    def step(self, *, cycles: int = 0) -> InstructionStep:
        """Sample inputs and fetch one opcode for dispatch.

        The opcode is fetched at the current PC, then PC wraps as a 16-bit
        register. ``cycles`` lets a dispatcher account for the completed
        context in the returned result; instruction semantics are not performed.
        """
        cycles = _require_cycles(cycles)
        boundary = self.sample_instruction_boundary()
        opcode_address = _normalize_word_address(self._state.pc.value)
        opcode = self._fetch_byte()
        total_cycles = self.record_cycles(cycles)
        return InstructionStep(
            context=InstructionContext(
                state=self._state,
                boundary=boundary,
                opcode_address=opcode_address,
                opcode=opcode,
            ),
            cycles=cycles,
            total_cycles=total_cycles,
        )


__all__ = ("CPU", "InstructionContext", "InstructionStep")
