import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from router_py.core.extract_validated import parse


SAMPLE = """BEGIN_VALIDATED
Amoxicillin is a broad-spectrum antibiotic used to treat various bacterial infections.

Evidence:
type: entity
subject: Amoxicillin

Oscar is Mike's dog. He has a fixation on cats; training approach uses leave-it, distance, and reward.

---- BEGIN PROPOSAL ----
[MEMORY PROPOSAL]
type: drug information
subject: Amoxicillin
summary: A broad-spectrum antibiotic used to treat various bacterial infections.
confidence: high
---- END PROPOSAL ----
END_VALIDATED
"""


def test_parse_stops_before_evidence_and_proposal():
    result = parse(SAMPLE)
    assert result["parse_ok"] is True
    assert (
        result["answer"]
        == "Amoxicillin is a broad-spectrum antibiotic used to treat various bacterial infections."
    )
    assert "Oscar" not in result["answer"]
    assert "MEMORY PROPOSAL" not in result["answer"]
    assert "type:" not in result["answer"]
    assert "subject:" not in result["answer"]
    assert "confidence:" not in result["answer"]


def test_parse_empty_input():
    result = parse("")
    assert result["parse_ok"] is False
    assert result["answer"] == ""
    assert result["sources"] == []
    assert result["claims"] == []


def test_parse_missing_markers():
    result = parse("There is no validated block here.")
    assert result["parse_ok"] is False
