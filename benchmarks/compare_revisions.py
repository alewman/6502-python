"""Compare the core's speed at two git revisions, in one interpreter.

    python benchmarks/compare_revisions.py OLD NEW [--rounds 30] [--instructions 50000]

Each revision is checked out into a temporary git worktree, and its package and
its own ``benchmarks/core_benchmark.py`` host are imported into this one
process (``sys.modules`` is cleared between the two imports). The workloads are
then timed alternately, OLD and NEW in turn, and each rate is the best sample
in CPU time. ``NEW`` may be ``WORK`` for the working tree.

Why this shape: on a shared machine, separate benchmark runs moved by +-30%
with other people's load, which buries a 5-10% change. Two revisions timed
alternately in one process on one core see the same clock, cache and load, and
interference only ever slows a sample, so best-of recovers the undisturbed
rate. Pin the process to one performance core (``taskset -c 2`` on Linux)
where the CPU has more than one kind. The ratio is the result; the absolute
rates still depend on the machine and its load.
"""

from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[1]


def _load(tree: Path) -> ModuleType:
    for name in [m for m in sys.modules if m.startswith("sixfiveohtwo") or m == "core_benchmark"]:
        del sys.modules[name]
    sys.path[:0] = [str(tree / "src"), str(tree / "benchmarks")]
    try:
        return importlib.import_module("core_benchmark")
    finally:
        del sys.path[:2]


def compare(old: str, new: str, *, rounds: int, instructions: int) -> None:
    with tempfile.TemporaryDirectory() as scratch:
        trees = {}
        for revision in (old, new):
            if revision == "WORK":
                trees[revision] = REPO
                continue
            tree = Path(scratch) / revision
            subprocess.run(
                ["git", "-C", str(REPO), "worktree", "add", "-q", "--detach", str(tree), revision],
                check=True,
            )
            trees[revision] = tree
        try:
            benches = {revision: _load(tree) for revision, tree in trees.items()}
            best: dict[str, dict[str, float]] = {old: {}, new: {}}
            for round_number in range(rounds):
                order = (old, new) if round_number % 2 == 0 else (new, old)
                for revision in order:
                    bench = benches[revision]
                    for workload in bench.WORKLOADS:
                        cpu = bench.BenchmarkCPU(workload.program)
                        bench._execute(cpu, instructions // 10)  # warm up
                        started = time.process_time()
                        bench._execute(cpu, instructions)
                        rate = instructions / (time.process_time() - started)
                        best[revision][workload.name] = max(
                            best[revision].get(workload.name, 0.0), rate
                        )
        finally:
            for revision, tree in trees.items():
                if revision != "WORK":
                    subprocess.run(
                        ["git", "-C", str(REPO), "worktree", "remove", "--force", str(tree)],
                        check=True,
                    )
    implementation = f"{sys.implementation.name} {sys.version.split()[0]}"
    print(f"{implementation}: best of {rounds} x {instructions:,} instructions, CPU time")
    for name, old_rate in best[old].items():
        new_rate = best[new][name]
        print(
            f"  {name:11} {old:>9} {old_rate / 1e6:8.3f}M  {new:>9} {new_rate / 1e6:8.3f}M"
            f"  x{new_rate / old_rate:.3f}"
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument(
        "--instructions",
        type=int,
        default=3_000_000 if sys.implementation.name == "pypy" else 50_000,
    )
    args = parser.parse_args(argv)
    compare(args.old, args.new, rounds=args.rounds, instructions=args.instructions)


if __name__ == "__main__":
    main()
