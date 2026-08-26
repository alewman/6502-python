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
`tests/6502_test_vectors/6502/`. It does not make the corpus part of the package
or wheel. The archive has no upstream-published checksum; integrity is pinned
by the immutable revision URL rather than by an invented checksum.

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

## Claim and limits

This validates instruction-core behavior represented by the selected
SingleStepTests inputs. It does not validate cycle-accurate bus pins or bus
activity, and it does not claim to validate a complete host machine. In
particular, it says nothing by itself about machine-specific memory maps,
devices, cartridges, host-bus integration, undocumented opcodes, or CPU
variants such as the 65C02 and 65816. Passing the oracle is evidence for the
covered instruction behavior, not proof of exhaustive hardware equivalence.
.
