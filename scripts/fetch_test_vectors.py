"""Fetch the pinned SingleStepTests 65x02 vector corpus."""

from __future__ import annotations

import hashlib
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path
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
    with urlopen(ARCHIVE_URL) as response, archive.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    return digest.hexdigest()


def _extract_source(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as bundle:
        members = [member for member in bundle.getmembers() if member.isfile()]
        source_marker = f"/{SOURCE_DIRECTORY}/"
        source_members = [
            member for member in members if source_marker in f"/{member.name}"
        ]
        if not source_members:
            raise RuntimeError(
                f"archive does not contain the expected {SOURCE_DIRECTORY!r} directory"
            )

        source_prefix = f"/{SOURCE_DIRECTORY}/"
        for member in source_members:
            relative_name = member.name.split(source_prefix, 1)[1]
            target = destination / SOURCE_DIRECTORY / relative_name
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(member) as source, target.open("wb") as output:
                if source is None:
                    raise RuntimeError(f"unable to read archive member {member.name!r}")
                shutil.copyfileobj(source, output)


def fetch_vectors() -> Path:
    root = _project_root()
    destination = root / DESTINATION
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="6502-vectors-", dir=root) as temporary:
        archive = Path(temporary) / "vectors.tar.gz"
        digest = _download(archive)
        if ARCHIVE_SHA256 is not None and digest != ARCHIVE_SHA256:
            raise RuntimeError(
                f"archive checksum mismatch: expected {ARCHIVE_SHA256}, got {digest}"
            )

        extracted = Path(temporary) / "extracted"
        extracted.mkdir()
        _extract_source(archive, extracted)
        staged = Path(temporary) / "6502_test_vectors"
        extracted.rename(staged)

        if destination.exists():
            shutil.rmtree(destination)
        staged.rename(destination)

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
