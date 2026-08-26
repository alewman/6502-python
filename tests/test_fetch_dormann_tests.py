import hashlib
import io
import tarfile

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
    return _archive(
        (f"{prefix}/6502_decimal_test.ca65", "source"),
        (f"{prefix}/example.cfg", "configuration"),
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
    assert not (working_directory / "tests").exists()


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
