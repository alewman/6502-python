# Undocumented behaviour

MOS documented 151 of the NMOS 6502's 256 opcodes. The other 105 are not
errors: each does something, decided by the same decode logic as the
documented ones, and most do it reliably. The core implements all of them as
*No More Secrets* v0.99 (NMS) describes and the SingleStepTests corpus
records; `_undocumented.py` has one handler per instruction, each citing its
NMS page.

| Group | Instructions | NMS |
| --- | --- | --- |
| read-modify-write, then an ALU operation with the result | SLO RLA SRE RRA DCP ISC | pp. 7-27 |
| two registers at once | SAX (A AND X stored), LAX (loads A and X) | pp. 16-21 |
| immediate combinations | ANC ALR ARR SBX, and USBC ($EB = SBC #imm) | pp. 28-40 |
| stack pointer | LAS (M AND S to A, X, S) | p. 41 |
| no effect | NOP in implied, immediate, zero page, zero page,X, absolute, absolute,X forms, each making its operand's reads | pp. 43-46 |
| lock-up | JAM: twelve opcodes that stop the CPU until reset | p. 47 |
| unstable address high byte | SHA SHX SHY TAS: the stored value is ANDed with the address's high byte + 1, and a page crossing corrupts the address | pp. 48-59 |
| magic constant | ANE, LXA: A is ORed with a chip-dependent constant first | pp. 60-66 |

Choices the core makes where the chip is not repeatable are listed in
docs/validation.md, "Divergences": the magic constant is $EE, and the
RDY-dependent behaviour of the unstable stores cannot arise because the core
has no RDY input.

Decimal mode applies to the undocumented arithmetic too: RRA adds and ISC
subtracts with the same NMOS decimal rules as ADC and SBC, and ARR has its
own decimal fix-up (NMS pp. 78-80).

After JAM the CPU is stopped: each `step()` reads $FFFF and returns one cycle,
and IRQ and NMI are ignored. `request_reset()` restarts it.
