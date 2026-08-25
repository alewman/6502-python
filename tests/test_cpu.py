import pytest

from sixfiveohtwo import (
    Accumulator,
    CPUState,
    IndexRegister,
    IndexRegisters,
    ProgramCounter,
    Register8,
    Register16,
    StackPointer,
    StatusFlags,
)


def test_cpu_state_defaults_match_reset_register_shape():
    state = CPUState()
    other = CPUState()

    assert state.a == Accumulator(0)
    assert state.x == IndexRegister(0)
    assert state.y == IndexRegister(0)
    assert state.pc == ProgramCounter(0)
    assert state.sp == StackPointer(0xFD)
    assert state.status == StatusFlags()
    assert state.status.to_byte() == 0x20

    state.a.value = 0xA5
    state.x.value = 0x5A
    assert other.a.value == 0
    assert other.x.value == 0


@pytest.mark.parametrize(
    ("register_type", "maximum"),
    [(Register8, 0xFF), (Register16, 0xFFFF)],
)
def test_registers_accept_width_boundaries(register_type, maximum):
    register = register_type(maximum)

    assert register.value == maximum
    register.value = 0
    register.set(maximum)
    assert int(register) == maximum


@pytest.mark.parametrize(
    ("register_type", "invalid_values"),
    [
        (Register8, (-1, 0x100, True, "1")),
        (Register16, (-1, 0x10000, True, "1")),
    ],
)
def test_registers_reject_values_outside_their_width(register_type, invalid_values):
    register = register_type()

    for value in invalid_values:
        error = TypeError if isinstance(value, (bool, str)) else ValueError
        with pytest.raises(error):
            register.value = value
        with pytest.raises(error):
            register.set(value)


def test_cpu_state_coerces_integer_register_values_to_typed_registers():
    state = CPUState(
        accumulator=0x12,
        index=IndexRegisters(x=1, y=2),
        program_counter=0x3456,
        stack_pointer=0xAB,
    )

    assert state.a.value == 0x12
    assert isinstance(state.a, Accumulator)
    assert state.x.value == 1
    assert state.y.value == 2
    assert state.pc.value == 0x3456
    assert state.sp.value == 0xAB


def test_cpu_state_cycle_accounting_defaults_and_accepts_nonnegative_totals():
    state = CPUState(cycles=7)

    assert state.cycles == 7
    state.cycles += 3
    assert state.cycles == 10

    with pytest.raises(TypeError):
        CPUState(cycles=True)
    with pytest.raises(ValueError):
        CPUState(cycles=-1)


def test_status_flags_serialize_all_physical_flags_with_unused_bit_set():
    flags = StatusFlags(
        negative=True,
        overflow=True,
        decimal=True,
        interrupt_disable=True,
        zero=True,
        carry=True,
    )

    assert flags.to_byte() == 0xEF


def test_status_flags_round_trip_ignores_unused_and_break_bits():
    flags = StatusFlags.from_byte(0xFF)

    assert flags == StatusFlags(
        negative=True,
        overflow=True,
        decimal=True,
        interrupt_disable=True,
        zero=True,
        carry=True,
    )
    assert flags.to_byte() == 0xEF


def test_break_flag_is_only_set_for_requested_status_serialization_context():
    flags = StatusFlags(carry=True)

    assert flags.to_byte() == 0x21
    assert flags.to_byte(break_flag=True) == 0x31
    assert StatusFlags.from_byte(0x31) == StatusFlags(carry=True)

    with pytest.raises(TypeError):
        flags.to_byte(break_flag=1)
