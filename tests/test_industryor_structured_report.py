import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.industryor_structured_report import build_report, paired_metrics, validate

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "work/industryor_structured_smoke_v0.1"


@pytest.mark.skipif(not (SMOKE / "analysis.json").exists(), reason="structured smoke has not completed")
def test_incomplete_smoke_report_preserves_errors_and_old_artifacts(tmp_path):
    validation = validate(SMOKE, require_complete=False)
    assert validation["results"] == 8
    assert validation["source_snapshots_verified"] == 9
    assert validation["iterative_prompt_pairs_verified"] == 4
    analysis = json.loads((SMOKE / "analysis.json").read_text())
    metrics = paired_metrics(analysis["results"], analysis["run_config"]["arms"])
    assert metrics["structured"]["paired_n"] == 2
    assert metrics["structured"]["false_business_accepts"] == 0
    report, image, data = build_report(SMOKE, tmp_path / "report.md", tmp_path,
                                       require_complete=False)
    text = report.read_text()
    assert "ERROR" in text
    assert "win 保留" in text
    assert "失败归因" in text
    assert "raw k=1=60/100" in text
    assert "raw k=3 selected=66/100" in text
    payload = json.loads(data.read_text())
    assert payload["paired_metrics"] == metrics
    assert payload["failure_attribution"]["structured"]["runner_error_ids"] == [1, 20]
    assert payload["claims"]["sota"] is False
    assert payload["claims"]["official_coopa_runner"] is False
    with Image.open(image) as figure:
        assert figure.format == "PNG"


MEMORY_SMOKE = ROOT / "work/industryor_structured_smoke_v0.2"


@pytest.mark.skipif(not (MEMORY_SMOKE / "analysis.json").exists(), reason="memory smoke has not completed")
def test_memory_delta_is_measured_against_plain_dag():
    from scripts.industryor_structured_report import compare_arms

    analysis = json.loads((MEMORY_SMOKE / "analysis.json").read_text())
    for arm in ("structured_dag_trigger", "structured_dag_full"):
        delta = compare_arms(analysis["results"], "structured_dag", arm)
        assert delta["paired_n"] == 3
        assert delta["objective_wins_preserved"] == 3
        assert delta["business_wins_preserved"] == 3
        assert delta["objective_gained_ids"] == []
        assert delta["objective_lost_ids"] == []
        assert delta["business_gained_ids"] == []
        assert delta["business_lost_ids"] == []
        assert delta["changed_objective_ids"] == []


def test_shared_cost_audit_separates_unique_and_reused_calls():
    from scripts.industryor_k3_pipeline import costs
    from scripts.industryor_structured_report import shared_cost_audit

    records = [{"response": {"request_wall_s": latency, "request_attempts": [{}],
                             "usage": {"total_tokens": 10, "completion_tokens": 4}},
                "new_llm_calls": 1, "reused": False} for latency in (1.004, 2.005)]
    saved = costs(records)
    saved["new_llm_calls"] = 1
    saved["new_llm_latency_s"] = costs(records[:1])["new_llm_latency_s"]
    audit = shared_cost_audit(records, saved)
    assert audit["artifact_cost"] == costs(records)
    assert audit["reused_new_llm_calls"] == 1
    assert audit["reused_new_llm_latency_s"] == 2.005
    with pytest.raises(AssertionError):
        shared_cost_audit(records, {**saved, "new_llm_calls": 3})
