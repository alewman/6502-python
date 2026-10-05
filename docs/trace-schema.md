# Trace schema (version 1)

A trace is the observable behaviour of a 6502 core written down one
processor boundary at a time. Two cores that produce equal traces for the same
program and host are, as far as software can tell, the same CPU. This page is
the contract for producing such a trace in any language so that
`first_trace_divergence` can compare it with this core's. Everything here is
implemented by `src/sixfiveohtwo/trace.py`; if the two disagree, the code is
the specification and this page has a bug. The shape is z80-python's, with
`cycles` for its `t_states` and the 6502's state fields.

## File format

JSON Lines: UTF-8, one JSON object per line, `\n` terminated, blank lines
ignored. This package writes sorted keys and no whitespace; readers must not
depend on either. Records are aligned by line position when two traces are
compared; `sequence` is for humans and never used for alignment.

## Record

| Key | Type | Meaning |
| --- | --- | --- |
| `version` | integer | Always `1`. A reader rejects any other value. |
| `sequence` | integer >= 0 | Producer-local counter. Informational only. |
| `kind` | string | What the boundary was; one of the five values below. |
| `cycles` | integer > 0 | Cycles the boundary took, exactly as `step()` returns them. |
| `instruction` | object or `null` | The instruction fetched; `null` for every other kind, and allowed to be `null` for an instruction when the producer cannot disassemble. |
| `before` | state object | Processor state at the boundary's start. |
| `after` | state object | Processor state at its end. |
| `accesses` | array, optional | Every bus access, in order, as `[kind, address, value]` with kind `"r"` or `"w"`: one per cycle. Absent means *not recorded*, not *none*. |

No other keys are allowed.

### `kind`

| Value | When |
| --- | --- |
| `instruction` | An opcode was fetched and executed. |
| `jam_idle` | JAM has stopped the CPU: one cycle reading $FFFF. |
| `reset` | A requested reset ran: the 7-cycle start sequence. |
| `nmi` | A latched NMI was taken: 7 cycles through $FFFA. |
| `irq` | IRQ was asserted and the boundary's poll saw I clear: 7 cycles through $FFFE. |

The kind follows from `before`, in this order: `reset_pending`, then
`halted`, then `non_maskable_interrupt_pending`, then
`maskable_interrupt_pending` with the polled I clear (`polled_i` when it is
not `null`, else P's I bit), else `instruction`.

### `instruction`

| Key | Type | Required | Meaning |
| --- | --- | --- | --- |
| `address` | integer 0..0xFFFF | yes | PC at fetch. |
| `data` | lowercase hex string | yes | Every byte the instruction occupies, e.g. `"bd0002"`. |
| `mnemonic` | string | optional | As this package's disassembler prints it. |
| `operands` | array of strings | optional | Operand texts as the disassembler prints them. |

`mnemonic` and `operands` are present together or absent together. A
producer in another language should omit both: the reader decodes `data` at
`address` and fills them in, so a port only has to get the bytes right. If
`data` is not exactly one instruction the record is rejected.

### State object

Every key is required and no others are allowed.

| Key | Type | Meaning |
| --- | --- | --- |
| `a` `x` `y` `s` | 0..255 | Registers; `s` is the stack pointer's low byte (page one). |
| `pc` | 0..65535 | Program counter. |
| `p` | 0..255 | Status, with bit 5 set and B (bit 4) clear. |
| `halted` | boolean | JAM has run. |
| `reset_pending` | boolean | A reset has been requested and not yet run. |
| `maskable_interrupt_pending` | boolean | The IRQ line is asserted. |
| `non_maskable_interrupt_pending` | boolean | An NMI edge is latched. |
| `polled_i` | boolean or `null` | The I flag the last poll saw, after CLI, SEI or PLP; `null` otherwise. |

These are the fields of `CPUState`, the definition of processor state for
equivalence purposes. Memory and devices are host state and not in the trace.

## Example

An external producer's record for `INX` at $0200 with X = $2A, accesses
tracked:

```json
{"accesses":[["r",512,232],["r",513,0]],"after":{"a":0,"halted":false,"maskable_interrupt_pending":false,"non_maskable_interrupt_pending":false,"p":36,"pc":513,"polled_i":null,"reset_pending":false,"s":0,"x":43,"y":0},"before":{"a":0,"halted":false,"maskable_interrupt_pending":false,"non_maskable_interrupt_pending":false,"p":36,"pc":512,"polled_i":null,"reset_pending":false,"s":0,"x":42,"y":0},"cycles":2,"instruction":{"address":512,"data":"e8"},"kind":"instruction","sequence":0,"version":1}
```

## Comparison rules

`compare_step_records` reports every differing field by path: `kind`,
`cycles`, `instruction.address`, `instruction.data`, `instruction.mnemonic`,
`instruction.operands`, `before.<field>` and `after.<field>`, and `accesses`
when both records carry them. When one trace ends first, the path is `record`
with values `"present"` and `null`. Comparison is lazy: the first divergence
is found without reading either file to the end.

## Versioning

Any change to the set of keys, their types or their meaning is a new
`version`, and readers reject versions they do not know.
