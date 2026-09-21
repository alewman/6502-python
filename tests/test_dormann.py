"""Klaus Dormann's 6502 functional and decimal exercisers, run to their end traps.

Both are programs a real NMOS 6502 passes: every outcome ends in a ``JMP *``
self-loop, and the loop's address says which. They are gated as slow (about
27 million instructions for the functional test). Fetch both with
``scripts/fetch_dormann_tests.py``; the decimal test is assembled there with
cc65's ca65 and is skipped without it.
"""

from pathlib import Path

import pytest

from sixfiveohtwo import MOS6502

DORMANN = Path(__file__).resolve().parent / "dormann"
FUNCTIONAL = DORMANN / "bin_files" / "6502_functional_test.bin"
DECIMAL = DORMANN / "6502_decimal_test.bin"

#: The functional test's success trap (its listing, label ``success``).
FUNCTIONAL_SUCCESS = 0x3469
#: The decimal test's ERROR byte: 1 while running and on failure, 0 on success.
DECIMAL_ERROR = 0x000B

pytestmark = pytest.mark.slow


def run_to_trap(image: bytes, start: int, budget: int) -> tuple[MOS6502, bytearray, int]:
    """Run from ``start`` until the program jumps to itself; return the CPU, RAM and steps."""
    memory = bytearray(image.ljust(0x10000, b"\0"))
    cpu = MOS6502(memory.__getitem__, memory.__setitem__)
    cpu.pc = start
    step = cpu.step
    previous = -1
    for steps in range(budget):
        pc = cpu.pc
        if pc == previous:
            return cpu, memory, steps
        previous = pc
        step()
    raise AssertionError(f"no trap within {budget} instructions; PC=0x{cpu.pc:04X}")


@pytest.mark.skipif(not FUNCTIONAL.is_file(), reason="run scripts/fetch_dormann_tests.py")
def test_functional_exerciser_reaches_success() -> None:
    cpu, _, _ = run_to_trap(FUNCTIONAL.read_bytes(), 0x0400, 40_000_000)
    assert cpu.pc == FUNCTIONAL_SUCCESS, f"trapped at 0x{cpu.pc:04X}: see the test's listing"


@pytest.mark.skipif(
    not DECIMAL.is_file(), reason="needs cc65: run scripts/fetch_dormann_tests.py with ca65"
)
def test_decimal_exerciser_reports_no_error() -> None:
    image = bytearray(DECIMAL.read_bytes())
    image[DECIMAL_ERROR] = 0xA5  # the test must overwrite it: 1 while running, 0 on success
    cpu, memory, _ = run_to_trap(bytes(image), 0x0400, 40_000_000)
    assert memory[DECIMAL_ERROR] == 0, f"ERROR={memory[DECIMAL_ERROR]} at PC 0x{cpu.pc:04X}"
