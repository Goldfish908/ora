"""Structured formulation candidates with iterative confidence feedback."""
from __future__ import annotations

import json
import math

from ora_agent.scoped_ir import extract_spec

DIMENSIONS = ("parameters", "variables", "constraints", "objective")
MODEL_INSTRUCTION = """You construct an optimization formulation, not solver code.
Return ONLY one JSON object with parameters, variables, objective and constraints.
- parameters: [{"name": str, "value": finite JSON value, "source": str}]
- variables: [{"name": str, "symbol": str, "type": "continuous"|"integer"|"binary", "bounds": finite JSON value, "source": str}]
- objective: {"direction": "minimize"|"maximize", "expression": str, "variables": [str], "source": str}
- constraints: [{"name": str, "expression": str, "type": str, "source": str}]
Every source must be a short VERBATIM quote from the original problem that supports that element.
Do not use or guess a reference objective. Do not invent requirements unsupported by the problem.
"""
EVALUATION_INSTRUCTION = """Evaluate a structured optimization formulation against the original problem.
Return ONLY JSON: {"scores":{"parameters":number,"variables":number,"constraints":number,"objective":number},"weak_points":[str]}.
Scores are confidence from 0 to 100. Be conservative when a required element is missing or inconsistent.
Identify concrete weaknesses that a later formulation should address. Do not use a reference objective or execute code.
"""
CODE_INSTRUCTION = """Implement the selected structured formulation faithfully as a PySCIPOpt script.
Preserve its business variables, objective direction and constraints. Output ONLY executable Python code.
"""


def model_prompt(question: str, history: list[dict]) -> str:
    guidance = ("Generate the first formulation." if not history else
                "Generate a revised formulation that explicitly addresses earlier low-confidence dimensions "
                "and weak_points. Do not merely rename variables or repeat the same modeling mistake.")
    return (MODEL_INSTRUCTION + "\n" + guidance + "\n\n[ORIGINAL PROBLEM]\n" + question
            + "\n\n[PREVIOUS CANDIDATES AND EVALUATIONS]\n"
            + json.dumps(history, ensure_ascii=False, indent=1))


def evaluation_prompt(question: str, model: dict) -> str:
    return (EVALUATION_INSTRUCTION + "\n[ORIGINAL PROBLEM]\n" + question
            + "\n\n[CANDIDATE FORMULATION]\n" + json.dumps(model, ensure_ascii=False, indent=1))


def code_prompt(question: str, model: dict) -> str:
    return (CODE_INSTRUCTION + "\n[ORIGINAL PROBLEM]\n" + question
            + "\n\n[SELECTED FORMULATION]\n" + json.dumps(model, ensure_ascii=False, indent=1))


def parse_json(text: str) -> dict:
    value = extract_spec(text)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def source_in_question(source, question: str) -> bool:
    if not isinstance(source, str) or not source.strip():
        return False
    normalized_source = " ".join(source.split())
    normalized_question = " ".join(question.split())
    return normalized_source in normalized_question


def validate_model(model: dict, question: str) -> list[str]:
    errors = []
    if not isinstance(model, dict):
        return ["model must be an object"]
    try:
        json.dumps(model, allow_nan=False)
    except (TypeError, ValueError):
        return ["model must contain finite JSON values"]
    for field in ("parameters", "variables", "constraints"):
        if not isinstance(model.get(field), list):
            errors.append(f"{field} must be a list")
    if not model.get("variables"):
        errors.append("at least one variable is required")
    for field in ("parameters", "variables", "constraints"):
        values = model.get(field)
        if not isinstance(values, list):
            continue
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                errors.append(f"{field}[{index}] must be an object")
                continue
            for required in (("name", "value", "source") if field == "parameters"
                             else ("name", "expression", "source") if field == "constraints"
                             else ("name", "symbol", "type", "bounds", "source")):
                if required not in item:
                    errors.append(f"{field}[{index}] missing {required}")
            if field == "variables" and item.get("type") not in {"continuous", "integer", "binary"}:
                errors.append(f"variables[{index}] has unsupported type")
            source = item.get("source")
            if not source_in_question(source, question):
                errors.append(f"{field}[{index}] source is not verbatim problem text")
    objective = model.get("objective")
    if not isinstance(objective, dict):
        errors.append("objective must be an object")
    else:
        if objective.get("direction") not in {"minimize", "maximize"}:
            errors.append("objective direction must be minimize or maximize")
        if not isinstance(objective.get("expression"), str) or not objective["expression"].strip():
            errors.append("objective expression is required")
        if not isinstance(objective.get("variables"), list):
            errors.append("objective variables must be a list")
        source = objective.get("source")
        if not source_in_question(source, question):
            errors.append("objective source is not verbatim problem text")
    return errors


def validate_evaluation(value: dict) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("scores"), dict):
        raise ValueError("evaluation scores are missing")
    result = {}
    for dimension in DIMENSIONS:
        score = value["scores"].get(dimension)
        if isinstance(score, bool) or not isinstance(score, (int, float)) \
                or not math.isfinite(score) or not 0 <= score <= 100:
            raise ValueError(f"invalid confidence for {dimension}")
        result[dimension] = float(score)
    weak_points = value.get("weak_points", [])
    if not isinstance(weak_points, list) or any(not isinstance(item, str) for item in weak_points):
        raise ValueError("weak_points must be a list of strings")
    return {"scores": result, "weak_points": weak_points}


def select_max_min(candidates: list[dict]) -> tuple[int, dict, str]:
    minima = {}
    for index, candidate in enumerate(candidates):
        scores = candidate["evaluation"].get("scores") or {}
        if candidate.get("schema_errors") or not scores:
            continue
        minima[candidate["candidate_id"]] = min(scores.values())
    if not minima:
        return 0, {}, "no_valid_candidate_fallback_first"
    best = max(minima.values())
    selected = next(index for index, candidate in enumerate(candidates)
                    if minima.get(candidate["candidate_id"]) == best)
    return selected, minima, "max_min_confidence"
