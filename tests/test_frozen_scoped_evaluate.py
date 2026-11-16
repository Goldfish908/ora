import json

from ora_agent.dvsa_repair import score_solution
from scripts import bwor_scoped_loop
from scripts.frozen_scoped_evaluate import load_case, prepare_case, run_problem


def reference(tmp_path):
    model = {"schema_version": "dvsa.model.v0.1", "problem_id": "BWOR-002",
             "variables": {"x": {"domain": "real", "lb": 0, "ub": None}},
             "data": {}, "constraints": [{"constraint_id": "nonnegative", "source": "Minimize x.",
                                           "relation": "ge", "lhs": {"var": "x"}, "rhs": 0}],
             "objective": {"sense": "minimize", "expression": {"var": "x"}},
             "assumptions": [], "modeling_conflicts": []}
    solution = {"variables": {"x": 1.0}, "objective": 1.0}
    model_path = tmp_path / "reference/model.json"
    solution_path = tmp_path / "reference/solution.json"
    question_path = tmp_path / "reference/question.txt"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(model))
    solution_path.write_text(json.dumps(solution))
    question_path.write_text("Minimize x.")
    return {"model": model, "solution": solution, "model_path": model_path,
            "solution_path": solution_path, "question_path": question_path,
            "question": "Minimize x.", "revision": "initial"}


def initial(tmp_path, ref, valid):
    directory = tmp_path / "BWOR-002/initial"
    directory.mkdir(parents=True, exist_ok=True)
    result = {"status": "initial_scored" if valid else "invalid_candidate",
              "generator": {"model_id": "test", "revision": "abc"},
              "score": score_solution(ref, ref["solution"] if valid else None, 1.0)}
    if valid:
        (directory / "candidate.json").write_text(json.dumps(ref["model"]))
        (directory / "solution.json").write_text(json.dumps(ref["solution"]))
        result["solve"] = {"status": "optimal"}
    (directory / "result.json").write_text(json.dumps(result))


def test_load_case_preserves_valid_initial_and_round_zero_win(tmp_path, monkeypatch):
    ref = reference(tmp_path)
    initial(tmp_path, ref, True)
    monkeypatch.setattr("scripts.frozen_scoped_evaluate.OUT", tmp_path)
    monkeypatch.setattr("scripts.frozen_scoped_evaluate.select_reference", lambda *args: ref)
    monkeypatch.setattr(bwor_scoped_loop, "relative", lambda path: str(path))
    case = load_case("BWOR-002", {"BWOR-002": 1.0})
    assert case["initial_score"]["business_correct"] is True
    prepared = prepare_case(case)
    assert prepared["gate"]["accepted"] is True
    result = run_problem(prepared, "fixed", tmp_path / "out")
    assert result["accepted_round"] == 0
    assert result["round0_unchanged"] is True
    assert result["final_score"]["business_correct"] is True
    assert result["harmed_win"] is False


def test_invalid_initial_stays_in_denominator_without_fabricated_solution(tmp_path, monkeypatch):
    ref = reference(tmp_path)
    initial(tmp_path, ref, False)
    monkeypatch.setattr("scripts.frozen_scoped_evaluate.OUT", tmp_path)
    monkeypatch.setattr("scripts.frozen_scoped_evaluate.select_reference", lambda *args: ref)
    monkeypatch.setattr(bwor_scoped_loop, "relative", lambda path: str(path))
    case = load_case("BWOR-002", {"BWOR-002": 1.0})
    assert case["eligible"] is True
    assert case["initial"]["solution"] is None
    assert case["initial_score"]["business_correct"] is False
    assert case["initial_generation_status"] == "invalid_candidate"
    prepared = prepare_case(case)
    assert prepared["gate"]["accepted"] is False
    result = run_problem(prepared, "fixed", tmp_path / "out")
    assert result["baseline_fallback"] is True
    assert result["final_score"]["business_correct"] is False
    assert result["negative_result"]["kind"] == "unrecovered_natural_initial_error"
