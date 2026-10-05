"""``python -m sixfiveohtwo``: load images, pick a start, run -c commands, reject bad specs."""

import io
import subprocess
import sys
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from sixfiveohtwo.__main__ import main

# LDA #$55; STA $10; JAM
PROGRAM = bytes((0xA9, 0x55, 0x85, 0x10, 0x02))


def _run(*argv: str) -> str:
    output = io.StringIO()
    with redirect_stdout(output):
        main(list(argv))
    return output.getvalue()


def _image(tmp_path: Path, data: bytes = PROGRAM, name: str = "program.bin") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_load_pc_and_batch_commands(tmp_path: Path) -> None:
    image = _image(tmp_path)
    text = _run(
        "--load", f"{image}@0x0200", "--pc", "$200", "--batch", "-c", "step 2", "-c", "m 0x10 1"
    )
    lines = text.splitlines()
    assert lines[:3] == [
        "6502> registers",
        "PC=0200 A=00 X=00 Y=00 S=00 P=24 -----I--",
        "JAM=0 RESET=0 NMI=0 IRQ=0 POLLED_I=-",
    ]
    assert "6502> disassemble" in lines
    assert "0200  A9 55        LDA #$55" in lines
    assert "0204  02           JAM" in lines
    assert "#1 0202  85 10        STA $10 -> PC=0204 +3" in lines
    assert lines[-2:] == ["6502> m 0x10 1", "0010  55"]


def test_access_tracking_lets_watch_stop_a_run(tmp_path: Path) -> None:
    image = _image(tmp_path)
    text = _run("--load", f"{image}@512", "--pc", "512", "--batch", "-c", "watch 0x10", "-c", "c")
    assert text.splitlines()[-1] == (
        "stopped=watchpoint steps=2 instructions=2 cycles=5 PC=0204 w 0010=55"
    )


def test_reset_starts_through_the_reset_vector(tmp_path: Path) -> None:
    program = _image(tmp_path)
    vector = _image(tmp_path, bytes((0x00, 0x03)), "vector.bin")
    text = _run("--load", f"{program}@0x0300", "--load", f"{vector}@0xFFFC", "--reset", "--batch")
    assert text.splitlines()[1].startswith("PC=0300 ")
    assert "0300  A9 55        LDA #$55" in text


def test_zip_member_loads_like_a_file(tmp_path: Path) -> None:
    archive = tmp_path / "set.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("rom.bin", PROGRAM)
    text = _run("--zip", f"{archive}:rom.bin@0xF000", "--pc", "0xF000", "--batch")
    assert "F000  A9 55        LDA #$55" in text


def test_command_errors_are_printed_and_quit_stops(tmp_path: Path) -> None:
    image = _image(tmp_path)
    text = _run("--load", f"{image}@0", "--batch", "-c", "bogus", "-c", "quit", "-c", "step")
    lines = text.splitlines()
    assert "error: unknown command: bogus" in lines
    assert lines[-1] == "6502> quit"


def test_without_batch_the_prompt_reads_stdin(tmp_path: Path, monkeypatch) -> None:
    image = _image(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO("s\n"))
    text = _run("--load", f"{image}@0")
    assert text.endswith("6502> #0 0000  A9 55        LDA #$55 -> PC=0002 +2\n6502> ")


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--load", "{image}"], "FILE@ADDRESS"),
        (["--load", "{image}@0x10000"], "load address"),
        (["--load", "{image}@later"], "load address"),
        (["--load", "{image}@0xFFFE"], "do not fit"),
        (["--zip", "{image}@0"], "ZIPFILE:MEMBER@ADDRESS"),
        (["--pc", "0x10000"], "--pc"),
    ],
)
def test_bad_specs_exit_with_a_message(tmp_path: Path, argv: list[str], message: str) -> None:
    image = _image(tmp_path)
    argv = [argument.format(image=image) for argument in argv]
    with pytest.raises(SystemExit, match=message):
        _run(*argv, "--batch")


def test_the_module_runs_as_a_program(tmp_path: Path) -> None:
    image = _image(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-m", "sixfiveohtwo", "--load", f"{image}@0", "--batch", "-c", "s"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "#0 0000  A9 55        LDA #$55 -> PC=0002 +2" in completed.stdout
