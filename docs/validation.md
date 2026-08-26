# Validation

## Pinned SingleStepTests oracle

The project uses the MIT-licensed [SingleStepTests 65x02
corpus](https://github.com/SingleStepTests/65x02) as an external oracle for
one-instruction NMOS 6502 execution. The source attribution is the
`SingleStepTests/65x02` repository at the immutable revision
`2f6980a2d95757486c7bee24355c360e40e2a224`. The revision and archive URL are
also defined in `scripts/fetch_test_vectors.py`, which is the canonical fetch
configuration.

Fetch the corpus explicitly from the project root:

```console
python scripts/fetch_test_vectors.py
```

The script downloads that pinned archive and installs its `6502` directory at
the gitignored, project-relative location
`tests/6502_test_vectors/6502/`. It does not make the corpus part of the
package or wheel. The archive has no upstream-published checksum; integrity is
pinned by the immutable revision URL rather than by an invented checksum.

## Running validation

`pytest` is offline by design. It never invokes the fetch script or accesses the
network. When the local corpus is absent, `tests/test_6502_vectors.py` skips
with an actionable instruction to run `python scripts/fetch_test_vectors.py`.
When present, the runner recursively discovers every JSON vector under
`tests/6502_test_vectors/6502/` and executes every record in each file.

For each one-instruction vector, assertions cover the expected cycle count,
complete post-state registers (A, X, Y, PC, and SP), the packed status byte and
each persistent status flag, every sparse final-RAM value and address, and the
set and values of memory mutations. The runner compares cycle totals, not the
corpus's per-cycle bus-operation records.

## Opt-in Dormann exercisers

Dormann assets are external, gitignored files and are never included in the
package or wheel. Provision the pinned Klaus2m5 functional binary and the
pinned amb5l decimal source/binary under `tests/dormann/` with:

```console
python scripts/fetch_dormann_tests.py
pytest -m integration
```

The functional binary is loaded directly from
`tests/dormann/bin_files/6502_functional_test.bin`; the decimal exerciser is
loaded from `tests/dormann/6502_decimal_test.bin`. Both are stepped through the
public `CPU.step()` API in a 64 KiB machine-neutral memory with finite budgets.
The functional source revision is
`7954e2dbb49c469ea286070bf46cdd71aeb29e4b` and its SHA-256 is
`fa12bfc761e6f9057e4cc01a665a7b800ff01ae91f598af1e39a1201d01953f`. The
decimal source revision is `966b1a35049f9d8be44ad092ec6d43d5ba1831b3`; its
expected built-binary SHA-256 is
`b179ca4c5a305de2d0cde9ccaa04861be965e2a85b9d3d1230dcc47a396ca43` (the
fetcher warns when a local cc65 version produces a different digest).

This is instruction-core validation only. It is not cycle-accurate bus-pin
emulation and is not a complete host machine.

## Claim and limits

This validates instruction-core behavior represented by the selected inputs. It
does not validate cycle-accurate bus pins or bus activity, and it does not
claim to validate a complete host machine. Passing the oracle or exercisers is
evidence for covered instruction behavior, not proof of exhaustive hardware
equivalence.
