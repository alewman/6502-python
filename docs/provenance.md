# Provenance

Where each part of this core's behaviour came from, the licence of that
source, and a verdict. Written for the family's provenance audit (wave 1,
2026-11-13) against the rules in emulator-lineage's `docs/charter.md`
("Licences and provenance") and `docs/methodology.md` ("Provenance in
practice").

Verdicts: **clean** (own work from facts or permissive sources, cited),
**cite** (clean, but a source must be named or a notice kept), **rewrite**
(derived from code we may not take), **unclear** (what would settle it).

The audit read `origin/main` (`741419a`, which holds `frame.py` and the
tooling hooks) and every other branch's history. This file was committed on
the branch checked out at the time (`dma-stall`, already merged into
`origin/main`).

## Summary

No GPL or LGPL code, and no emulator source of any licence, informed the
core. Its behaviour comes from MOS's manuals, groepaz's *No More Secrets*,
the NESdev wiki and the Breaks wiki (facts, all cited in the code), checked
against SingleStepTests (MIT, fetched) and Klaus Dormann's programs (GPL-3.0,
fetched and run, never committed). Nothing third-party is or ever was
committed (all history checked: no binary, fixture or corpus file was ever
added).

Counts: 15 clean, 0 cite, 0 rewrite, 0 unclear.

## The core

| Part | Behaviour from | Source licence | Verdict |
| --- | --- | --- | --- |
| `_core.py`: registers, P bits, fetch, every addressing mode's cycles and dummy accesses | MOS MCS6500 Programming Manual (PM) and Hardware Manual (HM) Appendix A; NMS "Unintended memory accesses" | manufacturer documents; NMS "free as in free beer, all rights reversed" | clean |
| `_alu.py` binary ADC/SBC, logic, compares | PM Appendix B | manufacturer document | clean |
| `_alu.py` NMOS decimal ADC/SBC and its flags | NMS "Unintended decimal mode" pp. 70-80 (its rules are backed by test programs run on real C64s, the VICE testprogs) | NMS as above; facts | clean |
| `_loads.py`, `_shifts.py` | PM Appendix B, HM Appendix A | manufacturer documents | clean |
| `_control.py`: branches, stack, JSR/RTS/RTI, BRK, reset | PM, HM, NMS | as above | clean |
| interrupt timing (`_control.py`, `frame.py`): poll at the end of the second-to-last cycle, CLI/SEI/PLP delay, NMI hijack | NESdev wiki "CPU interrupts" (prose; it cites the visual6502 transistor-level simulation) | wiki prose; facts | clean |
| `note_stall` / RDY behaviour (`frame.py`) | perfect6502 (MIT) run as a closed box by famicom-python; AccuracyCoin results on a console | MIT; run only | clean |
| `_undocumented.py`: all 105 undocumented opcodes, JAM, SHx/TAS with `dma_stalled` | NMS; ANE/LXA constant `$EE` is SingleStepTests' value and NMS's list | NMS; SST MIT (data) | clean |
| `_dispatch.py`: the 256-entry opcode, mode and cycle table | PM Appendix B/C (documented 151), NMS opcode matrix p. 1 (the other 105) | facts | clean |
| `cpu.py` `RP2A03`: decimal adjust cut | Breaks wiki (`BreakingNESWiki_DeepL/APU/core.md`), traced from a die photograph | wiki prose; facts | clean |
| `frame.py` (`CPUFrame`), `state.py` | own design; the rules above | MIT | clean |
| tooling: `debug.py`, `console.py` (z80-python's command set, same family, MIT), `disasm.py` (PM syntax, NMS names), `trace.py` | own work | MIT | clean |

## Tests, fixtures and scripts

| Part | Source | Licence / terms | Verdict |
| --- | --- | --- | --- |
| SingleStepTests 65x02 `6502` and `nes6502` sets @ `2f6980a2`, fetched by `scripts/fetch_test_vectors.py`, gitignored | Thomas Harte's generated corpus | MIT (GitHub licence field and repository) | clean (detector; data, never committed) |
| Klaus Dormann's 6502 functional test (Klaus2m5 @ `7954e2db`, prebuilt `.bin`) and Bruce Clark's decimal test (amb5l's ca65 port @ `966b1a35`), fetched and assembled by `scripts/fetch_dormann_tests.py`, gitignored; run in CI | Klaus Dormann; Bruce Clark | GPL-3.0 (both repositories' licence field) | clean: run as programs, never committed or redistributed (charter rule 6) |
| `tests/test_readability.py` page tables | read from PM and NMS text (`pdftotext`) | facts | clean |

`scripts/fetch_reference_docs.py` fetches PM, HM (archive.org scans) and NMS
(csdb.dk) into the gitignored `reference/`; none is committed.

## History

All branches searched (`git log --all -p`, added and deleted files, emulator
names, "transcribed", "port of", file extensions). The AFK-era first core
(deleted in `c9e101d`) cited no outside code either. Nothing to act on.

## Owed (not provenance breaches)

- SPDX headers: no source file carries `SPDX-License-Identifier: MIT` yet
  (charter rule 2; the family pass is owed).

## How this was checked

`provenance_check.py` was not run: no permissive emulator source informed
this core, so there is no reference tree to compare against. The audit read
the repository's own comments, docs, fetch scripts and history, the NMS
licence page, and the GitHub licence field of each fetched repository. No
GPL source was opened.
