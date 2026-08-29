"""Opt-in execution tests for the externally provisioned Dormann exercisers."""

from __future__ import annotations

import pytest

from tests.dormann_support import DormannAssetError, run_dormann


@pytest.mark.integration
@pytest.mark.parametrize(
    ("name", "start", "success_pc"),
    [("6502_functional_test.bin", 0x0400, 0x3469)],
)
def test_functional_exerciser_passes(name, start, success_pc):
    try:
        result = run_dormann(
            name,
            start=start,
            budget=40_000_000,
            success_pcs=frozenset({success_pc}),
            trap_on_self_loop=True,
        )
    except DormannAssetError as error:
        pytest.skip(str(error))

    assert result.status == "success", f"{result.message}; {result.diagnostics}"


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
