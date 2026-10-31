#!/usr/bin/env python3
"""M1 pilot (taskbook v1.1 §14.2 evidence group 2: natural generation).

Zero-shot natural generation on RetailOpt-190 with the MaaS qwen3.8-27B,
executed on the open-source stack (PySCIPOpt) instead of Gurobi. This is the
SCIP-adapted variant flagged by v1.1 §14.5: the [OUTPUT FORMAT]/[TASK] blocks
of prompt_full are mechanically rewritten from GurobiPy to PySCIPOpt; the
business description, data, and reference_objective are untouched. Scoring
does not re-run a reference solver — it compares the printed objective
against the dataset's reference_objective.

Usage (from /home/hewj13/wm/ora):
    source ~/.leagent_env
    python3 scripts/m1_pilot.py --limit 6          # smoke
    python3 scripts/m1_pilot.py --families F1 F6   # pick families

Results: runs/m1_pilot/m1_pilot.jsonl (one row per instance x mode).
Generated code is executed with the rl-env python (pyscipopt 4.3.0) in a
per-run sandbox dir under runs/m1_pilot/sandbox/.
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from m1_witness import f1 as witness_f1  # noqa: E402

DATA = ROOT / "data" / "m1_retailopt" / "retailopt_190.jsonl"
OUT_DIR = ROOT / "runs" / "m1_pilot"
EXEC_PYTHON = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"
EXEC_TIMEOUT_SEC = 620
SOLVER_TIME_LIMIT = 570
OBJ_REL_TOL = 1e-3

# Mechanical rewrite of the solver-specific blocks only (v1.1 §14.5).
SCIP_OUTPUT_FORMAT = f"""[OUTPUT FORMAT]
- Import: from pyscipopt import Model; import json
- Create the model: m = Model(); silence solver logs: m.hideOutput()
- Set a solver time limit: m.setRealParam("limits/time", {SOLVER_TIME_LIMIT})
- After m.optimize(), print at end:
  print(f"status: {{m.getStatus()}}")
  if m.getStatus() == "optimal":
      print(f"objective: {{m.getObjVal()}}")
- Output ONLY executable Python code. No markdown, no explanations.

[TASK]
Write a PySCIPOpt script that:"""

# schema_sol mode: the model must ALSO dump its decisions so a witness
# checker can re-verify every constraint instead of trusting the printed
# objective (motivation finding F2: objective-matching gives false success).
SCIP_OUTPUT_FORMAT_SOL = f"""[OUTPUT FORMAT]
- Import: from pyscipopt import Model; import json
- Create the model: m = Model(); silence solver logs: m.hideOutput()
- Set a solver time limit: m.setRealParam("limits/time", {SOLVER_TIME_LIMIT})
- After m.optimize(), print at end:
  print(f"status: {{m.getStatus()}}")
  if m.getStatus() == "optimal":
      print(f"objective: {{m.getObjVal()}}")
- When the status is optimal, ALSO write your decisions to solution.json.
  Sparse dict-of-dicts, ONLY nonzero entries, keys joined with "|":
    sol = {{"objective": float(m.getObjVal()),
           "Q": {{}}, "sales": {{}}, "I": {{}},
           "W": {{}}, "lost": {{}}, "sub": {{}}}}
    # Q:     "p|l|t"     order quantity, period t = 1..T
    # sales: "p|l|t|r"   sales out of the bucket with r periods of shelf
    #                    life remaining
    # I:     "p|l|t|r"   inventory at START of period t, r periods left
    # W:     "p|l|t"     expired waste
    # lost:  "p|l|t"     lost sales
    # sub:   "pf|pt|l|t" demand of pf served by pt (substitution)
    json.dump(sol, open("solution.json", "w"))
- Output ONLY executable Python code. No markdown, no explanations.

[TASK]
Write a PySCIPOpt script that:"""

_OUTPUT_RE = re.compile(r"\[OUTPUT FORMAT\].*?\[TASK\]\nWrite a \w+ script that:",
                        re.DOTALL)
# schema-mode prompts end the [TASK] header without a colon ("Write a GurobiPy
# script that models and solves this optimization problem.") — match the whole
# trailing line instead.
_OUTPUT_RE_SCHEMA = re.compile(
    r"\[OUTPUT FORMAT\].*?\[TASK\]\nWrite a \w+ script that[^\n]*",
    re.DOTALL)


def adapt_prompt(prompt_full: str) -> str:
    new, n = _OUTPUT_RE.subn(SCIP_OUTPUT_FORMAT, prompt_full)
    if n != 1:
        raise ValueError("prompt adaptation failed: OUTPUT FORMAT block "
                         f"matched {n} times")
    return new


def adapt_prompt_schema(prompt_schema: str,
                        fmt: str = SCIP_OUTPUT_FORMAT) -> str:
    """Schema-mode prompt: same OUTPUT FORMAT rewrite, plus neutralize the
    Gurobi-specific tuple note in [DATA ACCESS]."""
    new, n = _OUTPUT_RE_SCHEMA.subn(fmt, prompt_schema)
    if n != 1:
        raise ValueError("schema prompt adaptation failed: OUTPUT FORMAT "
                         f"block matched {n} times")
    return new.replace("CRITICAL - Network edges require tuple conversion "
                       "for Gurobi:",
                       "NOTE - Network edges as dict keys need tuples "
                       "(PySCIPOpt is fine with plain lists in expressions):")


SCHEMA_PRELUDE = ("import json\n"
                  "data = json.loads(open('data.json').read())\n\n")


def extract_code(text: str) -> str:
    """The prompt demands raw code; tolerate fenced blocks anyway, including
    an opening fence whose closing fence was cut off by max_tokens."""
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    stripped = text.strip()
    if stripped.startswith("```"):          # opening fence, no closing one
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    return stripped.strip()


def run_code(code: str, sandbox: Path) -> dict:
    sandbox.mkdir(parents=True, exist_ok=True)
    script = sandbox / "gen.py"
    script.write_text(code, encoding="utf-8")
    t0 = time.time()
    try:
        p = subprocess.run([EXEC_PYTHON, str(script)], cwd=sandbox,
                           capture_output=True, text=True,
                           timeout=EXEC_TIMEOUT_SEC)
        out, err, rc = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired:
        return {"exec_status": "timeout", "wall_s": time.time() - t0}
    wall = time.time() - t0
    status_m = re.search(r"^status:\s*(\S+)", out, re.MULTILINE)
    obj_m = re.search(r"^objective:\s*([-+0-9.eE]+)", out, re.MULTILINE)
    return {
        "exec_status": "ok" if rc == 0 else "crash",
        "return_code": rc,
        "solver_status": status_m.group(1) if status_m else None,
        "objective": float(obj_m.group(1)) if obj_m else None,
        "stderr_tail": err[-400:] if rc != 0 else "",
        "wall_s": round(wall, 1),
    }


def run_witness(row: dict, sandbox: Path) -> dict:
    """Re-verify the dumped solution.json instead of trusting the printed
    objective. Witness verdicts: no_solution / parse_error / feasible /
    infeasible(+rules). Family checkers beyond f1 are not built yet."""
    sol_path = sandbox / "solution.json"
    out = {"witness": "no_solution"}
    if not sol_path.exists():
        return out
    try:
        sol = json.loads(sol_path.read_text())
    except json.JSONDecodeError as e:
        return {"witness": "parse_error", "witness_error": str(e)[:200]}
    sid = row["scenario_id"]
    if "_f1_" not in sid:
        return {"witness": "no_checker"}
    res = witness_f1.check(json.loads(row["data"]), sol)
    out["witness"] = "feasible" if not res["violations"] else "infeasible"
    out["witness_rules"] = sorted({r for r, _ in res["violations"]})
    out["witness_details"] = [f"{r}: {d}" for r, d in
                              res["violations"][:10]]
    out["witness_warnings"] = len(res["warnings"])
    return out


def grade(objective, reference, solver_status) -> str:
    if solver_status is None:
        return "no_output"
    if solver_status == "infeasible":
        return "declared_infeasible"
    if objective is None:
        return "no_objective"
    if reference is None:
        return "unscored"
    gap = (objective - reference) / max(abs(reference), 1e-9)
    if gap < -OBJ_REL_TOL:
        return "better_than_reference"   # suspicious: likely a modeling hole
    if gap <= OBJ_REL_TOL:
        return "match"
    return f"suboptimal_gap_{gap:.3f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--families", nargs="*", default=None)
    ap.add_argument("--modes", nargs="*", default=["on", "off"],
                    choices=["on", "off"])
    ap.add_argument("--variant", default="v0", help="which data variant")
    ap.add_argument("--prompt-mode", default="full",
                    choices=["full", "schema", "schema_sol"],
                    help="full = inline data (transcription risk); schema = "
                         "data pre-loaded as variable, injected by harness; "
                         "schema_sol = schema + model must dump solution.json "
                         "for witness re-verification (f1 only for now)")
    args = ap.parse_args()

    rows = [json.loads(l) for l in DATA.read_text().splitlines() if l.strip()]
    if args.families:
        fams = tuple(f"_f{''.join(f.lower().lstrip('f'))}_"
                     for f in args.families)
        rows = [r for r in rows if any(f in r["scenario_id"] for f in fams)]
    rows = [r for r in rows
            if r["scenario_id"].endswith(f"_{args.variant}")]
    rows.sort(key=lambda r: r["scenario_id"])
    if args.limit:
        rows = rows[: args.limit]

    cfg = llm_mod.load_config()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"m1_pilot_{args.prompt_mode}.jsonl"
    done = set()
    if out_path.exists():
        for l in out_path.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                done.add((r["scenario_id"], r["thinking"]))

    with out_path.open("a", encoding="utf-8") as fp:
        for row in rows:
            if args.prompt_mode == "full":
                prompt = adapt_prompt(row["prompt_full"])
            elif args.prompt_mode == "schema":
                prompt = adapt_prompt_schema(row["prompt_schema"])
            else:
                prompt = adapt_prompt_schema(row["prompt_schema"],
                                             SCIP_OUTPUT_FORMAT_SOL)
            for mode in args.modes:
                sid = row["scenario_id"]
                if (sid, mode) in done:
                    print(f"[skip] {sid} {mode}")
                    continue
                # Internal vLLM: thinking off ONLY works via nested
                # chat_template_kwargs (top-level enable_thinking is silently
                # ignored — measured 2026-10-29). Thinking on gets
                # reasoning_effort=medium: default xhigh fills 32k reasoning
                # tokens and truncates the answer to empty.
                extra = ({"chat_template_kwargs": {"enable_thinking": False}}
                         if mode == "off" else {"reasoning_effort": "medium"})
                # thinking mode shares one completion budget between
                # reasoning and answer on this vLLM build; 8192 truncates
                # long reasoning and yields empty content. Off mode still
                # needs room: a 52-period MILP script exceeds 8192 tokens.
                max_tokens = 16384 if mode == "off" else 32768
                t0 = time.time()
                try:
                    resp = llm_mod.chat(
                        [{"role": "user", "content": prompt}],
                        max_tokens=max_tokens, temperature=0.6, extra=extra,
                        config=cfg)
                    text = resp.get("content") or ""
                    llm_err = None
                except Exception as e:
                    text, llm_err = "", f"{type(e).__name__}: {e}"
                rec = {"scenario_id": sid, "thinking": mode,
                       "prompt_mode": args.prompt_mode,
                       "llm_latency_s": round(time.time() - t0, 1),
                       "reference_objective": row["reference_objective"],
                       "reference_status": row["reference_status"]}
                if not llm_err:
                    u = resp.get("usage") or {}
                    rec["finish_reason"] = resp.get("finish_reason")
                    rec["reasoning_tokens"] = (
                        (u.get("completion_tokens_details") or {})
                        .get("reasoning_tokens"))
                    rec["completion_tokens"] = u.get("completion_tokens")
                if llm_err:
                    rec.update(exec_status="llm_error", error=llm_err)
                else:
                    rec["code_chars"] = len(text)
                    sandbox = (OUT_DIR / "sandbox"
                               / f"{args.prompt_mode}__{sid}__{mode}")
                    code = extract_code(text)
                    if args.prompt_mode in ("schema", "schema_sol"):
                        # the prompt says `data` is pre-loaded; the harness
                        # fulfills that contract with a prelude + data.json
                        (sandbox).mkdir(parents=True, exist_ok=True)
                        (sandbox / "data.json").write_text(row["data"])
                        code = SCHEMA_PRELUDE + code
                    rec.update(run_code(code, sandbox))
                    rec["grade"] = grade(rec.get("objective"),
                                         row["reference_objective"],
                                         rec.get("solver_status"))
                    if args.prompt_mode == "schema_sol":
                        rec.update(run_witness(row, sandbox))
                fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fp.flush()
                print(f"[{sid}][{mode}] {rec.get('exec_status')} "
                      f"solver={rec.get('solver_status')} "
                      f"grade={rec.get('grade')} "
                      f"witness={rec.get('witness', '-')} "
                      f"llm={rec['llm_latency_s']}s")


if __name__ == "__main__":
    main()
