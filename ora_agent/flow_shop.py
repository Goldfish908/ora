"""Independent structure and solution audits for two-machine permutation flow shops."""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from ora_agent.dvsa import InvalidSpec, UnknownValue
from ora_agent.dvsa_linear import linearize

TOL = 1e-5


@dataclass(frozen=True)
class LinearForm:
    relation: str
    coefficients: tuple[tuple[str, float], ...]
    bound: float


def duration_path(data: dict, stage: str, job: int) -> str:
    matches = [name for name in (f"{stage}{job}", f"{stage.lower()}{job}") if name in data]
    if len(matches) != 1:
        raise InvalidSpec(f"missing or ambiguous processing time: {stage}{job}")
    return matches[0]


def binding_for(model: dict, question: str) -> dict:
    data = model["data"]
    jobs = sorted({int(key[1:]) for key in data if key[0] in {"A", "a"} and key[1:].isdigit()})
    if not jobs or jobs != list(range(1, len(jobs) + 1)):
        raise InvalidSpec("flow-shop jobs require contiguous A<job> data")
    data_paths = {stage: {job: duration_path(data, stage, job) for job in jobs}
                  for stage in ("A", "B")}
    for stage in ("A", "B"):
        for job in jobs:
            value = data[data_paths[stage][job]]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise InvalidSpec(f"missing or invalid processing time: {stage}{job}")
    style = "_" if f"CA_{len(jobs)}" in model["variables"] else ""
    x_style = "_" if f"x_1_{len(jobs)}" in model["variables"] else ""
    objective = model["objective"].get("expression")
    makespan = objective.get("var") if isinstance(objective, dict) and set(objective) == {"var"} else None
    if makespan not in model["variables"]:
        raise InvalidSpec("only a declared scalar makespan objective is supported")
    return {
        "kind": "two_machine_permutation_flow_shop",
        "jobs": jobs, "positions": jobs, "question": question,
        "durations": {stage: {job: float(data[data_paths[stage][job]]) for job in jobs}
                      for stage in ("A", "B")},
        "data_paths": {stage: {job: "data." + data_paths[stage][job] for job in jobs}
                       for stage in ("A", "B")},
        "ca": lambda position: f"CA{style}{position}",
        "cb": lambda position: f"CB{style}{position}",
        "x": lambda position, job: f"x{x_style}{job}{x_style}{position}",
        "index_semantics": "x[job,position]",
        "makespan": makespan,
        "model_objective_sense": model["objective"]["sense"],
        "source": {"model_sha256": model.get("source_sha256"), "question": question},
    }


def term(variable: str, data_path: str) -> dict:
    return {"mul": [{"path": data_path}, {"var": variable}]}


def add(expressions: list[dict]) -> dict:
    return expressions[0] if len(expressions) == 1 else {"add": expressions}


def completion_constraints(binding: dict) -> list[dict]:
    rows = []
    for position in binding["positions"]:
        ca, cb = binding["ca"](position), binding["cb"](position)
        a_terms = [term(binding["x"](position, job), binding["data_paths"]["A"][job])
                   for job in binding["jobs"]]
        b_terms = [term(binding["x"](position, job), binding["data_paths"]["B"][job])
                   for job in binding["jobs"]]
        a_rhs = add(([] if position == 1 else [{"var": binding["ca"](position - 1)}]) + a_terms)
        rows.extend([
            {"constraint_id": f"job_completion:p{position}", "relation": "eq",
             "lhs": {"var": ca}, "rhs": a_rhs, "layer": "completion"},
            {"constraint_id": f"job_precedence:p{position}", "relation": "ge",
             "lhs": {"var": cb}, "rhs": add([{"var": ca}] + b_terms), "layer": "precedence"},
        ])
        if position > 1:
            b_rhs = add([{"var": binding["cb"](position - 1)}] + b_terms)
            rows.append({"constraint_id": f"job_machine_sequence:p{position}", "relation": "ge",
                         "lhs": {"var": cb}, "rhs": b_rhs, "layer": "machine_sequence"})
    if binding["makespan"] != binding["cb"](len(binding["jobs"])):
        rows.append({"constraint_id": "job_makespan", "relation": "eq",
                     "lhs": {"var": binding["makespan"]},
                     "rhs": {"var": binding["cb"](len(binding["jobs"]))}, "layer": "makespan"})
    for row in rows:
        row["source"] = binding["question"]
    return rows


def cut_constraints(binding: dict) -> list[dict]:
    rows = []
    for cut in binding["positions"]:
        terms = []
        for position in binding["positions"]:
            stages = ("A", "B") if position == cut else ("A",) if position < cut else ("B",)
            for job in binding["jobs"]:
                for stage in stages:
                    terms.append(term(binding["x"](position, job), binding["data_paths"][stage][job]))
        rows.append({"constraint_id": f"job_cut:k{cut}", "relation": "ge",
                     "lhs": {"var": binding["makespan"]}, "rhs": add(terms), "layer": "cut"})
    for row in rows:
        row["source"] = binding["question"]
    return rows


def canonical(model: dict, constraint: dict) -> LinearForm:
    lhs, lhs_const = linearize(constraint["lhs"], model)
    rhs, rhs_const = linearize(constraint["rhs"], model)
    coefficients = dict(lhs)
    for name, value in rhs.items():
        coefficients[name] = coefficients.get(name, 0.0) - value
    coefficients = {name: value for name, value in coefficients.items() if abs(value) > 1e-9}
    bound = rhs_const - lhs_const
    relation = constraint["relation"]
    if relation == "le":
        coefficients = {name: -value for name, value in coefficients.items()}
        bound = -bound
        relation = "ge"
    if relation == "eq":
        first = next((coefficients[name] for name in sorted(coefficients) if coefficients[name]), 1.0)
        if first < 0:
            coefficients = {name: -value for name, value in coefficients.items()}
            bound = -bound
    scale = max([abs(value) for value in coefficients.values()] + [abs(bound), 1.0])
    return LinearForm(relation, tuple(sorted((name, round(value / scale, 9))
                                               for name, value in coefficients.items())),
                      round(bound / scale, 9))


def align_duration_data(model: dict, binding: dict) -> tuple[dict, dict, list[dict], list[dict]]:
    prepared = copy.deepcopy(model)
    aliases, violations, unknown = {}, [], []
    for stage in ("A", "B"):
        for job, expected in binding["durations"][stage].items():
            key = binding["data_paths"][stage][job].split(".", 1)[1]
            matches = [name for name in model["data"] if name.casefold() == key.casefold()]
            alias = None
            if len(matches) == 1:
                actual_key = matches[0]
                observed = model["data"][actual_key]
                alias = "data." + actual_key
            else:
                arrays = [name for name in model["data"] if name.casefold() == stage.casefold()]
                values = model["data"][arrays[0]] if len(arrays) == 1 else None
                if not isinstance(values, list) or len(values) < job:
                    unknown.append({"rule": f"job_duration:{stage}{job}", "layer": "data",
                                    "detail": "missing or ambiguous duration mapping", "matches": matches})
                    continue
                actual_key = arrays[0]
                observed = values[job - 1]
                alias = {"index": {"value": {"path": "data." + actual_key}, "at": job - 1}}
            if observed != expected:
                violations.append({"rule": f"job_duration:{stage}{job}", "layer": "data",
                                   "expected": expected, "observed": observed})
            elif actual_key != key or isinstance(alias, dict):
                prepared["data"][key] = observed
                aliases["data." + key] = alias
    return prepared, aliases, violations, unknown


def structure_audit(model: dict, binding: dict) -> dict:
    if binding.get("strict"):
        return {"status": "UNKNOWN", "formulation": "unknown", "violations": [],
                "unknown": [{"rule": "strict_precedence",
                             "detail": "strict precedence is not representable in dvsa.model.v0.1"}]}
    model, aliases, violations, unknown = align_duration_data(model, binding)
    if unknown:
        return {"status": "UNKNOWN", "formulation": "unknown", "violations": [],
                "unknown": unknown, "data_aliases": aliases}
    if violations:
        return {"status": "VIOLATED", "formulation": "unknown", "violations": violations,
                "data_aliases": aliases}
    result = _structure_audit_aligned(model, binding)
    result["data_aliases"] = aliases
    return result


def _structure_audit_aligned(model: dict, binding: dict) -> dict:
    try:
        if model["objective"]["sense"] != binding["model_objective_sense"]:
            return {"status": "VIOLATED", "formulation": "unknown",
                    "violations": [{"rule": "job_objective_sense", "layer": "objective"}]}
        actual = {}
        for constraint in model["constraints"]:
            actual.setdefault(canonical(model, constraint), []).append(constraint["constraint_id"])
        missing = []
        for expected in completion_constraints(binding):
            key = canonical(model, expected)
            if key not in actual:
                missing.append({"rule": expected["constraint_id"], "layer": expected["layer"],
                                "expected_relation": expected["relation"]})
        if not missing:
            return {"status": "SATISFIED", "formulation": "completion", "violations": [],
                    "matched_constraints": len(completion_constraints(binding))}
        if binding["makespan"] != binding["cb"](len(binding["jobs"])):
            cut_missing = [expected["constraint_id"] for expected in cut_constraints(binding)
                           if canonical(model, expected) not in actual]
            if not cut_missing:
                return {"status": "SATISFIED", "formulation": "cut", "violations": [],
                        "matched_constraints": len(cut_constraints(binding)),
                        "equivalent_alternative_to_completion": True}
            return {"status": "VIOLATED", "formulation": "mixed_or_incomplete",
                    "violations": missing + [{"rule": name, "layer": "cut"} for name in cut_missing]}
        return {"status": "VIOLATED", "formulation": "completion", "violations": missing}
    except (InvalidSpec, UnknownValue, KeyError, TypeError, ValueError) as exc:
        return {"status": "UNKNOWN", "formulation": "unknown", "violations": [],
                "unknown": [{"rule": "structure", "detail": str(exc)}]}


def optimum(binding: dict) -> tuple[float, list[int]]:
    jobs = binding["jobs"]
    n = len(jobs)
    if n > 16:
        raise UnknownValue("independent subset-DP budget exceeded")
    a_sum = [0] * (1 << n)
    for mask in range(1, 1 << n):
        bit = mask & -mask
        a_sum[mask] = a_sum[mask ^ bit] + binding["durations"]["A"][bit.bit_length()]
    dp = [math.inf] * (1 << n)
    parent = [-1] * (1 << n)
    dp[0] = 0
    for mask in range(1, 1 << n):
        for job in jobs:
            bit = 1 << (job - 1)
            if mask & bit:
                previous = mask ^ bit
                candidate = max(dp[previous], a_sum[mask]) + binding["durations"]["B"][job]
                if candidate < dp[mask] - 1e-9:
                    dp[mask], parent[mask] = candidate, job
    permutation = []
    mask = (1 << n) - 1
    while mask:
        job = parent[mask]
        permutation.append(job)
        mask ^= 1 << (job - 1)
    return float(dp[-1]), list(reversed(permutation))


def schedule(binding: dict, permutation: list[int]) -> dict:
    if sorted(permutation) != binding["jobs"]:
        raise UnknownValue("assignment is not a permutation of jobs")
    ca, cb, previous_a, previous_b = {}, {}, 0.0, 0.0
    for position, job in enumerate(permutation, 1):
        previous_a += binding["durations"]["A"][job]
        previous_b = max(previous_b, previous_a) + binding["durations"]["B"][job]
        ca[position], cb[position] = previous_a, previous_b
    return {"permutation": permutation, "completion_a": ca, "completion_b": cb,
            "makespan": previous_b}


def make_solution(binding: dict, permutation: list[int], formulation="completion") -> dict:
    scheduled = schedule(binding, permutation)
    variables = {}
    for position in binding["positions"]:
        for job in binding["jobs"]:
            variables[binding["x"](position, job)] = float(scheduled["permutation"][position - 1] == job)
        if formulation == "completion":
            variables[binding["ca"](position)] = scheduled["completion_a"][position]
            variables[binding["cb"](position)] = scheduled["completion_b"][position]
        else:
            variables[binding["ca"](position)] = binding["durations"]["A"][scheduled["permutation"][position - 1]]
            variables[binding["cb"](position)] = binding["durations"]["B"][scheduled["permutation"][position - 1]]
    variables[binding["makespan"]] = scheduled["makespan"]
    return {"variables": variables, "objective": scheduled["makespan"]}


def solution_audit(model: dict, solution: dict, binding: dict, formulation: str) -> dict:
    if not isinstance(solution, dict) or not isinstance(solution.get("variables"), dict):
        return {"status": "UNKNOWN", "business_correct": False,
                "unknown": [{"rule": "solution", "detail": "variables object is missing"}]}
    variables = solution["variables"]
    required_assignments = {binding["x"](position, job) for position in binding["positions"]
                            for job in binding["jobs"]}
    if any(name not in variables for name in required_assignments):
        return {"status": "UNKNOWN", "business_correct": False,
                "unknown": [{"rule": "assignment_mapping", "detail": "missing assignment variable"}]}
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
           for value in variables.values()):
        return {"status": "UNKNOWN", "business_correct": False,
                "unknown": [{"rule": "solution", "detail": "non-finite or nonnumeric variable"}]}
    violations = []
    permutation = []
    for position in binding["positions"]:
        active = [job for job in binding["jobs"]
                  if variables.get(binding["x"](position, job), 0.0) > 1 - TOL]
        for job in binding["jobs"]:
            value = variables.get(binding["x"](position, job))
            if value is None or not (-TOL <= value <= 1 + TOL) or min(abs(value), abs(value - 1)) > TOL:
                violations.append({"rule": f"assignment_domain:p{position}:j{job}", "value": value})
        if len(active) != 1:
            violations.append({"rule": f"position_assignment:p{position}", "active": active})
        else:
            permutation.append(active[0])
    if sorted(permutation) != binding["jobs"]:
        violations.append({"rule": "job_permutation", "observed": permutation})
    if violations:
        return {"status": "VIOLATED", "business_correct": False, "violations": violations}
    scheduled = schedule(binding, permutation)
    observed_makespan = scheduled["makespan"]
    if formulation == "completion":
        previous_b = 0.0
        for position in binding["positions"]:
            ca_name, cb_name = binding["ca"](position), binding["cb"](position)
            ca_value, cb_value = variables.get(ca_name), variables.get(cb_name)
            if ca_value is None or cb_value is None:
                return {"status": "UNKNOWN", "business_correct": False,
                        "unknown": [{"rule": ca_name if ca_value is None else cb_name,
                                     "detail": "missing completion-time variable"}]}
            expected_a = scheduled["completion_a"][position]
            if abs(ca_value - expected_a) > TOL * max(1.0, abs(expected_a)):
                violations.append({"rule": f"job_ca:p{position}", "layer": "solution",
                                   "lhs": ca_value, "rhs": expected_a, "delta": ca_value - expected_a})
            job = permutation[position - 1]
            required_b = max(previous_b, expected_a) + binding["durations"]["B"][job]
            tolerance = TOL * max(1.0, abs(required_b))
            if cb_value < required_b - tolerance:
                violations.append({"rule": f"job_cb:p{position}", "layer": "solution",
                                   "lhs": cb_value, "rhs": required_b, "delta": cb_value - required_b})
            previous_b = cb_value
        observed_makespan = variables[binding["cb"](len(binding["jobs"]))]
    scheduled["observed_makespan"] = observed_makespan
    makespan_value = variables.get(binding["makespan"])
    if makespan_value is None:
        return {"status": "UNKNOWN", "business_correct": False,
                "unknown": [{"rule": "makespan", "detail": "missing objective variable"}]}
    if abs(makespan_value - observed_makespan) > TOL * max(1.0, observed_makespan):
        violations.append({"rule": "makespan_recompute", "lhs": makespan_value,
                           "rhs": observed_makespan})
    objective = solution.get("objective")
    if not isinstance(objective, (int, float)) or isinstance(objective, bool):
        return {"status": "UNKNOWN", "business_correct": False,
                "unknown": [{"rule": "objective", "detail": "missing or nonnumeric objective"}]}
    if abs(objective - observed_makespan) > TOL * max(1.0, observed_makespan):
        violations.append({"rule": "objective_recompute", "lhs": objective,
                           "rhs": observed_makespan})
    best, optimum_permutation = optimum(binding)
    optimal = abs(observed_makespan - best) <= TOL * max(1.0, abs(best))
    if not optimal:
        violations.append({"rule": "independent_optimality", "lhs": observed_makespan, "rhs": best})
    return {"status": "VIOLATED" if violations else "SATISFIED", "business_correct": not violations,
            "violations": violations, "schedule": scheduled, "independent_optimum": best,
            "independent_optimum_permutation": optimum_permutation,
            "objective_correct": abs(objective - best) <= 0.1 + TOL,
            "formulation": formulation}


def binding_variants(binding: dict) -> list[dict]:
    separator = "_" if binding["x"](1, 1).startswith("x_") else ""
    variants = []
    for semantics in ("job_position", "position_job"):
        candidate = dict(binding)
        if semantics == "job_position":
            candidate["x"] = lambda position, job: f"x{separator}{job}{separator}{position}"
        else:
            candidate["x"] = lambda position, job: f"x{separator}{position}{separator}{job}"
        candidate["index_semantics"] = semantics
        variants.append(candidate)
    return variants


def audit_candidate(model: dict, solution: dict, binding: dict) -> dict:
    failed, valid = [], []
    for variant in binding_variants(binding):
        structure = structure_audit(model, variant)
        if structure["status"] != "SATISFIED":
            failed.append({"index_semantics": variant["index_semantics"], "structure": structure})
            continue
        solution_result = solution_audit(model, solution, variant, structure["formulation"])
        valid.append({"status": solution_result["status"],
                      "business_correct": solution_result["business_correct"],
                      "index_semantics": variant["index_semantics"], "structure": structure,
                      "solution": solution_result, "violations": solution_result.get("violations", []),
                      "unknown": solution_result.get("unknown", [])})
    if len(valid) == 1:
        result = dict(valid[0])
        result["binding_trials"] = failed
        return result
    if valid and all(result["business_correct"] for result in valid):
        result = dict(valid[0])
        result["binding_trials"] = failed + valid[1:]
        result["equivalent_binding_count"] = len(valid)
        return result
    if valid:
        return {"status": "UNKNOWN", "business_correct": False,
                "structure": valid[0]["structure"], "binding_trials": failed + valid,
                "violations": [], "unknown": [{"rule": "index_semantics",
                                                "detail": "multiple structural bindings disagree"}]}
    structure = failed[0]["structure"]
    return {"status": structure["status"], "business_correct": False,
            "index_semantics": failed[0]["index_semantics"], "structure": structure,
            "binding_trials": failed[1:], "violations": structure.get("violations", []),
            "unknown": structure.get("unknown", [])}
