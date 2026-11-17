from scripts.industryor_hybrid_selector import select_candidate


def candidate(name, source, objective=1.0, accepted=False, exec_status="ok", solver_status="optimal"):
    return {"candidate_id": name, "source": source, "source_id": 1, "code": f"{source} code",
            "objective": objective, "business_accepted": accepted,
            "business_unverified": not accepted, "score": {"business_correct": accepted},
            "record": {"exec_status": exec_status, "solver_status": solver_status, "export_error": None},
            "solution": {"solution_count": 1, "objective": objective,
                         "export": {"complete": True}} if exec_status == "ok" else None}


def test_same_objective_preserves_full_without_llm(tmp_path, monkeypatch):
    full = candidate("A", "structured_full")
    raw = candidate("B", "raw_selected")
    monkeypatch.setattr("scripts.industryor_hybrid_selector.choose_with_llm",
                        lambda *args: (_ for _ in ()).throw(AssertionError("unexpected LLM call")))
    selected, selection, records = select_candidate("question", full, raw, tmp_path, None)
    assert selected["source"] == "structured_full"
    assert selection["method"] == "same_objective_preserve_full"
    assert records == []


def test_independent_business_acceptance_has_priority(tmp_path, monkeypatch):
    full = candidate("A", "structured_full")
    raw = candidate("B", "raw_selected", accepted=True)
    monkeypatch.setattr("scripts.industryor_hybrid_selector.choose_with_llm",
                        lambda *args: (_ for _ in ()).throw(AssertionError("unexpected LLM call")))
    selected, selection, _ = select_candidate("question", full, raw, tmp_path, None)
    assert selected["source"] == "raw_selected"
    assert selection["method"] == "independent_business"


def test_complete_execution_beats_incomplete_candidate(tmp_path):
    full = candidate("A", "structured_full", objective=None, exec_status="crash", solver_status=None)
    raw = candidate("B", "raw_selected", objective=35.0)
    selected, selection, records = select_candidate("question", full, raw, tmp_path, None)
    assert selected["source"] == "raw_selected"
    assert selection["method"] == "complete_execution"
    assert records == []


def test_different_valid_candidates_use_existing_max_min_selector(tmp_path, monkeypatch):
    full = candidate("A", "structured_full", objective=100.0)
    raw = candidate("B", "raw_selected", objective=200.0)
    calls = []

    def fake_choose(problem_id, question, candidates, case, config):
        calls.append((problem_id, question, candidates))
        return raw, {"method": "llm_max_min", "record": {"messages": [{"role": "user", "content": question}],
                                                         "new_llm_calls": 1, "reused": False,
                                                         "response": {"usage": {}}}}

    monkeypatch.setattr("scripts.industryor_hybrid_selector.choose_with_llm", fake_choose)
    selected, selection, records = select_candidate("question only", full, raw, tmp_path, None)
    assert selected["source"] == "raw_selected"
    assert selection["method"] == "llm_max_min"
    assert len(records) == 1
    assert calls[0][1] == "question only"
    assert [item["candidate_id"] for item in calls[0][2]] == ["A", "B"]


def test_three_replay_majority_is_deterministic():
    from scripts.industryor_hybrid_ensemble import majority_source

    assert majority_source(["raw_selected", "structured_full", "raw_selected"]) == "raw_selected"
    assert majority_source(["structured_full", "structured_full", "raw_selected"]) == "structured_full"
    assert majority_source(["structured_full"] * 3) == "structured_full"
    assert majority_source(["raw_selected"] * 3) == "raw_selected"
