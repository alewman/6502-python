# Validation

What the core is checked against, how to rerun each check, what it proved on
which revision, and every place the core's behaviour was decided between
sources that disagree. Paths are relative to the repository root.

## Oracles and tiers

An oracle's tier is where its expected values came from. A lower tier
detects disagreements; the highest tier that speaks to a question decides it.

| Tier | Oracle | What it checks | Where |
| --- | --- | --- | --- |
| self-checking program | Klaus Dormann's 6502 functional test | every documented instruction, addressing mode and flag, run as a 30.6-million-instruction program that traps on the first wrong result | `tests/test_dormann.py` |
| self-checking program | the decimal test (Bruce Clark's, in Dormann's suite; amb5l's ca65 port) | every ADC and SBC result and N V Z C in decimal mode, all 131,072 operand and carry combinations each, invalid BCD included, by NMOS rules | `tests/test_dormann.py` |
| emulator-derived | SingleStepTests 65x02, "6502" set | 10,000 cases per opcode, all 256: registers, RAM, and every bus cycle's address, value and direction | `tests/test_single_step_tests.py` |
| documentation | MOS programming manual (PM), hardware manual (HM), *No More Secrets* v0.99 (NMS), NESdev wiki | each handler's rule and each addressing mode's cycles; interrupt timing | `tests/test_readability.py`, `tests/test_interrupts.py` |

No oracle here was captured from a chip. Dormann's programs compute their own
expected values from the documented behaviour; SingleStepTests was generated
by its author's emulator; the manuals are what MOS and later researchers wrote
down. The bus order in particular has no hardware-captured oracle: it is
checked against SingleStepTests and read against HM Appendix A and NMS
"Unintended memory accesses", and the claim is worded accordingly.

## Results

Recorded 2026-09-21 on this machine (shared; timings are indicative), at the
commit that introduced them and rerun on every commit since:

| Gate | Command | Result | Time |
| --- | --- | --- | --- |
| SingleStepTests, full | `pytest -m slow tests/test_single_step_tests.py` | 2,560,000 / 2,560,000 cases, bus included | 33 s with both exercisers (PyPy); 2 min 54 s (CPython 3.14) |
| SingleStepTests, sample | `pytest -m "not slow"` | 100 cases x 256 opcodes | part of ~10 s |
| Dormann functional | `pytest -m slow tests/test_dormann.py` | success trap `$3469` after 30,646,177 instructions | 4.6 s for both (PyPy) |
| Dormann decimal | same | `ERROR` = 0 at the `$044B` trap | (above) |
| Readability | `pytest tests/test_readability.py` | every handler cites its own PM Appendix B page or NMS section | < 1 s |

Each oracle was also checked to fail: breaking the carry of one CMP case
traps the functional test at `$1CDB`; one wrong BCD sum leaves the decimal
test's `ERROR` at 1; dropping the dummy read of zero page,X fails
SingleStepTests on the bus comparison alone (the cycle count still matched,
which is why the bus is compared).

### SingleStepTests

`SingleStepTests/65x02 @ 2f6980a2d95757486c7bee24355c360e40e2a224`, MIT
licensed, fetched with `python scripts/fetch_test_vectors.py` into
`tests/6502_test_vectors/6502/` (gitignored; ~420 MB). The generated GitHub
archive has no published SHA-256, so none is claimed; the immutable commit
URL is the provenance.

`tests/single_step.py` runs one case: it loads the register image and RAM,
calls `step()` once through a bus that logs every access, and compares A X Y
S PC, P, every RAM byte the case names, the returned cycle count, and the
logged accesses against the case's `cycles` array, entry for entry. P is
compared on every bit but B: the corpus records whatever B its generator
chose, and B is not a flip-flop (see [Divergences](#divergences)). The quick
loop runs the first 100 cases of each opcode, decoding only those; `-m slow`
runs all 10,000.

### Dormann's exercisers

Fetched with `python scripts/fetch_dormann_tests.py` into `tests/dormann/`
(gitignored). The decimal test is assembled from source with cc65's `ca65` and
`ld65`; without them it is skipped with instructions.

| Artifact | Source revision | Path | SHA-256 |
| --- | --- | --- | --- |
| functional image (Klaus2m5) | `7954e2dbb49c469ea286070bf46cdd71aeb29e4b` | `tests/dormann/bin_files/6502_functional_test.bin` | `fa12bfc761e6f9057e4cc01a665a7b800ff01ae91f598af1e39a1201d01953fd` |
| decimal test (amb5l ca65 port) | `966b1a35049f9d8be44ad092ec6d43d5ba1831b3` | `tests/dormann/6502_decimal_test.bin` | `b179ca4c5a305de2d0cde9ccaa04861be965e2a85b9d3d1230dcc47a396ca43f` (cc65 V2.19) |

Both load at `$0000` and start at `$0400`, and each ends in a `JMP *`
self-loop. The functional test passes at `$3469`; any other self-loop is a
failure, and its address locates the failing check in the test's listing. The
decimal test always ends at `$044B`; its `ERROR` byte at `$000B` is 0 on
success. The test pre-fills `ERROR` with `$A5`, so a run that never reached
the code that writes it cannot pass.

### Reference documents

`python scripts/fetch_reference_docs.py` fetches the three documents the
handlers cite into `reference/` (gitignored) and checks these pins:

| Key | Document | SHA-256 |
| --- | --- | --- |
| PM | MOS MCS6500 Microcomputer Family Programming Manual, 6500-50A, Jan 1976 | `5ee2a698e274321bea9189d1f15038f69c13fcc4960026ca593c9229ba6a0973` |
| HM | MOS MCS6500 Microcomputer Family Hardware Manual, 6500-10A, Jan 1976 | `81ea570c9d68deff64d67365bdf24534df93a8c62121e53036aeac6a557cea23` |
| NMS | groepaz, *No More Secrets: NMOS 6510 Unintended Opcodes*, v0.99, 24 Dec 2024 | `d5f42bd5b301c68f774529ca21e95923e00fc1a13e3781afa561ff8d8e341fad` |

Page numbers are the documents' printed ones. The tables in
`tests/test_readability.py` -- which Appendix B page each documented
instruction is on, which NMS page each undocumented one starts on -- were
read from these files' text (`pdftotext -layout`) on 2026-09-21.

## Divergences

Every place the sources disagree, and what the core does.

1. **A taken branch's first extra cycle reads PC, not the target.** HM p. A-13
   lists that cycle's address as "PC + 2 + offset (w/o carry)". NMS p. 87 and
   SingleStepTests both read PC + 2, the next opcode, and only the page-crossing
   cycle at the uncorrected target. The core follows NMS and the corpus; HM's
   table appears to show the address formed during the cycle rather than the
   one on the bus.
2. **The second cycle of an IRQ or NMI entry reads PC again.** NMS p. 83 lists
   PC + 1; the NESdev wiki ("CPU interrupts", from the visual6502 simulation)
   says the increment is suppressed and PC is read twice. No executable oracle
   here covers interrupt entry. The core follows NESdev; either way the value
   is discarded, and only a device mapped at PC + 1 could tell.
3. **The reset sequence's first two cycles read PC.** PM p. 127 calls their
   address "don't care"; the core reads PC twice, as NESdev describes reset
   ("the same sequence" as IRQ and NMI, item 2).
   The three stack reads (S, S-1, S-2, nothing written, S left 3 lower) are
   PM's own.
4. **The read-modify-write extra cycle is a write.** HM pp. A-8 and A-9 put the
   operand's address on the bus in that cycle without saying which way the
   data goes; NMS p. 88 says it writes the unmodified byte back, and
   SingleStepTests agrees. The core writes.
5. **B is kept clear in P.** B is not a flip-flop: it exists only in the byte
   BRK and PHP push (set) and IRQ and NMI push (clear) (NMS p. 95). NMS says it
   reads as 1 "during normal program execution"; SingleStepTests leaves B 0
   after PLP and RTI and otherwise carries whatever its generator chose. No
   instruction can observe it, so the core keeps P's bit 4 clear and bit 5 set,
   and compares P with the corpus on the other seven bits.
6. **ANE and LXA use $EE for the magic constant.** NMS pp. 60-61: the
   constant varies between chips and with temperature ($EE, $00 and $FF are
   among the values reported). $EE is SingleStepTests' value. Programs that depend on it do not run
   reliably on real hardware either.
7. **SHA, SHX, SHY and TAS store "AND (H+1)" and, across a page, write to the
   corrupted address.** NMS pp. 48-49 also describes the AND dropping out when
   RDY or a DMA steals a cycle at the wrong moment; the core has no RDY input,
   so that case cannot arise.

## Limits

- Interrupt requests are sampled at instruction boundaries. The chip polls in
  the second-to-last cycle of an instruction, so an IRQ that a device raises
  from inside a bus callback during the last cycle is, on hardware, taken one
  instruction later than here. Requests made between steps -- the usual case --
  are exact, including the CLI/SEI/PLP delay and BRK/IRQ hijacking by NMI.
- There is no RDY, SO or bus-halt input, and no 65C02, 65816, 2A03 or 6510
  variant.
- The per-cycle timing within an instruction is the order of bus accesses and
  their count; nothing is claimed about sub-cycle timing.

## Speed

`benchmarks/core_benchmark.py`: four workloads, best of three, on this shared
machine. The 0.1.0 numbers were measured against the old core in the same
process, alternately, the method of `benchmarks/compare_revisions.py`.

| Workload | 0.1.0 CPython 3.14 | 0.2.0 CPython 3.14 | 0.1.0 PyPy 3.11 | 0.2.0 PyPy 3.11 |
| --- | --- | --- | --- | --- |
| base (loads, ALU, indexed store, branch) | 0.137 M/s | 2.24 M/s (x16.4) | 0.465 M/s | 44.9 M/s (x96) |
| rmw (INC/ROR abs,X, ASL/DEC zp) | 0.168 M/s | 1.69 M/s (x10.0) | 0.473 M/s | 39.6 M/s (x84) |
| stack (JSR/RTS, PHA/PLA) | 0.167 M/s | 2.17 M/s (x13.0) | 0.780 M/s | 34.6 M/s (x44) |
| decimal (ADC/SBC with D set) | 0.154 M/s | 2.29 M/s (x14.9) | 0.550 M/s | 33.3 M/s (x61) |

The new core also does more per instruction than the old one did: every dummy
read and dummy write is a real call on the host's bus.
