"""Mechanical conversion of scalar reference ASTs into linear template bindings."""
from __future__ import annotations

import math

from ora_agent.dvsa import Interpreter, InvalidSpec, UnknownValue


def linearize(expr, model, env=None, interpreter=None):
    env = env or {}
    interpreter = interpreter or Interpreter(model["data"], {})

    def constant(node):
        value = interpreter._eval(node, env)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise UnknownValue("expected a finite numeric constant")
        return float(value)

    def combine(parts, signs=None):
        coefficients, constant_value = {}, 0.0
        signs = signs or [1.0] * len(parts)
        for part, sign in zip(parts, signs):
            terms, offset = linearize(part, model, env, interpreter)
            constant_value += sign * offset
            for name, coefficient in terms.items():
                coefficients[name] = coefficients.get(name, 0.0) + sign * coefficient
        return coefficients, constant_value

    if isinstance(expr, (int, float)) and not isinstance(expr, bool):
        return {}, constant(expr)
    if not isinstance(expr, dict) or len(expr) != 1:
        raise InvalidSpec("linear expression must be a number or single-operator object")
    op, arg = next(iter(expr.items()))
    if op == "var":
        if arg in env:
            return {}, constant(expr)
        if arg not in model["variables"]:
            raise UnknownValue(f"undeclared decision variable: {arg}")
        return {arg: 1.0}, 0.0
    if op in {"path", "index", "lookup"}:
        return {}, constant(expr)
    if op == "add":
        if not isinstance(arg, list):
            raise InvalidSpec("add requires a list")
        return combine(arg)
    if op == "sub":
        if not isinstance(arg, list) or len(arg) != 2:
            raise InvalidSpec("sub requires two operands")
        return combine(arg, [1.0, -1.0])
    if op == "neg":
        terms, offset = linearize(arg, model, env, interpreter)
        return {name: -value for name, value in terms.items()}, -offset
    if op == "mul":
        if not isinstance(arg, list):
            raise InvalidSpec("mul requires a list")
        forms = [linearize(item, model, env, interpreter) for item in arg]
        varying = [form for form in forms if form[0]]
        if len(varying) > 1:
            raise InvalidSpec("nonlinear product")
        multiplier = 1.0
        for terms, offset in forms:
            if not terms:
                multiplier *= offset
        if not varying:
            return {}, multiplier
        terms, offset = varying[0]
        return ({name: multiplier * value for name, value in terms.items()},
                multiplier * offset)
    if op == "div":
        if not isinstance(arg, list) or len(arg) != 2:
            raise InvalidSpec("div requires two operands")
        numerator, denominator = linearize(arg[0], model, env, interpreter)[0], constant(arg[1])
        if denominator == 0:
            raise UnknownValue("division by zero")
        return {name: value / denominator for name, value in numerator[0].items()}, numerator[1] / denominator
    if op in {"abs", "round"}:
        terms, offset = linearize(arg, model, env, interpreter)
        if terms:
            raise InvalidSpec(f"{op} is not linear over decision variables")
        return {}, constant(expr)
    if op == "sum":
        if isinstance(arg, list):
            return combine(arg)
        if not isinstance(arg, dict) or "forall" not in arg or "value" not in arg:
            raise InvalidSpec("sum requires a list or forall/value")
        coefficients, constant_value = {}, 0.0
        for local in interpreter._cases(arg["forall"], env):
            if "where" in arg and not interpreter._truth(interpreter._eval(arg["where"], local)):
                continue
            terms, offset = linearize(arg["value"], model, local, interpreter)
            constant_value += offset
            for name, coefficient in terms.items():
                coefficients[name] = coefficients.get(name, 0.0) + coefficient
        return coefficients, constant_value
    raise InvalidSpec(f"unsupported linear operator: {op}")


def _terms(coefficients):
    return [{"variable": name, "coefficient": value}
            for name, value in sorted(coefficients.items()) if value != 0]


def _constraint_binding(model, constraint, env, interpreter):
    lhs, lhs_const = linearize(constraint["lhs"], model, env, interpreter)
    rhs, rhs_const = linearize(constraint["rhs"], model, env, interpreter)
    coefficients = dict(lhs)
    for name, value in rhs.items():
        coefficients[name] = coefficients.get(name, 0.0) - value
    bound = rhs_const - lhs_const
    relation = constraint["relation"]
    if relation in {"le", "ge"}:
        data = ({"terms": _terms(coefficients), "limit": bound} if relation == "le"
                else {"terms": _terms(coefficients), "bound": bound})
        template_id = "bwor.resource_capacity" if relation == "le" else "bwor.linear_lower_bound"
    else:
        positive = {name: value for name, value in coefficients.items() if value > 0}
        negative = {name: -value for name, value in coefficients.items() if value < 0}
        data = {"positive_terms": _terms(positive), "negative_terms": _terms(negative),
                "rhs": bound}
        template_id = "bwor.linear_balance"
    suffix = ":".join(f"{name}={env[name]}" for name in constraint.get("forall", {}))
    binding_id = constraint["constraint_id"] + (f":{suffix}" if suffix else "")
    return {"binding_id": binding_id, "template_id": template_id,
            "source": constraint["source"], "data": data}


def reference_bindings(model):
    interpreter = Interpreter(model["data"], {})
    bindings, skipped = [], []
    for constraint in model["constraints"]:
        try:
            for env in interpreter._cases(constraint.get("forall", {}), {}):
                env = dict(env)
                for name, expr in constraint.get("local", {}).items():
                    env[name] = interpreter._eval(expr, env)
                bindings.append(_constraint_binding(model, constraint, env, interpreter))
        except (InvalidSpec, UnknownValue) as exc:
            skipped.append({"constraint_id": constraint.get("constraint_id"), "reason": str(exc)})
    objective = model["objective"]
    if objective.get("source"):
        try:
            coefficients, constant = linearize(objective["expression"], model, {}, interpreter)
            bindings.append({"binding_id": "OBJECTIVE", "template_id": "bwor.objective_recompute",
                             "source": objective["source"],
                             "data": {"terms": _terms(coefficients), "constant": constant}})
        except (InvalidSpec, UnknownValue) as exc:
            skipped.append({"constraint_id": "OBJECTIVE", "reason": str(exc)})
    else:
        skipped.append({"constraint_id": "OBJECTIVE", "reason": "objective source span not provided"})
    return {"problem_id": model["problem_id"],
            "origin": "reference_derived_sanity_not_asset_learning",
            "bindings": bindings, "skipped": skipped}
