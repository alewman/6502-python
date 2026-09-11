"""Fetch the pinned SingleStepTests 65x02 vector corpus."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

# Keep the revision in one place. ARCHIVE_URL is derived from it below so an
# archive can never accidentally point at a different revision.
REPOSITORY_URL = "https://github.com/SingleStepTests/65x02"
REVISION = "2f6980a2d95757486c7bee24355c360e40e2a224"
ARCHIVE_URL = f"{REPOSITORY_URL}/archive/{REVISION}.tar.gz"
SOURCE_DIRECTORY = "6502"
DESTINATION = Path("tests") / "6502_test_vectors"

# SingleStepTests does not publish a checksum for the generated GitHub archive.
# Leave this unset rather than claiming an integrity value from an unverified
# source; the immutable commit URL still prevents moving-branch substitution.
ARCHIVE_SHA256: str | None = None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _download(archive: Path) -> str:
    digest = hashlib.sha256()
    try:
        with (
            urlopen(ARCHIVE_URL, timeout=60) as response,
            archive.open("wb") as output,
        ):
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
    except OSError as error:
        raise OSError(
            f"unable to download pinned archive {ARCHIVE_URL}: {error}"
        ) from error
    return digest.hexdigest()


def _source_member_path(member: tarfile.TarInfo) -> tuple[str, ...] | None:
    path = PurePosixPath(member.name)
    parts = path.parts
    if path.is_absolute() or len(parts) < 3 or parts[0] in (".", ".."):
        return None
    if any(part in ("", ".", "..") for part in parts):
        return None
    if parts[1] != SOURCE_DIRECTORY:
        return None
    return parts[2:]


def _extract_source(archive: Path, destination: Path) -> None:
    try:
        bundle = tarfile.open(archive, "r:gz")
    except (OSError, tarfile.TarError) as error:
        raise RuntimeError(f"unable to read downloaded archive: {error}") from error

    with bundle:
        source_members: list[tuple[tarfile.TarInfo, tuple[str, ...]]] = []
        for member in bundle.getmembers():
            relative_parts = _source_member_path(member)
            if relative_parts is None:
                continue
            if member.isdir():
                continue
            if not member.isfile():
                raise RuntimeError(
                    f"expected regular files under {SOURCE_DIRECTORY!r}; "
                    f"found {member.name!r}"
                )
            source_members.append((member, relative_parts))

        json_members = [
            (member, relative_parts)
            for member, relative_parts in source_members
            if relative_parts[-1].lower().endswith(".json")
        ]
        if not json_members:
            raise RuntimeError(
                f"archive does not contain JSON vectors under {SOURCE_DIRECTORY!r}"
            )

        for member, relative_parts in json_members:
            target = destination / SOURCE_DIRECTORY / Path(*relative_parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                source = bundle.extractfile(member)
            except (OSError, tarfile.TarError) as error:
                raise RuntimeError(
                    f"unable to read archive member {member.name!r}: {error}"
                ) from error
            if source is None:
                raise RuntimeError(f"unable to read archive member {member.name!r}")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _install_atomically(staged: Path, destination: Path) -> None:
    target = destination / SOURCE_DIRECTORY
    backup = destination / f".{SOURCE_DIRECTORY}.old"
    if backup.exists() or backup.is_symlink():
        raise RuntimeError(f"temporary backup path already exists: {backup}")

    target.parent.mkdir(parents=True, exist_ok=True)
    had_existing = target.exists() or target.is_symlink()
    try:
        if had_existing:
            os.replace(target, backup)
        os.replace(staged / SOURCE_DIRECTORY, target)
    except OSError as error:
        if had_existing and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise OSError(
            f"unable to install vector corpus at {target}: {error}"
        ) from error

    if backup.exists():
        shutil.rmtree(backup)


def fetch_vectors() -> Path:
    root = _project_root()
    destination = root / DESTINATION
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="6502-vectors-", dir=destination.parent
    ) as temporary:
        temporary_path = Path(temporary)
        archive = temporary_path / "vectors.tar.gz"
        digest = _download(archive)
        if ARCHIVE_SHA256 is not None and digest != ARCHIVE_SHA256:
            raise RuntimeError(
                f"archive checksum mismatch: expected {ARCHIVE_SHA256}, got {digest}"
            )

        staged = temporary_path / "staged"
        staged.mkdir()
        _extract_source(archive, staged)
        _install_atomically(staged, destination)

    return destination / SOURCE_DIRECTORY


def main() -> int:
    try:
        path = fetch_vectors()
    except OSError as error:
        print(f"failed to fetch vector corpus: {error}", file=sys.stderr)
        return 1
    except RuntimeError as error:
        print(f"invalid vector corpus: {error}", file=sys.stderr)
        return 1

    print(f"fetched SingleStepTests {REVISION} to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
