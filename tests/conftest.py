"""The one test host every test file shares.

``Host`` is a flat 64 KiB RAM behind the two bus callables, recording every
access in order, so a test can check the exact cycle-by-cycle bus traffic
the way the SingleStepTests host does.
"""

from collections.abc import Sequence

from sixfiveohtwo import MOS6502

Access = tuple[str, int, int]


class Host:
    """A 64 KiB RAM host that logs every bus access as ("r" | "w", address, value)."""

    def __init__(self, program: Sequence[int] = (), *, at: int = 0x0200) -> None:
        self.memory = bytearray(0x10000)
        self.memory[at : at + len(program)] = bytes(program)
        self.accesses: list[Access] = []
        self.cpu = MOS6502(self.read_byte, self.write_byte)
        self.cpu.pc = at

    def read_byte(self, address: int) -> int:
        value = self.memory[address]
        self.accesses.append(("r", address, value))
        return value

    def write_byte(self, address: int, value: int) -> None:
        self.accesses.append(("w", address, value))
        self.memory[address] = value

    def peek(self, address: int) -> int:
        """Read memory without touching the bus log (a debugger's peek)."""
        return self.memory[address]

    def load(self, address: int, data: Sequence[int]) -> None:
        self.memory[address : address + len(data)] = bytes(data)

    def step(self) -> int:
        """Step the CPU once, with a fresh access log."""
        self.accesses.clear()
        cycles = self.cpu.step()
        assert cycles == len(self.accesses), "every cycle is exactly one bus access"
        return cycles
