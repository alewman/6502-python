import pytest

from sixfiveohtwo import CPU, CPUState, InterruptBoundary, InterruptLines, MemoryBus


class HostMemory:
    def read_byte(self, address: int) -> int:
        return 0

    def write_byte(self, address: int, value: int) -> None:
        return None


def test_cpu_owns_state_and_delegates_host_memory_and_lines():
    memory = HostMemory()
    lines = InterruptLines()
    cpu = CPU(memory, lines=lines)

    assert isinstance(cpu.memory, MemoryBus)
    assert cpu.state == CPUState()
    assert cpu.lines is lines

    cpu.set_reset(True)
    cpu.set_irq(True)
    cpu.set_nmi(True)
    assert cpu.reset is True
    assert cpu.irq is True
    assert cpu.nmi is True
    assert cpu.nmi_pending is True


def test_cpu_boundary_inspection_does_not_consume_nmi():
    cpu = CPU(HostMemory())
    cpu.signal_nmi()

    expected = InterruptBoundary(reset=False, irq=False, nmi=True)
    assert cpu.pending_interrupt_boundary() == expected
    assert cpu.nmi_pending is True
    assert cpu.sample_instruction_boundary() == expected
    assert cpu.nmi_pending is False
    assert cpu.sample_instruction_boundary().nmi is False


def test_cpu_shell_does_not_change_state_or_access_memory_on_lines():
    cpu = CPU(HostMemory())
    cpu.set_reset(True)

    assert cpu.state == CPUState()


@pytest.mark.parametrize("argument", [None, object()])
def test_cpu_requires_host_memory(argument):
    with pytest.raises(TypeError):
        CPU(argument)


def test_cpu_rejects_wrong_optional_contract_objects():
    with pytest.raises(TypeError):
        CPU(HostMemory(), lines=object())
    with pytest.raises(TypeError):
        CPU(HostMemory(), state=object())
