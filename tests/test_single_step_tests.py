"""Every opcode against the SingleStepTests 65x02 corpus, every bus cycle included.

The quick loop runs the first 100 cases of each of the 256 opcodes; the slow
test runs all 10,000 of each, 2,560,000 cases (``pytest -m slow``).
"""

import pytest

from tests.single_step import FETCH_HINT, corpus_present, load_cases, run_case

pytestmark = pytest.mark.skipif(not corpus_present(), reason=FETCH_HINT)


def _failures(opcode: int, limit: int | None) -> list[str]:
    failures = []
    for case in load_cases(opcode, limit):
        failures.extend(str(mismatch) for mismatch in run_case(case))
    return failures


@pytest.mark.parametrize("opcode", range(256), ids=lambda opcode: f"{opcode:02x}")
def test_opcode_sample(opcode: int) -> None:
    failures = _failures(opcode, 100)
    assert not failures, "\n".join(failures[:5])


@pytest.mark.slow
@pytest.mark.parametrize("opcode", range(256), ids=lambda opcode: f"{opcode:02x}")
def test_opcode_full_corpus(opcode: int) -> None:
    failures = _failures(opcode, None)
    assert not failures, f"{len(failures)} mismatches; first: " + "\n".join(failures[:5])
