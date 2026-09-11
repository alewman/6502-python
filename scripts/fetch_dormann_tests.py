"""Fetch and, when possible, build the pinned Dormann 6502 exercisers."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

FUNCTIONAL_REPOSITORY_URL = "https://github.com/Klaus2m5/6502_65C02_functional_tests"
FUNCTIONAL_REVISION = "7954e2dbb49c469ea286070bf46cdd71aeb29e4b"
FUNCTIONAL_ARCHIVE_URL = (
    f"{FUNCTIONAL_REPOSITORY_URL}/archive/{FUNCTIONAL_REVISION}.tar.gz"
)
FUNCTIONAL_MEMBER = "bin_files/6502_functional_test.bin"
FUNCTIONAL_SHA256 = "fa12bfc761e6f9057e4cc01a665a7b800ff01ae91f598af1e39a1201d01953fd"

DECIMAL_REPOSITORY_URL = "https://github.com/amb5l/6502_65C02_functional_tests"
DECIMAL_REVISION = "966b1a35049f9d8be44ad092ec6d43d5ba1831b3"
DECIMAL_ARCHIVE_URL = f"{DECIMAL_REPOSITORY_URL}/archive/{DECIMAL_REVISION}.tar.gz"
# The ca65 sources live under a "ca65/" directory in the pinned archive.
DECIMAL_SOURCE_DIRECTORY = "ca65"
DECIMAL_SOURCE_MEMBERS = (
    f"{DECIMAL_SOURCE_DIRECTORY}/6502_decimal_test.ca65",
    f"{DECIMAL_SOURCE_DIRECTORY}/example.cfg",
)
# The decimal binary is assembled locally, and its digest legitimately varies
# with the cc65 version. Leave this unset rather than claiming an integrity
# value we cannot verify -- the same stance fetch_test_vectors.py takes for
# the unsigned GitHub archive. The pinned DECIMAL_REVISION is the real anchor.
DECIMAL_SHA256: str | None = None

DESTINATION = Path("tests") / "dormann"
FUNCTIONAL_DESTINATION = DESTINATION / "bin_files" / "6502_functional_test.bin"
DECIMAL_DESTINATION = DESTINATION / "6502_decimal_test.bin"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _download(url: str, archive: Path) -> None:
    try:
        with urlopen(url, timeout=60) as response, archive.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    except OSError as error:
        raise OSError(f"unable to download pinned archive {url}: {error}") from error


def _member_path(name: str) -> tuple[str, ...] | None:
    parts = PurePosixPath(name).parts
    if (
        not parts
        or PurePosixPath(name).is_absolute()
        or any(part in ("", ".", "..") for part in parts)
    ):
        return None
    return parts[1:]


def _extract_members(
    archive: Path, required: tuple[str, ...], destination: Path
) -> None:
    required_set = set(required)
    found: set[str] = set()
    try:
        bundle = tarfile.open(archive, "r:gz")
    except (OSError, tarfile.TarError) as error:
        raise RuntimeError(f"unable to read downloaded archive: {error}") from error

    with bundle:
        for member in bundle.getmembers():
            relative = _member_path(member.name)
            if relative is None:
                raise RuntimeError(f"unsafe archive member {member.name!r}")
            relative_name = "/".join(relative)
            if relative_name not in required_set:
                continue
            if not member.isfile():
                raise RuntimeError(f"expected regular file for {member.name!r}")
            source = bundle.extractfile(member)
            if source is None:
                raise RuntimeError(f"unable to read archive member {member.name!r}")
            target = destination / Path(*relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            found.add(relative_name)

    missing = required_set - found
    if missing:
        names = ", ".join(sorted(missing))
        raise RuntimeError(f"archive is missing required member(s): {names}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _install(staged: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.new")
    backup = target.with_name(f".{target.name}.old")
    if temporary.exists() or backup.exists():
        raise RuntimeError(f"temporary install path already exists beside {target}")
    try:
        os.replace(staged, temporary)
        if target.exists() or target.is_symlink():
            os.replace(target, backup)
        os.replace(temporary, target)
    except OSError as error:
        if backup.exists() and not target.exists():
            os.replace(backup, target)
        if temporary.exists():
            temporary.unlink()
        raise OSError(
            f"unable to install Dormann artifact at {target}: {error}"
        ) from error
    if backup.exists():
        backup.unlink()


def _build_decimal(source: Path, output: Path) -> bool:
    source = source / DECIMAL_SOURCE_DIRECTORY
    ca65 = shutil.which("ca65")
    ld65 = shutil.which("ld65")
    if ca65 is None or ld65 is None:
        missing = ", ".join(
            tool for tool, path in (("ca65", ca65), ("ld65", ld65)) if path is None
        )
        print(
            f"skipping decimal-test provisioning: missing cc65 toolchain ({missing}); "
            "install cc65 (for example, apt install cc65) and run this script again",
            file=sys.stderr,
        )
        return False

    with tempfile.TemporaryDirectory(
        prefix="dormann-decimal-", dir=source.parent
    ) as work:
        work_path = Path(work)
        object_file = work_path / "6502_decimal_test.o"
        listing_file = work_path / "6502_decimal_test.lst"
        built = work_path / "6502_decimal_test.bin"
        subprocess.run(
            [
                ca65,
                "-l",
                str(listing_file),
                "6502_decimal_test.ca65",
                "-o",
                str(object_file),
            ],
            cwd=source,
            check=True,
        )
        subprocess.run(
            [
                ld65,
                str(object_file),
                "-o",
                str(built),
                "-m",
                str(work_path / "6502_decimal_test.map"),
                "-C",
                "example.cfg",
            ],
            cwd=source,
            check=True,
        )
        digest = _sha256(built)
        if DECIMAL_SHA256 is not None and digest != DECIMAL_SHA256:
            print(
                f"warning: decimal binary checksum differs: expected {DECIMAL_SHA256}, "
                f"got {digest}; "
                "this can vary with cc65 versions",
                file=sys.stderr,
            )
        shutil.copyfile(built, output)
    return True


def fetch_tests() -> tuple[Path, bool]:
    root = _project_root()
    (root / DESTINATION).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="fetch-", dir=root / DESTINATION
    ) as temporary:
        work = Path(temporary)
        functional_source = work / "functional"
        decimal_source = work / "decimal"
        functional_source.mkdir()
        decimal_source.mkdir()
        _download(FUNCTIONAL_ARCHIVE_URL, work / "functional.tar.gz")
        _extract_members(
            work / "functional.tar.gz", (FUNCTIONAL_MEMBER,), functional_source
        )
        functional = functional_source / Path(*FUNCTIONAL_MEMBER.split("/"))
        digest = _sha256(functional)
        if digest != FUNCTIONAL_SHA256:
            raise RuntimeError(
                "functional binary checksum mismatch: "
                f"expected {FUNCTIONAL_SHA256}, got {digest}"
            )
        _install(functional, root / FUNCTIONAL_DESTINATION)

        _download(DECIMAL_ARCHIVE_URL, work / "decimal.tar.gz")
        _extract_members(
            work / "decimal.tar.gz", DECIMAL_SOURCE_MEMBERS, decimal_source
        )
        decimal_ready = _build_decimal(decimal_source, work / "decimal.bin")
        if decimal_ready:
            _install(work / "decimal.bin", root / DECIMAL_DESTINATION)

    return root / FUNCTIONAL_DESTINATION, decimal_ready


def main() -> int:
    try:
        functional, decimal_ready = fetch_tests()
    except OSError as error:
        print(f"failed to fetch Dormann tests: {error}", file=sys.stderr)
        return 1
    except RuntimeError as error:
        print(f"invalid Dormann tests: {error}", file=sys.stderr)
        return 1

    decimal_status = " and decimal test" if decimal_ready else ""
    print(
        f"fetched Dormann functional test {FUNCTIONAL_REVISION}{decimal_status} "
        f"to {functional.parent}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
