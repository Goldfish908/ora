"""Declarative, bounded evaluation of domain-validated semantic assets."""
from __future__ import annotations

import hashlib
import json
import math
import time


SCHEMA_VERSION = "dvsa.expr.v0.1"
RELATIONS = {"eq", "le", "ge", "lt", "gt"}


class InvalidSpec(ValueError):
    pass


class UnknownValue(ValueError):
    pass


def _mapping(value, label):
    if not isinstance(value, dict):
        raise InvalidSpec(f"{label} must be an object")
    return value


def validate_asset(asset):
    asset = _mapping(asset, "asset")
    required = ("asset_id", "schema_version", "asset_version", "source")
    missing = [key for key in required if key not in asset]
    if missing:
        raise InvalidSpec(f"missing asset fields: {missing}")
    if asset["schema_version"] != SCHEMA_VERSION:
        raise InvalidSpec(f"unsupported schema_version: {asset['schema_version']}")
    if not all(isinstance(asset[key], str) and asset[key]
               for key in ("asset_id", "asset_version")):
        raise InvalidSpec("asset_id and asset_version must be nonempty strings")
    _mapping(asset["source"], "source")
    if not asset["source"].get("reference"):
        raise InvalidSpec("source.reference is required")
    invariants = asset.get("invariants")
    if invariants is None:
        invariants = [asset]
    if not isinstance(invariants, list) or not invariants:
        raise InvalidSpec("asset must contain at least one invariant")
    for invariant in invariants:
        _mapping(invariant, "invariant")
        if invariant.get("relation") not in RELATIONS:
            raise InvalidSpec("invariant has an unsupported relation")
        if "lhs" not in invariant or "rhs" not in invariant:
            raise InvalidSpec("invariant requires lhs and rhs")
        if "forall" in invariant:
            _mapping(invariant["forall"], "forall")
    return asset


def asset_sha256(asset):
    validate_asset(asset)
    canonical = {k: v for k, v in asset.items() if k != "implementation_sha256"}
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def render_text(asset):
    validate_asset(asset)
    text = asset.get("text")
    if not isinstance(text, str) or not text.strip():
        raise InvalidSpec("text-memory rendering requires nonempty asset.text")
    return text.strip()


class Interpreter:
    def __init__(self, data, solution, max_seconds=10.0,
                 max_nodes=200000, max_cases=100000):
        self.root = {"data": data, "solution": solution}
        self.deadline = time.monotonic() + max_seconds
        self.max_nodes = max_nodes
        self.max_cases = max_cases
        self.nodes = 0
        self.cases = 0

    def _tick(self):
        self.nodes += 1
        if self.nodes > self.max_nodes:
            raise UnknownValue("expression node budget exceeded")
        if self.nodes % 128 == 0 and time.monotonic() > self.deadline:
            raise UnknownValue("expression time budget exceeded")

    def _number(self, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise UnknownValue(f"expected a number, got {type(value).__name__}")
        value = float(value)
        if not math.isfinite(value):
            raise UnknownValue("non-finite numeric value")
        return value

    def _path(self, path):
        if not isinstance(path, str) or not path:
            raise InvalidSpec("path must be a nonempty string")
        value = self.root
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                raise UnknownValue(f"missing path: {path}")
            value = value[part]
        if value is None:
            raise UnknownValue(f"null path: {path}")
        return value

    def _truth(self, value):
        if not isinstance(value, bool):
            raise InvalidSpec("predicate did not evaluate to boolean")
        return value

    def _compare(self, op, left, right):
        left, right = self._number(left), self._number(right)
        return {"eq": left == right, "ne": left != right,
                "lt": left < right, "le": left <= right,
                "gt": left > right, "ge": left >= right}[op]

    def _iterator(self, spec, env):
        spec = _mapping(spec, "iterator")
        if "range" in spec:
            bounds = spec["range"]
            if not isinstance(bounds, list) or len(bounds) not in (2, 3):
                raise InvalidSpec("range requires [start, stop] or [start, stop, step]")
            values = [self._eval(item, env) for item in bounds]
            if any(value != int(value) for value in values):
                raise UnknownValue("range bounds must be integers")
            start, stop = int(values[0]), int(values[1])
            step = int(values[2]) if len(values) == 3 else 1
            if step == 0 or abs(stop - start) > self.max_cases:
                raise UnknownValue("invalid or excessive range")
            return range(start, stop, step)
        if "path" not in spec or len(spec) != 1:
            raise InvalidSpec("iterator requires exactly range or path")
        values = self._path(spec["path"])
        if not isinstance(values, list):
            raise UnknownValue(f"iterator is not a list: {spec['path']}")
        if len(values) > self.max_cases:
            raise UnknownValue("iterator exceeds case budget")
        return values

    def _cases(self, iterators, env):
        iterators = _mapping(iterators, "forall")
        items = list(iterators.items())

        def visit(position, current):
            if position == len(items):
                self.cases += 1
                if self.cases > self.max_cases:
                    raise UnknownValue("forall case budget exceeded")
                yield current
                return
            name, spec = items[position]
            if not isinstance(name, str) or not name or name in {"data", "solution"}:
                raise InvalidSpec("invalid iterator variable")
            for value in self._iterator(spec, current):
                nested = dict(current)
                nested[name] = value
                yield from visit(position + 1, nested)

        yield from visit(0, env)

    def _sum(self, spec, env):
        if isinstance(spec, list):
            return sum(self._number(self._eval(item, env)) for item in spec)
        spec = _mapping(spec, "sum")
        if "forall" not in spec or "value" not in spec:
            raise InvalidSpec("sum requires a list or forall/value")
        total = 0.0
        for local in self._cases(spec["forall"], env):
            if "where" in spec and not self._truth(self._eval(spec["where"], local)):
                continue
            total += self._number(self._eval(spec["value"], local))
        return total

    def _eval(self, expr, env):
        self._tick()
        if isinstance(expr, bool) or expr is None:
            raise UnknownValue("boolean/null is not a numeric expression")
        if isinstance(expr, int):
            return expr
        if isinstance(expr, float):
            return self._number(expr)
        if isinstance(expr, str):
            return expr
        if not isinstance(expr, dict) or len(expr) != 1:
            raise InvalidSpec("expression must be a number or single-operator object")
        op, arg = next(iter(expr.items()))
        if op == "var":
            if not isinstance(arg, str) or arg not in env:
                raise UnknownValue(f"unbound variable: {arg}")
            return env[arg]
        if op == "path":
            return self._path(arg)
        if op in {"add", "mul", "and", "or"}:
            if not isinstance(arg, list):
                raise InvalidSpec(f"{op} requires a list")
            if op in {"and", "or"}:
                values = (self._truth(self._eval(item, env)) for item in arg)
                return all(values) if op == "and" else any(values)
            values = [self._number(self._eval(item, env)) for item in arg]
            if op == "add":
                return sum(values)
            result = 1.0
            for value in values:
                result *= value
            return result
        if op in {"max", "min"}:
            if not isinstance(arg, list) or not arg:
                raise InvalidSpec(f"{op} requires a nonempty list")
            values = [self._number(self._eval(item, env)) for item in arg]
            return max(values) if op == "max" else min(values)
        if op in {"sub", "div", "eq", "ne", "lt", "le", "gt", "ge"}:
            if not isinstance(arg, list) or len(arg) != 2:
                raise InvalidSpec(f"{op} requires two operands")
            left, right = (self._eval(item, env) for item in arg)
            if op == "sub":
                return self._number(left) - self._number(right)
            if op == "div":
                left, right = self._number(left), self._number(right)
                if right == 0:
                    raise UnknownValue("division by zero")
                return left / right
            if op in {"eq", "ne"} and isinstance(left, str) and isinstance(right, str):
                return left == right if op == "eq" else left != right
            return self._compare(op, left, right)
        if op in {"neg", "not", "abs", "round"}:
            value = self._eval(arg, env)
            if op == "not":
                return not self._truth(value)
            if op == "neg":
                return -self._number(value)
            if op == "abs":
                return abs(self._number(value))
            return round(self._number(value))
        if op == "sum":
            return self._sum(arg, env)
        if op == "index":
            arg = _mapping(arg, "index")
            if set(arg) != {"value", "at"}:
                raise InvalidSpec("index requires value and at")
            value = self._eval(arg["value"], env)
            index = self._eval(arg["at"], env)
            if isinstance(value, list):
                if (isinstance(index, bool) or not isinstance(index, (int, float))
                        or not math.isfinite(index) or int(index) != index):
                    raise UnknownValue("list index is not an integer")
                index = int(index)
                if not 0 <= index < len(value):
                    raise UnknownValue("list index is out of range")
                return value[index]
            if isinstance(value, dict) and isinstance(index, str) and index in value:
                return value[index]
            raise UnknownValue("invalid index or missing map key")
        if op == "lookup":
            arg = _mapping(arg, "lookup")
            if "path" not in arg or "key" not in arg or not set(arg) <= {"path", "key", "default"}:
                raise InvalidSpec("lookup requires path/key and optional default only")
            table = self._path(arg["path"])
            if not isinstance(table, dict):
                raise UnknownValue("lookup table is not an object")
            keys = arg["key"]
            if not isinstance(keys, list):
                raise InvalidSpec("lookup key must be a list")
            key = "|".join(str(self._eval(item, env)) for item in keys)
            if key in table:
                return table[key]
            if "default" in arg:
                return arg["default"]
            raise UnknownValue(f"missing lookup key: {key}")
        raise InvalidSpec(f"unsupported expression operator: {op}")

    def evaluate_relation(self, relation, lhs, rhs, tolerance):
        left, right = self._number(lhs), self._number(rhs)
        tolerance = _mapping(tolerance or {}, "tolerance")
        abs_tol = self._number(tolerance.get("abs", 0.0))
        rel_tol = self._number(tolerance.get("rel", 0.0))
        if abs_tol < 0 or rel_tol < 0:
            raise InvalidSpec("tolerances must be nonnegative")
        delta = left - right
        allowed = abs_tol + rel_tol * max(abs(left), abs(right), 1.0)
        if relation == "eq":
            passed = abs(delta) <= allowed
        elif relation == "le":
            passed = delta <= allowed
        elif relation == "ge":
            passed = delta >= -allowed
        elif relation == "lt":
            passed = delta < allowed
        else:
            passed = delta > -allowed
        return {"status": "SATISFIED" if passed else "VIOLATED",
                "lhs": left, "rhs": right, "delta": delta,
                "tolerance": allowed}


def run_asset(asset, data, solution, domain=None, max_seconds=10.0):
    validate_asset(asset)
    interpreter = Interpreter(data, solution, max_seconds=max_seconds)
    scope = asset.get("scope", {})
    if not isinstance(scope, dict):
        raise InvalidSpec("scope must be an object")
    if scope.get("domain") is not None and scope["domain"] != domain:
        return {"asset_id": asset["asset_id"], "asset_version": asset["asset_version"],
                "implementation_sha256": asset_sha256(asset),
                "status": "NOT_APPLICABLE", "violations": [], "unknown": [],
                "evaluated": 0, "not_applicable": 1}
    try:
        applicable = ("applicability" not in scope or interpreter._truth(
            interpreter._eval(scope["applicability"], {})))
    except UnknownValue as exc:
        return {"asset_id": asset["asset_id"], "asset_version": asset["asset_version"],
                "implementation_sha256": asset_sha256(asset),
                "status": "UNKNOWN", "violations": [],
                "unknown": [{"rule": "scope", "detail": str(exc)}],
                "evaluated": 0, "not_applicable": 0}
    if not applicable:
        return {"asset_id": asset["asset_id"], "asset_version": asset["asset_version"],
                "implementation_sha256": asset_sha256(asset),
                "status": "NOT_APPLICABLE", "violations": [], "unknown": [],
                "evaluated": 0, "not_applicable": 1}
    try:
        for key, prefix in (("required_data", "data"), ("required_solution", "solution")):
            paths = scope.get(key, [])
            if not isinstance(paths, list):
                raise InvalidSpec(f"scope.{key} must be a list")
            for path in paths:
                interpreter._path(f"{prefix}.{path}")
        env = {name: interpreter._eval(expr, {})
               for name, expr in asset.get("bindings", {}).items()}
    except UnknownValue as exc:
        return {"asset_id": asset["asset_id"], "asset_version": asset["asset_version"],
                "implementation_sha256": asset_sha256(asset),
                "status": "UNKNOWN", "violations": [],
                "unknown": [{"rule": "scope", "detail": str(exc)}],
                "evaluated": 0, "not_applicable": 0}
    violations, unknown = [], []
    evaluated = 0
    invariants = asset.get("invariants", [asset])
    for position, invariant in enumerate(invariants, 1):
        rule = invariant.get("invariant_id", f"I{position:02d}")
        try:
            for local in interpreter._cases(invariant.get("forall", {}), env):
                local_env = dict(local)
                for name, expr in invariant.get("local", {}).items():
                    local_env[name] = interpreter._eval(expr, local_env)
                if "where" in invariant and not interpreter._truth(
                        interpreter._eval(invariant["where"], local_env)):
                    continue
                if invariant.get("strict") and invariant["relation"] not in {"lt", "gt"}:
                    raise InvalidSpec("strict comparison requires lt or gt")
                tolerance = ({"abs": 0.0, "rel": 0.0} if invariant.get("strict")
                             else invariant.get("tolerance", asset.get("tolerance", {})))
                result = interpreter.evaluate_relation(
                    invariant["relation"],
                    interpreter._eval(invariant["lhs"], local_env),
                    interpreter._eval(invariant["rhs"], local_env), tolerance)
                evaluated += 1
                if result["status"] == "VIOLATED":
                    item = {"rule": rule, "source": asset["source"]["reference"], **result}
                    item["bindings"] = {k: local_env[k] for k in invariant.get("forall", {})}
                    violations.append(item)
        except UnknownValue as exc:
            unknown.append({"rule": rule, "detail": str(exc)})
    if violations:
        status = "VIOLATED"
    elif unknown:
        status = "UNKNOWN"
    else:
        status = "SATISFIED"
    return {"asset_id": asset["asset_id"], "asset_version": asset["asset_version"],
            "implementation_sha256": asset_sha256(asset), "status": status,
            "violations": violations[:50], "violation_count": len(violations),
            "unknown": unknown[:50], "unknown_count": len(unknown),
            "evaluated": evaluated, "complete": not unknown, "not_applicable": 0}
