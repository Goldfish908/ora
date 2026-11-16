import hashlib
import json

from scripts.precedence_reaudit import ROOT, run


def test_natural_reaudit_preserves_valid_alternatives(tmp_path):
    analysis = run(tmp_path)
    summary = analysis["summary"]
    assert summary["n"] == summary["reference_clean"] == 2
    assert summary["legacy_reference_correct"] == 0
    assert summary["independent_business_correct"] == 2
    assert summary["valid_alternative_formulations"] == 2
    assert summary["repair_required"] == 0
    assert summary["harmed_win"] == 0
    assert summary["accepted_but_business_incorrect"] == 0
    assert summary["new_llm_calls"] == 0
    assert summary["solver_runs_this_reaudit"] == 2
    rows = {row["id"]: row for row in analysis["results"]}
    assert rows["BWOR-024"]["formulation"] == "cut"
    assert rows["BWOR-025"]["formulation"] == "completion"
    assert rows["BWOR-025"]["index_semantics"] == "position_job"
    for problem_id, row in rows.items():
        assert row["repair_action"] == "not_required"
        assert row["legacy_reference_score"]["business_correct"] is False
        for source in row["inputs"].values():
            assert hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest() == source["sha256"]
        assert (tmp_path / problem_id / "audit.json").is_file()
