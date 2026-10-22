# Public API stability

`6502-python` uses semantic versioning for the names exported from the package
root and listed in each public module's `__all__`: `MOS6502` and its
constructor `MOS6502(read_byte, write_byte)`, the flag constants, `CPUState`,
`Instruction` and the disassembly functions, `DebugSession` and its values,
`next_boundary`, `CommandDebugger`, the trace functions and values, and the
`python -m sixfiveohtwo` command line. The package ships `py.typed`.

Underscore-prefixed modules and names are implementation details. The CPU's
register attributes (`a`, `x`, `y`, `s`, `pc`, `p`) and bus attributes
(`read_byte`, `write_byte`) are public and writable.

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
- `_init_frame()`, `_poll_fields()` and `_restore_poll(state)`;
- the requirement that the interrupt-disable flag is bit 2 of `self.p`.

`tests/test_frame.py` subclasses the frame with a toy CPU that has no NMOS
code, so a change to this surface fails here before it breaks a dependent
core. `MOS6502`'s own underscore names (its handlers, `_ea_*`, `_extra`,
`_table`) stay implementation details.

## Compatibility policy

- Patch releases fix defects without intentional public incompatibilities.
- Minor releases add without breaking, with one exception: before 1.0, a
  minor release may break the public surface when `CHANGELOG.md` says so
  under a **Breaking** heading with the migration. 0.2.0 does this, to take
  the family's shape.
- Fidelity claims stay bounded by docs/validation.md; API stability does not
  extend them.

Development snapshots carry a `.dev0` version and promise nothing.
