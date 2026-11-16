import hashlib
import json
from pathlib import Path

from PIL import Image

from scripts.cold_start_figure import build_figure

ROOT = Path(__file__).resolve().parents[1]


def test_cold_start_manifest_and_figure_match_verified_results(tmp_path):
    analysis = json.loads((ROOT / "work/cold_start_binding_v0.1/analysis.json").read_text())
    assert analysis["summary"]["valid_bindings"] == 2
    assert analysis["summary"]["wrong_bindings_rejected"] == 2
    assert analysis["summary"]["missing_evidence_unknown"] == 2
    assert analysis["summary"]["conflicts_unknown"] == 2
    assert analysis["summary"]["accepted_but_business_incorrect"] == 0
    for name, expected in analysis["run_config"]["implementation_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    image, data_path = build_figure(tmp_path)
    with Image.open(image) as figure:
        assert figure.format == "PNG" and figure.width >= 800 and figure.height >= 500
    data = json.loads(data_path.read_text())
    assert data["dag_comparison"]["same_business_correct"] is True
    assert data["dag_comparison"]["same_solver_runs"] is True
    assert data["dag_comparison"]["dag_incremental_benefit"] == "not_demonstrated"
    assert data["accepted_node_ids"] == ["reference_objective_patch"]
    assert set(data["negative_node_ids"]) == {"root_initial", "candidate_derived_binding"}
