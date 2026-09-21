"""Arithmetic, logic, compare and bit-test instructions.

Every handler here reads one operand from the effective address its
addressing mode computed, so each is the same shape: read, compute, set flags.
Binary ADC and SBC are PM's; the NMOS decimal-mode results, including the
flags the chip leaves after a BCD operation, are NMS's "Unintended decimal
mode" chapter (pp. 70-80), which the SingleStepTests corpus and Klaus
Dormann's decimal exerciser both check.
"""

from sixfiveohtwo._core import NZ, C, D, N, V, Z


def add(a: int, value: int, p: int) -> tuple[int, int]:
    """A + M + C, binary or NMOS decimal; return (A, P).

    In decimal mode the NMOS 6502 sets Z from the binary sum and N and V from
    the sum after the low digit is adjusted and before the high digit is
    (NMS pp. 73-75), so only C is a decimal flag.
    """
    carry = p & C
    total = a + value + carry
    p &= ~(N | V | Z | C)
    if not total & 0xFF:
        p |= Z
    if p & D:
        low = (a & 0x0F) + (value & 0x0F) + carry
        if low >= 0x0A:
            low = ((low + 0x06) & 0x0F) + 0x10
        total = (a & 0xF0) + (value & 0xF0) + low
        p |= total & N
        if ~(a ^ value) & (a ^ total) & 0x80:
            p |= V
        if total >= 0xA0:
            total += 0x60
        if total >= 0x100:
            p |= C
        return total & 0xFF, p
    result = total & 0xFF
    p |= result & N
    if ~(a ^ value) & (a ^ result) & 0x80:
        p |= V
    if total > 0xFF:
        p |= C
    return result, p


def subtract(a: int, value: int, p: int) -> tuple[int, int]:
    """A - M - (1 - C), binary or NMOS decimal; return (A, P).

    Every flag comes from the binary difference, in decimal mode too; only A
    is adjusted (NMS pp. 76-77).
    """
    borrow = 1 - (p & C)
    difference = a - value - borrow
    binary = difference & 0xFF
    p = (p & ~(N | V | Z | C)) | NZ[binary]
    if (a ^ binary) & (a ^ value) & 0x80:
        p |= V
    if difference >= 0:
        p |= C
    if not p & D:
        return binary, p
    low = (a & 0x0F) - (value & 0x0F) - borrow
    high = (a >> 4) - (value >> 4)
    if low < 0:
        low -= 6
        high -= 1
    if high < 0:
        high -= 6
    return ((high << 4) | (low & 0x0F)) & 0xFF, p


class ALUMixin:
    """Private arithmetic, logic and compare implementation."""

    def _op_adc(self, address: int) -> None:
        """ADC -- A + M + C -> A, C (PM p. B-3)."""
        self.a, self.p = add(self.a, self.read_byte(address), self.p)

    def _op_sbc(self, address: int) -> None:
        """SBC -- A - M - (1 - C) -> A (PM p. B-24)."""
        self.a, self.p = subtract(self.a, self.read_byte(address), self.p)

    def _op_and(self, address: int) -> None:
        """AND -- A AND M -> A (PM p. B-3)."""
        a = self.a & self.read_byte(address)
        self.a = a
        self.p = (self.p & ~(N | Z)) | NZ[a]

    def _op_ora(self, address: int) -> None:
        """ORA -- A OR M -> A (PM p. B-20)."""
        a = self.a | self.read_byte(address)
        self.a = a
        self.p = (self.p & ~(N | Z)) | NZ[a]

    def _op_eor(self, address: int) -> None:
        """EOR -- A EOR M -> A (PM p. B-14)."""
        a = self.a ^ self.read_byte(address)
        self.a = a
        self.p = (self.p & ~(N | Z)) | NZ[a]

    def _compare(self, register: int, value: int) -> None:
        # C is "no borrow": register >= M, unsigned; N and Z from the
        # difference, which is not kept.
        p = (self.p & ~(N | Z | C)) | NZ[(register - value) & 0xFF]
        if register >= value:
            p |= C
        self.p = p

    def _op_cmp(self, address: int) -> None:
        """CMP -- A - M, flags only (PM p. B-11)."""
        self._compare(self.a, self.read_byte(address))

    def _op_cpx(self, address: int) -> None:
        """CPX -- X - M, flags only (PM p. B-12)."""
        self._compare(self.x, self.read_byte(address))

    def _op_cpy(self, address: int) -> None:
        """CPY -- Y - M, flags only (PM p. B-12)."""
        self._compare(self.y, self.read_byte(address))

    def _op_bit(self, address: int) -> None:
        """BIT -- A AND M sets Z; M7 -> N, M6 -> V (PM p. B-6)."""
        value = self.read_byte(address)
        p = (self.p & ~(N | V | Z)) | (value & (N | V))
        if not self.a & value:
            p |= Z
        self.p = p
