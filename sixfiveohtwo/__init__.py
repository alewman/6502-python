"""Core package for the 6502-python distribution.

The distribution is installed as ``6502-python`` and imported as
``sixfiveohtwo``.
"""

from .memory import MemoryBus


# Keep the small root namespace while making the state types convenient to import.
def __getattr__(name: str):
    if name in {
        "Accumulator",
        "CPUState",
        "IndexRegister",
        "IndexRegisters",
        "ProgramCounter",
        "Register8",
        "Register16",
        "StackPointer",
        "StatusFlags",
    }:
        from . import cpu

        return getattr(cpu, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ("MemoryBus",)
