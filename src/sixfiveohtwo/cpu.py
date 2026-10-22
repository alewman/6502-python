"""Public NMOS 6502 CPU class.

The host owns memory and every device: it passes ``read_byte(address)`` and
``write_byte(address, value)`` in, calls :meth:`MOS6502.step`, and adds the
returned cycle count to its own clock. See docs/start-here.md, "The embedding
contract".
"""

from sixfiveohtwo._alu import ALUMixin
from sixfiveohtwo._control import ControlMixin
from sixfiveohtwo._core import (
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
from sixfiveohtwo.frame import CPUFrame
from sixfiveohtwo.state import CPUState

FLAG_N, FLAG_V, FLAG_U, FLAG_B, FLAG_D, FLAG_I, FLAG_Z, FLAG_C = N, V, U, B, D, I, Z, C


class MOS6502(
    ALUMixin,
    LoadMixin,
    ShiftMixin,
    ControlMixin,
    UndocumentedMixin,
    CoreMixin,
    CPUFrame,
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

    The bus, the interrupt requests, their poll and ``step()``'s skeleton
    are :class:`~sixfiveohtwo.frame.CPUFrame`'s; this class is the NMOS
    instruction set and sequences on top of it.
    """

    _table: list[Entry]

    #: The chip-dependent constant ANE ($8B) and LXA ($AB) OR into A before
    #: their AND: (A OR CONST) AND X AND #imm, and (A OR CONST) AND #imm (NMS
    #: pp. 60-64). It varies between chips and with temperature; $EE is the
    #: value SingleStepTests records. A host modelling a particular console
    #: sets the instance's attributes (docs/undocumented-behavior.md).
    ane_constant = 0xEE
    lxa_constant = 0xEE

    def __init__(self, read_byte: ReadByte, write_byte: WriteByte) -> None:
        super().__init__(read_byte, write_byte)
        self._init_core()
        cls = type(self)
        if "_table" not in cls.__dict__:
            cls._table = build_table(cls)

    def _execute(self) -> int:
        pc = self.pc
        opcode = self._read(pc)
        self.pc = (pc + 1) & 0xFFFF
        handler, mode, cycles = self._table[opcode]
        if mode is None:
            handler(self)
        else:
            handler(self, mode(self))
        extra = self._extra
        if extra:
            self._extra = 0
            return cycles + extra
        return cycles

    def _halted(self) -> int:
        # JAM has stopped the processor: it reads $FFFF every cycle until reset.
        self._read(0xFFFF)
        return 1

    # -- state -----------------------------------------------------------

    def capture_state(self) -> CPUState:
        """Return an immutable snapshot of all CPU-owned state.

        No host reads, no side effects. Memory and devices are the host's and
        are not included (docs/cpu-state.md).
        """
        return CPUState(
            a=self.a,
            x=self.x,
            y=self.y,
            s=self.s,
            pc=self.pc,
            p=self.p,
            **self._poll_fields(),
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
        self._restore_poll(state)
        self._extra = 0


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
