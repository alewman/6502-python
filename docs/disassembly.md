# Disassembly

`disassemble(peek, address)` decodes one instruction using only `peek`, a
side-effect-free byte reader -- the host's memory, not its bus, so that looking
at code never touches a device. `disassemble_bytes(data, address)` decodes from
a byte sequence and `disassemble_range(peek, address, count)` a listing.

The decode table is built from the opcode map the core executes, so the
disassembler cannot disagree with the core about length or addressing mode.

| Mode | Example | `operands` |
| --- | --- | --- |
| implied | `CLC` | `()` |
| accumulator | `ASL A` | `("A",)` |
| immediate | `LDA #$2A` | `("#$2A",)` |
| zero page | `LDA $12` | `("$12",)` |
| zero page,X / ,Y | `LDA $12,X` | `("$12", "X")` |
| absolute | `LDA $1234` | `("$1234",)` |
| absolute,X / ,Y | `LDA $1234,Y` | `("$1234", "Y")` |
| indirect | `JMP ($1234)` | `("($1234)",)` |
| (zp,X) | `LDA ($12,X)` | `("($12", "X)")` |
| (zp),Y | `LDA ($12),Y` | `("($12)", "Y")` |
| relative | `BNE $0200` | the resolved target |

`Instruction` carries `address`, `data`, `mnemonic`, `operands`, `mode`,
`target` (the zero-page, absolute, pointer or branch address, before
indexing) and `documented`. The 105 undocumented opcodes use NMS's names:
SLO RLA SRE RRA SAX LAX DCP ISC ANC ALR ARR SBX LAS SHA SHX SHY TAS ANE LXA
JAM, NOP with the operand the chip fetches, and `USBC` for $EB, the duplicate
of `SBC #imm`. BRK and JAM decode as one byte; BRK's return address skips the
byte after it, which assemblers write as data.
