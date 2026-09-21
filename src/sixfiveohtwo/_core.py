"""CPU state, fetch, effective-address and stack helpers.

Every cycle of an NMOS 6502 is one bus access, a read or a write, and this
core makes each of them, dummy reads included, in the order the chip does.
The addressing-mode helpers below are therefore written cycle by cycle.
Sources are cited as in docs/start-here.md: PM is MOS Technology's MCS6500
Microcomputer Family Programming Manual (6500-50A, January 1976), HM its
Hardware Manual (6500-10A, January 1976), whose Appendix A lists the address
and data bus for every cycle, and NMS is groepaz's "No More Secrets: NMOS
6510 Unintended Opcodes" v0.99 (2024-12-24).
"""

from collections.abc import Callable

# Status register bits, P (PM section 3.8, "Flag Summary", p. 30).
N = 0x80  # negative: bit 7 of the result
V = 0x40  # overflow: two's complement overflow
U = 0x20  # unused: no flip-flop; reads as 1 when P is pushed
B = 0x10  # break: no flip-flop; 1 in the byte BRK and PHP push, 0 for IRQ/NMI
D = 0x08  # decimal mode
I = 0x04  # IRQ disable
Z = 0x02  # zero
C = 0x01  # carry

#: N and Z for every 8-bit result, so a handler sets both with one lookup.
NZ = tuple((value & N) | (0 if value else Z) for value in range(256))

STACK = 0x0100  # the stack is page one: S is the low byte (PM section 8.3, p. 112)

ReadByte = Callable[[int], int]
WriteByte = Callable[[int, int], None]


class CoreMixin:
    """Private implementation of CPU state and the helpers every handler uses."""

    def _init_core(self) -> None:
        # A, X, Y and S hold "any random condition" until reset, which sets
        # only I and PC (PM section 9.2, p. 126; section 9.3, p. 127); zero
        # makes hosts and traces reproducible.
        self.a = 0
        self.x = 0
        self.y = 0
        self.s = 0
        self.pc = 0
        # Bit 5 is kept set and bit 4 (B) clear: neither is a flip-flop, and
        # this is the value P reads as everywhere except on the stack.
        self.p = U | I
        # Interrupt inputs (docs/start-here.md, "Reset and interrupts").
        self._reset_pending = False
        self._irq = False
        self._nmi_pending = False
        # CLI, SEI and PLP change I after the chip has polled for interrupts,
        # so the next boundary decides on the old I. None: poll P as it is.
        self._polled_i: int | None = None
        # JAM has stopped the processor; only a reset restarts it.
        self.halted = False
        # Cycles a step adds to its opcode's base count: a page crossed by an
        # indexed read, a branch taken.
        self._extra = 0

    # -- fetch -------------------------------------------------------------

    def _fetch(self) -> int:
        pc = self.pc
        self.pc = (pc + 1) & 0xFFFF
        return self.read_byte(pc)

    def _fetch_word(self) -> int:
        low = self._fetch()  # the 6502 is little-endian: low byte first
        return (self._fetch() << 8) | low

    def _read_pc(self) -> None:
        """The dummy read of every one-byte instruction's second cycle (HM p. A-2)."""
        self.read_byte(self.pc)

    # -- effective addresses, cycle by cycle (HM Appendix A) ---------------
    # Each returns the address the instruction's own read, write or
    # read-modify-write uses, after making the addressing cycles' accesses.
    # Immediate is included: its "address" is the operand's own place in the
    # instruction stream, so every read handler is one line.

    def _ea_imm(self) -> int:
        pc = self.pc
        self.pc = (pc + 1) & 0xFFFF
        return pc

    def _ea_zp(self) -> int:
        return self._fetch()

    def _ea_zpx(self) -> int:
        base = self._fetch()
        self.read_byte(base)  # the unindexed address is read and discarded (HM p. A-4)
        return (base + self.x) & 0xFF  # page zero wraps: never carries to page one

    def _ea_zpy(self) -> int:
        base = self._fetch()
        self.read_byte(base)
        return (base + self.y) & 0xFF

    def _ea_abs(self) -> int:
        return self._fetch_word()

    def _indexed(self, base: int, index: int, write: bool) -> int:
        # The low byte is added first and the address bus shows base-page:low
        # for one cycle; a read ends there unless a page was crossed, which
        # costs a cycle while the carry reaches the high byte (HM p. A-4).
        # Writes and read-modify-writes always spend that cycle (HM pp. A-6, A-9).
        address = (base + index) & 0xFFFF
        if write or (address ^ base) & 0xFF00:
            self.read_byte((base & 0xFF00) | (address & 0xFF))
            if not write:
                self._extra = 1
        return address

    def _ea_abx(self) -> int:
        return self._indexed(self._fetch_word(), self.x, False)

    def _ea_aby(self) -> int:
        return self._indexed(self._fetch_word(), self.y, False)

    def _ea_abx_w(self) -> int:
        return self._indexed(self._fetch_word(), self.x, True)

    def _ea_aby_w(self) -> int:
        return self._indexed(self._fetch_word(), self.y, True)

    def _ea_izx(self) -> int:
        # (zp,X): the pointer lives in page zero at zp+X, both bytes wrapping
        # within page zero (HM p. A-3).
        base = self._fetch()
        self.read_byte(base)
        pointer = (base + self.x) & 0xFF
        low = self.read_byte(pointer)
        return (self.read_byte((pointer + 1) & 0xFF) << 8) | low

    def _izy_base(self) -> int:
        pointer = self._fetch()
        low = self.read_byte(pointer)
        return (self.read_byte((pointer + 1) & 0xFF) << 8) | low

    def _ea_izy(self) -> int:
        return self._indexed(self._izy_base(), self.y, False)  # (zp),Y: HM p. A-5

    def _ea_izy_w(self) -> int:
        return self._indexed(self._izy_base(), self.y, True)

    # -- stack (S points at the next free byte: PM section 8.3, p. 112) ----

    def _push(self, value: int) -> None:
        s = self.s
        self.write_byte(STACK | s, value)
        self.s = (s - 1) & 0xFF

    def _pull(self) -> int:
        s = (self.s + 1) & 0xFF
        self.s = s
        return self.read_byte(STACK | s)

    def _read_stack(self) -> None:
        """The dummy read of the stack before a pull, or during JSR (HM p. A-10)."""
        self.read_byte(STACK | self.s)
