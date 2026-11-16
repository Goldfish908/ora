import json

import pytest

from ora_agent.scoped_assets import compile_asset, load_asset
from scripts.industryor_next_stage import load_problem
from scripts.industryor_scoped_loop import (
    CASES,
    DOMAIN_TEMPLATE,
    IDS,
    TEMPLATE,
    binding_for,
    domain_binding_for,
    independent_clean,
    repair_integer_variables,
    repair_objective,
    run_all,
    run_problem,
    validation_cells,
)
from scripts.scoped_ir_gate import gate


def question(problem_id):
    manifest = json.loads(open("assets/industryor_next_stage/manifest.json").read())
    return next(row for row in manifest["problems"] if row["id"] == problem_id)["question"]


@pytest.mark.parametrize("problem_id", [19, 21])
def test_independent_reference_cells_validate_natural_objective_error(problem_id):
    problem = load_problem(problem_id)
    binding = binding_for(problem_id, question(problem_id))
    spec = compile_asset(load_asset(TEMPLATE), binding)
    cells = validation_cells(problem_id, problem.solution)
    assert problem.scorer(cells[0]["solution"])["business_correct"] is True
    assert problem.scorer(cells[1]["solution"])["business_correct"] is False
    assert problem.scorer(cells[2]["solution"])["business_correct"] is False
    result = gate(spec, question(problem_id), cells[:3], str(problem_id))
    assert result["accepted"] is True
    assert result["evaluation"]["records"][1]["fired"] is True


def test_objective_patch_recovers_real_scip_solution_without_llm(tmp_path):
    result = run_problem(19, "fixed", tmp_path)
    assert result["initial_score"]["business_correct"] is False
    assert result["final_score"]["business_correct"] is True
    assert result["semantic_recovery"] is True
    assert result["accepted_but_business_incorrect"] is False
    assert result["llm_calls"] == 0
    assert result["tokens"] == 0
    assert result["solver_runs_this_run"] == 1
    assert result["harmed_win"] is False


def test_full_cohort_has_shared_positive_result_and_preserves_wins(tmp_path):
    analysis = run_all(tmp_path / "cohort")
    assert analysis["arms"]["no_repair"]["initial_business_correct"] == 3
    assert analysis["arms"]["no_repair"]["final_business_correct"] == 3
    for policy in ("fixed", "progress"):
        arm = analysis["arms"][policy]
        assert arm["n"] == len(IDS)
        assert arm["final_business_correct"] == 6
        assert arm["improved"] == 3
        assert arm["semantic_recoveries"] == 3
        assert arm["not_applicable"] == 4
        assert arm["harmed_win"] == 0
        assert arm["accepted_but_business_incorrect"] == 0
        assert arm["llm_calls"] == 0
        assert arm["solver_runs_this_run"] == 3
    for row in analysis["results"]:
        if row["id"] in CASES or row["policy"] == "no_repair":
            continue
        assert row["status"] == "not_applicable"
        assert row["initial_code"] == row["final_code"]
        assert row["initial_score"] == row["final_score"]


def test_cache_requires_identical_run_configuration(tmp_path):
    outdir = tmp_path / "cache"
    first = run_all(outdir, ids=(19,))
    assert run_all(outdir, ids=(19,), resume=True) == first
    with pytest.raises(ValueError, match="different configuration"):
        run_all(outdir, ids=(19,), resume=True, max_repairs=1)
    with pytest.raises(ValueError, match="different configuration"):
        run_all(outdir, ids=(19,), resume=False)


def test_objective_patch_rejects_unbound_solver_variable():
    binding = {"terms": [{"path": "solution.variables.missing", "coefficient": 2}]}
    with pytest.raises(ValueError, match="no matching PySCIPOpt variable"):
        repair_objective("m.setObjective(x, 'minimize')\nx = 1\n", binding)


def test_independent_clean_uses_question_business_constraints():
    solution = independent_clean(21, load_problem(21).solution)
    variables = solution["variables"]
    tables = 20 * variables["x_A"] + 15 * variables["x_B"] + 15 * variables["x_C"]
    assert 150 <= tables <= 600
    assert variables["x_A"] <= 0 or variables["x_B"] >= 2
    assert variables["x_B"] <= 0 or variables["x_C"] >= 1


def test_integer_patch_is_limited_to_independently_bound_variables():
    code = ("x1 = m.addVar('x1', vtype='C')\n"
            "aux = m.addVar('aux', lb=0)\n"
            "y1 = m.addVar('y1', vtype='B')\n")
    binding = {"terms": [{"path": "solution.variables.x1"}]}
    patched = repair_integer_variables(code, binding)
    assert "x1 = m.addVar('x1', vtype='I')" in patched
    assert "aux = m.addVar('aux', lb=0)" in patched
    assert "y1 = m.addVar('y1', vtype='B')" in patched
    with pytest.raises(ValueError, match="expected one PySCIPOpt declaration"):
        repair_integer_variables(code, {"terms": [{"path": "solution.variables.missing"}]})
    with pytest.raises(ValueError, match="expected one PySCIPOpt declaration"):
        repair_integer_variables(code + "x1 = m.addVar('x1', vtype='C')\n", binding)
    with pytest.raises(ValueError, match="invalid integer variable path"):
        repair_integer_variables(code, {"terms": [{"path": "data.x1"}]})


def test_toy_domain_has_traceable_reference_and_independent_counterexamples():
    binding = domain_binding_for(20, question(20))
    evidence = binding["source_evidence"]
    assert evidence["reference"].endswith("prob_019/model.txt")
    assert "Integer variable" in evidence["span"]
    assert evidence["span"] in evidence["text"]
    assert "independent_validation" not in binding
    spec = compile_asset(load_asset(DOMAIN_TEMPLATE), binding)
    cells = validation_cells(20, load_problem(20).solution)
    assert [cell["key"] for cell in cells] == [
        "independent_clean", "natural_initial", "wrong_objective", "clean_zero",
        "clean_positive", "wrong_domain", "wrong_indicator_off", "wrong_indicator_on",
    ]
    result = gate(spec, question(20), cells[3:], "20")
    assert result["accepted"] is False
    assert result["evaluation"]["records"][2]["fired"] is True
    problem = load_problem(20)
    assert problem.scorer(cells[0]["solution"])["business_correct"] is True
    for cell in cells[1:]:
        if cell["wrong"]:
            assert problem.scorer(cell["solution"])["business_correct"] is False
    positive = problem.scorer(cells[4]["solution"])
    assert positive["violations"] == ["business objective is not independently optimal"]


def test_toy_integer_and_indicator_repair_recovers_real_scip_solution(tmp_path):
    result = run_problem(20, "fixed", tmp_path)
    assert result["initial_score"]["business_correct"] is False
    assert result["final_score"]["business_correct"] is True
    assert result["final_score"]["violations"] == []
    assert result["semantic_recovery"] is True
    assert result["accepted_round"] == 1
    assert result["accepted_but_business_incorrect"] is False
    assert result["solver_runs_this_run"] == 1
    assert result["llm_calls"] == 0
    assert result["tokens"] == 0
    assert all(result["final_score"]["variable_audit"][f"x{i}"]["passed"]
               for i in range(1, 5))
    gate_result = json.loads((tmp_path / "prob_020/fixed/gate.json").read_text())
    assert gate_result["accepted"] is True
    assert gate_result["evaluation"]["valid_invariant_count"] == 13
    assert gate_result["evaluation"]["unknown"] == 0
    assert gate_result["evaluation"]["rejected_count"] == 0
