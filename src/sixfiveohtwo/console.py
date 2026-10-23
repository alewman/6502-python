"""Portable command debugger built as a thin frontend over DebugSession.

``CommandDebugger.execute(line)`` runs one command and returns printable lines;
``interact(input, output)`` is a line-oriented loop with no terminal
dependencies. ``python -m sixfiveohtwo`` starts one on a binary. The command set
is z80-python's, with 6502 registers and interrupt inputs.

A core for another 65xx-family part subclasses :class:`CommandDebugger` over
its own :class:`~sixfiveohtwo.debug.DebugSession` subclass and overrides the
hooks below the class docstring (prompt, registers, state and address text,
disassembly, the subroutine calls ``over`` runs through).
"""

import shlex
from dataclasses import dataclass
from typing import Any, ClassVar, TextIO

from sixfiveohtwo.debug import DebugSession, RunResult, StepRecord, StopReason
from sixfiveohtwo.disasm import ByteReader, Instruction, disassemble
from sixfiveohtwo.state import CPUState


class CommandError(ValueError):
    """A malformed or unsupported debugger command."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Rendered lines and control state returned by one debugger command."""

    lines: tuple[str, ...] = ()
    quit: bool = False

    def __post_init__(self) -> None:
        if type(self.lines) is not tuple or not all(type(line) is str for line in self.lines):
            raise ValueError("lines must be a tuple of strings")
        if type(self.quit) is not bool:
            raise ValueError("quit must be a bool")


_HELP = (
    "help | ?                     Show this command summary",
    "registers | regs | r         Show CPU registers and lifecycle state",
    "step [COUNT] | s             Execute one or more boundaries (ignores breakpoints)",
    "over | o                     Step, running a JSR through to its return",
    "run STEPS [CYCLES]           Run with finite step and optional cycle limits",
    "continue | c                 Run up to 1,000,000 steps, off a breakpoint if on one",
    "break ADDRESS | b            Add an execute breakpoint",
    "delete ADDRESS               Remove an execute breakpoint",
    "breakpoints                  List breakpoints and watchpoints",
    "watch ADDRESS [r|w|rw]       Stop after a step that touches the byte at ADDRESS",
    "unwatch ADDRESS              Remove a watchpoint",
    "disassemble [ADDRESS] [COUNT] | d  Decode instructions without side effects",
    "memory ADDRESS [LENGTH] | m  Display up to 256 bytes",
    "history [COUNT]              Show retained step records",
    "set REGISTER VALUE           Set A X Y S P PC",
    "irq on | irq off             Assert or release the IRQ line (a level)",
    "nmi | reset                  Latch an NMI edge, or run the reset sequence",
    "quit | exit | q              Leave the command loop",
    "Numbers are decimal; 0x1234 or $1234 is hexadecimal.",
)

#: Registers ``set`` accepts, with their widths.
_REGISTERS = {"A": 0xFF, "X": 0xFF, "Y": 0xFF, "S": 0xFF, "P": 0xFF, "PC": 0xFFFF}


def _number(text: str, name: str, *, maximum: int | None = None) -> int:
    try:
        value = int(text[1:], 16) if text.startswith("$") else int(text, 0)
    except ValueError as exc:
        raise CommandError(f"{name} must be an integer") from exc
    if value < 0 or (maximum is not None and value > maximum):
        suffix = f" in range 0..{maximum}" if maximum is not None else " non-negative"
        raise CommandError(f"{name} must be{suffix}")
    return value


def parse_number(text: str, name: str = "value", *, maximum: int | None = None) -> int:
    """Parse a debugger number: decimal, or hexadecimal written ``0x1234`` or ``$1234``."""
    return _number(text, name, maximum=maximum)


def _positive(text: str, name: str, *, maximum: int | None = None) -> int:
    value = _number(text, name, maximum=maximum)
    if value == 0:
        raise CommandError(f"{name} must be positive")
    return value


def _flags(value: int) -> str:
    labels = "NV-BDIZC"
    return "".join(label if value & (0x80 >> index) else "-" for index, label in enumerate(labels))


def _format_state(state: CPUState) -> tuple[str, ...]:
    polled = "-" if state.polled_i is None else str(int(state.polled_i))
    seen = "".join(
        f" POLLED_{name}={'-' if value is None else int(value)}"
        for name, value in (
            ("NMI", state.polled_non_maskable_interrupt),
            ("IRQ", state.polled_maskable_interrupt),
        )
        if value is not None
    )
    skipped = " NO_POLL" if state.skipped_poll else ""
    return (
        f"PC={state.pc:04X} A={state.a:02X} X={state.x:02X} Y={state.y:02X} "
        f"S={state.s:02X} P={state.p:02X} {_flags(state.p)}",
        f"JAM={int(state.halted)} RESET={int(state.reset_pending)} "
        f"NMI={int(state.non_maskable_interrupt_pending)} "
        f"IRQ={int(state.maskable_interrupt_pending)} POLLED_I={polled}{seen}{skipped}",
    )


_ALIASES = {
    "?": "help",
    "r": "registers",
    "s": "step",
    "o": "over",
    "c": "continue",
    "b": "break",
    "d": "disassemble",
    "m": "memory",
    "q": "quit",
}


class CommandDebugger:
    """Parse and execute portable debugger commands against a DebugSession."""

    #: The prompt :meth:`interact` shows.
    prompt: ClassVar[str] = "6502> "
    #: Registers ``set`` accepts, with their largest values.
    registers: ClassVar[dict[str, int]] = _REGISTERS
    #: The help text.
    help_lines: ClassVar[tuple[str, ...]] = _HELP
    #: Mnemonics ``over`` runs through to their return.
    call_mnemonics: ClassVar[frozenset[str]] = frozenset(("JSR",))

    def __init__(self, session: DebugSession) -> None:
        if not isinstance(session, DebugSession):
            raise TypeError("session must be a DebugSession")
        self.session = session
        self.address_mask = session.record_type.address_mask

    # -- hooks a subclass for another part overrides ----------------------

    def format_state(self, state: Any) -> tuple[str, ...]:
        """The lines ``registers`` prints."""
        return _format_state(state)

    def format_address(self, address: int) -> str:
        return f"{address:04X}" if self.address_mask <= 0xFFFF else f"{address:06X}"

    def disassemble_at(self, peek: ByteReader, address: int, state: Any) -> Instruction:
        """The instruction at ``address``, decoded as the CPU in ``state`` would."""
        return disassemble(peek, address)

    def set_register(self, name: str, value: int) -> None:
        """Set register ``name`` (a key of :attr:`registers`) on the CPU."""
        if name == "P":
            value = (value | 0x20) & ~0x10  # bit 5 reads as 1; B is not a flip-flop
        setattr(self.session.cpu, name.lower(), value)

    def format_instruction(self, instruction: Instruction) -> str:
        encoded = " ".join(f"{value:02X}" for value in instruction.data)
        return f"{self.format_address(instruction.address)}  {encoded:<11}  {instruction.text}"

    def format_record(self, record: StepRecord) -> str:
        session = self.session
        if record.instruction is not None:
            work = self.format_instruction(record.instruction)
        else:
            before = self.format_address(session.program_address(record.before))
            work = f"{before}  {record.kind.value}"
        after = self.format_address(session.program_address(record.after))
        return f"#{record.sequence} {work} -> PC={after} +{record.cycles}"

    def format_run(self, result: RunResult) -> str:
        line = (
            f"stopped={result.reason.value} steps={result.steps} "
            f"instructions={result.instructions} cycles={result.cycles} "
            f"PC={self.format_address(self.session.program_address(result.state))}"
        )
        if result.reason is StopReason.WATCHPOINT:
            line += " " + " ".join(
                f"{kind} {self.format_address(address)}={value:02X}"
                for kind, address, value in result.hits
            )
        return line

    # -- commands ---------------------------------------------------------

    def execute(self, command: str) -> CommandResult:
        """Execute one command and return deterministic printable lines."""

        if type(command) is not str:
            raise TypeError("command must be a string")
        try:
            words = shlex.split(command)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        if not words:
            return CommandResult()

        name, *arguments = words
        name = _ALIASES.get(name.lower(), name.lower())
        if name in ("quit", "exit"):
            self._arity(name, arguments, 0)
            return CommandResult(quit=True)
        if name == "help":
            self._arity(name, arguments, 0)
            return CommandResult(self.help_lines)
        if name in ("registers", "regs"):
            self._arity(name, arguments, 0)
            return CommandResult(self.format_state(self.session.target.capture_state()))
        if name == "step":
            return self._step(arguments)
        if name == "over":
            return self._over(arguments)
        if name == "run":
            return self._run(arguments)
        if name == "continue":
            return self._continue(arguments)
        if name == "watch":
            self._arity(name, arguments, 1, 2)
            address = _number(arguments[0], "address", maximum=self.address_mask)
            kind = arguments[1].lower() if len(arguments) == 2 else "rw"
            try:
                self.session.add_watchpoint(address, kind)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            return CommandResult((f"watchpoint added at {self.format_address(address)} ({kind})",))
        if name == "unwatch":
            self._arity(name, arguments, 1)
            address = _number(arguments[0], "address", maximum=self.address_mask)
            self.session.remove_watchpoint(address)
            return CommandResult((f"watchpoint removed from {self.format_address(address)}",))
        if name == "set":
            return self._set(arguments)
        if name == "irq":
            return self._interrupt(arguments)
        if name == "nmi":
            self._arity(name, arguments, 0)
            self.session.cpu.request_non_maskable_interrupt()
            return CommandResult(("NMI latched; taken at the next step",))
        if name == "reset":
            self._arity(name, arguments, 0)
            self.session.cpu.request_reset()
            record = self.session.step()
            return CommandResult(
                (
                    self.format_record(record),
                    *self.format_state(self.session.target.capture_state()),
                )
            )
        if name == "break":
            self._arity(name, arguments, 1)
            address = _number(arguments[0], "address", maximum=self.address_mask)
            self.session.add_breakpoint(address)
            return CommandResult((f"breakpoint added at {self.format_address(address)}",))
        if name == "delete":
            self._arity(name, arguments, 1)
            address = _number(arguments[0], "address", maximum=self.address_mask)
            self.session.remove_breakpoint(address)
            return CommandResult((f"breakpoint removed from {self.format_address(address)}",))
        if name == "breakpoints":
            self._arity(name, arguments, 0)
            lines = tuple(self.format_address(a) for a in sorted(self.session.breakpoints))
            lines += tuple(
                f"watch {self.format_address(address)} {kind}"
                for address, kind in sorted(self.session.watchpoints.items())
            )
            return CommandResult(lines or ("no breakpoints",))
        if name in ("disassemble", "disasm"):
            return self._disassemble(arguments)
        if name == "memory":
            return self._memory(arguments)
        if name == "history":
            return self._history(arguments)
        raise CommandError(f"unknown command: {name}")

    def interact(
        self,
        input_stream: TextIO,
        output_stream: TextIO,
        *,
        prompt: str | None = None,
    ) -> None:
        """Run a line-oriented debugger loop over supplied text streams."""

        prompt = self.prompt if prompt is None else prompt
        while True:
            output_stream.write(prompt)
            output_stream.flush()
            line = input_stream.readline()
            if line == "":
                return
            try:
                result = self.execute(line)
            except CommandError as exc:
                output_stream.write(f"error: {exc}\n")
                continue
            for rendered in result.lines:
                output_stream.write(f"{rendered}\n")
            if result.quit:
                return

    def _step(self, arguments: list[str]) -> CommandResult:
        self._arity("step", arguments, 0, 1)
        count = _positive(arguments[0], "count", maximum=10_000) if arguments else 1
        records = tuple(self.session.step() for _ in range(count))
        return CommandResult(tuple(self.format_record(record) for record in records))

    def _over(self, arguments: list[str]) -> CommandResult:
        self._arity("over", arguments, 0)
        session = self.session
        state = session.target.capture_state()
        pc = session.program_address(state)
        instruction = self.disassemble_at(self._require_peek(), pc, state)
        if instruction.mnemonic not in self.call_mnemonics:
            return self._step([])
        # Run the subroutine through: stop when control is back at the
        # instruction after the JSR with the stack where it was.
        lines = [self.format_record(session.step())]
        for _ in range(1_000_000):
            now = session.target.capture_state()
            now_pc = session.program_address(now)
            if now_pc == instruction.next_address and now.s == state.s:
                break
            if now_pc in session.breakpoints:
                lines.append(f"breakpoint at {self.format_address(now_pc)}")
                break
            result = session.run(max_steps=1, stop_on_halt=False)
            if result.reason is not StopReason.STEP_LIMIT:
                lines.append(self.format_run(result))
                break
        else:
            lines.append("gave up after 1,000,000 steps")
        return CommandResult((*lines, *self.format_state(session.target.capture_state())))

    def _continue(self, arguments: list[str]) -> CommandResult:
        self._arity("continue", arguments, 0)
        steps = 1_000_000
        lines = []
        # run() stops before a breakpoint without moving, so step off one first.
        session = self.session
        if session.program_address(session.target.capture_state()) in session.breakpoints:
            lines.append(self.format_record(session.step()))
            steps -= 1
        lines.append(self.format_run(session.run(max_steps=steps)))
        return CommandResult(tuple(lines))

    def _set(self, arguments: list[str]) -> CommandResult:
        self._arity("set", arguments, 2)
        register = arguments[0].upper()
        if register not in self.registers:
            raise CommandError(f"no register {register}; set takes {' '.join(self.registers)}")
        value = _number(arguments[1], register, maximum=self.registers[register])
        self.set_register(register, value)
        return CommandResult(self.format_state(self.session.cpu.capture_state()))

    def _interrupt(self, arguments: list[str]) -> CommandResult:
        self._arity("irq", arguments, 1)
        cpu = self.session.cpu
        level = arguments[0].lower()
        if level == "off":
            cpu.clear_maskable_interrupt()
            return CommandResult(("IRQ released",))
        if level != "on":
            raise CommandError("irq takes on or off")
        cpu.request_maskable_interrupt()
        return CommandResult(("IRQ asserted; it stays asserted until irq off",))

    def _run(self, arguments: list[str]) -> CommandResult:
        self._arity("run", arguments, 1, 2)
        steps = _positive(arguments[0], "steps")
        cycles = _positive(arguments[1], "cycles") if len(arguments) == 2 else None
        result = self.session.run(max_steps=steps, max_cycles=cycles)
        return CommandResult((self.format_run(result),))

    def _disassemble(self, arguments: list[str]) -> CommandResult:
        self._arity("disassemble", arguments, 0, 2)
        peek = self._require_peek()
        state = self.session.target.capture_state()
        address = (
            _number(arguments[0], "address", maximum=self.address_mask)
            if arguments
            else self.session.program_address(state)
        )
        count = _positive(arguments[1], "count", maximum=256) if len(arguments) == 2 else 8
        instructions = []
        for _ in range(count):
            instruction = self.disassemble_at(peek, address, state)
            instructions.append(instruction)
            address = instruction.next_address
        return CommandResult(tuple(self.format_instruction(item) for item in instructions))

    def _memory(self, arguments: list[str]) -> CommandResult:
        self._arity("memory", arguments, 1, 2)
        peek = self._require_peek()
        mask = self.address_mask
        address = _number(arguments[0], "address", maximum=mask)
        length = _positive(arguments[1], "length", maximum=256) if len(arguments) == 2 else 16
        lines = []
        for offset in range(0, length, 16):
            row_address = (address + offset) & mask
            row_length = min(16, length - offset)
            values = [
                self._read_peek(peek, (row_address + column) & mask) for column in range(row_length)
            ]
            text = " ".join(f"{value:02X}" for value in values)
            lines.append(f"{self.format_address(row_address)}  {text}")
        return CommandResult(tuple(lines))

    def _history(self, arguments: list[str]) -> CommandResult:
        self._arity("history", arguments, 0, 1)
        count = _positive(arguments[0], "count", maximum=10_000) if arguments else 16
        records = self.session.history[-count:]
        lines = tuple(self.format_record(record) for record in records)
        return CommandResult(lines or ("history empty",))

    def _require_peek(self) -> ByteReader:
        if self.session.peek_byte is None:
            raise CommandError("this session has no side-effect-free peek capability")
        return self.session.peek_byte

    @staticmethod
    def _read_peek(peek: ByteReader, address: int) -> int:
        value = peek(address)
        if type(value) is not int or not 0 <= value <= 0xFF:
            raise CommandError(f"peek returned a non-byte value at {address:04X}")
        return value

    @staticmethod
    def _arity(name: str, arguments: list[str], minimum: int, maximum: int | None = None) -> None:
        maximum = minimum if maximum is None else maximum
        if not minimum <= len(arguments) <= maximum:
            expected = str(minimum) if minimum == maximum else f"{minimum}..{maximum}"
            raise CommandError(f"{name} expects {expected} argument(s)")


__all__ = ["CommandDebugger", "CommandError", "CommandResult", "parse_number"]
