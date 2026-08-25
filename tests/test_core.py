import pytest

from sixfiveohtwo import CPU, CPUState, InterruptBoundary, InterruptLines, MemoryBus


class HostMemory:
    def __init__(self):
        self.bytes = {}
        self.operations = []

    def read_byte(self, address: int) -> int:
        self.operations.append(("read", address))
        return self.bytes.get(address, 0)

    def write_byte(self, address: int, value: int) -> None:
        self.operations.append(("write", address, value))
        self.bytes[address] = value


class HostDeviceMemory(HostMemory):
    def __init__(self):
        super().__init__()
        self.device_registers = {0xD012: 0x40}

    def read_byte(self, address: int) -> int:
        if address in self.device_registers:
            self.operations.append(("device-read", address))
            return self.device_registers[address]
        return super().read_byte(address)

    def write_byte(self, address: int, value: int) -> None:
        if address in self.device_registers:
            self.operations.append(("device-write", address, value))
            self.device_registers[address] = value
            return
        super().write_byte(address, value)


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


def test_host_can_inspect_line_lifecycle_without_executing_interrupts():
    cpu = CPU(HostMemory())

    cpu.set_reset(True)
    cpu.set_irq(True)
    cpu.set_nmi(True)

    asserted = InterruptBoundary(reset=True, irq=True, nmi=True)
    assert cpu.pending_interrupt_boundary() == asserted
    assert cpu.nmi_pending is True
    assert cpu.sample_instruction_boundary() == asserted
    assert cpu.nmi_pending is False

    # RESET and IRQ remain level-sensitive after the NMI edge is consumed.
    assert cpu.sample_instruction_boundary() == InterruptBoundary(
        reset=True, irq=True, nmi=False
    )
    cpu.set_reset(False)
    cpu.set_irq(False)
    cpu.set_nmi(False)
    assert cpu.pending_interrupt_boundary() == InterruptBoundary(
        reset=False, irq=False, nmi=False
    )

    cpu.set_nmi(True)
    assert cpu.pending_interrupt_boundary() == InterruptBoundary(
        reset=False, irq=False, nmi=True
    )


def test_cpu_preserves_host_memory_and_device_ownership():
    memory = HostDeviceMemory()
    cpu = CPU(memory)
    cpu.set_reset(True)
    cpu.set_irq(True)
    cpu.set_nmi(True)

    assert cpu.memory is memory
    assert memory.operations == []
    memory.write_byte(0x0042, 0xA5)
    memory.write_byte(0xD012, 0x7F)

    assert cpu.memory.read_byte(0x0042) == 0xA5
    assert cpu.memory.read_byte(0xD012) == 0x7F
    assert memory.operations == [
        ("write", 0x0042, 0xA5),
        ("device-write", 0xD012, 0x7F),
        ("read", 0x0042),
        ("device-read", 0xD012),
    ]


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
