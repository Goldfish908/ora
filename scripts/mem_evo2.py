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


# ---------- counterfactual replay (LLM + sandbox cost) ----------

def write_replay_inputs(unit: dict, base_conventions: Path | None,
                        target_cells: list[str], win_cells: list[str],
                        tag: str) -> dict:
    """Compose the conventions file (base + candidate unit) and the
    per-variant scenario lists; returns paths for the pilot shards."""
    rd = EVO_DIR / f"replay_{unit['unit_id']}_{tag}"
    rd.mkdir(parents=True, exist_ok=True)
    conv = ""
    if base_conventions:
        conv = base_conventions.read_text().strip() + "\n\n"
    conv += f"# candidate unit {unit['unit_id']} (trigger: {unit['trigger']})\n"
    conv += unit["text"].strip() + "\n"
    (rd / "conventions.txt").write_text(conv)
    by_variant = defaultdict(list)
    for sid in target_cells + win_cells:
        by_variant[sid.rsplit("_", 1)[-1]].append(sid)
    for v, sids in by_variant.items():
        (rd / f"cells_{v}.txt").write_text("\n".join(sorted(sids)) + "\n")
    (rd / "replay_meta.json").write_text(json.dumps(
        {"unit_id": unit["unit_id"], "target_cells": target_cells,
         "win_cells": win_cells}, ensure_ascii=False, indent=1))
    return {"dir": str(rd), "variants": sorted(by_variant)}


def replay_cmd(unit: dict, base_conventions: Path | None,
               target_cells: list[str], win_cells: list[str],
               tag: str) -> list[str]:
    """Shell commands (one per variant shard) for counterfactual replay:
    generation with base+candidate conventions on exactly the targeted
    failing cells (fix test) and a sample of passing cells (win-FP test)."""
    info = write_replay_inputs(unit, base_conventions, target_cells,
                               win_cells, tag)
    rd = Path(info["dir"])
    cmds = []
    for v in info["variants"]:
        cmds.append(
            f"python3 scripts/m1_pilot.py --variant {v} --modes on "
            f"--prompt-mode schema_sol "
            f"--scenarios-file {rd}/cells_{v}.txt "
            f"--conventions-file {rd}/conventions.txt "
            f"--out-dir {rd} --out-tag _{v}")
    return cmds


def cmd_replay(unit_id: str, base: str | None, tag: str,
               n_wins: int = 10) -> None:
    reg = {u["unit_id"]: u for u in load_registry()}
    unit = reg[unit_id]
    cl = json.loads(CLUSTERS.read_text())
    target = cl["clusters"][unit["origin"]["cluster_id"]]
    # win cells: passing cells from the same run's final states
    # (caller supplies the run via clusters meta; here: sample from dev slice)
    wins = unit["origin"].get("win_cells", [])[:n_wins]
    cmds = replay_cmd(unit, Path(base) if base else None, target, wins, tag)
    print(f"# {len(cmds)} shard commands (run with LLM env sourced):")
    for c in cmds:
        print(c + " &")
    print("wait")


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
    rp = sub.add_parser("replay")
    rp.add_argument("--unit", required=True)
    rp.add_argument("--base", default=None,
                    help="base conventions file the candidate is appended to")
    rp.add_argument("--tag", default="r1")
    args = ap.parse_args()

    if args.cmd == "cluster":
        cmd_cluster(args.runs)
    elif args.cmd == "register":
        u = register_unit(args.asset, args.text, args.trigger,
                          {"cluster_id": args.cluster})
        print(f"registered {u['unit_id']}")
    elif args.cmd == "replay":
        cmd_replay(args.unit, args.base, args.tag)
    elif args.cmd == "status":
        cmd_status()


if __name__ == "__main__":
    main()
