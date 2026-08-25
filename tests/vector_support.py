"""Internal helpers for adapting SingleStepTests 6502 vectors."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sixfiveohtwo import CPU, CPUState, IndexRegisters, unpack_status_byte


class VectorValidationError(ValueError):
    """A vector record does not satisfy the SingleStepTests schema."""


@dataclass(frozen=True)
class SingleStepVector:
    name: str
    initial: dict[str, Any]
    final: dict[str, Any]
    cycles: tuple[tuple[int, int, str], ...]
    source: str
    index: int


class VectorMemory:
    """Sparse host memory with an ordered log of bus operations."""

    def __init__(self) -> None:
        self.bytes: dict[int, int] = {}
        self.operations: list[tuple[str, int] | tuple[str, int, int]] = []

    def read_byte(self, address: int) -> int:
        self._address(address)
        self.operations.append(("read", address))
        return self.bytes.get(address, 0)

    def write_byte(self, address: int, value: int) -> None:
        self._address(address)
        self._byte(value, "value")
        self.operations.append(("write", address, value))
        self.bytes[address] = value

    @staticmethod
    def _address(value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("address must be an integer")
        if not 0 <= value <= 0xFFFF:
            raise ValueError("address must fit in 16 bits")

    @staticmethod
    def _byte(value: int, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{name} must fit in 8 bits")

    def reset_operations(self) -> None:
        self.operations.clear()


def _error(source: str, index: int, message: str) -> VectorValidationError:
    return VectorValidationError(f"{source}: record {index}: {message}")


def _mapping(value: Any, label: str, source: str, index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(source, index, f"{label} must be an object")
    return dict(value)


def _integer(value: Any, label: str, source: str, index: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(source, index, f"{label} must be an integer")
    return value


def _bounded(value: Any, label: str, maximum: int, source: str, index: int) -> int:
    value = _integer(value, label, source, index)
    if not 0 <= value <= maximum:
        raise _error(source, index, f"{label} must be between 0 and {maximum}")
    return value


def _ram(value: Any, label: str, source: str, index: int) -> list[tuple[int, int]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _error(source, index, f"{label} must be an array")
    result: list[tuple[int, int]] = []
    for pair_index, pair in enumerate(value):
        if (
            not isinstance(pair, Sequence)
            or isinstance(pair, (str, bytes, bytearray))
            or len(pair) != 2
        ):
            raise _error(
                source, index, f"{label}[{pair_index}] must be [address, value]"
            )
        result.append(
            (
                _bounded(
                    pair[0], f"{label}[{pair_index}] address", 0xFFFF, source, index
                ),
                _bounded(
                    pair[1], f"{label}[{pair_index}] value", 0xFF, source, index
                ),
            )
        )
    return result


def parse_vector_record(
    record: Any, source: str = "<vector>", index: int = 0
) -> SingleStepVector:
    if not isinstance(record, Mapping):
        raise _error(source, index, "record must be an object")
    name = record.get("name")
    if not isinstance(name, str):
        raise _error(source, index, "name must be a string")
    initial = _mapping(record.get("initial"), "initial", source, index)
    final = _mapping(record.get("final"), "final", source, index)
    for section_name, section in (("initial", initial), ("final", final)):
        for key, maximum in (
            ("pc", 0xFFFF),
            ("s", 0xFF),
            ("a", 0xFF),
            ("x", 0xFF),
            ("y", 0xFF),
            ("p", 0xFF),
        ):
            if key not in section:
                raise _error(source, index, f"{section_name}.{key} is required")
            _bounded(section[key], f"{section_name}.{key}", maximum, source, index)
        if "ram" not in section:
            raise _error(source, index, f"{section_name}.ram is required")
        _ram(section["ram"], f"{section_name}.ram", source, index)

    raw_cycles = record.get("cycles")
    if not isinstance(raw_cycles, Sequence) or isinstance(
        raw_cycles, (str, bytes, bytearray)
    ):
        raise _error(source, index, "cycles must be an array")
    cycles: list[tuple[int, int, str]] = []
    for cycle_index, cycle in enumerate(raw_cycles):
        if (
            not isinstance(cycle, Sequence)
            or isinstance(cycle, (str, bytes, bytearray))
            or len(cycle) != 3
        ):
            raise _error(
                source,
                index,
                f"cycles[{cycle_index}] must be [address, value, direction]",
            )
        address = _bounded(
            cycle[0], f"cycles[{cycle_index}] address", 0xFFFF, source, index
        )
        value = _bounded(
            cycle[1], f"cycles[{cycle_index}] value", 0xFF, source, index
        )
        direction = cycle[2]
        if direction not in ("read", "write"):
            raise _error(
                source,
                index,
                f"cycles[{cycle_index}] direction must be 'read' or 'write'",
            )
        cycles.append((address, value, direction))
    return SingleStepVector(name, initial, final, tuple(cycles), source, index)


def load_vector_file(path: str | Path) -> list[SingleStepVector]:
    source = str(path)
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise VectorValidationError(
            f"{source}: unable to read JSON: {error}"
        ) from error
    if not isinstance(payload, list):
        raise VectorValidationError(
            f"{source}: vector file must contain an array"
        )
    return [
        parse_vector_record(record, source, index)
        for index, record in enumerate(payload)
    ]


def adapt_vector(vector: SingleStepVector) -> tuple[CPU, VectorMemory]:
    """Construct a CPU and memory initialized from one validated vector."""
    initial = vector.initial
    memory = VectorMemory()
    for address, value in _ram(
        initial["ram"], "initial.ram", vector.source, vector.index
    ):
        memory.write_byte(address, value)
    memory.reset_operations()
    state = CPUState(
        accumulator=initial["a"],
        index=IndexRegisters(x=initial["x"], y=initial["y"]),
        program_counter=initial["pc"],
        stack_pointer=initial["s"],
        status=unpack_status_byte(initial["p"]),
        cycles=0,
    )
    return CPU(memory, state=state), memory
