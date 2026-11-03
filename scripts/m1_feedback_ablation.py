#!/usr/bin/env python3
"""A3 ablation: does attaching the relevant semantic convention to witness
feedback improve repair of hard phantom cells?

Population: combo3 first-trajectory residuals whose final state is
witness_infeasible (63 scenarios — plain feedback already failed on them
in up to 3 loop rounds, so any fix is signal; a fresh plain-feedback arm
controls for sampling luck).

Arms (1 LLM repair call + execute + witness + grade each):
  plain    — feedback_msg("witness_infeasible", rec) verbatim
  enriched — same + the semantic convention clauses mapped to the fired rules

Usage:
  python3 scripts/m1_feedback_ablation.py [--workers 6]
"""
from __future__ import annotations

import argparse, glob, json, os, re, sys, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod
from scripts.m1_pilot import (SCHEMA_PRELUDE, SCIP_OUTPUT_FORMAT_SOL,
                              adapt_prompt_schema, extract_code, run_code,
                              run_witness, grade, DATA)
from scripts.m1_feedback import feedback_msg

OUT = ROOT / "runs/m1_feedback_ablation"
CONVENTIONS = (ROOT / "configs/conventions_priors_v0.3.txt").read_text().strip()
SEM = (ROOT / "configs/semantic_priors_v0.1.txt").read_text().strip()
SEM_CLAUSES = re.split(r"\n(?=\d+\.\s)", SEM)
HEADER, CLAUSES = SEM_CLAUSES[0], SEM_CLAUSES[1:]

RULE2CLAUSE = {
    "C-DEMAND": [1, 2, 3, 4], "C-INIT": [6], "C-INFLOW": [3, 5],
    "C-AGING": [5], "C-AVAIL": [3], "C-OBJ": [5],
    "C-PRODCAP": [5], "C-STORAGE": [5], "C-MOQ": [5], "C-PACK": [5],
    "C-BUDGET": [5], "C-WASTELIMIT": [5], "C-LABOR": [5],
    "C-NONNEG": [4], "C-XEDGE": [3, 5], "C-XNET": [3, 5],
}
DEFAULT_CLAUSES = [2, 5]


def load_rows():
    return {r["scenario_id"]: r
            for r in map(json.loads, DATA.read_text().splitlines())}


def residuals() -> dict:
    """combo3 first-trajectory, final state witness_infeasible."""
    recs: dict[str, dict] = {}
    for fp in sorted(glob.glob(str(ROOT / "runs/m1_pilot_priors3/m1_pilot_schema_sol_p3_v*.jsonl"))):
        for line in open(fp):
            r = json.loads(line)
            recs.setdefault(r["scenario_id"], {})[1] = r
    for fp in sorted(glob.glob(str(ROOT / "runs/m1_presolve/m1_presolve_combo3_v*.jsonl"))):
        for line in open(fp):
            r = json.loads(line)
            recs.setdefault(r["scenario_id"], {})[r.get("round", 0)] = r
    out = {}
    for sid, rr in recs.items():
        last = rr[max(rr)]
        ts = last.get("true_success")
        if ts is None:
            ts = (last.get("witness") == "feasible"
                  and last.get("grade") == "match")
        if not ts and last.get("witness") == "infeasible":
            out[sid] = last
    return out


def last_code(sid: str, rnd: int) -> str | None:
    var = sid.rsplit("_", 1)[1]
    if rnd == 1:
        sb = (ROOT / f"runs/m1_pilot_priors3/sandbox/"
              f"m1_pilot_schema_sol_p3_{var}__{sid}__on/gen.py")
    else:
        sb = (ROOT / f"runs/m1_presolve/sandbox/"
              f"psv_combo3_{var}__{sid}__on__r{rnd}/gen.py")
    if not sb.exists():
        cands = sorted((ROOT / "runs/m1_presolve/sandbox").glob(
            f"psv_combo3_*__{sid}__on__r{rnd}/gen.py"))
        sb = cands[0] if cands else sb
    return sb.read_text().removeprefix(SCHEMA_PRELUDE) if sb.exists() else None


def enriched_feedback(rec: dict) -> str:
    base = feedback_msg("witness_infeasible", rec)
    rules = rec.get("witness_rules") or []
    idxs: list[int] = []
    for rule in rules:
        for i in RULE2CLAUSE.get(rule, []):
            if i not in idxs:
                idxs.append(i)
    if not idxs:
        idxs = DEFAULT_CLAUSES
    picked = "\n\n".join(CLAUSES[i - 1] for i in idxs)
    return (base + "\n\nReminder — the EXACT semantics your model must "
            "satisfy (read before rewriting):\n\n" + picked)


def one_attempt(sid: str, rec: dict, arm: str, rows: dict) -> dict:
    rnd = rec.get("round", 1)
    code = last_code(sid, rnd)
    row = rows[sid]
    prompt = CONVENTIONS + "\n\n" + adapt_prompt_schema(
        row["prompt_schema"], SCIP_OUTPUT_FORMAT_SOL)
    fb = (feedback_msg("witness_infeasible", rec) if arm == "plain"
          else enriched_feedback(rec))
    msgs = [{"role": "user", "content": prompt},
            {"role": "assistant", "content": code or "# (code unavailable)"},
            {"role": "user", "content": fb}]
    cfg = llm_mod.load_config()
    t0 = time.time()
    try:
        resp = llm_mod.chat(msgs, max_tokens=32768, temperature=0.6,
                            extra={"reasoning_effort": "medium"}, config=cfg)
        text = resp.get("content") or ""
    except Exception as e:
        return {"scenario_id": sid, "arm": arm, "llm_error": str(e)[:200]}
    new_code = extract_code(text)
    sandbox = OUT / "sandbox" / f"{arm}__{sid}"
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "data.json").write_text(row["data"])
    res = run_code(SCHEMA_PRELUDE + new_code, sandbox)
    out = {"scenario_id": sid, "arm": arm, "round_base": rnd,
           "llm_s": round(time.time() - t0, 1), **res}
    out.update(run_witness(row, sandbox))
    out["grade"] = grade(out.get("objective"), rec.get("reference_objective"),
                         out.get("solver_status"))
    ts = (out.get("witness") == "feasible" and out.get("grade") == "match")
    out["true_success"] = ts
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    (OUT / "sandbox").mkdir(exist_ok=True)
    rows = load_rows()
    res = residuals()
    sids = sorted(res)[: args.limit or None]
    print(f"residual witness_infeasible cells: {len(res)}, running {len(sids)}")
    tasks = [(sid, res[sid], arm) for sid in sids
             for arm in ("plain", "enriched")]
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(one_attempt, sid, rec, arm, rows)
                for sid, rec, arm in tasks]
        done = 0
        for f in futs:
            r = f.result()
            with (OUT / "ablation.jsonl").open("a") as fp:
                fp.write(json.dumps(r) + "\n")
            done += 1
            if done % 10 == 0:
                print(f"{done}/{len(tasks)}")
    # report
    stat = Counter()
    for line in (OUT / "ablation.jsonl").open():
        r = json.loads(line)
        if r["scenario_id"] in set(sids):
            stat[(r["arm"], bool(r.get("true_success")))] += 1
    for arm in ("plain", "enriched"):
        ok = stat[(arm, True)]; tot = ok + stat[(arm, False)]
        print(f"{arm}: fixed {ok}/{tot} = {ok/max(tot,1):.1%}")


if __name__ == "__main__":
    main()
