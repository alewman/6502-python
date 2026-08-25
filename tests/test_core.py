import pytest

from sixfiveohtwo import CPU, CPUState, InterruptBoundary, InterruptLines, MemoryBus
from sixfiveohtwo.core import (
    InstructionContext,
    InstructionStep,
    _normalize_byte_address,
    _normalize_word_address,
)


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


@pytest.mark.parametrize(
    ("normalizer", "value", "expected"),
    [
        (_normalize_byte_address, 0x1234, 0x34),
        (_normalize_byte_address, -1, 0xFF),
        (_normalize_word_address, 0x12345, 0x2345),
        (_normalize_word_address, -1, 0xFFFF),
    ],
)
def test_address_normalization_wraps_to_requested_width(normalizer, value, expected):
    assert normalizer(value) == expected


@pytest.mark.parametrize(
    ("start", "values", "expected_pc", "expected_value", "addresses"),
    [
        (0x0000, (0x12,), 0x0001, 0x12, (0x0000,)),
        (0xFFFF, (0x34,), 0x0000, 0x34, (0xFFFF,)),
    ],
)
def test_fetch_byte_reads_at_pc_and_wraps_pc(
    start, values, expected_pc, expected_value, addresses
):
    memory = HostMemory()
    memory.bytes.update(dict(zip(addresses, values)))
    cpu = CPU(memory, state=CPUState(program_counter=start))

    assert cpu._fetch_byte() == expected_value
    assert cpu.state.pc.value == expected_pc
    assert memory.operations == [("read", address) for address in addresses]


@pytest.mark.parametrize(
    ("start", "values", "expected_pc", "expected_word", "addresses"),
    [
        (0x0000, (0x34, 0x12), 0x0002, 0x1234, (0x0000, 0x0001)),
        (0xFFFF, (0x78, 0x56), 0x0001, 0x5678, (0xFFFF, 0x0000)),
    ],
)
def test_fetch_word_reads_little_endian_and_wraps_pc(
    start, values, expected_pc, expected_word, addresses
):
    memory = HostMemory()
    memory.bytes.update(dict(zip(addresses, values)))
    cpu = CPU(memory, state=CPUState(program_counter=start))

    assert cpu._fetch_word() == expected_word
    assert cpu.state.pc.value == expected_pc
    assert memory.operations == [("read", address) for address in addresses]


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


def test_step_samples_boundary_fetches_one_opcode_and_prepares_context():
    memory = HostMemory()
    memory.bytes[0xFFFF] = 0xA9
    state = CPUState(program_counter=0xFFFF)
    cpu = CPU(memory, state=state)
    cpu.signal_nmi()
    cpu.set_reset(True)

    result = cpu.step(cycles=2)

    assert isinstance(result, InstructionStep)
    assert isinstance(result.context, InstructionContext)
    assert result.boundary == InterruptBoundary(reset=True, irq=False, nmi=True)
    assert result.opcode == 0xA9
    assert result.context.opcode_address == 0xFFFF
    assert result.context.state is state
    assert state.pc.value == 0
    assert state.cycles == 2
    assert result.cycles == 2
    assert result.total_cycles == 2
    assert memory.operations == [("read", 0xFFFF)]


def test_step_without_execution_records_no_cycles_and_consumes_nmi_once():
    memory = HostMemory()
    memory.bytes[0] = 0xEA
    cpu = CPU(memory)
    cpu.signal_nmi()

    first = cpu.step()
    second = cpu.step()

    assert first.boundary.nmi is True
    assert second.boundary.nmi is False
    assert first.cycles == 0
    assert second.total_cycles == 0
    assert cpu.state.cycles == 0


@pytest.mark.parametrize("cycles", [-1, True, "1"])
def test_cycle_accounting_rejects_invalid_values(cycles):
    cpu = CPU(HostMemory())

    with pytest.raises((TypeError, ValueError)):
        cpu.record_cycles(cycles)
    with pytest.raises((TypeError, ValueError)):
        cpu.step(cycles=cycles)


@pytest.mark.parametrize("argument", [None, object()])
def test_cpu_requires_host_memory(argument):
    with pytest.raises(TypeError):
        CPU(argument)


def test_cpu_rejects_wrong_optional_contract_objects():
    with pytest.raises(TypeError):
        CPU(HostMemory(), lines=object())
    with pytest.raises(TypeError):
        CPU(HostMemory(), state=object())
