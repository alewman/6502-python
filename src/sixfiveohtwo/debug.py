"""Dependency-free execution control and structured debugging records.

``DebugSession`` drives an existing CPU -- any object with ``step()`` and
``capture_state()`` -- one boundary at a time, with execute breakpoints,
bounded runs, a history ring and, optionally, bus-access tracking and
watchpoints. It never changes what the core does. See docs/debug-session.md.

The defaults describe the NMOS 6502. A core for another 65xx-family part
subclasses :class:`StepRecord` and :class:`DebugSession` and overrides their
documented hooks (its state type, boundary kinds, address width,
disassembler and bus) to reuse the rest; docs/api-stability.md lists them.
"""

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, is_dataclass
from enum import Enum
from typing import Any, ClassVar, Protocol, runtime_checkable

from sixfiveohtwo._core import I
from sixfiveohtwo.disasm import ByteReader, Instruction, disassemble, disassemble_bytes
from sixfiveohtwo.state import CPUState


@runtime_checkable
class DebugTarget(Protocol):
    """Minimum processor interface consumed by :class:`DebugSession`."""

    def step(self) -> int:
        """Advance one instruction or lifecycle boundary and return cycles."""

    def capture_state(self) -> CPUState:
        """Capture the current CPU-owned state."""


class BoundaryKind(Enum):
    """Kind of work performed by one target ``step()`` call."""

    INSTRUCTION = "instruction"
    JAM_IDLE = "jam_idle"  # a cycle spent stopped by JAM
    RESET = "reset"
    NMI = "nmi"
    IRQ = "irq"


class StopReason(Enum):
    """Why a bounded debug-session run returned control."""

    BREAKPOINT = "breakpoint"  # before the instruction at a breakpoint
    WATCHPOINT = "watchpoint"  # after the step that touched a watched address
    HALTED = "halted"  # JAM has stopped the CPU
    STEP_LIMIT = "step_limit"
    CYCLE_LIMIT = "cycle_limit"


#: One bus access, ``(kind, address, value)``, in the order the step made
#: them: exactly one per cycle. On the 6502 the kind is ``"r"`` or ``"w"``; a
#: subclass's kinds start with ``"r"`` or ``"w"`` too, or with a letter of its
#: own for a cycle that is neither (watchpoints match the first letter).
Access = tuple[str, int, int]


@dataclass(frozen=True, slots=True)
class StepRecord:
    """Immutable before/after evidence for one processor boundary.

    The class attributes are the hooks a subclass for another part sets: the
    types its fields must have, the access kinds and the address width, and
    :meth:`decode`, which a trace reader uses to rebuild an instruction.
    """

    #: The CPU state type ``before`` and ``after`` hold.
    state_type: ClassVar[type] = CPUState
    #: The enum ``kind`` is a member of, and its member for an instruction.
    kind_type: ClassVar[type[Enum]] = BoundaryKind
    instruction_kind: ClassVar[Enum] = BoundaryKind.INSTRUCTION
    #: The kinds that mean a stopped CPU, for ``DebugSession.run(stop_on_halt=True)``.
    halted_kinds: ClassVar[frozenset[Enum]] = frozenset((BoundaryKind.JAM_IDLE,))
    instruction_type: ClassVar[type] = Instruction
    access_kinds: ClassVar[frozenset[str]] = frozenset(("r", "w"))
    address_mask: ClassVar[int] = 0xFFFF

    sequence: int
    kind: BoundaryKind
    before: CPUState
    after: CPUState
    cycles: int
    instruction: Instruction | None
    #: Every bus access the step made, in order, when the session tracks
    #: accesses; ``None`` when it does not.
    accesses: tuple[Access, ...] | None = None

    @staticmethod
    def decode(data: bytes, address: int) -> Instruction:
        """The instruction ``data`` encodes at ``address`` (a trace reader's decoder)."""
        return disassemble_bytes(data, address)

    def __post_init__(self) -> None:
        cls = type(self)
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if type(self.kind) is not cls.kind_type:
            raise ValueError(f"kind must be a {cls.kind_type.__name__}")
        state = cls.state_type
        if type(self.before) is not state or type(self.after) is not state:
            raise ValueError(f"before and after must be {state.__name__} values")
        if type(self.cycles) is not int or self.cycles <= 0:
            raise ValueError("cycles must be a positive integer")
        if self.instruction is not None and type(self.instruction) is not cls.instruction_type:
            raise ValueError(f"instruction must be an {cls.instruction_type.__name__} or None")
        if self.kind is not cls.instruction_kind and self.instruction is not None:
            raise ValueError("lifecycle boundaries cannot contain an instruction")
        if self.accesses is not None and (
            type(self.accesses) is not tuple
            or not all(cls.valid_access(access) for access in self.accesses)
        ):
            raise ValueError("accesses must be a tuple of (kind, address, value) or None")

    @classmethod
    def valid_access(cls, access: object) -> bool:
        """Whether ``access`` is a ``(kind, address, value)`` this record type allows."""
        if type(access) is not tuple or len(access) != 3:
            return False
        kind, address, value = access
        return (
            kind in cls.access_kinds
            and type(address) is int
            and 0 <= address <= cls.address_mask
            and type(value) is int
            and 0 <= value <= 0xFF
        )


def _valid_hit(access: object) -> bool:
    if type(access) is not tuple or len(access) != 3:
        return False
    kind, address, value = access
    return type(kind) is str and type(address) is int and type(value) is int


@dataclass(frozen=True, slots=True)
class RunResult:
    """Summary of one bounded run operation."""

    reason: StopReason
    steps: int
    instructions: int
    cycles: int
    state: Any  # the session's state type: CPUState on the 6502
    last_record: StepRecord | None
    #: For WATCHPOINT: the watched accesses that stopped the run.
    hits: tuple[Access, ...] = ()

    def __post_init__(self) -> None:
        if type(self.reason) is not StopReason:
            raise ValueError("reason must be a StopReason")
        for name in ("steps", "instructions", "cycles"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.instructions > self.steps:
            raise ValueError("instructions cannot exceed steps")
        if not is_dataclass(self.state) or isinstance(self.state, type):
            raise ValueError("state must be a CPU state value")
        if self.last_record is not None and not isinstance(self.last_record, StepRecord):
            raise ValueError("last_record must be a StepRecord or None")
        if type(self.hits) is not tuple or not all(_valid_hit(hit) for hit in self.hits):
            raise ValueError("hits must be a tuple of (kind, address, value) accesses")


def next_boundary(state: CPUState) -> BoundaryKind:
    """What the next ``step()`` will do, decided exactly as ``MOS6502.step()`` decides it."""

    if state.reset_pending:
        return BoundaryKind.RESET
    if state.halted:
        return BoundaryKind.JAM_IDLE
    if state.skipped_poll:
        return BoundaryKind.INSTRUCTION
    nmi = state.polled_non_maskable_interrupt
    if state.non_maskable_interrupt_pending if nmi is None else nmi:
        return BoundaryKind.NMI
    irq = state.polled_maskable_interrupt
    masked = bool(state.p & I) if state.polled_i is None else state.polled_i
    if (state.maskable_interrupt_pending if irq is None else irq) and not masked:
        return BoundaryKind.IRQ
    return BoundaryKind.INSTRUCTION


class DebugSession:
    """Control an existing CPU host without modifying its execution core.

    ``peek_byte`` must be side-effect-free (the host's memory, not its bus). If
    it is omitted, stepping and breakpoints still work but step records do not
    contain disassembly.

    ``track_accesses=True`` wraps the CPU's two bus callables (``read_byte``,
    ``write_byte``) to record every access in
    :attr:`StepRecord.accesses` and to enable watchpoints; :meth:`close` puts
    the originals back. The target may be a whole board rather than a bare
    CPU: an object whose ``step()`` runs its devices around one CPU step and
    whose ``cpu`` attribute is the processor, whose bus is then the one tracked.

    A subclass for another part sets :attr:`record_type` and overrides
    :meth:`boundary`, :meth:`program_address`, :meth:`decode` and, if its bus
    has more callables, :meth:`_wrap_bus`.
    """

    #: The StepRecord subclass this session makes; its hooks give the state
    #: type, kinds and address width.
    record_type: ClassVar[type[StepRecord]] = StepRecord

    def __init__(
        self,
        target: DebugTarget,
        *,
        peek_byte: ByteReader | None = None,
        history_limit: int = 256,
        track_accesses: bool = False,
    ) -> None:
        if not isinstance(target, DebugTarget):
            raise TypeError("target must provide step() and capture_state()")
        if peek_byte is not None and not callable(peek_byte):
            raise TypeError("peek_byte must be callable or None")
        if type(history_limit) is not int or history_limit < 0:
            raise ValueError("history_limit must be a non-negative integer")
        if type(track_accesses) is not bool:
            raise ValueError("track_accesses must be a bool")

        self.target = target
        #: The processor: the target itself, or the ``cpu`` a board target
        #: carries. Access tracking wraps its bus callables.
        self.cpu = getattr(target, "cpu", target)
        self.peek_byte = peek_byte
        self.history_limit = history_limit
        self.breakpoints: set[int] = set()
        #: Memory watchpoints: address -> "r", "w" or "rw".
        self.watchpoints: dict[int, str] = {}
        self.total_steps = 0
        self.total_instructions = 0
        self.total_cycles = 0
        self._history: deque[StepRecord] = deque(maxlen=history_limit or 1)
        self._accesses: list[Access] | None = None
        self._originals: tuple | None = None
        if track_accesses:
            self._wrap_bus()

    # -- hooks a subclass for another part overrides ----------------------

    def boundary(self, state: Any) -> Enum:
        """What the next ``step()`` will do from ``state`` (:func:`next_boundary`)."""
        return next_boundary(state)

    def program_address(self, state: Any) -> int:
        """The address breakpoints match: the instruction's, before it runs."""
        return state.pc

    def decode(self, state: Any) -> Instruction:
        """The instruction about to run from ``state``, read with ``peek_byte``."""
        return disassemble(self.peek_byte, state.pc)

    def _wrap_bus(self) -> None:
        """Install tracking wrappers on the CPU's bus and keep the originals.

        Sets ``self._accesses`` (the list each access is appended to) and
        ``self._originals``; :meth:`_unwrap_bus` puts the originals back.
        """
        cpu = self.cpu
        originals = (cpu.read_byte, cpu.write_byte)
        read_byte, write_byte = originals
        self._originals = originals
        log: list[Access] = []
        self._accesses = log

        def tracked_read_byte(address: int) -> int:
            value = read_byte(address)
            log.append(("r", address, value))
            return value

        def tracked_write_byte(address: int, value: int) -> None:
            log.append(("w", address, value))
            write_byte(address, value)

        cpu.read_byte = tracked_read_byte
        cpu.write_byte = tracked_write_byte

    def _unwrap_bus(self, originals: tuple) -> None:
        """Give the CPU the bus callables :meth:`_wrap_bus` kept."""
        cpu = self.cpu
        cpu.read_byte, cpu.write_byte = originals

    # -- the session ------------------------------------------------------

    @property
    def tracking(self) -> bool:
        """Whether this session is recording bus accesses."""

        return self._originals is not None

    def close(self) -> None:
        """Stop tracking accesses and give the CPU its own bus callables back."""

        if self._originals is not None:
            self._unwrap_bus(self._originals)
            self._originals = None
            self._accesses = None

    @property
    def history(self) -> tuple[StepRecord, ...]:
        """Bounded immutable view of the retained step records."""

        return tuple(self._history)

    def clear_history(self) -> None:
        """Discard retained records without changing execution totals."""

        self._history.clear()

    def add_breakpoint(self, address: int) -> None:
        """Stop before executing the instruction at an address."""

        self.breakpoints.add(self._validate_address(address))

    def remove_breakpoint(self, address: int) -> None:
        """Remove an execute breakpoint if it exists."""

        self.breakpoints.discard(self._validate_address(address))

    def add_watchpoint(self, address: int, kind: str = "rw") -> None:
        """Stop after any step that reads (``"r"``), writes (``"w"``) or either (``"rw"``)
        the memory byte at ``address``."""

        if not self.tracking:
            raise ValueError("watchpoints need a session created with track_accesses=True")
        if kind not in ("r", "w", "rw"):
            raise ValueError('kind must be "r", "w" or "rw"')
        self.watchpoints[self._validate_address(address)] = kind

    def remove_watchpoint(self, address: int) -> None:
        """Remove a watchpoint if it exists."""

        self.watchpoints.pop(self._validate_address(address), None)

    def step(self) -> StepRecord:
        """Advance exactly one boundary, ignoring execute breakpoints."""

        before = self.target.capture_state()
        kind = self.boundary(before)
        instruction_kind = self.record_type.instruction_kind
        instruction = None
        if kind is instruction_kind and self.peek_byte is not None:
            instruction = self.decode(before)

        if self._accesses is not None:
            self._accesses.clear()
        cycles = self.target.step()
        if type(cycles) is not int or cycles <= 0:
            raise ValueError("target step() must return a positive integer cycle count")
        after = self.target.capture_state()
        record = self.record_type(
            sequence=self.total_steps,
            kind=kind,
            before=before,
            after=after,
            cycles=cycles,
            instruction=instruction,
            accesses=None if self._accesses is None else tuple(self._accesses),
        )
        self.total_steps += 1
        self.total_cycles += cycles
        if kind is instruction_kind:
            self.total_instructions += 1
        if self.history_limit:
            self._history.append(record)
        return record

    def run(
        self,
        *,
        max_steps: int,
        max_cycles: int | None = None,
        stop_on_halt: bool = True,
    ) -> RunResult:
        """Run until a stop condition or mandatory finite step budget is reached.

        A cycle limit is checked after each atomic boundary and may therefore be
        exceeded by that boundary's cost. Execute breakpoints stop before execution;
        watchpoints stop after the step that touched the watched byte.
        """

        if type(max_steps) is not int or max_steps <= 0:
            raise ValueError("max_steps must be a positive integer")
        if max_cycles is not None and (type(max_cycles) is not int or max_cycles <= 0):
            raise ValueError("max_cycles must be a positive integer or None")
        if type(stop_on_halt) is not bool:
            raise ValueError("stop_on_halt must be a bool")

        instruction_kind = self.record_type.instruction_kind
        halted_kinds = self.record_type.halted_kinds
        steps = 0
        instructions = 0
        cycles = 0
        last_record = None
        while steps < max_steps:
            state = self.target.capture_state()
            kind = self.boundary(state)
            if kind is instruction_kind and self.program_address(state) in self.breakpoints:
                return RunResult(
                    StopReason.BREAKPOINT,
                    steps,
                    instructions,
                    cycles,
                    state,
                    last_record,
                )
            if stop_on_halt and kind in halted_kinds:
                return RunResult(
                    StopReason.HALTED,
                    steps,
                    instructions,
                    cycles,
                    state,
                    last_record,
                )

            last_record = self.step()
            steps += 1
            cycles += last_record.cycles
            if last_record.kind is instruction_kind:
                instructions += 1
            hits = self._watch_hits(last_record)
            if hits:
                return RunResult(
                    StopReason.WATCHPOINT,
                    steps,
                    instructions,
                    cycles,
                    last_record.after,
                    last_record,
                    hits,
                )
            if max_cycles is not None and cycles >= max_cycles:
                return RunResult(
                    StopReason.CYCLE_LIMIT,
                    steps,
                    instructions,
                    cycles,
                    last_record.after,
                    last_record,
                )

        state = last_record.after if last_record is not None else self.target.capture_state()
        return RunResult(
            StopReason.STEP_LIMIT,
            steps,
            instructions,
            cycles,
            state,
            last_record,
        )

    def iter_history(self, *, newest_first: bool = False) -> Iterator[StepRecord]:
        """Iterate retained records without exposing the mutable history buffer."""

        return reversed(self._history) if newest_first else iter(self._history)

    def _watch_hits(self, record: StepRecord) -> tuple[Access, ...]:
        if not self.watchpoints or not record.accesses:
            return ()
        return tuple(
            access
            for access in record.accesses
            if access[1] in self.watchpoints and access[0][0] in self.watchpoints[access[1]]
        )

    def _validate_address(self, address: int) -> int:
        mask = self.record_type.address_mask
        if type(address) is not int or not 0 <= address <= mask:
            width = 4 if mask <= 0xFFFF else 6
            raise ValueError(f"address must be an integer in range 0x{0:0{width}X}..0x{mask:X}")
        return address


__all__ = [
    "Access",
    "BoundaryKind",
    "DebugSession",
    "DebugTarget",
    "RunResult",
    "StepRecord",
    "StopReason",
    "next_boundary",
]
