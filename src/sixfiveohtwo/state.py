"""Immutable values for capturing and restoring NMOS 6502 processor state."""

from dataclasses import dataclass


def _require_int(name: str, value: object, maximum: int) -> None:
    if type(value) is not int or not 0 <= value <= maximum:
        width = 2 if maximum == 0xFF else 4
        message = f"{name} must be an integer in range 0x{'0' * width}..0x{maximum:0{width}X}"
        raise ValueError(message)


def _require_bool(name: str, value: object) -> None:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a bool")


@dataclass(frozen=True, slots=True)
class CPUState:
    """Complete CPU-owned state at an instruction boundary.

    Registers, the interrupt requests the host has made and the core has not
    yet taken, and the internal state that decides what the next ``step()``
    does. Host memory, devices, scheduling and cycle counters are deliberately
    excluded: restoring this value restores the processor, not a machine.
    """

    a: int = 0
    x: int = 0
    y: int = 0
    s: int = 0
    pc: int = 0
    #: P as the core keeps it: bit 5 set and B (bit 4) clear, since neither
    #: is a flip-flop (docs/cpu-state.md).
    p: int = 0x24
    halted: bool = False  # JAM has run; only a reset restarts the CPU
    reset_pending: bool = False
    maskable_interrupt_pending: bool = False  # the IRQ line, a level
    non_maskable_interrupt_pending: bool = False  # an NMI edge latched and not yet taken
    #: The I flag the last instruction's interrupt poll saw, when that differs
    #: in timing from P: set by CLI, SEI and PLP for exactly one boundary.
    polled_i: bool | None = None

    def __post_init__(self) -> None:
        for name in ("a", "x", "y", "s", "p"):
            _require_int(name, getattr(self, name), 0xFF)
        _require_int("pc", self.pc, 0xFFFF)
        for name in (
            "halted",
            "reset_pending",
            "maskable_interrupt_pending",
            "non_maskable_interrupt_pending",
        ):
            _require_bool(name, getattr(self, name))
        if self.polled_i is not None:
            _require_bool("polled_i", self.polled_i)
        if self.p & 0x30 != 0x20:
            raise ValueError("p must have bit 5 set and B (bit 4) clear")


__all__ = ["CPUState"]
