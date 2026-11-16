import json

from scripts.precedence_lifecycle import run


def test_controlled_repair_has_source_replay_cost_and_nonpromotion(tmp_path):
    result = run(tmp_path)
    assert result["independent_business_correct"] is True
    assert result["registry_decision"] == "not_promoted_controlled_only"
    assert result["counterexample"]["kind"] == "single_position_job_index_swap"
    assert result["counterexample"]["invalid_bindings"]
    assert result["repair"]["non_time_constraints_preserved"] is True
    assert result["repair"]["llm_calls"] == 0
    assert result["replay"]["status"] == "optimal"
    assert result["replay"]["solution_objective"] == 81
    assert result["rollback"]["original_input_overwritten"] is False
    assert result["rollback"]["before_sha256"] == result["counterexample"]["before_sha256"]
    assert result["cost"] == {"new_llm_calls": 0, "tokens": 0, "solver_runs": 1}
    assert result["negative_results"]
    assert json.loads((tmp_path / "lifecycle.json").read_text()) == result
    assert (tmp_path / "wrong_model.json").is_file()
    assert (tmp_path / "repaired_model.json").is_file()
