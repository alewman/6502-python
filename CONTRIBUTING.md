# Contributing

## Setup

Python 3.11 or newer; CPython 3.12-3.14 and PyPy 3.11 are what CI tests.
From the repository root:

```console
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
```

## Checks

```console
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .      # ruff is pinned; CI formats with the same one
.venv/bin/python -m pytest -m "not slow"       # the quick loop, ~10 s
```

A change to `src/` must also pass the oracles, run once before review (PyPy
is fastest):

```console
python scripts/fetch_test_vectors.py           # SingleStepTests, ~420 MB, once
python scripts/fetch_dormann_tests.py          # Dormann; the decimal test needs cc65's ca65
.venv/bin/python -m pytest -m slow             # 2,560,000 SST cases, both exercisers
```

A speed claim is measured with `benchmarks/compare_revisions.py OLD NEW`,
which times both revisions alternately in one process; separate runs on a
shared machine move by tens of percent.

## The bar

- Every handler's docstring starts with its mnemonic and ends with the page
  its rule comes from (`tests/test_readability.py` checks the page).
- Every bus access the chip makes is made, in order; the SingleStepTests
  comparison is of the whole cycle list, not its length.
- Every place the core chooses between disagreeing sources is listed in
  docs/validation.md, "Divergences", with the source that decided it.
- Numbers in the docs are regenerated when they change, not remembered.

## Test oracles

`tests/6502_test_vectors/`, `tests/dormann/` and `reference/` hold external
material, fetched by the scripts and gitignored. Do not edit or commit them.
