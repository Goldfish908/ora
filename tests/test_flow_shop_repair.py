import copy

import pytest

from ora_agent.dvsa_model import solve_model
from ora_agent.flow_shop import audit_candidate, binding_for, completion_constraints, cut_constraints, optimum
from ora_agent.flow_shop_repair import model_digest, repair_completion_model
from tests.test_flow_shop import assignment_constraints, toy


def completion_model(formulation="completion"):
    model = toy()
    binding = binding_for(model, "A then B")
    expected = completion_constraints(binding) if formulation == "completion" else cut_constraints(binding)
    model["constraints"] = expected + assignment_constraints(binding)
    return model


def test_narrow_time_repair_preserves_assignments_and_recovers_scip():
    reference = completion_model()
    wrong = copy.deepcopy(reference)
    second = next(row for row in wrong["constraints"] if row["constraint_id"] == "job_completion:p2")
    second["rhs"] = {"add": [{"var": "CA_1"}] + [
        {"mul": [{"path": f"data.A{job}"}, {"var": f"x_2_{job}"}]} for job in (1, 2, 3)]}
    before = copy.deepcopy(wrong)
    assert audit_candidate(wrong, None, binding_for(reference, "A then B"))["business_correct"] is False
    repaired, record = repair_completion_model(wrong, reference, "A then B")
    assert wrong == before
    assert record["before_sha256"] == model_digest(before)
    assert record["non_time_constraints_preserved"] is True
    assert record["llm_calls"] == 0
    assert record["data_aliases"] == {}
    assert repaired["variables"] == reference["variables"]
    assert repaired["objective"] == reference["objective"]
    solved = solve_model(repaired)
    assert solved["status"] == "optimal"
    assert solved["solution"]["objective"] == optimum(binding_for(reference, "A then B"))[0]
    result = audit_candidate(repaired, solved["solution"], binding_for(reference, "A then B"))
    assert result["business_correct"] is True
    with pytest.raises(ValueError, match="no repair required"):
        repair_completion_model(repaired, reference, "A then B")


def test_valid_completion_and_cut_alternatives_are_never_repaired():
    reference = completion_model()
    for formulation in ("completion", "cut"):
        with pytest.raises(ValueError, match="no repair required"):
            repair_completion_model(completion_model(formulation), reference, "A then B")


def test_repair_rejects_changed_processing_times_and_objectives():
    reference = completion_model()
    wrong = completion_model()
    wrong["data"]["B2"] += 1
    with pytest.raises(ValueError, match="processing times|valid structural"):
        repair_completion_model(wrong, reference, "A then B")
    wrong = completion_model()
    wrong["objective"]["sense"] = "maximize"
    with pytest.raises(ValueError, match="objective|valid structural"):
        repair_completion_model(wrong, reference, "A then B")


def test_missing_time_constraints_can_be_added_without_touching_assignments():
    reference = completion_model()
    binding = binding_for(reference, "A then B")
    time_names = {binding["ca"](position) for position in binding["positions"]}
    time_names.update(binding["cb"](position) for position in binding["positions"])
    time_names.add("T")
    wrong = copy.deepcopy(reference)
    wrong["constraints"] = [row for row in wrong["constraints"]
                            if not any(name in str(row) for name in time_names)]
    repaired, record = repair_completion_model(wrong, reference, "A then B")
    assert record["non_time_constraints_preserved"] is True
    solved = solve_model(repaired)
    assert solved["status"] == "optimal"
    assert audit_candidate(repaired, solved["solution"], binding)["business_correct"] is True
