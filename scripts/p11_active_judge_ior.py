#!/usr/bin/env python3
"""P11: active-perception judge for IndustryOR — independent re-derivation.

IndustryOR cells carry no solution.json/data.json — only prompt, model code,
and the reported objective. The active-perception idea therefore takes its
purest form: the judge writes its OWN pyscipopt model from the problem
statement, solves it (SCIP, deterministic), and compares the optimum against
the reported objective. The LLM decider then judges whether a mismatch is a
genuine semantic violation or the judge's own modeling error (fail-open).

Cells: runs/industryor/industryor_judge_cells.jsonl (240; wrong = objective
mismatch vs reference). Same cells as the trained-judge / zero-shot arms.

Usage: same ORA_LLM_* env as p9/p10.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.p5_judge_rs import parse_verdict  # noqa: E402
from scripts.p10_active_judge import call, extract_code  # noqa: E402

CELLS = ROOT / "runs" / "industryor" / "industryor_judge_cells.jsonl"

PLANNER_PROMPT = """You are independently re-solving an operations-research problem to audit an AI agent's claimed answer.

[PROBLEM]
{prompt}

An AI agent modeled this problem and claims the optimal objective value is:
REPORTED_OBJECTIVE = {objective}

Write a self-contained Python script using pyscipopt (from pyscipopt import Model) that models the problem FROM THE PROBLEM STATEMENT ALONE and solves it. Rules:
- Build your own model; do not trust or import the agent's code.
- Print exactly one final line: "MY_OBJECTIVE: <value>" (the optimal objective you found), or "MY_STATUS: INFEASIBLE" / "MY_STATUS: ERROR <reason>".
- Suppress solver output (model.hideOutput()). Keep it fast (<30s).
Output ONLY the Python code in a single ```python fenced block."""

DECIDER_TEMPLATE = """You are auditing an AI agent's optimization answer by independent re-derivation.

[PROBLEM]
{prompt}

[AGENT'S MODEL CODE]
```python
{code}
```

The agent reported objective = {objective}.

You independently modeled and solved the same problem. Your script:

```python
{script}
```

Its output:
```
{output}
```

Compare your optimum with the reported objective (relative tolerance ~1e-3):
- If they match, the answer is consistent — VALID.
- If they mismatch, decide whether the AGENT's model is wrong (it violates/ignores something the problem states) or YOUR re-derivation is wrong (you missed a constraint, misread a parameter, used wrong units). When in doubt, or when your script failed to produce an objective, declare VALID (fail-open).
End with exactly one final line:
VERDICT: VALID
or
VERDICT: INVALID"""


def run_script(script: str, timeout: int = 90) -> str:
    with tempfile.TemporaryDirectory() as td:
        py = Path(td) / "resolve.py"
        py.write_text(script)
        try:
            p = subprocess.run([sys.executable, "resolve.py"], cwd=td,
                               capture_output=True, text=True, timeout=timeout)
            out = (p.stdout + ("\n[stderr]\n" + p.stderr[-800:] if p.returncode else "")).strip()
            return (out or "(no output)")[:2000]
        except subprocess.TimeoutExpired:
            return "[TIMEOUT]"
        except Exception as e:  # noqa: BLE001
            return f"[EXEC ERROR] {e}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "work" / "judge_data" / "active_industryor.jsonl"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=12288)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cells = [json.loads(l) for l in CELLS.read_text().splitlines()]
    out_path = Path(args.out)
    done = set()
    if out_path.exists():
        done = {json.loads(l)["key"] for l in out_path.read_text().splitlines()
                if not json.loads(l).get("error")}
    todo = [c for c in cells if f"industryor_{c['arm']}_{c['id']}" not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"cells {len(cells)}, pending {len(todo)}")

    base_url = os.environ["ORA_LLM_BASE_URL"]
    api_key = os.environ["ORA_LLM_API_KEY"]
    model = os.environ.get("ORA_LLM_MODEL", "Qwen3_8-27B")
    insecure = os.environ.get("ORA_LLM_INSECURE") == "1"

    def one(c):
        key = f"industryor_{c['arm']}_{c['id']}"
        if c.get("objective") is None:
            return {"key": key, "wrong": bool(c["wrong"]), "verdict": None,
                    "error": "no_objective"}
        r1 = call(PLANNER_PROMPT.format(prompt=(c.get("prompt") or "")[:6000],
                                        objective=c["objective"]),
                  model=model, base_url=base_url, api_key=api_key,
                  insecure=insecure, max_tokens=args.max_tokens, thinking=False)
        script = extract_code(r1["content"])
        if not script:
            return {"key": key, "wrong": bool(c["wrong"]), "verdict": None,
                    "error": "no_script"}
        output = run_script(script)
        if "MY_OBJECTIVE" not in output:
            fix = call(
                "The script below failed to print MY_OBJECTIVE. Output:\n```\n"
                + output + "\n```\nScript:\n```python\n" + script
                + "\n```\nFix it and output ONLY the corrected ```python block.",
                model=model, base_url=base_url, api_key=api_key,
                insecure=insecure, max_tokens=args.max_tokens, thinking=False)
            fixed = extract_code(fix["content"])
            if fixed:
                script = fixed
                output = run_script(script)
        r2 = call(DECIDER_TEMPLATE.format(prompt=(c.get("prompt") or "")[:6000],
                                          code=(c.get("code") or "")[:4000],
                                          objective=c["objective"],
                                          script=script, output=output),
                  model=model, base_url=base_url, api_key=api_key,
                  insecure=insecure, max_tokens=args.max_tokens, thinking=False)
        return {"key": key, "wrong": bool(c["wrong"]),
                "verdict": parse_verdict(r2["content"]),
                "resolve_output": output[:400],
                "decider_tail": r2["content"][-300:],
                "latency_s": r1["latency_s"] + r2["latency_s"]}

    n, t0 = 0, time.time()
    with out_path.open("a") as out, ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(one, c) for c in todo]
        for fut in as_completed(futs):
            r = fut.result()
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
            out.flush()
            n += 1
            if n % 20 == 0 or n == len(todo):
                print(f"[{n}/{len(todo)}] {time.time()-t0:.0f}s", flush=True)

    rows = [json.loads(l) for l in out_path.read_text().splitlines()]
    tp = sum(1 for r in rows if r["wrong"] and r["verdict"] == "INVALID")
    fn = sum(1 for r in rows if r["wrong"] and r["verdict"] != "INVALID")
    fp = sum(1 for r in rows if not r["wrong"] and r["verdict"] == "INVALID")
    tn = sum(1 for r in rows if not r["wrong"] and r["verdict"] != "INVALID")
    unp = sum(1 for r in rows if r["verdict"] is None)
    print(json.dumps({"n": len(rows), "tp": tp, "fn": fn, "fp": fp, "tn": tn,
                      "unparsed": unp,
                      "detection": round(tp / max(tp + fn, 1), 4),
                      "false_positive": round(fp / max(fp + tn, 1), 4)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
