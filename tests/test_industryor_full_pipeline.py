import json
from pathlib import Path

import pytest

from scripts.industryor_full_pipeline import (
    baseline,
    safe_problem,
    toy_aliases,
)
from scripts.industryor_next_stage import instrument_code, score_solution
from scripts.industryor_scoped_loop import (
    binding_for,
    domain_binding_for,
    indicator_binding_for,
    repair_model,
)
from scripts.m1_pilot import extract_code, run_code

ROOT = Path(__file__).resolve().parents[1]


def test_old_baseline_is_recomputed_from_logs():
    result = baseline()
    assert result["z0"]["n"] == result["z1"]["n"] == result["z2"]["n"] == 100
    assert result["z0"]["objective_matches_abs_0_1"] == 35
    assert result["z1"]["objective_matches_abs_0_1"] == 60
    assert result["z2"]["objective_matches_abs_0_1"] == 74
    assert result["z0"]["objective_matches_relative_1pct"] == 39
    assert result["z1"]["objective_matches_relative_1pct"] == 67
    assert result["z2"]["objective_matches_relative_1pct"] == 79
    assert result["z2"]["llm_calls"] == 115


def test_safe_problem_preserves_failure_without_claiming_correctness(tmp_path):
    row = {"id": 19, "en_answer": "4000"}
    result = safe_problem(row, tmp_path, {"llm_config": None, "ids": [19]}, False)
    assert result["status"] == "runner_error"
    assert result["objective_match_abs_0_1"] is False
    assert result["accepted"] is False
    assert result["accepted_but_business_incorrect"] is False
    assert result["harmed_win"] is False
    assert result["llm_calls"] == 0
    assert "llm_config" not in result["run_config"]


def test_cached_generation_is_not_a_new_llm_call(tmp_path, monkeypatch):
    from ora_agent.llm import LLMConfig
    from scripts.industryor_full_pipeline import generation

    calls = []

    def fake_chat(*args, **kwargs):
        calls.append(1)
        return {"content": "from pyscipopt import Model\n", "model": "test-model",
                "usage": {"total_tokens": 10}, "latency_s": 1.25,
                "request_wall_s": 1.25, "retry_count": 0,
                "request_attempts": [{"attempt": 1, "outcome": "success", "latency_s": 1.25}]}

    monkeypatch.setattr("scripts.industryor_full_pipeline.llm_mod.chat", fake_chat)
    config = {"llm_config": LLMConfig("http://llm.local/v1", "test-key", "test-model")}
    messages = [{"role": "user", "content": "problem only"}]
    response, first = generation(tmp_path, 0, messages, config, tmp_path / "initial_response.json")
    cached_response, cached = generation(tmp_path, 0, messages, config, tmp_path / "initial_response.json")
    assert len(calls) == 1
    assert first["invoked_this_run"] is True
    assert first["reused"] is False
    assert cached["invoked_this_run"] is False
    assert cached["reused"] is True
    assert cached_response == response
    assert len(list(tmp_path.glob("generation_*.json"))) == 1


def test_runner_error_preserves_successful_generation_and_cost(tmp_path, monkeypatch):
    from ora_agent.llm import LLMConfig

    def fake_chat(*args, **kwargs):
        return {"content": "from pyscipopt import Model\n", "model": "test-model",
                "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
                "latency_s": 1.5, "request_wall_s": 1.5, "retry_count": 0,
                "request_attempts": [{"attempt": 1, "outcome": "success", "latency_s": 1.5}]}

    def fail_audit(problem_id):
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr("scripts.industryor_full_pipeline.llm_mod.chat", fake_chat)
    monkeypatch.setattr("scripts.industryor_full_pipeline.scoped_assets", fail_audit)
    config = {"llm_config": LLMConfig("http://llm.local/v1", "test-key", "test-model"), "ids": [1]}
    row = {"id": 1, "en_question": "A test problem", "en_answer": "1"}
    result = safe_problem(row, tmp_path, config, False)
    case = tmp_path / "prob_001"
    assert result["status"] == "runner_error"
    assert result["llm_calls"] == 1
    assert result["new_llm_calls"] == 1
    assert result["api_attempts"] == 1
    assert result["total_tokens"] == 12
    assert result["llm_latency_s"] == 1.5
    assert result["objective_match_abs_0_1"] is False
    assert result["accepted"] is False
    assert result["retry_accounting_complete"] is True
    assert (case / "generation_00.json").is_file()
    assert (case / "initial_response.json").is_file()
    assert (case / "initial.py").is_file()
    assert "api_key" not in json.dumps(result["run_config"])


def test_invalid_business_evidence_is_unknown_not_business_rejected():
    from scripts.industryor_full_pipeline import failure_classification

    row = {"objective_match_abs_0_1": True, "objective": 14.0,
           "business_unverified": False, "exec_status": "ok",
           "final_score": {"audit_status": "invalid_solution", "business_correct": False}}
    assert failure_classification(row) == "objective_matched_business_unknown"
    row["final_score"]["audit_status"] = "complete"
    assert failure_classification(row) == "objective_matched_business_rejected"
    row["objective_match_abs_0_1"] = False
    row["final_score"]["audit_status"] = "invalid_solution"
    assert failure_classification(row) == "objective_mismatch_business_unknown"


def test_toy_alias_repair_preserves_solver_variables_and_passes_independent_audit(tmp_path):
    case = ROOT / "work/industryor_full_smoke_v0.1/prob_020"
    response = json.loads((case / "initial_response.json").read_text())
    code = extract_code(response["content"])
    manifest = json.loads((ROOT / "assets/industryor_next_stage/manifest.json").read_text())
    question = next(row["question"] for row in manifest["problems"] if row["id"] == 20)
    aliases, export_aliases = toy_aliases(code)
    assert aliases["x1"] == "R"
    assert aliases["x4"] == "D"
    assert aliases["y1"] == "y"
    assert aliases["y2"] == "z"
    assert export_aliases["R"] == "x1"
    patched = repair_model(code, binding_for(20, question), indicator_binding_for(20, question),
                           domain_binding_for(20, question), aliases)
    assert "R = m.addVar('R', vtype='I', lb=0, ub=40)" in patched
    assert "y = m.addVar('y', vtype='B')" in patched
    assert "z = m.addVar('z', vtype='B')" in patched
    assert "y3 = m.addVar('y3', vtype='B')" in patched
    assert "y4 = m.addVar('y4', vtype='B')" in patched
    assert "m.addCons(y <= R" in patched
    assert "m.addCons(z <= C" in patched
    assert "m.addCons(y3 <= B" in patched
    assert "m.addCons(y4 <= D" in patched
    instrumented = instrument_code(patched, export_aliases)
    record = run_code(instrumented, tmp_path / "nested/sandbox")
    solution = json.loads((tmp_path / "nested/sandbox/solution.json").read_text())
    score = score_solution(20, solution)
    assert record["exec_status"] == "ok"
    assert record["solver_status"] == "optimal"
    assert solution["export"]["complete"] is True
    assert "R" not in solution["variables"]
    assert "y" not in solution["variables"]
    assert set(f"x{i}" for i in range(1, 5)) <= set(solution["variables"])
    assert set(f"y{i}" for i in range(1, 5)) <= set(solution["variables"])
    assert score["business_correct"] is True, score["violations"]
    assert (tmp_path / "nested/sandbox/stdout.txt").is_file()
    assert (tmp_path / "nested/sandbox/stderr.txt").is_file()


def test_alias_export_rejects_duplicate_destinations_and_runtime_collisions(tmp_path):
    source = ("from pyscipopt import Model\n"
              "m = Model()\nm.hideOutput()\n"
              "R = m.addVar('R')\nx1 = m.addVar('x1')\n"
              "m.optimize()\nprint(f'status: {m.getStatus()}')\n")
    with pytest.raises(ValueError, match="unique destination"):
        instrument_code(source, {"R": "x1", "C": "x1"})
    code = instrument_code(source, {"R": "x1"})
    record = run_code(code, tmp_path)
    solution = json.loads((tmp_path / "solution.json").read_text())
    assert record["exec_status"] == "ok"
    assert solution["export"]["complete"] is False
    assert "collide" in solution["export"]["error"]
    assert solution["variables"] == {}


def test_smoke_artifacts_have_shared_prompts_real_responses_and_safe_dags():
    root = ROOT / "work/industryor_full_smoke_v0.2"
    analysis = json.loads((root / "analysis.json").read_text())
    assert analysis["summary"]["n"] == 4
    for row in analysis["results"]:
        case = root / f"prob_{row['id']:03d}"
        initial = json.loads((case / "initial_response.json").read_text())
        generation = json.loads((case / "generation_00.json").read_text())
        assert initial["prompt_sha256"] == row["prompt_sha256"]
        assert initial["model"] == "Qwen3_8-27B"
        assert initial["content"]
        assert generation["response"] == initial
        assert generation["messages"][0]["content"] == (case / "prompt.txt").read_text()
        assert row["public_answer_hidden_from_prompt"] is True
        assert row["accepted_but_business_incorrect"] is False
        assert row["harmed_win"] is False
        assert row["dag"]["score_based_pruning"] is False
        assert row["dag"]["nodes"]
        assert row["dag"]["nodes"][0]["node_id"] == "root"
        assert all(node["snapshot"] for node in row["dag"]["nodes"])
        assert row["history"]
        assert row["final_code"]
        assert row["status"] == "completed", row.get("error")
        assert row["llm_latency_s"] > 0
        assert "api_key" not in json.dumps(row["run_config"])
        if row["id"] in (19, 20, 21):
            assert row["final_score"]["audit_status"] == "complete"
    by_id = {row["id"]: row for row in analysis["results"]}
    assert by_id[19]["final_score"]["business_correct"] is True
    assert by_id[20]["final_score"]["business_correct"] is True
    assert by_id[8]["final_score"]["business_correct"] is True
    assert any(event["type"] == "rollback" for event in by_id[8]["dag"]["events"])
