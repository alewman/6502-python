# 6502-python

`6502-python` is a dependency-free Python 3.12+ NMOS 6502 core package. The
project distribution name is `6502-python`; import it in Python as
`sixfiveohtwo`.

## Embedding

The host supplies a byte-addressable `MemoryBus` implementation with
`read_byte(address)` and `write_byte(address, value)`. Host-controlled
interrupt inputs are represented by `InterruptLines`:

```python
from sixfiveohtwo import CPU

cpu = CPU(host_memory)       # host_memory implements MemoryBus
cpu.set_irq(True)            # IRQ is a level; keep it asserted as needed.
cpu.set_reset(True)          # RESET is also level-sensitive.
cpu.set_nmi(True)            # NMI latches this low-to-high edge.
inputs = cpu.sample_instruction_boundary()
```

`CPU` owns a mutable `CPUState` in `cpu.state`, while `cpu.memory` remains the
host-provided `MemoryBus` and `cpu.lines` exposes the shared line object. The
line setters (`set_reset`, `set_irq`, and `set_nmi`) and `signal_nmi()` are
available directly on the core. `pending_interrupt_boundary()` inspects input
state without consuming NMI; `sample_instruction_boundary()` returns an
immutable `InterruptBoundary` and consumes a pending NMI edge. RESET and IRQ
report their levels on every sample, while NMI will not retrigger until driven
low and high again.

The shell only communicates host input state. It does not yet execute
instructions, fetch vectors, perform reset sequencing, or implement a memory
map or devices; those belong to later core phases.

## v1 scope

The v1 target is the NMOS 6502, with host-provided memory and interrupt lines.
Unofficial opcodes, 65C02 extensions and differences, and 65816 behavior are
explicitly out of scope.
