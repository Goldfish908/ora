"""Scalar LP/MILP reference models expressed with the DVSA expression grammar."""
from __future__ import annotations

import copy
import json
import math
import re

from ora_agent.dvsa import (Interpreter, InvalidSpec, UnknownValue,
                            RELATIONS)


MODEL_SCHEMA = "dvsa.model.v0.1"
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def normalize_model(model):
    if isinstance(model, dict) and "data" not in model:
        return {**model, "data": {}}, ["missing_data_default_empty"]
    return model, []


def normalize_candidate(candidate):
    if not isinstance(candidate, dict):
        raise InvalidSpec("candidate must be a JSON object")
    variables = candidate.get("variables")
    if isinstance(variables, dict):
        return candidate
    if not isinstance(variables, list):
        raise InvalidSpec("variables must be an object or declaration list")
    declarations = {}
    for spec in variables:
        if not isinstance(spec, dict) or set(spec) != {"name", "domain", "lb", "ub"}:
            raise InvalidSpec("variable list entries must contain exactly name/domain/lb/ub")
        name = spec["name"]
        if not isinstance(name, str) or not NAME.match(name) or name in {"data", "solution"}:
            raise InvalidSpec(f"invalid variable name: {name}")
        if name in declarations:
            raise InvalidSpec(f"duplicate variable name: {name}")
        declarations[name] = {key: spec[key] for key in ("domain", "lb", "ub")}
    return {**candidate, "variables": declarations}


def normalize_candidate_paths(model):
    normalized = copy.deepcopy(model)
    interpreter = Interpreter(model.get("data", {}), {})
    changes = []

    def data_path(raw):
        if not isinstance(raw, str) or not raw:
            raise InvalidSpec("candidate data path must be a nonempty string")
        if raw == "solution" or raw.startswith("solution."):
            raise InvalidSpec("candidate expressions may only read data paths")
        path = raw if raw.startswith("data.") else "data." + raw
        try:
            interpreter._path(path)
        except UnknownValue as exc:
            raise InvalidSpec(f"undefined data path: {path} ({exc})") from exc
        if path != raw:
            changes.append({"kind": "data_path_prefix", "from": raw, "to": path})
        return path

    def visit(value):
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value
        if set(value) == {"lookup"} and isinstance(value["lookup"], dict):
            lookup = value["lookup"]
            if set(lookup) == {"path", "index"} and isinstance(lookup["path"], str):
                path = data_path(lookup["path"])
                table = interpreter._path(path)
                index = lookup["index"]
                if isinstance(table, list) and isinstance(index, int) and not isinstance(index, bool):
                    if not 0 <= index < len(table):
                        raise InvalidSpec("lookup list index is out of range")
                    changes.append({"kind": "lookup_list_index", "path": path, "index": index})
                    return {"index": {"value": {"path": path}, "at": index}}
        return {key: data_path(arg) if key == "path" else visit(arg)
                for key, arg in value.items()}

    normalized["objective"]["expression"] = visit(model["objective"]["expression"])
    for position, constraint in enumerate(model["constraints"]):
        for field in ("lhs", "rhs", "local", "forall"):
            normalized["constraints"][position][field] = visit(constraint.get(field, {}))
    return normalized, changes


def validate_candidate_paths(model):
    interpreter = Interpreter(model.get("data", {}), {})

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        if set(value) == {"lookup"}:
            lookup = value["lookup"]
            if (not isinstance(lookup, dict) or "path" not in lookup or "key" not in lookup
                    or not set(lookup) <= {"path", "key", "default"}
                    or not isinstance(lookup["key"], list)):
                raise InvalidSpec("lookup requires path/key and optional default only")
        if set(value) == {"index"}:
            index = value["index"]
            if not isinstance(index, dict) or set(index) != {"value", "at"}:
                raise InvalidSpec("index requires value and at")
        for key, arg in value.items():
            if key == "path":
                if not isinstance(arg, str) or arg == "data" or not arg.startswith("data."):
                    raise InvalidSpec(f"candidate data path must use the data namespace: {arg}")
                try:
                    interpreter._path(arg)
                except UnknownValue as exc:
                    raise InvalidSpec(f"undefined data path: {arg} ({exc})") from exc
            else:
                visit(arg)

    visit(model["objective"]["expression"])
    for constraint in model["constraints"]:
        visit(constraint["lhs"])
        visit(constraint["rhs"])
        visit(constraint.get("local", {}))
        visit(constraint.get("forall", {}))
    return model


def validate_model(model):
    model, _ = normalize_model(model)
    if not isinstance(model, dict) or model.get("schema_version") != MODEL_SCHEMA:
        raise InvalidSpec(f"schema_version must be {MODEL_SCHEMA}")
    if not isinstance(model.get("problem_id"), str) or not model["problem_id"]:
        raise InvalidSpec("problem_id is required")
    variables = model.get("variables")
    if not isinstance(variables, dict) or not variables or len(variables) > 500:
        raise InvalidSpec("variables must contain 1..500 scalar declarations")
    for name, spec in variables.items():
        if not isinstance(name, str) or not NAME.match(name) or name in {"data", "solution"}:
            raise InvalidSpec(f"invalid variable name: {name}")
        if not isinstance(spec, dict) or spec.get("domain", "real") not in {"real", "integer", "binary"}:
            raise InvalidSpec(f"invalid variable domain: {name}")
        if "lb" not in spec:
            raise InvalidSpec(f"explicit lb is required: {name}")
        for key in ("lb", "ub"):
            value = spec.get(key)
            if value is not None and (isinstance(value, bool)
                                      or not isinstance(value, (int, float))
                                      or not math.isfinite(value)):
                raise InvalidSpec(f"invalid {key}: {name}")
        if spec.get("ub") is not None and spec["ub"] < spec["lb"]:
            raise InvalidSpec(f"ub < lb: {name}")
    if not isinstance(model.get("data"), dict):
        raise InvalidSpec("data must be an object")
    encoded = json.dumps(model["data"], allow_nan=False)
    if len(encoded) > 200000:
        raise InvalidSpec("data exceeds size budget")
    constraints = model.get("constraints")
    if not isinstance(constraints, list) or not constraints or len(constraints) > 2000:
        raise InvalidSpec("constraints must contain 1..2000 entries")
    for position, constraint in enumerate(constraints, 1):
        if not isinstance(constraint, dict):
            raise InvalidSpec("constraint must be an object")
        if not isinstance(constraint.get("constraint_id"), str):
            raise InvalidSpec(f"constraint {position} requires an ID")
        if constraint.get("relation") not in {"eq", "le", "ge"}:
            raise InvalidSpec("solver constraints must use eq/le/ge")
        if not isinstance(constraint.get("source"), str) or not constraint["source"].strip():
            raise InvalidSpec("constraint source is required")
        if "lhs" not in constraint or "rhs" not in constraint:
            raise InvalidSpec("constraint requires lhs/rhs")
    objective = model.get("objective")
    if not isinstance(objective, dict) or objective.get("sense") not in {"minimize", "maximize"}:
        raise InvalidSpec("objective sense must be minimize/maximize")
    if "expression" not in objective:
        raise InvalidSpec("objective expression is required")
    return model


def extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("no complete JSON object in model response")


def verify_sources(model, question):
    model, _ = normalize_model(model)
    validate_model(model)
    normalize = lambda value: " ".join(value.split()).casefold()
    normalized_question = normalize(question)
    missing = []
    for constraint in model["constraints"]:
        source = constraint["source"].strip()
        if len(source) < 8 or normalize(source) not in normalized_question:
            missing.append({"constraint_id": constraint["constraint_id"], "source": source})
    return missing


class LinearCompiler:
    def __init__(self, variables, data):
        self.variables = variables
        self.interpreter = Interpreter(data, {}, max_seconds=20.0,
                                       max_nodes=500000, max_cases=100000)

    def _has_decision(self, expr):
        if isinstance(expr, list):
            return any(self._has_decision(item) for item in expr)
        if not isinstance(expr, dict):
            return False
        op, arg = next(iter(expr.items()))
        if op == "var":
            return arg in self.variables
        return self._has_decision(arg)

    def _constant(self, expr, env):
        value = self.interpreter._eval(expr, env)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidSpec("expected a numeric constant")
        return value

    def build(self, expr, env=None):
        env = env or {}
        if not self._has_decision(expr):
            return self._constant(expr, env)
        if not isinstance(expr, dict) or len(expr) != 1:
            raise InvalidSpec("invalid linear expression")
        op, arg = next(iter(expr.items()))
        if op == "var":
            return self.variables[arg]
        if op == "add":
            if not isinstance(arg, list):
                raise InvalidSpec("add requires a list")
            return sum(self.build(item, env) for item in arg)
        if op == "mul":
            if not isinstance(arg, list):
                raise InvalidSpec("mul requires a list")
            varying = [item for item in arg if self._has_decision(item)]
            if len(varying) > 1:
                raise InvalidSpec("nonlinear product of decision expressions")
            if not varying:
                return self._constant(expr, env)
            constant = 1.0
            for item in arg:
                if item not in varying:
                    constant *= self._constant(item, env)
            return constant * self.build(varying[0], env)
        if op == "sub" and isinstance(arg, list) and len(arg) == 2:
            return self.build(arg[0], env) - self.build(arg[1], env)
        if op == "div" and isinstance(arg, list) and len(arg) == 2:
            if self._has_decision(arg[1]):
                raise InvalidSpec("division by a decision expression")
            divisor = self._constant(arg[1], env)
            if divisor == 0:
                raise InvalidSpec("division by zero")
            return self.build(arg[0], env) / divisor
        if op == "neg":
            return -self.build(arg, env)
        if op == "sum":
            if isinstance(arg, list):
                return sum(self.build(item, env) for item in arg)
            if not isinstance(arg, dict) or "forall" not in arg or "value" not in arg:
                raise InvalidSpec("sum requires a list or forall/value")
            total = 0.0
            for local in self.interpreter._cases(arg["forall"], env):
                if "where" in arg and not self.interpreter._truth(
                        self.interpreter._eval(arg["where"], local)):
                    continue
                total += self.build(arg["value"], local)
            return total
        raise InvalidSpec(f"unsupported linear decision operator: {op}")


def solve_model(model, time_limit=60.0):
    model, _ = normalize_model(model)
    validate_model(model)
    from pyscipopt import Model

    solver = Model()
    solver.hideOutput()
    solver.setRealParam("limits/time", float(time_limit))
    variables = {}
    for name, spec in model["variables"].items():
        domain = spec.get("domain", "real")
        vtype = {"real": "C", "integer": "I", "binary": "B"}[domain]
        lb, ub = spec["lb"], spec.get("ub")
        if domain == "binary":
            lb, ub = max(0, lb), min(1, 1 if ub is None else ub)
        variables[name] = solver.addVar(name=name, vtype=vtype, lb=lb, ub=ub)
    compiler = LinearCompiler(variables, model["data"])
    try:
        for constraint in model["constraints"]:
            cases = compiler.interpreter._cases(constraint.get("forall", {}), {})
            for env in cases:
                env = dict(env)
                for name, expr in constraint.get("local", {}).items():
                    env[name] = compiler._constant(expr, env)
                lhs = compiler.build(constraint["lhs"], env)
                rhs = compiler.build(constraint["rhs"], env)
                relation = constraint["relation"]
                if relation == "eq":
                    solver.addCons(lhs == rhs)
                elif relation == "le":
                    solver.addCons(lhs <= rhs)
                else:
                    solver.addCons(lhs >= rhs)
        objective = compiler.build(model["objective"]["expression"])
        solver.setObjective(objective, sense=model["objective"]["sense"])
        solver.optimize()
        status = solver.getStatus()
        result = {"status": status, "solver_calls": 1}
        if status != "optimal":
            return result
        values = {name: float(solver.getVal(var)) for name, var in variables.items()}
        solution = {"variables": values, "objective": float(solver.getObjVal())}
        result["solution"] = solution
        result["audit"] = audit_solution(model, solution)
        return result
    except (InvalidSpec, UnknownValue, TypeError, ValueError) as exc:
        return {"status": "invalid_model", "error": str(exc), "solver_calls": 0}


def audit_solution(model, solution, abs_tol=1e-5, rel_tol=1e-6):
    model, _ = normalize_model(model)
    validate_model(model)
    if not isinstance(solution, dict) or not isinstance(solution.get("variables"), dict):
        return {"verdict": "UNKNOWN", "violations": [], "unknown": ["variables object is missing"]}
    values = solution["variables"]
    violations, unknown = [], []
    env = {}
    for name, spec in model["variables"].items():
        value = values.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            unknown.append({"rule": "VARIABLE", "variable": name, "detail": "missing/nonfinite value"})
            continue
        env[name] = float(value)
        if value < spec["lb"] - abs_tol - rel_tol * abs(spec["lb"]):
            violations.append({"rule": "LOWER_BOUND", "variable": name, "value": value, "bound": spec["lb"]})
        if spec.get("ub") is not None and value > spec["ub"] + abs_tol + rel_tol * abs(spec["ub"]):
            violations.append({"rule": "UPPER_BOUND", "variable": name, "value": value, "bound": spec["ub"]})
        if spec.get("domain") in {"integer", "binary"} and abs(value - round(value)) > abs_tol:
            violations.append({"rule": "INTEGRALITY", "variable": name, "value": value})
        if spec.get("domain") == "binary" and abs(value) > abs_tol and abs(value - 1) > abs_tol:
            violations.append({"rule": "BINARY", "variable": name, "value": value})
    interpreter = Interpreter(model["data"], solution, max_seconds=20.0,
                              max_nodes=500000, max_cases=100000)
    if len(env) == len(model["variables"]):
        for constraint in model["constraints"]:
            try:
                for local in interpreter._cases(constraint.get("forall", {}), env):
                    for name, expr in constraint.get("local", {}).items():
                        local[name] = interpreter._eval(expr, local)
                    result = interpreter.evaluate_relation(
                        constraint["relation"], interpreter._eval(constraint["lhs"], local),
                        interpreter._eval(constraint["rhs"], local),
                        {"abs": abs_tol, "rel": rel_tol})
                    if result["status"] == "VIOLATED":
                        violations.append({"rule": constraint["constraint_id"],
                                           "source": constraint["source"], **result})
            except UnknownValue as exc:
                unknown.append({"rule": constraint["constraint_id"], "detail": str(exc)})
        try:
            recomputed = interpreter._eval(model["objective"]["expression"], env)
            reported = solution.get("objective")
            if isinstance(reported, bool) or not isinstance(reported, (int, float)) or not math.isfinite(reported):
                unknown.append({"rule": "OBJECTIVE", "detail": "missing/nonfinite objective"})
            else:
                result = interpreter.evaluate_relation("eq", reported, recomputed,
                                                       {"abs": abs_tol, "rel": rel_tol})
                if result["status"] == "VIOLATED":
                    violations.append({"rule": "OBJECTIVE", **result})
        except UnknownValue as exc:
            unknown.append({"rule": "OBJECTIVE", "detail": str(exc)})
    verdict = "INVALID" if violations else "UNKNOWN" if unknown else "VALID"
    return {"verdict": verdict, "violations": violations[:100], "unknown": unknown[:100]}
