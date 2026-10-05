"""Instructions per second for four representative workloads.

    python benchmarks/core_benchmark.py [--instructions N] [--repeats R]

Each workload is a loop that never ends, so a run is exactly N instructions:

- ``base``: loads, ALU, an indexed store and a taken branch -- ordinary code;
- ``rmw``: read-modify-writes, absolute,X and zero page, with their dummy writes;
- ``stack``: JSR/RTS and PHA/PLA, whose stack cycles are mostly dummy reads;
- ``decimal``: ADC and SBC with D set.

The host is a bytearray's own methods, the fastest callable bus on both
interpreters. Rates on a shared machine move with its load: to measure a
change, use compare_revisions.py, which times two revisions alternately in
one process.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sixfiveohtwo import MOS6502


@dataclass(frozen=True)
class Workload:
    name: str
    program: bytes


ORIGIN = 0x0400

WORKLOADS = (
    Workload(
        "base",
        # loop: INX; LDA $10,X; CLC; ADC #$01; STA $0200,X; CMP #$80; BNE loop; JMP loop
        bytes.fromhex("e8 b5 10 18 69 01 9d 00 02 c9 80 d0 f3 4c 00 04"),
    ),
    Workload(
        "rmw",
        # loop: INX; INC $0300,X; ASL $20; ROR $0300,X; DEC $21; JMP loop
        bytes.fromhex("e8 fe 00 03 06 20 7e 00 03 c6 21 4c 00 04"),
    ),
    Workload(
        "stack",
        # loop: JSR sub; PHA; PLA; JMP loop; sub: RTS
        bytes.fromhex("20 09 04 48 68 4c 00 04 ea 60"),
    ),
    Workload(
        "decimal",
        # SED; loop: CLC; ADC #$19; SEC; SBC #$07; JMP loop
        bytes.fromhex("f8 18 69 19 38 e9 07 4c 01 04"),
    ),
)


def BenchmarkCPU(program: bytes) -> MOS6502:  # the name compare_revisions expects
    memory = bytearray(0x10000)
    memory[ORIGIN : ORIGIN + len(program)] = program
    cpu = MOS6502(memory.__getitem__, memory.__setitem__)
    cpu.pc = ORIGIN
    cpu.s = 0xFF
    return cpu


def _execute(cpu: MOS6502, instructions: int) -> None:
    step = cpu.step
    for _ in range(instructions):
        step()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--instructions",
        type=int,
        default=5_000_000 if sys.implementation.name == "pypy" else 300_000,
    )
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)
    implementation = f"{sys.implementation.name} {sys.version.split()[0]}"
    print(f"{implementation}: best of {args.repeats} x {args.instructions:,} instructions")
    for workload in WORKLOADS:
        best = 0.0
        for _ in range(args.repeats):
            cpu = BenchmarkCPU(workload.program)
            _execute(cpu, args.instructions // 10)  # warm up
            started = time.process_time()
            _execute(cpu, args.instructions)
            best = max(best, args.instructions / (time.process_time() - started))
        print(f"  {workload.name:8} {best / 1e6:8.3f} M instr/s")


if __name__ == "__main__":
    main()
