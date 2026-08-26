import importlib
import sys
import types

import pytest


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="sixfiveohtwo requires Python 3.12+"
)
def test_package_imports_on_supported_python():
    package = importlib.import_module("sixfiveohtwo")

    assert package.__name__ == "sixfiveohtwo"


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="sixfiveohtwo requires Python 3.12+"
)
def test_package_exposes_memory_bus():
    package = importlib.import_module("sixfiveohtwo")

    # Excludes submodules: importing any lazily-loaded name (e.g. CPU) attaches
    # its owning submodule to the package namespace as an unavoidable CPython
    # side effect, independent of test order or what other tests imported.
    public_symbols = {
        name
        for name, value in vars(package).items()
        if not name.startswith("_") and not isinstance(value, types.ModuleType)
    }

    assert package.__all__ == ("MemoryBus",)
    assert public_symbols == {"MemoryBus"}
