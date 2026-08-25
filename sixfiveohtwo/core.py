"""Embeddable, machine-neutral NMOS 6502 core shell."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from .cpu import CPUState
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
    """Metadata used to route an official opcode to its future handler."""

    opcode: int
    mnemonic: str
    addressing_mode: AddressingMode
    cycles: int


# The catalog deliberately contains metadata only. Instruction semantics are added
# by later phases without changing boundary fetch or addressing dispatch.
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
    for opcodes, mnemonic, modes, cycles in _OPCODE_ROWS:
        for opcode, mode, cycle in zip(
            (int(value, 16) for value in opcodes.split()),
            (AddressingMode[value] for value in modes.split()),
            (int(value) for value in cycles.split()),
            strict=True,
        ):
            catalog[opcode] = OpcodeDefinition(opcode, mnemonic, mode, cycle)
    return MappingProxyType(catalog)


OFFICIAL_OPCODES = _build_opcode_catalog()


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


class CPU:
    """Own CPU state while delegating memory and input lines to the host.

    :meth:`step` prepares a dispatch context and rejects non-official opcodes;
    instruction semantics and interrupt sequencing are added in later phases.
    Hosts retain ownership of memory maps and devices.
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

    def resolve_addressing(self, mode: AddressingMode | str) -> AddressingResult:
        """Fetch and resolve one supported instruction addressing form.

        Memory forms read their operand, while accumulator and implied forms do
        not access the bus. Indexed absolute and indirect-indexed forms report
        page crossing based on the unindexed and indexed 16-bit addresses.
        """
        mode = self._coerce_addressing_mode(mode)

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
            return AddressingResult(mode, address, self._read_operand(address))

        if mode in (AddressingMode.ZERO_PAGE_X, AddressingMode.ZERO_PAGE_Y):
            index = (
                self._state.x.value
                if mode is AddressingMode.ZERO_PAGE_X
                else self._state.y.value
            )
            base = self._fetch_byte()
            address = _normalize_byte_address(base + index)
            return AddressingResult(mode, address, self._read_operand(address))

        if mode is AddressingMode.INDIRECT:
            pointer = self._fetch_word()
            address = self._read_pointer(pointer)
            return AddressingResult(mode, address, self._read_operand(address))

        if mode is AddressingMode.INDEXED_INDIRECT:
            pointer = _normalize_byte_address(self._fetch_byte() + self._state.x.value)
            address = self._read_pointer(pointer, zero_page=True)
            return AddressingResult(mode, address, self._read_operand(address))

        if mode is AddressingMode.INDIRECT_INDEXED:
            pointer = self._fetch_byte()
            base = self._read_pointer(pointer, zero_page=True)
            address = _normalize_word_address(base + self._state.y.value)
            page_crossed = (base & 0xFF00) != (address & 0xFF00)
            return AddressingResult(
                mode, address, self._read_operand(address), page_crossed
            )

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
        return AddressingResult(
            mode, address, self._read_operand(address), page_crossed
        )

    @staticmethod
    def dispatch_opcode(opcode: int) -> OpcodeDefinition:
        """Return the official routing metadata for one opcode byte.

        This is intentionally a metadata-only dispatch point. A later phase can
        attach instruction handlers while retaining this explicit illegal-opcode
        boundary.
        """
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

    def step(self, *, cycles: int = 0) -> InstructionStep:
        """Sample inputs, fetch, and route one official opcode.

        Operand bytes are left for the future instruction handler; this boundary
        step therefore performs no instruction semantics or operand fetches.
        """
        cycles = _require_cycles(cycles)
        boundary = self.sample_instruction_boundary()
        opcode_address = _normalize_word_address(self._state.pc.value)
        opcode = self._fetch_byte()
        self.dispatch_opcode(opcode)
        total_cycles = self.record_cycles(cycles)
        return InstructionStep(
            context=InstructionContext(
                state=self._state,
                boundary=boundary,
                opcode_address=opcode_address,
                opcode=opcode,
            ),
            cycles=cycles,
            total_cycles=total_cycles,
        )


__all__ = (
    "AddressingMode",
    "AddressingResult",
    "CPU",
    "InstructionContext",
    "InstructionStep",
    "OFFICIAL_OPCODES",
    "OpcodeDefinition",
    "UnsupportedOpcodeError",
)
