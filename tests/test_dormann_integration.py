"""Opt-in execution tests for the externally provisioned Dormann exercisers."""

from __future__ import annotations

import pytest

from sixfiveohtwo import CPU, CPUState
from tests.dormann_support import (
    DormannAssetError,
    dormann_binary,
    load_dormann_asset,
    run_dormann,
)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("name", "start", "success_pc"),
    [("6502_functional_test.bin", 0x0400, 0x36DD)],
)
def test_functional_exerciser_passes(name, start, success_pc):
    result = run_dormann(
        name,
        start=start,
        budget=5_000_000,
        success_pcs=frozenset({success_pc}),
        failure_pcs=frozenset({0x3469}),
    )

    assert result.status == "success", result.message


@pytest.mark.integration
def test_decimal_exerciser_passes():
    try:
        memory = load_dormann_asset("6502_decimal_test.bin")
    except DormannAssetError as error:
        pytest.skip(str(error))
    cpu = CPU(memory, state=CPUState(program_counter=0x0400))

    for steps in range(1, 20_000_000 + 1):
        cpu.step()
        if cpu.state.pc.value == 0x044B:
            if memory.read_byte(0x000B) != 0:
                pytest.fail(
                    "Dormann decimal exerciser failed at 0x044B after "
                    f"{steps} instructions"
                )
            return

    pytest.fail(
        "Dormann decimal exerciser exhausted its 20000000-instruction budget "
        f"at 0x{cpu.state.pc.value:04X}"
    )


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
