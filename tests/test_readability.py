"""Readability contract for the instruction core, enforced the way correctness is.

Following z80-python's tests/test_readability.py: every opcode handler must be
findable by the mnemonic a 6502 programmer would grep for, must live in the
module that owns its instruction group, and must say where its rule comes
from. Checked from the source with :mod:`ast`, without importing it:

1. Every ``_op_*`` method's docstring headline is ``MNEMONIC[ form] -- text
   (SOURCE).``, SOURCE being a page of MOS's programming manual (``PM p. B-3``)
   or of No More Secrets (``NMS p. 7``).
2. The page is the right one: a documented mnemonic cites its own page of PM
   Appendix B and an undocumented one its own section of NMS, both as the
   documents print them (docs/validation.md pins both files by SHA-256).
3. The handler lives in the module that owns that mnemonic, is named after
   it, and every mnemonic has a handler.
"""

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "sixfiveohtwo"

#: PM Appendix B: the page each documented instruction's summary is printed on.
PM_APPENDIX_B = {
    mnemonic: f"B-{page}"
    for page, mnemonics in {
        3: "ADC AND",
        4: "ASL BCC",
        5: "BCS BEQ",
        6: "BIT BMI",
        7: "BNE BPL",
        8: "BRK BVC",
        9: "BVS CLC",
        10: "CLD CLI",
        11: "CLV CMP",
        12: "CPX CPY",
        13: "DEC DEX",
        14: "DEY EOR",
        15: "INC INX",
        16: "INY JMP",
        17: "JSR LDA",
        18: "LDX LDY",
        19: "LSR NOP",
        20: "ORA PHA",
        21: "PHP PLA",
        22: "PLP ROL",
        23: "ROR RTI RTS",
        24: "SBC SEC",
        25: "SED SEI",
        26: "STA STX",
        27: "STY TAX",
        28: "TAY TYA",
        29: "TSX TXA TXS",
    }.items()
    for mnemonic in mnemonics.split()
}

#: NMS's table of contents: the page each undocumented instruction starts on.
NMS_PAGES = {
    "SLO": 7,
    "RLA": 9,
    "SRE": 11,
    "RRA": 14,
    "SAX": 16,
    "LAX": 19,
    "DCP": 22,
    "ISC": 26,
    "ANC": 28,
    "ALR": 30,
    "ARR": 32,
    "SBX": 35,
    "USBC": 40,
    "LAS": 41,
    "NOP": 43,
    "JAM": 47,
    "SHA": 50,
    "SHX": 52,
    "SHY": 55,
    "TAS": 58,
    "ANE": 61,
    "LXA": 64,
}

OWNERS: dict[str, frozenset[str]] = {
    module: frozenset(mnemonics.split())
    for module, mnemonics in {
        "_alu.py": "ADC SBC AND ORA EOR CMP CPX CPY BIT",
        "_loads.py": "LDA LDX LDY STA STX STY TAX TAY TXA TYA TSX TXS INX INY DEX DEY",
        "_shifts.py": "ASL LSR ROL ROR INC DEC",
        "_control.py": "BPL BMI BVC BVS BCC BCS BNE BEQ JMP JSR RTS PHA PHP PLA PLP "
        "CLC SEC CLD SED CLV CLI SEI NOP BRK RTI",
        "_undocumented.py": " ".join(NMS_PAGES),
    }.items()
}
HEADLINE = re.compile(r"^(?P<mnemonic>[A-Z]+)(?P<form>[^-]*?) -- (?P<text>.+)$")
CITATION = re.compile(r"\((?P<source>PM|NMS) pp?\. (?P<page>B-\d+|\d+)[^)]*\)\.$")


def handlers() -> list[tuple[str, ast.FunctionDef]]:
    found = []
    for path in sorted(SRC.glob("_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            found += [
                (path.name, node)
                for node in cls.body
                if isinstance(node, ast.FunctionDef) and node.name.startswith("_op_")
            ]
    assert found
    return found


HANDLERS = handlers()


def headline(node: ast.FunctionDef) -> str:
    docstring = ast.get_docstring(node) or ""
    return " ".join(docstring.split("\n\n")[0].split())


@pytest.mark.parametrize(("module", "node"), HANDLERS, ids=[node.name for _, node in HANDLERS])
def test_handler_headline_names_mnemonic_and_cites_its_own_page(
    module: str, node: ast.FunctionDef
) -> None:
    line = headline(node)
    match = HEADLINE.match(line)
    assert match, f"{node.name}: headline must read 'MNEMONIC -- text (SOURCE).', got {line!r}"
    mnemonic = match["mnemonic"]
    citation = CITATION.search(line)
    assert citation, f"{node.name}: headline must end with (PM p. B-n) or (NMS p. n)"
    if module == "_undocumented.py":
        assert citation["source"] == "NMS", f"{node.name}: undocumented opcodes cite NMS"
        assert int(citation["page"]) == NMS_PAGES[mnemonic], (
            f"{node.name}: {mnemonic} starts on NMS p. {NMS_PAGES[mnemonic]}"
        )
    else:
        assert citation["source"] == "PM", f"{node.name}: documented opcodes cite PM"
        assert citation["page"] == PM_APPENDIX_B[mnemonic], (
            f"{node.name}: {mnemonic} is on PM p. {PM_APPENDIX_B[mnemonic]}"
        )


@pytest.mark.parametrize(("module", "node"), HANDLERS, ids=[node.name for _, node in HANDLERS])
def test_handler_lives_in_its_module_and_is_named_after_its_mnemonic(
    module: str, node: ast.FunctionDef
) -> None:
    mnemonic = HEADLINE.match(headline(node))["mnemonic"]
    assert mnemonic in OWNERS[module], f"{node.name}: {mnemonic} belongs elsewhere"
    assert node.name.removeprefix("_op_").split("_")[0] == mnemonic.lower()


def test_every_mnemonic_has_a_handler_and_no_handler_is_defined_twice() -> None:
    names = [node.name for _, node in HANDLERS]
    assert len(names) == len(set(names)), "a duplicate would be shadowed by the MRO"
    claimed = {HEADLINE.match(headline(node))["mnemonic"] for _, node in HANDLERS}
    assert claimed == set(PM_APPENDIX_B) | set(NMS_PAGES)
    assert len(PM_APPENDIX_B) == 56
