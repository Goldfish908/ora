from ora_agent.dvsa_repair import score_solution, select_win_safe_solution
from scripts.dvsa_win_safe_replay import run_replay
from tests.test_dvsa_repair import reference


def test_fallback_only_when_initial_win_would_be_harmed():
    ref = reference()
    initial = {"variables": {"x": 2, "y": 2}, "objective": 4}
    initial_score = score_solution(ref, initial, 4)
    bad = {"variables": {"x": 3, "y": 2}, "objective": 4}
    selected = select_win_safe_solution(ref, initial, initial_score, bad, 4)
    assert selected["baseline_fallback"] is True
    assert selected["solution"] == initial
    assert selected["score"]["business_correct"] is True
    assert selected["candidate_score"]["business_correct"] is False


def test_good_candidate_is_not_replaced_when_initial_is_wrong():
    ref = reference()
    initial = {"variables": {"x": 0, "y": 0}, "objective": 0}
    initial_score = score_solution(ref, initial, 4)
    good = {"variables": {"x": 2, "y": 2}, "objective": 4}
    selected = select_win_safe_solution(ref, initial, initial_score, good, 4)
    assert selected["baseline_fallback"] is False
    assert selected["solution"] == good
    assert selected["score"]["business_correct"] is True


def test_retailopt_replay_prevents_real_harmed_win_without_new_calls(tmp_path):
    analysis = run_replay("dev", tmp_path)
    no_memory = analysis["summary"]["no_memory"]
    assert no_memory["original_final_business_correct"] == 5
    assert no_memory["safe_final_business_correct"] == 6
    assert no_memory["original_harmed_win"] == 1
    assert no_memory["safe_harmed_win"] == 0
    assert no_memory["baseline_fallback"] == 1
    assert no_memory["replay_llm_calls"] == 0
    harmed = next(row for row in analysis["results"]
                  if row["id"] == "retail_f2_price_band_tight_v0" and row["arm"] == "no_memory")
    assert harmed["original_harmed_win"] is True
    assert harmed["safe_harmed_win"] is False
    assert harmed["baseline_fallback"] is True
    assert harmed["safe_final_score"]["business_correct"] is True
    for arm in ("text_memory", "dvsa", "direct_legacy_witness"):
        assert analysis["summary"][arm]["safe_harmed_win"] == 0
    for row in analysis["results"]:
        assert row["accepted"] is row["safe_final_score"]["business_correct"]
        assert row["accepted_but_business_incorrect"] is False
        assert analysis["summary"][row["arm"]]["accepted_but_business_incorrect"] == 0
