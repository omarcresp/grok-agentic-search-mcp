import importlib.util
import json
from pathlib import Path

from grok_search_mcp.models import Claim, Evidence

ROOT = Path(__file__).resolve().parents[1]


def test_evaluation_keeps_mechanical_checks_separate_from_accuracy(record, source):
    spec = importlib.util.spec_from_file_location("evaluation", ROOT / "scripts" / "evaluate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    record.output.claims = [
        Claim(
            id="c1",
            statement="A claim",
            question="q",
            status="supported",
            evidence=[Evidence(source_id=source.id, quote=source.text[:50])],
        )
    ]
    result = module.measurements(record.output, [source])
    assert result["quote_match_rate"] == 1
    assert result["human_rubric_score"] is None
    assert module.measurements(record.output, [])["quote_match_rate"] == 0
    cases = json.loads((ROOT / "evals" / "questions.json").read_text())
    assert len(cases) == 12 and len({c["id"] for c in cases}) == 12
    assert all(c["rubric"] and c["query"] for c in cases)
