"""Smoke-test the installed 6502-python package, from outside the source tree.

    python scripts/smoke_installed_package.py

CI runs this against the freshly built wheel. It must pass with only the
installed package importable.
"""

from pathlib import Path

import sixfiveohtwo
from sixfiveohtwo import MOS6502, CPUState, DebugSession, disassemble_bytes

source_tree = Path(__file__).resolve().parents[1] / "src"
assert source_tree not in Path(sixfiveohtwo.__file__).resolve().parents, sixfiveohtwo.__file__

memory = bytearray(0x10000)
cpu = MOS6502(memory.__getitem__, memory.__setitem__)
memory[:2] = bytes((0xA9, 0x2A))  # LDA #$2A
assert cpu.capture_state() == CPUState()
assert disassemble_bytes(memory[:2]).text == "LDA #$2A"
record = DebugSession(cpu, peek_byte=memory.__getitem__, track_accesses=True).step()
assert (record.after.a, record.cycles) == (0x2A, 2)
assert record.accesses == (("r", 0, 0xA9), ("r", 1, 0x2A))
print(f"6502-python {sixfiveohtwo.__file__}: installed package OK")
