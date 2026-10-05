# Start here

This page is for someone who knows what a CPU is and wants to read, embed or
check this one. It covers the registers, the status byte, the embedding
contract, what the chip does on its bus every cycle, reset and interrupts,
and the documents the code cites.

## Registers

| Register | Width | Attribute | Notes |
| --- | --- | --- | --- |
| A | 8 | `cpu.a` | the accumulator: every ALU result lands here |
| X, Y | 8 | `cpu.x`, `cpu.y` | index registers |
| S | 8 | `cpu.s` | the stack pointer; the stack is page one, `$0100 + S`, and grows down |
| PC | 16 | `cpu.pc` | |
| P | 8 | `cpu.p` | status: N V 1 B D I Z C |

All are plain integers; write them directly. The flag masks are exported as
`FLAG_N` ... `FLAG_C`.

In P, N is bit 7 of the last result, V the signed overflow of ADC or SBC (or
bit 6 of BIT's operand), D selects decimal (BCD) arithmetic for ADC and SBC,
I masks IRQ, Z is "result was zero", C the carry, or "no borrow" after a
subtract or compare. Bit 5 and B are not flip-flops: bit 5 is 1 whenever P is
pushed, and B exists only in the pushed byte (1 from BRK and PHP, 0 from IRQ
and NMI). The core keeps `p` with bit 5 set and B clear.

## The embedding contract

```python
memory = bytearray(0x10000)
cpu = MOS6502(memory.__getitem__, memory.__setitem__)
```

The host passes two callables, `read_byte(address)` and
`write_byte(address, value)`, and owns everything behind them: RAM, ROM,
mirrors, devices. The core always passes a 16-bit address and an 8-bit
value, so a flat host needs no masking. `step()` runs one instruction (or
reset, or an interrupt entry) and returns the cycles it took; the host adds
them to its clock and runs its devices for that long. This is the family's
contract -- z80-python and m6800-python take their bus the same way -- and a
host that decodes addresses is a function:

```python
def read_byte(address: int) -> int:
    if address >= 0xE000:
        return rom[address - 0xE000]
    if 0xD000 <= address < 0xD400:
        return video.read(address & 0x3F)  # a device: reading may acknowledge
    return ram[address & 0x07FF]
```

## Every cycle is a bus access

The 6502 has no idle cycles: in every one it either reads or writes, and
when it has nothing useful to read it reads something anyway. Those dummy
reads, and the dummy write of a read-modify-write, reach devices on a real
board -- reading a status register twice can lose an interrupt -- so the
core makes each of them. `step()` calls the bus exactly once per cycle it
returns, in the chip's order. `_core.py` writes each addressing mode cycle by
cycle:

| Mode | Cycles after the opcode fetch | Dummy accesses |
| --- | --- | --- |
| implied, accumulator | read PC | the byte after the opcode, discarded |
| immediate | read PC (the operand) | none |
| zero page | operand; data | none |
| zero page,X / ,Y | operand; read the unindexed address; data | the unindexed read; page zero wraps |
| absolute | two operand bytes; data | none |
| absolute,X / ,Y read | two operand bytes; read base-page:low; (data again if a page was crossed) | the read at the uncorrected address, only across a page |
| absolute,X / ,Y write or RMW | two operand bytes; read base-page:low; data | the uncorrected read, always |
| (zp,X) | operand; read zp; pointer low; pointer high; data | the read at zp |
| (zp),Y | operand; pointer low; pointer high; then as absolute,Y | as absolute,Y |
| read-modify-write | ...; read; write the old value; write the new | the first write |
| taken branch | operand; read PC; (read PCH:new-PCL across a page) | both |

The stack instructions and JSR/RTS/RTI add their own dummy reads of PC and
of the stack; `_control.py` spells each out. HM Appendix A lists the address
bus for each cycle; NMS "Unintended memory accesses" (pp. 81-93) says which
are dummies. The SingleStepTests corpus checks all of it
(docs/validation.md).

## Reset and interrupts

The host drives three inputs:

- `request_reset()`: at the next boundary the chip runs its start sequence,
  seven cycles with three stack reads and no writes (S ends 3 lower), sets I
  and loads PC from `$FFFC` (PM section 9.2, p. 127). Registers are otherwise
  unchanged; a new `MOS6502` has them at zero with I set.
- `request_maskable_interrupt()` / `clear_maskable_interrupt()`: IRQ is a
  level. While asserted and I clear, each boundary takes it; taking it does
  not clear it, because on a board the device holds the line until its
  handler acknowledges the device.
- `request_non_maskable_interrupt()`: NMI is edge-triggered; call this on the
  edge. The next boundary takes it regardless of I.

An IRQ or NMI entry is seven cycles: two reads of PC, PC and P pushed (B
clear), I set, the vector read ($FFFE for IRQ and BRK, $FFFA for NMI).
Priority at a boundary: reset, then (unless JAM has stopped the CPU) NMI,
then IRQ.

Three timing rules come from the chip's interrupt poll happening before the
instruction's last cycle rather than after it (NESdev wiki, "CPU
interrupts"):

- CLI, SEI and PLP change I after the poll, so the next boundary decides on
  the old I: an IRQ waiting behind a CLI is taken one instruction late, and
  one polled just before SEI is still taken. `CPUState.polled_i` carries
  this across a capture and restore.
- RTI restores P before the poll, so an RTI that clears I lets a waiting IRQ
  in at once.
- An NMI that arrives during BRK or an IRQ entry, before the vector is read,
  takes it over: the frame already pushed stays, the NMI vector is used.

## JAM

Twelve undocumented opcodes stop the processor: it fetches, puts $FFFF on
the bus and never fetches again. `cpu.halted` goes true; each `step()` then
reads $FFFF and returns one cycle, ignoring IRQ and NMI, until a reset.

## Reading a handler

Every handler is a method named `_op_` plus its mnemonic, in the module for
its family: `_alu.py` (ADC SBC AND ORA EOR CMP CPX CPY BIT), `_loads.py`
(loads, stores, transfers, INX/DEX...), `_shifts.py` (the shifts, rotates,
INC and DEC), `_control.py` (branches, jumps, the stack, flags, BRK, RTI,
interrupt entry, reset) and `_undocumented.py`. `_dispatch.py` has the table:
one line per opcode naming the handler, the addressing mode and the base
cycle count.

Each docstring's first line is the mnemonic, the rule, and the source:

```python
def _op_adc(self, address: int) -> None:
    """ADC -- A + M + C -> A, C (PM p. B-3)."""
```

| Key | Document |
| --- | --- |
| PM | MOS MCS6500 Microcomputer Family Programming Manual, 6500-50A, January 1976 |
| HM | MOS MCS6500 Microcomputer Family Hardware Manual, 6500-10A, January 1976 |
| NMS | groepaz, *No More Secrets: NMOS 6510 Unintended Opcodes*, v0.99, 2024 |
| NESdev | the NESdev wiki, "CPU interrupts" (interrupt timing, from visual6502) |

`python scripts/fetch_reference_docs.py` downloads the first three and
checks their SHA-256 pins; page numbers are the printed ones.
`tests/test_readability.py` checks that each handler cites its own page.
