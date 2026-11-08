#!/usr/bin/env python3
"""P13: instrumented active judge for IndustryOR — the architecture-valid form.

The first IndustryOR active run (p11) forced the judge into RE-DERIVATION
(re-solve from scratch), which failed: 18/47 misses were correlated errors
(same model re-derives the same wrong optimum). The architecture-valid form
needs the agent's variable-level solution, which p11 lacked.

Stage 0 (local, deterministic): execute the agent's own pyscipopt code with a
  generic epilogue that dumps ALL variable values to solution.json.
Stage 1-3 (judge): same judge-writes-checks flow as p10, but the check script
  reads solution.json and takes constants from the problem text (no data.json
  exists for IndustryOR — parsing constants from the text IS the audit).

One-shot discipline: IndustryOR is the untouched validation set; this script
is run once, no prompt iteration against its results.
"""
from __future__ import annotations

import argparse
import json
import os
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
SANDBOX = ROOT / "work" / "judge_data" / "ior_sandbox"

DECIDER_TEMPLATE = """You are auditing an AI agent's optimization solution for semantic validity.

[PROBLEM]
{prompt}

[AGENT'S MODEL CODE]
```python
{code}
```

The agent reported objective = {objective}.

You wrote and ran the following check script against the agent's dumped variable values:

[CHECK SCRIPT]
```python
{script}
```

[CHECK OUTPUT]
```
{output}
```

Classify each FAIL before counting it:
(a) CHECK MALFUNCTION — disregard: recomputed values that are all zero / empty (variable-name or parsing bugs), parse errors, crashes, or checks whose evidence is inconsistent with the solution dump's actual structure.
(b) PREMISE MISMATCH — disregard: the check assumes something the problem does not require.
(c) GENUINE VIOLATION — counts: detailed numeric evidence consistent with the problem's constants.

Declare INVALID only if at least one genuine (c) violation exists. When in doubt, or when checks crashed / are inapplicable, declare VALID (fail-open).
End with exactly one final line:
VERDICT: VALID
or
VERDICT: INVALID"""

EPILOGUE = """

# --- instrumentation epilogue (appended by p13) ---
import json as _json
from pyscipopt import Model as _Model
_mods = [v for v in list(globals().values()) if isinstance(v, _Model)]
if _mods:
    _m = _mods[0]
    if _m.getNSols() == 0:
        try:
            _m.optimize()
        except Exception:
            pass
    _sol = {}
    if _m.getNSols() > 0:
        _sol = {v.name: _m.getVal(v) for v in _m.getVars()}
        _out = {"objective": _m.getObjVal(), "status": str(_m.getStatus()), "vars": _sol}
    else:
        _out = {"objective": None, "status": str(_m.getStatus()), "vars": {}}
    with open("solution.json", "w") as _f:
        _json.dump(_out, _f)
"""

PLANNER_PROMPT = """You are auditing an optimization solution for SEMANTIC validity with respect to the problem's business meaning.

[PROBLEM]
{prompt}

[AGENT'S MODEL CODE]
```python
{code}
```

The agent's code was executed; every decision variable's value was dumped to `solution.json` in the current working directory:
{{"objective": float, "status": str, "vars": {{"var_name": value, ...}}}}
Variable names follow the agent's naming (see the code). {nvar} variables dumped; sample names: {sample_vars}

Write a Python script that loads `solution.json` and verifies the solution against the problem statement:
- Silently enumerate EVERY requirement the problem states (constraints, bounds, integrality, objective definition), then write at least one check per requirement.
- Take constants from the problem text / the agent's code (verify they match!); do not assume.
- Print exactly one line per check: "CHECK <name>: PASS <evidence>" or "CHECK <name>: FAIL <evidence with numbers>".
- Also verify the reported objective equals the objective recomputed from the dumped variable values and the problem's cost coefficients.
- Runtime < 20s. Print nothing else.
Output ONLY the Python code in a single ```python fenced block."""


def instrument(c: dict, timeout: int = 90) -> dict:
    """Stage 0: run agent code + epilogue, harvest solution.json."""
    key = f"industryor_{c['arm']}_{c['id']}"
    with tempfile.TemporaryDirectory() as td:
        py = Path(td) / "agent_code.py"
        py.write_text(c["code"] + EPILOGUE)
        try:
            p = subprocess.run([sys.executable, "agent_code.py"], cwd=td,
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"key": key, "ok": False, "err": "timeout"}
        sol_p = Path(td) / "solution.json"
        if not sol_p.exists():
            return {"key": key, "ok": False, "err": (p.stderr or "no solution.json")[-200:]}
        sol = json.loads(sol_p.read_text())
        out_dir = SANDBOX / key
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "solution.json").write_text(json.dumps(sol))
        return {"key": key, "ok": True, "nvars": len(sol.get("vars") or {}),
                "objective": sol.get("objective")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "work" / "judge_data" / "active_ior2.jsonl"))
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--max-tokens", type=int, default=12288)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-instrument", action="store_true")
    args = ap.parse_args()

    cells = [json.loads(l) for l in CELLS.read_text().splitlines()]
    if args.limit:
        cells = cells[: args.limit]

    # stage 0
    if not args.skip_instrument:
        ok = fail = 0
        with ThreadPoolExecutor(max_workers=12) as ex:
            for res in ex.map(instrument, cells):
                ok += res["ok"]
                fail += (not res["ok"])
        print(f"instrumented: {ok} ok, {fail} fail")

    base_url = os.environ["ORA_LLM_BASE_URL"]
    api_key = os.environ["ORA_LLM_API_KEY"]
    model = os.environ.get("ORA_LLM_MODEL", "Qwen3_8-27B")
    insecure = os.environ.get("ORA_LLM_INSECURE") == "1"

    out_path = Path(args.out)
    done = set()
    if out_path.exists():
        done = {json.loads(l)["key"] for l in out_path.read_text().splitlines()
                if not json.loads(l).get("error")}

    def one(c):
        key = f"industryor_{c['arm']}_{c['id']}"
        if key in done:
            return None
        sol_p = SANDBOX / key / "solution.json"
        if not sol_p.exists():
            return {"key": key, "wrong": bool(c["wrong"]), "verdict": None,
                    "error": "no_instrument"}
        sol = json.loads(sol_p.read_text())
        varnames = list((sol.get("vars") or {}).keys())
        r1 = call(PLANNER_PROMPT.format(
            prompt=(c.get("prompt") or "")[:6000],
            code=(c.get("code") or "")[:4000],
            nvar=len(varnames),
            sample_vars=", ".join(varnames[:8])), model=model,
            base_url=base_url, api_key=api_key, insecure=insecure,
            max_tokens=args.max_tokens, thinking=False)
        script = extract_code(r1["content"])
        if not script:
            return {"key": key, "wrong": bool(c["wrong"]), "verdict": None,
                    "error": "no_script"}
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "solution.json").write_text(json.dumps(sol))
            (Path(td) / "check.py").write_text(script)
            try:
                p = subprocess.run([sys.executable, "check.py"], cwd=td,
                                   capture_output=True, text=True, timeout=30)
                output = ((p.stdout or "") + ("\n[stderr]\n" + p.stderr[-600:] if p.returncode else "")).strip()[:4000]
            except subprocess.TimeoutExpired:
                output = "[TIMEOUT]"
        r2 = call(DECIDER_TEMPLATE.format(
            prompt=(c.get("prompt") or "")[:6000],
            code=(c.get("code") or "")[:4000],
            objective=c.get("objective"), script=script, output=output),
            model=model, base_url=base_url, api_key=api_key, insecure=insecure,
            max_tokens=args.max_tokens, thinking=False)
        return {"key": key, "wrong": bool(c["wrong"]),
                "verdict": parse_verdict(r2["content"]),
                "check_output": output[:1200],
                "decider_tail": r2["content"][-300:],
                "latency_s": r1["latency_s"] + r2["latency_s"]}

    todo = [c for c in cells if f"industryor_{c['arm']}_{c['id']}" not in done]
    n, t0 = 0, time.time()
    with out_path.open("a") as out, ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(one, c) for c in todo]
        for fut in as_completed(futs):
            r = fut.result()
            if r is None:
                continue
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
