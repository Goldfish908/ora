#!/usr/bin/env python3
"""M1 Route-B feedback harness: execution + witness feedback loop.

Round 1 is the zero-shot result already in runs/m1_pilot/m1_pilot_schema_sol*.
jsonl. Cells that did not reach true_success (witness feasible AND objective
within tol of reference) get up to --max-rounds total attempts with targeted
feedback:

  crash            -> stderr tail fed back
  timeout          -> efficiency warning
  solver timelimit -> incumbent-print contract fix (F11 finding: the
                      optimal-only print discards feasible incumbents)
  no solution.json -> contract reminder
  witness infeasible -> violation rules + up to 10 detail lines fed back
  declared infeasible -> over-constraint warning
  feasible suboptimal -> generic improvement nudge

Conversation per round n>=2: [prompt, latest code, feedback] (bounded
context; earlier rounds are summarized by the latest failure only).

Usage (from /home/hewj13/wm/ora):
    source ~/.leagent_env  (+ ORA_LLM_* exports)
    python3 scripts/m1_feedback.py --variant v0
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from scripts.m1_pilot import (  # noqa: E402
    SCHEMA_PRELUDE, SCIP_OUTPUT_FORMAT_SOL, adapt_prompt_schema,
    extract_code, run_code, run_witness, grade, DATA)

PILOT_DIR = ROOT / "runs" / "m1_pilot"
OUT_DIR = ROOT / "runs" / "m1_feedback"


def failure_type(rec: dict) -> str | None:
    """None means true success (loop stops)."""
    w = rec.get("witness")
    g = rec.get("grade")
    if w == "feasible" and g in ("match", "better_than_reference"):
        return None
    if rec.get("exec_status") == "crash":
        return "crash"
    if rec.get("exec_status") == "timeout":
        return "timeout"
    if rec.get("exec_status") == "llm_error":
        return "llm_error"
    if rec.get("solver_status") == "infeasible":
        return "declared_infeasible"
    if rec.get("solver_status") not in (None, "optimal") \
            and rec.get("objective") is None:
        return "timelimit_no_incumbent"
    if w == "no_solution":
        return "no_solution_dump"
    if w == "parse_error":
        return "solution_parse_error"
    if w == "infeasible":
        return "witness_infeasible"
    return "suboptimal"


def feedback_msg(ftype: str, rec: dict) -> str:
    tail = (rec.get("stderr_tail") or "")[-600:]
    if ftype == "crash":
        return ("The script CRASHED when executed. stderr (tail):\n"
                f"```\n{tail}\n```\nDiagnose and rewrite the COMPLETE "
                "corrected script. Output ONLY executable Python code.")
    if ftype == "timeout":
        return ("The script exceeded the execution time limit. Make the "
                "model/code substantially more efficient and rewrite the "
                "COMPLETE script. Output ONLY executable Python code.")
    if ftype == "llm_error":
        return ("The previous generation failed. Produce the COMPLETE "
                "script. Output ONLY executable Python code.")
    if ftype == "declared_infeasible":
        return ("The solver reports the model is INFEASIBLE — it is "
                "over-constrained. Check sign directions, capacity vs demand "
                "consistency, and bucket bookkeeping; then rewrite the "
                "COMPLETE script. Output ONLY executable Python code.")
    if ftype == "timelimit_no_incumbent":
        return ("The solver hit its time limit without proving optimality, "
                "and your print contract discarded the best incumbent. Fix "
                "the reporting: after m.optimize(), use st = m.getStatus(); "
                "print(f\"status: {st}\"); if m.getNSols() > 0: "
                "print(f\"objective: {m.getObjVal()}\") and ALSO dump the "
                "incumbent to solution.json. Tighten the formulation if "
                "possible. Rewrite the COMPLETE script. Output ONLY "
                "executable Python code.")
    if ftype in ("no_solution_dump", "solution_parse_error"):
        return ("The script ran but did not produce a valid solution.json. "
                "Follow the [OUTPUT FORMAT] contract exactly: after solving, "
                "write the sparse decision tables with json.dump to "
                "solution.json. Rewrite the COMPLETE script. Output ONLY "
                "executable Python code.")
    if ftype == "witness_infeasible":
        details = "\n".join(rec.get("witness_details") or
                            rec.get("witness_rules") or [])
        return ("The script ran and printed an objective, but an independent "
                "constraint checker re-verified your solution.json and found "
                "HARD CONSTRAINT VIOLATIONS — the objective is not "
                "trustworthy:\n"
                f"```\n{details[:1500]}\n```\n"
                "These are modeling errors (e.g. inventory that does not "
                "exist, demand balance broken). Fix the MODEL — do not try "
                "to match a number — and rewrite the COMPLETE script. "
                "Output ONLY executable Python code.")
    return ("Your solution is feasible but likely suboptimal. Improve the "
            "decisions and rewrite the COMPLETE script. Output ONLY "
            "executable Python code.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="v0")
    ap.add_argument("--out-tag", default="")
    ap.add_argument("--modes", nargs="*", default=["on", "off"],
                    choices=["on", "off"])
    ap.add_argument("--max-rounds", type=int, default=3,
                    help="total attempts including the zero-shot round 1")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    ds_rows = {json.loads(l)["scenario_id"]: json.loads(l)
               for l in DATA.read_text().splitlines() if l.strip()}

    # round-1 state from the pilot shards
    r1: dict[tuple[str, str], dict] = {}
    for f in sorted(PILOT_DIR.glob("m1_pilot_schema_sol*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                r1[(r["scenario_id"], r["thinking"])] = r

    cells = sorted(
        (sid, mode) for (sid, mode), r in r1.items()
        if sid.endswith(f"_{args.variant}") and mode in args.modes
        and failure_type(r) is not None)
    if args.limit:
        cells = cells[: args.limit]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"m1_feedback{args.out_tag}.jsonl"
    done = set()
    last_rec: dict[tuple[str, str], dict] = {}
    if out_path.exists():
        for l in out_path.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                key = (r["scenario_id"], r["thinking"])
                done.add((r["scenario_id"], r["thinking"], r["round"]))
                if key not in last_rec or r["round"] > last_rec[key]["round"]:
                    last_rec[key] = r

    cfg = llm_mod.load_config()
    with out_path.open("a", encoding="utf-8") as fp:
        for sid, mode in cells:
            row = ds_rows[sid]
            prompt = adapt_prompt_schema(row["prompt_schema"],
                                         SCIP_OUTPUT_FORMAT_SOL)
            prev = last_rec.get((sid, mode)) or r1[(sid, mode)]
            prev_code = None
            for rnd in range(2, args.max_rounds + 1):
                if (sid, mode, rnd) in done:
                    continue
                ftype = failure_type(prev)
                if ftype is None:
                    break
                if prev_code is None:
                    # recover round-1 (or previous-round) code from sandbox
                    sb = (PILOT_DIR / "sandbox"
                          / f"schema_sol__{sid}__{mode}" / "gen.py")
                    if rnd > 2:
                        sb = (OUT_DIR / "sandbox"
                              / f"fb__{sid}__{mode}__r{rnd - 1}" / "gen.py")
                    prev_code = (sb.read_text()
                                 .removeprefix(SCHEMA_PRELUDE) if sb.exists()
                                 else "# (code unavailable)")
                msgs = [{"role": "user", "content": prompt},
                        {"role": "assistant", "content": prev_code},
                        {"role": "user", "content": feedback_msg(ftype, prev)}]
                extra = ({"chat_template_kwargs": {"enable_thinking": False}}
                         if mode == "off"
                         else {"reasoning_effort": "medium"})
                max_tokens = 16384 if mode == "off" else 32768
                t0 = time.time()
                try:
                    resp = llm_mod.chat(msgs, max_tokens=max_tokens,
                                        temperature=0.6, extra=extra,
                                        config=cfg)
                    text = resp.get("content") or ""
                    llm_err = None
                except Exception as e:
                    text, llm_err = "", f"{type(e).__name__}: {e}"
                rec = {"scenario_id": sid, "thinking": mode, "round": rnd,
                       "failure_in": ftype,
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
                               / f"fb__{sid}__{mode}__r{rnd}")
                    code = extract_code(text)
                    sandbox.mkdir(parents=True, exist_ok=True)
                    (sandbox / "data.json").write_text(row["data"])
                    rec.update(run_code(SCHEMA_PRELUDE + code, sandbox))
                    rec["grade"] = grade(rec.get("objective"),
                                         row["reference_objective"],
                                         rec.get("solver_status"))
                    rec.update(run_witness(row, sandbox))
                rec["true_success"] = failure_type(rec) is None
                fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fp.flush()
                print(f"[{sid}][{mode}][r{rnd}] in={ftype} "
                      f"exec={rec.get('exec_status')} "
                      f"witness={rec.get('witness', '-')} "
                      f"grade={rec.get('grade')} "
                      f"success={rec['true_success']}", flush=True)
                prev = rec
                if not llm_err:
                    prev_code = code
                if rec["true_success"]:
                    break


if __name__ == "__main__":
    main()
