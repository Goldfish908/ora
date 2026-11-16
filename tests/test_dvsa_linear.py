from ora_agent.dvsa_linear import linearize, reference_bindings


def model():
    return {
        "problem_id": "toy",
        "variables": {"x": {"domain": "real", "lb": 0}, "y": {"domain": "real", "lb": 0}},
        "data": {"a": 3, "b": 2, "coefficients": [2, 3]},
        "constraints": [
            {"constraint_id": "cap", "source": "capacity source", "relation": "le",
             "lhs": {"add": [{"var": "x"}, {"var": "y"}]}, "rhs": 4},
            {"constraint_id": "minimum", "source": "minimum source", "relation": "ge",
             "lhs": {"var": "x"}, "rhs": 1},
            {"constraint_id": "balance", "source": "balance source", "relation": "eq",
             "lhs": {"var": "x"}, "rhs": {"var": "y"}},
        ],
        "objective": {"sense": "maximize", "source": "annual profit",
                      "expression": {"add": [
                          {"mul": [{"path": "data.a"}, {"var": "x"}]},
                          {"mul": [{"path": "data.b"}, {"var": "y"}]}
                      ]}},
    }


def test_linearize_preserves_coefficients_and_dynamic_constant_indices():
    spec = model()
    expr = {"sum": {
        "forall": {"r": {"range": [0, 2]}},
        "value": {"mul": [
            {"index": {"value": {"path": "data.coefficients"}, "at": {"var": "r"}}},
            {"var": "x"}
        ]}
    }}
    coefficients, constant = linearize(expr, spec)
    assert coefficients == {"x": 5}
    assert constant == 0


def test_reference_export_covers_all_three_relations_and_objective():
    result = reference_bindings(model())
    by_id = {item["binding_id"]: item for item in result["bindings"]}
    assert by_id["cap"]["data"] == {
        "terms": [{"variable": "x", "coefficient": 1}, {"variable": "y", "coefficient": 1}],
        "limit": 4}
    assert by_id["minimum"]["template_id"] == "bwor.linear_lower_bound"
    assert by_id["balance"]["data"]["positive_terms"] == [{"variable": "x", "coefficient": 1}]
    assert by_id["balance"]["data"]["negative_terms"] == [{"variable": "y", "coefficient": 1}]
    assert by_id["OBJECTIVE"]["data"]["constant"] == 0
    assert result["skipped"] == []


def test_nonlinear_constraint_is_skipped_not_misclassified():
    spec = model()
    spec["constraints"][0]["lhs"] = {"mul": [{"var": "x"}, {"var": "y"}]}
    result = reference_bindings(spec)
    assert any(item["constraint_id"] == "cap" for item in result["skipped"])
