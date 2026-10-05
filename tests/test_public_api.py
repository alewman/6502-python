"""The package's public surface: ``__all__`` is exactly what it exports, and nothing private.

Also the embedding contract a consumer meets first: the CPU takes two bus
callables, validates them, and lets them be replaced.
"""

import importlib
import inspect
import types

import pytest

import sixfiveohtwo
from sixfiveohtwo import MOS6502

SUBMODULES = ("console", "cpu", "debug", "disasm", "state", "trace")


def test_all_is_exactly_the_public_names_the_package_binds() -> None:
    public = {
        name
        for name, value in vars(sixfiveohtwo).items()
        if not name.startswith("_") and not isinstance(value, types.ModuleType)
    }
    assert len(sixfiveohtwo.__all__) == len(set(sixfiveohtwo.__all__))
    assert set(sixfiveohtwo.__all__) == public


def test_star_import_gives_exactly_all() -> None:
    namespace: dict[str, object] = {}
    exec("from sixfiveohtwo import *", namespace)
    namespace.pop("__builtins__")
    assert set(namespace) == set(sixfiveohtwo.__all__)


@pytest.mark.parametrize("name", sixfiveohtwo.__all__)
def test_each_export_comes_from_a_public_module_that_exports_it(name: str) -> None:
    assert not name.startswith("_")
    value = getattr(sixfiveohtwo, name)
    homes = [
        module
        for module in (importlib.import_module(f"sixfiveohtwo.{sub}") for sub in SUBMODULES)
        if name in module.__all__
    ]
    assert homes, f"{name} is not in any public submodule's __all__"
    assert all(getattr(module, name) is value for module in homes)
    if inspect.isclass(value) or inspect.isfunction(value):
        assert value.__module__ in {f"sixfiveohtwo.{sub}" for sub in SUBMODULES}


def test_submodule_all_names_resolve() -> None:
    for sub in SUBMODULES:
        module = importlib.import_module(f"sixfiveohtwo.{sub}")
        for name in module.__all__:
            assert hasattr(module, name), f"sixfiveohtwo.{sub}.__all__ names missing {name}"


def test_flag_constants_are_the_p_register_bits() -> None:
    flags = [getattr(sixfiveohtwo, f"FLAG_{letter}") for letter in "NVUBDIZC"]
    assert flags == [0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01]


def test_two_callables_are_a_complete_host() -> None:
    memory = bytearray(0x10000)
    memory[0:2] = bytes((0xA9, 0x2A))  # LDA #$2A
    cpu = MOS6502(memory.__getitem__, memory.__setitem__)
    assert (cpu.step(), cpu.a, cpu.pc) == (2, 0x2A, 2)


def test_bus_callables_are_validated_and_replaceable() -> None:
    memory = bytearray(0x10000)
    with pytest.raises(TypeError, match="write_byte must be callable"):
        MOS6502(memory.__getitem__, memory)  # type: ignore[arg-type]

    class OldBus:
        def read_byte(self, address: int) -> int:
            return 0

        def write_byte(self, address: int, value: int) -> None:
            pass

    with pytest.raises(TypeError, match=r"MOS6502\(bus.read_byte, bus.write_byte\)"):
        MOS6502(OldBus(), OldBus())  # type: ignore[arg-type]

    cpu = MOS6502(memory.__getitem__, memory.__setitem__)
    reads: list[int] = []
    cpu.read_byte = lambda address: reads.append(address) or memory[address]
    cpu.step()  # BRK from zeroed memory: opcode, padding, then the stack and vector
    assert reads[:2] == [0x0000, 0x0001]
