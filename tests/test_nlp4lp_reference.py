import json

from scripts.nlp4lp_reference import audit, compatible, load_rows, mutate


def exposed_row():
    return next(r for r in load_rows("dev") if r["id"] == "prob_000")


def test_expert_solution_passes_independent_audit():
    row = exposed_row()
    assert compatible(row)[0]
    assert audit(row, json.loads(row["solution"]))["verdict"] == "VALID"


def test_controlled_mutations_have_independent_wrong_labels():
    row = exposed_row()
    mutations = mutate(row)
    assert any(m["mutation"] == "objective_misreport" for m in mutations)
    assert any(m.get("target_rule") for m in mutations)
    for mutation in mutations:
        assert audit(row, mutation["solution"])["verdict"] == "INVALID"


def test_objective_misreport_does_not_change_variables():
    row = exposed_row()
    mutation = next(m for m in mutate(row) if m["mutation"] == "objective_misreport")
    clean = json.loads(row["solution"])
    assert mutation["solution"]["variables"] == clean["variables"]
    violations = audit(row, mutation["solution"])["violations"]
    assert [v["rule"] for v in violations] == ["OBJECTIVE"]


def test_validation_mutations_differ_but_keep_independent_labels():
    row = exposed_row()
    assert mutate(row, "dev") == mutate(row)
    validation = mutate(row, "validation")
    assert validation != mutate(row, "dev")
    for mutation in validation:
        assert audit(row, mutation["solution"])["verdict"] == "INVALID"


def test_pathological_reference_is_not_a_clean_gold_label():
    row = next(r for r in load_rows("dev") if r["id"] == "prob_005")
    ok, reason = compatible(row)
    assert not ok
    assert reason == "pathological_reference_magnitude"
