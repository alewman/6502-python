# Public API stability

`6502-python` uses semantic versioning for the names exported from the package
root and listed in each public module's `__all__`: `MOS6502` and its
constructor `MOS6502(read_byte, write_byte)`, the flag constants, `CPUState`,
`Instruction` and the disassembly functions, `DebugSession` and its values,
`next_boundary`, `CommandDebugger`, the trace functions and values, and the
`python -m sixfiveohtwo` command line. The package ships `py.typed`.

Underscore-prefixed modules and names are implementation details. The CPU's
register attributes (`a`, `x`, `y`, `s`, `pc`, `p`), bus attributes
(`read_byte`, `write_byte`), chip settings (`ane_constant`, `lxa_constant`)
and the host's DMA input (`dma_stalled`) are public and writable.

## The frame: a subclassing surface

`sixfiveohtwo.frame.CPUFrame` is the base class of `MOS6502` and the base a
core for another 65xx-family part subclasses (`65816-python`'s `W65C816`
does). For it, these underscore names are public and semver-covered like the
exports, because a dependent core cannot work without them:

- the hooks `step()` calls, each returning cycles: `_accept_reset()`,
  `_halted()`, `_enter_interrupt(kind)` (`kind` is `NMI_LATCH` or
  `IRQ_LINE`, or a subclass's own bit) and `_execute()`; and
  `_boundary_interrupt()`, which a subclass may extend with its own request
  bits;
- the bus as handlers use it: `_read(address)`, `_write(address, value)`,
  `_read_byte`, `_write_byte`, and `_confirm()`, which an additional kind of
  bus cycle calls when `_deferred is not None`;
- the request state: `_requests`, `_polled`, `_deferred`, `_polled_i`,
  `_reset_pending`, `_request(requests)`, and the bits `IRQ_LINE`,
  `NMI_LATCH` and `NO_POLL` exported by `sixfiveohtwo.frame`;
- the stalled-read record `note_stall()` keeps, `_stalled` and
  `_stalled_before`, which a part's branch sequence reads and resets;
- `_init_frame()`, `_poll_fields()` and `_restore_poll(state)`;
- the requirement that the interrupt-disable flag is bit 2 of `self.p`.

`tests/test_frame.py` subclasses the frame with a toy CPU that has no NMOS
code, so a change to this surface fails here before it breaks a dependent
core. `MOS6502`'s own underscore names (its handlers, `_ea_*`, `_extra`,
`_table`) stay implementation details.

## The tooling: a subclassing surface

`65816-python` reuses the debugger, the trace functions and the console by
subclassing them, as it subclasses the frame. These hooks are public and
semver-covered:

- `StepRecord`'s class attributes `state_type`, `kind_type`,
  `instruction_kind`, `halted_kinds`, `instruction_type`, `access_kinds`,
  `address_mask`, and its static method `decode(data, address)`; a subclass
  is a `@dataclass(frozen=True, slots=True)` that sets them and adds no
  fields. An access kind starts with `"r"` or `"w"` for a read or write, or
  with a letter of the part's own for a cycle that is neither; watchpoints
  match the first letter.
- `DebugSession.record_type` and the methods `boundary(state)`,
  `program_address(state)`, `decode(state)`, `_wrap_bus()` and
  `_unwrap_bus(originals)` (the second gets back the tuple the first stored
  in `_originals`; `_accesses` is the list the wrappers append to).
- `read_trace(stream, record_type=)` and `step_record_from_dict(value,
  record_type=)`; the writers and comparisons read the record's own type.
- `CommandDebugger`'s class attributes `prompt`, `registers`, `help_lines`,
  `call_mnemonics`, and the methods `format_state`, `format_address`,
  `format_instruction`, `format_record`, `format_run`, `disassemble_at` and
  `set_register`.

`tests/test_tooling_hooks.py` holds them with a toy CPU that has 24-bit
addresses, its own state and boundary kinds, and IO cycles.

## Compatibility policy

- Patch releases fix defects without intentional public incompatibilities.
- Minor releases add without breaking, with one exception: before 1.0, a
  minor release may break the public surface when `CHANGELOG.md` says so
  under a **Breaking** heading with the migration. 0.2.0 does this, to take
  the family's shape.
- Fidelity claims stay bounded by docs/validation.md; API stability does not
  extend them.

Development snapshots carry a `.dev0` version and promise nothing.
