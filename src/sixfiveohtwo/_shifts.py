"""Shifts, rotates, and memory increment and decrement: the read-modify-writes.

A read-modify-write reads its operand, writes it back unchanged while the ALU
works, then writes the result: two writes to the same address. MOS lists the
extra cycle with the operand's address on the bus (HM section A.4, pp. A-7 to
A-9, cycle T3 of each table); NMS documents that it is a write of the
unmodified byte ("Dummy writes", p. 88). Hardware that counts writes or
triggers on them sees both, so the core makes both.
"""

from sixfiveohtwo._core import NZ, C, N, Z


def _asl(value: int, p: int) -> tuple[int, int]:
    result = (value << 1) & 0xFF
    return result, (p & ~(N | Z | C)) | NZ[result] | (value >> 7)


def _lsr(value: int, p: int) -> tuple[int, int]:
    result = value >> 1
    return result, (p & ~(N | Z | C)) | NZ[result] | (value & C)


def _rol(value: int, p: int) -> tuple[int, int]:
    result = ((value << 1) | (p & C)) & 0xFF
    return result, (p & ~(N | Z | C)) | NZ[result] | (value >> 7)


def _ror(value: int, p: int) -> tuple[int, int]:
    result = (value >> 1) | ((p & C) << 7)
    return result, (p & ~(N | Z | C)) | NZ[result] | (value & C)


class ShiftMixin:
    """Private shift, rotate and memory increment/decrement implementation."""

    def _modify(self, address: int, value: int) -> int:
        # The first write is the unmodified byte (NMS p. 88; HM p. A-8, cycle T3).
        self.write_byte(address, value)
        return value

    def _op_asl(self, address: int) -> None:
        """ASL -- C <- M7..M0 <- 0 (PM p. B-4)."""
        value, self.p = _asl(self._modify(address, self.read_byte(address)), self.p)
        self.write_byte(address, value)

    def _op_lsr(self, address: int) -> None:
        """LSR -- 0 -> M7..M0 -> C (PM p. B-19)."""
        value, self.p = _lsr(self._modify(address, self.read_byte(address)), self.p)
        self.write_byte(address, value)

    def _op_rol(self, address: int) -> None:
        """ROL -- C <- M7..M0 <- C (PM p. B-22)."""
        value, self.p = _rol(self._modify(address, self.read_byte(address)), self.p)
        self.write_byte(address, value)

    def _op_ror(self, address: int) -> None:
        """ROR -- C -> M7..M0 -> C (PM p. B-23)."""
        value, self.p = _ror(self._modify(address, self.read_byte(address)), self.p)
        self.write_byte(address, value)

    def _op_inc(self, address: int) -> None:
        """INC -- M + 1 -> M (PM p. B-15)."""
        value = (self._modify(address, self.read_byte(address)) + 1) & 0xFF
        self.p = (self.p & ~(N | Z)) | NZ[value]
        self.write_byte(address, value)

    def _op_dec(self, address: int) -> None:
        """DEC -- M - 1 -> M (PM p. B-13)."""
        value = (self._modify(address, self.read_byte(address)) - 1) & 0xFF
        self.p = (self.p & ~(N | Z)) | NZ[value]
        self.write_byte(address, value)

    def _op_asl_a(self) -> None:
        """ASL A -- C <- A7..A0 <- 0 (PM p. B-4)."""
        self._read_pc()
        self.a, self.p = _asl(self.a, self.p)

    def _op_lsr_a(self) -> None:
        """LSR A -- 0 -> A7..A0 -> C (PM p. B-19)."""
        self._read_pc()
        self.a, self.p = _lsr(self.a, self.p)

    def _op_rol_a(self) -> None:
        """ROL A -- C <- A7..A0 <- C (PM p. B-22)."""
        self._read_pc()
        self.a, self.p = _rol(self.a, self.p)

    def _op_ror_a(self) -> None:
        """ROR A -- C -> A7..A0 -> C (PM p. B-23)."""
        self._read_pc()
        self.a, self.p = _ror(self.a, self.p)
