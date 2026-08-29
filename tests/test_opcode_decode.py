import pytest

from sixfiveohtwo import AddressingMode
from sixfiveohtwo.core import (
    OFFICIAL_OPCODES,
    OpcodeDefinition,
    decode_opcode,
)


def test_catalog_is_canonical_and_covers_every_encoding():
    assert set(OFFICIAL_OPCODES) == set(range(0x100))
    assert decode_opcode(0xA9) is OFFICIAL_OPCODES[0xA9]
    assert decode_opcode(0xA9) == OpcodeDefinition(
        0xA9, "LDA", AddressingMode.IMMEDIATE, 2
    )


def test_decode_exposes_instruction_length_and_page_penalty_metadata():
    lda_absolute_x = decode_opcode(0xBD)
    sta_absolute_x = decode_opcode(0x9D)

    assert (lda_absolute_x.operand_bytes, lda_absolute_x.length) == (2, 3)
    assert lda_absolute_x.page_cross_penalty is True
    assert sta_absolute_x.page_cross_penalty is False


@pytest.mark.parametrize("opcode", [0x0B])
def test_decode_accepts_previously_unofficial_opcodes(opcode):
    assert decode_opcode(opcode).opcode == opcode


def test_decode_accepts_every_opcode_byte():
    decoded = [decode_opcode(opcode).opcode for opcode in range(0x100)]
    assert decoded == list(range(0x100))


@pytest.mark.parametrize("opcode", [True, "A9", -1, 0x100])
def test_decode_validates_opcode_byte(opcode):
    with pytest.raises((TypeError, ValueError)):
        decode_opcode(opcode)
