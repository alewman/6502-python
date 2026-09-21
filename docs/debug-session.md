# Debug sessions

`DebugSession` is a dependency-free controller around an existing `MOS6502`
host. It does not subclass the host or alter the instruction core. It has
z80-python's shape, so a debugger written for one family core reads like one
for another.

```python
session = DebugSession(
    cpu,
    peek_byte=memory.__getitem__,
    history_limit=256,
    track_accesses=True,
)
session.add_breakpoint(0x1234)
session.add_watchpoint(0xD012, "r")
result = session.run(max_steps=100_000, max_cycles=1_000_000)
```

To step through a binary without writing a host:

```text
python -m sixfiveohtwo --load program.bin@0x0400 --pc 0x0400 -c "break 0x1234" -c "run 1000"
python -m sixfiveohtwo --zip ROMPATH/set.zip:rom.bin@0xF800 --reset -c "continue"
```

The command line puts the images in flat 64 KiB RAM, tracks accesses, runs
the `-c` commands, then reads more from stdin unless `--batch` is given.
`--reset` starts through the reset vector.

## Bounded control

Every `run()` requires a positive `max_steps`, and may add a positive
`max_cycles`; one boundary is atomic, so the returned total may exceed that
limit by the last boundary's cycles. A `RunResult` carries its `StopReason`:

- `BREAKPOINT`: before the instruction at a breakpoint address;
- `WATCHPOINT`: after the step that read or wrote a watched byte, with the
  matching accesses in `RunResult.hits`;
- `HALTED`: before another idle cycle of a CPU stopped by JAM (pass
  `stop_on_halt=False` to step through it);
- `STEP_LIMIT` and `CYCLE_LIMIT`: a budget ran out.

`session.step()` always advances exactly one boundary and ignores
breakpoints, so a debugger can step off one without editing the set.

## Records and history

Each `StepRecord` holds immutable before and after `CPUState` values, the
cycles, a `BoundaryKind` (`INSTRUCTION`, `JAM_IDLE`, `RESET`, `NMI`, `IRQ`),
the disassembled `Instruction` when the session has a peek function, and,
when it tracks accesses, `accesses`: every bus access in order as
`("r" | "w", address, value)`. On the 6502 that is one access per cycle, so
`len(record.accesses) == record.cycles`. `next_boundary(state)` says which
kind the next `step()` will be, decided exactly as `MOS6502.step()` decides.

History is an optional bounded ring; a limit of zero disables it while
totals and returned records continue. It holds no memory or device state and
is not rewind.

## Access tracking and watchpoints

Because the CPU takes its bus as callables, `track_accesses=True` sees every
access without the host's help: it replaces the CPU's `read_byte` and
`write_byte` with wrappers that log and then call the originals, and
`close()` puts the originals back. Nothing reads memory the program did not
read. A target may be a whole board -- an object whose `step()` runs its
devices around one CPU step and whose `cpu` attribute is the processor -- and
the processor's bus is then the one tracked. Watchpoints see the dummy reads
and writes too: a watch on a device register stops on the dummy read of an
indexed store, exactly where a real board would have acknowledged it.

## Command frontend

`CommandDebugger` is a thin human interface over the session: `execute()`
takes one command and returns printable lines; `interact(input, output)` is
a line loop with no terminal dependencies. Commands: `registers`, `step`,
`over` (runs a JSR through to its return), `run`, `continue`, `break`,
`delete`, `breakpoints`, `watch`, `unwatch`, `disassemble`, `memory`,
`history`, `set` (A X Y S P PC), `irq on|off`, `nmi`, `reset`, `quit`, with
z80-python's one-letter aliases. Numbers are decimal unless written `0x1234`
or `$1234`.
