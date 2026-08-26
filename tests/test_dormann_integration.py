"""Opt-in execution tests for the externally provisioned Dormann exercisers."""

from __future__ import annotations

import pytest

from tests.dormann_support import DormannAssetError, dormann_binary, run_dormann


@pytest.mark.integration
@pytest.mark.parametrize(
    ("name", "start", "success_pc"),
    [("6502_functional_test.bin", 0x0400, 0x36DD)],
)
def test_functional_exerciser_passes(name, start, success_pc):
    try:
        result = run_dormann(
            name,
            start=start,
            budget=5_000_000,
            success_pcs=frozenset({success_pc}),
            failure_pcs=frozenset({0x3469}),
        )
    except DormannAssetError as error:
        pytest.skip(str(error))

    assert result.status == "success", result.message


@pytest.mark.integration
def test_decimal_exerciser_passes():
    try:
        result = run_dormann(
            "6502_decimal_test.bin",
            asset=True,
            start=0x0400,
            budget=20_000_000,
            success_pcs=frozenset({0x044B}),
            failure_memory_addresses=frozenset({0x000B}),
            diagnostic_memory_addresses=frozenset(range(0x000C)),
        )
    except DormannAssetError as error:
        pytest.skip(str(error))

    assert result.status == "success", f"{result.message}; {result.diagnostics}"


def test_dormann_locator_rejects_paths_outside_bin_files(tmp_path, monkeypatch):
    import tests.dormann_support as support

    monkeypatch.setattr(
        support,
        "_DORMANN_BIN_ROOT",
        tmp_path / "tests" / "dormann" / "bin_files",
    )
    with pytest.raises(DormannAssetError, match="direct child"):
        dormann_binary("..\\6502_decimal_test.bin")


def test_dormann_budget_result_is_actionable(tmp_path, monkeypatch):
    import tests.dormann_support as support

    root = tmp_path / "tests" / "dormann" / "bin_files"
    root.mkdir(parents=True)
    (root / "loop.bin").write_bytes(bytes((0x4C, 0x00, 0x04)))
    monkeypatch.setattr(support, "_DORMANN_BIN_ROOT", root)

    result = run_dormann(
        "loop.bin", start=0x0400, budget=2, success_pcs=frozenset({0x1234})
    )

    assert result.status == "budget"
    assert "2-instruction budget" in result.message
