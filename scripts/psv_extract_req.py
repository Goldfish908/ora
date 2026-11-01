#!/usr/bin/env python3
"""Phase B: extract a structured requirement ledger from each problem text.

One LLM call per instance (thinking off), cached to
runs/presolve/req_ledgers.jsonl. The ledger uses a canonical requirement-type
enum so the Phase-C diff can be deterministic. The extractor is also asked to
list requirements it believes are conventionally implied but NOT stated in the
text (hidden-convention probe, cf. design doc section 6.5).

Usage (from /home/hewj13/wm/ora):
    source ~/.leagent_env
    python3 scripts/psv_extract_req.py --limit 2     # smoke
    python3 scripts/psv_extract_req.py               # all 190
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402

DATA = ROOT / "data" / "m1_retailopt" / "retailopt_190.jsonl"
OUT = ROOT / "runs" / "presolve" / "req_ledgers.jsonl"

REQ_TYPES = (
    "inventory_init (starting inventory pinned, e.g. to zero or given stock)",
    "inventory_balance / fresh_inflow (production arrival, transshipment net, returns)",
    "aging (inventory by remaining life carried across periods)",
    "waste_flow (expired inventory discarded)",
    "availability (sales cannot exceed usable stock, e.g. FIFO life>=2)",
    "demand_fulfillment (demand conservation: served + substituted + lost = demand; lost penalized)",
    "production_capacity (aggregate capacity per product per period)",
    "order_lead_time (orders arrive after lead_time; orders before period 1 are zero)",
    "labor_capacity", "cold_storage_capacity",
    "moq (minimum order quantity)", "pack_size (order multiples)",
    "budget_per_period", "waste_limit",
    "transshipment_arcs (flow only on declared trans_edges)",
    "substitution_arcs (flow only on declared sub_edges; substitution demand semantics)",
    "returns_flow (fraction of last-period sales returns as stock)",
    "nonnegativity",
    "objective_terms (all cost/revenue components)",
    "other",
)

PROMPT = """You are building a PRE-SOLVE requirement checklist for an optimization
modeling agent. Read the problem statement and extract every requirement the
mathematical model MUST implement, as a structured ledger.

Rules:
- Use ONLY these requirement types: {types}
- Each requirement: id (R1,R2,...), type (short key before any parenthesis),
  subject (variables/sets involved, compact), sense (==, <=, >=, or n/a),
  detail (one line, instance-specific numbers when visible),
  source_span (short verbatim quote from the statement).
- Be COMPLETE on hard constraints; skip solver/output-format instructions.
- Additionally list `hidden_conventions`: requirements a competent modeler
  would assume but the text never states (e.g. value of starting inventory).
  If none, use [].

Problem statement:
{problem}

Output ONLY the JSON object:
{{"requirements": [...], "hidden_conventions": [...]}}"""


def extract_one(scen: str, problem: str) -> dict:
    prompt = PROMPT.replace("{types", "{types").format(
        types="\n".join(f"- {t}" for t in REQ_TYPES), problem=problem)
    t0 = time.time()
    resp = llm_mod.chat(
        [{"role": "user", "content": prompt}],
        max_tokens=8192, temperature=0.0,
        extra={"chat_template_kwargs": {"enable_thinking": False}},
    )
    txt = resp["content"].strip()
    if txt.startswith("```"):
        txt = txt.split("```")[1]
        if txt.startswith("json"):
            txt = txt[4:]
    try:
        ledger = json.loads(txt)
        err = None
    except json.JSONDecodeError as e:
        ledger = None
        err = f"json_decode: {e}"
    return {"scenario_id": scen, "ledger": ledger, "error": err,
            "latency_s": round(time.time() - t0, 1),
            "finish_reason": resp.get("finish_reason")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(DATA)]
    done = set()
    if OUT.exists():
        for l in open(OUT):
            r = json.loads(l)
            if r.get("ledger"):
                done.add(r["scenario_id"])
    todo = [r for r in rows if r["scenario_id"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"todo={len(todo)} cached={len(done)}", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a") as f:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for res in ex.map(lambda r: extract_one(r["scenario_id"], r["prompt_full"]), todo):
                f.write(json.dumps(res) + "\n")
                f.flush()
                ok = "ok" if res["ledger"] else f"ERR {res['error']}"
                print(f"{res['scenario_id']}: {ok} {res['latency_s']}s", flush=True)


if __name__ == "__main__":
    main()
