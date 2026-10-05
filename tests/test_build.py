import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_wheel_build_uses_hatchling_without_runtime_dependencies(tmp_path):
    wheel_directory = tmp_path / "wheel"
    wheel_directory.mkdir()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--wheel-dir",
            str(wheel_directory),
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    wheels = list(wheel_directory.glob("*.whl"))
    assert len(wheels) == 1

    with ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = wheel.read(metadata_name).decode("utf-8")

    assert "sixfiveohtwo/__init__.py" in names
    # Optional extras carry an `extra ==` marker; unmarked entries install at runtime.
    runtime_requirements = [
        line
        for line in metadata.splitlines()
        if line.startswith("Requires-Dist:") and "extra ==" not in line
    ]
    assert runtime_requirements == []
    assert "Provides-Extra: dev" in metadata
