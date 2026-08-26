"""Deterministic unit tests for Dormann runner boundaries."""

from __future__ import annotations

import pytest

import tests.dormann_support as support
from tests.vector_support import VectorMemory


def test_dormann_asset_rejects_paths_outside_project_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(
        support,
        "_DORMANN_BIN_ROOT",
        tmp_path / "tests" / "dormann" / "bin_files",
    )

    with pytest.raises(support.DormannAssetError, match="missing or outside"):
        support.dormann_asset("..\\outside.bin")


def test_absent_dormann_artifact_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(support, "_DORMANN_BIN_ROOT", tmp_path)
    with pytest.raises(
        pytest.skip.Exception, match="run scripts/fetch_dormann_tests.py"
    ):
        try:
            support.dormann_binary("not-provisioned.bin")
        except support.DormannAssetError as error:
            pytest.skip(str(error))


def test_runner_detects_success_trap(monkeypatch):
    memory = VectorMemory()
    memory.bytes.update({0x0400: 0x4C, 0x0401: 0x34, 0x0402: 0x12})
    monkeypatch.setattr(
        support, "load_dormann_binary", lambda name, load_address=0: memory
    )

    result = support.run_dormann(
        "synthetic.bin",
        start=0x0400,
        budget=2,
        success_pcs=frozenset({0x1234}),
    )

    assert result.status == "success"
    assert result.steps == 1
    assert result.pc == 0x1234


def test_runner_reports_failure_trap_and_diagnostics(monkeypatch):
    memory = VectorMemory()
    memory.bytes.update({0x0400: 0x4C, 0x0401: 0x35, 0x0402: 0x12, 0x0020: 0xAB})
    monkeypatch.setattr(
        support, "load_dormann_binary", lambda name, load_address=0: memory
    )

    result = support.run_dormann(
        "synthetic.bin",
        start=0x0400,
        budget=2,
        success_pcs=frozenset({0x1234}),
        failure_pcs=frozenset({0x1235}),
        diagnostic_memory_addresses=frozenset({0x0020}),
    )

    assert result.status == "failure"
    assert result.steps == 1
    assert result.pc == 0x1235
    assert "failure trap" in result.message
    assert "0x0020=0xAB" in result.diagnostics


def test_runner_reports_instruction_budget_exhaustion(monkeypatch):
    memory = VectorMemory()
    memory.bytes.update({0x0400: 0x4C, 0x0401: 0x00, 0x0402: 0x04})
    monkeypatch.setattr(
        support, "load_dormann_binary", lambda name, load_address=0: memory
    )

    result = support.run_dormann(
        "synthetic.bin",
        start=0x0400,
        budget=2,
        success_pcs=frozenset({0x1234}),
    )

    assert result.status == "budget"
    assert result.steps == 2
    assert result.pc == 0x0400
    assert "2-instruction budget" in result.message
