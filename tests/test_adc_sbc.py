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


ADC_OPCODES = (0x69, 0x65, 0x75, 0x6D, 0x7D, 0x79, 0x61, 0x71)
SBC_OPCODES = (0xE9, 0xE5, 0xF5, 0xED, 0xFD, 0xF9, 0xE1, 0xF1)


@pytest.mark.parametrize(
    "mnemonic,opcodes", [("ADC", ADC_OPCODES), ("SBC", SBC_OPCODES)]
)
def test_catalog_contains_every_adc_and_sbc_encoding(mnemonic, opcodes):
    assert {
        definition.opcode
        for definition in OFFICIAL_OPCODES.values()
        if definition.mnemonic == mnemonic
    } == set(opcodes)


@pytest.mark.parametrize(
    "opcode,operand,index,address,cycles,adc_result,sbc_result",
    [
        (0x69, (0x02,), (0, 0), None, 2, 0x06, 0x01),
        (0x65, (0x20,), (0, 0), 0x20, 3, 0x05, 0x02),
        (0x75, (0xFF,), (1, 0), 0x00, 4, 0x05, 0x02),
        (0x6D, (0x34, 0x12), (0, 0), 0x1234, 4, 0x05, 0x02),
        (0x7D, (0xFF, 0x20), (1, 0), 0x2100, 5, 0x05, 0x02),
        (0x79, (0xFF, 0x20), (0, 1), 0x2100, 5, 0x05, 0x02),
        (0x61, (0x20,), (1, 0), 0x3000, 6, 0x05, 0x02),
        (0x71, (0x20,), (0, 1), 0x3100, 6, 0x05, 0x02),
    ],
)
@pytest.mark.parametrize("opcode_offset", [0, 0x80])
def test_adc_and_sbc_all_addressing_modes(
    opcode, operand, index, address, cycles, adc_result, sbc_result, opcode_offset
):
    opcode += opcode_offset
    values = {0x100: opcode, **dict(enumerate(operand, start=0x101))}
    if opcode in (0x61, 0xE1):
        values.update({0x21: 0x00, 0x22: 0x30})
    elif opcode in (0x71, 0xF1):
        values.update({0x20: 0xFF, 0x21: 0x30})
    if address is not None:
        values[address] = 0x01
    state = CPUState(
        program_counter=0x100,
        accumulator=0x03,
        index=IndexRegisters(x=index[0], y=index[1]),
        status=StatusFlags(carry=True),
    )

    result = CPU(Bus(values), state=state).step()

    assert result.cycles == cycles
    assert state.a.value == (adc_result if opcode < 0x80 else sbc_result)


@pytest.mark.parametrize(
    "accumulator,operand,carry,expected,flags",
    [
        (0x50, 0x50, False, 0xA0, (False, True, True, False)),
        (0xFF, 0x01, False, 0x00, (True, False, False, True)),
        (0x45, 0x55, False, 0x00, (True, True, True, False)),
        (0x0A, 0x00, False, 0x10, (False, False, False, False)),
    ],
)
def test_adc_binary_and_nmos_decimal_flags(
    accumulator, operand, carry, expected, flags
):
    decimal = expected in (0x00, 0x10) and accumulator in (0x45, 0x0A)
    state = CPUState(
        accumulator=accumulator,
        status=StatusFlags(carry=carry, decimal=decimal),
    )
    cpu = CPU(Bus({0: 0x69, 1: operand}), state=state)

    cpu.step()

    assert state.a.value == expected
    assert (
        state.status.carry,
        state.status.negative,
        state.status.overflow,
        state.status.zero,
    ) == flags


@pytest.mark.parametrize(
    "accumulator,operand,carry,decimal,expected,flags",
    [
        (0x80, 0x01, True, False, 0x7F, (True, False, True, False)),
        (0x00, 0x01, True, False, 0xFF, (False, True, False, False)),
        (0x00, 0x01, True, True, 0x99, (False, True, False, False)),
        (0x10, 0x01, True, True, 0x09, (True, False, False, False)),
        (0x00, 0x0A, True, True, 0x90, (False, True, False, False)),
    ],
)
def test_sbc_binary_and_nmos_decimal_flags(
    accumulator, operand, carry, decimal, expected, flags
):
    state = CPUState(
        accumulator=accumulator,
        status=StatusFlags(carry=carry, decimal=decimal),
    )
    cpu = CPU(Bus({0: 0xE9, 1: operand}), state=state)

    cpu.step()

    assert state.a.value == expected
    assert (
        state.status.carry,
        state.status.negative,
        state.status.overflow,
        state.status.zero,
    ) == flags


@pytest.mark.parametrize(
    "opcode,expected_cycles",
    [(0x7D, 5), (0x79, 5), (0x71, 6), (0xFD, 5), (0xF9, 5), (0xF1, 6)],
)
def test_adc_sbc_page_crossing_adds_one_cycle(opcode, expected_cycles):
    values = {0: opcode, 1: 0xFF, 2: 0x20, 0x2100: 0x01}
    if opcode in (0x71, 0xF1):
        values.update({1: 0x20, 0x20: 0xFF, 0x21: 0x20, 0x2100: 0x01})
    state = CPUState(
        accumulator=0x02,
        index=IndexRegisters(x=1, y=1),
        status=StatusFlags(carry=True),
    )

    result = CPU(Bus(values), state=state).step()

    assert result.cycles == expected_cycles
