"""Deterministic AST probes over generated modeling code (Phase A).

Extracts, from a gen.py source string:
- data_keys: dataset keys the code actually reads (string constants that match
  the known data schema, attribute accesses on a `data`-like object)
- var_names: solver variable name prefixes from addVar(name=...) calls
- n_addcons: number of addCons/addConsIndicator calls
- init_signals: heuristic evidence that first-period inventory is pinned

Then evaluates rule probes: each probe maps a witness rule family to required
data keys. A probe FAILS (=> early BLOCK evidence) when a required key is never
referenced anywhere in the source.
"""

from __future__ import annotations

import ast
import re

# Data schema universe for RetailOpt-190 (top-level + nested), from
# data/m1_retailopt/retailopt_190.jsonl (union over all 190 instances).
DATA_KEYS = {
    "cold_capacity", "cold_usage", "constraints", "costs", "demand_curve",
    "demand_share", "description", "labor_cap", "labor_usage", "lead_time",
    "locations", "name", "network", "periods", "production_cap", "products",
    "return_rate", "shelf_life",
    # nested
    "moq", "pack_size", "budget_per_period", "waste_limit_pct",
    "sub_edges", "trans_edges",
    "lost_sales", "inventory", "waste", "fixed_order", "transshipment",
    "purchasing",
}

# rule_id -> (description, required data keys -- ALL must be referenced)
# Only requirements that are unconditional for every RetailOpt instance are
# probeable this way; conditional ones (moq>0, budget is not null, ...) are
# handled per-instance by the caller passing instance-specific requirements.
BASE_PROBES = {
    "P-DEMAND": ("demand fulfillment needs demand data",
                 ["demand_curve", "demand_share"]),
    "P-PRODCAP": ("aggregate production capacity", ["production_cap"]),
    "P-SHELF": ("shelf-life tracking", ["shelf_life"]),
    "P-LEAD": ("order lead time", ["lead_time"]),
    "P-LOSTSALES": ("lost-sales penalty in objective", ["lost_sales"]),
    "P-INVCOST": ("inventory holding cost in objective", ["inventory"]),
}

CONDITIONAL_PROBES = {
    # condition(data) -> (rule_id, description, required keys)
    "P-LABOR": (lambda d: any((v or 0) > 0 for v in (d.get("labor_cap") or {}).values())
                if isinstance(d.get("labor_cap"), dict) else bool(d.get("labor_cap")),
                "labor capacity", ["labor_cap", "labor_usage"]),
    "P-COLD": (lambda d: bool(d.get("cold_capacity")),
               "cold storage capacity", ["cold_capacity", "cold_usage"]),
    "P-MOQ": (lambda d: (d.get("constraints", {}).get("moq") or 0) > 0,
              "minimum order quantity", ["moq"]),
    "P-PACK": (lambda d: (d.get("constraints", {}).get("pack_size") or 1) > 1,
               "pack-size rounding", ["pack_size"]),
    "P-BUDGET": (lambda d: d.get("constraints", {}).get("budget_per_period") is not None,
                 "per-period budget", ["budget_per_period"]),
    "P-WASTELIM": (lambda d: d.get("constraints", {}).get("waste_limit_pct") is not None,
                   "waste limit", ["waste_limit_pct"]),
    "P-TRANS": (lambda d: bool(d.get("network", {}).get("trans_edges")),
                "transshipment arcs", ["trans_edges", "transshipment"]),
    "P-SUB": (lambda d: bool(d.get("network", {}).get("sub_edges")),
              "substitution arcs", ["sub_edges"]),
    "P-RET": (lambda d: any((v or 0) > 0 for v in (d.get("return_rate") or {}).values())
              if isinstance(d.get("return_rate"), dict) else bool(d.get("return_rate")),
              "returns flow", ["return_rate"]),
}

_INIT_PAT = re.compile(
    r"(==\s*0\b|\.fix\(|setInitial|initial)", re.IGNORECASE)


def extract_signals(code: str) -> dict:
    """AST extraction; degrades to regex if the source does not parse."""
    out = {"parse_ok": True, "data_keys": set(), "var_names": set(),
           "n_addcons": 0, "addcons_src": [], "string_consts": set()}
    try:
        tree = ast.parse(code)
    except SyntaxError:
        out["parse_ok"] = False
        out["string_consts"] = set(re.findall(r"""['"]([A-Za-z_][A-Za-z0-9_]*)['"]""", code))
        out["data_keys"] = out["string_consts"] & DATA_KEYS
        out["var_names"] = set(re.findall(r"""addVar\([^)]*name\s*=\s*['"]([A-Za-z_]+)""", code))
        out["n_addcons"] = len(re.findall(r"\baddCons", code))
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out["string_consts"].add(node.value)
            for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", node.value):
                if tok in DATA_KEYS:
                    out["data_keys"].add(tok)
        if isinstance(node, ast.Attribute) and node.attr in DATA_KEYS:
            out["data_keys"].add(node.attr)
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (
                fn.id if isinstance(fn, ast.Name) else "")
            if name == "addVar":
                for kw in node.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        m = re.match(r"([A-Za-z_]+)", str(kw.value.value))
                        if m:
                            out["var_names"].add(m.group(1))
            if name.startswith("addCons"):
                out["n_addcons"] += 1
                seg = ast.get_source_segment(code, node)
                if seg:
                    out["addcons_src"].append(seg)
    out["data_keys"] |= out["string_consts"] & DATA_KEYS
    return out


def eval_probes(signals: dict, data: dict) -> dict:
    """Return {rule_id: 'pass'|'fail'|'na'} plus per-rule missing keys."""
    res = {}
    for rid, (desc, keys) in BASE_PROBES.items():
        missing = [k for k in keys if k not in signals["data_keys"]]
        res[rid] = {"status": "fail" if missing else "pass",
                    "missing_keys": missing, "desc": desc}
    for rid, (cond, desc, keys) in CONDITIONAL_PROBES.items():
        try:
            active = bool(cond(data))
        except Exception:
            active = False
        if not active:
            res[rid] = {"status": "na", "missing_keys": [], "desc": desc}
            continue
        missing = [k for k in keys if k not in signals["data_keys"]]
        res[rid] = {"status": "fail" if missing else "pass",
                    "missing_keys": missing, "desc": desc}
    return res


def init_pin_evidence(signals: dict) -> dict:
    """Heuristic: does any constraint source mention pinning inventory at the
    first period? We look for addCons segments that combine the inventory var
    prefix with a zero-fixing / initial pattern. Advisory only (LLM ledger in
    Phase B/C is the main C-INIT detector)."""
    inv_vars = [v for v in signals["var_names"] if v.upper().startswith("I")]
    hits = []
    for seg in signals["addcons_src"]:
        if any(re.search(rf"\b{v}\b", seg) for v in inv_vars) and _INIT_PAT.search(seg):
            hits.append(seg[:200])
    return {"inv_vars": inv_vars, "pin_hits": hits,
            "heuristic_pass": bool(hits)}
