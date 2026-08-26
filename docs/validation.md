# Validation

This document records the immutable inputs and execution contracts for the
project's validation. All paths below are relative to the repository root.

## Pinned SingleStepTests oracle

The project uses the MIT-licensed [SingleStepTests 65x02
corpus](https://github.com/SingleStepTests/65x02) as an external oracle for
one-instruction NMOS 6502 execution. The exact immutable revision already used
by the project is:

`SingleStepTests/65x02 @ 2f6980a2d95757486c7bee24355c360e40e2a224`

The canonical fetch command, run from the project root, is:

```console
python scripts/fetch_test_vectors.py
```

The corpus is installed at `tests/6502_test_vectors/6502/`. It is gitignored,
external to the package, and is never fetched by pytest. The generated GitHub
archive has no upstream-published SHA-256, so no archive hash is claimed; the
immutable commit URL is the recorded provenance. With the corpus absent,
the vector test skips and reports the fetch command. With it present, pytest
recursively executes every JSON record.

Each record checks one instruction's cycle total, A/X/Y/PC/SP, packed and
persistent status flags, sparse final RAM, and memory mutations. Cycle totals
are checked, but the corpus's per-cycle bus-operation records are not replayed.

## Opt-in Dormann exercisers

Dormann assets are external, gitignored, never bundled, and may only be read
below `tests/dormann/`. Provision them with this project-relative command:

```console
python scripts/fetch_dormann_tests.py
```

That command fetches these immutable sources and installs these artifacts:

| Artifact | Source revision | Project-relative path | SHA-256 |
| --- | --- | --- | --- |
| Klaus2m5 functional image | `7954e2dbb49c469ea286070bf46cdd71aeb29e4b` | `tests/dormann/bin_files/6502_functional_test.bin` | `fa12bfc761e6f9057e4cc01a665a7b800ff01ae91f598af1e39a1201d01953f` |
| amb5l decimal source/build | `966b1a35049f9d8be44ad092ec6d43d5ba1831b3` | `tests/dormann/6502_decimal_test.bin` | `b179ca4c5a305de2d0cde9ccaa04861be965e2a85b9d3d1230dcc47a396ca43` |

The functional image is an upstream prebuilt 64 KiB image. The decimal image
is built locally from the pinned amb5l sources with `ca65` and `ld65`; its
expected hash can vary with cc65 versions and the fetcher warns on a mismatch.
If `ca65` or `ld65` is unavailable, decimal provisioning is skipped with
installation guidance; the functional artifact remains independently usable.

Run only the opt-in suite with:

```console
pytest -m integration
```

Both tests are marked `pytest.mark.integration`; missing assets cause an
informative skip. To run the non-integration suite, use `pytest -m "not integration"`.
The tests execute one instruction per public `CPU.step()` call in a fresh,
64 KiB machine-neutral memory, with no network access or environment-variable
switch. The functional test loads the image at `$0000`, starts at `$0400`, and
has a 5,000,000-instruction budget. Its documented success convention is the
persistent `$3469` self-loop; any other persistent loop is a failure trap. The
harness also recognizes `$36DD` as its success target when returned by the
selected functional image.

The decimal test loads `tests/dormann/6502_decimal_test.bin` at `$0000`, starts
at `$0400` (the embedded RESET-vector target), and has a 20,000,000-instruction
budget. Completion is the `$044B` (`DONE: JMP $044B`) self-loop for both pass
and fail. Zero-page `$000B` (`ERROR`) distinguishes them: `0` is success and
`1` is failure.

## Scope and limits

This is instruction-core validation only. It does not validate cycle-accurate
bus-pin behavior or bus activity, a memory map, devices, host-bus integration,
or a complete host machine. Passing these inputs is evidence for the covered
instruction behavior, not proof of hardware equivalence. Unofficial opcodes and
65C02/65816 extensions remain outside v1 scope.
