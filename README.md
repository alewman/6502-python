# 6502-python

`6502-python` is a dependency-free Python 3.12+ NMOS 6502 core package. The
project distribution name is `6502-python`; import it in Python as
`sixfiveohtwo`.

## Embedding

The host supplies a byte-addressable `MemoryBus` implementation with
`read_byte(address)` and `write_byte(address, value)`. Host-controlled
interrupt inputs are represented by `InterruptLines`:

```python
from sixfiveohtwo import InterruptLines

lines = InterruptLines()
lines.set_irq(True)       # IRQ is a level; keep it asserted as needed.
lines.set_reset(True)     # RESET is also level-sensitive.
lines.set_nmi(True)       # NMI latches this low-to-high edge.
inputs = lines.sample_instruction_boundary()
```

`sample_instruction_boundary()` returns an immutable `InterruptBoundary`.
RESET and IRQ report their levels on every sample. NMI reports and consumes a
pending rising edge; it will not retrigger until NMI is driven low and high
again. `signal_nmi()` is available when a host wants to submit an NMI edge
without maintaining a line level.

The boundary model only communicates host input state. Vector fetch,
interrupt entry, reset sequencing, and instruction execution are intentionally
reserved for later core phases.

## v1 scope

The v1 target is the NMOS 6502, with host-provided memory and interrupt lines.
Unofficial opcodes, 65C02 extensions and differences, and 65816 behavior are
explicitly out of scope.
