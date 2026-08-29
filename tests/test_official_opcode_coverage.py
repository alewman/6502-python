import pytest

from sixfiveohtwo import CPU, CPUState, IndexRegisters, StatusFlags
from sixfiveohtwo.core import OFFICIAL_OPCODES, UnsupportedOpcodeError


class Bus:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def read_byte(self, address):
        return self.values.get(address, 0)

    def write_byte(self, address, value):
        self.values[address] = value


OFFICIAL_OPCODE_BYTES = {
    int(value, 16)
    for value in """
    00 01 02 03 04 05 06 07 08 09 0A 0C 0D 0E 0F 10 11 12 13 14 15 16
    17 18 19 1A 1B 1C 1D 1E 1F 20 21 22 23 24 25 26 27 28 29 2A 2C 2D
    2E 2F 30 31 32 33 34 35 36 37 38 39 3A 3B 3C 3D 3E 3F 40 41 42 43
    44 45 46 47 48 49 4A 4C 4D 4E 4F 50 51 52 53 54 55 56 57 58 59 5A
    5B 5C 5D 5E 5F 60 61 62 63 64 65 66 67 68 69 6A 6C 6D 6E 6F 70 71
    72 73 74 75 76 77 78 79 7A 7B 7C 7D 7E 7F 80 81 82 84 85 86 88 89
    8A 8C 8D 8E 90 91 92 94 95 96 98 99 9A 9D A0 A1 A2 A4 A5 A6 A8 A9
    AA AC AD AE B0 B1 B2 B4 B5 B6 B8 B9 BA BC BD BE C0 C1 C2 C4 C5 C6
    C8 C9 CA CC CD CE D0 D1 D2 D4 D5 D6 D8 D9 DA DC DD DE E0 E1 E2 E4
    E5 E6 E8 E9 EA EC ED EE F0 F1 F2 F4 F5 F6 F8 F9 FA FC FD FE
    """.split()
}


def test_official_opcode_set_is_complete_and_dispatches_to_implemented_semantics():
    assert set(OFFICIAL_OPCODES) == OFFICIAL_OPCODE_BYTES
    assert len(OFFICIAL_OPCODE_BYTES) == 218

    for opcode in sorted(OFFICIAL_OPCODE_BYTES):
        cpu = CPU(Bus({0: opcode, 0xFFFE: 0, 0xFFFF: 0}))
        result = cpu.step()
        assert result.opcode == opcode
        definition = OFFICIAL_OPCODES[opcode]
        branch_taken = definition.mnemonic in {"BCC", "BNE", "BPL", "BVC"}
        expected_cycles = (
            11
            if definition.mnemonic == "JAM"
            else definition.cycles
            + int(definition.mnemonic.startswith("B") and branch_taken)
        )
        assert result.cycles == expected_cycles


@pytest.mark.parametrize("opcode", [0x0B, 0x4B, 0x6B, 0x8B, 0xAB, 0xCB, 0xFF])
def test_unofficial_opcodes_are_rejected_after_fetch_without_state_mutation(opcode):
    state = CPUState(
        accumulator=0x12,
        index=IndexRegisters(x=0x34, y=0x56),
        program_counter=0x1234,
        stack_pointer=0x78,
        status=StatusFlags(
            negative=True,
            overflow=True,
            decimal=True,
            interrupt_disable=True,
            zero=True,
            carry=True,
        ),
        cycles=11,
    )
    cpu = CPU(Bus({0x1234: opcode}), state=state)
    before = (
        state.a.value,
        state.x.value,
        state.y.value,
        state.sp.value,
        state.status,
        state.cycles,
    )

    with pytest.raises(UnsupportedOpcodeError):
        cpu.step()

    assert state.pc.value == 0x1235
    assert (
        state.a.value,
        state.x.value,
        state.y.value,
        state.sp.value,
        state.status,
        state.cycles,
    ) == before
