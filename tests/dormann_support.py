"""Reusable, project-local support for opt-in Dormann exercisers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sixfiveohtwo import CPU, CPUState, MemoryBus
from tests.vector_support import VectorMemory

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DORMANN_BIN_ROOT = (_PROJECT_ROOT / "tests" / "dormann" / "bin_files").resolve()


class DormannAssetError(RuntimeError):
    """Raised when a requested Dormann binary is unavailable or unsafe."""


DormannMemory = VectorMemory


def dormann_binary(name: str) -> Path:
    """Return a regular binary below ``tests/dormann/bin_files`` only."""
    candidate = (_DORMANN_BIN_ROOT / name).resolve()
    if candidate.parent != _DORMANN_BIN_ROOT or candidate.name != name:
        raise DormannAssetError(
            "Dormann binary must be a direct child of tests/dormann/bin_files: "
            f"{name!r}"
        )
    if not candidate.is_file():
        raise DormannAssetError(
            f"Dormann binary is missing: {candidate}; "
            "run scripts/fetch_dormann_tests.py"
        )
    return candidate


def load_dormann_binary(name: str, *, load_address: int = 0) -> DormannMemory:
    """Load a bin_files binary into the machine-neutral 64 KiB test memory."""
    return _load_path(dormann_binary(name), load_address=load_address)


def dormann_asset(relative: str) -> Path:
    """Return a regular asset below the project-local Dormann directory."""
    root = _DORMANN_BIN_ROOT.parent
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise DormannAssetError(
            f"Dormann asset is missing or outside tests/dormann: {relative!r}"
        )
    return candidate


def load_dormann_asset(relative: str, *, load_address: int = 0) -> DormannMemory:
    return _load_path(dormann_asset(relative), load_address=load_address)


def _load_path(path: Path, *, load_address: int) -> DormannMemory:
    if not 0 <= load_address <= 0xFFFF:
        raise ValueError("load_address must fit in 16 bits")
    payload = path.read_bytes()
    if len(payload) > 0x10000 - load_address:
        raise DormannAssetError(f"Dormann binary does not fit at 0x{load_address:04X}")
    memory = DormannMemory()
    for offset, value in enumerate(payload):
        memory.write_byte(load_address + offset, value)
    memory.reset_operations()
    return memory


@dataclass(frozen=True)
class DormannRun:
    """The observable result of a finite exerciser run."""

    status: str
    steps: int
    pc: int
    message: str
    diagnostics: str = ""


def run_dormann(
    name: str,
    *,
    start: int,
    budget: int,
    success_pcs: frozenset[int],
    failure_pcs: frozenset[int] = frozenset(),
    failure_memory_addresses: frozenset[int] = frozenset(),
    diagnostic_memory_addresses: frozenset[int] = frozenset(),
    load_address: int = 0,
    asset: bool = False,
) -> DormannRun:
    """Execute one instruction per public ``CPU.step`` call until a trap."""
    if budget <= 0:
        raise ValueError("budget must be positive")
    if not 0 <= start <= 0xFFFF:
        raise ValueError("start must fit in 16 bits")
    memory = (
        load_dormann_asset(name, load_address=load_address)
        if asset
        else load_dormann_binary(name, load_address=load_address)
    )
    cpu = CPU(memory, state=CPUState(program_counter=start))

    def diagnostics() -> str:
        state = cpu.state
        flags = state.status.to_byte()
        values = ", ".join(
            f"0x{address:04X}=0x{memory.read_byte(address):02X}"
            for address in sorted(diagnostic_memory_addresses)
        )
        return (
            f"A=0x{state.a.value:02X} X=0x{state.x.value:02X} "
            f"Y=0x{state.y.value:02X} SP=0x{state.sp.value:02X} "
            f"PC=0x{state.pc.value:04X} cycles={state.cycles} "
            f"P=0x{flags:02X} ({state.status})"
            + (f"; memory: {values}" if values else "")
        )

    for steps in range(1, budget + 1):
        cpu.step()
        pc = cpu.state.pc.value
        if pc in failure_pcs or (
            pc in success_pcs
            and any(
                memory.read_byte(address) != 0 for address in failure_memory_addresses
            )
        ):
            detail = "failure trap" if pc in failure_pcs else "failure marker"
            return DormannRun(
                "failure",
                steps,
                pc,
                f"Dormann {name} reached {detail} at 0x{pc:04X}",
                diagnostics(),
            )
        if pc in success_pcs:
            return DormannRun(
                "success",
                steps,
                pc,
                f"Dormann {name} passed at 0x{pc:04X}",
                diagnostics(),
            )
    pc = cpu.state.pc.value
    return DormannRun(
        "budget",
        budget,
        pc,
        f"Dormann {name} exhausted the {budget}-instruction budget at 0x{pc:04X}",
        diagnostics(),
    )


assert isinstance(DormannMemory(), MemoryBus)
