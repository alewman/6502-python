"""Host-driven NMOS 6502 interrupt-line contracts.

This module describes line state only. It does not fetch vectors, alter CPU state,
or execute instructions.
"""

from __future__ import annotations

from dataclasses import dataclass


def _require_boolean(value: bool, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")
    return value


@dataclass(frozen=True)
class InterruptBoundary:
    """The interrupt inputs observed at one instruction boundary.

    ``reset`` and ``irq`` are level-sensitive and therefore reflect the line at
    the time of sampling. ``nmi`` is true when a rising edge was latched since
    the previous sample. Sampling consumes that NMI indication.
    """

    reset: bool
    irq: bool
    nmi: bool


class InterruptLines:
    """Mutable host-owned RESET, IRQ, and NMI input lines.

    RESET and IRQ are level-sensitive: their asserted state is reported at each
    boundary while the host holds the line high. NMI is edge-latched: a low to
    high transition records one pending signal, which is consumed by the next
    call to :meth:`sample_instruction_boundary`. NMI must return low before a
    subsequent high transition can be latched.
    """

    __slots__ = ("_reset", "_irq", "_nmi", "_nmi_pending")

    def __init__(
        self, *, reset: bool = False, irq: bool = False, nmi: bool = False
    ) -> None:
        self._reset = _require_boolean(reset, "reset")
        self._irq = _require_boolean(irq, "irq")
        self._nmi = _require_boolean(nmi, "nmi")
        self._nmi_pending = False

    @property
    def reset(self) -> bool:
        """Whether the RESET line is currently asserted."""
        return self._reset

    @property
    def irq(self) -> bool:
        """Whether the IRQ line is currently asserted."""
        return self._irq

    @property
    def nmi(self) -> bool:
        """Whether the NMI input line is currently high."""
        return self._nmi

    @property
    def nmi_pending(self) -> bool:
        """Whether an NMI rising edge awaits boundary sampling."""
        return self._nmi_pending

    def set_reset(self, asserted: bool) -> None:
        """Drive RESET to an asserted or deasserted level."""
        self._reset = _require_boolean(asserted, "asserted")

    def set_irq(self, asserted: bool) -> None:
        """Drive IRQ to an asserted or deasserted level."""
        self._irq = _require_boolean(asserted, "asserted")

    def set_nmi(self, high: bool) -> None:
        """Drive NMI and latch its low-to-high transition."""
        high = _require_boolean(high, "high")
        if high and not self._nmi:
            self._nmi_pending = True
        self._nmi = high

    def signal_nmi(self) -> None:
        """Latch an NMI signal without requiring a persistent host line."""
        self._nmi_pending = True

    def pending_interrupt_boundary(self) -> InterruptBoundary:
        """Inspect the current boundary inputs without consuming NMI."""
        return InterruptBoundary(
            reset=self._reset, irq=self._irq, nmi=self._nmi_pending
        )

    def sample_instruction_boundary(self) -> InterruptBoundary:
        """Return and consume the pending line state at a boundary.

        The core may sample this contract again at an NMOS interrupt-sequence
        boundary, such as immediately before BRK vector fetch.
        """
        sample = self.pending_interrupt_boundary()
        self._nmi_pending = False
        return sample


__all__ = ("InterruptBoundary", "InterruptLines")
