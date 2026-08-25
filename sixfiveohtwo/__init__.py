"""Core package for the 6502-python distribution.

The distribution is installed as ``6502-python`` and imported as
``sixfiveohtwo``.
"""

from importlib import import_module as _import_module

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
        cpu = _import_module(".cpu", __name__)
        try:
            return getattr(cpu, name)
        finally:
            globals().pop("cpu", None)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ("MemoryBus",)
