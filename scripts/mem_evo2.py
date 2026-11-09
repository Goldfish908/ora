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
  - MULTI-SAMPLE (learned gen1, 2026-11-09): single-sample replay is
    dominated by resampling noise — marginally-passing cells flip ~75%
    of the time under a FRESH SAMPLE OF THE SAME conventions (6/8 wins
    flipped in gen1's v0.3 control). Replay must run n_seeds >= 3 per
    cell per arm, treatment AND control (base conventions), and compare
    per-cell mean pass rates, not single draws.
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


# ---------- RSI: LLM propose + automatic promotion judgement ----------

PROPOSE_PROMPT = """You are the PROPOSER in a self-evolving OR-modeling system.
A cluster of modeling failures has been mined from run records. Your job:
diagnose the SHARED mechanism and draft ONE conditional memory clause that
would prevent it.

Cluster signature: {sig}  ({n} failing cells)

Example failures (problem excerpt + the violation evidence):
{examples}

Hard requirements for the clause (learned from rejected generations):
1. CONDITIONAL: it must fire only when a SPECIFIC data structure is present
   (name the exact data field / edge type / parameter that activates it) —
   never phrase the trigger as a business noun ("substitution", "transfer");
   always bind to the data ("when data['sub_edges'] is non-empty ...").
2. WIN-SAFE: the clause must NOT change behavior on cells where the trigger
   is absent. State explicitly why previously-passing cells are unaffected.
3. SMALL: one mechanism per clause, <= 4 sentences.
4. Do NOT mention reference objectives or ground truth.

Reply with ONLY a JSON object:
{{"asset": "memory_clause", "trigger": "<exact data-field condition>",
  "text": "<the clause>", "rationale": "<mechanism diagnosis, 1-2 sentences>",
  "win_safety": "<why passing cells are unaffected>"}}"""


def cmd_propose(cluster_id: str, n_examples: int = 3) -> None:
    """LLM diagnoses a failure cluster and drafts a candidate unit."""
    from ora_agent import llm as llm_mod
    from scripts.m1_pilot import DATA
    cl = json.loads(CLUSTERS.read_text())
    cells = cl["clusters"][cluster_id][:n_examples]
    ds = {json.loads(l)["scenario_id"]: json.loads(l)
          for l in DATA.read_text().splitlines() if l.strip()}
    # pull violation evidence from the clustered run records
    examples = []
    run_globs = cl.get("runs", [])
    for sid in cells:
        ev = ""
        for g in run_globs:
            for f in sorted(ROOT.glob(g)):
                for line in f.read_text().splitlines():
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    if r["scenario_id"] == sid and r.get("witness_details"):
                        ev = "\n".join(r["witness_details"][:3])
        row = ds.get(sid)
        excerpt = (row["prompt_schema"][:1200] if row else "(prompt n/a)")
        examples.append(f"--- {sid} ---\n{excerpt}\nVIOLATION:\n{ev[:800]}")
    prompt = PROPOSE_PROMPT.format(sig=cluster_id,
                                   n=len(cl["clusters"][cluster_id]),
                                   examples="\n\n".join(examples))
    cfg = llm_mod.load_config()
    resp = llm_mod.chat([{"role": "user", "content": prompt}],
                        max_tokens=8192, temperature=0.6,
                        extra={"reasoning_effort": "medium"}, config=cfg)
    text = (resp.get("content") or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        print("propose failed: no JSON in output")
        print(text[:500])
        return
    spec = json.loads(m.group(0))
    unit = register_unit(spec.get("asset", "memory_clause"), spec["text"],
                         spec.get("trigger", ""),
                         {"cluster_id": cluster_id, "proposer": "llm",
                          "rationale": spec.get("rationale", ""),
                          "win_safety": spec.get("win_safety", "")})
    print(f"proposed {unit['unit_id']}: trigger={unit['trigger']}")
    print(f"  text: {unit['text'][:200]}")


def _pass_rates(replay_dir: Path, cells: list[str]) -> dict[str, list[bool]]:
    """Per-cell pass indicators across all seed files in a replay dir."""
    res: dict[str, list[bool]] = defaultdict(list)
    for f in sorted(replay_dir.glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r["scenario_id"] in cells:
                res[r["scenario_id"]].append(failure_type(r) is None)
    return res


def cmd_judge(unit_id: str, treat_dir: str, ctrl_dir: str, tier: str) -> None:
    """Automatic promotion judgement for one replay tier (dev or gapcheck).

    Discipline: promote iff target mean gain >= +8pp AND win mean delta
    >= -3pp (noise tolerance). Verdict is written back to the registry.
    """
    reg = load_registry()
    unit = next(u for u in reg if u["unit_id"] == unit_id)
    meta = json.loads((Path(treat_dir) / "replay_meta.json").read_text())
    targets, wins = meta["target_cells"], meta["win_cells"]
    t, c = _pass_rates(Path(treat_dir), targets + wins), \
        _pass_rates(Path(ctrl_dir), targets + wins)

    def delta(group):
        d = []
        for s in group:
            tv, cv = t.get(s, []), c.get(s, [])
            if tv and cv:
                d.append(sum(tv) / len(tv) - sum(cv) / len(cv))
        return (sum(d) / len(d) * 100) if d else 0.0, len(d)

    tg, nt = delta(targets)
    wg, nw = delta(wins)
    verdict = "dev-passed" if (tg >= 8.0 and wg >= -3.0) else "rejected"
    if tier == "gapcheck" and unit["status"] == "dev-passed":
        verdict = "promoted" if (tg >= 5.0 and wg >= -3.0) else "rejected"
    unit["status"] = verdict
    unit["stats"][f"{tier}"] = {"target_gain_pp": round(tg, 1),
                                "win_delta_pp": round(wg, 1),
                                "n_targets": nt, "n_wins": nw}
    REGISTRY.write_text("\n".join(json.dumps(u, ensure_ascii=False)
                                  for u in reg) + "\n")
    print(f"{unit_id} [{tier}] target_gain={tg:+.1f}pp win_delta={wg:+.1f}pp "
          f"-> {verdict.upper()}")


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
    pp = sub.add_parser("propose")
    pp.add_argument("--cluster", required=True)
    pp.add_argument("--n-examples", type=int, default=3)
    jp = sub.add_parser("judge")
    jp.add_argument("--unit", required=True)
    jp.add_argument("--treat-dir", required=True)
    jp.add_argument("--ctrl-dir", required=True)
    jp.add_argument("--tier", choices=["dev40", "gapcheck"], required=True)
    args = ap.parse_args()

    if args.cmd == "cluster":
        cmd_cluster(args.runs)
    elif args.cmd == "register":
        u = register_unit(args.asset, args.text, args.trigger,
                          {"cluster_id": args.cluster})
        print(f"registered {u['unit_id']}")
    elif args.cmd == "replay":
        cmd_replay(args.unit, args.base, args.tag)
    elif args.cmd == "propose":
        cmd_propose(args.cluster, args.n_examples)
    elif args.cmd == "judge":
        cmd_judge(args.unit, args.treat_dir, args.ctrl_dir, args.tier)
    elif args.cmd == "status":
        cmd_status()


if __name__ == "__main__":
    main()
