import hashlib
import io
import tarfile
import tempfile
from pathlib import Path

import pytest

from scripts import fetch_dormann_tests


class _ArchiveResponse:
    def __init__(self, payload):
        self._stream = io.BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._stream.close()
        return False

    def read(self, size):
        return self._stream.read(size)


def _archive(*files):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as bundle:
        for name, contents in files:
            data = contents if isinstance(contents, bytes) else contents.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            bundle.addfile(member, io.BytesIO(data))
    return payload.getvalue()


def _functional_archive(contents):
    return _archive(
        (
            f"6502_65C02_functional_tests-{fetch_dormann_tests.FUNCTIONAL_REVISION}/"
            f"{fetch_dormann_tests.FUNCTIONAL_MEMBER}",
            contents,
        )
    )


def _decimal_archive():
    prefix = f"6502_65C02_functional_tests-{fetch_dormann_tests.DECIMAL_REVISION}"
    # Mirror the real pinned archive, which keeps the ca65 sources in their own
    # directory. A fixture shaped to match the code instead of the upstream
    # archive is why the flat-layout bug survived review.
    return _archive(
        *(
            (f"{prefix}/{member}", "source")
            for member in fetch_dormann_tests.DECIMAL_SOURCE_MEMBERS
        )
    )


def _offline_project(tmp_path, monkeypatch, functional_archive):
    monkeypatch.setattr(fetch_dormann_tests, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(fetch_dormann_tests.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        fetch_dormann_tests.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("external subprocess must not run"),
    )
    archives = iter((functional_archive, _decimal_archive()))
    requested = []

    def fake_urlopen(url, timeout):
        requested.append((url, timeout))
        return _ArchiveResponse(next(archives))

    monkeypatch.setattr(fetch_dormann_tests, "urlopen", fake_urlopen)
    return requested


def test_fetch_uses_immutable_revisions_and_project_relative_destinations(
    tmp_path, monkeypatch
):
    contents = b"functional test"
    monkeypatch.setattr(
        fetch_dormann_tests,
        "FUNCTIONAL_SHA256",
        hashlib.sha256(contents).hexdigest(),
    )
    requested = _offline_project(tmp_path, monkeypatch, _functional_archive(contents))
    working_directory = tmp_path / "working-directory"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)

    functional, decimal_ready = fetch_dormann_tests.fetch_tests()

    assert requested == [
        (fetch_dormann_tests.FUNCTIONAL_ARCHIVE_URL, 60),
        (fetch_dormann_tests.DECIMAL_ARCHIVE_URL, 60),
    ]
    assert fetch_dormann_tests.FUNCTIONAL_REVISION in requested[0][0]
    assert fetch_dormann_tests.DECIMAL_REVISION in requested[1][0]
    assert not fetch_dormann_tests.FUNCTIONAL_DESTINATION.is_absolute()
    assert not fetch_dormann_tests.DECIMAL_DESTINATION.is_absolute()
    assert functional == tmp_path / fetch_dormann_tests.FUNCTIONAL_DESTINATION
    assert functional.is_relative_to(tmp_path)
    assert functional.read_bytes() == contents
    assert decimal_ready is False


def test_fetch_confines_scratch_work_below_tests_dormann(tmp_path, monkeypatch):
    contents = b"functional test"
    monkeypatch.setattr(
        fetch_dormann_tests,
        "FUNCTIONAL_SHA256",
        hashlib.sha256(contents).hexdigest(),
    )
    _offline_project(tmp_path, monkeypatch, _functional_archive(contents))

    dormann_root = tmp_path / "tests" / "dormann"
    real_temporary_directory = tempfile.TemporaryDirectory
    created_under = []

    class _RecordingTemporaryDirectory(real_temporary_directory):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created_under.append(self.name)

    monkeypatch.setattr(
        fetch_dormann_tests.tempfile, "TemporaryDirectory", _RecordingTemporaryDirectory
    )

    fetch_dormann_tests.fetch_tests()

    assert created_under
    for path in created_under:
        assert Path(path).is_relative_to(dormann_root)
    assert not any(tmp_path.joinpath("tests").glob("dormann-*"))


def test_fetch_is_idempotent_for_valid_downloads(tmp_path, monkeypatch):
    contents = b"valid functional test"
    monkeypatch.setattr(
        fetch_dormann_tests,
        "FUNCTIONAL_SHA256",
        hashlib.sha256(contents).hexdigest(),
    )
    monkeypatch.setattr(fetch_dormann_tests, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(fetch_dormann_tests.shutil, "which", lambda name: None)
    responses = iter(
        (
            _functional_archive(contents),
            _decimal_archive(),
            _functional_archive(contents),
            _decimal_archive(),
        )
    )
    monkeypatch.setattr(
        fetch_dormann_tests,
        "urlopen",
        lambda url, timeout: _ArchiveResponse(next(responses)),
    )
    target = tmp_path / fetch_dormann_tests.FUNCTIONAL_DESTINATION
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old contents")

    first = fetch_dormann_tests.fetch_tests()
    second = fetch_dormann_tests.fetch_tests()

    assert first == second == (target, False)
    assert target.read_bytes() == contents
    assert not target.with_name(f".{target.name}.new").exists()
    assert not target.with_name(f".{target.name}.old").exists()


def test_fetch_rejects_missing_functional_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_dormann_tests, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(
        fetch_dormann_tests,
        "urlopen",
        lambda url, timeout: _ArchiveResponse(
            _archive(("source/README.md", "no binary"))
        ),
    )

    with pytest.raises(RuntimeError, match="archive is missing required member"):
        fetch_dormann_tests.fetch_tests()

    assert not (tmp_path / fetch_dormann_tests.FUNCTIONAL_DESTINATION).exists()


def test_fetch_rejects_mismatched_functional_checksum(tmp_path, monkeypatch):
    contents = b"tampered functional test"
    monkeypatch.setattr(fetch_dormann_tests, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(fetch_dormann_tests, "FUNCTIONAL_SHA256", "0" * 64)
    monkeypatch.setattr(
        fetch_dormann_tests,
        "urlopen",
        lambda url, timeout: _ArchiveResponse(_functional_archive(contents)),
    )

    with pytest.raises(RuntimeError, match="functional binary checksum mismatch"):
        fetch_dormann_tests.fetch_tests()

    assert not (tmp_path / fetch_dormann_tests.FUNCTIONAL_DESTINATION).exists()


def test_pinned_digests_are_well_formed_sha256_values():
    """A digest of the wrong length can never match, so it verifies nothing.

    Both constants shipped 63 characters long and silently made the functional
    exerciser unfetchable. Every test that touched them monkeypatched a valid
    stand-in, so nothing ever measured the real values.
    """
    for name in ("FUNCTIONAL_SHA256", "DECIMAL_SHA256"):
        digest = getattr(fetch_dormann_tests, name)
        if digest is None:
            continue  # Explicitly unclaimed beats a value nobody can verify.
        assert len(digest) == 64, f"{name} is {len(digest)} chars; SHA-256 is 64"
        assert set(digest) <= set("0123456789abcdef"), f"{name} is not lowercase hex"


def test_pinned_revisions_are_well_formed_git_object_names():
    for name in ("FUNCTIONAL_REVISION", "DECIMAL_REVISION"):
        revision = getattr(fetch_dormann_tests, name)
        assert len(revision) == 40, f"{name} is {len(revision)} chars; a SHA-1 is 40"
        assert set(revision) <= set("0123456789abcdef"), f"{name} is not lowercase hex"
