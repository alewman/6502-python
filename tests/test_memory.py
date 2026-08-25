from sixfiveohtwo import MemoryBus


def test_memory_bus_is_structurally_runtime_checkable():
    class HostMemory:
        def read_byte(self, address: int) -> int:
            return address & 0xFF

        def write_byte(self, address: int, value: int) -> None:
            pass

    assert isinstance(HostMemory(), MemoryBus)
