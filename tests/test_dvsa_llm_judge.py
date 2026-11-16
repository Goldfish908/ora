from scripts.dvsa_llm_judge import (evaluate_verdicts, public_artifacts,
                                    render_prompt)


def reference():
    model = {
        "schema_version": "dvsa.model.v0.1", "problem_id": "toy",
        "variables": {"x": {"domain": "real", "lb": 0}, "y": {"domain": "real", "lb": 0}},
        "data": {"limit": 4},
        "constraints": [{"constraint_id": "capacity", "source": "total capacity is four",
                         "relation": "le", "lhs": {"add": [{"var": "x"}, {"var": "y"}]},
                         "rhs": {"path": "data.limit"}}],
        "objective": {"sense": "maximize", "expression": {"add": [{"var": "x"}, {"var": "y"}]}},
    }
    return {"model": model, "solution": {"variables": {"x": 2, "y": 2}, "objective": 4},
            "question": "The total capacity is four. Maximize annual profit from the two products."}


def test_judge_input_has_no_labels_or_ordered_clean_id():
    ref = reference()
    artifacts = public_artifacts(ref)
    assert len({row["artifact_id"] for row in artifacts}) == len(artifacts)
    assert not any("clean" in row["artifact_id"] or "A000" in row["artifact_id"] for row in artifacts)
    prompt = render_prompt(ref, artifacts, "")
    assert "original_key" not in prompt
    assert "expected_rule" not in prompt
    assert '"wrong"' not in prompt
    assert "999" not in prompt


def verdict(artifact_id, value, details):
    return {"artifact_id": artifact_id, "verdict": value,
            "violations": [{"rule": "capacity", "detail": detail} for detail in details]}


def test_verdict_mapping_uses_opaque_ids_and_numeric_evidence():
    artifacts = [{"artifact_id": "a", "original_key": "x", "original_keys": ["x"],
                  "wrong": True, "expected_rule": "capacity", "expected_rules": ["capacity"]},
                 {"artifact_id": "b", "original_key": "y", "original_keys": ["y"],
                  "wrong": False, "expected_rule": None, "expected_rules": [None]}]
    proposal = {"verdicts": [verdict("b", "VALID", []), verdict("a", "INVALID", ["5 > 4"])]}
    summary, records = evaluate_verdicts(artifacts, proposal)
    assert summary["detection"] == 1
    assert summary["false_positive_n"] == 0
    assert summary["unknown"] == 0


def test_unsupported_or_contradictory_verdict_is_unknown():
    artifacts = [{"artifact_id": "a", "original_key": "x", "original_keys": ["x"],
                  "wrong": True, "expected_rule": "capacity", "expected_rules": ["capacity"]},
                 {"artifact_id": "b", "original_key": "y", "original_keys": ["y"],
                  "wrong": False, "expected_rule": None, "expected_rules": [None]}]
    proposal = {"verdicts": [verdict("a", "INVALID", ["looks suspicious"]),
                             verdict("b", "VALID", ["5 > 4"])]}
    summary, records = evaluate_verdicts(artifacts, proposal)
    assert summary["detection"] == 0
    assert summary["false_positive_n"] == 0
    assert summary["unknown"] == 2
    assert {row["reason"] for row in records} == {"invalid_without_numeric_evidence", "valid_with_reported_violations"}


def test_identical_solutions_are_one_artifact_with_multiple_reference_rules():
    ref = reference()
    duplicate = dict(ref["model"]["constraints"][0])
    duplicate["constraint_id"] = "capacity_duplicate"
    ref["model"]["constraints"].append(duplicate)
    artifacts = public_artifacts(ref)
    assert len(artifacts) == 3
    combined = next(row for row in artifacts if len(row["expected_rules"]) > 1)
    assert set(combined["expected_rules"]) == {"capacity", "capacity_duplicate"}


def test_duplicate_model_verdict_is_unknown_not_double_counted():
    artifacts = [{"artifact_id": "a", "original_key": "x", "original_keys": ["x"],
                  "wrong": True, "expected_rule": "capacity", "expected_rules": ["capacity"]}]
    proposal = {"verdicts": [verdict("a", "INVALID", ["5 > 4"]),
                             verdict("a", "INVALID", ["5 > 4"])]}
    summary, records = evaluate_verdicts(artifacts, proposal)
    assert summary["detection"] == 0
    assert summary["unknown"] == 1
    assert summary["missing_or_duplicate_ids"] == 1
