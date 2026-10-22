"""The frame of a 65xx-family core: bus, interrupt requests, the poll and ``step()``.

:class:`MOS6502` is this frame plus the NMOS instruction set. A core for
another member of the family (the 65C816 in ``65816-python``) subclasses
:class:`CPUFrame` itself, not :class:`MOS6502`, and so inherits none of the
NMOS handlers; it gets what is chip-independent and easy to get subtly wrong:

- the two bus callables, replaceable at any time (the debugger does);
- the interrupt request API and the poll: requests are sampled at the end of
  an instruction's second-to-last cycle, so a bus callback that changes one
  during the last cycle is seen one instruction later (NESdev, "CPU
  interrupts", "Detailed interrupt behavior"); CLI, SEI and PLP change I
  after their poll (``_polled_i``); BRK, interrupt entries and reset do not
  poll (``NO_POLL``);
- ``step()``'s skeleton: a pending reset, a halted CPU, the interrupt the
  boundary takes, or one instruction.

The subclassing surface, covered by docs/api-stability.md:

- implement ``_accept_reset()``, ``_halted()``, ``_enter_interrupt(kind)``
  and ``_execute()``, each returning the cycles it took; ``kind`` is
  :data:`NMI_LATCH` or :data:`IRQ_LINE`;
- make every bus access through ``self._read(address)`` and
  ``self._write(address, value)``, which are the host's callables or the
  confirming wrappers; an additional kind of cycle (an IO cycle) confirms by
  calling ``self._confirm()`` when ``self._deferred is not None``;
- keep the interrupt-disable flag in bit 2 of ``self.p`` (both parts do);
- an extra request (an ABORT input) is a further bit of ``_requests`` set
  through ``_request``, taken by overriding ``_boundary_interrupt``;
- a state snapshot includes :meth:`_poll_fields` and is restored with
  :meth:`_restore_poll`.
"""

from typing import Any

from sixfiveohtwo._core import IRQ_LINE, NMI_LATCH, NO_POLL, I, ReadByte, WriteByte

_BUS = ("read_byte", "write_byte")


class CPUFrame:
    """Bus callables, interrupt requests and their poll, and the step skeleton.

    Not a CPU on its own: :class:`~sixfiveohtwo.MOS6502` and other cores
    subclass it and implement the four hooks ``step()`` calls.
    """

    halted: bool

    def __init__(self, read_byte: ReadByte, write_byte: WriteByte) -> None:
        for name, bus in zip(_BUS, (read_byte, write_byte), strict=True):
            if not callable(bus):
                hint = ""
                if callable(getattr(bus, name, None)):
                    # Until 0.2.0 the CPU took one object with both methods.
                    cls = type(self).__name__
                    hint = f"; since 0.2.0 pass the methods: {cls}(bus.read_byte, bus.write_byte)"
                raise TypeError(f"{name} must be callable, not {type(bus).__name__}{hint}")
        self._init_frame()
        self.read_byte = read_byte
        self.write_byte = write_byte

    def _init_frame(self) -> None:
        # Interrupt inputs (docs/start-here.md, "Reset and interrupts").
        self._reset_pending = False
        self._requests = 0  # IRQ_LINE | NMI_LATCH, as the host has set them
        # The chip polls its interrupt detectors in an instruction's last
        # cycle, so what counts is the requests as they stood at the end of
        # the second-to-last cycle (NESdev, "CPU interrupts", "Detailed
        # interrupt behavior"). Usually that is the requests as they stand,
        # and _polled is None. It holds what the poll saw instead, for the
        # next boundary only, when that differs: a bus callback changed a
        # request in the last cycle, too late (_deferred, see _request), or
        # the step was BRK, an interrupt entry or reset, which do not poll
        # (NO_POLL). A request the host makes between steps is taken at the
        # next boundary, unless that step did not poll.
        self._polled: int | None = None
        self._deferred: int | None = None
        # CLI, SEI and PLP change I after the chip has polled for interrupts,
        # so the next boundary decides on the old I. None: poll P as it is.
        self._polled_i: int | None = None
        # The CPU has stopped (JAM on the NMOS part); _halted() decides what
        # a step does until reset.
        self.halted = False

    # -- the bus ---------------------------------------------------------

    @property
    def read_byte(self) -> ReadByte:
        """The host's ``read_byte(address)``, as passed in or last assigned."""
        return self._read_byte

    @read_byte.setter
    def read_byte(self, read_byte: ReadByte) -> None:
        self._read_byte = read_byte
        if self._deferred is None:
            self._read = read_byte

    @property
    def write_byte(self) -> WriteByte:
        """The host's ``write_byte(address, value)``, as passed in or last assigned."""
        return self._write_byte

    @write_byte.setter
    def write_byte(self, write_byte: WriteByte) -> None:
        self._write_byte = write_byte
        if self._deferred is None:
            self._write = write_byte

    # -- interrupt requests ------------------------------------------------

    def _request(self, requests: int) -> None:
        """Change the requests, and arrange to learn whether a bus access follows.

        The first change since the last access keeps the requests from
        before it in _deferred and routes the next access through
        _confirm. If that access comes in the same step, the change was
        before the last cycle and the poll sees it; if the step ends first,
        the poll saw _deferred. Accesses cost nothing extra otherwise.
        """
        if self._deferred is None:
            self._deferred = self._requests
            self._read = self._read_confirming
            self._write = self._write_confirming
        self._requests = requests

    def _confirm(self) -> None:
        self._deferred = None
        self._read = self._read_byte
        self._write = self._write_byte

    def _read_confirming(self, address: int) -> int:
        self._confirm()
        return self._read_byte(address)

    def _write_confirming(self, address: int, value: int) -> None:
        self._confirm()
        self._write_byte(address, value)

    # -- the step --------------------------------------------------------

    def step(self) -> int:
        """Execute one instruction, interrupt entry or reset; return its cycle count.

        At an instruction boundary: a pending reset runs the start sequence; a
        halted CPU does what its part does while stopped; an NMI the last
        instruction's poll saw is taken; so is an IRQ it saw, if the I flag
        that poll saw is clear; otherwise one instruction runs.

        The poll sees the requests as they stood at the end of the
        instruction's second-to-last cycle, so one a bus callback makes
        during the last cycle waits for the next instruction's poll. One the
        host makes between steps is taken at the next boundary. BRK,
        interrupt entries and reset do not poll: one instruction runs after
        them before anything requested since is taken.
        """
        if self._reset_pending:
            return self._accept_reset()
        if self.halted:
            return self._halted()
        # Nothing requested, nothing remembered: no interrupt to decide (the
        # usual boundary, so it skips the call).
        if self._requests or self._polled is not None or self._polled_i is not None:
            taken = self._boundary_interrupt()
            if taken:
                return self._enter_interrupt(taken)
        cycles = self._execute()
        deferred = self._deferred
        if deferred is not None:
            # A bus callback changed a request in the last cycle, after the poll.
            self._polled = deferred
            self._deferred = None
        return cycles

    def _boundary_interrupt(self) -> int:
        """The interrupt this boundary takes: NMI_LATCH, IRQ_LINE, or 0 for none."""
        polled = self._polled
        if polled is None:
            polled = self._requests
        else:
            self._polled = None
        if polled & NMI_LATCH:
            return NMI_LATCH
        polled_i = self._polled_i
        if polled_i is None:
            if polled & IRQ_LINE and not self.p & I:
                return IRQ_LINE
        else:
            self._polled_i = None
            if polled & IRQ_LINE and not polled_i:
                return IRQ_LINE
        return 0

    # The part's own sequences; each returns the cycles it took.

    def _accept_reset(self) -> int:
        raise NotImplementedError

    def _halted(self) -> int:
        raise NotImplementedError

    def _enter_interrupt(self, kind: int) -> int:
        raise NotImplementedError

    def _execute(self) -> int:
        raise NotImplementedError

    # -- interrupt and reset inputs ------------------------------------

    @property
    def reset_pending(self) -> bool:
        """Whether a reset has been requested and not yet run."""
        return self._reset_pending

    def request_reset(self) -> None:
        """Run the start sequence at the next boundary.

        The start sequence begins when RESET is released (PM section 9.2), so
        one request is one reset, whenever the host's board releases the line.
        Reset has priority over everything, and restarts a halted CPU.
        """
        self._reset_pending = True

    def clear_reset(self) -> None:
        """Cancel a requested reset that has not yet reached a boundary."""
        self._reset_pending = False

    @property
    def maskable_interrupt_pending(self) -> bool:
        """Whether the IRQ line is asserted."""
        return bool(self._requests & IRQ_LINE)

    def request_maskable_interrupt(self) -> None:
        """Assert IRQ, a level: it stays asserted until :meth:`clear_maskable_interrupt`.

        Taking the interrupt does not clear it; on a board the device holds
        IRQ low until its handler acknowledges it, and so must the host. While
        it is asserted and I is clear, every poll takes the interrupt.
        """
        self._request(self._requests | IRQ_LINE)
        polled = self._polled
        if polled is not None and not polled & NO_POLL:
            self._polled = polled | IRQ_LINE

    def clear_maskable_interrupt(self) -> None:
        """Release IRQ."""
        self._request(self._requests & ~IRQ_LINE)
        if self._polled is not None:
            self._polled &= ~IRQ_LINE

    @property
    def non_maskable_interrupt_pending(self) -> bool:
        """Whether an NMI edge has been latched and not yet taken."""
        return bool(self._requests & NMI_LATCH)

    def request_non_maskable_interrupt(self) -> None:
        """Latch an NMI edge; the next poll takes it, whatever I says.

        NMI is edge-triggered: call this on the line's falling edge. Requests
        made while one is pending coalesce into one NMI.
        """
        self._request(self._requests | NMI_LATCH)
        polled = self._polled
        if polled is not None and not polled & NO_POLL:
            self._polled = polled | NMI_LATCH

    def clear_non_maskable_interrupt(self) -> None:
        """Cancel a latched NMI that has not yet been taken, even one already polled."""
        self._request(self._requests & ~NMI_LATCH)
        if self._polled is not None:
            self._polled &= ~NMI_LATCH

    # -- state -----------------------------------------------------------

    def _poll_fields(self) -> dict[str, Any]:
        """The frame's part of a state snapshot, as keyword arguments."""
        polled_i = self._polled_i
        polled = self._requests if self._polled is None else self._polled
        return {
            "halted": self.halted,
            "reset_pending": self._reset_pending,
            "maskable_interrupt_pending": bool(self._requests & IRQ_LINE),
            "non_maskable_interrupt_pending": bool(self._requests & NMI_LATCH),
            "polled_i": None if polled_i is None else bool(polled_i),
            "polled_maskable_interrupt": _differs(polled, self._requests, IRQ_LINE),
            "polled_non_maskable_interrupt": _differs(polled, self._requests, NMI_LATCH),
            "skipped_poll": bool(polled & NO_POLL),
        }

    def _restore_poll(self, state: Any) -> None:
        """Restore the fields :meth:`_poll_fields` captured, from any object that has them."""
        self.halted = state.halted
        self._reset_pending = state.reset_pending
        self._requests = (IRQ_LINE if state.maskable_interrupt_pending else 0) | (
            NMI_LATCH if state.non_maskable_interrupt_pending else 0
        )
        polled = self._requests
        for bit, seen in (
            (IRQ_LINE, state.polled_maskable_interrupt),
            (NMI_LATCH, state.polled_non_maskable_interrupt),
        ):
            if seen is not None:
                polled = polled | bit if seen else polled & ~bit
        if state.skipped_poll:
            polled |= NO_POLL
        self._polled = None if polled == self._requests else polled
        self._confirm()
        self._polled_i = None if state.polled_i is None else (I if state.polled_i else 0)


def _differs(polled: int, requests: int, bit: int) -> bool | None:
    """What the poll saw of ``bit`` when that is not what the host has requested, else None."""
    seen = bool(polled & bit)
    return None if seen == bool(requests & bit) else seen


# The request bits are exported for a subclass's own request inputs and its
# ``_enter_interrupt``.
__all__ = ["IRQ_LINE", "NMI_LATCH", "NO_POLL", "CPUFrame"]
