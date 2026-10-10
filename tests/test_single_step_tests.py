"""Every opcode against the SingleStepTests 65x02 corpus, every bus cycle included.

Two sets: ``6502`` checks :class:`MOS6502` and ``nes6502`` checks
:class:`RP2A03`. The quick loop runs the first 100 cases of each of the 256
opcodes in each set; the slow test runs all 10,000 of each, 2,560,000 cases a
set (``pytest -m slow``).
"""

import pytest

from tests.single_step import FETCH_HINT, SETS, corpus_present, load_cases, run_case

CORPORA = [
    pytest.param(corpus, marks=pytest.mark.skipif(not corpus_present(corpus), reason=FETCH_HINT))
    for corpus in SETS
]


def _failures(corpus: str, opcode: int, limit: int | None) -> list[str]:
    failures = []
    for case in load_cases(opcode, limit, corpus):
        failures.extend(str(mismatch) for mismatch in run_case(case, SETS[corpus]))
    return failures


@pytest.mark.parametrize("opcode", range(256), ids=lambda opcode: f"{opcode:02x}")
@pytest.mark.parametrize("corpus", CORPORA)
def test_opcode_sample(corpus: str, opcode: int) -> None:
    failures = _failures(corpus, opcode, 100)
    assert not failures, "\n".join(failures[:5])


@pytest.mark.slow
@pytest.mark.parametrize("opcode", range(256), ids=lambda opcode: f"{opcode:02x}")
@pytest.mark.parametrize("corpus", CORPORA)
def test_opcode_full_corpus(corpus: str, opcode: int) -> None:
    failures = _failures(corpus, opcode, None)
    assert not failures, f"{len(failures)} mismatches; first: " + "\n".join(failures[:5])
