#!/usr/bin/env python3
"""Phase C: check each round-1 gen.py against its instance requirement ledger.

Per cell (380): the LLM gets the requirement ledger (Phase B) plus the
generated code and returns, per requirement, implemented / missing / wrong
with a MANDATORY code-span citation for 'implemented'. The BLOCK decision rule
is deterministic: any requirement not implemented-with-citation => BLOCK.

Usage (from /home/hewj13/wm/ora):
    source ~/.leagent_env
    python3 scripts/psv_check_code.py --limit 4     # smoke
    python3 scripts/psv_check_code.py               # all 380

Output: runs/presolve/code_checks.jsonl
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
PILOT = ROOT / "runs" / "m1_pilot"
REQ = ROOT / "runs" / "presolve" / "req_ledgers.jsonl"
OUT = ROOT / "runs" / "presolve" / "code_checks.jsonl"

PROMPT = """You are a pre-solve verifier for optimization modeling code.

Below is (1) a requirement ledger the model MUST implement, and (2) the
generated Python code (PySCIPOpt). For EACH requirement decide:
- "implemented": the code enforces it -- you MUST cite the exact code line(s)
  as evidence (verbatim substring).
- "missing": nothing in the code enforces it.
- "wrong": the code addresses it but with a visible defect (wrong index range,
  wrong sense, wrong data field). Explain in one line.

Do NOT judge mathematical elegance; only presence/correctness of enforcement.
Citation is MANDATORY for "implemented"; without a citation the verdict is
treated as missing.

Equivalence rules (do NOT flag these as wrong):
- Inventory initialization: only buckets with r < shelf_life must be pinned
  (to zero) at t=1. The fresh bucket (r = shelf_life) at t=1 is legitimately
  determined by period-1 production inflow; do not require it to be zero.
- Demand conservation written as served + lost >= demand is ACCEPTABLE when
  lost sales (or unmet demand) are penalized in the objective, because
  over-satisfaction cannot be optimal under minimization.

Requirement ledger:
{ledger}

Generated code:
```python
{code}
```

Output ONLY JSON:
{{"checks": [{{"id": "R1", "status": "implemented|missing|wrong",
"evidence": "<code line(s) or empty>", "note": "<one line or empty>"}}]}}"""


def load_code(scen: str, mode: str) -> str | None:
    for cand in (PILOT / "sandbox" / f"schema_sol__{scen}__{mode}" / "gen.py",
                 PILOT / "sandbox" / f"{scen}__{mode}" / "gen.py"):
        if cand.exists():
            return cand.read_text()
    return None


def check_one(scen: str, mode: str, ledger: dict, code: str) -> dict:
    # dedupe hidden conventions that merely restate an existing requirement
    covered = {q.get("type") for q in ledger["requirements"]}
    dup_kw = {"inventory_init": ("initial", "starting inventory",
                                 "start of period 1"),
              "demand_fulfillment": ("demand",),
              "returns_flow": ("return",)}
    hidden = []
    for h in ledger.get("hidden_conventions") or []:
        hl = h.lower()
        dup = any(t in covered and any(k in hl for k in kws)
                  for t, kws in dup_kw.items())
        if not dup:
            hidden.append(h)
    reqs = ledger["requirements"] + [
        {"id": f"H{i+1}", "type": "hidden_convention", "detail": h,
         "subject": "", "sense": ""}
        for i, h in enumerate(hidden)]
    ledger_txt = json.dumps(reqs, ensure_ascii=False, indent=1)
    prompt = PROMPT.replace("{ledger", "{ledger").format(
        ledger=ledger_txt, code=code)
    t0 = time.time()
    try:
        resp = llm_mod.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=8192, temperature=0.0,
            extra={"chat_template_kwargs": {"enable_thinking": False}},
        )
    except Exception as e:  # network/HTTP after retries: record, do not crash batch
        return {"scenario_id": scen, "thinking": mode, "checks": None,
                "error": f"llm: {type(e).__name__}: {e}", "latency_s": 0}
    txt = resp["content"].strip()
    if txt.startswith("```"):
        txt = txt.split("```")[1]
        if txt.startswith("json"):
            txt = txt[4:]
    try:
        out = json.loads(txt)
        checks = out.get("checks")
        err = None
    except json.JSONDecodeError as e:
        checks = None
        err = f"json_decode: {e}"
    return {"scenario_id": scen, "thinking": mode, "checks": checks,
            "error": err, "latency_s": round(time.time() - t0, 1),
            "finish_reason": resp.get("finish_reason")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    ledgers = {}
    for line in open(REQ):
        r = json.loads(line)
        if r.get("ledger"):
            ledgers[r["scenario_id"]] = r["ledger"]

    cells = []
    for line in open(DATA):
        row = json.loads(line)
        scen = row["scenario_id"]
        if scen not in ledgers:
            continue
        for mode in ("on", "off"):
            code = load_code(scen, mode)
            if code:
                cells.append((scen, mode, code))

    done = set()
    if OUT.exists():
        for l in open(OUT):
            r = json.loads(l)
            if r.get("checks"):
                done.add((r["scenario_id"], r["thinking"]))
    todo = [c for c in cells if (c[0], c[1]) not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"cells={len(cells)} todo={len(todo)} cached={len(done)}", flush=True)

    with open(OUT, "a") as f:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for res in ex.map(lambda c: check_one(c[0], c[1], ledgers[c[0]], c[2]), todo):
                f.write(json.dumps(res) + "\n")
                f.flush()
                ok = "ok" if res["checks"] else f"ERR {res['error']}"
                print(f"{res['scenario_id']}__{res['thinking']}: {ok} "
                      f"{res['latency_s']}s", flush=True)


if __name__ == "__main__":
    main()
