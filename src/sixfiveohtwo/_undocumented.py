"""The 105 opcodes MOS did not document, as the NMOS 6502 executes them.

Every one does something repeatable enough to be tested, and SingleStepTests
records all of them. Names and behaviour are NMS's; the "magic constant" of
ANE and LXA, which varies from chip to chip and with temperature (NMS p. 60),
is fixed at $EE, the value SingleStepTests records. See
docs/undocumented-behavior.md.
"""

from sixfiveohtwo._alu import add, subtract
from sixfiveohtwo._core import NZ, C, D, N, V, Z
from sixfiveohtwo._shifts import _asl, _lsr, _rol, _ror

#: ANE and LXA compute (A OR CONST) AND ...; CONST is chip-dependent (NMS p. 61).
MAGIC = 0xEE

#: What a JAMmed CPU puts on the address bus after its second cycle, as the
#: SingleStepTests corpus (emulator-derived) records it.
JAM_READS = (0xFFFF, 0xFFFE, 0xFFFE, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF)


class UndocumentedMixin:
    """Private implementation of the undocumented NMOS opcodes."""

    # -- a read-modify-write, then an ALU operation with the result ------

    def _op_slo(self, address: int) -> None:
        """SLO -- ASL M, then A OR M -> A (NMS p. 7)."""
        value, p = _asl(self._modify(address, self.read_byte(address)), self.p)
        self.write_byte(address, value)
        a = self.a | value
        self.a = a
        self.p = (p & ~(N | Z)) | NZ[a]

    def _op_rla(self, address: int) -> None:
        """RLA -- ROL M, then A AND M -> A (NMS p. 9)."""
        value, p = _rol(self._modify(address, self.read_byte(address)), self.p)
        self.write_byte(address, value)
        a = self.a & value
        self.a = a
        self.p = (p & ~(N | Z)) | NZ[a]

    def _op_sre(self, address: int) -> None:
        """SRE -- LSR M, then A EOR M -> A (NMS p. 11)."""
        value, p = _lsr(self._modify(address, self.read_byte(address)), self.p)
        self.write_byte(address, value)
        a = self.a ^ value
        self.a = a
        self.p = (p & ~(N | Z)) | NZ[a]

    def _op_rra(self, address: int) -> None:
        """RRA -- ROR M, then A + M + C -> A, decimal mode included (NMS p. 14)."""
        value, p = _ror(self._modify(address, self.read_byte(address)), self.p)
        self.write_byte(address, value)
        self.a, self.p = add(self.a, value, p)

    def _op_dcp(self, address: int) -> None:
        """DCP -- DEC M, then CMP M (NMS p. 22)."""
        value = (self._modify(address, self.read_byte(address)) - 1) & 0xFF
        self.write_byte(address, value)
        self._compare(self.a, value)

    def _op_isc(self, address: int) -> None:
        """ISC -- INC M, then A - M - (1 - C) -> A, decimal mode included (NMS p. 26)."""
        value = (self._modify(address, self.read_byte(address)) + 1) & 0xFF
        self.write_byte(address, value)
        self.a, self.p = subtract(self.a, value, self.p)

    # -- loads and stores of two registers -------------------------------

    def _op_sax(self, address: int) -> None:
        """SAX -- A AND X -> M, no flags (NMS p. 16)."""
        self.write_byte(address, self.a & self.x)

    def _op_lax(self, address: int) -> None:
        """LAX -- M -> A and X (NMS p. 19)."""
        value = self.read_byte(address)
        self.a = value
        self.x = value
        self.p = (self.p & ~(N | Z)) | NZ[value]

    def _op_las(self, address: int) -> None:
        """LAS -- M AND S -> A, X and S (NMS p. 41)."""
        value = self.read_byte(address) & self.s
        self.a = value
        self.x = value
        self.s = value
        self.p = (self.p & ~(N | Z)) | NZ[value]

    # -- immediate combinations ------------------------------------------

    def _op_anc(self, address: int) -> None:
        """ANC -- A AND #imm -> A, then N -> C (NMS p. 28)."""
        a = self.a & self.read_byte(address)
        self.a = a
        self.p = (self.p & ~(N | Z | C)) | NZ[a] | (a >> 7)

    def _op_alr(self, address: int) -> None:
        """ALR -- A AND #imm, then LSR A (NMS p. 30)."""
        self.a, self.p = _lsr(self.a & self.read_byte(address), self.p)

    def _op_arr(self, address: int) -> None:
        """ARR -- A AND #imm, then ROR A, with its own C and V (NMS pp. 32, 78)."""
        value = self.a & self.read_byte(address)
        p = self.p
        result = (value >> 1) | ((p & C) << 7)
        # N and Z from the rotated value; V from bits 6 and 5 of it.
        p = (p & ~(N | V | Z | C)) | NZ[result] | ((result ^ (result << 1)) & V)
        if p & D:
            # Decimal mode: a BCD fix-up of each digit of the rotated value,
            # decided by the digits of the value before rotating (NMS p. 78).
            if (value & 0x0F) >= 0x05:
                result = (result & 0xF0) | ((result + 0x06) & 0x0F)
            if (value & 0xF0) >= 0x50:
                result = (result + 0x60) & 0xFF
                p |= C
        elif result & 0x40:
            p |= C
        self.a = result
        self.p = p

    def _op_sbx(self, address: int) -> None:
        """SBX -- (A AND X) - #imm -> X, C as for CMP, no decimal (NMS p. 35)."""
        difference = (self.a & self.x) - self.read_byte(address)
        x = difference & 0xFF
        self.x = x
        self.p = (self.p & ~(N | Z | C)) | NZ[x] | (C if difference >= 0 else 0)

    def _op_usbc(self, address: int) -> None:
        """USBC -- $EB, the same operation as SBC #imm (NMS p. 40)."""
        self.a, self.p = subtract(self.a, self.read_byte(address), self.p)

    # -- unstable: magic constant (NMS p. 60) ----------------------------

    def _op_ane(self, address: int) -> None:
        """ANE -- (A OR CONST) AND X AND #imm -> A (NMS p. 61)."""
        a = (self.a | MAGIC) & self.x & self.read_byte(address)
        self.a = a
        self.p = (self.p & ~(N | Z)) | NZ[a]

    def _op_lxa(self, address: int) -> None:
        """LXA -- (A OR CONST) AND #imm -> A and X (NMS p. 64)."""
        a = (self.a | MAGIC) & self.read_byte(address)
        self.a = a
        self.x = a
        self.p = (self.p & ~(N | Z)) | NZ[a]

    # -- unstable: address high byte (NMS p. 48) -------------------------

    def _store_and_high(self, address: int, index: int, value: int) -> None:
        # The stored value is ANDed with the base address's high byte plus
        # one; when indexing crossed a page, that same value replaces the
        # high byte of the address written (NMS pp. 48-49).
        base = (address - index) & 0xFFFF
        value &= ((base >> 8) + 1) & 0xFF
        if (address ^ base) & 0xFF00:
            address = (value << 8) | (address & 0xFF)
        self.write_byte(address, value)

    def _op_sha(self, address: int) -> None:
        """SHA -- A AND X AND (H + 1) -> M (NMS p. 50)."""
        self._store_and_high(address, self.y, self.a & self.x)

    def _op_shx(self, address: int) -> None:
        """SHX -- X AND (H + 1) -> M (NMS p. 52)."""
        self._store_and_high(address, self.y, self.x)

    def _op_shy(self, address: int) -> None:
        """SHY -- Y AND (H + 1) -> M (NMS p. 55)."""
        self._store_and_high(address, self.x, self.y)

    def _op_tas(self, address: int) -> None:
        """TAS -- A AND X -> S, then S AND (H + 1) -> M (NMS p. 58)."""
        self.s = self.a & self.x
        self._store_and_high(address, self.y, self.s)

    # -- no effect, and no return ----------------------------------------

    def _op_nop_read(self, address: int) -> None:
        """NOP with an operand -- reads M and discards it (NMS p. 43)."""
        self.read_byte(address)

    def _op_jam(self) -> None:
        """JAM -- the processor stops; only a reset restarts it (NMS p. 47)."""
        self._read_pc()
        for address in JAM_READS:
            self.read_byte(address)
        self.halted = True
