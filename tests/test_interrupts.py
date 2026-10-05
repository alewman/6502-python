"""Reset, IRQ, NMI and JAM: the boundaries SingleStepTests does not cover.

SingleStepTests runs one instruction from a register image, so the start
sequence, interrupt entry, the one-instruction delay after CLI, SEI and PLP,
and JAM's aftermath are checked here, bus cycle by bus cycle, against the
sources the core cites (PM section 9.2; HM p. A-11; NMS pp. 83, 47; NESdev).
"""

import pytest

from sixfiveohtwo import FLAG_I, MOS6502
from tests.conftest import Host

# Programs sit at $0200; the vectors point at $0300 (IRQ), $0400 (NMI), $0500 (reset).
VECTORS = (0x00, 0x04, 0x00, 0x05, 0x00, 0x03)  # $FFFA NMI, $FFFC RESET, $FFFE IRQ/BRK
NOP, CLI, SEI, PLP, PHP, INX, BRK, JAM = 0xEA, 0x58, 0x78, 0x28, 0x08, 0xE8, 0x00, 0x02


def host(*program: int) -> Host:
    machine = Host(program)
    machine.load(0xFFFA, VECTORS)
    return machine


def test_reset_is_seven_cycles_three_stack_reads_and_no_writes() -> None:
    machine = host()
    cpu = machine.cpu
    cpu.s = 0x40
    cpu.p = 0x20
    cpu.request_reset()
    assert machine.step() == 7
    assert machine.accesses == [
        ("r", 0x0200, 0),
        ("r", 0x0200, 0),
        ("r", 0x0140, 0),
        ("r", 0x013F, 0),
        ("r", 0x013E, 0),
        ("r", 0xFFFC, 0x00),
        ("r", 0xFFFD, 0x05),
    ]
    assert (cpu.pc, cpu.s, cpu.p) == (0x0500, 0x3D, 0x20 | FLAG_I)
    assert not cpu.reset_pending


def test_irq_entry_pushes_pc_and_p_with_b_clear() -> None:
    machine = host(NOP)
    cpu = machine.cpu
    cpu.s = 0xFF
    cpu.p = 0x20 | 0x01  # I clear, C set
    cpu.request_maskable_interrupt()
    assert machine.step() == 7
    assert machine.accesses == [
        ("r", 0x0200, NOP),
        ("r", 0x0200, NOP),
        ("w", 0x01FF, 0x02),
        ("w", 0x01FE, 0x00),
        ("w", 0x01FD, 0x21),
        ("r", 0xFFFE, 0x00),
        ("r", 0xFFFF, 0x03),
    ]
    assert cpu.pc == 0x0300
    assert cpu.p & FLAG_I
    assert cpu.maskable_interrupt_pending, "IRQ is a level: the device releases it, not the CPU"


def test_masked_irq_waits_while_i_is_set() -> None:
    machine = host(NOP)
    cpu = machine.cpu
    cpu.p = 0x24
    cpu.request_maskable_interrupt()
    assert machine.step() == 2  # the NOP: I is set
    assert cpu.pc == 0x0201


def test_nmi_is_edge_latched_and_ignores_i() -> None:
    machine = host(NOP)
    cpu = machine.cpu
    cpu.s = 0xFF
    cpu.p = 0x24
    cpu.request_non_maskable_interrupt()
    cpu.request_non_maskable_interrupt()  # coalesces
    assert machine.step() == 7
    assert cpu.pc == 0x0400
    assert not cpu.non_maskable_interrupt_pending
    machine.load(0x0400, (NOP,))
    assert machine.step() == 2  # one edge, one NMI


def test_nmi_wins_over_irq_at_the_same_boundary() -> None:
    machine = host(NOP)
    cpu = machine.cpu
    cpu.p = 0x20
    cpu.request_maskable_interrupt()
    cpu.request_non_maskable_interrupt()
    machine.step()
    assert cpu.pc == 0x0400


def test_cli_lets_one_more_instruction_run_before_a_waiting_irq() -> None:
    machine = host(CLI, INX, INX)
    cpu = machine.cpu
    cpu.p = 0x24
    cpu.request_maskable_interrupt()
    machine.step()  # CLI: the poll saw I set
    assert cpu.pc == 0x0201
    machine.step()  # INX runs before the IRQ is taken
    assert (cpu.pc, cpu.x) == (0x0202, 1)
    assert machine.step() == 7
    assert cpu.pc == 0x0300


def test_sei_still_takes_an_irq_polled_before_it() -> None:
    machine = host(SEI, INX)
    cpu = machine.cpu
    cpu.s = 0xFF
    cpu.p = 0x20
    machine.step()  # SEI with no IRQ yet
    cpu.request_maskable_interrupt()
    assert machine.step() == 7, "the poll after SEI saw I clear"
    assert cpu.pc == 0x0300
    assert machine.memory[0x01FD] & FLAG_I, "the pushed P already has I set"


def test_plp_clearing_i_delays_a_waiting_irq_by_one_instruction() -> None:
    machine = host(PLP, INX)
    cpu = machine.cpu
    cpu.s = 0xFE
    machine.memory[0x01FF] = 0x20  # P with I clear
    cpu.p = 0x24
    cpu.request_maskable_interrupt()
    machine.step()
    assert cpu.p == 0x20
    machine.step()
    assert cpu.x == 1
    assert machine.step() == 7


def test_rti_restoring_i_clear_takes_a_waiting_irq_at_once() -> None:
    machine = host(0x40)  # RTI
    cpu = machine.cpu
    cpu.s = 0xFC
    machine.load(0x01FD, (0x20, 0x00, 0x06))  # P (I clear), return address $0600
    cpu.p = 0x24
    cpu.request_maskable_interrupt()
    machine.step()
    assert cpu.pc == 0x0600
    assert machine.step() == 7
    assert cpu.pc == 0x0300


def test_nmi_during_brk_takes_the_nmi_vector_with_brks_frame() -> None:
    machine = host(BRK, 0xFF)
    cpu = machine.cpu
    cpu.s = 0xFF
    cpu.p = 0x20
    write = cpu.write_byte

    def device_write(address: int, value: int) -> None:
        write(address, value)
        if address == 0x01FF:  # the NMI edge arrives during BRK's first push
            cpu.request_non_maskable_interrupt()

    cpu.write_byte = device_write
    assert cpu.step() == 7
    assert cpu.pc == 0x0400
    assert machine.memory[0x01FD] == 0x30, "BRK's frame: B set"
    assert not cpu.non_maskable_interrupt_pending


def test_brk_pushes_pc_plus_two_and_b_set() -> None:
    machine = host(BRK, 0xFF)
    cpu = machine.cpu
    cpu.s = 0xFF
    cpu.p = 0x20
    assert machine.step() == 7
    assert machine.memory[0x01FE:0x0200] == bytes((0x02, 0x02))
    assert machine.memory[0x01FD] == 0x30
    assert cpu.pc == 0x0300


def test_jam_stops_the_cpu_until_reset_and_ignores_interrupts() -> None:
    machine = host(JAM)
    cpu = machine.cpu
    cpu.p = 0x20
    assert machine.step() == 11
    assert cpu.halted
    cpu.request_non_maskable_interrupt()
    cpu.request_maskable_interrupt()
    assert machine.step() == 1
    assert machine.accesses == [("r", 0xFFFF, 0x03)]
    assert cpu.pc == 0x0201
    cpu.request_reset()
    assert machine.step() == 7
    assert not cpu.halted
    assert cpu.pc == 0x0500


def test_old_single_object_bus_gets_a_message_naming_the_new_form() -> None:
    class Bus:
        def read_byte(self, address: int) -> int:
            return 0

        def write_byte(self, address: int, value: int) -> None:
            pass

    with pytest.raises(TypeError, match=r"MOS6502\(bus\.read_byte, bus\.write_byte\)"):
        MOS6502(Bus(), None)  # type: ignore[arg-type]
