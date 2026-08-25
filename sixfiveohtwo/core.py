"""Embeddable, machine-neutral NMOS 6502 core shell."""

from __future__ import annotations

from .cpu import CPUState
from .interrupts import InterruptBoundary, InterruptLines
from .memory import MemoryBus


class CPU:
    """Own CPU state while delegating memory and input lines to the host.

    This shell deliberately does not execute instructions or implement reset
    sequencing, vector fetches, address maps, or devices.  Hosts drive the
    input lines and an execution phase can call
    :meth:`sample_instruction_boundary` before handling an instruction.
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


__all__ = ("CPU",)
