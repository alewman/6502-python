import pytest

from sixfiveohtwo import CPU, CPUState, IndexRegisters, StatusFlags
from sixfiveohtwo.core import OFFICIAL_OPCODES


class Bus:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def read_byte(self, address):
        return self.values.get(address, 0)

    def write_byte(self, address, value):
        self.values[address] = value


# The core implements the whole NMOS byte space, documented and undocumented.
OPCODE_BYTES = set(range(0x100))


def test_opcode_set_is_complete_and_dispatches_to_implemented_semantics():
    assert set(OFFICIAL_OPCODES) == OPCODE_BYTES

    for opcode in sorted(OPCODE_BYTES):
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


@pytest.mark.parametrize("opcode", [0x0B, 0x4B, 0x6B, 0x8B, 0xAB, 0xCB])
def test_previously_unofficial_opcodes_now_execute_and_advance(opcode):
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

    result = cpu.step()

    assert result.opcode == opcode
    # Every one of these is a two-byte immediate form, so PC clears the operand.
    assert state.pc.value == 0x1236
    assert state.cycles > 11
