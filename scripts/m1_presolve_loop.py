#!/usr/bin/env python3
"""M1 pre-solve-gated feedback loop (online arm B of the PSV experiment).

Identical to scripts/m1_feedback.py (Route-B, max 3 rounds) except that every
newly generated code passes a PRE-SOLVE GATE before execution:

  gate = checklist verification (scripts/psv_check_code.check_one) against the
         instance requirement ledger (runs/presolve/req_ledgers.jsonl);
         BLOCK rule = any requirement missing/wrong or implemented-without-
         citation (scripts/psv_score.blocked).
  BLOCK -> verifier report fed back, regenerate WITHOUT solver invocation
           (max --presolve-turns per round), then re-gate.
  PASS  -> execute + witness exactly as Route-B.

Round-1 gating reuses the offline Phase-C verdicts (code_checks.jsonl) so the
round-1 code is never re-checked nor re-executed.

Arm A for the controlled comparison is the existing F12 run
(runs/m1_feedback/m1_feedback_v*.jsonl), same max-rounds=3.

Usage (from /home/hewj13/wm/ora):
    source ~/.leagent_env  (+ ORA_LLM_* exports)
    python3 scripts/m1_presolve_loop.py --variant v0 --modes on
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
from scripts.m1_feedback import failure_type, feedback_msg  # noqa: E402
from scripts.psv_check_code import check_one  # noqa: E402
from scripts.psv_score import blocked  # noqa: E402

PILOT_DIR = ROOT / "runs" / "m1_pilot"
OUT_DIR = ROOT / "runs" / "m1_presolve"
PSV_DIR = ROOT / "runs" / "presolve"


def verifier_report(bad: list[dict]) -> str:
    items = "\n".join(
        f"- [{c['id']}] {c['status'].upper()}: {(c.get('note') or '').strip() or 'no note'}"
        for c in bad)
    return ("PRE-SOLVE VERIFICATION FAILED (your code was NOT executed). An "
            "independent checker compared your code against this problem's "
            "requirement ledger and found requirements that are not enforced:\n"
            f"{items}\n"
            "Fix these MODELING issues (add the missing constraints / correct "
            "the defective ones) and rewrite the COMPLETE script. Output ONLY "
            "executable Python code.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="v0")
    ap.add_argument("--out-tag", default="")
    ap.add_argument("--modes", nargs="*", default=["on"], choices=["on", "off"])
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--presolve-turns", type=int, default=2,
                    help="max BLOCK-regenerate turns per round before solving anyway")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    ds_rows = {json.loads(l)["scenario_id"]: json.loads(l)
               for l in DATA.read_text().splitlines() if l.strip()}

    ledgers = {}
    for line in open(PSV_DIR / "req_ledgers.jsonl"):
        r = json.loads(line)
        if r.get("ledger"):
            ledgers[r["scenario_id"]] = r["ledger"]

    r1_checks = {}
    cc = PSV_DIR / "code_checks.jsonl"
    if cc.exists():
        for line in open(cc):
            r = json.loads(line)
            if r.get("checks"):
                r1_checks[(r["scenario_id"], r["thinking"])] = r["checks"]

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
    out_path = OUT_DIR / f"m1_presolve{args.out_tag}.jsonl"
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
            ledger = ledgers.get(sid)
            prompt = adapt_prompt_schema(row["prompt_schema"],
                                         SCIP_OUTPUT_FORMAT_SOL)
            prev = last_rec.get((sid, mode)) or r1[(sid, mode)]
            prev_code = None
            # round-1 gate verdict from the offline Phase-C pass
            prev_gate_bad = None
            if (sid, mode) in r1_checks and (sid, mode) not in last_rec:
                b, bad = blocked(r1_checks[(sid, mode)])
                prev_gate_bad = bad if b else None
            n_solves = 1  # round-1 solve already happened (pilot)
            for rnd in range(2, args.max_rounds + 1):
                if (sid, mode, rnd) in done:
                    continue
                ftype = failure_type(prev)
                if ftype is None:
                    break
                if prev_code is None:
                    sb = (PILOT_DIR / "sandbox"
                          / f"schema_sol__{sid}__{mode}" / "gen.py")
                    if rnd > 2:
                        sb = (OUT_DIR / "sandbox"
                              / f"psv__{sid}__{mode}__r{rnd - 1}" / "gen.py")
                    prev_code = (sb.read_text()
                                 .removeprefix(SCHEMA_PRELUDE) if sb.exists()
                                 else "# (code unavailable)")
                # choose feedback: verifier report if the last code was gated
                # BLOCK, else the standard Route-B failure feedback
                if prev_gate_bad:
                    fb = verifier_report(prev_gate_bad)
                    fb_kind = "presolve"
                else:
                    fb = feedback_msg(ftype, prev)
                    fb_kind = ftype
                msgs = [{"role": "user", "content": prompt},
                        {"role": "assistant", "content": prev_code},
                        {"role": "user", "content": fb}]
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
                       "failure_in": fb_kind,
                       "llm_latency_s": round(time.time() - t0, 1),
                       "reference_objective": row["reference_objective"],
                       "reference_status": row["reference_status"],
                       "n_solves_so_far": n_solves}
                if not llm_err:
                    u = resp.get("usage") or {}
                    rec["finish_reason"] = resp.get("finish_reason")
                    rec["completion_tokens"] = u.get("completion_tokens")
                if llm_err:
                    rec.update(exec_status="llm_error", error=llm_err)
                    rec["true_success"] = False
                    fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fp.flush()
                    prev = rec
                    prev_gate_bad = None
                    continue
                code = extract_code(text)
                rec["code_chars"] = len(text)
                # ---- PRE-SOLVE GATE on the new code ----
                gate_turns = 0
                gate_bad = None
                if ledger:
                    while True:
                        chk = check_one(sid, mode, ledger,
                                        SCHEMA_PRELUDE + code)
                        rec.setdefault("presolve_checks", []).append(
                            {"turn": gate_turns, "latency_s": chk["latency_s"],
                             "n_bad": (len([c for c in (chk["checks"] or [])
                                            if c["status"] != "implemented"])
                                       if chk["checks"] else None)})
                        if not chk["checks"]:
                            break  # checker failed -> fail open (solve anyway)
                        b, bad = blocked(chk["checks"])
                        if not b:
                            break
                        gate_bad = bad
                        gate_turns += 1
                        if gate_turns > args.presolve_turns:
                            break  # budget exhausted -> solve anyway
                        # regenerate without solving
                        gmsgs = [{"role": "user", "content": prompt},
                                 {"role": "assistant", "content": code},
                                 {"role": "user", "content": verifier_report(bad)}]
                        try:
                            gresp = llm_mod.chat(
                                gmsgs, max_tokens=max_tokens, temperature=0.6,
                                extra=extra, config=cfg)
                            code = extract_code(gresp.get("content") or "")
                        except Exception:
                            break
                    rec["presolve_gate_turns"] = gate_turns
                    rec["presolve_final"] = ("block" if gate_bad and
                                             gate_turns > args.presolve_turns
                                             else "pass")
                # ---- execute ----
                sandbox = (OUT_DIR / "sandbox"
                           / f"psv__{sid}__{mode}__r{rnd}")
                sandbox.mkdir(parents=True, exist_ok=True)
                (sandbox / "data.json").write_text(row["data"])
                rec.update(run_code(SCHEMA_PRELUDE + code, sandbox))
                n_solves += 1
                rec["grade"] = grade(rec.get("objective"),
                                     row["reference_objective"],
                                     rec.get("solver_status"))
                rec.update(run_witness(row, sandbox))
                rec["true_success"] = failure_type(rec) is None
                fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fp.flush()
                print(f"[{sid}][{mode}][r{rnd}] in={fb_kind} "
                      f"gate={rec.get('presolve_final', '-')} "
                      f"exec={rec.get('exec_status')} "
                      f"witness={rec.get('witness', '-')} "
                      f"success={rec['true_success']}", flush=True)
                prev = rec
                prev_code = code
                prev_gate_bad = None  # post-solve failures use Route-B feedback
                if rec["true_success"]:
                    break


if __name__ == "__main__":
    main()
