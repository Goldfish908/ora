from ora_agent.scoped_ir import evaluate_spec, extract_spec, prepare_asset


def cell(key, wrong, x, objective, mutation="clean"):
    return {"key": key, "wrong": wrong, "mutation": mutation,
            "reference_violations": [], "solution": {"variables": {"x": x},
                                                    "objective": objective}}


def test_scoped_ir_checks_constraint_and_objective():
    question = "At most 100 units. Each unit yields 3 profit."
    spec = {"invariants": [
        {"invariant_id": "capacity", "kind": "constraint", "relation": "le",
         "lhs": {"path": "solution.variables.x"}, "rhs": 100,
         "source_span": "At most 100 units."},
        {"invariant_id": "objective", "kind": "objective", "relation": "eq",
         "lhs": {"path": "solution.objective"},
         "rhs": {"mul": [3, {"path": "solution.variables.x"}]},
         "source_span": "Each unit yields 3 profit."},
    ]}
    cells = [cell("clean", False, 50, 150), cell("bad", True, 101, 151.5, "bound")]
    result = evaluate_spec(spec, question, cells, "p0")
    assert result["detection"] == 1.0
    assert result["false_positive"] == 0.0
    assert result["unknown"] == 0
    assert result["valid_invariant_count"] == 2


def test_integer_requires_explicit_text_evidence():
    question = "How many art pieces should be made?"
    spec = {"invariants": [
        {"invariant_id": "integer", "kind": "domain_integer", "relation": "eq",
         "lhs": {"path": "solution.variables.x"},
         "rhs": {"round": {"path": "solution.variables.x"}},
         "source_span": "How many art pieces"},
    ]}
    result = evaluate_spec(spec, question, [cell("clean", False, 5.2, 0)], "p0")
    assert result["rejected_count"] == 1
    assert result["valid_invariant_count"] == 0
    assert result["unknown"] == 1
    assert result["fp"] == 0


def test_explicit_integer_is_checked_deterministically():
    question = "The number must be an integer."
    spec = {"invariants": [
        {"invariant_id": "integer", "kind": "domain_integer", "relation": "eq",
         "lhs": {"path": "solution.variables.x"},
         "rhs": {"round": {"path": "solution.variables.x"}},
         "source_span": "must be an integer"},
    ]}
    cells = [cell("clean", False, 5, 0), cell("bad", True, 5.5, 0, "integrality")]
    result = evaluate_spec(spec, question, cells, "p0")
    assert result["detection"] == 1.0
    assert result["false_positive"] == 0.0
    assert result["unknown"] == 0


def test_wrong_variable_path_is_unknown_not_violation():
    question = "At most 100 units."
    spec = {"invariants": [
        {"invariant_id": "capacity", "kind": "constraint", "relation": "le",
         "lhs": {"path": "x"}, "rhs": 100, "source_span": "At most 100 units."},
    ]}
    result = evaluate_spec(spec, question, [cell("clean", False, 50, 150)], "p0")
    assert result["valid_invariant_count"] == 0
    assert result["rejected_count"] == 1
    assert result["unknown"] == 1
    assert result["fp"] == 0


def test_non_verbatim_source_span_is_rejected():
    question = "At most 100 units."
    spec = {"invariants": [
        {"invariant_id": "capacity", "kind": "constraint", "relation": "le",
         "lhs": {"path": "solution.variables.x"}, "rhs": 100,
         "source_span": "paraphrased requirement"},
    ]}
    result = evaluate_spec(spec, question, [cell("clean", False, 50, 150)], "p0")
    assert result["rejected_count"] == 1
    assert result["unknown"] == 1
    assert result["fp"] == 0


def test_extract_spec_accepts_json_only():
    assert extract_spec('{"invariants": []}') == {"invariants": []}
    try:
        extract_spec("not json")
        assert False, "invalid JSON must fail"
    except ValueError:
        pass


def test_max_expression_supports_parallel_makespan():
    question = "The jobs run in parallel and total time is the maximum."
    spec = {"invariants": [
        {"invariant_id": "makespan", "kind": "objective", "relation": "eq",
         "lhs": {"path": "solution.objective"},
         "rhs": {"max": [{"mul": [0.5, {"path": "solution.variables.x"}]},
                         {"mul": [1.5, {"path": "solution.variables.x"}]}]},
         "source_span": "time is the maximum"},
    ]}
    cells = [cell("clean", False, 50, 75.0), cell("bad", True, 50, 62.5, "objective")]
    result = evaluate_spec(spec, question, cells, "p0")
    assert result["detection"] == 1.0
    assert result["false_positive"] == 0.0
    assert result["unknown"] == 0


def bounded_spec():
    return {"invariants": [
        {"invariant_id": "capacity", "kind": "constraint", "relation": "le",
         "lhs": {"path": "solution.variables.x"}, "rhs": 100,
         "source_span": "At most 100 units."},
    ]}


def test_dev_pass_requires_every_wrong_cell_to_fire():
    cells = [cell("clean", False, 50, 0),
             cell("bad1", True, 101, 0, "bound"),
             cell("missed", True, 90, 0, "mislabeled"),
             cell("bad2", True, 102, 0, "bound")]
    result = evaluate_spec(bounded_spec(), "At most 100 units.", cells, "p0")
    assert result["detection"] == 2 / 3
    assert result["false_positive"] == 0.0
    assert result["unknown"] == 0
    assert result["rejected_count"] == 0
    assert result["dev_passed"] is False


def test_dev_pass_requires_both_clean_and_wrong_cells():
    wrong_only = evaluate_spec(
        bounded_spec(), "At most 100 units.",
        [cell("bad", True, 101, 0, "bound")], "p0")
    assert wrong_only["detection"] == 1.0
    assert wrong_only["dev_passed"] is False
    clean_only = evaluate_spec(
        bounded_spec(), "At most 100 units.", [cell("clean", False, 50, 0)], "p0")
    assert clean_only["false_positive"] == 0.0
    assert clean_only["dev_passed"] is False


def test_partial_rejection_preserves_valid_evidence_but_blocks_dev_pass():
    spec = bounded_spec()
    spec["invariants"].append(
        {"invariant_id": "invalid", "kind": "constraint", "relation": "ne",
         "lhs": {"path": "solution.variables.x"}, "rhs": 0,
         "source_span": "At most 100 units."})
    cells = [cell("clean", False, 50, 0), cell("bad", True, 101, 0, "bound")]
    result = evaluate_spec(spec, "At most 100 units.", cells, "p0")
    assert result["valid_invariant_count"] == 1
    assert result["rejected_count"] == 1
    assert result["detection"] == 1.0
    assert result["dev_passed"] is False
    assert result["records"][1]["fired"] is True
    assert result["records"][1]["violations"][0]["rule"] == "capacity"
    assert result["records"][0]["status"] == "unknown"
    assert result["records"][0]["rejected"][0]["invariant_id"] == "invalid"


def test_none_spec_invalid_invariants_and_empty_cells_are_safe_rejections():
    question = "At most 100 units."
    none_spec = evaluate_spec(None, question, [cell("clean", False, 50, 0)], "p0")
    assert none_spec["rejected_count"] == 1
    assert none_spec["records"][0]["status"] == "unknown"
    assert none_spec["dev_passed"] is False
    invalid_invariants = evaluate_spec(
        {"invariants": {}}, question, [cell("clean", False, 50, 0)], "p0")
    assert invalid_invariants["rejected_count"] == 1
    assert invalid_invariants["records"][0]["status"] == "unknown"
    empty = evaluate_spec(bounded_spec(), question, [], "p0")
    assert empty["records"] == []
    assert empty["dev_passed"] is False
    assert empty["unknown"] == 0


def test_violated_and_unknown_preserves_both_evidence_channels():
    spec = bounded_spec()
    spec["invariants"].append(
        {"invariant_id": "unknown_objective", "kind": "objective", "relation": "eq",
         "lhs": {"path": "solution.objective"}, "rhs": {"div": [1, 0]},
         "source_span": "At most 100 units."})
    result = evaluate_spec(spec, "At most 100 units.",
                           [cell("bad", True, 101, 0, "bound")], "p0")
    record = result["records"][0]
    assert record["status"] == "unknown"
    assert record["asset_status"] == "VIOLATED"
    assert record["fired"] is True
    assert record["violations"][0]["rule"] == "capacity"
    assert record["violations"][0]["lhs"] == 101.0
    assert record["unknown_evidence"][0]["rule"] == "unknown_objective"
    assert "division by zero" in record["unknown_evidence"][0]["detail"]
    assert result["unknown"] == 1
    assert result["dev_passed"] is False


def test_not_applicable_is_distinct_from_ok_and_unknown(monkeypatch):
    def not_applicable(asset, data, solution):
        return {"status": "NOT_APPLICABLE", "violations": [], "unknown": []}

    monkeypatch.setattr("ora_agent.scoped_ir.run_asset", not_applicable)
    result = evaluate_spec(bounded_spec(), "At most 100 units.",
                           [cell("clean", False, 50, 0)], "p0")
    record = result["records"][0]
    assert record["status"] == "not_applicable"
    assert record["asset_status"] == "NOT_APPLICABLE"
    assert record["fired"] is False
    assert result["unknown"] == 0
    assert result["not_applicable"] == 1
    assert result["dev_passed"] is False


def test_integer_domain_cannot_be_enabled_by_a_self_declared_boolean():
    question = "Choose Food_1 to meet dietary requirements."
    spec = {"invariants": [
        {"invariant_id": "unsupported_integer", "kind": "domain_integer", "relation": "eq",
         "lhs": {"path": "solution.variables.x"},
         "rhs": {"round": {"path": "solution.variables.x"}},
         "source_span": "Food_1", "independent_validation": True},
    ]}
    result = evaluate_spec(spec, question, [cell("clean", False, 5, 0)], "p0")
    assert result["valid_invariant_count"] == 0
    assert result["records"][0]["status"] == "unknown"
    assert result["rejected_count"] == 1
    assert result["dev_passed"] is False
