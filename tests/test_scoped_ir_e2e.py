import json

from scripts.scoped_ir_e2e import (
    analyze,
    audit,
    author_witness,
    current_cell,
    execution_guidance,
    repair_prompt,
    score_nlp4lp,
    semantic_feedback,
)
from scripts.scoped_ir_e2e_data import normalized_rows


def spec_for_x():
    return {"invariants": [
        {"invariant_id": "capacity", "kind": "constraint", "relation": "le",
         "lhs": {"path": "solution.variables.x"}, "rhs": 100,
         "source_span": "At most 100 units."},
        {"invariant_id": "objective", "kind": "objective", "relation": "eq",
         "lhs": {"path": "solution.objective"},
         "rhs": {"mul": [3, {"path": "solution.variables.x"}]},
         "source_span": "Each unit yields 3 profit."},
    ]}


def test_scoped_audit_produces_numeric_repair_feedback():
    question = "At most 100 units. Each unit yields 3 profit."
    solution = {"variables": {"x": 101}, "objective": 303}
    result = audit("scoped_ir", {"spec": spec_for_x()}, solution, question,
                   [current_cell(solution)], "p0")
    assert result["fired"] is True
    feedback = semantic_feedback(result)
    assert "capacity" in feedback
    assert "lhs=101.0" in feedback
    assert "rhs=100.0" in feedback
    assert "COMPLETE" in feedback


def test_scoped_clean_candidate_is_accepted_without_firing():
    question = "At most 100 units. Each unit yields 3 profit."
    solution = {"variables": {"x": 50}, "objective": 150}
    result = audit("scoped_ir", {"spec": spec_for_x()}, solution, question,
                   [current_cell(solution)], "p0")
    assert result["status"] == "ok"
    assert result["fired"] is False
    assert semantic_feedback(result) is None


def test_missing_solution_and_witness_are_not_violations():
    assert audit("zero", {}, None, "q", [], "p0")["status"] == "unknown"
    solution = {"variables": {"x": 1}, "objective": 3}
    result = audit("zero", {}, solution, "q", [current_cell(solution)], "p0")
    assert result["status"] == "unknown"
    assert result["fired"] is False


def test_repair_prompt_keeps_exact_schema():
    prompt = repair_prompt("problem", "x, y")
    assert "x, y" in prompt
    assert "variables" in prompt


def result(arm, initial=False, final=True, harmed=False, recovery=True):
    return {"arm": arm,
            "initial_score": {"business_correct": initial},
            "final_score": {"business_correct": final},
            "improved": not initial and final,
            "harmed_win": harmed,
            "semantic_recovery": recovery,
            "accepted_round": 1,
            "history": [{"audit": {"fired": True}}],
            "final_status": "accepted" if final else "unverified",
            "repair_calls": 1,
            "usage": {"total_tokens": 10},
            "latency_s": 2.0}


def test_analysis_counts_outcomes_and_cost(tmp_path):
    arm_dir = tmp_path / "p0" / "scoped_ir"
    arm_dir.mkdir(parents=True)
    (arm_dir / "final.json").write_text(json.dumps(result("scoped_ir")))
    analysis = analyze(tmp_path)
    summary = analysis["arms"]["scoped_ir"]
    assert summary["n"] == 1
    assert summary["initial_business_correct"] == 0
    assert summary["final_business_correct"] == 1
    assert summary["improved"] == 1
    assert summary["harmed_win"] == 0
    assert summary["semantic_recoveries"] == 1
    assert summary["tokens"] == 10
    assert (tmp_path / "analysis.json").exists()


def test_nlp4lp_score_uses_reference_and_public_objective():
    reference = next(row for row in normalized_rows() if row["id"] == "prob_016")
    clean = reference["solution"]
    scored = score_nlp4lp(reference, clean)
    assert scored["business_correct"] is True
    assert scored["semantic_valid"] is True
    assert scored["objective_absolute_error"] == 0.0
    changed = dict(clean)
    changed["objective"] = clean["objective"] + 1.0
    scored = score_nlp4lp(reference, changed)
    assert scored["business_correct"] is False
    assert scored["semantic_valid"] is False
    assert scored["objective_correct"] is False


def test_execution_guidance_names_exact_scip_sense():
    feedback = execution_guidance("fix script", {"stderr_tail": "unrecognized optimization sense: max"})
    assert '"maximize"' in feedback
    assert 'Do not repeat "max"' in feedback


def test_gate_rejects_bad_spec_and_uses_valid_fallback(tmp_path, monkeypatch):
    question = "parallel completion"
    wrong_spec = {"invariants": [{
        "invariant_id": "objective", "kind": "objective", "relation": "eq",
        "lhs": {"path": "solution.objective"},
        "rhs": {"add": [{"path": "solution.variables.x"},
                        {"path": "solution.variables.y"}]},
        "source_span": "parallel completion"}]}
    valid_spec = {"invariants": [{
        "invariant_id": "objective", "kind": "makespan", "relation": "eq",
        "lhs": {"path": "solution.objective"},
        "rhs": {"max": [{"path": "solution.variables.x"},
                        {"path": "solution.variables.y"}]},
        "source_span": "parallel completion"}]}
    cells = [
        {"key": "clean", "wrong": False, "mutation": "clean",
         "reference_violations": [],
         "solution": {"variables": {"x": 50, "y": 25}, "objective": 50.0}},
        {"key": "bad", "wrong": True, "mutation": "objective",
         "reference_violations": ["OBJECTIVE"],
         "solution": {"variables": {"x": 50, "y": 25}, "objective": 33.375}},
    ]
    fallback_dir = tmp_path / "fallback"
    (fallback_dir / "prob_104").mkdir(parents=True)
    (fallback_dir / "prob_104" / "spec.json").write_text(json.dumps(valid_spec))
    monkeypatch.setattr("scripts.scoped_ir_e2e.llm_mod.chat",
                        lambda *args, **kwargs: {"content": json.dumps(wrong_spec), "usage": {}})
    (tmp_path / "prob_104" / "scoped_ir").mkdir(parents=True)
    witness = author_witness("scoped_ir", question, cells,
                             tmp_path / "prob_104" / "scoped_ir", 0.2, {},
                             gate_cells=cells, fallback_dir=fallback_dir)
    assert witness["gate_fallback"] is True
    assert witness["spec"]["invariants"][0]["kind"] == "makespan"



def test_cached_witness_receives_independent_gate(tmp_path, monkeypatch):
    question = "At most 100 units. Each unit yields 3 profit."
    solution = {"variables": {"x": 50}, "objective": 150}
    wrong = {"variables": {"x": 101}, "objective": 303}
    cells = [
        {"key": "clean", "wrong": False, "mutation": "clean",
         "reference_violations": [], "solution": solution},
        {"key": "wrong", "wrong": True, "mutation": "capacity",
         "reference_violations": ["capacity"], "solution": wrong},
    ]
    problem_dir = tmp_path / "p0" / "scoped_ir"
    problem_dir.mkdir(parents=True)
    (problem_dir / "author.json").write_text(json.dumps({"spec": spec_for_x()}))

    def no_llm(*args, **kwargs):
        raise AssertionError("cached authoring must not call the LLM")

    monkeypatch.setattr("scripts.scoped_ir_e2e.llm_mod.chat", no_llm)
    witness = author_witness("scoped_ir", question, [], problem_dir, 0.2, {},
                             gate_cells=cells)
    assert witness["gate"]["accepted"] is True
    assert witness["spec"]["invariants"][0]["invariant_id"] == "capacity"
