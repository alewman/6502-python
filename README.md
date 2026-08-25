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

At an instruction boundary, `CPU.step()` accepts RESET first, then pending NMI,
then an asserted IRQ when the interrupt-disable flag is clear. IRQ and NMI push
PC and status (with B clear), set I, fetch their vectors, and account for seven
cycles. A masked IRQ remains asserted and is deferred until interrupts are
enabled.

## v1 scope and exclusions

This project is an **embeddable instruction core**, not a complete computer or
console emulator. The v1 target is the original NMOS 6502 instruction set,
operating against host-provided memory and interrupt lines.

The planned official opcode scope covers all documented NMOS 6502 instructions:
ADC, AND, ASL, BCC, BCS, BEQ, BIT, BMI, BNE, BPL, BRK, BVC, BVS, CLC, CLD,
CLI, CLV, CMP, CPX, CPY, DEC, DEX, DEY, EOR, INC, INX, INY, JMP, JSR, LDA,
LDX, LDY, LSR, NOP, ORA, PHA, PHP, PLA, PLP, ROL, ROR, RTI, RTS, SBC, SEC,
SED, SEI, STA, STX, STY, TAX, TAY, TSX, TXA, TXS, and TYA. Their documented
addressing modes are in scope: accumulator, immediate, implied, relative,
zero page, zero-page indexed (X or Y), absolute, absolute indexed (X or Y),
indirect, indexed indirect (X), and indirect indexed (Y), where each mode is
valid for the corresponding instruction.

Decimal mode is intended to match NMOS 6502 behavior, including BCD ADC and
SBC arithmetic and the NMOS-specific status-flag results. This is a fidelity
target for the instruction core, rather than a claim that every host machine's
surrounding hardware behaves identically.

The v1 core explicitly does **not** provide or emulate:

- unofficial/undocumented opcodes;
- 65C02 or 65816 instructions, extensions, or behavior;
- memory maps or machine-specific host machines;
- cartridges or other devices; or
- cycle-accurate bus-pin activity or bus-pin timing claims.

The host remains responsible for the memory and device environment around the
core. See [Embedding](#embedding) for the host-memory and interrupt-line
contract.
