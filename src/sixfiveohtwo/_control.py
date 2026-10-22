"""Branches, jumps, subroutines, the stack, flag instructions, interrupts and reset.

The vectors are PM's (section 9.0, p. 124): NMI at $FFFA, RESET at $FFFC,
IRQ and BRK at $FFFE. Interrupt timing that MOS does not document -- the
one-instruction delay after CLI, SEI and PLP, and an NMI taking over a BRK or
IRQ already under way -- is from the NESdev wiki's "CPU interrupts" page
(documentation tier; it cites the visual6502 transistor-level simulation).
"""

from sixfiveohtwo._core import NMI_LATCH, NO_POLL, STACK, B, C, D, I, N, U, V, Z

VECTOR_NMI = 0xFFFA
VECTOR_RESET = 0xFFFC
VECTOR_IRQ = 0xFFFE  # shared by BRK


class ControlMixin:
    """Private control-flow, stack, flag, interrupt and reset implementation."""

    # -- branches (HM p. A-13; NMS p. 87) ---------------------------------

    def _branch(self, taken: int) -> None:
        # A taken branch spends a cycle reading the next opcode while the
        # offset is added to PCL, and one more reading PCH:new-PCL when that
        # crosses a page (NMS p. 87; HM p. A-13 lists the first read at the
        # target instead: see docs/validation.md, "Divergences").
        #
        # Its interrupt poll is its own (NESdev, "CPU interrupts", "Branch
        # instructions and interrupts"): always at the end of cycle 1, never
        # at the end of cycle 2 of a taken branch, and at the end of cycle 3
        # of one that crosses a page; seen at either point, it is taken. Not
        # taken, cycle 1 is the second-to-last and the usual rule holds.
        early = self._requests  # as they stand at the end of cycle 1
        self._stalled = self._stalled_before = None
        offset = self._fetch()
        if self._stalled is not None:
            # RDY held the operand fetch: requests raised during the stall
            # are polled at its end (note_stall).
            early = self._stalled
            self._stalled = self._stalled_before = None
        if not taken:
            return
        pc = self.pc
        self._read(pc)
        if self._stalled_before is not None:
            # A stall of the next-opcode read: requests raised by the start
            # of its last halted cycle count (perfect6502).
            early |= self._stalled_before
            self._stalled = self._stalled_before = None
        target = (pc + offset - ((offset & 0x80) << 1)) & 0xFFFF
        if (target ^ pc) & 0xFF00:
            self._read((pc & 0xFF00) | (target & 0xFF))
            self._extra = 2
            # The usual poll, at the end of cycle 3, or the early one.
            deferred = self._deferred
            self._deferred = early | (self._requests if deferred is None else deferred)
        else:
            self._extra = 1
            self._deferred = early
        self.pc = target

    def _op_bpl(self) -> None:
        """BPL -- branch if N = 0 (PM p. B-7)."""
        self._branch(not self.p & N)

    def _op_bmi(self) -> None:
        """BMI -- branch if N = 1 (PM p. B-6)."""
        self._branch(self.p & N)

    def _op_bvc(self) -> None:
        """BVC -- branch if V = 0 (PM p. B-8)."""
        self._branch(not self.p & V)

    def _op_bvs(self) -> None:
        """BVS -- branch if V = 1 (PM p. B-9)."""
        self._branch(self.p & V)

    def _op_bcc(self) -> None:
        """BCC -- branch if C = 0 (PM p. B-4)."""
        self._branch(not self.p & C)

    def _op_bcs(self) -> None:
        """BCS -- branch if C = 1 (PM p. B-5)."""
        self._branch(self.p & C)

    def _op_bne(self) -> None:
        """BNE -- branch if Z = 0 (PM p. B-7)."""
        self._branch(not self.p & Z)

    def _op_beq(self) -> None:
        """BEQ -- branch if Z = 1 (PM p. B-5)."""
        self._branch(self.p & Z)

    # -- jumps and subroutines ---------------------------------------------

    def _op_jmp(self) -> None:
        """JMP abs -- (PC + 1) -> PCL, (PC + 2) -> PCH (PM p. B-16)."""
        self.pc = self._fetch_word()

    def _op_jmp_ind(self) -> None:
        """JMP (abs) -- the pointer's high byte never carries into the next page (PM p. B-16)."""
        pointer = self._fetch_word()
        low = self._read(pointer)
        # JMP ($C0FF) reads $C0FF and $C000 (NMS p. 94; HM p. A-12).
        high = self._read((pointer & 0xFF00) | ((pointer + 1) & 0xFF))
        self.pc = (high << 8) | low

    def _op_jsr(self) -> None:
        """JSR -- push PC + 2 - 1, then jump (PM p. B-17)."""
        # Low target byte, a stack read, PCH and PCL pushed, and only then
        # the high target byte, from the operand's own address (HM p. A-10;
        # NMS p. 86). If that address is the stack slot just written, the
        # pushed byte is what arrives.
        low = self._fetch()
        self._read_stack()
        pc = self.pc
        self._push(pc >> 8)
        self._push(pc & 0xFF)
        self.pc = (self._read(pc) << 8) | low

    def _op_rts(self) -> None:
        """RTS -- pull PC, then PC + 1 -> PC (PM p. B-23)."""
        self._read_pc()
        self._read_stack()
        low = self._pull()
        pc = (self._pull() << 8) | low
        self._read(pc)  # the increment's cycle reads the pulled address (HM p. A-12)
        self.pc = (pc + 1) & 0xFFFF

    # -- stack -------------------------------------------------------------

    def _op_pha(self) -> None:
        """PHA -- push A (PM p. B-20)."""
        self._read_pc()
        self._push(self.a)

    def _op_php(self) -> None:
        """PHP -- push P with B and bit 5 set (PM p. B-21; NMS p. 95)."""
        self._read_pc()
        self._push(self.p | B | U)

    def _op_pla(self) -> None:
        """PLA -- pull A (PM p. B-21)."""
        self._read_pc()
        self._read_stack()
        a = self._pull()
        self.a = a
        self.p = (self.p & ~(N | Z)) | (a & N) | (0 if a else Z)

    def _op_plp(self) -> None:
        """PLP -- pull P; B and bit 5 keep their fixed values (PM p. B-22)."""
        self._read_pc()
        self._read_stack()
        # The interrupt poll has already happened, on the old I (NESdev).
        self._polled_i = self.p & I
        self.p = (self._pull() | U) & ~B

    # -- flags -------------------------------------------------------------

    def _op_clc(self) -> None:
        """CLC -- 0 -> C (PM p. B-9)."""
        self._read_pc()
        self.p &= ~C

    def _op_sec(self) -> None:
        """SEC -- 1 -> C (PM p. B-24)."""
        self._read_pc()
        self.p |= C

    def _op_cld(self) -> None:
        """CLD -- 0 -> D (PM p. B-10)."""
        self._read_pc()
        self.p &= ~D

    def _op_sed(self) -> None:
        """SED -- 1 -> D (PM p. B-25)."""
        self._read_pc()
        self.p |= D

    def _op_clv(self) -> None:
        """CLV -- 0 -> V (PM p. B-11)."""
        self._read_pc()
        self.p &= ~V

    def _op_cli(self) -> None:
        """CLI -- 0 -> I, one instruction late for a waiting IRQ (PM p. B-10)."""
        self._read_pc()
        # I changes after this instruction's interrupt poll, so an IRQ
        # already waiting is taken after the next instruction, not this one
        # (NESdev, "Delayed IRQ response after CLI, SEI, and PLP").
        self._polled_i = self.p & I
        self.p &= ~I

    def _op_sei(self) -> None:
        """SEI -- 1 -> I; an IRQ polled before it is still taken (PM p. B-25)."""
        self._read_pc()
        self._polled_i = self.p & I
        self.p |= I

    def _op_nop(self) -> None:
        """NOP -- no operation (PM p. B-19)."""
        self._read_pc()

    # -- software and hardware interrupts ----------------------------------

    def _interrupt(self, vector: int, pushed_p: int) -> None:
        # Shared by BRK, IRQ and NMI after their first two cycles: PCH, PCL
        # and P pushed, I set, then the vector (HM p. A-11; NMS pp. 82-83).
        pc = self.pc
        self._push(pc >> 8)
        self._push(pc & 0xFF)
        if vector != VECTOR_NMI and self._requests & NMI_LATCH:
            # The vector is chosen after cycle 4, the PCL push: an NMI by
            # then takes it over, BRK's or the IRQ's frame with NMI's vector
            # (NESdev, "CPU interrupts", "Interrupt hijacking").
            self._requests &= ~NMI_LATCH
            vector = VECTOR_NMI
        self._push(pushed_p)
        self.p |= I
        low = self._read(vector)
        self.pc = (self._read(vector + 1) << 8) | low
        # The sequence does not poll: the handler's first instruction runs
        # before any other interrupt is taken (NESdev, "CPU interrupts").
        self._deferred = NO_POLL

    def _op_brk(self) -> None:
        """BRK -- push PC + 2 and P with B set, jump through $FFFE (PM p. B-8)."""
        self._fetch()  # the byte after BRK is skipped: the return address is PC + 2
        self._interrupt(VECTOR_IRQ, self.p | B | U)

    def _op_rti(self) -> None:
        """RTI -- pull P, then PC (PM p. B-23)."""
        self._read_pc()
        self._read_stack()
        # Unlike PLP, the restored I decides the very next poll (NESdev).
        self.p = (self._pull() | U) & ~B
        low = self._pull()
        self.pc = (self._pull() << 8) | low

    def _enter_interrupt(self, vector: int) -> int:
        """Take IRQ or NMI at an instruction boundary: seven cycles, B clear."""
        # The opcode at PC is fetched and discarded, then read again: PC is not
        # advanced (NESdev, "CPU interrupts"; NMS p. 83 lists PC + 1 for the
        # second read -- see docs/validation.md, "Divergences").
        self._polled_i = None
        pc = self.pc
        self._read(pc)
        self._read(pc)
        if vector == VECTOR_NMI:
            self._requests &= ~NMI_LATCH
        self._interrupt(vector, (self.p | U) & ~B)
        self._polled = NO_POLL
        self._deferred = None
        return 7

    def _accept_reset(self) -> int:
        """Run the seven-cycle start sequence: I set, PC from $FFFC (PM p. 127)."""
        # PM section 9.2, Example 9.1: two cycles whose address MOS calls
        # "don't care" (read here at PC, as NMS p. 83 and NESdev do), three
        # stack cycles with R/W held at read -- S decrements, nothing is
        # written -- and the vector. Only I and PC change (PM section 9.3).
        self._reset_pending = False
        self.halted = False
        self._polled_i = None
        pc = self.pc
        self._read(pc)
        self._read(pc)
        for _ in range(3):
            self._read(STACK | self.s)
            self.s = (self.s - 1) & 0xFF
        self.p |= I
        low = self._read(VECTOR_RESET)
        self.pc = (self._read(VECTOR_RESET + 1) << 8) | low
        self._polled = NO_POLL  # like an interrupt sequence, reset does not poll
        self._deferred = None
        return 7
