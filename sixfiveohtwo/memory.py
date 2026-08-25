"""Machine-neutral host memory interface."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryBus(Protocol):
    """Byte-addressable memory supplied by the host machine.

    Addresses are inclusive and limited to ``0x0000`` through ``0xFFFF``.
    Values read from the bus and values written to it are bytes in the range
    ``0x00`` through ``0xFF``. Implementations must validate both arguments
    and raise ``TypeError`` for non-integer arguments or ``ValueError`` for
    integers outside those ranges; they must not silently wrap invalid input.

    A read result must be normalized to an integer in the byte range, even if
    the underlying storage uses a wider representation. The protocol does not
    require storage, allocate memory, or define address decoding or device
    behavior.
    """

    def read_byte(self, address: int, /) -> int:
        """Read and return the byte at a 16-bit address."""
        ...

    def write_byte(self, address: int, value: int, /) -> None:
        """Write a byte to a 16-bit address."""
        ...
