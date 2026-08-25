import pytest

from sixfiveohtwo import CPU, CPUState, StatusFlags
from sixfiveohtwo.core import OFFICIAL_OPCODES


class Bus:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def read_byte(self, address):
        return self.values.get(address, 0)

    def write_byte(self, address, value):
        self.values[address] = value


BRANCHES = {
    "BCC": (0x90, "carry", False),
    "BCS": (0xB0, "carry", True),
    "BEQ": (0xF0, "zero", True),
    "BMI": (0x30, "negative", True),
    "BNE": (0xD0, "zero", False),
    "BPL": (0x10, "negative", False),
    "BVC": (0x50, "overflow", False),
    "BVS": (0x70, "overflow", True),
}


@pytest.mark.parametrize("mnemonic, branch", BRANCHES.items())
def test_all_official_branch_encodings_are_cataloged(mnemonic, branch):
    opcode = branch[0]
    assert OFFICIAL_OPCODES[opcode].mnemonic == mnemonic
    assert OFFICIAL_OPCODES[opcode].operand_bytes == 1


@pytest.mark.parametrize("mnemonic, branch", BRANCHES.items())
def test_branch_not_taken_consumes_two_cycles_and_leaves_post_operand_pc(
    mnemonic, branch
):
    opcode, flag, taken = branch
    state = CPUState(program_counter=0x2000, status=StatusFlags(**{flag: not taken}))
    cpu = CPU(Bus({0x2000: opcode, 0x2001: 0x7F}), state=state)

    result = cpu.step()

    assert result.cycles == 2
    assert state.pc.value == 0x2002


@pytest.mark.parametrize("mnemonic, branch", BRANCHES.items())
def test_branch_taken_adds_one_cycle_and_uses_signed_forward_offset(mnemonic, branch):
    opcode, flag, taken = branch
    state = CPUState(program_counter=0x2000, status=StatusFlags(**{flag: taken}))
    cpu = CPU(Bus({0x2000: opcode, 0x2001: 0x05}), state=state)

    result = cpu.step()

    assert result.cycles == 3
    assert state.pc.value == 0x2007


@pytest.mark.parametrize("mnemonic, branch", BRANCHES.items())
def test_branch_taken_backward_offset_and_page_cross_costs_one_extra_cycle(
    mnemonic, branch
):
    opcode, flag, taken = branch
    state = CPUState(program_counter=0x20FE, status=StatusFlags(**{flag: taken}))
    cpu = CPU(Bus({0x20FE: opcode, 0x20FF: 0xFC}), state=state)

    result = cpu.step()

    assert result.cycles == 4
    assert state.pc.value == 0x20FC


@pytest.mark.parametrize(
    "start, offset, expected_pc",
    [(0xFFFE, 0x02, 0x0002), (0x0000, 0xFE, 0x0000)],
)
def test_branch_target_wraps_the_16_bit_address_space(start, offset, expected_pc):
    state = CPUState(program_counter=start, status=StatusFlags(carry=False))
    cpu = CPU(Bus({start: 0x90, (start + 1) & 0xFFFF: offset}), state=state)

    result = cpu.step()

    assert result.cycles == 3
    assert state.pc.value == expected_pc
