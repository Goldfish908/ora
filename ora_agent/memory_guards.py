"""Allowlisted deterministic repairs proposed by the memory outer loop."""
from __future__ import annotations

import ast

GUARD_ADDVAR_V = "addvar_v_to_vtype"
GUARD_ADDVAR_NAME = "addvar_v_to_name"
SUPPORTED_GUARDS = {GUARD_ADDVAR_V, GUARD_ADDVAR_NAME}


def _rewrite_addvar_v(code: str, destination: str) -> str:
    tree = ast.parse(code)
    lines = code.splitlines(keepends=True)
    edits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "addVar"):
            continue
        keywords = {keyword.arg: keyword for keyword in node.keywords if keyword.arg}
        if "v" not in keywords:
            continue
        if destination == "vtype" and "vtype" in keywords:
            raise ValueError("addVar contains both v and vtype; automatic repair is unsafe")
        if destination == "name":
            if "vtype" not in keywords:
                raise ValueError("v is ambiguous without an existing vtype")
            if "name" in keywords:
                raise ValueError("addVar already contains a name keyword")
        keyword = keywords["v"]
        literal_domain = (isinstance(keyword.value, ast.Constant)
                          and isinstance(keyword.value.value, str))
        variable_name = literal_domain or isinstance(keyword.value, ast.JoinedStr)
        if (destination == "vtype" and not literal_domain) or (destination == "name" and not variable_name):
            raise ValueError("addVar v value has an unsupported role or expression")
        if keyword.lineno != keyword.end_lineno:
            raise ValueError("multiline addVar shorthand requires LLM repair")
        line = lines[keyword.lineno - 1]
        if line[keyword.col_offset:keyword.col_offset + 1] != "v":
            raise ValueError("cannot locate the addVar v keyword")
        edits.append((keyword.lineno, keyword.col_offset))
    if not edits:
        raise ValueError("no repairable addVar v shorthand found")
    for line_number, column in sorted(edits, reverse=True):
        index = line_number - 1
        lines[index] = lines[index][:column] + destination + lines[index][column + 1:]
    patched = "".join(lines)
    ast.parse(patched)
    if patched == code:
        raise ValueError("memory guard did not change the candidate")
    return patched


def repair_addvar_v_to_vtype(code: str) -> str:
    return _rewrite_addvar_v(code, "vtype")


def repair_addvar_v_to_name(code: str) -> str:
    return _rewrite_addvar_v(code, "name")


def apply_memory_guard(name: str, code: str) -> str:
    if name == GUARD_ADDVAR_V:
        return repair_addvar_v_to_vtype(code)
    if name == GUARD_ADDVAR_NAME:
        return repair_addvar_v_to_name(code)
    raise ValueError(f"unsupported memory guard: {name}")


def validate_guard_contract(name: str) -> dict:
    if name not in SUPPORTED_GUARDS:
        return {"passed": False, "reason": "unsupported_guard", "guard": name}
    if name == GUARD_ADDVAR_V:
        invalid = "from pyscipopt import Model\nm = Model()\nx = m.addVar(v='I')\n"
        clean = invalid.replace("v='I'", "vtype='I'")
        ambiguous = invalid.replace("v='I'", "v='I', vtype='I'")
        expected = "vtype='I'"
        ambiguity_marker = "both v and vtype"
    else:
        invalid = "from pyscipopt import Model\nm = Model()\nx = m.addVar(v='x1', vtype='I')\n"
        clean = invalid.replace("v='x1'", "name='x1'")
        ambiguous = "from pyscipopt import Model\nm = Model()\nx = m.addVar(v='x1')\n"
        expected = "name='x1'"
        ambiguity_marker = "ambiguous"
    unrelated = "factory(v='I')\n"
    checks = {}
    try:
        patched = apply_memory_guard(name, invalid)
        checks["must_fire"] = expected in patched and "v=" not in patched
    except (ValueError, TypeError, SyntaxError) as exc:
        checks["must_fire"] = False
        checks["must_fire_error"] = f"{type(exc).__name__}: {exc}"
    for key, source, marker in (("must_pass_clean", clean, "no repairable"),
                                ("unrelated_unchanged", unrelated, "no repairable"),
                                ("ambiguous_rejected", ambiguous, ambiguity_marker)):
        try:
            apply_memory_guard(name, source)
            checks[key] = False
        except ValueError as exc:
            checks[key] = marker in str(exc)
    passed = all(checks.get(key) is True for key in
                 ("must_fire", "must_pass_clean", "unrelated_unchanged", "ambiguous_rejected"))
    return {"passed": passed, "guard": name, "checks": checks,
            "independent_from_source_traces": True}
