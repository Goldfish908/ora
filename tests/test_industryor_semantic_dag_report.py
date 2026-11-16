import json
from pathlib import Path

from PIL import Image

from scripts.industryor_semantic_dag_report import build_report, validate

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "work/industryor_semantic_dag_dev_v0.2"


def test_v02_rebinding_artifacts_and_report_keep_business_failures_visible(tmp_path):
    validation = validate(RUN)
    assert validation["results"] == 24
    assert validation["business_scores_recomputed"] == 32
    assert validation["generation_records_verified"] == 5
    assert validation["source_snapshots_verified"] == 9
    report, image, data = build_report(RUN, tmp_path / "report.md", tmp_path, "v0.2")
    text = report.read_text()
    assert "可完整审计" in text
    assert "逻辑修复调用差为 **+4**" in text
    assert "重生成响应回放" in text
    payload = json.loads(data.read_text())
    assert payload["audit_complete_problem_ids"]["single_line"] == [4, 8, 9, 19, 20, 21, 25, 48]
    assert payload["arms"]["single_line"]["final_business_correct"] == 7
    assert payload["arms"]["branch_dag"]["final_business_correct"] == 7
    assert payload["arms"]["single_line"]["new_llm_calls"] == 0
    assert payload["arms"]["branch_dag"]["new_llm_calls"] == 0
    assert payload["dag_minus_single_logical_llm_calls"] == 4
    assert payload["claims"]["heldout"] is False
    with Image.open(image) as figure:
        assert figure.format == "PNG"
    analysis = json.loads((RUN / "analysis.json").read_text())
    row48 = next(row for row in analysis["results"] if row["id"] == 48 and row["arm"] == "branch_dag")
    regenerate = next(node for node in row48["dag"]["nodes"] if node["action"] == "regenerate")
    assert regenerate["business_audit"]["audit_status"] == "complete"
    assert regenerate["business_audit"]["business_correct"] is False
    assert regenerate["business_audit"]["model_objective_consistent"] is False
    assert row48["accepted"] is False
    manifest = json.loads((RUN / "manifest.json").read_text())
    assert len(manifest["results"]) == 24
    assert manifest["audit_complete_problem_ids"]["branch_dag"] == [4, 8, 9, 19, 20, 21, 25, 48]
