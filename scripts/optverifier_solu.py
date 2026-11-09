#!/usr/bin/env python3
"""Opt-Verifier solution-side verification (arXiv 2605.29556, Sec 4.3)
reproduction — head-to-head against our deterministic witness on cells with
KNOWN ground truth:

  - phantom cells: final-round solutions our witness proved infeasible
    (deterministic re-computation). A correct detector must REJECT them.
  - clean cells: solutions our witness proved feasible + objective matches
    reference. A correct detector must ACCEPT them.

Pipeline per cell (faithful to the paper):
  D~ = SolInterp_Agent(x, D)      # interpret raw solution in problem context
  (com, cv) = SolEval_Agent(D, D~)  # binary validity score + comment

Usage:
  python3 scripts/optverifier_solu.py --out runs/optverifier/solu_head2head.jsonl
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from scripts.m1_pilot import DATA  # noqa: E402
from scripts.m1_feedback import failure_type  # noqa: E402

SOL_INTERP = """You are a solution interpreter for an optimization problem.
Below is the problem description and the numeric solution produced by a
solver (decision variables as sparse JSON tables).

Problem description:
{problem}

Numeric solution (solution.json):
{solution}

Translate this numeric solution into a clear natural-language description:
what is being produced/ordered/shipped/sold, in what quantities, where and
when. Point out the concrete numbers. Be factual and complete."""

SOL_EVAL = """You are a solution evaluation agent for optimization modeling.

Problem description:
{problem}

Interpreted solution:
{interp}

Scrutinize the interpreted solution for any logical or mathematical errors
with respect to the problem (e.g. conservation violations, capacity
overruns, selling more than available, violating shelf-life or MOQ rules,
inventory appearing from nowhere).
If the solution is valid, reply with exactly: VALID
Otherwise reply with: INVALID, then list each flaw you found."""


def chat(prompt: str, cfg, max_tokens=16384) -> str:
    resp = llm_mod.chat([{"role": "user", "content": prompt}],
                        max_tokens=max_tokens, temperature=0.6,
                        extra={"reasoning_effort": "medium"}, config=cfg)
    return resp.get("content") or ""


def final_states() -> dict:
    """C-arm final round per cell -> (record, sandbox solution path)."""
    best = {}
    for f in glob.glob(str(ROOT / "runs/m1_presolve/m1_presolve_memloop_*.jsonl")):
        for line in open(f):
            if not line.strip():
                continue
            r = json.loads(line)
            k = r["scenario_id"]
            if k not in best or r.get("round", 0) >= best[k].get("round", 0):
                best[k] = r
    out = {}
    for sid, r in best.items():
        var = sid.rsplit("_", 1)[-1]
        sb = (ROOT / "runs/m1_presolve/sandbox"
              / f"psv_memloop_{var}__{sid}__on__r{r.get('round', 1)}")
        sol = sb / "solution.json"
        if sol.exists():
            out[sid] = (r, sol)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-phantom", type=int, default=0,
                    help="0 = all phantom cells")
    ap.add_argument("--n-clean", type=int, default=20)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    ds = {json.loads(l)["scenario_id"]: json.loads(l)
          for l in DATA.read_text().splitlines() if l.strip()}
    fs = final_states()
    phantom, clean = [], []
    for sid, (r, sol) in sorted(fs.items()):
        ft = failure_type(r)
        if ft == "witness_infeasible":
            phantom.append(sid)
        elif ft is None:
            clean.append(sid)
    if args.n_phantom:
        phantom = phantom[: args.n_phantom]
    clean = clean[: args.n_clean]
    cells = [(s, "phantom") for s in phantom] + [(s, "clean") for s in clean]
    print(f"phantom={len(phantom)} clean={len(clean)}")

    cfg = llm_mod.load_config()
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.exists():
        for l in out_path.read_text().splitlines():
            if l.strip():
                done.add(json.loads(l)["scenario_id"])

    with out_path.open("a", encoding="utf-8") as fp:
        for sid, kind in cells:
            if sid in done:
                continue
            r, sol = fs[sid]
            problem = ds[sid]["prompt_schema"][:6000]
            sol_text = sol.read_text()[:8000]
            t0 = time.time()
            try:
                interp = chat(SOL_INTERP.format(problem=problem,
                                                solution=sol_text), cfg)
                verdict = chat(SOL_EVAL.format(problem=problem,
                                               interp=interp), cfg)
                llm_valid = verdict.strip().upper().startswith("VALID") \
                    and not verdict.strip().upper().startswith("INVALID")
                rec = {"scenario_id": sid, "kind": kind, "round": r["round"],
                       "witness": r.get("witness"),
                       "grade": r.get("grade"),
                       "llm_valid": llm_valid,
                       "eval_head": verdict.strip()[:300],
                       "elapsed_s": round(time.time() - t0, 1)}
            except Exception as e:
                rec = {"scenario_id": sid, "kind": kind,
                       "error": f"{type(e).__name__}: {e}"}
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fp.flush()
            print(f"[{sid}][{kind}] llm_valid={rec.get('llm_valid')} "
                  f"witness={rec.get('witness')}", flush=True)


if __name__ == "__main__":
    main()
