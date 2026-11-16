import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.industryor_full_report import build_report, validate_run

ROOT = Path(__file__).resolve().parents[1]


def test_smoke_artifacts_are_recomputed_but_never_promoted_to_full_results(tmp_path):
    run = ROOT / "work/industryor_full_smoke_v0.2"
    validation = validate_run(run, require_full=False)
    assert validation["registered_n"] == 4
    assert validation["initial_responses_verified"] == 4
    assert validation["executions_verified"] == 6
    assert validation["business_scores_recomputed"] >= 4
    assert validation["retry_accounting_complete"] is False
    report, image, data = build_report(run, tmp_path / "report.md", tmp_path, require_full=False)
    text = report.read_text()
    assert "工程冒烟" in text
    assert "非全集" in text
    assert "旧 z2 为 **3/4**" in text
    with Image.open(image) as figure:
        assert figure.format == "PNG"
        assert figure.width >= 1600
        assert figure.height >= 600
    figure_data = json.loads(data.read_text())
    assert figure_data["n"] == 4
    assert figure_data["business_unverified"] == 1
    assert figure_data["claims"]["sota_claim"] is False
    comparison = json.loads((run / "comparison.json").read_text())
    assert len(comparison["results"]) == 4
    assert all(row["old"]["z2"] for row in comparison["results"])


@pytest.mark.skipif(not (ROOT / "work/industryor_full_qwen_v0.1/analysis.json").exists(),
                    reason="full IndustryOR run has not completed")
def test_full_industryor_artifacts_support_the_reported_metrics(tmp_path):
    run = ROOT / "work/industryor_full_qwen_v0.1"
    analysis = json.loads((run / "analysis.json").read_text())
    validation = validate_run(run)
    assert validation["registered_n"] == 100
    assert validation["initial_responses_verified"] == 100
    assert validation["executions_verified"] == analysis["summary"]["candidate_evaluations"]
    assert validation["source_snapshots_verified"] == len(analysis["run_config"]["implementation_sha256"])
    assert validation["retry_accounting_complete"] is True
    assert analysis["summary"]["business_unverified"] == 92
    assert analysis["summary"]["business_audit"]["n"] == 8
    assert analysis["summary"]["accepted_but_business_incorrect"] == 0
    assert analysis["summary"]["harmed_win"] == 0
    report, image, data = build_report(run, tmp_path / "report.md", tmp_path)
    assert "完整 IndustryOR-100" in report.read_text()
    comparison = json.loads((run / "comparison.json").read_text())
    assert comparison["old_metrics_same_ids"]["z2"]["objective_matches_abs_0_1"] == 74
    assert comparison["new_metrics"]["objective_matches_abs_0_1"] == 70
    assert len(comparison["results"]) == 100
    derived = comparison["derived_summary"]
    assert derived["business_semantic_recovery_ids"] == [19, 21]
    assert len(derived["objective_recovered_ids"]) == 14
    assert derived["objective_lost_ids"] == []
    assert derived["audit_incomplete_or_blocked_ids"] == [4, 8, 9, 20, 25, 48]
    assert derived["outcome_classes_recomputed_from_business_evidence"]["objective_matched_business_unknown"] == 4
    assert "objective_matched_business_rejected" not in derived["outcome_classes_recomputed_from_business_evidence"]
    with Image.open(image) as figure:
        assert figure.format == "PNG"
    figure_data = json.loads(data.read_text())
    assert figure_data["n"] == 100
    assert figure_data["business_unverified"] == 92
    assert figure_data["delta_vs_z2"] == -4
    assert figure_data["claims"]["controlled_model_revision_ablation"] is False
