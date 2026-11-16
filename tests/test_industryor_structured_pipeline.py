import json

from scripts.industryor_structured_pipeline import generate_formations, needs_repair, run_dag

QUESTION = "Produce at most 10 chairs. Each chair yields 5 profit."
MODEL = {
    "parameters": [{"name": "limit", "value": 10, "source": "at most 10 chairs"}],
    "variables": [{"name": "chairs", "symbol": "x", "type": "integer", "bounds": [0, 10], "source": "chairs"}],
    "objective": {"direction": "maximize", "expression": "5*x", "variables": ["x"],
                  "source": "Each chair yields 5 profit"},
    "constraints": [{"name": "capacity", "expression": "x <= 10", "type": "<=",
                     "source": "at most 10 chairs"}],
}


def fake_record(messages, response):
    return {"messages": messages, "request": {}, "response": response,
            "new_llm_calls": 1, "reused": False}


def test_sequential_candidates_receive_prior_weak_points(tmp_path, monkeypatch):
    calls = []

    def fake_call(messages, path, config, temperature, max_tokens):
        calls.append(messages)
        text = messages[0]["content"]
        if "[CANDIDATE FORMULATION]" in text:
            content = json.dumps({"scores": {"parameters": 80, "variables": 80,
                                             "constraints": 45, "objective": 85},
                                  "weak_points": ["capacity needs a source check"]})
        else:
            content = json.dumps(MODEL)
        return fake_record(messages, {"content": content, "model": "Qwen3_8-27B", "usage": {}})

    monkeypatch.setattr("scripts.industryor_structured_pipeline.call_llm", fake_call)
    candidates, history = generate_formations(QUESTION, tmp_path, None)
    assert len(candidates) == 3
    assert len(history) == 3
    assert candidates[0]["schema_errors"] == []
    assert candidates[1]["schema_errors"] == []
    assert candidates[2]["schema_errors"] == []
    third_prompt = calls[4][0]["content"]
    assert "capacity needs a source check" in third_prompt
    assert "low-confidence dimensions" in third_prompt
    assert len(calls) == 6


def test_unregistered_optimal_result_does_not_trigger_unbounded_regeneration(tmp_path):
    selected = {"code": "m.optimize()", "objective": 100.0,
                "record": {"exec_status": "ok", "solver_status": "optimal", "objective": 100.0},
                "audit": {"gate": {"status": "ready", "aliases": {}, "repair_aliases": {}},
                          "solution": {"objective": 100.0, "solution_count": 1}, "score": None},
                "business_accepted": False}
    assert needs_repair(1, selected) is False
    selected["record"]["exec_status"] = "crash"
    assert needs_repair(1, selected) is True
    selected["business_accepted"] = True
    assert needs_repair(20, selected) is False


def test_unregistered_valid_result_stops_at_root_without_llm(tmp_path):
    selected = {"code": "m.optimize()", "objective": 100.0,
                "record": {"exec_status": "ok", "solver_status": "optimal", "objective": 100.0},
                "audit": {"gate": {"status": "ready", "aliases": {}, "repair_aliases": {}},
                          "solution": {"objective": 100.0, "solution_count": 1}, "score": None},
                "business_accepted": False}
    result = run_dag(1, "question", selected, tmp_path, tmp_path, None)
    assert result["objective"] == 100.0
    assert result["accepted"] is False
    assert result["repair_records"] == []
    assert result["dag"]["total_llm_calls"] == 0
    assert result["dag"]["nodes"][0]["stop_reason"] == "business_unverified"


def test_runner_error_recovers_saved_request_cost(tmp_path, monkeypatch):
    from scripts.industryor_structured_pipeline import safe_problem

    case = tmp_path / "prob_001"
    case.mkdir()
    record = {"messages": [{"role": "user", "content": "test problem"}], "request": {},
              "response": {"request_attempts": [{"attempt": 1, "outcome": "error"}]},
              "error": "HTTP 405", "new_llm_calls": 1, "reused": False}
    (case / "code_A.json").write_text(json.dumps(record))
    monkeypatch.setattr("scripts.industryor_structured_pipeline.run_problem",
                        lambda *args: (_ for _ in ()).throw(RuntimeError("service failed")))
    row = {"id": 1, "en_question": "test problem", "en_answer": "1"}
    results = safe_problem(row, tmp_path, {"public": {}, "llm_config": None}, False)
    assert results[0]["status"] == "runner_error"
    assert results[0]["cost"]["logical_llm_calls"] == 1
    assert results[0]["cost"]["new_llm_calls"] == 1
    assert results[0]["cost"]["api_attempts"] == 1
    assert results[0]["cost_accounting_complete"] is False
    assert results[0]["cost_source"] == "saved_artifacts"
