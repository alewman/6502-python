"""SHA, SHX, SHY and TAS after a DMA stretches the cycle before their write.

NMS p. 48 (its table): with no DMA in cycle N, the value stored is ANDed with
the base address's high byte plus one; with a DMA in cycle N it is the plain
value ("SHY becomes true STY"); across a page the address's high byte is
(H + 1) AND value either way. The core has no RDY input: the host says a read
was stretched by setting ``dma_stalled`` during it, and clears it on the next
read that was not, as famicom-python's board does. AccuracyCoin's
unofficial-opcode error codes 7-C (run by famicom-python) are the hardware
judge; these pin the rule here.
"""

import pytest

from sixfiveohtwo import MOS6502
from tests.conftest import Host


class StallingHost(Host):
    """A Host whose ``stalled``-th access of a step (from 1) is a DMA-stretched read."""

    def __init__(self, program: tuple[int, ...], stalled: int) -> None:
        super().__init__(program)
        self.stalled = stalled

    def read_byte(self, address: int) -> int:
        value = super().read_byte(address)
        self.cpu.dma_stalled = len(self.accesses) == self.stalled
        return value


def _store(program: tuple[int, ...], stalled: int, **registers: int) -> tuple[int, int]:
    """Run one instruction; return the (address, value) of its write."""
    host = StallingHost(program, stalled)
    for name, value in registers.items():
        setattr(host.cpu, name, value)
    host.cpu.step()
    writes = [(address, value) for kind, address, value in host.accesses if kind == "w"]
    assert len(writes) == 1
    return writes[0]


# (opcode bytes, the cycle N before the write, registers); base $0500, no page crossing.
STORES = [
    ((0x9C, 0x00, 0x05), 4, {"x": 0x00, "y": 0xA5}, 0xA5),  # SHY $0500,X
    ((0x9E, 0x00, 0x05), 4, {"y": 0x00, "x": 0xA5}, 0xA5),  # SHX $0500,Y
    ((0x9F, 0x00, 0x05), 4, {"y": 0x00, "a": 0xF5, "x": 0xAF}, 0xA5),  # SHA $0500,Y
    ((0x9B, 0x00, 0x05), 4, {"y": 0x00, "a": 0xF5, "x": 0xAF}, 0xA5),  # TAS $0500,Y
]


@pytest.mark.parametrize(("program", "cycle_n", "registers", "value"), STORES)
def test_a_stretched_cycle_n_drops_the_and(program, cycle_n, registers, value) -> None:
    # H + 1 = $06: without a DMA, $A5 AND $06 = $04.
    assert _store(program, 0, **registers) == (0x0500, value & 0x06)
    assert _store(program, cycle_n, **registers) == (0x0500, value)


def test_sha_indirect_y_has_its_cycle_n_fifth() -> None:
    # SHA ($10),Y with ($10) = $0500: opcode, operand, two pointer reads, the
    # dummy read (cycle N = 5), the write.
    program = (0x93, 0x10)
    registers = {"y": 0x00, "a": 0xF5, "x": 0xAF}

    def run(stalled: int) -> tuple[int, int]:
        host = StallingHost(program, stalled)
        host.memory[0x10:0x12] = bytes((0x00, 0x05))
        for name, value in registers.items():
            setattr(host.cpu, name, value)
        host.cpu.step()
        return next((a, v) for kind, a, v in host.accesses if kind == "w")

    assert run(0) == (0x0500, 0x04)
    assert run(4) == (0x0500, 0x04)  # a stretch two cycles early changes nothing
    assert run(5) == (0x0500, 0xA5)


def test_across_a_page_the_address_keeps_its_and() -> None:
    # SHX $10F0,Y with Y = $20: target $1110 crosses; (H + 1) AND X = $11 AND
    # $0F = $01 is the high byte written to either way.
    program = (0x9E, 0xF0, 0x10)
    assert _store(program, 0, x=0x0F, y=0x20) == (0x0110, 0x01)
    assert _store(program, 4, x=0x0F, y=0x20) == (0x0110, 0x0F)


def test_tas_sets_s_whatever_the_dma() -> None:
    for stalled in (0, 4):
        host = StallingHost((0x9B, 0x00, 0x05), stalled)
        host.cpu.a, host.cpu.x, host.cpu.y = 0xF5, 0xAF, 0x00
        host.cpu.step()
        assert host.cpu.s == 0xA5


def test_the_core_never_sets_it_itself() -> None:
    assert MOS6502.dma_stalled is False
    host = Host((0x9C, 0x00, 0x05))
    host.cpu.y = 0xA5
    host.cpu.step()
    assert host.cpu.dma_stalled is False
    assert host.memory[0x0500] == 0x04
