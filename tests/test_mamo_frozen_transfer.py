import json

from scripts.scoped_ir_mamo_reuse import run_transfer


def test_mamo_integer_transfer_rejects_missing_evidence_and_rolls_back(tmp_path):
    result = run_transfer(tmp_path)
    assert result["status"] == "rejected_missing_integer_evidence"
    assert result["gate"]["accepted"] is False
    assert result["gate"]["evaluation"]["unknown"] == 3
    assert result["gate"]["evaluation"]["rejected_count"] == 4
    assert result["initial_audit"]["status"] == "unknown"
    assert result["initial_score"]["objective_correct"] is False
    assert result["final_score"] == result["initial_score"]
    assert result["accepted"] is False
    assert result["improved"] is False
    assert result["harmed_win"] is False
    assert result["rollback"]["applied"] is True
    assert result["rollback"]["initial_solution_retained"] is True
    assert result["solver_runs_this_run"] == 0
    assert result["authoring_llm_calls"] == 0
    assert result["repair_llm_calls"] == 0
    assert result["independent_business_scoring_available"] is False
    assert result["negative_result"]["deployment_permitted"] is False
    assert (tmp_path / "analysis.json").is_file()
    assert json.loads((tmp_path / "analysis.json").read_text()) == result
