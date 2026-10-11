"""Public NMOS 6502 CPU class.

The host owns memory and every device: it passes ``read_byte(address)`` and
``write_byte(address, value)`` in, calls :meth:`MOS6502.step`, and adds the
returned cycle count to its own clock. See docs/start-here.md, "The embedding
contract".
"""

from sixfiveohtwo._alu import ALUMixin
from sixfiveohtwo._control import VECTOR_IRQ, VECTOR_NMI, ControlMixin
from sixfiveohtwo._core import (
    IRQ_LINE,
    NMI_LATCH,
    NO_POLL,
    STACK,
    B,
    C,
    CoreMixin,
    D,
    I,
    N,
    ReadByte,
    U,
    V,
    WriteByte,
    Z,
)
from sixfiveohtwo._dispatch import Entry, build_table
from sixfiveohtwo._loads import LoadMixin
from sixfiveohtwo._shifts import ShiftMixin
from sixfiveohtwo._undocumented import UndocumentedMixin
from sixfiveohtwo.state import CPUState

FLAG_N, FLAG_V, FLAG_U, FLAG_B, FLAG_D, FLAG_I, FLAG_Z, FLAG_C = N, V, U, B, D, I, Z, C

_BUS = ("read_byte", "write_byte")


class MOS6502(
    ALUMixin,
    LoadMixin,
    ShiftMixin,
    ControlMixin,
    UndocumentedMixin,
    CoreMixin,
):
    """An NMOS 6502 instruction core whose memory is two callables supplied by a host.

    ``read_byte(address)`` and ``write_byte(address, value)`` are the bus.
    The core always passes a 16-bit address and an 8-bit value, so a flat
    host is two arguments::

        memory = bytearray(0x10000)
        cpu = MOS6502(memory.__getitem__, memory.__setitem__)

    Every cycle is a bus access, so ``step()`` calls the bus once per cycle it
    returns, dummy reads and read-modify-write dummy writes included, in the
    chip's order. Memory-mapped devices therefore see what they would see on
    a board.

    Registers are plain attributes: ``a``, ``x``, ``y``, ``s`` (8-bit), ``pc``
    (16-bit) and ``p``, which keeps bit 5 set and B clear. The two bus
    callables are attributes too and may be replaced later (the debugger's
    access tracking does exactly that); the core keeps sampling the
    interrupt requests at each access of the replacement. A new CPU has
    zeroed registers and I set; :meth:`request_reset` runs the chip's start
    sequence.
    """

    _table: list[Entry]

    def __init__(self, read_byte: ReadByte, write_byte: WriteByte) -> None:
        for name, bus in zip(_BUS, (read_byte, write_byte), strict=True):
            if not callable(bus):
                hint = ""
                if callable(getattr(bus, name, None)):
                    # Until 0.2.0 the CPU took one object with both methods.
                    hint = "; since 0.2.0 pass the methods: MOS6502(bus.read_byte, bus.write_byte)"
                raise TypeError(f"{name} must be callable, not {type(bus).__name__}{hint}")
        self._init_core()
        self.read_byte = read_byte
        self.write_byte = write_byte
        cls = type(self)
        if "_table" not in cls.__dict__:
            cls._table = build_table(cls)

    # -- the bus ---------------------------------------------------------

    @property
    def read_byte(self) -> ReadByte:
        """The host's ``read_byte(address)``, as passed in or last assigned."""
        return self._read_byte

    @read_byte.setter
    def read_byte(self, read_byte: ReadByte) -> None:
        self._read_byte = read_byte
        if self._deferred is None:
            self._read = read_byte

    @property
    def write_byte(self) -> WriteByte:
        """The host's ``write_byte(address, value)``, as passed in or last assigned."""
        return self._write_byte

    @write_byte.setter
    def write_byte(self, write_byte: WriteByte) -> None:
        self._write_byte = write_byte
        if self._deferred is None:
            self._write = write_byte

    def step(self) -> int:
        """Execute one instruction, interrupt entry or reset; return its cycle count.

        At an instruction boundary: a pending reset runs the start sequence; a
        JAMmed CPU stays stopped, reading $FFFF for one cycle; an NMI the last
        instruction's poll saw is taken; so is an IRQ it saw, if the I flag
        that poll saw is clear; otherwise one instruction runs.

        The poll sees the requests as they stood at the end of the
        instruction's second-to-last cycle, so one a bus callback makes
        during the last cycle waits for the next instruction's poll. One the
        host makes between steps is taken at the next boundary. BRK,
        interrupt entries and reset do not poll: one instruction runs after
        them before anything requested since is taken.
        """
        if self._reset_pending:
            return self._accept_reset()
        if self.halted:
            self._read(0xFFFF)
            return 1
        polled = self._polled
        if polled is None:
            polled = self._requests
        else:
            self._polled = None
        if polled & NMI_LATCH:
            return self._enter_interrupt(VECTOR_NMI)
        polled_i = self._polled_i
        if polled_i is None:
            if polled & IRQ_LINE and not self.p & I:
                return self._enter_interrupt(VECTOR_IRQ)
        else:
            self._polled_i = None
            if polled & IRQ_LINE and not polled_i:
                return self._enter_interrupt(VECTOR_IRQ)

        pc = self.pc
        opcode = self._read(pc)
        self.pc = (pc + 1) & 0xFFFF
        handler, mode, cycles = self._table[opcode]
        if mode is None:
            handler(self)
        else:
            handler(self, mode(self))
        deferred = self._deferred
        if deferred is not None:
            # A bus callback changed a request in the last cycle, after the poll.
            self._polled = deferred
            self._deferred = None
        extra = self._extra
        if extra:
            self._extra = 0
            return cycles + extra
        return cycles

    # -- interrupt and reset inputs ------------------------------------

    @property
    def reset_pending(self) -> bool:
        """Whether a reset has been requested and not yet run."""
        return self._reset_pending

    def request_reset(self) -> None:
        """Run the seven-cycle start sequence at the next boundary.

        The start sequence begins when RESET is released (PM section 9.2), so
        one request is one reset, whenever the host's board releases the line.
        Reset has priority over everything, and restarts a JAMmed CPU.
        """
        self._reset_pending = True

    def clear_reset(self) -> None:
        """Cancel a requested reset that has not yet reached a boundary."""
        self._reset_pending = False

    @property
    def maskable_interrupt_pending(self) -> bool:
        """Whether the IRQ line is asserted."""
        return bool(self._requests & IRQ_LINE)

    def request_maskable_interrupt(self) -> None:
        """Assert IRQ, a level: it stays asserted until :meth:`clear_maskable_interrupt`.

        Taking the interrupt does not clear it; on a board the device holds
        IRQ low until its handler acknowledges it, and so must the host. While
        it is asserted and I is clear, every poll takes the interrupt.
        """
        self._request(self._requests | IRQ_LINE)
        polled = self._polled
        if polled is not None and not polled & NO_POLL:
            self._polled = polled | IRQ_LINE

    def clear_maskable_interrupt(self) -> None:
        """Release IRQ."""
        self._request(self._requests & ~IRQ_LINE)
        if self._polled is not None:
            self._polled &= ~IRQ_LINE

    @property
    def non_maskable_interrupt_pending(self) -> bool:
        """Whether an NMI edge has been latched and not yet taken."""
        return bool(self._requests & NMI_LATCH)

    def request_non_maskable_interrupt(self) -> None:
        """Latch an NMI edge; the next poll takes it, whatever I says.

        NMI is edge-triggered: call this on the line's falling edge. Requests
        made while one is pending coalesce into one NMI.
        """
        self._request(self._requests | NMI_LATCH)
        polled = self._polled
        if polled is not None and not polled & NO_POLL:
            self._polled = polled | NMI_LATCH

    def clear_non_maskable_interrupt(self) -> None:
        """Cancel a latched NMI that has not yet been taken, even one already polled."""
        self._request(self._requests & ~NMI_LATCH)
        if self._polled is not None:
            self._polled &= ~NMI_LATCH

    # -- state -----------------------------------------------------------

    def capture_state(self) -> CPUState:
        """Return an immutable snapshot of all CPU-owned state.

        No host reads, no side effects. Memory and devices are the host's and
        are not included (docs/cpu-state.md).
        """
        polled_i = self._polled_i
        polled = self._requests if self._polled is None else self._polled
        return CPUState(
            a=self.a,
            x=self.x,
            y=self.y,
            s=self.s,
            pc=self.pc,
            p=self.p,
            halted=self.halted,
            reset_pending=self._reset_pending,
            maskable_interrupt_pending=bool(self._requests & IRQ_LINE),
            non_maskable_interrupt_pending=bool(self._requests & NMI_LATCH),
            polled_i=None if polled_i is None else bool(polled_i),
            polled_maskable_interrupt=_differs(polled, self._requests, IRQ_LINE),
            polled_non_maskable_interrupt=_differs(polled, self._requests, NMI_LATCH),
            skipped_poll=bool(polled & NO_POLL),
        )

    def restore_state(self, state: CPUState) -> None:
        """Restore a captured CPU state without touching the host.

        Restoring the processor alone does not restore memory or devices.
        """
        if type(state) is not CPUState:
            raise TypeError("state must be a CPUState")
        self.a, self.x, self.y, self.s, self.pc, self.p = (
            state.a,
            state.x,
            state.y,
            state.s,
            state.pc,
            state.p,
        )
        self.halted = state.halted
        self._reset_pending = state.reset_pending
        self._requests = (IRQ_LINE if state.maskable_interrupt_pending else 0) | (
            NMI_LATCH if state.non_maskable_interrupt_pending else 0
        )
        polled = self._requests
        for bit, seen in (
            (IRQ_LINE, state.polled_maskable_interrupt),
            (NMI_LATCH, state.polled_non_maskable_interrupt),
        ):
            if seen is not None:
                polled = polled | bit if seen else polled & ~bit
        if state.skipped_poll:
            polled |= NO_POLL
        self._polled = None if polled == self._requests else polled
        self._confirm()
        self._polled_i = None if state.polled_i is None else (I if state.polled_i else 0)
        self._extra = 0


def _differs(polled: int, requests: int, bit: int) -> bool | None:
    """What the poll saw of ``bit`` when that is not what the host has requested, else None."""
    seen = bool(polled & bit)
    return None if seen == bool(requests & bit) else seen


class RP2A03(MOS6502):
    """The NMOS 6502 inside Nintendo's RP2A03 and RP2A07: decimal mode disconnected.

    The NES and Famicom CPU is this core with the decimal adjust cut out of
    the die ("cutting 5 pieces of polysilicon"; the instruction decoder is
    otherwise identical: the Breaks wiki, ``BreakingNESWiki_DeepL/APU/core.md``,
    die-derived). D is still a flag that SED, CLD, PHP, PLP and RTI set,
    clear, push and pull, but ADC, SBC, USBC, RRA, ISC and ARR compute in
    binary with binary flags whatever it says. SingleStepTests ``nes6502``
    checks this part as ``6502`` checks :class:`MOS6502`
    (docs/validation.md).

    The APU, DMA and the rest of the chip are the host's, like every device.
    """

    _decimal_mode = 0


__all__ = [
    "FLAG_B",
    "FLAG_C",
    "FLAG_D",
    "FLAG_I",
    "FLAG_N",
    "FLAG_U",
    "FLAG_V",
    "FLAG_Z",
    "MOS6502",
    "RP2A03",
    "STACK",
    "CPUState",
    "ReadByte",
    "WriteByte",
]
