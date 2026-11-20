import json
from pathlib import Path

from scripts.cleanroom_report import build


def test_report_separates_direct_dag_and_unrun_memory(tmp_path):
    run = tmp_path / "gepa"
    run.mkdir()
    (run / "analysis.json").write_text(json.dumps({"curves": [
        {"candidate_idx": 0, "official_proxy_mean": 0.0, "n": 2, "proxy_match": 1,
         "true_correct": 0, "phantom_proxy": 1, "unknown": 1, "mean_quality": 0.2},
        {"candidate_idx": 1, "official_proxy_mean": 1.0, "n": 2, "proxy_match": 2,
         "true_correct": 2, "phantom_proxy": 0, "unknown": 0, "mean_quality": 1.2},
    ]}))
    repair = tmp_path / "repair_result.json"
    repair.write_text(json.dumps({
        "status": "accepted", "before": {"execution_contract": "fail"},
        "after": {"execution_contract": "pass"},
        "record": {"task": "task", "true_correct": True, "quality": 1.0, "objective": 4.0}}))
    result = build(run, [repair], None, tmp_path / "out")
    assert result["direct"][0]["arm"] == "B0_empty_specification"
    assert result["direct"][1]["true_correct"] == 2
    assert result["residual_dag"][0]["status"] == "accepted"
    assert result["memory"]["status"] == "not_run"
    assert "not full-validation accuracy" in (tmp_path / "out/report.md").read_text()
