import importlib
import sys

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

    public_symbols = {name for name in vars(package) if not name.startswith("_")}

    assert package.__all__ == ("MemoryBus",)
    assert public_symbols == {"MemoryBus", "memory"}
