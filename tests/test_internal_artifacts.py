import hashlib
import json
from pathlib import Path

from PIL import Image

from scripts.internal_cold_start_figure import build_figure

ROOT = Path(__file__).resolve().parents[1]


def test_internal_qwen_results_cost_and_business_evidence():
    analysis = json.loads((ROOT / "work/internal_cold_start_v0.1/analysis.json").read_text())
    summary = analysis["summary"]
    assert summary["cold_start_valid"] == summary["reference_assisted_valid"] == 2
    assert summary["wrong_bindings_rejected"] == 2
    assert summary["missing_evidence_unknown"] == 2
    assert summary["conflicts_unknown"] == 2
    assert summary["accepted_but_business_incorrect"] == 0
    assert summary["proposal_generation_llm_calls"] == 2
    assert summary["new_llm_calls"] == 0
    assert summary["prompt_tokens"] == 1324
    assert summary["completion_tokens"] == 584
    assert summary["total_tokens"] == 1908
    assert summary["llm_latency_s"] > 0
    assert summary["new_solver_runs"] == 1
    for name, expected in analysis["run_config"]["implementation_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    assert analysis["run_config"]["api_key_recorded"] is False
    objective, resource = analysis["cases"]
    assert objective["generation"]["response"]["model"] == "Qwen3_8-27B"
    assert resource["generation"]["response"]["model"] == "Qwen3_8-27B"
    assert objective["generation"]["reused_saved_response"] is True
    assert resource["generation"]["reused_saved_response"] is True
    assert {row["path"]: row["coefficient"] for row in objective["cold_start"]["payload"]["terms"]} == {
        "solution.variables.x1": 15, "solution.variables.x2": 8,
        "solution.variables.x3": 12, "solution.variables.x4": 5}
    assert {row["path"]: row["coefficient"] for row in resource["cold_start"]["payload"]["terms"]} == {
        "solution.variables.x1": 3, "solution.variables.x2": 2, "solution.variables.x3": 1,
        "solution.variables.x4": 6, "solution.variables.x5": 18}
    wrong = next(row for row in resource["cold_start"]["gate"]["evaluation"]["records"]
                 if row["key"] == "wrong_protein")
    assert wrong["fired"] is True


def test_internal_result_figure_has_real_cost_and_no_secret_config(tmp_path):
    image, data_path = build_figure(tmp_path)
    with Image.open(image) as figure:
        assert figure.format == "PNG" and figure.width >= 800 and figure.height >= 500
    data = json.loads(data_path.read_text())
    assert data["summary"]["cold_start_valid"] == 2
    assert data["summary"]["reference_assisted_valid"] == 2
    assert data["summary"]["proposal_generation_llm_calls"] == 2
    assert data["summary"]["new_llm_calls"] == 0
    assert data["summary"]["total_tokens"] == 1908
    assert data["api_key_recorded"] is False
