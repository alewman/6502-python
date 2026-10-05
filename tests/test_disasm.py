"""The disassembler: MOS syntax for every mode, NMS names, and lengths the core agrees with.

The decode table is derived from the core's own opcode map, so what is worth
checking is the rendering, and that each opcode's length is the number of
bytes the core actually consumes.
"""

import pytest

from sixfiveohtwo import Instruction, disassemble, disassemble_bytes, disassemble_range
from tests.conftest import Host

LENGTHS = {
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
# Opcodes whose PC after one step is not "the next instruction".
TRANSFERS = {"BRK", "JAM", "JMP", "JSR", "RTS", "RTI"}


@pytest.mark.parametrize(
    ("encoded", "text", "operands", "mode", "target"),
    [
        ((0xEA,), "NOP", (), "implied", None),
        ((0x0A,), "ASL A", ("A",), "accumulator", None),
        ((0xA9, 0x12), "LDA #$12", ("#$12",), "immediate", None),
        ((0xA5, 0x12), "LDA $12", ("$12",), "zero_page", 0x12),
        ((0xB5, 0x12), "LDA $12,X", ("$12", "X"), "zero_page_x", 0x12),
        ((0xB6, 0x12), "LDX $12,Y", ("$12", "Y"), "zero_page_y", 0x12),
        ((0xAD, 0x34, 0x12), "LDA $1234", ("$1234",), "absolute", 0x1234),
        ((0xBD, 0x34, 0x12), "LDA $1234,X", ("$1234", "X"), "absolute_x", 0x1234),
        ((0xB9, 0x34, 0x12), "LDA $1234,Y", ("$1234", "Y"), "absolute_y", 0x1234),
        ((0x6C, 0x34, 0x12), "JMP ($1234)", ("($1234)",), "indirect", 0x1234),
        ((0xA1, 0x12), "LDA ($12,X)", ("($12", "X)"), "indexed_indirect", 0x12),
        ((0xB1, 0x12), "LDA ($12),Y", ("($12)", "Y"), "indirect_indexed", 0x12),
        ((0xD0, 0xFC), "BNE $0FFE", ("$0FFE",), "relative", 0x0FFE),
        ((0x20, 0x00, 0x03), "JSR $0300", ("$0300",), "absolute", 0x0300),
    ],
)
def test_every_mode_renders_in_mos_syntax(
    encoded: tuple[int, ...], text: str, operands: tuple[str, ...], mode: str, target: int | None
) -> None:
    instruction = disassemble_bytes(encoded, 0x1000)
    assert (instruction.text, instruction.operands) == (text, operands)
    assert (instruction.mode, instruction.target, instruction.documented) == (mode, target, True)
    assert instruction.data == bytes(encoded)
    assert instruction.next_address == 0x1000 + len(encoded)


@pytest.mark.parametrize(
    ("opcode", "mnemonic", "mode"),
    [
        (0x02, "JAM", "implied"),
        (0x03, "SLO", "indexed_indirect"),
        (0x27, "RLA", "zero_page"),
        (0x4B, "ALR", "immediate"),
        (0x6B, "ARR", "immediate"),
        (0x0B, "ANC", "immediate"),
        (0x87, "SAX", "zero_page"),
        (0xB7, "LAX", "zero_page_y"),
        (0x8B, "ANE", "immediate"),
        (0xAB, "LXA", "immediate"),
        (0xCB, "SBX", "immediate"),
        (0xC7, "DCP", "zero_page"),
        (0xE7, "ISC", "zero_page"),
        (0x4F, "SRE", "absolute"),
        (0x6F, "RRA", "absolute"),
        (0xEB, "USBC", "immediate"),
        (0x93, "SHA", "indirect_indexed"),
        (0x9C, "SHY", "absolute_x"),
        (0x9E, "SHX", "absolute_y"),
        (0x9B, "TAS", "absolute_y"),
        (0xBB, "LAS", "absolute_y"),
        (0x1A, "NOP", "implied"),
        (0x80, "NOP", "immediate"),
        (0x04, "NOP", "zero_page"),
        (0x14, "NOP", "zero_page_x"),
        (0x0C, "NOP", "absolute"),
        (0x1C, "NOP", "absolute_x"),
    ],
)
def test_undocumented_opcodes_use_no_more_secrets_names(
    opcode: int, mnemonic: str, mode: str
) -> None:
    instruction = disassemble_bytes((opcode, 0x12, 0x34))
    assert (instruction.mnemonic, instruction.mode, instruction.documented) == (
        mnemonic,
        mode,
        False,
    )


def test_undocumented_nop_carries_its_operand() -> None:
    assert disassemble_bytes((0x1C, 0x34, 0x12)).text == "NOP $1234,X"


def test_mos_documents_151_opcodes() -> None:
    documented = [disassemble_bytes((opcode, 0, 0)).documented for opcode in range(256)]
    assert documented.count(True) == 151
    assert disassemble_bytes((0xEA,)).documented and not disassemble_bytes((0xFA,)).documented


@pytest.mark.parametrize("opcode", [0x00, 0x02])
def test_brk_and_jam_decode_as_one_byte(opcode: int) -> None:
    assert disassemble_bytes((opcode,)).size == 1


@pytest.mark.parametrize("opcode", range(256))
def test_length_follows_the_mode_and_matches_what_the_core_consumes(opcode: int) -> None:
    instruction = disassemble_bytes((opcode, 0, 0), 0x0200)
    assert instruction.size == LENGTHS[instruction.mode]
    if instruction.mnemonic in TRANSFERS:
        return
    # Zero operands keep every access in RAM and make a taken branch land on pc+2 too.
    machine = Host((opcode, 0, 0))
    machine.step()
    assert machine.cpu.pc == instruction.next_address


@pytest.mark.parametrize(
    ("address", "encoded", "target"),
    [
        (0xFFFE, (0xF0, 0x7F), 0x007F),  # forward across $FFFF
        (0x0000, (0xD0, 0x80), 0xFF82),  # backward across $0000
        (0x1000, (0x10, 0xFE), 0x1000),  # branch to itself
    ],
)
def test_branch_targets_wrap_in_sixteen_bits(
    address: int, encoded: tuple[int, int], target: int
) -> None:
    instruction = disassemble_bytes(encoded, address)
    assert instruction.target == target
    assert instruction.operands == (f"${target:04X}",)


def test_reader_wraps_past_ffff_without_touching_the_bus_or_cpu() -> None:
    machine = Host(at=0)
    machine.load(0xFFFF, (0x4C,))
    machine.load(0x0000, (0x34, 0x12))
    before = machine.cpu.capture_state()

    instruction = disassemble(machine.peek, 0xFFFF)

    assert (instruction.text, instruction.data) == ("JMP $1234", bytes((0x4C, 0x34, 0x12)))
    assert instruction.next_address == 0x0002
    assert machine.accesses == []
    assert machine.cpu.capture_state() == before


def test_disassemble_range_walks_consecutive_instructions() -> None:
    machine = Host((0xA9, 0x01, 0x8D, 0x00, 0x04, 0xEA))
    listing = disassemble_range(machine.peek, 0x0200, 3)
    assert [(item.address, item.text) for item in listing] == [
        (0x0200, "LDA #$01"),
        (0x0202, "STA $0400"),
        (0x0205, "NOP"),
    ]


def test_bytes_running_past_the_end_raise() -> None:
    with pytest.raises(ValueError, match="runs past"):
        disassemble_bytes((0xAD, 0x34))
    with pytest.raises(ValueError, match="empty"):
        disassemble_bytes(())


@pytest.mark.parametrize("bad_value", [-1, 0x100, True, None])
def test_reader_rejects_non_byte_values(bad_value: object) -> None:
    with pytest.raises(ValueError, match="non-byte"):
        disassemble(lambda _address: bad_value, 0)  # type: ignore[arg-type,return-value]


def test_instruction_values_are_validated() -> None:
    with pytest.raises(ValueError, match="address"):
        disassemble(lambda _address: 0xEA, 0x10000)
    with pytest.raises(ValueError, match="mode"):
        Instruction(0, b"\xea", "NOP", mode="zero-page")
    with pytest.raises(ValueError, match="at least one byte"):
        Instruction(0, b"", "NOP")
