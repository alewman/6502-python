"""Side-effect-free structured disassembly for the NMOS 6502.

The decode table is built from the opcode map the core executes
(``_dispatch.OPCODES``), so the disassembler cannot disagree with the core
about which opcode is which instruction, how long it is, or how it addresses
memory. Syntax is MOS's (PM Appendix B): ``LDA #$12``, ``LDA $12``,
``LDA $12,X``, ``LDA $1234,Y``, ``LDA ($12,X)``, ``LDA ($12),Y``,
``JMP ($1234)``, ``ASL A``, and branches with their target resolved to an
absolute address. Undocumented opcodes use NMS's names. See
docs/disassembly.md.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sixfiveohtwo._dispatch import DOCUMENTED, OPCODES

ByteReader = Callable[[int], int]

#: Addressing modes, as ``Instruction.mode`` reports them.
MODES = (
    "implied",
    "accumulator",
    "immediate",
    "zero_page",
    "zero_page_x",
    "zero_page_y",
    "absolute",
    "absolute_x",
    "absolute_y",
    "indirect",
    "indexed_indirect",
    "indirect_indexed",
    "relative",
)

_MODE_NAMES = {
    "imm": "immediate",
    "zp": "zero_page",
    "zpx": "zero_page_x",
    "zpy": "zero_page_y",
    "abs": "absolute",
    "abx": "absolute_x",
    "abx_w": "absolute_x",
    "aby": "absolute_y",
    "aby_w": "absolute_y",
    "izx": "indexed_indirect",
    "izy": "indirect_indexed",
    "izy_w": "indirect_indexed",
}
_LENGTHS = {
    "implied": 1,
    "accumulator": 1,
    "immediate": 2,
    "zero_page": 2,
    "zero_page_x": 2,
    "zero_page_y": 2,
    "indexed_indirect": 2,
    "indirect_indexed": 2,
    "relative": 2,
    "absolute": 3,
    "absolute_x": 3,
    "absolute_y": 3,
    "indirect": 3,
}
_BRANCHES = frozenset(("bpl", "bmi", "bvc", "bvs", "bcc", "bcs", "bne", "beq"))


@dataclass(frozen=True, slots=True)
class Instruction:
    """One decoded instruction and the exact bytes it occupies."""

    address: int
    data: bytes
    mnemonic: str
    operands: tuple[str, ...] = ()
    mode: str = "implied"
    #: The address the operand names -- a zero-page, absolute, indirect
    #: pointer or branch target -- before any indexing; None otherwise.
    target: int | None = None
    #: False for the 105 opcodes MOS does not document.
    documented: bool = True

    def __post_init__(self) -> None:
        if type(self.address) is not int or not 0 <= self.address <= 0xFFFF:
            raise ValueError("address must be an integer in range 0x0000..0xFFFF")
        if type(self.data) is not bytes or not self.data:
            raise ValueError("data must contain at least one byte")
        if type(self.mnemonic) is not str or not self.mnemonic:
            raise ValueError("mnemonic must not be empty")
        if type(self.operands) is not tuple or not all(type(o) is str for o in self.operands):
            raise ValueError("operands must be a tuple of strings")
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")

    @property
    def size(self) -> int:
        """Number of encoded bytes."""
        return len(self.data)

    @property
    def next_address(self) -> int:
        """16-bit address immediately following the encoded instruction."""
        return (self.address + self.size) & 0xFFFF

    @property
    def text(self) -> str:
        """Canonical human-readable assembly text."""
        return self.mnemonic if not self.operands else f"{self.mnemonic} {','.join(self.operands)}"


def _form(opcode: int) -> tuple[str, str]:
    handler, mode, _cycles = OPCODES[opcode]
    if handler in _BRANCHES:
        return handler.upper(), "relative"
    if handler.endswith("_a"):
        return handler[:-2].upper(), "accumulator"
    if handler == "jmp_ind":
        return "JMP", "indirect"
    if handler in ("jmp", "jsr"):
        return handler.upper(), "absolute"
    if handler == "nop_read":
        return "NOP", _MODE_NAMES[mode]
    return handler.upper(), "implied" if mode is None else _MODE_NAMES[mode]


#: (mnemonic, mode) for each of the 256 opcodes, as the core executes them.
DECODE_TABLE: tuple[tuple[str, str], ...] = tuple(_form(opcode) for opcode in range(256))


def disassemble(reader: ByteReader, address: int) -> Instruction:
    """Decode the instruction at ``address`` using only ``reader``.

    ``reader`` must be side-effect-free (a peek, not the host's bus read); it
    is called with 16-bit addresses and must return byte values.
    """
    if type(address) is not int or not 0 <= address <= 0xFFFF:
        raise ValueError("address must be an integer in range 0x0000..0xFFFF")
    opcode = _byte(reader, address)
    mnemonic, mode = DECODE_TABLE[opcode]
    data = bytes(_byte(reader, (address + n) & 0xFFFF) for n in range(_LENGTHS[mode]))
    operands: tuple[str, ...] = ()
    target = None
    if mode == "accumulator":
        operands = ("A",)
    elif mode == "immediate":
        operands = (f"#${data[1]:02X}",)
    elif mode == "relative":
        offset = data[1] - 0x100 if data[1] & 0x80 else data[1]
        target = (address + 2 + offset) & 0xFFFF
        operands = (f"${target:04X}",)
    elif len(data) == 2:
        target = data[1]
        operands = {
            "zero_page": (f"${target:02X}",),
            "zero_page_x": (f"${target:02X}", "X"),
            "zero_page_y": (f"${target:02X}", "Y"),
            "indexed_indirect": (f"(${target:02X}", "X)"),
            "indirect_indexed": (f"(${target:02X})", "Y"),
        }[mode]
    elif len(data) == 3:
        target = data[1] | (data[2] << 8)
        operands = {
            "absolute": (f"${target:04X}",),
            "absolute_x": (f"${target:04X}", "X"),
            "absolute_y": (f"${target:04X}", "Y"),
            "indirect": (f"(${target:04X})",),
        }[mode]
    return Instruction(address, data, mnemonic, operands, mode, target, opcode in DOCUMENTED)


def disassemble_bytes(data: Sequence[int] | bytes, address: int = 0) -> Instruction:
    """Decode one instruction from ``data``, whose first byte sits at ``address``."""
    copy = bytes(data)
    if not copy:
        raise ValueError("data must not be empty")

    def reader(where: int) -> int:
        offset = (where - address) & 0xFFFF
        if offset >= len(copy):
            raise ValueError(f"instruction at 0x{address:04X} runs past the supplied bytes")
        return copy[offset]

    return disassemble(reader, address)


def disassemble_range(reader: ByteReader, address: int, count: int) -> list[Instruction]:
    """Decode ``count`` consecutive instructions starting at ``address``."""
    listing = []
    for _ in range(count):
        instruction = disassemble(reader, address)
        listing.append(instruction)
        address = instruction.next_address
    return listing


def _byte(reader: ByteReader, address: int) -> int:
    value = reader(address)
    if type(value) is not int or not 0 <= value <= 0xFF:
        raise ValueError(f"byte reader returned a non-byte value at 0x{address:04X}")
    return value


__all__ = [
    "DECODE_TABLE",
    "MODES",
    "ByteReader",
    "Instruction",
    "disassemble",
    "disassemble_bytes",
    "disassemble_range",
]
