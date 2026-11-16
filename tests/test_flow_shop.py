import itertools
import json
from pathlib import Path

from ora_agent.dvsa_model import solve_model
from ora_agent.flow_shop import (
    audit_candidate,
    binding_for,
    binding_variants,
    completion_constraints,
    cut_constraints,
    make_solution,
    optimum,
    schedule,
    solution_audit,
    structure_audit,
)

ROOT = Path(__file__).resolve().parents[1]


def toy():
    variables = {}
    for position in (1, 2, 3):
        for job in (1, 2, 3):
            variables[f"x_{position}_{job}"] = {"domain": "binary", "lb": 0, "ub": 1}
        variables[f"CA_{position}"] = {"domain": "real", "lb": 0, "ub": None}
        variables[f"CB_{position}"] = {"domain": "real", "lb": 0, "ub": None}
    variables["T"] = {"domain": "real", "lb": 0, "ub": None}
    return {"schema_version": "dvsa.model.v0.1", "problem_id": "toy_flow_shop",
            "variables": variables, "data": {"A1": 2, "A2": 3, "A3": 1,
                                             "B1": 4, "B2": 1, "B3": 2},
            "constraints": [], "objective": {"sense": "minimize", "expression": {"var": "T"}},
            "assumptions": [], "modeling_conflicts": []}


def test_independent_optimum_matches_exhaustive_permutations():
    binding = binding_for(toy(), "Each job is processed on A then B")
    value, _ = optimum(binding)
    brute = min(schedule(binding, list(permutation))["makespan"]
                for permutation in itertools.permutations(binding["jobs"]))
    assert value == brute


def test_completion_structure_and_solution_are_independently_accepted():
    model = toy()
    model["constraints"] = completion_constraints(binding_for(model, "A then B"))
    binding = binding_for(model, "A then B")
    _, permutation = optimum(binding)
    result = audit_candidate(model, make_solution(binding, permutation), binding)
    assert result["status"] == "SATISFIED"
    assert result["business_correct"] is True
    assert result["structure"]["formulation"] == "completion"


def test_equivalent_cut_formulation_is_not_repaired_as_a_completion_model():
    model = toy()
    binding = binding_for(model, "A then B")
    model["constraints"] = cut_constraints(binding)
    _, permutation = optimum(binding)
    result = audit_candidate(model, make_solution(binding, permutation, "cut"), binding)
    assert result["status"] == "SATISFIED"
    assert result["structure"]["formulation"] == "cut"
    assert result["structure"]["equivalent_alternative_to_completion"] is True


def test_same_objective_wrong_precedence_is_rejected():
    model = toy()
    binding = binding_for(model, "A then B")
    _, permutation = optimum(binding)
    solution = make_solution(binding, permutation)
    first_job = permutation[0]
    solution["variables"]["CB_1"] = (solution["variables"]["CA_1"]
                                      + binding["durations"]["B"][first_job] - 1)
    result = solution_audit(model, solution, binding, "completion")
    assert result["business_correct"] is False
    assert any(row["rule"] == "job_cb:p1" for row in result["violations"])
    assert result["schedule"]["makespan"] == result["independent_optimum"]


def test_feasible_but_suboptimal_schedule_is_not_business_correct():
    model = toy()
    binding = binding_for(model, "A then B")
    result = solution_audit(model, make_solution(binding, [3, 2, 1]), binding, "completion")
    assert result["schedule"]["makespan"] > result["independent_optimum"]
    assert result["business_correct"] is False
    assert any(row["rule"] == "independent_optimality" for row in result["violations"])


def test_missing_mapping_and_nonbinary_assignments_are_not_accepted():
    model = toy()
    binding = binding_for(model, "A then B")
    _, permutation = optimum(binding)
    solution = make_solution(binding, permutation)
    del solution["variables"]["CB_1"]
    assert solution_audit(model, solution, binding, "completion")["status"] == "UNKNOWN"
    solution = make_solution(binding, permutation)
    solution["variables"]["x_1_1"] = 0.5
    assert solution_audit(model, solution, binding, "completion")["business_correct"] is False


def test_index_swap_and_duration_change_are_structural_errors():
    model = toy()
    binding = binding_for(model, "A then B")
    model["constraints"] = completion_constraints(binding)
    wrong = json.loads(json.dumps(model))
    second = next(row for row in wrong["constraints"] if row["constraint_id"] == "job_completion:p2")
    second["rhs"] = {"add": [{"var": "CA_1"}] + [
        {"mul": [{"path": f"data.A{position}"}, {"var": f"x_2_{position}"}]}
        for position in (1, 2, 3)]}
    result = structure_audit(wrong, binding)
    assert result["status"] == "VIOLATED"
    assert any(row["rule"] == "job_completion:p2" for row in result["violations"])
    wrong = json.loads(json.dumps(model))
    wrong["data"]["B2"] += 1
    assert structure_audit(wrong, binding)["status"] == "VIOLATED"


def test_missing_cut_is_not_mistaken_for_valid_alternative():
    model = toy()
    binding = binding_for(model, "A then B")
    model["constraints"] = cut_constraints(binding)[:-1]
    assert structure_audit(model, binding)["status"] == "VIOLATED"


def natural_problem(problem_id):
    reference = json.loads((ROOT / f"work/dvsa/bwor_reference/frozen/{problem_id}/model.json").read_text())
    question = (ROOT / f"work/dvsa/bwor_reference/frozen/{problem_id}/question.txt").read_text()
    binding = binding_for(reference, question)
    candidate = json.loads((ROOT / f"work/bwor_candidate_blind_replay_v0.1/{problem_id}/initial/candidate.json").read_text())
    solution = json.loads((ROOT / f"work/bwor_candidate_blind_replay_v0.1/{problem_id}/initial/solution.json").read_text())
    reference_solution = json.loads((ROOT / f"work/dvsa/bwor_reference/frozen/{problem_id}/solution.json").read_text())
    return reference, candidate, reference_solution, solution, binding


def test_natural_024_cut_is_valid_despite_different_auxiliary_variable_meaning():
    reference, candidate, reference_solution, solution, binding = natural_problem("BWOR-024")
    assert audit_candidate(reference, reference_solution, binding)["business_correct"] is True
    result = audit_candidate(candidate, solution, binding)
    assert result["structure"]["formulation"] == "cut"
    assert result["business_correct"] is True
    assert result["solution"]["independent_optimum"] == 370


def test_natural_025_is_valid_with_its_own_position_job_binding():
    reference, candidate, reference_solution, solution, binding = natural_problem("BWOR-025")
    assert audit_candidate(reference, reference_solution, binding)["business_correct"] is True
    result = audit_candidate(candidate, solution, binding)
    assert result["status"] == "SATISFIED"
    assert result["business_correct"] is True
    assert result["index_semantics"] == "position_job"
    assert result["structure"]["formulation"] == "completion"
    assert solution["objective"] == 81
    assert result["solution"]["independent_optimum"] == 81


def test_multiple_valid_bindings_cannot_select_the_more_favorable_answer():
    model = toy()
    binding = binding_for(model, "A then B")
    variants = binding_variants(binding)
    model["constraints"] = sum((completion_constraints(variant) for variant in variants), [])
    result = audit_candidate(model, make_solution(variants[0], optimum(binding)[1]), binding)
    assert result["status"] == "UNKNOWN"
    assert result["business_correct"] is False
    assert result["unknown"][0]["rule"] == "index_semantics"


def assignment_constraints(binding):
    rows = []
    for position in binding["positions"]:
        rows.append({"constraint_id": f"position_{position}", "source": binding["question"],
                     "relation": "eq",
                     "lhs": {"add": [{"var": binding["x"](position, job)} for job in binding["jobs"]]},
                     "rhs": 1})
    for job in binding["jobs"]:
        rows.append({"constraint_id": f"job_{job}", "source": binding["question"],
                     "relation": "eq",
                     "lhs": {"add": [{"var": binding["x"](position, job)}
                                     for position in binding["positions"]]},
                     "rhs": 1})
    return rows


def test_real_scip_completion_and_cut_agree_with_independent_optimum():
    for formulation in ("completion", "cut"):
        model = toy()
        binding = binding_for(model, "A then B")
        expected = completion_constraints(binding) if formulation == "completion" else cut_constraints(binding)
        model["constraints"] = expected + assignment_constraints(binding)
        solved = solve_model(model)
        assert solved["status"] == "optimal"
        assert solved["solution"]["objective"] == optimum(binding)[0]
        result = audit_candidate(model, solved["solution"], binding)
        assert result["business_correct"] is True
        assert result["structure"]["formulation"] == formulation
