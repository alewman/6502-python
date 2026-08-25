import io
import tarfile

import pytest

from scripts import fetch_test_vectors


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
            data = contents.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            bundle.addfile(member, io.BytesIO(data))
    return payload.getvalue()


def _use_project(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_test_vectors, "_project_root", lambda: tmp_path)
    return tmp_path / fetch_test_vectors.DESTINATION


def test_fetch_vectors_uses_pinned_url_and_installs_6502_layout(tmp_path, monkeypatch):
    archive = _archive(
        (
            f"65x02-{fetch_test_vectors.REVISION}/6502/v1/adc.json",
            '{"name": "adc"}',
        ),
        (
            f"65x02-{fetch_test_vectors.REVISION}/6502/README.md",
            "vectors",
        ),
    )
    requested = []

    def fake_urlopen(url, timeout):
        requested.append((url, timeout))
        return _ArchiveResponse(archive)

    monkeypatch.setattr(fetch_test_vectors, "urlopen", fake_urlopen)
    destination = _use_project(tmp_path, monkeypatch)

    installed = fetch_test_vectors.fetch_vectors()

    assert requested == [(fetch_test_vectors.ARCHIVE_URL, 60)]
    assert fetch_test_vectors.REVISION in requested[0][0]
    assert installed == destination / "6502"
    assert (installed / "v1" / "adc.json").read_text() == '{"name": "adc"}'
    assert not (installed / "README.md").exists()


def test_fetch_vectors_replaces_existing_corpus(tmp_path, monkeypatch):
    destination = _use_project(tmp_path, monkeypatch)
    old_corpus = destination / "6502"
    old_corpus.mkdir(parents=True)
    (old_corpus / "obsolete.json").write_text("old")
    (old_corpus / "preserved-only-by-old-install.txt").write_text("old")

    archive = _archive(
        ("source/6502/v1/adc.json", "new"),
    )
    monkeypatch.setattr(
        fetch_test_vectors,
        "urlopen",
        lambda url, timeout: _ArchiveResponse(archive),
    )

    fetch_test_vectors.fetch_vectors()

    assert (old_corpus / "v1" / "adc.json").read_text() == "new"
    assert not (old_corpus / "obsolete.json").exists()
    assert not (old_corpus / "preserved-only-by-old-install.txt").exists()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"not a gzip archive", "unable to read downloaded archive"),
        (
            _archive(("source/README.md", "not vectors")),
            "archive does not contain JSON vectors under '6502'",
        ),
    ],
)
def test_fetch_vectors_rejects_malformed_archives_without_replacing_corpus(
    tmp_path, monkeypatch, payload, message
):
    destination = _use_project(tmp_path, monkeypatch)
    old_corpus = destination / "6502"
    old_corpus.mkdir(parents=True)
    marker = old_corpus / "existing.json"
    marker.write_text("existing")
    monkeypatch.setattr(
        fetch_test_vectors,
        "urlopen",
        lambda url, timeout: _ArchiveResponse(payload),
    )

    with pytest.raises(RuntimeError, match=message):
        fetch_test_vectors.fetch_vectors()

    assert marker.read_text() == "existing"


def test_main_reports_download_failure_actionably(monkeypatch, capsys):
    error = OSError("connection refused")
    monkeypatch.setattr(
        fetch_test_vectors, "fetch_vectors", lambda: (_ for _ in ()).throw(error)
    )

    assert fetch_test_vectors.main() == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"failed to fetch vector corpus: {error}" in captured.err


def test_main_reports_invalid_archive_actionably(monkeypatch, capsys):
    error = RuntimeError("archive does not contain JSON vectors under '6502'")
    monkeypatch.setattr(
        fetch_test_vectors, "fetch_vectors", lambda: (_ for _ in ()).throw(error)
    )

    assert fetch_test_vectors.main() == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"invalid vector corpus: {error}" in captured.err
