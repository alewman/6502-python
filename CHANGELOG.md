# Changelog

All notable changes to `6502-python` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] -- 0.2.0

The family release: the core rebuilt in the shape of z80-python 0.4.0, the
family's reference core, and made correct to the bus cycle.

### Breaking

- **`MOS6502(read_byte, write_byte)` replaces `CPU(memory, lines=, state=)`.**
  The bus is two callables, the embedding contract z80-python and
  m6800-python share; `MemoryBus`, `InterruptLines`, `InterruptBoundary`, the
  `Register8`/`StatusFlags` wrappers and the `*Step` result objects are gone.
  Migration: `CPU(bus)` becomes `MOS6502(bus.read_byte, bus.write_byte)`
  (passing the old object raises a `TypeError` that says so); `cpu.state.a.value`
  becomes `cpu.a`, and likewise `x`, `y`, `s` (was `sp`), `pc`, `p` (P as one
  int, bit 5 set, B clear); `step()` returns the cycle count instead of a step
  object, and the host keeps its own cycle total.
- **Interrupt inputs take z80-python's names.** `request_reset()`,
  `request_maskable_interrupt()` / `clear_maskable_interrupt()` (IRQ, a
  level), `request_non_maskable_interrupt()` (an edge latch). Migration:
  `set_irq(True/False)` becomes the request/clear pair; `set_nmi(True)` on a
  rising edge, or `signal_nmi()`, becomes `request_non_maskable_interrupt()`;
  `set_reset(True)` followed by a step becomes `request_reset()`.
- **The package lives in `src/`.** An editable install must be redone
  (`pip install -e .`).

### Changed

- **Every bus cycle is made, in the chip's order.** Dummy reads of indexed
  and implied modes, the read-modify-write dummy write, the stack reads of
  JSR, RTS, RTI, PLA and PLP, the taken-branch reads, and the reset
  sequence's three stack reads now reach the host's bus, so memory-mapped
  devices see what they would on a board. `step()` calls the bus exactly once
  per cycle it returns.
- **The SingleStepTests host compares the whole `cycles` array**, address,
  value and direction per cycle, where it compared only its length:
  2,560,000 of 2,560,000 cases agree (emulator-derived tier). The quick loop
  (`pytest -m "not slow"`, ~10 s) runs 100 cases per opcode; `-m slow` runs
  all of them and both Dormann exercisers.
- **10-16x faster on CPython, 44-97x on PyPy**, measured in one process
  against the old core: CPython 3.14 base workload 0.137 -> 2.24 M instr/s,
  PyPy 3.11 0.465 -> 44.9 M instr/s; the full table is in
  docs/validation.md, "Speed". The 1,421-line if-chain became one 256-entry
  table routing to handler methods by instruction family, P became one int,
  and N and Z come from a 256-entry table.
- **Every claim names its oracle's tier** (docs/validation.md): Dormann's
  programs are self-checking, SingleStepTests is emulator-derived, the
  manuals are documentation; nothing is hardware-captured, and the claims
  say so.
- The test suite is rebuilt around the new API: one shared host
  (`tests/conftest.py`), the corpus and exerciser gates, and tests for
  interrupts, state, disassembly, the debugger, traces, the console, the
  command line and the public API. The five `test_phase_*_regressions`
  files and the other old-API unit tests are gone; the CPU behaviour they
  covered is covered by SingleStepTests or by `tests/test_interrupts.py`,
  and the API they tested no longer exists.
- ruff is pinned (0.16.8, z80-python's), line length 100, z80-python's rule
  set, and CI checks formatting.

### Added

- **Interrupt timing the chip has and the old core did not**: CLI, SEI and
  PLP delay a waiting IRQ by one instruction; RTI's restored I counts at
  once; an NMI arriving during BRK or an IRQ entry takes it over; IRQ is a
  level and stays asserted after it is taken. `CPUState.polled_i` carries the
  delay across capture and restore.
- **Tooling at z80-python's level**: `CPUState` with `capture_state()` /
  `restore_state()`; a structured disassembler built from the core's own
  opcode table; `DebugSession` with breakpoints, bounded runs, history,
  bus-access tracking and watchpoints; trace schema version 1 with
  `write_trace`, `read_trace` and lazy divergence search; `CommandDebugger`;
  `python -m sixfiveohtwo` for stepping a binary. `py.typed`.
- **Every handler cites its source**: its page of MOS's programming manual
  (Appendix B) or of *No More Secrets* v0.99, and the addressing modes their
  hardware-manual (Appendix A) and NMS pages. `tests/test_readability.py`
  checks each page against the documents' own layout;
  `scripts/fetch_reference_docs.py` fetches all three with SHA-256 pins.
- **The Dormann decimal exerciser runs**, assembled with cc65 (locally from
  source; in CI from Ubuntu's package). It had never run: the old suite
  skipped it without cc65. Both exercisers were checked to fail on a
  deliberately broken core.
- `benchmarks/core_benchmark.py` (four workloads) and
  `benchmarks/compare_revisions.py`, the same-process A/B.
- CI runs both Dormann exercisers on every push and builds the wheel with an
  installed-package smoke test; `oracles.yml` runs the full SingleStepTests
  corpus weekly and on demand.
- docs: start-here, validation (tiers, results, pins, divergences, limits,
  speed), CPU state, disassembly, debug sessions, trace schema, undocumented
  behaviour, API stability.

### Fixed

- The README and SECURITY.md said the package was on PyPI; it is not. The
  install instructions are from a checkout until it is published.
- The repository description claimed the Dormann decimal test as a passed
  oracle while it was always skipped; it now runs and passes.
- The README said the core followed z80-python's shape and contract; it
  did not, and now does.

### Not done in this release

- z80-python's conformance kit (manifests, a reference-trace command line)
  exists for its Rust port; no 6502 port exists, so it is not ported. Traces
  and `first_trace_divergence` are, which is what a port would diff with.
- No publish workflow: nothing is published yet. Add z80-python's
  `publish.yml` when the package goes to PyPI, and put the install line back
  in the README then.
- The import name stays `sixfiveohtwo` rather than the family's
  `<cpu>_python` pattern; renaming it is a decision for its own release.

## [0.1.0] -- never tagged or published

The pure-Python NMOS 6502 core as it stood at `e7a9b09` (2026-09-21): all 256
opcodes, validated against the SingleStepTests 65x02 corpus (cycle counts,
not bus cycles) and Dormann's functional exerciser.
