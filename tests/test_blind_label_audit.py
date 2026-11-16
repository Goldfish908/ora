import json

from scripts.bwor_candidate_blind_audit import run_audit
from scripts.bwor_scoped_loop import validation_cells


def test_constraint_errors_are_not_mislabelled_as_objective_errors():
    solution = {"variables": {"x": 1.0}, "objective": 1.0}
    case = {"initial_score": {"business_correct": False, "reference_audit": {
                "violations": [{"rule": "C14"}, {"rule": "C25"}]}},
            "initial": {"solution": solution},
            "reference": {"solution": solution}}
    natural = validation_cells(case)[1]
    assert natural["wrong"] is True
    assert natural["mutation"] == "natural_initial_reference_error"
    assert natural["reference_violations"] == ["C14", "C25"]


def test_posthoc_label_correction_preserves_original_decisions(tmp_path):
    result = run_audit(tmp_path)
    assert result["status"] == "posthoc_label_correction_no_replay"
    assert result["behavior_changed"] is False
    assert result["new_llm_calls"] == result["new_solver_runs"] == 0
    rows = {row["id"]: row for row in result["rows"]}
    for problem_id in ("BWOR-024", "BWOR-025"):
        row = rows[problem_id]
        assert row["original_label"]["mutation"] == "natural_initial_objective_error"
        assert row["corrected_label"]["mutation"] == "natural_initial_reference_error"
        assert row["corrected_label"]["reference_violations"][0] != "business_objective"
        assert row["decision_evidence_unchanged"]["gate_accepted"] is False
    for problem_id in ("BWOR-013", "BWOR-018", "BWOR-019", "BWOR-021"):
        assert rows[problem_id]["corrected_label"] == {
            "mutation": "natural_initial_clean", "reference_violations": []}
    assert (tmp_path / "label_audit.json").is_file()
