"""ANE and LXA's magic constant is a setting of each CPU, $EE by default.

The constant varies between chips (NMS pp. 60-64), so a host modelling a
particular console sets it: famicom-python sets LXA's to $FF, the value under
which blargg's ``instr_test-v5`` CRCs, taken on an NES, match.
"""

from sixfiveohtwo import MOS6502, RP2A03


def _run(cpu_class: type[MOS6502], program: bytes, a: int, x: int, **constants: int) -> MOS6502:
    memory = bytearray(0x10000)
    memory[0x0200 : 0x0200 + len(program)] = program
    cpu = cpu_class(memory.__getitem__, memory.__setitem__)
    for name, value in constants.items():
        setattr(cpu, name, value)
    cpu.pc, cpu.a, cpu.x = 0x0200, a, x
    cpu.step()
    return cpu


def test_default_constant_is_single_step_tests_value() -> None:
    assert MOS6502.ane_constant == MOS6502.lxa_constant == 0xEE
    cpu = _run(MOS6502, bytes((0xAB, 0x0F)), a=0x00, x=0x55)  # LXA #$0F
    assert (cpu.a, cpu.x) == (0x0E, 0x0E)
    cpu = _run(MOS6502, bytes((0x8B, 0xFF)), a=0x00, x=0xFF)  # ANE #$FF
    assert cpu.a == 0xEE


def test_lxa_uses_the_instance_constant() -> None:
    cpu = _run(RP2A03, bytes((0xAB, 0x0F)), a=0x00, x=0x55, lxa_constant=0xFF)
    assert (cpu.a, cpu.x) == (0x0F, 0x0F)
    cpu = _run(RP2A03, bytes((0xAB, 0x80)), a=0x00, x=0x55, lxa_constant=0x00)
    assert (cpu.a, cpu.x) == (0x00, 0x00)
    assert cpu.p & 0x02  # Z from the result


def test_ane_uses_the_instance_constant() -> None:
    cpu = _run(MOS6502, bytes((0x8B, 0xFF)), a=0x00, x=0x0F, ane_constant=0xFF)
    assert cpu.a == 0x0F
    cpu = _run(MOS6502, bytes((0x8B, 0xFF)), a=0x00, x=0xFF, ane_constant=0x11)
    assert cpu.a == 0x11


def test_setting_one_cpu_leaves_the_others_alone() -> None:
    _run(MOS6502, bytes((0xEA,)), a=0, x=0, ane_constant=0x00, lxa_constant=0x00)
    assert MOS6502.ane_constant == MOS6502.lxa_constant == 0xEE
    cpu = _run(MOS6502, bytes((0xAB, 0xFF)), a=0x00, x=0x00)
    assert cpu.a == 0xEE
