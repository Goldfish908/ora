"""D2 rule templates: human-written check skeletons with LLM-filled slots.

D1 showed free-form LLM-drafted rules are net-negative (code-grep rules) or
hallucinate numeric bounds. D2 constrains generation (see
docs/paper/d2_spec_evolution_v0.1.md section 2): the LLM never writes code,
it only picks a template, fills slots (numbers or arithmetic over extracted
params), cites verbatim text evidence, and supplies must-fire / must-pass
cases. Every skeleton is CONSERVATIVE: any exception or ambiguity returns
None (no alarm).

Slot expressions are evaluated at render time (safe_eval over the authoring
params) and baked into the rendered code as constants, so sandboxed rules
contain no eval and no params lookups for their thresholds.

Templates (mechanism -> slots):
  objective_range    printed objective outside physical bounds   lower, upper
  phantom_resource   fabricated resource (e.g. initial stock)    keywords, granted
  sense_direction    wrong optimization direction                expected
  constant_fidelity  key text constant absent from code          name, expected
  conditional_moq    q=0 or q>=m relation not modeled            m, require_binary

run_fixtures() renders and executes every template's built-in
must-fire/must-pass fixture in-process; tests/test_spec_templates.py asserts
it passes and scripts/d2_author.py runs it as a startup sanity gate.
"""

from __future__ import annotations

import ast
import json


class TemplateError(ValueError):
    """Invalid template name, slot value, or slot expression."""


# ------------------------------------------------------------------ safe_eval

_ALLOWED_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
}
_ALLOWED_UNARY = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a}
_ALLOWED_FUNCS = {"min": min, "max": max, "abs": abs, "sum": sum, "round": round}
_MAX_ABS = 1e15


def safe_eval(expr, params):
    """Evaluate an arithmetic slot expression over authoring ``params``.

    Whitelist: numbers, param names (or ``params['name']``), nested list
    indexing, ``+ - * / %``, parentheses, and min/max/abs/sum/round.
    Everything else raises TemplateError. The result must be a finite
    number with abs(value) < 1e15 (guards against runaway arithmetic).
    """
    if not isinstance(expr, str) or not expr.strip():
        raise TemplateError(
            f"slot expression must be a non-empty string, got {expr!r}")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise TemplateError(f"unparseable slot expression {expr!r}: {e}") from e
    value = _eval_node(tree.body, params or {})
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TemplateError(f"slot expression {expr!r} did not produce a number")
    value = float(value)
    if value != value or abs(value) >= _MAX_ABS:
        raise TemplateError(f"slot expression {expr!r} out of range: {value!r}")
    return value


def _eval_node(node, params):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            raise TemplateError("booleans are not valid slot values")
        if isinstance(node.value, (int, float, str)):
            return node.value
        raise TemplateError(f"unsupported constant {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id == "params":
            return params
        if node.id in params:
            return params[node.id]
        keys = sorted(params)[:12]
        raise TemplateError(
            f"unknown name {node.id!r}; params keys are {keys}")
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        left = _eval_node(node.left, params)
        right = _eval_node(node.right, params)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in (left, right)):
            raise TemplateError("arithmetic operands must be numbers")
        try:
            return _ALLOWED_BINOPS[type(node.op)](left, right)
        except ArithmeticError as e:
            raise TemplateError(f"arithmetic error: {e}") from e
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_eval_node(node.operand, params))
    if isinstance(node, ast.Subscript):
        target = _eval_node(node.value, params)
        key = _eval_node(node.slice, params)
        try:
            return target[key]
        except (KeyError, IndexError, TypeError) as e:
            raise TemplateError(f"subscript failed: {e}") from e
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_node(elt, params) for elt in node.elts]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in _ALLOWED_FUNCS and not node.keywords:
        args = [_eval_node(a, params) for a in node.args]
        try:
            return _ALLOWED_FUNCS[node.func.id](*args)
        except (TypeError, ValueError) as e:
            raise TemplateError(f"{node.func.id}() failed: {e}") from e
    raise TemplateError(
        f"unsupported syntax in slot expression: {ast.dump(node)[:80]}")


def _num(value, params, slot):
    """Slot values may be numbers or arithmetic expressions over params."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise TemplateError(f"slot {slot}: booleans are not valid numbers")
    if isinstance(value, (int, float)):
        value = float(value)
        if value != value or abs(value) >= _MAX_ABS:
            raise TemplateError(f"slot {slot}: value out of range: {value!r}")
        return value
    if isinstance(value, str):
        return safe_eval(value, params)
    raise TemplateError(
        f"slot {slot}: expected number or params expression, got {value!r}")


# ------------------------------------------------------------------ skeletons
# Raw-string skeletons with __SLOT__ placeholders substituted via .replace().
# Placeholders are only ever filled with repr()/json.dumps() output, so the
# rendered code is always a valid, eval-free Python literal program.

_OBJECTIVE_RANGE_CODE = r'''def check(code, objective, params):
    """objective_range: flag a printed objective outside the physical bounds
    [lower=__LOWER__, upper=__UPPER__] derived from the problem text."""
    try:
        if objective is None:
            return None
        obj = float(objective)
        lower = __LOWER__
        upper = __UPPER__
        tol = 1e-6 * max(1.0, abs(obj))
        if lower is not None and obj < lower - tol:
            return ("objective %.6g is below the physical lower bound %.6g"
                    % (obj, lower))
        if upper is not None and obj > upper + tol:
            return ("objective %.6g exceeds the physical upper bound %.6g"
                    % (obj, upper))
        return None
    except Exception:
        return None
'''

_SENSE_CODE = r'''def check(code, objective, params):
    """sense_direction: problem asks to __EXPECTED__; flag only when the
    opposite sense appears in the code and the expected sense is absent."""
    import re
    try:
        c = (code or "").lower()
        if not c.strip():
            return None
        max_sig = re.search(r"\bmaximi[sz]e\b", c) \
            or re.search(r"\blpmaximize\b", c) \
            or re.search(r"sense\s*=\s*[\"']max", c)
        min_sig = re.search(r"\bminimi[sz]e\b", c) \
            or re.search(r"\blpminimize\b", c) \
            or re.search(r"sense\s*=\s*[\"']min", c)
        if max_sig and min_sig:
            return None
        if "__EXPECTED__" == "maximize" and min_sig and not max_sig:
            return ("problem asks to maximize but the code only shows a "
                    "minimize sense (no maximize signal found)")
        if "__EXPECTED__" == "minimize" and max_sig and not min_sig:
            return ("problem asks to minimize but the code only shows a "
                    "maximize sense (no minimize signal found)")
        return None
    except Exception:
        return None
'''

_PHANTOM_CODE = r'''def check(code, objective, params):
    """phantom_resource: flag assignments of more of a resource than the
    problem grants (granted=__GRANTED__); classic case is a nonzero initial
    inventory the text never mentions."""
    import re
    try:
        if not code:
            return None
        granted = __GRANTED__
        keywords = __KEYWORDS__
        tol = 1e-9 * max(1.0, abs(granted))
        for kw in keywords:
            if not isinstance(kw, str) or len(kw) < 2:
                continue
            pat = re.compile(
                r"(?i)\b" + re.escape(kw) + r"(?:[A-Za-z0-9_]*|\[\d+\])"
                r"\s*=\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?)")
            for m in pat.finditer(code):
                try:
                    val = float(m.group(1))
                except ValueError:
                    continue
                if val > granted + tol:
                    return ("fabricated resource: '%s' assigns %.6g but the "
                            "problem grants at most %.6g"
                            % (m.group(0)[:60], val, granted))
        return None
    except Exception:
        return None
'''

_CONSTANT_CODE = r'''def check(code, objective, params):
    """constant_fidelity: the text constant __NAME_JSON__ (value __EXPECTED__)
    must appear among the code's numeric literals (rel tol __REL_TOL__)."""
    import re
    try:
        if not code:
            return None
        name = __NAME_JSON__
        expected = __EXPECTED__
        rel_tol = __REL_TOL__
        tol = rel_tol * max(1.0, abs(expected))
        for tok in re.findall(
                r"(?<![A-Za-z0-9_.])(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?",
                code):
            try:
                v = float(tok)
            except ValueError:
                continue
            if abs(v - expected) <= tol:
                return None
            if expected < 0 and abs(v + expected) <= tol:
                return None
        return ("constant %s=%.6g from the problem text not found among the "
                "code's numeric literals" % (name, expected))
    except Exception:
        return None
'''

_MOQ_CODE = r'''def check(code, objective, params):
    """conditional_moq: the text states an all-or-nothing relation
    (q = 0 or q >= m); a faithful model needs a binary/indicator variable,
    and the threshold m (when given) must appear among numeric literals."""
    import re
    try:
        if not code:
            return None
        m = __M__
        require_binary = __REQUIRE_BINARY__
        has_binary = bool(
            re.search(r"vtype\s*=\s*[\"'][bB]", code)
            or re.search(r"\bcat\s*=\s*[\"'][Bb]inary", code)
            or re.search(r"\bbinary\s*=\s*True", code)
            or re.search(r"\b(?:BoolVar|NewBoolVar|bool_var|addBinary)\b", code)
            or re.search(r"\bBinary\b", code)
            or re.search(r"\bbinvar\b", code, re.I))
        if require_binary and not has_binary:
            return ("text requires a conditional all-or-nothing quantity "
                    "(q=0 or q>=m) but the code declares no binary variable")
        if m is not None:
            tol = 1e-6 * max(1.0, abs(m))
            found = False
            for tok in re.findall(
                    r"(?<![A-Za-z0-9_.])(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?",
                    code):
                try:
                    v = float(tok)
                except ValueError:
                    continue
                if abs(v - m) <= tol:
                    found = True
                    break
            if not found:
                return ("conditional-quantity threshold %.6g from the text "
                        "not found among the code's numeric literals" % m)
        return None
    except Exception:
        return None
'''


def _render_objective_range(slots, params):
    lower = _num(slots.get("lower"), params, "lower")
    upper = _num(slots.get("upper"), params, "upper")
    if lower is None and upper is None:
        raise TemplateError("objective_range needs at least one of lower/upper")
    if lower is not None and upper is not None and lower > upper:
        raise TemplateError(f"lower {lower} > upper {upper}")
    return (_OBJECTIVE_RANGE_CODE
            .replace("__LOWER__", repr(lower))
            .replace("__UPPER__", repr(upper)))


def _render_sense_direction(slots, params):
    expected = str(slots.get("expected", "")).strip().lower()
    if expected not in ("maximize", "minimize"):
        raise TemplateError(
            f"sense_direction slot 'expected' must be maximize|minimize, "
            f"got {slots.get('expected')!r}")
    return _SENSE_CODE.replace("__EXPECTED__", expected)


def _render_phantom_resource(slots, params):
    granted = _num(slots.get("granted", 0), params, "granted")
    if granted is None:
        granted = 0.0
    if granted < 0:
        raise TemplateError(f"slot granted must be >= 0, got {granted}")
    raw_kw = slots.get("keywords") or []
    if isinstance(raw_kw, str):
        raw_kw = [raw_kw]
    keywords = []
    for kw in raw_kw:
        if isinstance(kw, str) and len(kw.strip()) >= 2:
            kw = kw.strip()
            if kw not in keywords:
                keywords.append(kw)
    keywords = keywords[:10]
    if not keywords:
        raise TemplateError(
            "phantom_resource needs >=1 keyword of length >= 2")
    return (_PHANTOM_CODE
            .replace("__GRANTED__", repr(granted))
            .replace("__KEYWORDS__", json.dumps(keywords)))


def _render_constant_fidelity(slots, params):
    name = str(slots.get("name") or "").strip()
    if not name:
        raise TemplateError("constant_fidelity needs a non-empty slot 'name'")
    expected = _num(slots.get("expected"), params, "expected")
    if expected is None:
        raise TemplateError("constant_fidelity needs slot 'expected'")
    rel_tol = _num(slots.get("rel_tol", 1e-6), params, "rel_tol")
    if rel_tol is None or rel_tol <= 0 or rel_tol > 0.1:
        raise TemplateError(f"slot rel_tol must be in (0, 0.1], got {rel_tol}")
    return (_CONSTANT_CODE
            .replace("__NAME_JSON__", json.dumps(name))
            .replace("__EXPECTED__", repr(expected))
            .replace("__REL_TOL__", repr(rel_tol)))


def _render_conditional_moq(slots, params):
    m = _num(slots.get("m"), params, "m")
    require_binary = slots.get("require_binary", True)
    require_binary = bool(require_binary)
    if m is None and not require_binary:
        raise TemplateError(
            "conditional_moq with m=null and require_binary=false checks "
            "nothing; supply m or require_binary")
    if m is not None and m <= 0:
        raise TemplateError(f"slot m must be positive, got {m}")
    return (_MOQ_CODE
            .replace("__M__", repr(m))
            .replace("__REQUIRE_BINARY__", repr(require_binary)))


TEMPLATES = ("objective_range", "phantom_resource", "sense_direction",
             "constant_fidelity", "conditional_moq")

_RENDERERS = {
    "objective_range": _render_objective_range,
    "phantom_resource": _render_phantom_resource,
    "sense_direction": _render_sense_direction,
    "constant_fidelity": _render_constant_fidelity,
    "conditional_moq": _render_conditional_moq,
}


def render(template, slots, params=None):
    """Render a template instance to a self-contained check() source string.

    ``slots`` numbers/params-expressions are evaluated against ``params``
    and baked in as constants. Raises TemplateError on any invalid slot.
    """
    if not isinstance(slots, dict):
        raise TemplateError(f"slots must be a dict, got {type(slots).__name__}")
    fn = _RENDERERS.get(str(template))
    if fn is None:
        raise TemplateError(
            f"unknown template {template!r}; choose from {list(_RENDERERS)}")
    return fn(slots, params or {})


# ------------------------------------------------------------------ fixtures
# Each template ships a built-in must-fire/must-pass pair; run_fixtures()
# executes them in-process as a smoke gate (tests + d2_author startup).

FIXTURES = [
    {"template": "objective_range",
     "slots": {"lower": 0, "upper": "(a1+a2)*train_rate"},
     "params": {"a1": 10, "a2": 15, "train_rate": 5},
     "must_fire": {"code": "", "objective": 126},
     "must_pass": {"code": "", "objective": 125}},
    {"template": "objective_range",
     "slots": {"lower": 0, "upper": None},
     "params": {},
     "must_fire": {"code": "", "objective": -5},
     "must_pass": {"code": "", "objective": 0}},
    {"template": "sense_direction",
     "slots": {"expected": "maximize"},
     "params": {},
     "must_fire": {"code": "model.setObjective(obj, sense='minimize')",
                   "objective": None},
     "must_pass": {"code": "model.setObjective(obj, sense='maximize')",
                   "objective": None}},
    {"template": "phantom_resource",
     "slots": {"resource": "initial inventory",
               "keywords": ["initial_inventory", "init_inv", "I0"],
               "granted": 0},
     "params": {},
     "must_fire": {"code": "I0 = 500\nmodel.addConstr(inv[0] == I0 + x[0])",
                   "objective": None},
     "must_pass": {"code": "I0 = 0\nmodel.addConstr(inv[0] == x[0] - d[0])",
                   "objective": None}},
    {"template": "constant_fidelity",
     "slots": {"name": "train_rate", "expected": "train_rate"},
     "params": {"train_rate": 5},
     "must_fire": {"code": "model.addConstr(pilots <= 4 * jets)",
                   "objective": None},
     "must_pass": {"code": "model.addConstr(pilots <= 5 * jets)",
                   "objective": None}},
    {"template": "conditional_moq",
     "slots": {"m": 100, "require_binary": True},
     "params": {},
     "must_fire": {"code": "q = model.addVar(lb=0, ub=1000)",
                   "objective": None},
     "must_pass": {"code": ("q = model.addVar(lb=0)\n"
                            "y = model.addVar(vtype='B')\n"
                            "model.addConstr(q >= 100 * y)"),
                   "objective": None}},
]


def _exec_local(rule_code, case, params):
    ns = {}
    exec(compile(rule_code, "<rule>", "exec"), ns)
    check = ns.get("check")
    if check is None:
        raise TemplateError("rendered code defines no check()")
    return check(case.get("code") or "", case.get("objective"), params or {})


def run_fixtures():
    """Render each built-in fixture and verify must-fire fires and
    must-pass stays silent. Returns {"ok": bool, "fixtures": [...]}."""
    out = []
    ok_all = True
    for fx in FIXTURES:
        entry = {"template": fx["template"], "slots": fx["slots"]}
        try:
            code = render(fx["template"], fx["slots"], fx.get("params"))
            fire_v = _exec_local(code, fx["must_fire"], fx.get("params"))
            pass_v = _exec_local(code, fx["must_pass"], fx.get("params"))
            entry.update(must_fire_fired=fire_v is not None,
                         must_pass_fired=pass_v is not None,
                         ok=fire_v is not None and pass_v is None)
        except Exception as e:
            entry.update(ok=False, error=f"{type(e).__name__}: {e}")
        ok_all = ok_all and entry["ok"]
        out.append(entry)
    return {"ok": ok_all, "fixtures": out}
