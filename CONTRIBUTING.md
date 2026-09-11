# Contributing

## Setup

Use Python 3.12 or newer. Create an isolated environment and install the
package with its development tools from the repository root:

```console
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
```

## Validation

Run Ruff before submitting changes:

```console
.venv/bin/python -m ruff check .
```

For core changes and refactors, run the complete, unscoped suite--not selected
tests--with a timeout of at least 1500 seconds:

```console
timeout 1500s .venv/bin/python -m pytest
```

Compare outcomes with the [immutable refactor baseline](docs/refactor-baseline.md).
The baseline is a record, not a test assertion: preserve every behavior covered
by baseline-passing tests and do not hard-code its counts in tests.

## Test oracles

`tests/6502_test_vectors/` and `tests/dormann/` are immutable external oracle
directories. Do not edit, regenerate, reformat, delete, or commit their
contents. Use the documented provisioning commands in
[docs/validation.md](docs/validation.md) when an oracle must be installed or
refreshed; pytest itself remains offline.

## Core refactors

Refactors of `sixfiveohtwo/` must preserve observable CPU behavior, including
instruction results, flags, memory effects, cycle totals, interrupt semantics,
and public API contracts. Keep changes behavior-preserving unless an intentional
behavior change is explicitly specified and covered by appropriate tests and
documentation. Do not alter source, tests, or oracle inputs merely to make a
refactor pass.
