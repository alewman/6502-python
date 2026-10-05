"""DebugSession: breakpoints, bounded runs, history, access tracking and watchpoints.

The session never changes what the core does; the one thing it predicts,
``next_boundary``, is checked against what ``step()`` then actually does for
each kind of boundary the 6502 has.
"""

from collections.abc import Callable
from dataclasses import replace

import pytest

from sixfiveohtwo import (
    BoundaryKind,
    CPUState,
    DebugSession,
    DebugTarget,
    RunResult,
    StopReason,
    next_boundary,
)
from tests.conftest import Host

VECTORS = (0x00, 0x04, 0x00, 0x05, 0x00, 0x03)  # NMI $0400, RESET $0500, IRQ $0300
NOP, JAM, CLI, SEI = 0xEA, 0x02, 0x58, 0x78
# LDA #$55; STA $10; LDA $10; JAM
PROGRAM = (0xA9, 0x55, 0x85, 0x10, 0xA5, 0x10, JAM)


def _session(*program: int, **options: object) -> tuple[Host, DebugSession]:
    machine = Host(program)
    machine.load(0xFFFA, VECTORS)
    machine.cpu.s = 0xFF
    return machine, DebugSession(machine.cpu, peek_byte=machine.peek, **options)  # type: ignore[arg-type]


def test_step_records_disassembly_state_delta_and_totals() -> None:
    _machine, session = _session(0xA9, 0x2A)

    record = session.step()

    assert (record.sequence, record.kind) == (0, BoundaryKind.INSTRUCTION)
    assert record.instruction is not None and record.instruction.text == "LDA #$2A"
    assert (record.before.pc, record.after.pc, record.after.a, record.cycles) == (
        0x0200,
        0x0202,
        0x2A,
        2,
    )
    assert (session.total_steps, session.total_instructions, session.total_cycles) == (1, 1, 2)
    assert session.history == (record,)
    assert record.accesses is None and not session.tracking


def test_breakpoint_stops_before_the_instruction_and_step_crosses_it() -> None:
    machine, session = _session(NOP, NOP, NOP)
    session.add_breakpoint(0x0201)

    result = session.run(max_steps=10)

    assert result.reason is StopReason.BREAKPOINT
    assert (result.steps, result.instructions, result.cycles, machine.cpu.pc) == (1, 1, 2, 0x0201)
    assert session.run(max_steps=10).steps == 0  # still sitting on it
    assert session.step().after.pc == 0x0202
    session.remove_breakpoint(0x0201)
    assert session.breakpoints == set()


def test_jam_stops_a_run_as_halted_without_idling() -> None:
    machine, session = _session(NOP, JAM)

    result = session.run(max_steps=10)

    assert result.reason is StopReason.HALTED
    assert (result.steps, result.instructions, result.cycles) == (2, 2, 13)
    assert machine.cpu.halted and result.state.halted


def test_run_can_consume_jam_idle_boundaries_explicitly() -> None:
    _machine, session = _session(JAM)
    session.step()

    result = session.run(max_steps=3, stop_on_halt=False)

    assert result.reason is StopReason.STEP_LIMIT
    assert (result.steps, result.instructions, result.cycles) == (3, 0, 3)
    assert [record.kind for record in session.history[-3:]] == [BoundaryKind.JAM_IDLE] * 3


def test_cycle_budget_is_checked_after_an_atomic_boundary() -> None:
    _machine, session = _session(0xAD, 0x00, 0x10, NOP)  # LDA $1000 (4 cycles)

    result = session.run(max_steps=10, max_cycles=3)

    assert result.reason is StopReason.CYCLE_LIMIT
    assert (result.steps, result.cycles, result.state.pc) == (1, 4, 0x0203)


def test_history_is_a_bounded_ring_clearable_and_optionally_disabled() -> None:
    _machine, session = _session(NOP, NOP, NOP, history_limit=2)
    session.run(max_steps=3)

    assert [record.sequence for record in session.history] == [1, 2]
    assert [record.sequence for record in session.iter_history(newest_first=True)] == [2, 1]
    session.clear_history()
    assert (session.history, session.total_steps) == ((), 3)

    _machine, disabled = _session(NOP, history_limit=0)
    assert (disabled.step().sequence, disabled.history) == (0, ())


def test_session_without_peek_steps_but_does_not_disassemble() -> None:
    machine = Host((NOP,))
    record = DebugSession(machine.cpu).step()
    assert (record.instruction, record.after.pc) == (None, 0x0201)


def test_tracked_steps_record_every_bus_access_in_order() -> None:
    _machine, session = _session(*PROGRAM, track_accesses=True)
    records = [session.step() for _ in range(3)]
    assert [record.accesses for record in records] == [
        (("r", 0x0200, 0xA9), ("r", 0x0201, 0x55)),
        (("r", 0x0202, 0x85), ("r", 0x0203, 0x10), ("w", 0x0010, 0x55)),
        (("r", 0x0204, 0xA5), ("r", 0x0205, 0x10), ("r", 0x0010, 0x55)),
    ]
    assert all(len(record.accesses or ()) == record.cycles for record in records)


@pytest.mark.parametrize(
    ("kind", "steps", "hit"),
    [("w", 2, ("w", 0x10, 0x55)), ("r", 3, ("r", 0x10, 0x55)), ("rw", 2, ("w", 0x10, 0x55))],
)
def test_watchpoint_stops_after_the_step_that_touches_the_byte(
    kind: str, steps: int, hit: tuple[str, int, int]
) -> None:
    _machine, session = _session(*PROGRAM, track_accesses=True)
    session.add_watchpoint(0x10, kind)

    result = session.run(max_steps=100)

    assert (result.reason, result.steps, result.hits) == (StopReason.WATCHPOINT, steps, (hit,))
    assert result.state == result.last_record.after  # type: ignore[union-attr]


def test_watchpoints_need_tracking_and_a_valid_kind() -> None:
    _machine, untracked = _session(*PROGRAM)
    with pytest.raises(ValueError, match="track_accesses"):
        untracked.add_watchpoint(0x10)
    _machine, session = _session(*PROGRAM, track_accesses=True)
    with pytest.raises(ValueError, match="kind"):
        session.add_watchpoint(0x10, "x")
    session.add_watchpoint(0x10)
    session.remove_watchpoint(0x10)
    assert session.run(max_steps=100).reason is StopReason.HALTED


def test_close_gives_the_cpu_its_own_bus_callables_back() -> None:
    machine, session = _session(NOP, NOP, track_accesses=True)
    assert machine.cpu.read_byte != machine.read_byte
    session.step()
    assert machine.accesses == [("r", 0x0200, NOP), ("r", 0x0201, NOP)]  # host still sees it

    session.close()

    assert (machine.cpu.read_byte, machine.cpu.write_byte) == (
        machine.read_byte,
        machine.write_byte,
    )
    assert session.step().accesses is None and not session.tracking


def test_a_board_target_has_its_cpu_bus_tracked() -> None:
    machine = Host((NOP, NOP))

    class Board:
        cpu = machine.cpu

        def step(self) -> int:
            return self.cpu.step()

        def capture_state(self) -> CPUState:
            return self.cpu.capture_state()

    session = DebugSession(Board(), track_accesses=True)
    assert session.cpu is machine.cpu
    assert session.step().accesses == (("r", 0x0200, NOP), ("r", 0x0201, NOP))


def _then(*actions: Callable[[Host], None]) -> Callable[[Host], None]:
    def apply(machine: Host) -> None:
        for action in actions:
            action(machine)

    return apply


def _p(value: int) -> Callable[[Host], None]:
    return lambda machine: setattr(machine.cpu, "p", value)


def _irq(machine: Host) -> None:
    machine.cpu.request_maskable_interrupt()


def _nmi(machine: Host) -> None:
    machine.cpu.request_non_maskable_interrupt()


def _reset(machine: Host) -> None:
    machine.cpu.request_reset()


def _step(machine: Host) -> None:
    machine.cpu.step()


@pytest.mark.parametrize(
    ("program", "setup", "expected", "cycles"),
    [
        ((NOP,), _p(0x24), BoundaryKind.INSTRUCTION, 2),
        ((NOP,), _reset, BoundaryKind.RESET, 7),
        ((JAM,), _then(_step, _reset, _nmi), BoundaryKind.RESET, 7),  # reset restarts JAM
        ((JAM,), _step, BoundaryKind.JAM_IDLE, 1),
        ((JAM,), _then(_step, _nmi, _irq, _p(0x20)), BoundaryKind.JAM_IDLE, 1),
        ((NOP,), _then(_p(0x24), _nmi, _irq), BoundaryKind.NMI, 7),
        ((NOP,), _then(_p(0x20), _irq), BoundaryKind.IRQ, 7),
        ((NOP,), _then(_p(0x24), _irq), BoundaryKind.INSTRUCTION, 2),
        # CLI: I is clear in P, but this boundary's poll saw it set.
        ((CLI, NOP), _then(_p(0x24), _irq, _step), BoundaryKind.INSTRUCTION, 2),
        ((CLI, NOP), _then(_p(0x24), _irq, _step, _step), BoundaryKind.IRQ, 7),
        # SEI: I is set in P, but this boundary's poll saw it clear.
        ((SEI, NOP), _then(_p(0x20), _step, _irq), BoundaryKind.IRQ, 7),
        ((SEI, NOP, NOP), _then(_p(0x20), _step, _step, _irq), BoundaryKind.INSTRUCTION, 2),
    ],
)
def test_next_boundary_predicts_what_step_does(
    program: tuple[int, ...], setup: Callable[[Host], None], expected: BoundaryKind, cycles: int
) -> None:
    machine, session = _session(*program)
    setup(machine)

    assert next_boundary(machine.cpu.capture_state()) is expected
    record = session.step()

    assert (record.kind, record.cycles) == (expected, cycles)
    assert (record.instruction is None) == (expected is not BoundaryKind.INSTRUCTION)
    assert session.total_instructions == (expected is BoundaryKind.INSTRUCTION)


def test_irq_stays_asserted_after_entry_so_the_handler_must_release_it() -> None:
    machine, session = _session(NOP)
    machine.load(0x0300, (CLI, NOP))  # re-enables without acknowledging; CLI delays the poll
    machine.cpu.p = 0x20
    machine.cpu.request_maskable_interrupt()
    kinds = [session.step().kind for _ in range(4)]
    assert kinds == [
        BoundaryKind.IRQ,
        BoundaryKind.INSTRUCTION,
        BoundaryKind.INSTRUCTION,
        BoundaryKind.IRQ,
    ]


def test_debug_target_is_a_runtime_checkable_protocol() -> None:
    assert isinstance(Host().cpu, DebugTarget)
    assert not isinstance(object(), DebugTarget)
    with pytest.raises(TypeError, match="step"):
        DebugSession(object())  # type: ignore[arg-type]


def test_public_debug_values_reject_invalid_construction() -> None:
    _machine, session = _session(NOP)
    record = session.step()

    with pytest.raises(ValueError, match="sequence"):
        replace(record, sequence=-1)
    with pytest.raises(ValueError, match="lifecycle"):
        replace(record, kind=BoundaryKind.RESET)
    with pytest.raises(ValueError, match="cycles"):
        replace(record, cycles=0)
    with pytest.raises(ValueError, match="accesses"):
        replace(record, accesses=(("in", 0, 0),))
    with pytest.raises(ValueError, match="instructions cannot exceed"):
        RunResult(StopReason.STEP_LIMIT, 0, 1, 0, record.after, None)
    with pytest.raises(ValueError, match="last_record"):
        RunResult(StopReason.STEP_LIMIT, 1, 1, 2, record.after, object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"max_steps": 0}, "max_steps"),
        ({"max_steps": 1, "max_cycles": 0}, "max_cycles"),
        ({"max_steps": 1, "stop_on_halt": 1}, "stop_on_halt"),
    ],
)
def test_run_rejects_invalid_or_unbounded_limits(
    arguments: dict[str, object], message: str
) -> None:
    _machine, session = _session(NOP)
    with pytest.raises(ValueError, match=message):
        session.run(**arguments)  # type: ignore[arg-type]
