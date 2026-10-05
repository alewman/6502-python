"""Loads, stores, register transfers and register increments.

A store writes the register to the effective address and reads nothing
there; a one-byte instruction spends its second cycle reading the byte after
its opcode and discarding it (HM p. A-2).
"""

from sixfiveohtwo._core import NZ, N, Z


class LoadMixin:
    """Private load, store, transfer and register-arithmetic implementation."""

    def _op_lda(self, address: int) -> None:
        """LDA -- M -> A (PM p. B-17)."""
        a = self.read_byte(address)
        self.a = a
        self.p = (self.p & ~(N | Z)) | NZ[a]

    def _op_ldx(self, address: int) -> None:
        """LDX -- M -> X (PM p. B-18)."""
        x = self.read_byte(address)
        self.x = x
        self.p = (self.p & ~(N | Z)) | NZ[x]

    def _op_ldy(self, address: int) -> None:
        """LDY -- M -> Y (PM p. B-18)."""
        y = self.read_byte(address)
        self.y = y
        self.p = (self.p & ~(N | Z)) | NZ[y]

    def _op_sta(self, address: int) -> None:
        """STA -- A -> M (PM p. B-26)."""
        self.write_byte(address, self.a)

    def _op_stx(self, address: int) -> None:
        """STX -- X -> M (PM p. B-26)."""
        self.write_byte(address, self.x)

    def _op_sty(self, address: int) -> None:
        """STY -- Y -> M (PM p. B-27)."""
        self.write_byte(address, self.y)

    def _op_tax(self) -> None:
        """TAX -- A -> X (PM p. B-27)."""
        self._read_pc()
        self.x = self.a
        self.p = (self.p & ~(N | Z)) | NZ[self.a]

    def _op_tay(self) -> None:
        """TAY -- A -> Y (PM p. B-28)."""
        self._read_pc()
        self.y = self.a
        self.p = (self.p & ~(N | Z)) | NZ[self.a]

    def _op_txa(self) -> None:
        """TXA -- X -> A (PM p. B-29)."""
        self._read_pc()
        self.a = self.x
        self.p = (self.p & ~(N | Z)) | NZ[self.x]

    def _op_tya(self) -> None:
        """TYA -- Y -> A (PM p. B-28)."""
        self._read_pc()
        self.a = self.y
        self.p = (self.p & ~(N | Z)) | NZ[self.y]

    def _op_tsx(self) -> None:
        """TSX -- S -> X (PM p. B-29)."""
        self._read_pc()
        self.x = self.s
        self.p = (self.p & ~(N | Z)) | NZ[self.s]

    def _op_txs(self) -> None:
        """TXS -- X -> S, no flags (PM p. B-29)."""
        self._read_pc()
        self.s = self.x

    def _op_inx(self) -> None:
        """INX -- X + 1 -> X (PM p. B-15)."""
        self._read_pc()
        x = (self.x + 1) & 0xFF
        self.x = x
        self.p = (self.p & ~(N | Z)) | NZ[x]

    def _op_iny(self) -> None:
        """INY -- Y + 1 -> Y (PM p. B-16)."""
        self._read_pc()
        y = (self.y + 1) & 0xFF
        self.y = y
        self.p = (self.p & ~(N | Z)) | NZ[y]

    def _op_dex(self) -> None:
        """DEX -- X - 1 -> X (PM p. B-13)."""
        self._read_pc()
        x = (self.x - 1) & 0xFF
        self.x = x
        self.p = (self.p & ~(N | Z)) | NZ[x]

    def _op_dey(self) -> None:
        """DEY -- Y - 1 -> Y (PM p. B-14)."""
        self._read_pc()
        y = (self.y - 1) & 0xFF
        self.y = y
        self.p = (self.p & ~(N | Z)) | NZ[y]
