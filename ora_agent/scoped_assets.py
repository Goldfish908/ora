"""Versioned semantic-asset templates, local bindings and validation."""
from __future__ import annotations

import json
from pathlib import Path

from ora_agent.scoped_ir import evaluate_spec


def _term(binding: dict) -> dict | int | float:
    path = binding["path"]
    coefficient = binding.get("coefficient", 1)
    return {"path": path} if coefficient == 1 else {"mul": [coefficient, {"path": path}]}


def _expression(terms: list[dict]) -> dict | int | float:
    if not terms:
        return 0
    values = [_term(term) for term in terms]
    return values[0] if len(values) == 1 else {"add": values}


def compile_asset(asset: dict, binding: dict) -> dict:
    mechanism = asset["mechanism_id"]
    scope = asset.get("scope", {})
    required = scope.get("required_activities")
    if required is not None and len(binding.get("terms", [])) != required:
        raise ValueError(f"scope requires {required} activities")
    if mechanism == "makespan":
        relation = "eq"
        lhs = {"path": binding.get("objective_path", "solution.objective")}
        rhs = {"max": [_term(term) for term in binding["terms"]]}
        kind = "makespan"
    elif mechanism == "objective_recompute":
        relation = "eq"
        lhs = {"path": binding.get("objective_path", "solution.objective")}
        rhs = _expression(binding["terms"])
        constant = binding.get("constant", 0)
        if constant != 0:
            rhs = {"add": [rhs, constant]} if binding["terms"] else constant
        kind = "objective"
    elif mechanism == "resource_bound":
        relation = binding["relation"]
        lhs = _expression(binding["terms"])
        rhs = binding["limit"]
        kind = "constraint"
    elif mechanism == "state_conservation":
        rule = binding.get("invariant_id", mechanism)
        source = binding["source_span"]
        initial = binding["initial"]
        previous = _term(binding["previous"])
        inflows = _expression(binding.get("inflows", []))
        outflows = _expression(binding.get("outflows", []))
        balance = {"add": [previous, inflows, {"neg": outflows}]}
        return {"invariants": [
            {"invariant_id": f"{rule}_initial", "kind": "state_initialization",
             "relation": "eq", "lhs": {"path": initial["path"]},
             "rhs": initial["value"], "source_span": source},
            {"invariant_id": f"{rule}_flow", "kind": "state_conservation",
             "relation": "eq", "lhs": {"path": binding["next"]["path"]},
             "rhs": balance,
             "source_span": binding.get("flow_source_span", source)},
        ]}
    elif mechanism == "indicator_link":
        invariants = []
        for index, link in enumerate(binding["links"], 1):
            rule = link.get("invariant_id", f"indicator_link_{index}")
            quantity = {"path": link["quantity_path"]}
            indicator = {"path": link["indicator_path"]}
            upper = link["upper_bound"]
            if isinstance(upper, bool) or not isinstance(upper, (int, float)) or upper <= 0:
                raise ValueError("indicator upper_bound must be positive and numeric")
            for suffix, lhs, rhs in (
                    ("off", indicator, quantity),
                    ("on", quantity, {"mul": [upper, indicator]})):
                invariants.append({
                    "invariant_id": f"{rule}_{suffix}", "kind": f"indicator_{suffix}",
                    "relation": "le", "lhs": lhs, "rhs": rhs,
                    "source_span": link["source_span"],
                    "source_evidence": link.get("source_evidence")})
        return {"invariants": invariants}
    elif mechanism == "job_precedence":
        relation = binding.get("relation", "ge")
        if relation not in {"ge", "gt"}:
            raise ValueError("job_precedence relation must be ge or gt")
        rhs = {"path": binding["first_end_path"]}
        duration_terms = binding.get("duration_terms", [])
        for term in duration_terms:
            coefficient = term.get("coefficient", 1)
            if isinstance(coefficient, bool) or not isinstance(coefficient, (int, float)) or coefficient <= 0:
                raise ValueError("job_precedence durations must be positive numbers")
        if duration_terms:
            rhs = {"add": [rhs, *[_term(item) for item in duration_terms]]}
        return {"invariants": [{
            "invariant_id": binding.get("invariant_id", mechanism),
            "kind": "job_precedence_strict" if relation == "gt" else "job_precedence",
            "relation": relation, "lhs": {"path": binding["second_start_path"]}, "rhs": rhs,
            "strict": relation == "gt", "source_span": binding["source_span"],
            "source_evidence": binding.get("source_evidence")}]}
    elif mechanism == "variable_domain":
        relation = "eq"
        kind = "domain_integer"
        invariants = [{"invariant_id": f"{binding.get('invariant_id', mechanism)}_{index}",
                       "kind": kind, "relation": relation,
                       "lhs": {"path": term["path"]},
                       "rhs": {"round": {"path": term["path"]}},
                       "source_span": binding["source_span"],
                       "source_evidence": binding.get("source_evidence")}
                      for index, term in enumerate(binding["terms"], 1)]
        return {"invariants": invariants}
    else:
        raise ValueError(f"unsupported mechanism: {mechanism}")
    return {"invariants": [{
        "invariant_id": binding.get("invariant_id", mechanism),
        "kind": kind, "relation": relation, "lhs": lhs, "rhs": rhs,
        "source_span": binding["source_span"],
        "source_evidence": binding.get("source_evidence"),
    }]}


def validation_cells(validation: dict) -> list[dict]:
    cells = []
    for label, solution in validation.items():
        if label in {"question", "binding"}:
            continue
        wrong = not label.startswith("clean")
        cells.append({"key": label, "wrong": wrong,
                      "mutation": label, "reference_violations": [],
                      "solution": solution})
    if not any(cell["key"].startswith("clean") for cell in cells):
        raise ValueError("validation requires a clean solution")
    if not any(cell["wrong"] for cell in cells):
        raise ValueError("validation requires at least one wrong solution")
    return cells


def validate_asset(asset: dict) -> dict:
    validation = asset["validation"]
    binding = validation["binding"]
    spec = compile_asset(asset, binding)
    evaluation = evaluate_spec(spec, validation["question"],
                               validation_cells(validation), asset["mechanism_id"])
    passed = (evaluation["detection"] == 1.0
              and evaluation["false_positive"] == 0.0
              and evaluation["unknown"] == 0
              and evaluation["rejected_count"] == 0
              and evaluation["not_applicable"] == 0)
    return {"mechanism_id": asset["mechanism_id"],
            "version": asset["version"],
            "status": "validated" if passed else "rejected",
            "spec": spec, "binding": binding, "evaluation": evaluation}


def load_asset(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def validate_many(paths: list[str | Path]) -> list[dict]:
    return [validate_asset(load_asset(path)) for path in paths]
