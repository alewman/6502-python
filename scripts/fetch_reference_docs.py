"""Fetch the three documents every handler docstring cites, and check their pins.

    python scripts/fetch_reference_docs.py [--dest DIR] [--only PM|HM|NMS]

``PM`` is MOS Technology's *MCS6500 Microcomputer Family Programming Manual*,
publication 6500-50A (January 1976); ``PM p. B-3`` means its printed page B-3.
``HM`` is the *MCS6500 Microcomputer Family Hardware Manual*, 6500-10A (January
1976), whose Appendix A lists every cycle's address and data bus. ``NMS`` is
groepaz's *No More Secrets: NMOS 6510 Unintended Opcodes*, v0.99 (24 December
2024); ``NMS p. 7`` means its printed page 7. docs/validation.md places all
three in the oracle tiers: documentation, below every executable oracle.

None is redistributed: the download directory is gitignored. Each file is
checked against the SHA-256 recorded below and in docs/validation.md. A
mismatch means the publisher replaced the file; do not silently update the
hash -- check whether the cited page numbers still hold, and record the change.
"""

from __future__ import annotations

import argparse
import hashlib
import urllib.request
from pathlib import Path

DOCUMENTS = {
    "PM": (
        "https://archive.org/download/6500-50a_mcs6500pgmmanjan76/"
        "6500-50A_MCS6500pgmManJan76_text.pdf",
        "mcs6500-programming-manual.pdf",
        "MOS MCS6500 Microcomputer Family Programming Manual, 6500-50A",
    ),
    "HM": (
        "https://archive.org/download/mcs-6500-family-hardware-manual-1976-01/"
        "MCS6500_family_hardware_manual_1976-01.pdf",
        "mcs6500-hardware-manual.pdf",
        "MOS MCS6500 Microcomputer Family Hardware Manual, 6500-10A",
    ),
    "NMS": (
        "https://csdb.dk/getinternalfile.php/264129/"
        "NoMoreSecrets-NMOS6510UnintendedOpcodes-20242412.pdf",
        "no-more-secrets-v0.99.pdf",
        "groepaz, No More Secrets: NMOS 6510 Unintended Opcodes, v0.99",
    ),
}

# SHA-256 of each file as fetched on 2026-09-21; recorded in docs/validation.md.
PINNED_SHA256 = {
    "PM": "5ee2a698e274321bea9189d1f15038f69c13fcc4960026ca593c9229ba6a0973",
    "HM": "81ea570c9d68deff64d67365bdf24534df93a8c62121e53036aeac6a557cea23",
    "NMS": "d5f42bd5b301c68f774529ca21e95923e00fc1a13e3781afa561ff8d8e341fad",
}

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) 6502-python/docs-fetch"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(name: str, dest: Path) -> Path:
    url, filename, title = DOCUMENTS[name]
    target = dest / filename
    if not target.exists():
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request) as response, target.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
    digest = _sha256(target)
    status = "ok" if digest == PINNED_SHA256[name] else "MISMATCH"
    print(f"{name:<4} {target.stat().st_size:>10,} bytes  {digest}  {status}  {title}")
    if status == "MISMATCH":
        raise SystemExit(f"{name}: expected SHA-256 {PINNED_SHA256[name]}")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dest", type=Path, default=Path(__file__).resolve().parents[1] / "reference"
    )
    parser.add_argument("--only", choices=sorted(DOCUMENTS))
    arguments = parser.parse_args()
    arguments.dest.mkdir(parents=True, exist_ok=True)
    for name in [arguments.only] if arguments.only else sorted(DOCUMENTS):
        fetch(name, arguments.dest)


if __name__ == "__main__":
    main()
