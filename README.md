# 6502-python

[![CI](https://github.com/alewman/6502-python/actions/workflows/ci.yml/badge.svg)](https://github.com/alewman/6502-python/actions/workflows/ci.yml)
[![Oracles](https://github.com/alewman/6502-python/actions/workflows/oracles.yml/badge.svg)](https://github.com/alewman/6502-python/actions/workflows/oracles.yml)

A readable, pure-Python NMOS 6502 **instruction-core reference implementation**,
correct to the bus cycle.

`6502-python` (imported as `sixfiveohtwo`) is a member of a family of cores
built to one shape, whose reference is
[z80-python](https://github.com/alewman/z80-python): the host passes its bus
in as two callables, `step()` returns the cycles it took, registers are plain
attributes, and the same debugger, disassembler and trace format sit beside
the core. It implements all 256 NMOS 6502 opcodes, the 151 MOS documented and
the 105 it did not, and makes every bus access the chip makes, in the chip's
order, dummy reads and read-modify-write dummy writes included.

The project is deliberately:

- **readable** -- every instruction is an ordinary Python method; one table
  routes each opcode to its method, and each method cites the page its rule
  comes from;
- **pure Python** -- no runtime dependencies; CPython 3.12+ and PyPy 3.11;
- **independently validated** -- correctness claims come from external
  oracles, each named with its tier;
- **embeddable** -- a host passes in its memory as callables and decides
  when the processor advances; and
- **inspectable** -- CPU state capture, disassembly, a debugger with
  breakpoints, watchpoints and bus-access tracking, structured traces, and
  `python -m sixfiveohtwo` for stepping a binary.

## Validation

Each oracle is named with its tier: where its expected values came from
([oracle tiers](docs/validation.md#oracles-and-tiers)). The core passes:

- **self-checking programs:** Klaus Dormann's 6502 functional test (every
  documented instruction and addressing mode, 30,646,177 instructions to its
  success trap) and the decimal test (every ADC and SBC result and flag in
  decimal mode, by NMOS rules), whose expected values their authors computed;
- **emulator-derived:** the SingleStepTests 65x02 corpus, all 256 opcodes,
  2,560,000 of 2,560,000 cases: registers, RAM, cycle count, and the address,
  value and direction of every bus cycle;
- **documentation:** MOS's programming and hardware manuals for the documented
  instructions and their bus cycles, *No More Secrets* v0.99 for the
  undocumented ones, the NESdev wiki for interrupt timing; every handler cites
  its page, and `tests/test_readability.py` checks each page against the
  document's own layout.

Where the documents and the corpus disagree, the core's choice and the reason
are listed in [docs/validation.md](docs/validation.md#divergences).

### CI coverage

Every push runs the quick loop on CPython 3.12, 3.13, 3.14 and PyPy 3.11, ruff
lint and format checks, a wheel build with an installed-package smoke test,
and both Dormann exercisers (the decimal one assembled with cc65). The
SingleStepTests corpus is ~420 MB, so the full sweep runs weekly and on
demand in `oracles.yml`.

## Install

Not yet on PyPI. Install from a checkout:

```console
git clone https://github.com/alewman/6502-python
cd 6502-python
python -m pip install -e '.[dev]'
```

## Minimal host

```python
from sixfiveohtwo import MOS6502

memory = bytearray(0x10000)
cpu = MOS6502(memory.__getitem__, memory.__setitem__)  # read_byte, write_byte
memory[0x0200:0x0203] = bytes((0xA9, 0x2A, 0xE8))  # LDA #$2A; INX
cpu.pc = 0x0200
assert cpu.step() == 2
assert cpu.step() == 2
assert (cpu.a, cpu.x) == (0x2A, 1)
```

This is the embedding contract of the whole family: z80-python and
m6800-python take their bus the same way. The core always passes a 16-bit
address and an 8-bit value, and calls the bus exactly once per cycle it
returns, so a memory-mapped device sees each read and write the real chip
would make -- including the dummy read of an I/O register that acknowledges
it. [Start here](docs/start-here.md) has the rest; `examples/minimal_host.py`
is a runnable host that boots through the reset vector.

Until 0.2.0 the CPU took one object with both methods; passing one now raises
a `TypeError` naming the new form. See [CHANGELOG.md](CHANGELOG.md).

## Reset and interrupts

- `request_reset()` runs the chip's seven-cycle start sequence at the next
  boundary: three stack reads with nothing written, I set, PC from `$FFFC`
  (MOS programming manual, section 9.2). It also restarts a CPU stopped by JAM.
- `request_maskable_interrupt()` asserts IRQ, a level: it stays asserted until
  `clear_maskable_interrupt()`, as a device holds the line until acknowledged.
- `request_non_maskable_interrupt()` latches an NMI edge, taken at the next
  boundary whatever I says.

CLI, SEI and PLP change I after the chip has polled for interrupts, so a
waiting IRQ is taken one instruction later than I alone suggests; RTI's
restored I counts at once; an NMI arriving during BRK or an IRQ entry takes it
over. All three are modelled and tested.

## Learning and inspection

Every opcode handler's docstring starts with its mnemonic, so
`grep -rn '"""LDA' src/` lands on the implementation, and ends with the page its
rule comes from. The addressing modes in `_core.py` are written cycle by
cycle, one bus access per line, in the order the hardware manual lists them.

- [Start here](docs/start-here.md): registers, P, the embedding contract,
  the bus cycles, reset and interrupts, and the sources.
- [CPU state](docs/cpu-state.md), [disassembly](docs/disassembly.md),
  [debug sessions](docs/debug-session.md), [trace schema](docs/trace-schema.md).
- [Undocumented behaviour](docs/undocumented-behavior.md): the 105 opcodes
  and the magic constant.

```console
python -m sixfiveohtwo --load tests/dormann/bin_files/6502_functional_test.bin@0 \
    --pc 0x0400 --batch -c "step 3" -c "watch 0x0200 w" -c "continue"
```

## Development

```console
python -m pytest -m "not slow"                  # the quick loop, ~10 s
python scripts/fetch_test_vectors.py            # SingleStepTests, ~420 MB
python scripts/fetch_dormann_tests.py           # Dormann; the decimal test needs cc65
python -m pytest -m slow                        # the full corpus and both exercisers
python scripts/fetch_reference_docs.py          # the three cited documents, SHA-256 pinned
python benchmarks/core_benchmark.py             # instructions per second
python benchmarks/compare_revisions.py OLD NEW  # a same-process A/B between revisions
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT; see [LICENSE](LICENSE).
