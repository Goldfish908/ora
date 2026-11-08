#!/usr/bin/env python3
"""P10: active-perception judge (judge-writes-checks) — architecture pilot.

Stage 1: judge reads [PROBLEM]/[DATA]/[MODEL CODE]/[SOLUTION digest] and
         WRITES a Python check script (what to verify, decided by the model).
Stage 2: script runs locally against the cell's solution.json + data.json
         (deterministic execution — the judge's "hands").
Stage 3: judge reads its script + the execution output and gives VERDICT.

Hypothesis: cross-family detection is bounded by the static digest channel;
letting the judge compute its own checks should recover C-DEMAND-class
violations that the F1-F4-era digest cannot see. Zero-shot Qwen27B pilot on
the F5-F8 48 cells (trained judge: 14.7% detection; zero-shot direct: 20.6%).

Usage: same ORA_LLM_* env as p9.  --limit N for smoke tests.
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


def call(msg: str, *, model: str, base_url: str, api_key: str, insecure: bool,
         max_tokens: int, thinking: bool = False) -> dict:
    """call_llm variant with thinking toggleable: for the active judge the
    heavy lifting is done by deterministic script execution, so thinking only
    burns the token budget (12K tokens vanished into reasoning with zero
    content in the smoke test)."""
    import ssl
    import urllib.request
    body = {
        "model": model,
        "messages": [{"role": "user", "content": msg}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"}, method="POST")
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    m = (payload.get("choices") or [{}])[0]
    msg_out = m.get("message") or {}
    return {"content": msg_out.get("content") or "",
            "latency_s": round(time.monotonic() - t0, 2),
            "finish_reason": m.get("finish_reason")}

SCENARIOS = ROOT / "data" / "m1_retailopt" / "f5f8_heldout90.jsonl"
RUN = ROOT / "runs" / "evo" / "gen3_full190"

PLANNER_PROMPT = """You are auditing an optimization solution for SEMANTIC validity with respect to the problem's business meaning.

{context}

The numeric digest above only covers a few known signal types. To check what actually matters for THIS problem, write a Python script that loads `solution.json` and `data.json` from the current working directory and verifies the solution against the problem statement.

- solution.json: maps variable names to dicts of "idx|idx|..." -> numeric value (solver output).
- data.json schema (types, exact): {schema}
- solution.json: {{"objective": float, var_name: {{"idx|idx|...": value}} }}; typical vars: Q (order), sales, I (inventory), W (waste), lost (lost sales), sub, X.

Start your script with this canonical loader (verbatim) and build checks on top:
```python
import json
sol = json.load(open("solution.json"))
data = json.load(open("data.json"))
def items(var):
    d = sol.get(var) or {{}}
    return [(tuple(k.split("|")), float(v)) for k, v in d.items()
            if isinstance(v, (int, float)) and abs(v) > 1e-9]
```
Note: demand may be composite (e.g. demand_curve[p][t] x demand_share[l]) — compute it per the schema, do not assume a plain "demand" key.
- First, silently enumerate EVERY requirement the problem text states (service level / fill-rate targets, budget caps, labor, capacity, shelf life, MOQ, substitution rules, network restrictions...). Then write at least one check per stated requirement.
- Check what MUST hold for this problem: demand fulfillment or service-level targets vs data, inventory balance, capacity/labor/budget limits, parameter consistency (MOQ, shelf life, lead time), objective consistency.
- Objective consistency is FRAGILE: only include it if your recomputation enumerates EVERY cost term present in data["costs"] (and any transport/substitution/labor costs in data). An objective mismatch from an incomplete recomputation is a false alarm.
- Read actual values from data.json; do not assume constants.
- Print exactly one line per check: "CHECK <name>: PASS <evidence>" or "CHECK <name>: FAIL <evidence with numbers>".
- Runtime must be well under 20 seconds. Print nothing else.

Output ONLY the Python code in a single ```python fenced block."""

REPAIR_TEMPLATE = """The following check script crashed. Output:

```
{output}
```

Script:
```python
{script}
```

Fix the crash (defensive coding: validate list/dict shapes before indexing; wrap risky checks in try/except and print "CHECK <name>: SKIP <reason>" on failure). Keep the same checks otherwise. Output ONLY the fixed Python code in a single ```python fenced block."""

DECIDER_TEMPLATE = """{context}

You wrote and ran the following check script against the instance data and the solver's solution:

[CHECK SCRIPT]
```python
{script}
```

[CHECK OUTPUT]
```
{output}
```

Classify each FAIL before counting it:
(a) CHECK MALFUNCTION — disregard: recomputed values that are all zero / empty (key-format or parsing bugs), parse errors, crashes, checks whose evidence is inconsistent with the data's actual structure, or an objective-recomputation FAIL whose script did NOT enumerate every cost term in data["costs"] (incomplete cost model => false mismatch).
(b) PREMISE MISMATCH — disregard: the check assumes something the problem does not require (e.g. full demand fulfillment when the problem allows lost sales or substitution).
(c) GENUINE VIOLATION — counts: detailed per-entry evidence with plausible magnitudes consistent with data.json. A FAIL that lists concrete violating entries (product/location/period/value tuples with non-zero numbers comparable to the demand scale) is genuine evidence, NOT a malfunction. Malfunction looks like: all-zero recomputation, empty outputs, tracebacks, "could not parse" errors.

Declare INVALID only if at least one genuine (c) violation exists. When everything fails by (a)/(b) or checks are inapplicable, declare VALID (fail-open).
Then end with exactly one final line:
VERDICT: VALID
or
VERDICT: INVALID"""


def extract_code(text: str) -> str | None:
    m = re.findall(r"```python\s*\n(.*?)```", text or "", re.S)
    return m[-1] if m else None


def run_check(script: str, workdir: Path, timeout: int = 30) -> str:
    py = workdir / "check.py"
    py.write_text(script)
    try:
        p = subprocess.run([sys.executable, "check.py"], cwd=workdir,
                           capture_output=True, text=True, timeout=timeout)
        out = (p.stdout + ("\n[stderr]\n" + p.stderr if p.stderr else "")).strip()
        return (out or "(no output)")[:4000]
    except subprocess.TimeoutExpired:
        return "[TIMEOUT after %ds]" % timeout
    except Exception as e:  # noqa: BLE001
        return f"[EXEC ERROR] {e}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default=str(ROOT / "work" / "judge_data" / "eval_f5f8.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "work" / "judge_data" / "active_f5f8.jsonl"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=12288)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    scen = {}
    for line in SCENARIOS.read_text().splitlines():
        r = json.loads(line)
        d = r.get("data")
        scen[r["scenario_id"]] = json.loads(d) if isinstance(d, str) else d

    cells = [json.loads(l) for l in open(args.eval)]
    out_path = Path(args.out)
    done = set()
    if out_path.exists():
        done = {json.loads(l)["key"] for l in out_path.read_text().splitlines()
                if not json.loads(l).get("error")}
    todo = [c for c in cells if c["key"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"cells {len(cells)}, pending {len(todo)}")

    base_url = os.environ["ORA_LLM_BASE_URL"]
    api_key = os.environ["ORA_LLM_API_KEY"]
    model = os.environ.get("ORA_LLM_MODEL", "Qwen3_8-27B")
    insecure = os.environ.get("ORA_LLM_INSECURE") == "1"

    def one(c):
        sid = c["key"].split("|")[0]
        box = RUN / "sandbox" / f"schema_sol__{sid}__on"
        sol_p, data = box / "solution.json", scen.get(sid)
        if not sol_p.exists() or data is None:
            return {"key": c["key"], "wrong": bool(c["wrong"]), "verdict": None,
                    "error": "missing artifacts"}
        ctx = c["user"]
        def _shape(x, depth=0):
            if isinstance(x, dict):
                if not x or depth >= 3:
                    return "dict"
                k0 = next(iter(x))
                return "{<%s>: %s}" % (k0, _shape(x[k0], depth + 1))
            if isinstance(x, list):
                return "list[%d] of %s" % (len(x), _shape(x[0], depth + 1) if x else "?")
            return type(x).__name__
        dkeys = "; ".join(f"{k}: {_shape(v)}" for k, v in data.items())
        # stage 1: plan checks
        r1 = call(PLANNER_PROMPT.format(context=ctx, schema=dkeys),
                  model=model, base_url=base_url, api_key=api_key,
                  insecure=insecure, max_tokens=args.max_tokens,
                  thinking=False)
        script = extract_code(r1["content"])
        if not script:
            return {"key": c["key"], "wrong": bool(c["wrong"]), "verdict": None,
                    "error": "no_script", "planner_tail": r1["content"][-300:]}
        # stage 2: deterministic execution (one repair round on crash)
        with tempfile.TemporaryDirectory() as td:
            wd = Path(td)
            (wd / "solution.json").write_text(sol_p.read_text())
            (wd / "data.json").write_text(json.dumps(data, ensure_ascii=False))
            output = run_check(script, wd)
            if "[stderr]" in output or "[EXEC ERROR]" in output or "[TIMEOUT" in output:
                fix = call(REPAIR_TEMPLATE.format(script=script, output=output),
                           model=model, base_url=base_url, api_key=api_key,
                           insecure=insecure, max_tokens=args.max_tokens,
                           thinking=False)
                fixed = extract_code(fix["content"])
                if fixed:
                    script = fixed
                    output = run_check(script, wd)
        # stage 3: decide
        r2 = call(DECIDER_TEMPLATE.format(context=ctx, script=script,
                                          output=output),
                  model=model, base_url=base_url, api_key=api_key,
                  insecure=insecure, max_tokens=args.max_tokens,
                  thinking=False)
        return {"key": c["key"], "wrong": bool(c["wrong"]),
                "verdict": parse_verdict(r2["content"]),
                "script_chars": len(script), "check_output": output[:1500],
                "decider_tail": r2["content"][-400:],
                "latency_s": r1["latency_s"] + r2["latency_s"],
                "error": r1.get("error") or r2.get("error")}

    n, t0 = 0, time.time()
    with out_path.open("a") as out, ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(one, c) for c in todo]
        for fut in as_completed(futs):
            r = fut.result()
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
            out.flush()
            n += 1
            if n % 8 == 0 or n == len(todo):
                print(f"[{n}/{len(todo)}] {time.time()-t0:.0f}s", flush=True)

    rows = [json.loads(l) for l in out_path.read_text().splitlines()]
    tp = sum(1 for r in rows if r["wrong"] and r["verdict"] == "INVALID")
    fn = sum(1 for r in rows if r["wrong"] and r["verdict"] != "INVALID")
    fp = sum(1 for r in rows if not r["wrong"] and r["verdict"] == "INVALID")
    tn = sum(1 for r in rows if not r["wrong"] and r["verdict"] != "INVALID")
    unparsed = sum(1 for r in rows if r["verdict"] is None)
    print(json.dumps({"n": len(rows), "tp": tp, "fn": fn, "fp": fp, "tn": tn,
                      "unparsed": unparsed,
                      "detection": round(tp / max(tp + fn, 1), 4),
                      "false_positive": round(fp / max(fp + tn, 1), 4)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
