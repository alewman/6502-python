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

## Compatibility policy

- Patch releases fix defects without intentional public incompatibilities.
- Minor releases add without breaking, with one exception: before 1.0, a
  minor release may break the public surface when `CHANGELOG.md` says so
  under a **Breaking** heading with the migration. 0.2.0 does this, to take
  the family's shape.
- Fidelity claims stay bounded by docs/validation.md; API stability does not
  extend them.

Development snapshots carry a `.dev0` version and promise nothing.
