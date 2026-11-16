import json
from pathlib import Path

from ora_agent.llm import LLMConfig
from ora_agent.semantic_binding import propose_binding, reconcile_binding, validate_binding
from scripts.industryor_next_stage import instrument_code, score_solution
from scripts.industryor_scoped_loop import (
    binding_for,
    domain_binding_for,
    indicator_binding_for,
    repair_model,
)
from scripts.m1_pilot import run_code

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "work/industryor_full_qwen_v0.1"


def initial(problem_id):
    result = json.loads((RUN / f"prob_{problem_id:03d}/result.json").read_text())
    solution_path = RUN / f"prob_{problem_id:03d}/round_0/solution.json"
    solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
    return result["initial_code"], solution


def question(problem_id):
    rows = json.loads((ROOT / "data/industryor/IndustryOR.json").read_text())
    return next(row["en_question"] for row in rows if row["id"] == problem_id)


def test_singular_animal_names_bind_without_changing_model_semantics(tmp_path):
    code, solution = initial(4)
    aliases = {"x_cow": "x_cows", "x_sheep": "x_sheep", "x_chicken": "x_chickens"}
    gate = validate_binding(4, code, aliases, solution)
    assert gate["status"] == "ready"
    assert gate["repair_aliases"] == {"x_cows": "x_cow", "x_sheep": "x_sheep", "x_chickens": "x_chicken"}
    record = run_code(instrument_code(code, aliases), tmp_path)
    mapped = json.loads((tmp_path / "solution.json").read_text())
    score = score_solution(4, mapped)
    assert record["solver_status"] == "optimal"
    assert mapped["objective"] == solution["objective"]
    assert score["business_correct"] is True, score["violations"]


def test_roman_assignment_names_bind_at_export_without_ast_variable_rewriting(tmp_path):
    code, solution = initial(8)
    workers = ("I", "II", "III", "IV", "V")
    tasks = ("A", "B", "C", "D")
    aliases = {f"x_{worker}_{task}": f"x_{i}_{j}"
               for i, worker in enumerate(workers) for j, task in enumerate(tasks)}
    gate = validate_binding(8, code, aliases, solution)
    assert gate["status"] == "ready"
    assert gate["runtime_verification_required"] is True
    record = run_code(instrument_code(code, aliases), tmp_path)
    mapped = json.loads((tmp_path / "solution.json").read_text())
    score = score_solution(8, mapped)
    assert record["exec_status"] == "ok"
    assert mapped["objective"] == solution["objective"] == 14.0
    assert score["business_correct"] is True, score["violations"]


def test_toy_rebinding_exposes_real_indicator_hole_then_narrow_repair_recovers(tmp_path):
    code, solution = initial(20)
    aliases = {"R": "x1", "C": "x2", "B": "x3", "D": "x4",
               "y_R": "y1", "y_C": "y2", "y_B": "y3", "y_D": "y4"}
    gate = validate_binding(20, code, aliases, solution)
    assert gate["status"] == "ready"
    rebound = run_code(instrument_code(code, aliases), tmp_path / "rebound")
    rebound_solution = json.loads((tmp_path / "rebound/solution.json").read_text())
    rebound_score = score_solution(20, rebound_solution)
    assert rebound["solver_status"] == "optimal"
    assert rebound_score["audit_status"] == "complete"
    assert rebound_score["business_correct"] is False
    assert any(check["rule"].startswith("link_") and not check["passed"]
               for check in rebound_score["constraint_checks"])
    text = question(20)
    patched = repair_model(code, binding_for(20, text), indicator_binding_for(20, text),
                           domain_binding_for(20, text), gate["repair_aliases"])
    record = run_code(instrument_code(patched, aliases), tmp_path / "patched")
    mapped = json.loads((tmp_path / "patched/solution.json").read_text())
    score = score_solution(20, mapped)
    assert record["solver_status"] == "optimal"
    assert mapped["objective"] == 956.0
    assert score["business_correct"] is True, score["violations"]


def test_comprehension_variables_support_narrow_semantic_repair(tmp_path):
    code, solution = initial(19)
    aliases = {name: name for name in ("x_A", "x_B", "x_C", "y_A", "y_B")}
    gate = validate_binding(19, code, aliases, solution)
    assert gate["status"] == "ready"
    assert gate["repair_aliases"]["x_A"] == "x['A']"
    assert gate["repair_aliases"]["y_B"] == "y['B']"
    text = question(19)
    patched = repair_model(code, binding_for(19, text), indicator_binding_for(19, text),
                           domain_binding_for(19, text), gate["repair_aliases"])
    record = run_code(instrument_code(patched, aliases), tmp_path)
    mapped = json.loads((tmp_path / "solution.json").read_text())
    score = score_solution(19, mapped)
    assert record["solver_status"] == "optimal"
    assert mapped["objective"] == 4000.0
    assert score["business_correct"] is True, score["violations"]


def test_second_toy_family_uses_independent_indicator_evidence(tmp_path):
    code, solution = initial(9)
    aliases = {"T": "x1", "A": "x2", "B": "x3", "R": "x4", "yT": "y1", "yB": "y2"}
    gate = validate_binding(9, code, aliases, solution)
    assert gate["status"] == "ready"
    text = question(9)
    indicator = indicator_binding_for(9, text)
    assert indicator["links"][0]["source_evidence"]["reference"].endswith("prob_008/model.txt")
    patched = repair_model(code, binding_for(9, text), indicator,
                           domain_binding_for(9, text), gate["repair_aliases"])
    record = run_code(instrument_code(patched, aliases), tmp_path)
    mapped = json.loads((tmp_path / "solution.json").read_text())
    score = score_solution(9, mapped)
    assert record["solver_status"] == "optimal"
    assert score["business_correct"] is True, score["violations"]


def test_missing_or_hallucinated_bindings_fail_before_execution():
    code, solution = initial(20)
    aliases = {"R": "x1", "C": "x2", "B": "x3", "D": "x4",
               "y_R": "y1", "y_C": "y2", "y_B": "y3", "y_D": "y4"}
    missing = dict(aliases)
    del missing["y_D"]
    gate = validate_binding(20, code, missing, solution)
    assert gate["status"] == "needs_binding_evidence"
    assert gate["missing_semantic_names"] == ["y4"]
    hallucinated = dict(aliases, not_a_variable="y4")
    del hallucinated["y_D"]
    hallucinated["y_D"] = "not_a_variable"
    gate = validate_binding(20, code, hallucinated, solution)
    assert gate["status"] == "needs_binding_evidence"
    assert "not_a_variable" in gate["unresolved_solver_names"]


def test_llm_binding_is_only_a_cached_proposal_with_verbatim_code_evidence(tmp_path, monkeypatch):
    code, solution = initial(4)
    payload = {"aliases": [
        {"solver_name": "x_cow", "semantic_name": "x_cows", "evidence": 'x_cow = m.addVar("x_cow"'},
        {"solver_name": "x_sheep", "semantic_name": "x_sheep", "evidence": 'x_sheep = m.addVar("x_sheep"'},
        {"solver_name": "x_chicken", "semantic_name": "x_chickens", "evidence": 'x_chicken = m.addVar("x_chicken"'},
    ]}
    calls = []

    def fake_chat(*args, **kwargs):
        calls.append(1)
        return {"content": json.dumps(payload), "model": "Qwen3_8-27B",
                "usage": {"total_tokens": 100}, "latency_s": 0.5,
                "request_attempts": [{"attempt": 1, "outcome": "success", "latency_s": 0.5}]}

    monkeypatch.setattr("ora_agent.semantic_binding.llm_mod.chat", fake_chat)
    config = LLMConfig("http://llm.local/v1", "test-key", "Qwen3_8-27B")
    cache = tmp_path / "binding.json"
    first = propose_binding(4, question(4), code, solution, cache, config)
    second = propose_binding(4, question(4), code, solution, cache, config)
    assert len(calls) == 1
    assert first["new_llm_calls"] == 1
    assert second["new_llm_calls"] == 0
    assert first["gate"]["status"] == "ready"
    assert first["gate"]["business_correct"] is False
    assert "en_answer" not in first["prompt"]
    assert first["response"]["content"] == json.dumps(payload)
    assert first["api_attempts"] == 1


def test_regenerated_canonical_names_are_rebound_without_another_llm_call(tmp_path):
    dag = json.loads((ROOT / "work/industryor_semantic_dag_dev_v0.1/prob_048/branch_dag/dag.json").read_text())
    code = next(node["snapshot"] for node in dag["nodes"] if node["action"] == "regenerate")
    binding = json.loads((ROOT / "work/industryor_semantic_inner8_dev_v0.1/prob_048/binding.json").read_text())
    gate = reconcile_binding(48, code, binding["gate"]["aliases"])
    assert gate["status"] == "ready"
    assert gate["aliases"]["x_A"] == "x_A"
    assert gate["aliases"]["x_B"] == "x_B"
    assert gate["aliases"]["x_A_OT"] == "x_A_OT"
    assert gate["aliases"]["x_B_OT"] == "x_B_OT"
    assert "x_A_ot" not in gate["aliases"]
    assert "x_B_ot" not in gate["aliases"]
    assert gate["rebinding_required"] is False
    record = run_code(instrument_code(code, gate["aliases"]), tmp_path)
    solution = json.loads((tmp_path / "solution.json").read_text())
    score = score_solution(48, solution)
    assert record["solver_status"] == "optimal"
    assert solution["export"]["complete"] is True
    assert score["audit_status"] == "complete"
    assert score["optimality"] == "proven_optimal"
    assert all(check["passed"] for check in score["constraint_checks"])
    assert score["model_objective_consistent"] is False
    assert score["violations"] == ["reported model objective differs from the audited business objective"]
    assert score["business_correct"] is False
