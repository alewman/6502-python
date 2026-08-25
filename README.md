# 6502-python

`6502-python` is a dependency-free Python 3.12+ NMOS 6502 core package. The
project distribution name is `6502-python`; import it in Python as
`sixfiveohtwo`.

## Installation

Install the distribution from PyPI (or from a checkout containing this
project):

```console
python -m pip install 6502-python
```

The distribution name contains a hyphen, but the import package uses the flat
module name `sixfiveohtwo`:

```python
from sixfiveohtwo import CPU, InterruptLines
```

## Embedding

The host owns memory and supplies a byte-addressable object implementing
`read_byte(address)` and `write_byte(address, value)`. The core does not
allocate a memory map or provide machine-specific devices. For example, this
is a complete in-memory host bus:

```python
class HostMemory:
    def __init__(self):
        self.data = bytearray(0x10000)

    def read_byte(self, address):
        if not 0 <= address <= 0xFFFF:
            raise ValueError("address must fit in 16 bits")
        return self.data[address]

    def write_byte(self, address, value):
        if not 0 <= address <= 0xFFFF:
            raise ValueError("address must fit in 16 bits")
        if not 0 <= value <= 0xFF:
            raise ValueError("value must fit in 8 bits")
        self.data[address] = value


memory = HostMemory()
lines = InterruptLines()
cpu = CPU(memory, lines=lines)
```

`CPU` owns mutable register state in `cpu.state`; `cpu.memory` remains the
host-provided bus and `cpu.lines` exposes the line object. A `CPUState` can
also be supplied to `CPU(..., state=existing_state)` when the host needs to
initialize or restore registers.

### Reset and interrupt lines

Drive RESET and IRQ as levels. They are reported whenever the host samples an
instruction boundary, so keep them asserted for as long as required:

```python
cpu.set_reset(True)
reset_sample = cpu.sample_instruction_boundary()
cpu.set_reset(False)

cpu.set_irq(True)
irq_sample = cpu.sample_instruction_boundary()
cpu.set_irq(False)
```

NMI is edge-latched. A low-to-high transition, or an explicit `signal_nmi()`
call, creates one pending NMI indication. The indication is consumed by the
next `sample_instruction_boundary()` call; drive NMI low before another rising
edge can be recognized:

```python
cpu.set_nmi(True)                         # latch one rising edge
pending = cpu.pending_interrupt_boundary()  # inspect; does not consume NMI
accepted = cpu.sample_instruction_boundary() # accepted.nmi is True
cpu.set_nmi(False)

cpu.signal_nmi()                          # latch without a persistent level
accepted = cpu.sample_instruction_boundary()
```

`pending_interrupt_boundary()` returns the current RESET and IRQ levels and
whether NMI is pending without consuming it. `sample_instruction_boundary()`
returns an immutable `InterruptBoundary` and consumes the pending NMI flag.

This phase implements only line acceptance and pending-state reporting. It
does **not** execute instructions, perform reset sequencing, fetch interrupt
vectors, or change CPU state in response to a sampled line. The later interrupt
implementation will cover the 7-cycle vector execution lifecycle; a boundary
sample in this phase must not be confused with those seven execution cycles.

## v1 scope

The v1 target is the NMOS 6502, with host-provided memory and interrupt lines.
Unofficial opcodes, 65C02 extensions and differences, and 65816 behavior are
explicitly out of scope.
