"""The command debugger: every command and alias, over a DebugSession on a Host.

Commands return rendered lines; malformed ones raise CommandError. The 6502
specifics are the register set (A X Y S P PC), ``irq on|off`` for the IRQ
level, ``reset`` running the seven-cycle start sequence, and ``over`` running
a JSR through to its return.
"""

from io import StringIO

import pytest

from sixfiveohtwo import CommandDebugger, CommandError, CommandResult, DebugSession
from tests.conftest import Host

VECTORS = (0x00, 0x04, 0x00, 0x05, 0x00, 0x03)  # NMI $0400, RESET $0500, IRQ $0300
# $0200: JSR $0300; NOP; LDA #$55; STA $10; NOP     $0300: INX; RTS
PROGRAM = (0x20, 0x00, 0x03, 0xEA, 0xA9, 0x55, 0x85, 0x10, 0xEA)


def _debugger(*, track_accesses: bool = False) -> tuple[Host, CommandDebugger]:
    machine = Host(PROGRAM)
    machine.load(0x0300, (0xE8, 0x60))
    machine.load(0xFFFA, VECTORS)
    machine.cpu.s = 0xFF
    session = DebugSession(
        machine.cpu, peek_byte=machine.peek, history_limit=16, track_accesses=track_accesses
    )
    return machine, CommandDebugger(session)


@pytest.mark.parametrize("command", ["registers", "regs", "r", "R"])
def test_registers_render_every_register_and_lifecycle_input(command: str) -> None:
    machine, debugger = _debugger()
    cpu = machine.cpu
    cpu.a, cpu.x, cpu.y, cpu.p = 0x12, 0x34, 0x56, 0xA5
    cpu.request_maskable_interrupt()
    assert debugger.execute(command).lines == (
        "PC=0200 A=12 X=34 Y=56 S=FF P=A5 N----I-C",
        "JAM=0 RESET=0 NMI=0 IRQ=1 POLLED_I=-",
    )


@pytest.mark.parametrize("command", ["help", "?"])
def test_help_lists_the_commands(command: str) -> None:
    lines = _debugger()[1].execute(command).lines
    assert lines[0].startswith("help | ?")
    assert any(line.startswith("irq on | irq off") for line in lines)


@pytest.mark.parametrize("command", ["quit", "exit", "q"])
def test_quit_and_its_aliases_end_the_loop(command: str) -> None:
    assert _debugger()[1].execute(command) == CommandResult(quit=True)


def test_blank_line_does_nothing() -> None:
    assert _debugger()[1].execute("   ") == CommandResult()


def test_step_and_its_count() -> None:
    machine, debugger = _debugger()
    assert debugger.execute("step").lines == ("#0 0200  20 00 03     JSR $0300 -> PC=0300 +6",)
    assert debugger.execute("s 2").lines == (
        "#1 0300  E8           INX -> PC=0301 +2",
        "#2 0301  60           RTS -> PC=0203 +6",
    )
    assert machine.cpu.pc == 0x0203


def test_over_runs_a_jsr_subroutine_through_to_its_return() -> None:
    machine, debugger = _debugger()
    lines = debugger.execute("over").lines
    assert lines[0] == "#0 0200  20 00 03     JSR $0300 -> PC=0300 +6"
    assert lines[1] == "PC=0203 A=00 X=01 Y=00 S=FF P=24 -----I--"
    assert (machine.cpu.pc, machine.cpu.s, machine.cpu.x) == (0x0203, 0xFF, 1)
    assert debugger.execute("o").lines == ("#3 0203  EA           NOP -> PC=0204 +2",)


def test_over_stops_at_a_breakpoint_inside_the_subroutine() -> None:
    machine, debugger = _debugger()
    debugger.execute("b $0301")
    assert debugger.execute("over").lines[1] == "breakpoint at 0301"
    assert machine.cpu.pc == 0x0301


def test_run_break_delete_breakpoints_continue_and_history() -> None:
    machine, debugger = _debugger()
    assert debugger.execute("break 0x0204").lines == ("breakpoint added at 0204",)
    assert debugger.execute("b $0206").lines == ("breakpoint added at 0206",)
    assert debugger.execute("breakpoints").lines == ("0204", "0206")
    assert debugger.execute("run 100").lines == (
        "stopped=breakpoint steps=4 instructions=4 cycles=16 PC=0204",
    )
    lines = debugger.execute("c").lines  # steps off the breakpoint first
    assert lines == (
        "#4 0204  A9 55        LDA #$55 -> PC=0206 +2",
        "stopped=breakpoint steps=0 instructions=0 cycles=0 PC=0206",
    )
    assert debugger.execute("delete 0x0204").lines == ("breakpoint removed from 0204",)
    debugger.execute("delete 0x0206")
    assert debugger.execute("breakpoints").lines == ("no breakpoints",)
    assert debugger.execute("run 5 3").lines == (
        "stopped=cycle_limit steps=1 instructions=1 cycles=3 PC=0208",
    )
    assert debugger.execute("history 2").lines == (
        "#4 0204  A9 55        LDA #$55 -> PC=0206 +2",
        "#5 0206  85 10        STA $10 -> PC=0208 +3",
    )
    assert machine.memory[0x10] == 0x55


def test_watch_and_unwatch() -> None:
    _machine, debugger = _debugger(track_accesses=True)
    assert debugger.execute("watch $10 w").lines == ("watchpoint added at 0010 (w)",)
    assert debugger.execute("watch 0x11").lines == ("watchpoint added at 0011 (rw)",)
    assert debugger.execute("breakpoints").lines == ("watch 0010 w", "watch 0011 rw")
    stopped = debugger.execute("continue").lines[-1]
    assert stopped == "stopped=watchpoint steps=6 instructions=6 cycles=21 PC=0208 w 0010=55"
    assert debugger.execute("unwatch 16").lines == ("watchpoint removed from 0010",)
    with pytest.raises(CommandError, match="kind"):
        debugger.execute("watch 0x10 x")


def test_watch_without_tracking_is_a_command_error() -> None:
    with pytest.raises(CommandError, match="track_accesses"):
        _debugger()[1].execute("watch 0x10")


@pytest.mark.parametrize("command", ["disassemble 0x200 3", "disasm $200 3", "d 512 3"])
def test_disassemble_and_its_aliases(command: str) -> None:
    assert _debugger()[1].execute(command).lines == (
        "0200  20 00 03     JSR $0300",
        "0203  EA           NOP",
        "0204  A9 55        LDA #$55",
    )


def test_disassemble_defaults_to_eight_from_pc() -> None:
    assert len(_debugger()[1].execute("d").lines) == 8


@pytest.mark.parametrize("command", ["memory 0xFFFF 3", "m $ffff 3"])
def test_memory_wraps_past_ffff(command: str) -> None:
    assert _debugger()[1].execute(command).lines == ("FFFF  03 00 00",)


def test_memory_rows_are_sixteen_wide() -> None:
    lines = _debugger()[1].execute("m 0x200 20").lines
    assert [line[:4] for line in lines] == ["0200", "0210"]
    assert lines[1] == "0210  00 00 00 00"


def test_set_writes_registers_and_forces_p_bits() -> None:
    machine, debugger = _debugger()
    debugger.execute("set a 0x12")
    debugger.execute("set PC $1234")
    debugger.execute("set S 0")
    assert (machine.cpu.a, machine.cpu.pc, machine.cpu.s) == (0x12, 0x1234, 0)
    assert debugger.execute("set P 0xFF").lines[0].endswith("P=EF NV--DIZC")
    assert machine.cpu.p == 0xEF  # B cleared
    debugger.execute("set P 0")
    assert machine.cpu.p == 0x20  # bit 5 set


def test_irq_on_and_off_drive_the_level() -> None:
    machine, debugger = _debugger()
    assert debugger.execute("irq on").lines == ("IRQ asserted; it stays asserted until irq off",)
    assert machine.cpu.maskable_interrupt_pending
    assert debugger.execute("IRQ OFF").lines == ("IRQ released",)
    assert not machine.cpu.maskable_interrupt_pending


def test_nmi_latches_an_edge_taken_at_the_next_step() -> None:
    machine, debugger = _debugger()
    assert debugger.execute("nmi").lines == ("NMI latched; taken at the next step",)
    assert machine.cpu.non_maskable_interrupt_pending
    assert debugger.execute("s").lines == ("#0 0200  nmi -> PC=0400 +7",)


def test_reset_runs_the_seven_cycle_start_sequence() -> None:
    machine, debugger = _debugger()
    assert debugger.execute("reset").lines == (
        "#0 0200  reset -> PC=0500 +7",
        "PC=0500 A=00 X=00 Y=00 S=FC P=24 -----I--",
        "JAM=0 RESET=0 NMI=0 IRQ=0 POLLED_I=-",
    )
    assert not machine.cpu.reset_pending


@pytest.mark.parametrize(
    ("command", "message"),
    [
        ("bogus", "unknown command: bogus"),
        ("step 0", "positive"),
        ("step 1 2", "expects"),
        ("step x", "integer"),
        ("run", "expects"),
        ("run 10 0", "positive"),
        ("break 0x10000", "range"),
        ("break $zz", "integer"),
        ("history -1", "range"),
        ("memory 0 257", r"range 0\.\.256"),
        ("set Q 1", "no register Q"),
        ("set A 256", "range"),
        ("set PC 0x10000", "range"),
        ("irq", "expects"),
        ("irq maybe", "on or off"),
        ("int on", "unknown command"),
        ("nmi now", "expects"),
        ("regs 1", "expects"),
        ("quit now", "expects"),
        ("step 'open", "quotation"),
    ],
)
def test_malformed_commands_raise_command_errors(command: str, message: str) -> None:
    with pytest.raises(CommandError, match=message):
        _debugger()[1].execute(command)


def test_commands_that_need_peek_fail_without_it() -> None:
    debugger = CommandDebugger(DebugSession(Host().cpu))
    for command in ("disassemble", "memory 0", "over"):
        with pytest.raises(CommandError, match="no side-effect-free peek"):
            debugger.execute(command)


def test_interactive_loop_reports_errors_and_exits() -> None:
    _machine, debugger = _debugger()
    output = StringIO()

    debugger.interact(StringIO("bad\nstep\nquit\nstep\n"), output)

    assert output.getvalue() == (
        "6502> error: unknown command: bad\n"
        "6502> #0 0200  20 00 03     JSR $0300 -> PC=0300 +6\n"
        "6502> "
    )


def test_interactive_loop_ends_at_end_of_input() -> None:
    output = StringIO()
    _debugger()[1].interact(StringIO("s\n"), output, prompt="> ")
    assert output.getvalue().endswith("+6\n> ")


def test_public_values_are_validated() -> None:
    with pytest.raises(TypeError, match="DebugSession"):
        CommandDebugger(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="string"):
        _debugger()[1].execute(1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="tuple of strings"):
        CommandResult(["line"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="bool"):
        CommandResult(quit=1)  # type: ignore[arg-type]
