import pytest

from sixfiveohtwo import CPU, CPUState, IndexRegisters, StatusFlags


class Bus:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def read_byte(self, address):
        return self.values.get(address, 0)

    def write_byte(self, address, value):
        self.values[address] = value


LOGICAL_CASES = [
    (opcode, mnemonic, mode, operand, index, address, cycles)
    for mnemonic, opcodes in (
        ("ORA", (0x09, 0x05, 0x15, 0x0D, 0x1D, 0x19, 0x01, 0x11)),
        ("AND", (0x29, 0x25, 0x35, 0x2D, 0x3D, 0x39, 0x21, 0x31)),
        ("EOR", (0x49, 0x45, 0x55, 0x4D, 0x5D, 0x59, 0x41, 0x51)),
    )
    for opcode, mode, operand, index, address, cycles in zip(
        opcodes,
        (
            "immediate",
            "zero_page",
            "zero_page_x",
            "absolute",
            "absolute_x",
            "absolute_y",
            "indexed_indirect",
            "indirect_indexed",
        ),
        (
            (0x0F,),
            (0x20,),
            (0xFF,),
            (0x34, 0x12),
            (0xFF, 0x20),
            (0xFF, 0x20),
            (0x20,),
            (0x20,),
        ),
        ((0, 0), (0, 0), (1, 0), (0, 0), (1, 0), (0, 1), (1, 0), (0, 1)),
        (None, 0x20, 0, 0x1234, 0x2100, 0x2100, 0x3000, 0x3100),
        (2, 3, 4, 4, 5, 5, 6, 6),
        strict=True,
    )
]


def _logical_memory(opcode, operand, address, index):
    values = {0x100: opcode}
    values.update(dict(enumerate(operand, start=0x101)))
    if opcode in (0x01, 0x41, 0x21):
        values.update({0x21: 0, 0x22: 0x30})
    elif opcode in (0x11, 0x51, 0x31):
        values.update({0x20: 0xFF, 0x21: 0x30})
    if address is not None:
        values[address] = 0x0F
    return values


@pytest.mark.parametrize(
    "opcode,mnemonic,mode,operand,index,address,cycles", LOGICAL_CASES
)
def test_all_logical_encodings_update_a_nz_and_account_for_indexing(
    opcode, mnemonic, mode, operand, index, address, cycles
):
    state = CPUState(
        program_counter=0x100,
        accumulator=0xF0,
        index=IndexRegisters(x=index[0], y=index[1]),
        status=StatusFlags(negative=False, zero=False),
    )
    cpu = CPU(Bus(_logical_memory(opcode, operand, address, index)), state=state)
    result = cpu.step()

    expected = {"ORA": 0xFF, "AND": 0x00, "EOR": 0xFF}[mnemonic]
    assert state.a.value == expected
    assert state.status.negative is (expected & 0x80 != 0)
    assert state.status.zero is (expected == 0)
    assert result.cycles == cycles


BIT_CASES = ((0x24, (0x20,), 0x20, 3), (0x2C, (0x34, 0x12), 0x1234, 4))


@pytest.mark.parametrize("opcode,operand,address,cycles", BIT_CASES)
def test_bit_sets_n_v_from_operand_z_from_a_and_preserves_a(
    opcode, operand, address, cycles
):
    values = {0x100: opcode, **dict(enumerate(operand, start=0x101)), address: 0xC0}
    state = CPUState(
        program_counter=0x100,
        accumulator=0x20,
        status=StatusFlags(negative=False, overflow=False, zero=False),
    )
    cpu = CPU(Bus(values), state=state)

    result = cpu.step()

    assert result.cycles == cycles
    assert state.a.value == 0x20
    assert state.status == StatusFlags(negative=True, overflow=True, zero=True)


def test_zero_page_indexed_logical_reads_wrap_at_ff():
    state = CPUState(
        program_counter=0x100,
        accumulator=0x01,
        index=IndexRegisters(x=1),
    )
    cpu = CPU(Bus({0x100: 0x15, 0x101: 0xFF, 0: 0x03}), state=state)

    cpu.step()

    assert state.a.value == 0x03
    assert state.cycles == 4


@pytest.mark.parametrize("opcode", [0x1D, 0x19, 0x3D, 0x39, 0x5D, 0x59])
def test_indexed_logical_reads_add_only_page_cross_penalty(opcode):
    values = {0: opcode, 1: 0xFF, 2: 0x20, 0x2100: 0x01}
    state = CPUState(
        accumulator=0x02,
        index=IndexRegisters(x=1, y=1),
    )
    result = CPU(Bus(values), state=state).step()

    assert result.cycles == 5
