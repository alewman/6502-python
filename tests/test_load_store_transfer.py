import pytest

from sixfiveohtwo import CPU, CPUState, IndexRegisters, StatusFlags


class Bus:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def read_byte(self, address):
        return self.values.get(address, 0)

    def write_byte(self, address, value):
        self.values[address] = value


@pytest.mark.parametrize(
    "opcode,operand,index,address,value,cycles",
    [
        (0xA9, (0x80,), (0, 0), None, 0x80, 2),
        (0xA5, (0x20,), (0, 0), 0x20, 0x81, 3),
        (0xB5, (0xFF,), (1, 0), 0, 0x82, 4),
        (0xAD, (0, 0x20), (0, 0), 0x2000, 0x83, 4),
        (0xBD, (0xFF, 0x20), (1, 0), 0x2100, 0x84, 5),
        (0xB9, (0xFF, 0x20), (0, 1), 0x2100, 0x85, 5),
        (0xA1, (0x20,), (1, 0), 0x3000, 0x86, 6),
        (0xB1, (0x20,), (0, 1), 0x3100, 0x87, 6),
        (0xA2, (0x90,), (0, 0), None, 0x90, 2),
        (0xA6, (0x20,), (0, 0), 0x20, 0x91, 3),
        (0xB6, (0xFF,), (0, 1), 0, 0x92, 4),
        (0xAE, (0, 0x20), (0, 0), 0x2000, 0x93, 4),
        (0xBE, (0xFF, 0x20), (0, 1), 0x2100, 0x94, 4),
        (0xA0, (0xA0,), (0, 0), None, 0xA0, 2),
        (0xA4, (0x20,), (1, 0), 0x20, 0xA1, 3),
        (0xB4, (0xFF,), (1, 0), 0, 0xA2, 4),
        (0xAC, (0, 0x20), (0, 0), 0x2000, 0xA3, 4),
        (0xBC, (0xFF, 0x20), (1, 0), 0x2100, 0xA4, 4),
    ],
)
def test_all_load_encodings(opcode, operand, index, address, value, cycles):
    memory = {0x100: opcode, 0x101: operand[0], 0x102: operand[-1]}
    if opcode == 0xA1:
        memory.update({0x21: 0, 0x22: 0x30, 0x3000: value})
    elif opcode == 0xB1:
        memory.update({0x20: 0xFF, 0x21: 0x30, 0x3100: value})
    elif address is not None:
        memory[address] = value
    else:
        memory[0x101] = value
    cpu = CPU(
        Bus(memory),
        state=CPUState(
            program_counter=0x100, index=IndexRegisters(x=index[0], y=index[1])
        ),
    )
    result = cpu.step()
    register = (
        "a"
        if opcode in (0xA9, 0xA5, 0xB5, 0xAD, 0xBD, 0xB9, 0xA1, 0xB1)
        else ("x" if opcode in (0xA2, 0xA6, 0xB6, 0xAE, 0xBE) else "y")
    )
    assert getattr(cpu.state, register).value == value
    assert result.cycles == cycles
    assert cpu.state.status.negative is True
    assert cpu.state.status.zero is False


@pytest.mark.parametrize(
    "opcode,operand,index,register,cycles",
    [
        (0x85, (0x20,), (0, 0), "a", 3),
        (0x95, (0xFF,), (1, 0), "a", 4),
        (0x8D, (0, 0x20), (0, 0), "a", 4),
        (0x9D, (0xFF, 0x20), (1, 0), "a", 5),
        (0x99, (0xFF, 0x20), (0, 1), "a", 5),
        (0x81, (0x20,), (1, 0), "a", 6),
        (0x91, (0x20,), (0, 1), "a", 6),
        (0x86, (0x20,), (0, 0), "x", 3),
        (0x96, (0xFF,), (0, 1), "x", 4),
        (0x8E, (0, 0x20), (0, 0), "x", 4),
        (0x84, (0x20,), (0, 0), "y", 3),
        (0x94, (0xFF,), (1, 0), "y", 4),
        (0x8C, (0, 0x20), (0, 0), "y", 4),
    ],
)
def test_all_store_encodings_write_and_preserve_flags(
    opcode, operand, index, register, cycles
):
    state = CPUState(
        accumulator=0xA5,
        index=IndexRegisters(x=0xA5, y=0xA5),
        status=StatusFlags(negative=True, zero=True),
    )
    values = {0: opcode, 1: operand[0], 2: operand[-1]}
    if opcode == 0x81:
        values.update({0x21: 0, 0x22: 0x30})
    elif opcode == 0x91:
        values.update({0x20: 0xFF, 0x21: 0x30})
    cpu = CPU(Bus(values), state=state)
    result = cpu.step()
    assert result.cycles == cycles
    assert state.status == StatusFlags(negative=True, zero=True)
    stored_value = getattr(state, register).value
    assert any(
        address not in (0x100, 0x101, 0x102) and value == stored_value
        for address, value in cpu.memory.values.items()
    )


@pytest.mark.parametrize(
    "opcode,source,target,flags",
    [
        (0xAA, "a", "x", True),
        (0xA8, "a", "y", True),
        (0xBA, "sp", "x", True),
        (0x8A, "x", "a", True),
        (0x9A, "x", "sp", False),
        (0x98, "y", "a", True),
    ],
)
def test_transfer_encodings_apply_nz_except_txs(opcode, source, target, flags):
    state = CPUState(
        accumulator=0x80, index=IndexRegisters(x=0x80, y=0x80), stack_pointer=0x80
    )
    cpu = CPU(Bus({0: opcode}), state=state)
    cpu.step()
    assert getattr(state, target).value == getattr(state, source).value
    assert state.status.negative is flags
    assert state.status.zero is False
    assert state.cycles == 2
