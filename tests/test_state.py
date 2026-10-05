"""CPUState: capture and restore round-trip, and the value's own validation.

A captured state is everything the CPU owns (registers, the interrupt and
reset requests not yet taken, JAM, and the one-boundary I-flag poll CLI, SEI
and PLP leave behind), and nothing the host owns.
"""

from dataclasses import FrozenInstanceError, replace

import pytest

from sixfiveohtwo import CPUState
from tests.conftest import Host

CLI, SEI, NOP = 0x58, 0x78, 0xEA


def test_a_new_cpu_captures_zeroed_registers_with_i_set() -> None:
    assert Host(at=0).cpu.capture_state() == CPUState()


def test_capture_and_restore_round_trip_all_cpu_owned_state_without_touching_host() -> None:
    machine = Host((CLI,))
    cpu = machine.cpu
    cpu.a, cpu.x, cpu.y, cpu.s, cpu.p = 0x12, 0x34, 0x56, 0x78, 0xE5  # I set
    machine.step()  # CLI: P now has I clear, the poll still saw it set
    cpu.request_reset()
    cpu.request_maskable_interrupt()
    cpu.request_non_maskable_interrupt()
    cpu.halted = True
    machine.memory[0x1234] = 0x56

    state = cpu.capture_state()
    assert state == CPUState(
        a=0x12,
        x=0x34,
        y=0x56,
        s=0x78,
        pc=0x0201,
        p=0xE1,
        halted=True,
        reset_pending=True,
        maskable_interrupt_pending=True,
        non_maskable_interrupt_pending=True,
        polled_i=True,
    )
    cpu.restore_state(CPUState())
    assert cpu.capture_state() == CPUState()
    assert not (cpu.reset_pending or cpu.maskable_interrupt_pending)
    cpu.restore_state(state)
    assert cpu.capture_state() == state
    assert machine.memory[0x1234] == 0x56
    assert machine.accesses == [("r", 0x0200, CLI), ("r", 0x0201, 0)]  # capture reads nothing


@pytest.mark.parametrize("polled_i", [None, False, True])
def test_polled_i_round_trips_in_each_of_its_three_values(polled_i: bool | None) -> None:
    cpu = Host().cpu
    state = replace(cpu.capture_state(), polled_i=polled_i)
    cpu.restore_state(state)
    assert cpu.capture_state().polled_i is polled_i


@pytest.mark.parametrize("opcode", [CLI, SEI])
def test_restored_poll_delay_and_irq_continue_identically(opcode: int) -> None:
    machine = Host((opcode, NOP, NOP))
    machine.load(0xFFFE, (0x00, 0x03))
    cpu = machine.cpu
    cpu.s = 0xFF
    cpu.p = 0x24 if opcode == CLI else 0x20
    machine.step()
    cpu.request_maskable_interrupt()
    state = cpu.capture_state()
    memory = bytes(machine.memory)

    first = (machine.step(), machine.step(), cpu.capture_state())
    machine.memory[:] = memory
    cpu.restore_state(state)
    second = (machine.step(), machine.step(), cpu.capture_state())

    assert second == first


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("a", -1, "a must be"),
        ("x", 0x100, "x must be"),
        ("y", True, "y must be"),
        ("s", 1.0, "s must be"),
        ("pc", 0x1_0000, "pc must be"),
        ("p", 0x100, "p must be"),
        ("p", 0x04, "bit 5 set"),
        ("p", 0x34, "B"),
        ("halted", 1, "halted must be a bool"),
        ("reset_pending", None, "reset_pending"),
        ("maskable_interrupt_pending", 0, "maskable_interrupt_pending"),
        ("non_maskable_interrupt_pending", "yes", "non_maskable_interrupt_pending"),
        ("polled_i", 0, "polled_i must be a bool"),
    ],
)
def test_cpu_state_rejects_values_outside_its_contract(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(CPUState(), **{field: value})


def test_cpu_state_is_frozen_and_restore_requires_one() -> None:
    state = CPUState()
    with pytest.raises(FrozenInstanceError):
        state.pc = 1  # type: ignore[misc]
    with pytest.raises(TypeError, match="CPUState"):
        Host().cpu.restore_state({})  # type: ignore[arg-type]
