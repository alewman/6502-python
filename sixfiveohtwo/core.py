"""Embeddable, machine-neutral NMOS 6502 core shell."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from .cpu import CPUState, pack_status_byte, unpack_status_byte
from .interrupts import InterruptBoundary, InterruptLines
from .memory import MemoryBus


def _require_cycles(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("cycles must be an integer")
    if value < 0:
        raise ValueError("cycles must not be negative")
    return value


def _normalize_byte_address(address: int) -> int:
    """Wrap an address to the 8-bit address range."""
    if isinstance(address, bool) or not isinstance(address, int):
        raise TypeError("address must be an integer")
    return address & 0xFF


def _normalize_word_address(address: int) -> int:
    """Wrap an address to the 16-bit address range."""
    if isinstance(address, bool) or not isinstance(address, int):
        raise TypeError("address must be an integer")
    return address & 0xFFFF


def _decode_relative_offset(value: int) -> int:
    """Decode an unsigned instruction byte as a signed 8-bit offset."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("relative offset must be an integer byte")
    if not 0x00 <= value <= 0xFF:
        raise ValueError("relative offset must fit in 8 bits")
    return value - 0x100 if value & 0x80 else value


def _adc_result(
    accumulator: int, operand: int, carry: bool, decimal: bool
) -> tuple[int, bool, bool, bool, bool]:
    """Return ADC result and flags, retaining NMOS binary intermediate flags."""
    binary_sum = accumulator + operand + int(carry)
    binary_result = binary_sum & 0xFF
    zero = binary_result == 0
    if decimal:
        low_sum = (accumulator & 0x0F) + (operand & 0x0F) + int(carry)
        if low_sum >= 0x0A:
            low_sum = ((low_sum + 0x06) & 0x0F) + 0x10
        high_sum = (accumulator & 0xF0) + (operand & 0xF0) + low_sum
        # N and V reflect the low-nibble-corrected intermediate, before the final
        # high-byte +0x60 correction -- a documented NMOS decimal-mode quirk.
        intermediate_result = high_sum & 0xFF
        negative = bool(intermediate_result & 0x80)
        overflow = bool(
            ~(accumulator ^ operand) & (accumulator ^ intermediate_result) & 0x80
        )
        if high_sum >= 0xA0:
            high_sum += 0x60
        result = high_sum & 0xFF
        carry_out = high_sum >= 0x100
    else:
        result = binary_result
        carry_out = binary_sum > 0xFF
        negative = bool(binary_result & 0x80)
        overflow = bool(~(accumulator ^ operand) & (accumulator ^ binary_result) & 0x80)
    return (result, carry_out, negative, overflow, zero)


def _sbc_result(
    accumulator: int, operand: int, carry: bool, decimal: bool
) -> tuple[int, bool, bool, bool, bool]:
    """Return SBC result and flags, retaining NMOS binary intermediate flags."""
    borrow = int(not carry)
    binary_difference = accumulator - operand - borrow
    binary_result = binary_difference & 0xFF
    overflow = bool((accumulator ^ binary_result) & (accumulator ^ operand) & 0x80)
    if decimal:
        low_difference = (accumulator & 0x0F) - (operand & 0x0F) - borrow
        high_difference = (accumulator >> 4) - (operand >> 4)
        if low_difference < 0:
            low_difference -= 6
        if low_difference < 0:
            high_difference -= 1
        if high_difference < 0:
            high_difference -= 6
        result = ((high_difference << 4) | (low_difference & 0x0F)) & 0xFF
        carry_out = high_difference >= 0
    else:
        result = binary_result
        carry_out = binary_difference >= 0
    return (
        result,
        carry_out,
        bool(binary_result & 0x80),
        overflow,
        binary_result == 0,
    )


class AddressingMode(StrEnum):
    """Addressing forms resolved by the instruction dispatcher."""

    ACCUMULATOR = "accumulator"
    IMPLIED = "implied"
    IMMEDIATE = "immediate"
    ZERO_PAGE = "zero_page"
    ZERO_PAGE_X = "zero_page_x"
    ZERO_PAGE_Y = "zero_page_y"
    ABSOLUTE = "absolute"
    ABSOLUTE_X = "absolute_x"
    ABSOLUTE_Y = "absolute_y"
    INDIRECT = "indirect"
    RELATIVE = "relative"
    INDEXED_INDIRECT = "indexed_indirect"
    INDIRECT_INDEXED = "indirect_indexed"


class UnsupportedOpcodeError(ValueError):
    """Raised when an opcode is not part of the documented NMOS 6502 set."""


@dataclass(frozen=True)
class OpcodeDefinition:
    """Canonical routing and timing metadata for an official opcode."""

    opcode: int
    mnemonic: str
    addressing_mode: AddressingMode
    cycles: int
    page_cross_penalty: bool = False

    @property
    def operand_bytes(self) -> int:
        """Number of bytes after the opcode in this instruction."""
        return {
            AddressingMode.ACCUMULATOR: 0,
            AddressingMode.IMPLIED: 0,
            AddressingMode.RELATIVE: 1,
            AddressingMode.IMMEDIATE: 1,
            AddressingMode.ZERO_PAGE: 1,
            AddressingMode.ZERO_PAGE_X: 1,
            AddressingMode.ZERO_PAGE_Y: 1,
            AddressingMode.INDEXED_INDIRECT: 1,
            AddressingMode.INDIRECT_INDEXED: 1,
            AddressingMode.ABSOLUTE: 2,
            AddressingMode.ABSOLUTE_X: 2,
            AddressingMode.ABSOLUTE_Y: 2,
            AddressingMode.INDIRECT: 2,
        }[self.addressing_mode]

    @property
    def length(self) -> int:
        """Total encoded instruction length, including its opcode byte."""
        return 1 + self.operand_bytes


# The catalog contains canonical routing and timing metadata for official opcodes.
_OPCODE_ROWS = (
    (
        "69 65 75 6D 7D 79 61 71",
        "ADC",
        "IMMEDIATE ZERO_PAGE ZERO_PAGE_X ABSOLUTE ABSOLUTE_X ABSOLUTE_Y "
        "INDEXED_INDIRECT INDIRECT_INDEXED",
        "2 3 4 4 4 4 6 5",
    ),
    (
        "29 25 35 2D 3D 39 21 31",
        "AND",
        "IMMEDIATE ZERO_PAGE ZERO_PAGE_X ABSOLUTE ABSOLUTE_X ABSOLUTE_Y "
        "INDEXED_INDIRECT INDIRECT_INDEXED",
        "2 3 4 4 4 4 6 5",
    ),
    (
        "0A 06 16 0E 1E",
        "ASL",
        "ACCUMULATOR ZERO_PAGE ZERO_PAGE_X ABSOLUTE ABSOLUTE_X",
        "2 5 6 6 7",
    ),
    ("00", "BRK", "IMPLIED", "7"),
    ("90", "BCC", "RELATIVE", "2"),
    ("B0", "BCS", "RELATIVE", "2"),
    ("F0", "BEQ", "RELATIVE", "2"),
    ("30", "BMI", "RELATIVE", "2"),
    ("D0", "BNE", "RELATIVE", "2"),
    ("10", "BPL", "RELATIVE", "2"),
    ("50", "BVC", "RELATIVE", "2"),
    ("70", "BVS", "RELATIVE", "2"),
    ("24 2C", "BIT", "ZERO_PAGE ABSOLUTE", "3 4"),
    ("18", "CLC", "IMPLIED", "2"),
    ("D8", "CLD", "IMPLIED", "2"),
    ("58", "CLI", "IMPLIED", "2"),
    ("B8", "CLV", "IMPLIED", "2"),
    ("38", "SEC", "IMPLIED", "2"),
    ("F8", "SED", "IMPLIED", "2"),
    ("78", "SEI", "IMPLIED", "2"),
    (
        "C9 C5 D5 CD DD D9 C1 D1",
        "CMP",
        "IMMEDIATE ZERO_PAGE ZERO_PAGE_X ABSOLUTE ABSOLUTE_X ABSOLUTE_Y "
        "INDEXED_INDIRECT INDIRECT_INDEXED",
        "2 3 4 4 4 4 6 5",
    ),
    ("E0 E4 EC", "CPX", "IMMEDIATE ZERO_PAGE ABSOLUTE", "2 3 4"),
    ("C0 C4 CC", "CPY", "IMMEDIATE ZERO_PAGE ABSOLUTE", "2 3 4"),
    ("C6 D6 CE DE", "DEC", "ZERO_PAGE ZERO_PAGE_X ABSOLUTE ABSOLUTE_X", "5 6 6 7"),
    ("CA", "DEX", "IMPLIED", "2"),
    ("88", "DEY", "IMPLIED", "2"),
    (
        "49 45 55 4D 5D 59 41 51",
        "EOR",
        "IMMEDIATE ZERO_PAGE ZERO_PAGE_X ABSOLUTE ABSOLUTE_X ABSOLUTE_Y "
        "INDEXED_INDIRECT INDIRECT_INDEXED",
        "2 3 4 4 4 4 6 5",
    ),
    ("E6 F6 EE FE", "INC", "ZERO_PAGE ZERO_PAGE_X ABSOLUTE ABSOLUTE_X", "5 6 6 7"),
    ("E8", "INX", "IMPLIED", "2"),
    ("C8", "INY", "IMPLIED", "2"),
    ("4C 6C", "JMP", "ABSOLUTE INDIRECT", "3 5"),
    ("20", "JSR", "ABSOLUTE", "6"),
    (
        "A9 A5 B5 AD BD B9 A1 B1",
        "LDA",
        "IMMEDIATE ZERO_PAGE ZERO_PAGE_X ABSOLUTE ABSOLUTE_X ABSOLUTE_Y "
        "INDEXED_INDIRECT INDIRECT_INDEXED",
        "2 3 4 4 4 4 6 5",
    ),
    (
        "A2 A6 B6 AE BE",
        "LDX",
        "IMMEDIATE ZERO_PAGE ZERO_PAGE_Y ABSOLUTE ABSOLUTE_Y",
        "2 3 4 4 4",
    ),
    (
        "A0 A4 B4 AC BC",
        "LDY",
        "IMMEDIATE ZERO_PAGE ZERO_PAGE_X ABSOLUTE ABSOLUTE_X",
        "2 3 4 4 4",
    ),
    (
        "4A 46 56 4E 5E",
        "LSR",
        "ACCUMULATOR ZERO_PAGE ZERO_PAGE_X ABSOLUTE ABSOLUTE_X",
        "2 5 6 6 7",
    ),
    ("EA", "NOP", "IMPLIED", "2"),
    (
        "09 05 15 0D 1D 19 01 11",
        "ORA",
        "IMMEDIATE ZERO_PAGE ZERO_PAGE_X ABSOLUTE ABSOLUTE_X ABSOLUTE_Y "
        "INDEXED_INDIRECT INDIRECT_INDEXED",
        "2 3 4 4 4 4 6 5",
    ),
    ("48", "PHA", "IMPLIED", "3"),
    ("08", "PHP", "IMPLIED", "3"),
    ("68", "PLA", "IMPLIED", "4"),
    ("28", "PLP", "IMPLIED", "4"),
    (
        "2A 26 36 2E 3E",
        "ROL",
        "ACCUMULATOR ZERO_PAGE ZERO_PAGE_X ABSOLUTE ABSOLUTE_X",
        "2 5 6 6 7",
    ),
    (
        "6A 66 76 6E 7E",
        "ROR",
        "ACCUMULATOR ZERO_PAGE ZERO_PAGE_X ABSOLUTE ABSOLUTE_X",
        "2 5 6 6 7",
    ),
    ("40", "RTI", "IMPLIED", "6"),
    ("60", "RTS", "IMPLIED", "6"),
    (
        "E9 E5 F5 ED FD F9 E1 F1",
        "SBC",
        "IMMEDIATE ZERO_PAGE ZERO_PAGE_X ABSOLUTE ABSOLUTE_X ABSOLUTE_Y "
        "INDEXED_INDIRECT INDIRECT_INDEXED",
        "2 3 4 4 4 4 6 5",
    ),
    (
        "85 95 8D 9D 99 81 91",
        "STA",
        "ZERO_PAGE ZERO_PAGE_X ABSOLUTE ABSOLUTE_X ABSOLUTE_Y "
        "INDEXED_INDIRECT INDIRECT_INDEXED",
        "3 4 4 5 5 6 6",
    ),
    ("86 96 8E", "STX", "ZERO_PAGE ZERO_PAGE_Y ABSOLUTE", "3 4 4"),
    ("84 94 8C", "STY", "ZERO_PAGE ZERO_PAGE_X ABSOLUTE", "3 4 4"),
    ("AA", "TAX", "IMPLIED", "2"),
    ("A8", "TAY", "IMPLIED", "2"),
    ("BA", "TSX", "IMPLIED", "2"),
    ("8A", "TXA", "IMPLIED", "2"),
    ("9A", "TXS", "IMPLIED", "2"),
    ("98", "TYA", "IMPLIED", "2"),
)


def _build_opcode_catalog() -> Mapping[int, OpcodeDefinition]:
    catalog: dict[int, OpcodeDefinition] = {}
    page_penalty_mnemonics = {
        "ADC",
        "AND",
        "CMP",
        "EOR",
        "LDA",
        "LDX",
        "LDY",
        "ORA",
        "SBC",
    }
    page_penalty_modes = {
        AddressingMode.ABSOLUTE_X,
        AddressingMode.ABSOLUTE_Y,
        AddressingMode.INDIRECT_INDEXED,
    }
    for opcodes, mnemonic, modes, cycles in _OPCODE_ROWS:
        for opcode, mode, cycle in zip(
            (int(value, 16) for value in opcodes.split()),
            (AddressingMode[value] for value in modes.split()),
            (int(value) for value in cycles.split()),
            strict=True,
        ):
            catalog[opcode] = OpcodeDefinition(
                opcode,
                mnemonic,
                mode,
                cycle,
                mnemonic in page_penalty_mnemonics and mode in page_penalty_modes,
            )
    return MappingProxyType(catalog)


OFFICIAL_OPCODES = _build_opcode_catalog()


def decode_opcode(opcode: int) -> OpcodeDefinition:
    """Decode one byte into canonical official-opcode metadata."""
    if isinstance(opcode, bool) or not isinstance(opcode, int):
        raise TypeError("opcode must be an integer byte")
    if not 0x00 <= opcode <= 0xFF:
        raise ValueError("opcode must fit in 8 bits")
    try:
        return OFFICIAL_OPCODES[opcode]
    except KeyError as exc:
        raise UnsupportedOpcodeError(
            f"unsupported or unofficial opcode: 0x{opcode:02X}"
        ) from exc


@dataclass(frozen=True)
class AddressingResult:
    """The operand information needed by an opcode handler."""

    mode: AddressingMode
    effective_address: int | None
    operand: int | None
    page_crossed: bool = False
    sequential_pc: int | None = None

    @property
    def address(self) -> int | None:
        """Alias for the resolved effective address."""
        return self.effective_address

    @property
    def value(self) -> int | None:
        """Alias for the resolved operand value."""
        return self.operand


@dataclass(frozen=True)
class InstructionContext:
    """Dispatch input prepared at one instruction boundary."""

    state: CPUState
    boundary: InterruptBoundary
    opcode_address: int
    opcode: int

    @property
    def pc(self) -> int:
        """The address from which the opcode was fetched."""
        return self.opcode_address


@dataclass(frozen=True)
class InstructionStep:
    """The boundary context and cycles accounted for by a single step."""

    context: InstructionContext
    cycles: int
    total_cycles: int
    vector: int | None = None
    accepted_events: tuple[str, ...] = ()

    @property
    def opcode(self) -> int:
        return self.context.opcode

    @property
    def boundary(self) -> InterruptBoundary:
        return self.context.boundary

    @property
    def definition(self) -> OpcodeDefinition:
        """The official routing metadata selected for this step."""
        return CPU.dispatch_opcode(self.opcode)


@dataclass(frozen=True)
class ResetStep:
    """The result of accepting RESET at an instruction boundary."""

    boundary: InterruptBoundary
    vector: int
    cycles: int
    total_cycles: int
    accepted_events: tuple[str, ...] = ("RESET",)

    @property
    def reset(self) -> bool:
        """Whether this lifecycle result represents RESET acceptance."""
        return self.boundary.reset


@dataclass(frozen=True)
class InterruptStep:
    """The result of accepting a hardware IRQ or NMI at a boundary."""

    boundary: InterruptBoundary
    vector: int
    cycles: int
    total_cycles: int
    accepted_events: tuple[str, ...] = ()

    @property
    def irq(self) -> bool:
        """Whether this result accepted the maskable IRQ line."""
        return isinstance(self, IRQStep)

    @property
    def nmi(self) -> bool:
        """Whether this result accepted NMI."""
        return isinstance(self, NMIStep)


class IRQStep(InterruptStep):
    """The result of accepting a maskable IRQ."""


class NMIStep(InterruptStep):
    """The result of accepting a non-maskable interrupt."""


# Accept the conventional mixed-case spelling as well as the all-caps acronym.
NmiStep = NMIStep


class CPU:
    """Own CPU state while delegating memory and input lines to the host.

    :meth:`step` accepts boundary interrupts before preparing a dispatch context
    and rejects non-official opcodes. Hosts retain ownership of memory maps and
    devices.
    """

    __slots__ = ("_memory", "_state", "_lines")

    def __init__(
        self,
        memory: MemoryBus,
        *,
        lines: InterruptLines | None = None,
        state: CPUState | None = None,
    ) -> None:
        if not isinstance(memory, MemoryBus):
            raise TypeError("memory must implement MemoryBus")
        if lines is not None and not isinstance(lines, InterruptLines):
            raise TypeError("lines must be InterruptLines")
        if state is not None and not isinstance(state, CPUState):
            raise TypeError("state must be CPUState")
        self._memory = memory
        self._lines = lines if lines is not None else InterruptLines()
        self._state = state if state is not None else CPUState()

    @property
    def memory(self) -> MemoryBus:
        """The host-provided memory implementation."""
        return self._memory

    @property
    def state(self) -> CPUState:
        """The mutable register state owned by this core."""
        return self._state

    @property
    def lines(self) -> InterruptLines:
        """The host-driven RESET, IRQ, and NMI inputs."""
        return self._lines

    @property
    def reset(self) -> bool:
        """Whether RESET is currently asserted."""
        return self._lines.reset

    @property
    def irq(self) -> bool:
        """Whether IRQ is currently asserted."""
        return self._lines.irq

    @property
    def nmi(self) -> bool:
        """Whether NMI is currently high."""
        return self._lines.nmi

    @property
    def nmi_pending(self) -> bool:
        """Whether a latched NMI edge awaits boundary sampling."""
        return self._lines.nmi_pending

    def set_reset(self, asserted: bool) -> None:
        """Drive the RESET line without performing reset sequencing."""
        self._lines.set_reset(asserted)

    def set_irq(self, asserted: bool) -> None:
        """Drive the IRQ line."""
        self._lines.set_irq(asserted)

    def set_nmi(self, high: bool) -> None:
        """Drive the NMI line, latching a rising edge."""
        self._lines.set_nmi(high)

    def signal_nmi(self) -> None:
        """Latch one NMI signal without requiring a persistent line level."""
        self._lines.signal_nmi()

    def pending_interrupt_boundary(self) -> InterruptBoundary:
        """Inspect current input state without consuming a pending NMI."""
        return self._lines.pending_interrupt_boundary()

    def sample_instruction_boundary(self) -> InterruptBoundary:
        """Sample and consume input state at an instruction boundary."""
        return self._lines.sample_instruction_boundary()

    def record_cycles(self, cycles: int) -> int:
        """Record cycles consumed by dispatched execution and return the total."""
        cycles = _require_cycles(cycles)
        self._state.cycles += cycles
        return self._state.cycles

    @staticmethod
    def _validate_fetched_byte(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("memory read must return an integer byte")
        if not 0x00 <= value <= 0xFF:
            raise ValueError("memory read must return a byte")
        return value

    def _fetch_byte(self) -> int:
        """Read one instruction byte and advance the PC with 16-bit wrapping."""
        address = _normalize_word_address(self._state.pc.value)
        value = self._validate_fetched_byte(self._memory.read_byte(address))
        self._state.pc.value = _normalize_word_address(address + 1)
        return value

    def _fetch_word(self) -> int:
        """Read a little-endian word from the instruction stream."""
        low = self._fetch_byte()
        high = self._fetch_byte()
        return low | (high << 8)

    @staticmethod
    def _validate_stack_byte(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("stack value must be an integer byte")
        if not 0x00 <= value <= 0xFF:
            raise ValueError("stack value must fit in 8 bits")
        return value

    def _stack_address(self) -> int:
        """Return the current stack slot in the fixed 6502 stack page."""
        return 0x0100 | self._state.sp.value

    def _push_byte(self, value: int) -> None:
        """Push one byte and decrement S with 8-bit wrapping."""
        value = self._validate_stack_byte(value)
        self._memory.write_byte(self._stack_address(), value)
        self._state.sp.value = (self._state.sp.value - 1) & 0xFF

    def _pop_byte(self) -> int:
        """Increment S with 8-bit wrapping and pop one byte."""
        self._state.sp.value = (self._state.sp.value + 1) & 0xFF
        return self._validate_fetched_byte(
            self._memory.read_byte(self._stack_address())
        )

    def _push_word(self, value: int) -> None:
        """Push a word high byte first, as used by 6502 interrupts and JSR."""
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("stack word must be an integer")
        if not 0x0000 <= value <= 0xFFFF:
            raise ValueError("stack word must fit in 16 bits")
        self._push_byte(value >> 8)
        self._push_byte(value & 0xFF)

    def _pop_word(self) -> int:
        """Pop a word low byte first, reversing the 6502 stack order."""
        low = self._pop_byte()
        high = self._pop_byte()
        return low | (high << 8)

    @staticmethod
    def _coerce_addressing_mode(mode: AddressingMode | str) -> AddressingMode:
        if isinstance(mode, AddressingMode):
            return mode
        if isinstance(mode, str):
            normalized = mode.strip().lower().replace("-", "_").replace(",", "_")
            try:
                return AddressingMode(normalized)
            except ValueError:
                try:
                    return AddressingMode[normalized.upper()]
                except KeyError:
                    pass
        raise ValueError(f"unsupported addressing mode: {mode!r}")

    def _read_operand(self, address: int) -> int:
        address = _normalize_word_address(address)
        return self._validate_fetched_byte(self._memory.read_byte(address))

    def _read_pointer(self, pointer: int, *, zero_page: bool = False) -> int:
        """Read a little-endian pointer with NMOS wraparound behavior."""
        if zero_page:
            pointer = _normalize_byte_address(pointer)
            high_address = _normalize_byte_address(pointer + 1)
        else:
            pointer = _normalize_word_address(pointer)
            high_address = (pointer & 0xFF00) | ((pointer + 1) & 0x00FF)
        low = self._read_operand(pointer)
        high = self._read_operand(high_address)
        return low | (high << 8)

    def resolve_relative_address(self) -> AddressingResult:
        """Resolve a relative branch operand from the instruction stream.

        The operand is returned as a signed offset. The sequential PC is retained
        separately because branch timing compares it with the taken target.
        """
        offset = _decode_relative_offset(self._fetch_byte())
        sequential_pc = _normalize_word_address(self._state.pc.value)
        target = _normalize_word_address(sequential_pc + offset)
        page_crossed = (sequential_pc & 0xFF00) != (target & 0xFF00)
        return AddressingResult(
            AddressingMode.RELATIVE,
            target,
            offset,
            page_crossed,
            sequential_pc,
        )

    def resolve_addressing(
        self, mode: AddressingMode | str, *, read_operand: bool = True
    ) -> AddressingResult:
        """Fetch and resolve one supported instruction addressing form.

        Memory forms read their operand unless ``read_operand`` is false, which
        lets write instructions resolve an address without reading its target.
        Indexed absolute and indirect-indexed forms report page crossing based
        on the unindexed and indexed 16-bit addresses.
        """
        if not isinstance(read_operand, bool):
            raise TypeError("read_operand must be a boolean")
        mode = self._coerce_addressing_mode(mode)

        def operand_at(address: int) -> int | None:
            return self._read_operand(address) if read_operand else None

        if mode is AddressingMode.ACCUMULATOR:
            return AddressingResult(mode, None, self._state.a.value)
        if mode is AddressingMode.IMPLIED:
            return AddressingResult(mode, None, None)
        if mode is AddressingMode.IMMEDIATE:
            return AddressingResult(mode, None, self._fetch_byte())
        if mode is AddressingMode.RELATIVE:
            return self.resolve_relative_address()

        if mode is AddressingMode.ZERO_PAGE:
            address = self._fetch_byte()
            return AddressingResult(mode, address, operand_at(address))

        if mode in (AddressingMode.ZERO_PAGE_X, AddressingMode.ZERO_PAGE_Y):
            index = (
                self._state.x.value
                if mode is AddressingMode.ZERO_PAGE_X
                else self._state.y.value
            )
            base = self._fetch_byte()
            address = _normalize_byte_address(base + index)
            return AddressingResult(mode, address, operand_at(address))

        if mode is AddressingMode.INDIRECT:
            pointer = self._fetch_word()
            address = self._read_pointer(pointer)
            return AddressingResult(mode, address, operand_at(address))

        if mode is AddressingMode.INDEXED_INDIRECT:
            pointer = _normalize_byte_address(self._fetch_byte() + self._state.x.value)
            address = self._read_pointer(pointer, zero_page=True)
            return AddressingResult(mode, address, operand_at(address))

        if mode is AddressingMode.INDIRECT_INDEXED:
            pointer = self._fetch_byte()
            base = self._read_pointer(pointer, zero_page=True)
            address = _normalize_word_address(base + self._state.y.value)
            page_crossed = (base & 0xFF00) != (address & 0xFF00)
            return AddressingResult(mode, address, operand_at(address), page_crossed)

        if mode not in (
            AddressingMode.ABSOLUTE,
            AddressingMode.ABSOLUTE_X,
            AddressingMode.ABSOLUTE_Y,
        ):
            raise ValueError(f"unsupported addressing mode: {mode!r}")

        base = self._fetch_word()
        if mode is AddressingMode.ABSOLUTE:
            address = base
            page_crossed = False
        elif mode is AddressingMode.ABSOLUTE_X:
            address = _normalize_word_address(base + self._state.x.value)
            page_crossed = (base & 0xFF00) != (address & 0xFF00)
        else:
            address = _normalize_word_address(base + self._state.y.value)
            page_crossed = (base & 0xFF00) != (address & 0xFF00)
        return AddressingResult(mode, address, operand_at(address), page_crossed)

    @staticmethod
    def dispatch_opcode(opcode: int) -> OpcodeDefinition:
        """Return canonical official routing metadata for one opcode byte."""
        return decode_opcode(opcode)

    def _accept_reset(self, boundary: InterruptBoundary) -> ResetStep:
        """Load the reset vector and apply RESET's persistent flag effect."""
        low = self._read_operand(0xFFFC)
        high = self._read_operand(0xFFFD)
        vector = low | (high << 8)
        self._state.pc.value = vector
        self._state.status.interrupt_disable = True
        total_cycles = self.record_cycles(7)
        return ResetStep(
            boundary=boundary,
            vector=vector,
            cycles=7,
            total_cycles=total_cycles,
        )

    def _push_status(self, *, break_flag: bool) -> None:
        self._push_byte(pack_status_byte(self._state.status, break_flag=break_flag))

    def _pop_status(self) -> None:
        self._state.status = unpack_status_byte(self._pop_byte())

    def _read_vector(self, address: int) -> int:
        low = self._read_operand(address)
        high = self._read_operand(address + 1)
        return low | (high << 8)

    def _accept_interrupt(
        self, boundary: InterruptBoundary, *, nmi: bool
    ) -> InterruptStep:
        """Perform the common seven-cycle IRQ/NMI stack and vector sequence."""
        vector_address = 0xFFFA if nmi else 0xFFFE
        result_type = NMIStep if nmi else IRQStep

        self._push_word(self._state.pc.value)
        self._push_status(break_flag=False)
        self._state.status.interrupt_disable = True
        vector = self._read_vector(vector_address)
        self._state.pc.value = vector
        total_cycles = self.record_cycles(7)
        return result_type(
            boundary=boundary,
            vector=vector,
            cycles=7,
            total_cycles=total_cycles,
            accepted_events=("NMI",) if nmi else ("IRQ",),
        )

    def _update_nz(self, value: int) -> None:
        self._state.status.zero = value == 0
        self._state.status.negative = bool(value & 0x80)

    def _execute_instruction(self, definition: OpcodeDefinition) -> int | None:
        """Execute implemented register, transfer, and logical families."""
        mnemonic = definition.mnemonic
        page_crossed = False
        if mnemonic in {"CLC", "CLD", "CLI", "CLV", "SEC", "SED", "SEI"}:
            flag = {
                "CLC": "carry",
                "CLD": "decimal",
                "CLI": "interrupt_disable",
                "CLV": "overflow",
                "SEC": "carry",
                "SED": "decimal",
                "SEI": "interrupt_disable",
            }[mnemonic]
            setattr(self._state.status, flag, mnemonic in {"SEC", "SED", "SEI"})
            return definition.cycles
        if mnemonic == "NOP":
            return definition.cycles
        if mnemonic == "JMP":
            result = self.resolve_addressing(definition.addressing_mode)
            if result.address is None:
                raise ValueError("JMP requires a target address")
            self._state.pc.value = result.address
            return definition.cycles
        if mnemonic == "JSR":
            low = self._fetch_byte()
            # Real NMOS hardware pushes the return address, then fetches the
            # target's high byte LAST -- if that byte's address aliases the
            # stack slot just written (rare but real), the CPU reads back its
            # own pushed byte instead of the original operand.
            return_address = self._state.pc.value
            self._push_word(return_address)
            high = self._read_operand(return_address)
            self._state.pc.value = low | (high << 8)
            return definition.cycles
        if mnemonic in {"BCC", "BCS", "BEQ", "BMI", "BNE", "BPL", "BVC", "BVS"}:
            result = self.resolve_relative_address()
            conditions = {
                "BCC": not self._state.status.carry,
                "BCS": self._state.status.carry,
                "BEQ": self._state.status.zero,
                "BMI": self._state.status.negative,
                "BNE": not self._state.status.zero,
                "BPL": not self._state.status.negative,
                "BVC": not self._state.status.overflow,
                "BVS": self._state.status.overflow,
            }
            if conditions[mnemonic]:
                if result.address is None:
                    raise ValueError(f"{mnemonic} requires a relative target")
                self._state.pc.value = result.address
                return definition.cycles + 1 + int(result.page_crossed)
            return definition.cycles
        if mnemonic in {"ADC", "SBC"}:
            result = self.resolve_addressing(definition.addressing_mode)
            page_crossed = result.page_crossed
            if result.operand is None:
                raise ValueError(f"{mnemonic} requires an operand")
            arithmetic = _adc_result if mnemonic == "ADC" else _sbc_result
            value, carry, negative, overflow, zero = arithmetic(
                self._state.a.value,
                result.operand,
                self._state.status.carry,
                self._state.status.decimal,
            )
            self._state.a.value = value
            self._state.status.carry = carry
            self._state.status.negative = negative
            self._state.status.overflow = overflow
            self._state.status.zero = zero
        elif mnemonic in {"ORA", "AND", "EOR", "BIT"}:
            result = self.resolve_addressing(definition.addressing_mode)
            page_crossed = result.page_crossed
            if result.operand is None:
                raise ValueError(f"{mnemonic} requires an operand")
            operand = result.operand
            if mnemonic == "BIT":
                self._state.status.zero = (self._state.a.value & operand) == 0
                self._state.status.negative = bool(operand & 0x80)
                self._state.status.overflow = bool(operand & 0x40)
            else:
                value = {
                    "ORA": self._state.a.value | operand,
                    "AND": self._state.a.value & operand,
                    "EOR": self._state.a.value ^ operand,
                }[mnemonic]
                self._state.a.value = value
                self._update_nz(value)
        elif mnemonic in {"CMP", "CPX", "CPY"}:
            result = self.resolve_addressing(definition.addressing_mode)
            page_crossed = result.page_crossed
            if result.operand is None:
                raise ValueError(f"{mnemonic} requires an operand")
            register = {
                "CMP": self._state.a,
                "CPX": self._state.x,
                "CPY": self._state.y,
            }[mnemonic]
            difference = (register.value - result.operand) & 0xFF
            self._state.status.carry = register.value >= result.operand
            self._update_nz(difference)
        elif mnemonic in {"ASL", "LSR", "ROL", "ROR"}:
            result = self.resolve_addressing(definition.addressing_mode)
            if result.operand is None:
                raise ValueError(f"{mnemonic} requires an operand")
            value = result.operand
            carry_in = int(self._state.status.carry)
            if mnemonic == "ASL":
                self._state.status.carry = bool(value & 0x80)
                shifted = value << 1
            elif mnemonic == "LSR":
                self._state.status.carry = bool(value & 0x01)
                shifted = value >> 1
            elif mnemonic == "ROL":
                self._state.status.carry = bool(value & 0x80)
                shifted = (value << 1) | carry_in
            else:
                self._state.status.carry = bool(value & 0x01)
                shifted = (value >> 1) | (carry_in << 7)
            value = shifted & 0xFF
            if result.address is None:
                self._state.a.value = value
            else:
                self._memory.write_byte(result.address, result.operand)
                self._memory.write_byte(result.address, value)
            self._update_nz(value)
        elif mnemonic in {"INC", "DEC"}:
            result = self.resolve_addressing(definition.addressing_mode)
            if result.address is None or result.operand is None:
                raise ValueError(f"{mnemonic} requires a memory operand")
            value = (result.operand + (1 if mnemonic == "INC" else -1)) & 0xFF
            self._memory.write_byte(result.address, result.operand)
            self._memory.write_byte(result.address, value)
            self._update_nz(value)
        elif mnemonic in {"INX", "INY", "DEX", "DEY"}:
            register = {
                "INX": self._state.x,
                "INY": self._state.y,
                "DEX": self._state.x,
                "DEY": self._state.y,
            }[mnemonic]
            delta = 1 if mnemonic in {"INX", "INY"} else -1
            register.value = (register.value + delta) & 0xFF
            self._update_nz(register.value)
        elif mnemonic in {"LDA", "LDX", "LDY"}:
            result = self.resolve_addressing(definition.addressing_mode)
            page_crossed = result.page_crossed
            if result.operand is None:
                raise ValueError(f"{mnemonic} requires an operand")
            register = {
                "LDA": self._state.a,
                "LDX": self._state.x,
                "LDY": self._state.y,
            }[mnemonic]
            register.value = result.operand
            self._update_nz(register.value)
        elif mnemonic in {"STA", "STX", "STY"}:
            result = self.resolve_addressing(
                definition.addressing_mode, read_operand=False
            )
            if result.address is None:
                raise ValueError(f"{mnemonic} requires a memory address")
            value = {
                "STA": self._state.a,
                "STX": self._state.x,
                "STY": self._state.y,
            }[mnemonic].value
            self._memory.write_byte(result.address, value)
        elif mnemonic in {"TAX", "TAY", "TSX", "TXA", "TXS", "TYA"}:
            sources = {
                "TAX": (self._state.a, self._state.x, True),
                "TAY": (self._state.a, self._state.y, True),
                "TSX": (self._state.sp, self._state.x, True),
                "TXA": (self._state.x, self._state.a, True),
                "TXS": (self._state.x, self._state.sp, False),
                "TYA": (self._state.y, self._state.a, True),
            }
            source, target, updates_flags = sources[mnemonic]
            target.value = source.value
            if updates_flags:
                self._update_nz(target.value)
        else:
            raise RuntimeError(
                f"official opcode has no implementation: 0x{definition.opcode:02X}"
            )

        return definition.cycles + int(definition.page_cross_penalty and page_crossed)

    def _execute_lifecycle(
        self, mnemonic: str
    ) -> tuple[int, int | None, tuple[str, ...]] | None:
        if mnemonic == "BRK":
            self._fetch_byte()
            self._push_word(self._state.pc.value)
            self._push_status(break_flag=True)
            self._state.status.interrupt_disable = True
            sequence_boundary = self.sample_instruction_boundary()
            vector_address = 0xFFFA if sequence_boundary.nmi else 0xFFFE
            self._state.pc.value = self._read_vector(vector_address)
            accepted_events = ("BRK", "NMI") if sequence_boundary.nmi else ("BRK",)
            return 7, self._state.pc.value, accepted_events
        if mnemonic == "RTI":
            self._pop_status()
            self._state.pc.value = self._pop_word()
            return 6, None, ()
        if mnemonic == "PHP":
            self._push_status(break_flag=True)
            return 3, None, ()
        if mnemonic == "PLP":
            self._pop_status()
            return 4, None, ()
        if mnemonic == "PHA":
            self._push_byte(self._state.a.value)
            return 3, None, ()
        if mnemonic == "PLA":
            self._state.a.value = self._pop_byte()
            self._update_nz(self._state.a.value)
            return 4, None, ()
        if mnemonic == "RTS":
            self._state.pc.value = (self._pop_word() + 1) & 0xFFFF
            return 6, None, ()
        return None

    def step(self, *, cycles: int = 0) -> InstructionStep | ResetStep | InterruptStep:
        """Accept RESET, IRQ, or NMI before routing an opcode at a boundary.

        RESET has priority, followed by NMI and then an unmasked IRQ. Hardware
        interrupt vector lifecycles consume seven cycles; otherwise ``cycles``
        records the cycles supplied by the eventual instruction handler.
        """
        cycles = _require_cycles(cycles)
        boundary = self.sample_instruction_boundary()
        if boundary.reset:
            return self._accept_reset(boundary)
        if boundary.nmi:
            return self._accept_interrupt(boundary, nmi=True)
        if boundary.irq and not self._state.status.interrupt_disable:
            return self._accept_interrupt(boundary, nmi=False)
        opcode_address = _normalize_word_address(self._state.pc.value)
        opcode = self._fetch_byte()
        definition = self.dispatch_opcode(opcode)
        lifecycle = self._execute_lifecycle(definition.mnemonic)
        if lifecycle is None:
            executed_cycles = self._execute_instruction(definition)
            if executed_cycles is None:
                executed_cycles = cycles
            vector = None
            accepted_events = ()
        else:
            executed_cycles, vector, accepted_events = lifecycle
        total_cycles = self.record_cycles(executed_cycles)
        return InstructionStep(
            context=InstructionContext(
                state=self._state,
                boundary=boundary,
                opcode_address=opcode_address,
                opcode=opcode,
            ),
            cycles=executed_cycles,
            total_cycles=total_cycles,
            vector=vector,
            accepted_events=accepted_events,
        )


__all__ = (
    "AddressingMode",
    "AddressingResult",
    "CPU",
    "InstructionContext",
    "InstructionStep",
    "InterruptStep",
    "IRQStep",
    "NMIStep",
    "NmiStep",
    "OFFICIAL_OPCODES",
    "decode_opcode",
    "ResetStep",
    "OpcodeDefinition",
    "UnsupportedOpcodeError",
)
