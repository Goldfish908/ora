import json

from scripts.industryor_k3_pipeline import choose_with_llm, run_problem, selector_prompt


def response(content, model="Qwen3_8-27B"):
    return {"content": content, "model": model, "usage": {"total_tokens": 10},
            "latency_s": 0.1, "request_wall_s": 0.1,
            "request_attempts": [{"attempt": 1, "outcome": "success", "latency_s": 0.1}]}


def candidate(name, objective=None, accepted=False):
    return {"candidate_id": name, "code": "m.optimize()", "record": {"exec_status": "ok"},
            "objective": objective, "solution": None, "score": None,
            "gate": {"status": "ready", "aliases": {}}, "business_accepted": accepted,
            "generation_record": {"response": response("code"), "new_llm_calls": 1, "reused": False},
            "binding_record": None}


def test_max_min_selection_is_deterministic_and_does_not_read_answer(tmp_path, monkeypatch):
    selected = "B"
    scores = {name: {dimension: value for dimension in ("variables", "parameters", "constraints", "objective")}
              for name, value in (("A", 70), ("B", 90), ("C", 80))}
    record = {"response": response(json.dumps({"selected": selected, "scores": scores, "rationale": "test"})),
              "new_llm_calls": 1, "reused": False}
    monkeypatch.setattr("scripts.industryor_k3_pipeline.call_llm", lambda *args: record)
    candidates = [candidate("A", 1), candidate("B"), candidate("C", 3)]
    chosen, selection = choose_with_llm(20, "business question", candidates, tmp_path, None)
    assert chosen["candidate_id"] == "B"
    assert selection["method"] == "llm_max_min"
    assert selection["min_confidence"] == {"A": 70.0, "B": 90.0, "C": 80.0}
    prompt = selector_prompt("business question", candidates)
    assert "en_answer" not in prompt
    assert "reference_objective" not in prompt


def test_invalid_selector_json_falls_back_to_first_without_oracle(tmp_path, monkeypatch):
    record = {"response": response("not valid JSON"), "new_llm_calls": 1, "reused": False}
    monkeypatch.setattr("scripts.industryor_k3_pipeline.call_llm", lambda *args: record)
    candidates = [candidate("A", 1), candidate("B", 2), candidate("C", 3)]
    chosen, selection = choose_with_llm(20, "business question", candidates, tmp_path, None)
    assert chosen["candidate_id"] == "A"
    assert selection["method"] == "fallback_A_invalid_selector"
    assert "error" in selection


def test_missing_solution_does_not_break_oracle_or_change_selected_candidate(tmp_path, monkeypatch):
    candidates = [candidate("A", 100), candidate("B"), candidate("C", 200)]
    iterator = iter(candidates)
    monkeypatch.setattr("scripts.industryor_k3_pipeline.generate_candidate", lambda *args: next(iterator))
    monkeypatch.setattr("scripts.industryor_k3_pipeline.choose_with_llm",
                        lambda *args: (candidates[1], {"method": "mock", "record": None}))
    row = {"id": 20, "en_question": "test problem", "en_answer": "200"}
    result = run_problem(row, tmp_path, {"public": {}, "llm_config": None}, False)
    assert result["selected_candidate"] == "B"
    assert result["selected_match"] is False
    assert result["oracle_candidate"] == "C"
    assert result["oracle_match"] is True
    assert result["selection_missed_pool"] is True
    assert result["public_answer_used_for_selection"] is False
    assert result["oracle_not_deployable"] is True


def test_independent_business_acceptance_avoids_llm_selector(tmp_path, monkeypatch):
    candidates = [candidate("A", 100), candidate("B", 200, accepted=True), candidate("C", 300)]
    iterator = iter(candidates)
    monkeypatch.setattr("scripts.industryor_k3_pipeline.generate_candidate", lambda *args: next(iterator))

    def no_selector(*args):
        raise AssertionError("business-valid candidate must not need an LLM selector")

    monkeypatch.setattr("scripts.industryor_k3_pipeline.choose_with_llm", no_selector)
    row = {"id": 20, "en_question": "test problem", "en_answer": "200"}
    result = run_problem(row, tmp_path, {"public": {}, "llm_config": None}, False)
    assert result["selected_candidate"] == "B"
    assert result["selected_business_correct"] is True
    assert result["selection"]["method"] == "independent_business"
    assert result["selected_match"] is True
