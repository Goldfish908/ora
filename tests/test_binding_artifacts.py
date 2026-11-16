import hashlib
import json
from pathlib import Path

from PIL import Image

from scripts.binding_figure import build_figure

ROOT = Path(__file__).resolve().parents[1]


def test_binding_manifest_and_figure_preserve_scope_and_provenance(tmp_path):
    analysis = json.loads((ROOT / "work/binding_validation_v0.1/analysis.json").read_text())
    assert analysis["summary"] == {
        "families": 2, "valid_bindings": 2, "wrong_bindings_rejected": 2,
        "missing_evidence_unknown": 2, "conflicts_unknown": 2,
        "accepted_but_business_incorrect": 0, "new_llm_calls": 0,
    }
    assert analysis["run_config"]["same_validation_code_for_all_families"] is True
    assert "no LLM proposals" in analysis["run_config"]["proposal_authoring"]
    for name, expected in analysis["run_config"]["implementation_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    assert analysis["lifecycle"]["wrong_or_unknown_bindings"] == "rejected_not_promoted"
    image, data_path = build_figure(tmp_path)
    with Image.open(image) as figure:
        assert figure.format == "PNG" and figure.width >= 800 and figure.height >= 500
    data = json.loads(data_path.read_text())
    assert data["summary"]["valid_bindings"] == 2
    assert data["summary"]["conflicts_unknown"] == 2
    assert data["accepted_but_business_incorrect"] == 0
