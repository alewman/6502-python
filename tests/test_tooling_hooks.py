"""The tooling's subclassing surface (docs/api-stability.md), held by a toy CPU.

``65816-python`` reuses :class:`DebugSession`, the trace functions and
:class:`CommandDebugger` by subclassing them for a part with 24-bit
addresses, a state of its own, more boundary kinds and IO cycles. The toy
here does the same, so a refactor that ties them back to the 6502 fails in
this repository first.
"""

import io
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

import pytest

from sixfiveohtwo.console import CommandDebugger
from sixfiveohtwo.debug import DebugSession, StepRecord, StopReason
from sixfiveohtwo.trace import first_trace_divergence, read_trace, write_trace


@dataclass(frozen=True, slots=True)
class ToyState:
    pc: int  # 24 bits
    a: int
    s: int
    waiting: bool


class ToyKind(Enum):
    INSTRUCTION = "instruction"
    WAIT_IDLE = "wait_idle"


@dataclass(frozen=True, slots=True)
class ToyInstruction:
    address: int
    data: bytes
    mnemonic: str
    operands: tuple[str, ...] = ()

    @property
    def next_address(self) -> int:
        return (self.address + len(self.data)) & 0xFFFFFF

    @property
    def text(self) -> str:
        return " ".join((self.mnemonic, *self.operands))


# Opcode 0: NOP (1 byte: a read, then an IO cycle). 1 nn: LDA nn (an operand
# read). 2 aa bb cc: STA at a 24-bit address. 3: WAI (the CPU then idles).
LENGTHS = {0: 1, 1: 2, 2: 4, 3: 1}
CYCLES = {0: 2, 1: 3, 2: 6, 3: 2}  # one per bus call


def toy_decode(data: bytes, address: int) -> ToyInstruction:
    opcode = data[0]
    if opcode == 1:
        return ToyInstruction(address, data[:2], "LDA", (f"#${data[1]:02X}",))
    if opcode == 2:
        target = data[1] | data[2] << 8 | data[3] << 16
        return ToyInstruction(address, data[:4], "STA", (f"${target:06X}",))
    return ToyInstruction(address, data[:1], "WAI" if opcode == 3 else "NOP")


@dataclass(frozen=True, slots=True)
class ToyRecord(StepRecord):
    state_type = ToyState
    kind_type = ToyKind
    instruction_kind = ToyKind.INSTRUCTION
    halted_kinds = frozenset((ToyKind.WAIT_IDLE,))
    instruction_type = ToyInstruction
    access_kinds = frozenset(("r", "w", "i"))
    address_mask = 0xFFFFFF

    @staticmethod
    def decode(data: bytes, address: int) -> ToyInstruction:
        return toy_decode(data, address)


class Toy:
    def __init__(self, memory: dict[int, int]) -> None:
        self.memory = memory
        self.read_byte = lambda address: self.memory.get(address, 0)
        self.write_byte = self.memory.__setitem__
        self.idle = lambda address: None
        self.pc, self.a, self.s, self.waiting = 0x018000, 0, 0x1FF, False

    def capture_state(self) -> ToyState:
        return ToyState(self.pc, self.a, self.s, self.waiting)

    def step(self) -> int:
        if self.waiting:
            self.idle(self.pc)
            return 1
        opcode = self.read_byte(self.pc)
        if opcode == 1:
            self.a = self.read_byte(self.pc + 1)
        elif opcode == 2:
            target = sum(self.read_byte(self.pc + n) << (8 * (n - 1)) for n in (1, 2, 3))
            self.write_byte(target, self.a)
        elif opcode == 3:
            self.waiting = True
        self.idle(self.pc)
        self.pc += LENGTHS[opcode]
        return CYCLES[opcode]


class ToySession(DebugSession):
    record_type = ToyRecord

    def boundary(self, state: ToyState) -> ToyKind:
        return ToyKind.WAIT_IDLE if state.waiting else ToyKind.INSTRUCTION

    def decode(self, state: ToyState) -> ToyInstruction:
        return toy_decode(bytes(self.peek_byte(state.pc + n) for n in range(4)), state.pc)

    def _wrap_bus(self) -> None:
        super()._wrap_bus()
        cpu, log = self.cpu, self._accesses
        idle = cpu.idle
        self._originals = (*self._originals, idle)

        def tracked_idle(address: int) -> None:
            log.append(("i", address, 0))
            idle(address)

        cpu.idle = tracked_idle

    def _unwrap_bus(self, originals: tuple) -> None:
        super()._unwrap_bus(originals[:2])
        self.cpu.idle = originals[2]


class ToyDebugger(CommandDebugger):
    prompt = "toy> "
    registers: ClassVar[dict[str, int]] = {"A": 0xFF, "PC": 0xFFFFFF}

    def format_state(self, state: ToyState) -> tuple[str, ...]:
        return (f"PC={state.pc:06X} A={state.a:02X} WAIT={int(state.waiting)}",)

    def disassemble_at(self, peek: object, address: int, state: ToyState) -> ToyInstruction:
        return toy_decode(bytes(peek(address + n) for n in range(4)), address)

    def set_register(self, name: str, value: int) -> None:
        setattr(self.session.cpu, name.lower(), value)


PROGRAM = {0x018000: 1, 0x018001: 0x42, 0x018002: 2, 0x018003: 0x56, 0x018004: 0x34}
PROGRAM |= {0x018005: 0x12, 0x018006: 0, 0x018007: 3}


def session(**options: object) -> ToySession:
    toy = Toy(dict(PROGRAM))
    return ToySession(toy, peek_byte=lambda address: toy.memory.get(address, 0), **options)


def test_records_carry_the_subclass_state_kinds_and_24_bit_accesses() -> None:
    debug = session(track_accesses=True)
    load, store = debug.step(), debug.step()
    assert type(load) is ToyRecord and type(load.before) is ToyState
    assert load.instruction.text == "LDA #$42"
    assert store.accesses == (
        ("r", 0x018002, 2),
        ("r", 0x018003, 0x56),
        ("r", 0x018004, 0x34),
        ("r", 0x018005, 0x12),
        ("w", 0x123456, 0x42),
        ("i", 0x018002, 0),
    )
    debug.close()
    assert debug.cpu.idle.__name__ == "<lambda>"


def test_breakpoints_watchpoints_and_halts_use_the_hooks() -> None:
    debug = session(track_accesses=True)
    debug.add_breakpoint(0x018006)
    assert debug.run(max_steps=10).reason is StopReason.BREAKPOINT
    debug.add_watchpoint(0x123456, "w")
    debug.cpu.pc = 0x018002
    result = debug.run(max_steps=10)
    assert result.reason is StopReason.WATCHPOINT and result.hits == (("w", 0x123456, 0x42),)
    debug.breakpoints.clear()
    assert debug.run(max_steps=10).reason is StopReason.HALTED
    assert debug.run(max_steps=3, stop_on_halt=False).last_record.kind is ToyKind.WAIT_IDLE
    with pytest.raises(ValueError, match=r"0x000000\.\.0xFFFFFF"):
        debug.add_breakpoint(0x1000000)


def test_a_trace_round_trips_through_the_record_type() -> None:
    debug = session(track_accesses=True)
    records = [debug.step() for _ in range(5)]
    stream = io.StringIO()
    assert write_trace(records, stream) == 5
    stream.seek(0)
    read = list(read_trace(stream, record_type=ToyRecord))
    assert read == records
    assert first_trace_divergence(records, read) is None
    other = session(track_accesses=True)
    other.cpu.memory[0x018001] = 0x43
    divergence = first_trace_divergence(records, (other.step() for _ in range(5)))
    assert divergence.position == 0
    paths = {d.path for d in divergence.differences}
    assert {"after.a", "instruction.data", "instruction.operands"} <= paths


def test_the_command_debugger_speaks_the_subclass() -> None:
    debugger = ToyDebugger(session(track_accesses=True))
    assert debugger.execute("registers").lines == ("PC=018000 A=00 WAIT=0",)
    assert debugger.execute("break $018006").lines == ("breakpoint added at 018006",)
    assert debugger.execute("continue").lines[-1].endswith("PC=018006")
    assert debugger.execute("disassemble $018000 2").lines == (
        "018000  01 42        LDA #$42",
        "018002  02 56 34 12  STA $123456",
    )
    assert debugger.execute("set PC $018007").lines == ("PC=018007 A=42 WAIT=0",)
    assert debugger.execute("step 2").lines[1] == "#3 018008  wait_idle -> PC=018008 +1"
    assert debugger.execute("memory $123456 1").lines == ("123456  42",)
    out = io.StringIO()
    debugger.interact(io.StringIO("q\n"), out)
    assert out.getvalue() == "toy> "
