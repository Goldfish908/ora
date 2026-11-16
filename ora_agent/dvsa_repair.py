"""Shared schema and solution scoring for DVSA repair experiments."""
from __future__ import annotations

from ora_agent.dvsa_model import audit_solution


def schema_errors(model, expected_variables):
    if not isinstance(model, dict) or not isinstance(model.get("variables"), dict):
        return ["variables object is missing"]
    actual = model["variables"]
    errors = []
    for name in sorted(set(expected_variables) - set(actual)):
        errors.append(f"missing variable: {name}")
    for name in sorted(set(actual) - set(expected_variables)):
        errors.append(f"unexpected variable: {name}")
    for name in sorted(set(actual) & set(expected_variables)):
        expected = expected_variables[name]
        offered = actual[name]
        if not isinstance(offered, dict):
            errors.append(f"invalid declaration: {name}")
            continue
        for key in ("domain", "lb", "ub"):
            expected_value = expected.get(key, "real" if key == "domain" else None)
            offered_value = offered.get(key, "real" if key == "domain" else None)
            if offered_value != expected_value:
                errors.append(f"{name}.{key}: expected {expected_value!r}, got {offered_value!r}")
    return errors


def select_win_safe_solution(reference, initial_solution, initial_score, candidate_solution, public_answer):
    candidate_score = score_solution(reference, candidate_solution, public_answer)
    if initial_score.get("business_correct") and not candidate_score["business_correct"]:
        return {"solution": initial_solution, "score": initial_score,
                "candidate_score": candidate_score, "baseline_fallback": True}
    return {"solution": candidate_solution, "score": candidate_score,
            "candidate_score": candidate_score, "baseline_fallback": False}


def score_solution(reference, solution, public_answer):
    if not isinstance(solution, dict):
        return {"business_correct": False, "status": "no_solution",
                "objective_correct": False, "semantic_valid": False}
    audit = audit_solution(reference["model"], solution)
    objective = solution.get("objective")
    objective_error = abs(float(objective) - float(public_answer)) if isinstance(objective, (int, float)) else None
    objective_correct = objective_error is not None and objective_error <= 0.1
    semantic_valid = audit["verdict"] == "VALID"
    return {"business_correct": semantic_valid and objective_correct,
            "status": "scored", "semantic_valid": semantic_valid,
            "objective_correct": objective_correct,
            "objective_absolute_error": objective_error,
            "reference_audit": audit}
