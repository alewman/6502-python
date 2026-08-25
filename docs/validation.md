# Validation strategy

This document describes the intended validation strategy for the 6502 core. It is
an implementation plan, not a bundled test corpus. No external vectors or
exerciser binaries are downloaded, checked in, or required by the package at
this stage.

## External oracles

When the validation assets phase is implemented, opt-in integration tests should
use the following independent sources:

- **SingleStepTests 65x02 vectors** for instruction-by-instruction comparisons
  of registers, flags, memory effects, and supported addressing modes.
- **Klaus Dormann functional exerciser** for broad official-instruction and
  control-flow coverage.
- **Klaus Dormann decimal exerciser** for NMOS decimal-mode ADC and SBC
  behavior, including status-flag results.

These sources should be treated as external oracles rather than runtime
dependencies. The package's normal test suite must remain dependency-free and
must not require network access or locally installed corpus files.

## Provenance and reproducibility

The integration harness should record the identity of every external input when
assets are introduced. At minimum, its report should identify the source,
revision or release, acquisition date, and cryptographic hash of each downloaded
archive, vector file, or executable. The exact source pins and binary hashes
are intentionally left for the phase that introduces and reviews those assets;
this skeleton does not invent them.

## Opt-in execution

External validation should be separate from the default unit-test run and
explicitly opt in to avoid accidental downloads or long-running checks. A
future repository-supported command or test marker should:

1. verify that the required assets are present and match their recorded
   provenance;
2. fail clearly when assets are absent or do not match, rather than silently
   substituting another version; and
3. run the vector and exerciser adapters against the public embeddable core
   and report the selected source identities.

Asset acquisition, if supported, should be an explicit user action. External
corpora must not be vendored into the source distribution or wheel.

## Validation scope and limits

The oracles validate the NMOS 6502 instruction-core target described by the
project documentation. They do not turn this package into a complete machine
emulator. In particular, this strategy does not promise validation of:

- unofficial or undocumented opcodes;
- 65C02 or 65816 instructions or behavior;
- machine-specific memory maps, devices, cartridges, or host buses beyond the
  documented read/write contract;
- cycle-accurate bus-pin activity or timing claims; or
- behavior that is not represented by the selected oracle inputs.

The integration layer should preserve the host-provided memory and interrupt
interfaces and should distinguish core execution results from machine-specific
side effects. Passing an external oracle is evidence for the covered behavior,
not a claim of exhaustive hardware equivalence.
