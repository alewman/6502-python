"""Run a three-instruction program using the public sixfiveohtwo API."""

from sixfiveohtwo import CPU, CPUState, MemoryBus


class HostMemory(MemoryBus):
    """A complete 64 KiB RAM bus owned by the embedding host."""

    def __init__(self) -> None:
        self.data = bytearray(0x10000)

    def read_byte(self, address: int, /) -> int:
        self._require_address(address)
        return self.data[address]

    def write_byte(self, address: int, value: int, /) -> None:
        self._require_address(address)
        self._require_byte(value)
        self.data[address] = value

    @staticmethod
    def _require_address(address: int) -> None:
        if type(address) is not int:
            raise TypeError("address must be an integer")
        if not 0 <= address <= 0xFFFF:
            raise ValueError("address must fit in 16 bits")

    @staticmethod
    def _require_byte(value: int) -> None:
        if type(value) is not int:
            raise TypeError("value must be an integer")
        if not 0 <= value <= 0xFF:
            raise ValueError("value must fit in 8 bits")


def main() -> None:
    memory = HostMemory()
    start = 0x8000
    # LDA #$2A; CLC; ADC #$10 leaves A holding $3A.
    program = (0xA9, 0x2A, 0x18, 0x69, 0x10)
    for offset, byte in enumerate(program):
        memory.write_byte(start + offset, byte)

    cpu = CPU(memory, state=CPUState(program_counter=start))
    for _ in range(3):
        cpu.step()

    print(
        f"A={cpu.state.a.value:02X} "
        f"PC={cpu.state.pc.value:04X} cycles={cpu.state.cycles}"
    )


if __name__ == "__main__":
    main()
