#!/usr/bin/env python3
"""mem_evo2: closed-loop self-evolution engine for non-parametric assets.

One engine, five module assets (see docs: in-loop/out-loop architecture):
  A1 memory_clause  : conditional conventions injected at generation/feedback
  A2 guard_rule     : deterministic AST/regex crash checks (pre-solve)
  A3 gate_check     : requirement-ledger protocol items (pre-solve verifier)
  A4a witness_rule  : semantic re-computation rules (post-solve)
  (A4b judge weights are parametric: this loop only produces their DATA)

Lifecycle per unit: candidate -> dev-passed -> promoted | rejected | retired
Promotion discipline (inherited from crash-guard mining):
  - counterfactual replay: fix >= MIN_FIX of targeted failing cells
  - win-FP = 0: zero previously-passing cells broken
  - two-tier: dev40 pass -> gapcheck60 confirm -> promote
  - F5-F8 / IndustryOR NEVER participate in evolution (final eval only)

Subcommands (offline, zero LLM):
  cluster   : mine failure clusters from run records -> clusters.json
  register  : add a candidate unit to the registry
  status    : registry overview with per-unit lineage stats

Subcommands (LLM/sandbox cost, run when API is free):
  replay    : counterfactual replay of a unit on its target cells (+ wins)
  score     : collect replay outcomes into the unit's stats

Usage: python3 scripts/mem_evo2.py cluster --runs "runs/m1_presolve/m1_presolve_guard3_*.jsonl"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.m1_feedback import failure_type  # noqa: E402

EVO_DIR = ROOT / "work" / "mem_evo"
REGISTRY = EVO_DIR / "registry.jsonl"
CLUSTERS = EVO_DIR / "clusters.json"

MIN_FIX = 2  # a unit must demonstrably fix >=2 targeted cells on dev


# ---------- registry ----------

def load_registry() -> list[dict]:
    if not REGISTRY.exists():
        return []
    return [json.loads(l) for l in REGISTRY.read_text().splitlines() if l.strip()]


def register_unit(asset: str, text: str, trigger: str, origin: dict) -> dict:
    EVO_DIR.mkdir(parents=True, exist_ok=True)
    reg = load_registry()
    unit = {
        "unit_id": f"{asset}-{len([u for u in reg if u['asset'] == asset]) + 1:03d}",
        "asset": asset,
        "text": text,
        "trigger": trigger,
        "status": "candidate",
        "origin": origin,          # {cluster_id, run, example_cells}
        "stats": {"targeted": [], "fixed": [], "broken_wins": [],
                  "dev40": None, "gapcheck60": None},
        "created": time.strftime("%Y-%m-%d %H:%M"),
    }
    with REGISTRY.open("a") as f:
        f.write(json.dumps(unit, ensure_ascii=False) + "\n")
    return unit


# ---------- failure clustering ----------

CRASH_PAT = [
    ("sense_literal", r"unrecognized optimization sense"),
    ("objective_list", r"neither Expr or number but list"),
    ("expr_compare", r"__richcmp__|NotImplementedError"),
    ("bad_param_name", r"the parameter .* not found"),
    ("quicksum_method", r"no attribute.*quicksum"),
    ("none_subscript", r"NoneType.*subscript|NoneType.*not subscriptable"),
    ("infinity_method", r"infinity"),
    ("phantom_file", r"FileNotFoundError"),
    ("syntax", r"SyntaxError"),
]


def crash_signature(stderr: str) -> str:
    for name, pat in CRASH_PAT:
        if re.search(pat, stderr or ""):
            return name
    return "crash_other"


def cluster_records(recs: list[dict]) -> dict:
    """Group failing cells by (failure_type, fine signature)."""
    clusters = defaultdict(list)
    for r in recs:
        ft = failure_type(r)
        if ft is None:
            continue
        if ft == "crash":
            sig = crash_signature(r.get("stderr_tail", ""))
        elif ft == "witness_infeasible":
            rules = r.get("witness_rules") or []
            sig = rules[0] if rules else "witness_unknown"
        else:
            sig = ft
        clusters[f"{ft}::{sig}"].append(r["scenario_id"])
    return dict(clusters)


def cmd_cluster(run_globs: list[str]) -> None:
    recs = []
    for g in run_globs:
        for f in sorted(ROOT.glob(g)):
            for line in f.read_text().splitlines():
                if line.strip():
                    recs.append(json.loads(line))
    # keep only each cell's final round
    last = {}
    for r in recs:
        key = (r["scenario_id"], r["thinking"])
        if key not in last or r["round"] > last[key]["round"]:
            last[key] = r
    cl = cluster_records(last.values())
    out = {
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "runs": run_globs,
        "n_cells": len(last),
        "n_failing": sum(len(v) for v in cl.values()),
        "clusters": {k: sorted(v) for k, v in
                     sorted(cl.items(), key=lambda x: -len(x[1]))},
    }
    EVO_DIR.mkdir(parents=True, exist_ok=True)
    CLUSTERS.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"cells={out['n_cells']} failing={out['n_failing']} "
          f"clusters={len(cl)}")
    for k, v in sorted(cl.items(), key=lambda x: -len(x[1]))[:15]:
        print(f"  {len(v):>4}  {k}")


def cmd_status() -> None:
    reg = load_registry()
    if not reg:
        print("registry empty")
        return
    by_status = Counter(u["status"] for u in reg)
    print(f"units={len(reg)} status={dict(by_status)}")
    for u in reg:
        s = u["stats"]
        print(f"  {u['unit_id']} [{u['status']}] trigger={u['trigger'][:40]} "
              f"fixed={len(s['fixed'])} broken={len(s['broken_wins'])}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cluster")
    c.add_argument("--runs", nargs="+", required=True)
    r = sub.add_parser("register")
    r.add_argument("--asset", required=True,
                   choices=["memory_clause", "guard_rule", "gate_check",
                            "witness_rule"])
    r.add_argument("--text", required=True)
    r.add_argument("--trigger", default="")
    r.add_argument("--cluster", default="")
    sub.add_parser("status")
    args = ap.parse_args()

    if args.cmd == "cluster":
        cmd_cluster(args.runs)
    elif args.cmd == "register":
        u = register_unit(args.asset, args.text, args.trigger,
                          {"cluster_id": args.cluster})
        print(f"registered {u['unit_id']}")
    elif args.cmd == "status":
        cmd_status()


if __name__ == "__main__":
    main()
