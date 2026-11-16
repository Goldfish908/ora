import json

from scripts.dvsa_retail_repair_analyze import load_arm


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_load_arm_aggregates_feedback_and_execution_recovery(tmp_path):
    parent = {"scenario_id": "s", "arm": "dvsa", "initial_code_sha256": "abc",
              "initial_score": {"business_correct": False}, "repair_trigger": "dvsa_violation",
              "feedback": {"status": "VIOLATED"}, "llm_calls": 1, "solver_calls": 1,
              "usage": {"total_tokens": 10}, "llm_latency_s": 2,
              "run": {"wall_s": 1}, "status": "repair_executed",
              "final_score": {"status": "no_solution", "business_correct": False},
              "improved": False, "harmed_win": False}
    recovery = {"scenario_id": "s", "arm": "dvsa", "repair_trigger": "execution_recovery_after_feedback",
                "initial_score": {"business_correct": False}, "llm_calls": 1, "solver_calls": 1,
                "usage": {"total_tokens": 20}, "llm_latency_s": 3,
                "run": {"wall_s": 4}, "status": "execution_recovery_scored",
                "final_score": {"status": "scored", "business_correct": True},
                "improved": True, "harmed_win": False}
    write(tmp_path / "result.json", parent)
    write(tmp_path / "execution_recovery/result.json", recovery)
    result = load_arm(tmp_path)
    assert result["final_score"]["business_correct"] is True
    assert result["execution_recovery_used"] is True
    assert result["llm_calls"] == 2
    assert result["solver_calls"] == 2
    assert result["total_tokens"] == 30
    assert result["llm_latency_s"] == 5
    assert result["solver_wall_s"] == 5
    assert result["repair_trigger"] == "dvsa_violation"
