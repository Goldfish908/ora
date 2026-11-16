from scripts.precedence_controls import POLICIES, run_controls
from scripts.precedence_reaudit import run


def test_natural_valid_models_stop_at_round_zero_across_all_arms(tmp_path):
    analysis = run_controls(run(tmp_path), tmp_path)
    for policy in POLICIES:
        arm = analysis["arms"][policy]
        assert arm["n"] == arm["initial_business_correct"] == 2
        assert arm["final_business_correct"] == 2
        assert arm["recoveries"] == 0
        assert arm["round0_unchanged"] == 2
        assert arm["harmed_win"] == 0
        assert arm["accepted_but_business_incorrect"] == 0
        assert arm["baseline_fallback"] == 0
        assert arm["deterministic_transforms"] == 0
        assert arm["solver_runs_this_run"] == 0
        assert arm["llm_calls"] == arm["tokens"] == 0
    for row in analysis["control_results"]:
        assert row["initial_model_sha256"] == row["final_model_sha256"]
        assert row["accepted_round"] == 0
        assert row["stop_reason"] == "accepted"
        assert row["history"][0]["action"] == "accept"
    assert analysis["candidate_dag"]["status"] == "not_run_no_natural_repair_opportunity"
    assert analysis["candidate_dag"]["simulated_recoveries_claimed"] is False
