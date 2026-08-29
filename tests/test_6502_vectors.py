"""Exhaustive, file-level execution of the SingleStepTests 6502 corpus."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sixfiveohtwo import pack_status_byte
from tests.vector_support import adapt_vector, iter_vector_file

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_VECTOR_ROOT = _PROJECT_ROOT / "tests" / "6502_test_vectors" / "6502"
_FETCH_HINT = "run scripts/fetch_test_vectors.py"


def _vector_files(vector_root: Path = _VECTOR_ROOT) -> tuple[Path, ...]:
    """Discover corpus files while keeping every path inside this checkout."""
    project_root = _PROJECT_ROOT.resolve()
    root = vector_root.resolve()
    try:
        root.relative_to(project_root)
    except ValueError:
        return ()
    if not root.is_dir():
        return ()
    files = []
    for candidate in root.rglob("*"):
        if candidate.suffix.lower() != ".json" or not candidate.is_file():
            continue
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        files.append(resolved)
    return tuple(sorted(files, key=lambda path: path.relative_to(root).as_posix()))


_SOURCES = _vector_files()


def _file_case(path: Path) -> pytest.ParameterSet:
    """Build one file's test parameter."""
    file_id = f"vector:6502/{path.relative_to(_VECTOR_ROOT.resolve()).as_posix()}"
    return pytest.param(path, id=file_id)


_FILE_CASES: tuple[pytest.ParameterSet, ...] = tuple(
    _file_case(path) for path in _SOURCES
) or (pytest.param(None, id="vector corpus missing"),)


def _context(vector, opcode):
    return (
        f"{vector.source} [record {vector.index}, {vector.name}, opcode 0x{opcode:02X}]"
    )


def _assert_field(context, field, actual, expected):
    message = f"{context}: {field}: expected {expected!r}, got {actual!r}"
    assert actual == expected, message


def _assert_post_state(vector, cpu, memory, result):
    initial_ram = dict(vector.initial["ram"])
    expected_ram = dict(vector.final["ram"])
    opcode = initial_ram.get(vector.initial["pc"], 0)
    context = _context(vector, opcode)
    state = cpu.state

    _assert_field(context, "cycles (step)", result.cycles, len(vector.cycles))
    _assert_field(context, "cycles (state total)", state.cycles, len(vector.cycles))
    for field, actual, expected in (
        ("a", state.a.value, vector.final["a"]),
        ("x", state.x.value, vector.final["x"]),
        ("y", state.y.value, vector.final["y"]),
        ("pc", state.pc.value, vector.final["pc"]),
        ("sp", state.sp.value, vector.final["s"]),
    ):
        _assert_field(context, field, actual, expected)

    actual_status = pack_status_byte(state.status)
    _assert_field(context, "status byte (p)", actual_status, vector.final["p"])
    flag_bits = {
        "negative": 0x80,
        "overflow": 0x40,
        "decimal": 0x08,
        "interrupt_disable": 0x04,
        "zero": 0x02,
        "carry": 0x01,
    }
    for name, bit in flag_bits.items():
        _assert_field(
            context,
            f"status flag {name}",
            getattr(state.status, name),
            bool(vector.final["p"] & bit),
        )

    # The corpus RAM sections are sparse snapshots; compare every oracle address
    # and reject emulator state that introduces an extra sparse entry.
    _assert_field(context, "memory addresses", set(memory.bytes), set(expected_ram))
    for address, expected in sorted(expected_ram.items()):
        _assert_field(
            context, f"memory[0x{address:04X}]", memory.bytes[address], expected
        )
    expected_mutations = {
        address: value
        for address, value in expected_ram.items()
        if initial_ram.get(address) != value
    }
    actual_mutations = {
        address: memory.bytes[address]
        for address in memory.bytes
        if initial_ram.get(address) != memory.bytes[address]
    }
    _assert_field(context, "memory mutations", actual_mutations, expected_mutations)


@pytest.mark.parametrize("source", _FILE_CASES)
def test_6502_vectors(source: Path | None):
    if source is None:
        pytest.skip(f"SingleStepTests vectors are missing; {_FETCH_HINT}")

    for vector in iter_vector_file(source):
        cpu, memory = adapt_vector(vector)
        result = cpu.step()
        _assert_post_state(vector, cpu, memory, result)


@pytest.mark.parametrize("layout", ["missing", "empty", "wrong-parent"])
def test_vector_discovery_returns_no_sources_for_absent_layouts(
    tmp_path, monkeypatch, layout
):
    monkeypatch.setattr(sys.modules[__name__], "_PROJECT_ROOT", tmp_path)
    vector_root = tmp_path / "tests" / "6502_test_vectors" / "6502"
    if layout == "empty":
        vector_root.mkdir(parents=True)
    elif layout == "wrong-parent":
        wrong_root = tmp_path / "tests" / "6502_test_vectors" / "v1"
        wrong_root.mkdir(parents=True)
        (wrong_root / "00.json").write_text("[]")

    assert _vector_files(vector_root) == ()


def test_missing_vectors_skip_with_fetch_instructions():
    with pytest.raises(pytest.skip.Exception, match="scripts/fetch_test_vectors\\.py"):
        test_6502_vectors(None)


def test_vector_discovery_finds_populated_corpus_without_fetching(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sys.modules[__name__], "_PROJECT_ROOT", tmp_path)
    vector_root = tmp_path / "tests" / "6502_test_vectors" / "6502"
    vector_root.mkdir(parents=True)
    source = vector_root / "v1" / "ea.json"
    source.parent.mkdir()
    source.write_text("[]")

    assert _vector_files(vector_root) == (source.resolve(),)
