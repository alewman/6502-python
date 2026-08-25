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
        "AddressingMode",
        "AddressingResult",
        "CPU",
        "OpcodeDefinition",
        "UnsupportedOpcodeError",
        "ResetStep",
        "CPUState",
        "IndexRegister",
        "IndexRegisters",
        "InterruptBoundary",
        "InterruptLines",
        "ProgramCounter",
        "Register8",
        "Register16",
        "StackPointer",
        "StatusFlags",
        "pack_status_byte",
        "unpack_status_byte",
    }:
        if name in {
            "CPU",
            "AddressingMode",
            "AddressingResult",
            "OpcodeDefinition",
            "UnsupportedOpcodeError",
            "ResetStep",
        }:
            module_name = ".core"
        elif name in {"InterruptBoundary", "InterruptLines"}:
            module_name = ".interrupts"
        else:
            module_name = ".cpu"
        module = _import_module(module_name, __name__)
        try:
            return getattr(module, name)
        finally:
            globals().pop(module_name.removeprefix("."), None)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ("MemoryBus",)
