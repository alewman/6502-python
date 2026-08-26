"""Exhaustive, file-level execution of the SingleStepTests 6502 corpus."""

from __future__ import annotations

from pathlib import Path

import pytest

from sixfiveohtwo import pack_status_byte
from tests.vector_support import adapt_vector, iter_vector_file

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_VECTOR_ROOT = _PROJECT_ROOT / "tests" / "6502_test_vectors" / "6502"


def _vector_files() -> tuple[Path, ...]:
    """Discover corpus files while keeping every path inside this checkout."""
    project_root = _PROJECT_ROOT.resolve()
    root = _VECTOR_ROOT.resolve()
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
_FILE_CASES: tuple[Path | None, ...] = _SOURCES or (None,)
_FILE_IDS = [
    f"vector:6502/{path.relative_to(_VECTOR_ROOT.resolve()).as_posix()}"
    for path in _SOURCES
] or ["vector corpus missing"]


def _expected_operations(vector):
    return [
        (direction, address)
        if direction == "read"
        else (direction, address, value)
        for address, value, direction in vector.cycles
    ]


@pytest.mark.parametrize("source", _FILE_CASES, ids=_FILE_IDS)
def test_6502_vectors(source: Path | None):
    if source is None:
        pytest.skip(
            "SingleStepTests vectors are missing; run scripts/fetch_test_vectors.py"
        )

    for vector in iter_vector_file(source):
        cpu, memory = adapt_vector(vector)
        result = cpu.step()
        final = vector.final

        assert result.cycles == len(vector.cycles), vector.name
        assert cpu.state.cycles == len(vector.cycles), vector.name
        assert cpu.state.pc.value == final["pc"], vector.name
        assert cpu.state.sp.value == final["s"], vector.name
        assert cpu.state.a.value == final["a"], vector.name
        assert cpu.state.x.value == final["x"], vector.name
        assert cpu.state.y.value == final["y"], vector.name
        assert pack_status_byte(cpu.state.status) == final["p"], vector.name
        assert memory.bytes == dict(final["ram"]), vector.name
        assert memory.operations == _expected_operations(vector), vector.name
