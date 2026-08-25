import pytest

from sixfiveohtwo import MemoryBus


class HostMemory:
    def __init__(self):
        self.bytes = {}
        self.operations = []

    def read_byte(self, address: int) -> int:
        self._validate_address(address)
        self.operations.append(("read", address))
        return self.bytes.get(address, 0)

    def write_byte(self, address: int, value: int) -> None:
        self._validate_address(address)
        self._validate_value(value)
        self.operations.append(("write", address, value))
        self.bytes[address] = value

    @staticmethod
    def _validate_address(address: int) -> None:
        if not isinstance(address, int):
            raise TypeError("address must be an integer")
        if not 0x0000 <= address <= 0xFFFF:
            raise ValueError("address must fit in 16 bits")

    @staticmethod
    def _validate_value(value: int) -> None:
        if not isinstance(value, int):
            raise TypeError("value must be an integer")
        if not 0x00 <= value <= 0xFF:
            raise ValueError("value must fit in one byte")


def test_memory_bus_is_structurally_runtime_checkable():
    assert isinstance(HostMemory(), MemoryBus)


def test_host_memory_owns_reads_and_writes_at_address_boundaries():
    host = HostMemory()

    host.write_byte(0x0000, 0x00)
    host.write_byte(0xFFFF, 0xFF)

    assert host.read_byte(0x0000) == 0x00
    assert host.read_byte(0xFFFF) == 0xFF
    assert host.bytes == {0x0000: 0x00, 0xFFFF: 0xFF}


def test_host_memory_accepts_only_byte_values_and_16_bit_addresses():
    host = HostMemory()

    for address in (-1, 0x10000):
        with pytest.raises(ValueError):
            host.read_byte(address)
        with pytest.raises(ValueError):
            host.write_byte(address, 0x00)

    for value in (-1, 0x100):
        with pytest.raises(ValueError):
            host.write_byte(0x0000, value)


def test_memory_bus_adds_no_machine_specific_device_behavior():
    host = HostMemory()

    host.write_byte(0xD012, 0xA5)

    assert host.read_byte(0xD012) == 0xA5
    assert host.operations == [("write", 0xD012, 0xA5), ("read", 0xD012)]
