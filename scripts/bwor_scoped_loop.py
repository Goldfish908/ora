#!/usr/bin/env python3
"""Reference-bound scoped-objective controls on shared BWOR development initials."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.acceptance import can_accept
from ora_agent.dvsa import InvalidSpec
from ora_agent.dvsa_model import solve_model, validate_model
from ora_agent.dvsa_repair import schema_errors, score_solution
from ora_agent.repair_controller import ProgressController
from ora_agent.scoped_assets import compile_asset, load_asset, validate_asset
from ora_agent.scoped_ir import evaluate_spec
from scripts.scoped_ir_gate import gate as run_gate

IDS = ("BWOR-058", "BWOR-001", "BWOR-009", "BWOR-029",
       "BWOR-039", "BWOR-042", "BWOR-056", "BWOR-066")
POLICIES = ("no_repair", "fixed", "progress")
SPLITS = ("dev", "validation")
MAX_REPAIRS = 2
TEMPLATE = ROOT / "assets/scoped_ir/objective_recompute_v0.1.json"
FAMILIES = {
    "BWOR-058": "retail_tenant_selection_and_leasing",
    "BWOR-001": "candy_recipe_blending",
    "BWOR-009": "production_inventory_with_delivery_contract",
    "BWOR-029": "healthcare_shift_staffing",
    "BWOR-039": "paper_goods_product_mix",
    "BWOR-042": "unscreened_development_problem",
    "BWOR-056": "course_selection",
    "BWOR-066": "multi_period_warehouse_distribution",
}
ELIGIBILITY_RULES = (
    "Discover exactly one case location using only dev/validation directories.",
    "Require initial candidate.json/solution.json/result.json and independent question.txt/model.json/solution.json.",
    "Require valid DVSA models and exact shared variable names/domains/bounds; never relabel a schema mismatch.",
    "Require the independent reference solution to score clean against its own model.",
    "Require matching objective sense between candidate and independent reference.",
    "Admit an initially incorrect case only for registered BWOR-058 and only when its independent audit has exactly OBJECTIVE violations and no UNKNOWN evidence.",
    "Exclude every other initially incorrect case without changing its label; initially correct eligible cases must stop unchanged at round 0.",
)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                      allow_nan=False).encode()).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_text(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(",", ":"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1,
                               allow_nan=False) + "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def file_record(path: Path) -> dict:
    return {"path": relative(path), "sha256": file_digest(path)}


def discover_split(problem_id: str) -> tuple[str | None, dict]:
    locations = []
    for split in SPLITS:
        initial = ROOT / "work/dvsa/bwor_repair" / split / problem_id / "initial"
        reference = ROOT / "work/dvsa/bwor_reference" / split / problem_id
        if initial.is_dir() or reference.is_dir():
            locations.append(split)
    details = {"authorized_splits": list(SPLITS), "locations": locations}
    if len(locations) != 1:
        return None, details
    return locations[0], details


def excluded_case(problem_id: str, split: str | None, reason: str,
                  details: dict | None = None) -> dict:
    return {"id": problem_id, "split": split, "eligible": False,
            "status": "excluded", "exclusion_reason": reason,
            "details": details or {}, "family": FAMILIES[problem_id]}


def independent_score(case: dict, solution) -> dict:
    reference_solution = case["reference"]["solution"]
    return score_solution({"model": case["reference"]["model"]}, solution,
                          reference_solution["objective"])


def load_screened_case(problem_id: str) -> dict:
    if problem_id not in IDS:
        raise ValueError(f"unregistered problem ID: {problem_id}")
    split, discovery = discover_split(problem_id)
    if split is None:
        return excluded_case(problem_id, None, "split_discovery_failed", discovery)
    initial_dir = ROOT / "work/dvsa/bwor_repair" / split / problem_id / "initial"
    reference_dir = ROOT / "work/dvsa/bwor_reference" / split / problem_id
    paths = {
        "initial_candidate": initial_dir / "candidate.json",
        "initial_solution": initial_dir / "solution.json",
        "initial_result": initial_dir / "result.json",
        "question": reference_dir / "question.txt",
        "reference_model": reference_dir / "model.json",
        "reference_solution": reference_dir / "solution.json",
    }
    missing = [relative(path) for path in paths.values() if not path.is_file()]
    if missing:
        return excluded_case(problem_id, split, "missing_required_artifacts",
                             {"missing": missing, "discovery": discovery})
    provenance = {key: file_record(path) for key, path in paths.items()}
    try:
        candidate = json.loads(paths["initial_candidate"].read_text())
        initial_solution = json.loads(paths["initial_solution"].read_text())
        initial_result = json.loads(paths["initial_result"].read_text())
        question = paths["question"].read_text()
        reference_text = paths["reference_model"].read_text()
        reference_model = json.loads(reference_text)
        reference_solution = json.loads(paths["reference_solution"].read_text())
        validate_model(candidate)
        validate_model(reference_model)
        if candidate.get("problem_id") != problem_id or reference_model.get("problem_id") != problem_id:
            return excluded_case(problem_id, split, "problem_id_mismatch", provenance)
    except (InvalidSpec, ValueError, TypeError, KeyError) as exc:
        return excluded_case(problem_id, split, "invalid_required_artifact",
                             {"error": str(exc), "provenance": provenance})
    errors = schema_errors(candidate, reference_model["variables"])
    if errors:
        return excluded_case(problem_id, split, "shared_variable_schema_mismatch",
                             {"schema_errors": errors, "provenance": provenance})
    case = {
        "id": problem_id,
        "split": split,
        "family": FAMILIES[problem_id],
        "eligible": True,
        "status": "screened",
        "question": question,
        "reference_text": reference_text,
        "reference": {"model": reference_model, "solution": reference_solution},
        "initial": {
            "model": candidate,
            "solution": initial_solution,
            "solve": copy.deepcopy(initial_result.get("solve") or {
                "status": initial_result.get("status", "UNKNOWN"),
                "error": initial_result.get("error"),
            }),
        },
        "provenance": {**provenance, "discovery": discovery,
                       "public_dataset_answer_used": False,
                       "independent_score_target": "reference_solution.objective"},
    }
    reference_score = independent_score(case, reference_solution)
    if not reference_score["business_correct"]:
        return excluded_case(problem_id, split, "reference_solution_not_clean",
                             {"reference_score": reference_score,
                              "provenance": case["provenance"]})
    if candidate["objective"]["sense"] != reference_model["objective"]["sense"]:
        return excluded_case(problem_id, split, "objective_sense_mismatch",
                             {"candidate_sense": candidate["objective"]["sense"],
                              "reference_sense": reference_model["objective"]["sense"],
                              "provenance": case["provenance"]})
    initial_score = independent_score(case, initial_solution)
    case["initial_score"] = initial_score
    case["reference_score"] = reference_score
    if not initial_score["business_correct"]:
        audit = initial_score.get("reference_audit") or {}
        rules = {item.get("rule") for item in audit.get("violations", [])}
        natural_objective_error = (audit.get("verdict") == "INVALID"
                                   and not audit.get("unknown")
                                   and rules == {"OBJECTIVE"})
        case["natural_objective_error"] = natural_objective_error
        if problem_id != "BWOR-058":
            return excluded_case(problem_id, split, "unregistered_initial_incorrectness",
                                 {"initial_score": initial_score,
                                  "provenance": case["provenance"]})
        if not natural_objective_error:
            return excluded_case(problem_id, split, "registered_case_is_not_objective_only_error",
                                 {"initial_score": initial_score,
                                  "provenance": case["provenance"]})
    else:
        case["natural_objective_error"] = False
    return case


def _number(value) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def _constant_path(expression: str, data: dict):
    parts = expression.split(".")
    if parts[0] != "data" or len(parts) < 2:
        raise ValueError(f"objective constant path must start with data.: {expression}")
    value = data
    for part in parts[1:]:
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"unbound objective constant path: {expression}")
        value = value[part]
    if not _number(value):
        raise ValueError(f"objective path is not a finite numeric constant: {expression}")
    return value


def _merge_linear(left, right, right_scale=1):
    constant = left[0] + right_scale * right[0]
    terms = dict(left[1])
    for name, coefficient in right[1].items():
        terms[name] = terms.get(name, 0) + right_scale * coefficient
        if terms[name] == 0:
            del terms[name]
    return constant, terms


def _linear_expression(expression, model) -> tuple[float, dict]:
    variables = model["variables"]
    if _number(expression):
        return expression, {}
    if not isinstance(expression, dict) or len(expression) != 1:
        raise ValueError("objective expression must be a number or single-operator object")
    operator, argument = next(iter(expression.items()))
    if operator == "var":
        if argument not in variables:
            raise ValueError(f"unbound objective variable: {argument}")
        return 0, {argument: 1}
    if operator == "path":
        return _constant_path(argument, model.get("data", {})), {}
    if operator in {"add", "sum"}:
        if not isinstance(argument, list):
            raise ValueError(f"{operator} objective operand must be a list")
        result = (0, {})
        for item in argument:
            result = _merge_linear(result, _linear_expression(item, model))
        return result
    if operator == "neg":
        constant, terms = _linear_expression(argument, model)
        return -constant, {name: -value for name, value in terms.items()}
    if operator == "sub":
        if not isinstance(argument, list) or len(argument) != 2:
            raise ValueError("sub objective operand must contain two items")
        return _merge_linear(_linear_expression(argument[0], model),
                             _linear_expression(argument[1], model), -1)
    if operator == "mul":
        if not isinstance(argument, list):
            raise ValueError("mul objective operand must be a list")
        factors = [_linear_expression(item, model) for item in argument]
        varying = [factor for factor in factors if factor[1]]
        if len(varying) > 1:
            raise ValueError("nonlinear product in independent objective")
        scale = 1
        for factor in factors:
            if not factor[1]:
                scale *= factor[0]
        if not varying:
            return scale, {}
        constant, terms = varying[0]
        if constant != 0:
            raise ValueError("nonlinear product with a nonconstant affine factor")
        return 0, {name: scale * value for name, value in terms.items()}
    if operator == "div":
        if not isinstance(argument, list) or len(argument) != 2:
            raise ValueError("div objective operand must contain two items")
        numerator = _linear_expression(argument[0], model)
        denominator = _linear_expression(argument[1], model)
        if denominator[1] or denominator[0] == 0:
            raise ValueError("objective division requires a nonzero constant denominator")
        scale = 1 / denominator[0]
        return numerator[0] * scale, {name: value * scale
                                     for name, value in numerator[1].items()}
    raise ValueError(f"unsupported independent objective operator: {operator}")


def scoped_objective(case: dict) -> tuple[dict, dict, dict]:
    reference = case["reference"]["model"]
    constant, coefficients = _linear_expression(reference["objective"]["expression"], reference)
    terms = [{"path": f"solution.variables.{name}", "coefficient": coefficient}
             for name, coefficient in coefficients.items() if coefficient != 0]
    binding = {
        "invariant_id": f"{case['id'].lower().replace('-', '_')}_business_objective",
        "source_span": case["question"],
        "terms": terms,
    }
    template = load_asset(TEMPLATE)
    template_validation = validate_asset(template)
    if template_validation["status"] != "validated":
        raise ValueError("objective_recompute template failed mechanism validation")
    spec = compile_asset(template, binding)
    invariant = spec["invariants"][0]
    if constant != 0:
        invariant["rhs"] = ({"add": [invariant["rhs"], constant]}
                            if terms else constant)
    invariant["source_evidence"] = {
        "type": "independent_reference",
        "reference": case["provenance"]["reference_model"]["path"],
        "text": case["reference_text"],
        "span": case["reference_text"],
        "sha256": case["provenance"]["reference_model"]["sha256"],
    }
    binding_record = {
        **binding,
        "constant": constant,
        "reference_expression": copy.deepcopy(reference["objective"]["expression"]),
        "reference_expression_sha256": digest(reference["objective"]["expression"]),
        "scoped_rhs": copy.deepcopy(invariant["rhs"]),
        "question_sha256": case["provenance"]["question"]["sha256"],
        "reference_model_sha256": case["provenance"]["reference_model"]["sha256"],
        "reference_solution_sha256": case["provenance"]["reference_solution"]["sha256"],
        "template": relative(TEMPLATE),
        "template_sha256": file_digest(TEMPLATE),
    }
    return spec, binding_record, template_validation


def reference_violation_labels(score: dict) -> list[str]:
    audit = score.get("reference_audit") or {}
    return sorted({str(item["rule"]) for item in audit.get("violations", []) if "rule" in item})


def validation_cells(case: dict) -> list[dict]:
    initial_wrong = not case["initial_score"]["business_correct"]
    initial_labels = reference_violation_labels(case["initial_score"]) if initial_wrong else []
    mutation = ("natural_initial_clean" if not initial_wrong else
                "natural_initial_objective_error" if initial_labels == ["OBJECTIVE"]
                else "natural_initial_reference_error")
    wrong_objective = copy.deepcopy(case["reference"]["solution"])
    objective = float(wrong_objective["objective"])
    wrong_objective["objective"] = objective + max(1.0, abs(objective) * 1e-3)
    return [
        {"key": "reference_clean", "wrong": False,
         "mutation": "independent_reference_clean", "reference_violations": [],
         "solution": copy.deepcopy(case["reference"]["solution"])},
        {"key": "natural_initial", "wrong": initial_wrong, "mutation": mutation,
         "reference_violations": initial_labels,
         "solution": copy.deepcopy(case["initial"]["solution"])},
        {"key": "wrong_objective", "wrong": True,
         "mutation": "independent_reference_objective_plus_delta",
         "reference_violations": ["business_objective"], "solution": wrong_objective},
    ]


def prepare_case(case: dict) -> dict:
    if not case.get("eligible"):
        raise ValueError(f"cannot prepare excluded case: {case['id']}")
    prepared = copy.deepcopy(case)
    spec, binding, template_validation = scoped_objective(prepared)
    cells = validation_cells(prepared)
    gate_result = run_gate(spec, prepared["question"], cells, prepared["id"])
    wrong_score = independent_score(prepared, cells[2]["solution"])
    independent_checks = {
        "reference_clean": prepared["reference_score"],
        "natural_initial": prepared["initial_score"],
        "wrong_objective": wrong_score,
    }
    strict = (gate_result["accepted"]
              and prepared["reference_score"]["business_correct"]
              and not wrong_score["business_correct"]
              and (prepared["initial_score"]["business_correct"]
                   == (not cells[1]["wrong"])))
    gate_result.update({
        "accepted": strict,
        "status": "accepted" if strict else "rejected",
        "independent_scores": independent_checks,
        "natural_error_present": cells[1]["wrong"],
        "strict_reference_clean_required": True,
        "strict_wrong_objective_rejection_required": True,
        "repair_permitted": strict,
    })
    prepared.update({
        "spec": spec,
        "spec_sha256": digest(spec),
        "binding": binding,
        "template_validation": template_validation,
        "cells": cells,
        "gate": gate_result,
    })
    return prepared


def repair_objective_expression(candidate: dict, reference_expression: dict) -> dict:
    repaired = copy.deepcopy(candidate)
    if not isinstance(repaired.get("objective"), dict):
        raise ValueError("candidate objective object is missing")
    repaired["objective"]["expression"] = copy.deepcopy(reference_expression)
    for field in ("variables", "constraints", "data"):
        if repaired.get(field) != candidate.get(field):
            raise AssertionError(f"objective-only repair changed {field}")
    if repaired["objective"].get("sense") != candidate["objective"].get("sense"):
        raise AssertionError("objective-only repair changed sense")
    validate_model(repaired)
    return repaired


def candidate_audit(spec: dict, question: str, solution, problem_id: str) -> dict:
    if not isinstance(solution, dict) or not isinstance(solution.get("variables"), dict):
        return {"key": "candidate", "wrong": False, "mutation": "candidate",
                "reference_violations": [], "status": "unknown",
                "asset_status": "UNKNOWN", "fired": False, "violations": [],
                "unknown_evidence": [{"rule": "solution", "detail": "no solution variables"}],
                "rejected": [], "error": "no_solution", "not_applicable": 0}
    cell = {"key": "candidate", "wrong": False, "mutation": "candidate",
            "reference_violations": [], "solution": solution}
    return evaluate_spec(spec, question, [cell], problem_id)["records"][0]


def save_case_assets(case: dict, outdir: Path) -> None:
    case_dir = outdir / case["id"]
    initial = case["initial"]
    write_json(case_dir / "shared_initial/model.json", initial["model"])
    write_json(case_dir / "shared_initial/solution.json", initial["solution"])
    write_json(case_dir / "shared_initial/solve.json", initial["solve"])
    write_json(case_dir / "shared_initial/initial_independent_score.json", case["initial_score"])
    write_text(case_dir / "reference/question.txt", case["question"])
    write_json(case_dir / "reference/model.json", case["reference"]["model"])
    write_json(case_dir / "reference/solution.json", case["reference"]["solution"])
    write_json(case_dir / "reference/independent_score.json", case["reference_score"])
    write_json(case_dir / "scoped_ir/spec.json", case["spec"])
    write_json(case_dir / "scoped_ir/binding.json", case["binding"])
    write_json(case_dir / "scoped_ir/gate.json", case["gate"])
    write_json(case_dir / "scoped_ir/validation_cells.json", case["cells"])
    write_json(case_dir / "scoped_ir/template_validation.json", case["template_validation"])
    write_json(case_dir / "provenance.json", case["provenance"])


def save_snapshot(directory: Path, current: dict) -> dict:
    write_json(directory / "model.json", current["model"])
    write_json(directory / "solution.json", current["solution"])
    write_json(directory / "solve.json", current["solve"])
    return {"model_sha256": digest(current["model"]),
            "solution_sha256": digest(current["solution"]),
            "solve_sha256": digest(current["solve"])}


def _action(name: str, before: str, reason: str, repairer: str | None = None,
            after: str | None = None, solver_runs: int = 0) -> dict:
    after = before if after is None else after
    return {"name": name, "reason": reason, "before_sha256": before,
            "after_sha256": after, "model_changed": before != after,
            "changed_fields": ["objective.expression"] if before != after and repairer else [],
            "repairer": repairer, "llm_calls": 0, "tokens": 0,
            "cost": {"llm_calls": 0, "tokens": 0, "solver_runs": solver_runs}}


def run_problem(case: dict, policy: str, outdir: Path, max_repairs: int = MAX_REPAIRS,
                time_limit: float = 60.0, prepare_assets: bool = True) -> dict:
    if policy not in POLICIES:
        raise ValueError(f"unsupported policy: {policy}")
    if max_repairs != MAX_REPAIRS:
        raise ValueError("the registered protocol requires exactly two repair opportunities")
    started = time.monotonic()
    if prepare_assets:
        save_case_assets(case, outdir)
    initial = copy.deepcopy(case["initial"])
    initial_hash = digest(initial["model"])
    current = copy.deepcopy(initial)
    accepted = None
    accepted_round = None
    stop_reason = None
    history = []
    snapshots = []
    transforms = 0
    solver_runs = 0
    controller = ProgressController() if policy == "progress" else None
    case_dir = outdir / case["id"] / policy
    checker_status = case["gate"]["status"]

    for round_idx in range(max_repairs + 1):
        round_dir = case_dir / f"round_{round_idx:03d}"
        hashes = save_snapshot(round_dir, current)
        snapshots.append(copy.deepcopy(current))
        audit = candidate_audit(case["spec"], case["question"], current["solution"], case["id"])
        entry = {"round": round_idx, **hashes, "initial_model_sha256": initial_hash,
                 "audit": audit, "checker_status": checker_status,
                 "llm_calls": 0, "tokens": 0,
                 "artifacts": {"directory": relative(round_dir) if round_dir.is_relative_to(ROOT)
                               else str(round_dir)}}
        history.append(entry)
        if can_accept(audit, case["gate"]):
            accepted = copy.deepcopy(current)
            accepted_round = round_idx
            stop_reason = "accepted"
            entry["action"] = _action("accept", hashes["model_sha256"], "accepted")
            break
        if checker_status != "accepted":
            stop_reason = "repair_checker_required"
            entry["action"] = _action("stop", hashes["model_sha256"], stop_reason)
            break
        if policy == "no_repair":
            stop_reason = "no_repair_control"
            entry["action"] = _action("no_repair", hashes["model_sha256"], stop_reason)
            break
        if not audit.get("fired"):
            stop_reason = audit.get("status") or "not_accepted"
            entry["action"] = _action("stop", hashes["model_sha256"], stop_reason)
            break
        if round_idx >= max_repairs:
            stop_reason = "budget_exhausted"
            entry["action"] = _action("stop", hashes["model_sha256"], stop_reason)
            break

        action = "local_patch"
        reason = "fixed_local_patch"
        decision = None
        if controller is not None:
            decision = controller.decide(json_text(current["model"]), current["solve"], audit,
                                         max_repairs - round_idx, checker_status)
            action = decision.action
            reason = decision.reason
            entry["controller_decision"] = decision.__dict__
            if action != "local_patch":
                stop_reason = reason if action == "stop" else action + "_unavailable"
                entry["action"] = _action(action, hashes["model_sha256"], stop_reason)
                break

        before_hash = digest(current["model"])
        repaired = repair_objective_expression(
            current["model"], case["reference"]["model"]["objective"]["expression"])
        after_hash = digest(repaired)
        model_changed = repaired != current["model"]
        round_solver_runs = 0
        if model_changed:
            solved = solve_model(repaired, time_limit=time_limit)
            solver_runs += 1
            round_solver_runs = 1
        else:
            solved = copy.deepcopy(current["solve"])
        transforms += 1
        entry["action"] = _action(action, before_hash, reason,
                                  repair_objective_expression.__name__, after_hash,
                                  round_solver_runs)
        entry["action"]["solve_status"] = solved.get("status")
        if controller is not None:
            controller.record(decision, json_text(repaired))
        current = {"model": repaired, "solution": solved.get("solution"), "solve": solved}

    final = accepted if accepted is not None else initial
    for entry, snapshot in zip(history, snapshots):
        entry["independent_score"] = independent_score(case, snapshot["solution"])
        entry["cost"] = {"llm_calls": 0, "tokens": 0,
                         "solver_runs": entry["action"]["cost"]["solver_runs"]}
    final_score = independent_score(case, final["solution"])
    last_score = independent_score(case, current["solution"])
    final_hashes = save_snapshot(case_dir / "final", final)
    improved = (not case["initial_score"]["business_correct"]
                and final_score["business_correct"])
    recovery = bool(case["id"] == "BWOR-058" and improved
                    and accepted_round not in (None, 0) and transforms > 0
                    and case["gate"]["accepted"])
    negative_result = None
    if case["initial_score"]["business_correct"] is False and not improved:
        negative_result = {"kind": "unrecovered_natural_initial_error",
                           "stop_reason": stop_reason,
                           "fallback_to_initial": accepted is None,
                           "final_reference_correct": False}
    result = {
        "id": case["id"], "split": case["split"], "family": case["family"],
        "policy": policy, "status": "completed",
        "initial_model_sha256": initial_hash,
        "final_model_sha256": final_hashes["model_sha256"],
        "spec_sha256": case["spec_sha256"],
        "gate_accepted": case["gate"]["accepted"],
        "initial_score": case["initial_score"], "final_score": final_score,
        "last_candidate_score": last_score, "history": history,
        "accepted": accepted is not None, "accepted_round": accepted_round,
        "baseline_fallback": accepted is None, "stop_reason": stop_reason,
        "controller_trace": controller.trace() if controller else [],
        "no_progress_attempts": controller.no_progress_count if controller else None,
        "deterministic_transforms": transforms, "solver_runs_this_run": solver_runs,
        "llm_calls": 0, "tokens": 0,
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "cost": {"llm_calls": 0, "tokens": 0, "solver_runs": solver_runs,
                 "deterministic_transforms": transforms},
        "improved": improved,
        "harmed_win": bool(case["initial_score"]["business_correct"]
                           and not final_score["business_correct"]),
        "reference_bound_development_recovery": recovery,
        "natural_first_recovery": False,
        "nl_cold_start": False,
        "round0_unchanged": bool(accepted_round == 0 and transforms == 0
                                 and final_hashes["model_sha256"] == initial_hash),
        "accepted_but_reference_incorrect": bool(accepted is not None
                                                  and not final_score["business_correct"]),
        "negative_result": negative_result,
        "wall_s": round(time.monotonic() - started, 6),
    }
    write_json(case_dir / "result.json", result)
    return result


def summarize(results: list[dict], policy: str) -> dict:
    rows = [row for row in results if row["policy"] == policy]
    return {
        "n": len(rows),
        "initial_reference_correct": sum(row["initial_score"]["business_correct"] for row in rows),
        "final_reference_correct": sum(row["final_score"]["business_correct"] for row in rows),
        "improved": sum(row["improved"] for row in rows),
        "reference_bound_development_recoveries": sum(
            row["reference_bound_development_recovery"] for row in rows),
        "natural_first_recoveries": 0,
        "round0_unchanged": sum(row["round0_unchanged"] for row in rows),
        "harmed_win": sum(row["harmed_win"] for row in rows),
        "accepted_but_reference_incorrect": sum(row["accepted_but_reference_incorrect"] for row in rows),
        "accepted": sum(row["accepted"] for row in rows),
        "baseline_fallback": sum(row["baseline_fallback"] for row in rows),
        "gate_rejected": sum(not row["gate_accepted"] for row in rows),
        "negative_results": sum(row["negative_result"] is not None for row in rows),
        "deterministic_transforms": sum(row["deterministic_transforms"] for row in rows),
        "solver_runs_this_run": sum(row["solver_runs_this_run"] for row in rows),
        "no_progress_attempts": sum(row.get("no_progress_attempts") or 0 for row in rows),
        "llm_calls": 0,
        "tokens": 0,
    }


def input_manifest(ids: tuple[str, ...]) -> dict:
    records = {}
    for problem_id in ids:
        split, discovery = discover_split(problem_id)
        entry = {"discovery": discovery, "files": {}}
        if split is not None:
            paths = {
                "initial_candidate": ROOT / f"work/dvsa/bwor_repair/{split}/{problem_id}/initial/candidate.json",
                "initial_solution": ROOT / f"work/dvsa/bwor_repair/{split}/{problem_id}/initial/solution.json",
                "initial_result": ROOT / f"work/dvsa/bwor_repair/{split}/{problem_id}/initial/result.json",
                "question": ROOT / f"work/dvsa/bwor_reference/{split}/{problem_id}/question.txt",
                "reference_model": ROOT / f"work/dvsa/bwor_reference/{split}/{problem_id}/model.json",
                "reference_solution": ROOT / f"work/dvsa/bwor_reference/{split}/{problem_id}/solution.json",
            }
            entry["files"] = {key: (file_record(path) if path.is_file()
                                    else {"path": relative(path), "sha256": None, "missing": True})
                              for key, path in paths.items()}
        records[problem_id] = entry
    return records


def run_all(outdir: Path, ids=IDS, resume: bool = False,
            time_limit: float = 60.0, min_eligible: int | None = None) -> dict:
    ids = tuple(ids)
    if set(ids) - set(IDS) or len(set(ids)) != len(ids):
        raise ValueError("IDs must be unique members of the registered development cohort")
    min_eligible = (len(IDS) - 2) if ids == IDS and min_eligible is None else (min_eligible or 0)
    config = {
        "schema_version": "bwor.scoped_loop.v0.2",
        "ids": list(ids), "policies": list(POLICIES), "max_repairs": MAX_REPAIRS,
        "authorized_splits": list(SPLITS), "template_sha256": file_digest(TEMPLATE),
        "implementation_sha256": file_digest(Path(__file__)),
        "eligibility_rules": list(ELIGIBILITY_RULES), "families": {key: FAMILIES[key] for key in ids},
        "time_limit_s": time_limit, "minimum_eligible": min_eligible,
        "public_dataset_answers_read": False, "llm_or_external_api_calls": 0,
        "independent_score_target": "independent_reference_solution.objective",
        "input_manifest": input_manifest(ids),
    }
    config["config_sha256"] = digest(config)
    analysis_path = outdir / "analysis.json"
    if analysis_path.exists():
        previous = json.loads(analysis_path.read_text())
        if resume and previous["run_config"] == config:
            return previous
        raise ValueError("existing analysis has a different configuration; choose a new output directory")

    screened = [load_screened_case(problem_id) for problem_id in ids]
    eligible = [case for case in screened if case["eligible"]]
    excluded = [case for case in screened if not case["eligible"]]
    outdir.mkdir(parents=True, exist_ok=True)
    for case in excluded:
        write_json(outdir / case["id"] / "exclusion.json", case)
    results = []
    for case in eligible:
        prepared = prepare_case(case)
        save_case_assets(prepared, outdir)
        for policy in POLICIES:
            results.append(run_problem(prepared, policy, outdir,
                                       time_limit=time_limit, prepare_assets=False))

    negative_results = [{"id": case["id"], "kind": "screening_exclusion",
                         "reason": case["exclusion_reason"], "details": case["details"]}
                        for case in excluded]
    negative_results.extend({"id": row["id"], "policy": row["policy"], **row["negative_result"]}
                            for row in results if row["negative_result"] is not None)
    by_id = {}
    for case in eligible:
        rows = [row for row in results if row["id"] == case["id"]]
        initial_hashes = {row["initial_model_sha256"] for row in rows}
        fixed = next(row for row in rows if row["policy"] == "fixed")
        progress = next(row for row in rows if row["policy"] == "progress")
        by_id[case["id"]] = {
            "shared_initial_hash_across_arms": len(initial_hashes) == 1,
            "fixed_progress_same_final_model": fixed["final_model_sha256"] == progress["final_model_sha256"],
            "fixed_progress_same_accepted_round": fixed["accepted_round"] == progress["accepted_round"],
            "initial_reference_correct": case["initial_score"]["business_correct"],
            "natural_objective_error": case["natural_objective_error"],
        }
    families = sorted({case["family"] for case in eligible})
    analysis = {
        "run_config": config,
        "denominators": {"screened": len(ids), "eligible": len(eligible),
                         "excluded": len(excluded), "per_arm": len(eligible),
                         "natural_recovery_opportunities": sum(
                             not case["initial_score"]["business_correct"] for case in eligible)},
        "arms": {policy: summarize(results, policy) for policy in POLICIES},
        "family_coverage": {"unique_families": len(families), "families": families,
                            "by_split": {split: sum(case["split"] == split for case in eligible)
                                         for split in SPLITS}},
        "paired_checks": by_id,
        "exclusions": excluded,
        "negative_results": negative_results,
        "results": results,
        "limitations": [
            "This is a small development-cohort control, not frozen/sealed evaluation or evidence of NL cold start.",
            "BWOR-058 recovery is reference-bound deterministic objective replacement from a pre-existing natural initial; it is not a first natural recovery.",
            "The scoped checker validates only the independent business objective expression; full final scoring separately uses the independent reference model and solution.",
            "Initially correct cases measure round-0 preservation, not repair effectiveness.",
            "BWOR-001 and BWOR-042 exclusions are reported under preregistered artifact/schema rules without changing labels.",
            "No public dataset answer, LLM, external API, frozen split, or sealed split is used by this run.",
        ],
    }
    write_json(analysis_path, analysis)
    write_json(outdir / "negative_results.json", negative_results)
    summary = {key: analysis[key] for key in
               ("run_config", "denominators", "arms", "family_coverage", "paired_checks",
                "exclusions", "negative_results", "limitations")}
    write_json(outdir / "summary.json", summary)
    if len(eligible) < min_eligible:
        raise ValueError(f"eligible denominator {len(eligible)} is below required {min_eligible}")
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="+", default=list(IDS))
    parser.add_argument("--out", default="work/bwor_scoped_loop_v0.1")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--time-limit", type=float, default=60.0)
    args = parser.parse_args()
    outdir = Path(args.out)
    if not outdir.is_absolute():
        outdir = ROOT / outdir
    analysis = run_all(outdir, tuple(args.ids), args.resume, args.time_limit)
    print(json.dumps({"denominators": analysis["denominators"], "arms": analysis["arms"],
                      "family_coverage": analysis["family_coverage"]},
                     ensure_ascii=False, indent=1))
    if any(analysis["arms"][policy]["harmed_win"]
           or analysis["arms"][policy]["accepted_but_reference_incorrect"]
           for policy in POLICIES):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
