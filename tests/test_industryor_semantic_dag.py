import json
from pathlib import Path

import pytest

from ora_agent.llm import LLMConfig
from scripts.industryor_semantic_dag import repair_prompt, run_one

ROOT = Path(__file__).resolve().parents[1]


def question(problem_id):
    rows = json.loads((ROOT / "data/industryor/IndustryOR.json").read_text())
    return next(row["en_question"] for row in rows if row["id"] == problem_id)


@pytest.mark.parametrize("problem_id", [9, 19, 20, 21])
def test_same_initial_local_and_sibling_dag_preserve_business_recovery(problem_id, tmp_path, monkeypatch):
    source = json.loads((ROOT / f"work/industryor_full_qwen_v0.1/prob_{problem_id:03d}/result.json").read_text())
    original_code = source["initial_code"]
    calls = []

    def fake_chat(*args, **kwargs):
        calls.append(1)
        return {"content": original_code, "model": "Qwen3_8-27B",
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                "latency_s": 0.5, "request_wall_s": 0.5, "retry_count": 0,
                "request_attempts": [{"attempt": 1, "outcome": "success", "latency_s": 0.5}]}

    monkeypatch.setattr("scripts.industryor_semantic_dag.llm_mod.chat", fake_chat)
    config = {"llm_config": LLMConfig("http://llm.local/v1", "test-key", "Qwen3_8-27B"),
              "public": {"test": True}}
    row = {"id": problem_id, "en_question": question(problem_id), "en_answer": source["reference"]}
    results = {result["arm"]: result for result in run_one(row, tmp_path, config, False)}
    baseline = results["bind_only"]
    single = results["single_line"]
    branch = results["branch_dag"]
    assert baseline["root_score"]["audit_status"] == "complete"
    assert baseline["final_score"]["business_correct"] is False
    assert baseline["accepted"] is False
    for result in (single, branch):
        assert result["root_score"]["business_correct"] is False
        assert result["final_score"]["business_correct"] is True
        assert result["business_recovered"] is True
        assert result["accepted"] is True
        assert result["selection_reason"] == "accepted_min_llm_solver_depth"
        assert result["reference_answer_used_for_selection"] is False
        assert any(node["action"] == "local_patch" for node in result["dag"]["nodes"]
                   if node["node_id"] in result["accepted_node_ids"])
    assert single["logical_repair_llm_calls"] == 0
    assert single["new_llm_calls"] == 0
    assert len(single["dag"]["nodes"]) == 2
    assert branch["logical_repair_llm_calls"] == 1
    assert branch["new_llm_calls"] == 1
    assert len(branch["dag"]["nodes"]) == 3
    assert {node["parent_id"] for node in branch["dag"]["nodes"] if node["node_id"] != "root"} == {"root"}
    assert len(branch["accepted_node_ids"]) == 1
    assert branch["dag"]["total_llm_calls"] == 1
    assert branch["dag"]["total_solver_runs"] == 1
    assert any(node["action"] == "regenerate" and node["execution"]["status"] == "duplicate"
               for node in branch["dag"]["nodes"])
    assert len(calls) == 1


def test_missing_business_roles_go_to_regeneration_feedback_not_reference_answer():
    gate = {"status": "needs_binding_evidence", "missing_semantic_names": ["x_A", "x_B"],
            "domain_mismatches": []}
    score = {"audit_status": "blocked", "violations": ["full variable-level business audit is blocked"]}
    prompt = repair_prompt("production question", "m.optimize()", gate, score, 48)
    assert "x_A" in prompt
    assert "x_B" in prompt
    assert "add the corresponding model variable" in prompt
    assert "en_answer" not in prompt
    assert "11250" not in prompt


def test_unregistered_problem_keeps_execution_feedback_without_business_acceptance():
    from scripts.industryor_semantic_dag import independent_score

    score = independent_score(1, {"solution_count": 1, "objective": 0.0})
    assert score["audit_status"] == "business_unverified"
    gate = {"status": "ready", "missing_semantic_names": [], "domain_mismatches": []}
    prompt = repair_prompt("test question", "m.optimize()", gate, score, 1,
                           record={"exec_status": "crash", "solver_status": None,
                                   "stderr_tail": "TypeError: bad API"},
                           memory_text="counterexample only")
    assert "business_unverified" in prompt
    assert "TypeError: bad API" in prompt
    assert "counterexample only" in prompt
    assert "[MEMORY ASSETS AND COUNTEREXAMPLES]" in prompt
    assert "[VALIDATED MEMORY" not in prompt
    assert "en_answer" not in prompt


def test_unknown_evidence_is_controller_compatible():
    from ora_agent.repair_controller import ProgressController
    from scripts.industryor_semantic_dag import audit_record

    audit = audit_record({"audit_status": "invalid_solution",
                          "violations": ["required variables are unavailable"]})
    assert audit["unknown_evidence"] == [{"detail": "required variables are unavailable"}]
    decision = ProgressController().decide("m.optimize()", {"exec_status": "ok"}, audit, 2)
    assert decision.action == "acquire_evidence"
