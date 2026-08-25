"""Typed, machine-neutral NMOS 6502 CPU state models."""

from __future__ import annotations

from dataclasses import dataclass, field


def _require_integer(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _require_byte(value: int, name: str = "value") -> int:
    value = _require_integer(value, name)
    if not 0x00 <= value <= 0xFF:
        raise ValueError(f"{name} must fit in 8 bits")
    return value


def _require_word(value: int, name: str = "value") -> int:
    value = _require_integer(value, name)
    if not 0x0000 <= value <= 0xFFFF:
        raise ValueError(f"{name} must fit in 16 bits")
    return value


class Register8:
    """A mutable register whose value is always an unsigned byte."""

    __slots__ = ("_value",)

    def __init__(self, value: int = 0) -> None:
        self.value = value

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, value: int) -> None:
        self._value = _require_byte(value)

    def set(self, value: int) -> None:
        self.value = value

    def __int__(self) -> int:
        return self.value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Register8) and self.value == other.value


class Register16:
    """A mutable register whose value is always an unsigned 16-bit word."""

    __slots__ = ("_value",)

    def __init__(self, value: int = 0) -> None:
        self.value = value

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, value: int) -> None:
        self._value = _require_word(value)

    def set(self, value: int) -> None:
        self.value = value

    def __int__(self) -> int:
        return self.value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Register16) and self.value == other.value


class Accumulator(Register8):
    """The 8-bit accumulator (A)."""


class IndexRegister(Register8):
    """An 8-bit X or Y index register."""


class ProgramCounter(Register16):
    """The 16-bit program counter (PC)."""


class StackPointer(Register8):
    """The 8-bit stack offset (S), addressing page ``0x0100``."""


@dataclass
class IndexRegisters:
    """The two independent 8-bit index registers."""

    x: IndexRegister = field(default_factory=IndexRegister)
    y: IndexRegister = field(default_factory=IndexRegister)

    def __post_init__(self) -> None:
        if isinstance(self.x, int) and not isinstance(self.x, bool):
            self.x = IndexRegister(self.x)
        if isinstance(self.y, int) and not isinstance(self.y, bool):
            self.y = IndexRegister(self.y)
        if not isinstance(self.x, IndexRegister) or not isinstance(
            self.y, IndexRegister
        ):
            raise TypeError("x and y must be index registers or integers")


@dataclass
class StatusFlags:
    """The physical NMOS 6502 status flags.

    The break (B) bit is intentionally absent: it is an instruction/stack
    context bit, not a persistent latch in the processor status register.
    Bit 5 is always set when this state is represented as a status byte.
    """

    negative: bool = False
    overflow: bool = False
    decimal: bool = False
    interrupt_disable: bool = False
    zero: bool = False
    carry: bool = False

    def __post_init__(self) -> None:
        for name in (
            "negative",
            "overflow",
            "decimal",
            "interrupt_disable",
            "zero",
            "carry",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")

    def to_byte(self, *, break_flag: bool = False) -> int:
        """Encode flags for a status-byte transfer, optionally setting B."""
        if not isinstance(break_flag, bool):
            raise TypeError("break_flag must be a boolean")
        return (
            (int(self.negative) << 7)
            | (int(self.overflow) << 6)
            | 0x20
            | (int(break_flag) << 4)
            | (int(self.decimal) << 3)
            | (int(self.interrupt_disable) << 2)
            | (int(self.zero) << 1)
            | int(self.carry)
        )

    @classmethod
    def from_byte(cls, value: int) -> StatusFlags:
        """Decode a status byte, discarding its context-only B bit."""
        value = _require_byte(value, "status byte")
        return cls(
            negative=bool(value & 0x80),
            overflow=bool(value & 0x40),
            decimal=bool(value & 0x08),
            interrupt_disable=bool(value & 0x04),
            zero=bool(value & 0x02),
            carry=bool(value & 0x01),
        )


@dataclass
class CPUState:
    """Complete register state for an NMOS 6502 core.

    ``cycles`` is host-visible execution accounting. It is deliberately separate
    from register state transitions: a dispatcher records the cycles consumed by
    the context returned from a boundary step.
    """

    accumulator: Accumulator = field(default_factory=Accumulator)
    index: IndexRegisters = field(default_factory=IndexRegisters)
    program_counter: ProgramCounter = field(default_factory=ProgramCounter)
    stack_pointer: StackPointer = field(default_factory=lambda: StackPointer(0xFD))
    status: StatusFlags = field(default_factory=StatusFlags)
    cycles: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.accumulator, int) and not isinstance(self.accumulator, bool):
            self.accumulator = Accumulator(self.accumulator)
        if isinstance(self.program_counter, int) and not isinstance(
            self.program_counter, bool
        ):
            self.program_counter = ProgramCounter(self.program_counter)
        if isinstance(self.stack_pointer, int) and not isinstance(
            self.stack_pointer, bool
        ):
            self.stack_pointer = StackPointer(self.stack_pointer)
        if not isinstance(self.accumulator, Accumulator):
            raise TypeError("accumulator must be an accumulator or integer")
        if not isinstance(self.index, IndexRegisters):
            raise TypeError("index must be index registers")
        if not isinstance(self.program_counter, ProgramCounter):
            raise TypeError("program_counter must be a program counter or integer")
        if not isinstance(self.stack_pointer, StackPointer):
            raise TypeError("stack_pointer must be a stack pointer or integer")
        if not isinstance(self.status, StatusFlags):
            raise TypeError("status must be status flags")
        if isinstance(self.cycles, bool) or not isinstance(self.cycles, int):
            raise TypeError("cycles must be an integer")
        if self.cycles < 0:
            raise ValueError("cycles must not be negative")

    @property
    def a(self) -> Accumulator:
        return self.accumulator

    @property
    def x(self) -> IndexRegister:
        return self.index.x

    @property
    def y(self) -> IndexRegister:
        return self.index.y

    @property
    def pc(self) -> ProgramCounter:
        return self.program_counter

    @property
    def sp(self) -> StackPointer:
        return self.stack_pointer


__all__ = (
    "Accumulator",
    "CPUState",
    "IndexRegister",
    "IndexRegisters",
    "ProgramCounter",
    "Register8",
    "Register16",
    "StackPointer",
    "StatusFlags",
)
