# CPU state

`MOS6502.capture_state()` returns an immutable `CPUState` holding everything
the processor owns at an instruction boundary; `restore_state()` applies one
without calling the host's bus.

| Field | Meaning |
| --- | --- |
| `a`, `x`, `y`, `s` | 8-bit registers; S addresses page one |
| `pc` | 16-bit program counter |
| `p` | status: N V 1 B D I Z C, kept with bit 5 set and B clear |
| `halted` | JAM has run; only a reset restarts the CPU |
| `reset_pending` | a reset has been requested and not yet run |
| `maskable_interrupt_pending` | the IRQ line is asserted (a level) |
| `non_maskable_interrupt_pending` | an NMI edge is latched and not yet taken |
| `polled_i` | after CLI, SEI or PLP: the I flag the chip's interrupt poll saw, which decides the next boundary; `None` otherwise |

`polled_i` is the one piece of internal state a register dump does not show.
CLI, SEI and PLP change I after the poll, so for one boundary the decision
uses the old I (docs/validation.md; NESdev "CPU interrupts"). Without it a
restored CPU could take an IRQ one instruction early or late.

## P, bit 5 and B

Neither bit 5 nor B is a flip-flop. Bit 5 reads as 1 whenever P is pushed. B
exists only in the pushed byte: set by BRK and PHP, clear for IRQ and NMI
(NMS p. 95). The core keeps `p` with bit 5 set and B clear, and `CPUState`
rejects any other value, so equal states mean equal processors.

## Machine boundary

`CPUState` excludes everything the host owns: memory, devices, clocks and
scheduling. Restoring it is correct when the host restores its own matching
state too; alone it is not a save state.

```python
before = cpu.capture_state()
memory_before = bytes(memory)  # the host's, not the CPU's

cpu.step()

memory[:] = memory_before
cpu.restore_state(before)
assert cpu.capture_state() == before
```
