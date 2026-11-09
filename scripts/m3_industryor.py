#!/usr/bin/env python3
"""M3: IndustryOR-100 zero-adaptation migration runner (phase C).

Three arms measuring what transfers with ZERO RetailOpt semantic assets:
  z0: bare single-shot (NL + generic SCIP contract), no loop
  z1: + crash/timeout/infeasible repair loop (<=3 rounds), no priors
  z2: z1 + engineering priors (evo/genomes/g0_seed/code.txt, clause 1
      data.json sentences neutrally rewritten — IndustryOR has no data.json)

No witness (no rules exist for this dataset), no semantic memory, no
pre-solve gate. The repair loop never sees en_answer; ground truth is used
only for post-hoc grading. Phantom proxy = printed objective that mismatches
en_answer (invisible without an auditor — that invisibility is the finding).

Usage (from /home/hewj13/wm/ora):
    source ~/.leagent_env
    python3 scripts/m3_industryor.py --arm z0 --shard 0/4 --limit 2  # smoke
    python3 scripts/m3_industryor.py --arm z1 --shard 2/4
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from m1_pilot import extract_code, run_code  # noqa: E402

DATA = ROOT / "data" / "industryor" / "IndustryOR.json"
OUT_DIR = ROOT / "runs" / "industryor"
MAX_ROUNDS = 3

SCIP_CONTRACT = """[OUTPUT FORMAT]
- Import: from pyscipopt import Model; import json
- Create the model: m = Model(); silence solver logs: m.hideOutput()
- Set a solver time limit: m.setRealParam("limits/time", 570)
- After m.optimize(), print at end:
  st = m.getStatus()
  print(f"status: {st}")
  if m.getNSols() > 0:
      print(f"objective: {m.getObjVal()}")
- Output ONLY executable Python code. No markdown, no explanations.

[TASK]
Write a PySCIPOpt script that models and solves the following optimization
problem. All data appears in the problem text; transcribe it into Python
literals at the top of your script.

[PROBLEM]
"""


def load_priors() -> str:
    """g0_seed engineering priors with the data.json clause neutrally
    rewritten (IndustryOR has no data.json infrastructure)."""
    lines = (ROOT / "evo" / "genomes" / "g0_seed" / "code.txt") \
        .read_text().splitlines()
    out, skipping = [], False
    for ln in lines:
        if ln.startswith("1. The prelude already loads `data` from data.json"):
            skipping = True
            out.append(
                "1. All data appears in the problem text; transcribe it into\n"
                "   Python literals ONCE at the top of the script and never\n"
                "   re-read or reassign the container (e.g. `data = None`\n"
                "   kills every subsequent data[...] access).")
            continue
        if skipping:
            if ln.startswith("2. "):
                skipping = False
            else:
                continue
        out.append(ln)
    txt = "\n".join(out)
    assert "data.json" not in txt, "data.json reference leaked into priors"
    return txt.strip()


def feedback_msg(rec: dict) -> str | None:
    """None = stop (a solution printed an objective; correctness unknowable
    inside the loop without ground truth — deliberately unused here)."""
    tail = (rec.get("stderr_tail") or "")[-600:]
    es, ss = rec.get("exec_status"), rec.get("solver_status")
    if es == "crash":
        return ("The script CRASHED when executed. stderr (tail):\n"
                f"```\n{tail}\n```\nDiagnose and rewrite the COMPLETE "
                "corrected script. Output ONLY executable Python code.")
    if es == "timeout":
        return ("The script exceeded the execution time limit. Make the "
                "model/code substantially more efficient and rewrite the "
                "COMPLETE script. Output ONLY executable Python code.")
    if es == "llm_error":
        return ("The previous generation failed. Produce the COMPLETE "
                "script. Output ONLY executable Python code.")
    if ss == "infeasible":
        return ("The solver reports the model is INFEASIBLE — it is "
                "over-constrained. Check sign directions and capacity vs "
                "demand consistency; then rewrite the COMPLETE script. "
                "Output ONLY executable Python code.")
    if rec.get("objective") is None:
        return ("The script ran but printed no objective. Follow the "
                "[OUTPUT FORMAT] contract exactly: print status and, when "
                "a solution exists, the objective. Rewrite the COMPLETE "
                "script. Output ONLY executable Python code.")
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True,
                    choices=["z0", "z1", "z2", "z0b", "z0c"])
    ap.add_argument("--shard", default="0/1", help="k/K zero-based")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--data", default=None,
                    help="override dataset json (id/en_question/en_answer), "
                         "e.g. data/external/mamo_complex_lp.json")
    ap.add_argument("--out-suffix", default="",
                    help="appended to output filename, e.g. '_pearl4b' keeps "
                         "per-model results separate")
    args = ap.parse_args()

    k, kk = (int(x) for x in args.shard.split("/"))
    rows = json.loads((Path(args.data) if args.data else DATA).read_text())
    rows = [r for i, r in enumerate(sorted(rows, key=lambda r: r["id"]))
            if i % kk == k]
    if args.limit:
        rows = rows[: args.limit]

    conventions = load_priors() if args.arm == "z2" else None
    cfg = llm_mod.load_config()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"m3_{args.arm}{args.out_suffix}_s{k}.jsonl"
    done = set()
    last: dict[int, dict] = {}
    if out_path.exists():
        for l in out_path.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                done.add((r["id"], r["round"]))
                if r["id"] not in last or r["round"] > last[r["id"]]["round"]:
                    last[r["id"]] = r

    with out_path.open("a", encoding="utf-8") as fp:
        for row in rows:
            pid = row["id"]
            prompt = SCIP_CONTRACT + row["en_question"]
            if conventions:
                prompt = conventions + "\n\n" + prompt
            msgs: list[dict] = []
            prev: dict = last.get(pid) or {}
            prev_text = ""
            for rnd in range(1, (MAX_ROUNDS if not args.arm.startswith("z0") else 1) + 1):
                if (pid, rnd) in done:
                    continue
                if rnd == 1:
                    msgs = [{"role": "user", "content": prompt}]
                else:
                    fb = feedback_msg(prev)
                    if fb is None:
                        break
                    if not prev_text:
                        sb = (OUT_DIR / "sandbox"
                              / f"{args.arm}{args.out_suffix}__{pid}__r{rnd - 1}" / "gen.py")
                        prev_text = (sb.read_text() if sb.exists()
                                     else "# (previous code unavailable)")
                    msgs = [{"role": "user", "content": prompt},
                            {"role": "assistant", "content": prev_text},
                            {"role": "user", "content": fb}]
                t0 = time.time()
                try:
                    resp = llm_mod.chat(
                        msgs, max_tokens=32768, temperature=0.6,
                        extra={"reasoning_effort": "medium"}, config=cfg)
                    text = resp.get("content") or ""
                    llm_err = None
                except Exception as e:
                    text, llm_err = "", f"{type(e).__name__}: {e}"
                rec = {"id": pid, "arm": args.arm, "round": rnd,
                       "difficulty": row["difficulty"],
                       "llm_latency_s": round(time.time() - t0, 1),
                       "reference": float(row["en_answer"])}
                if llm_err:
                    rec.update(exec_status="llm_error", error=llm_err)
                else:
                    u = resp.get("usage") or {}
                    rec["completion_tokens"] = u.get("completion_tokens")
                    rec["reasoning_tokens"] = (
                        (u.get("completion_tokens_details") or {})
                        .get("reasoning_tokens"))
                    rec["code_chars"] = len(text)
                    sandbox = (OUT_DIR / "sandbox"
                               / f"{args.arm}{args.out_suffix}__{pid}__r{rnd}")
                    rec.update(run_code(extract_code(text), sandbox))
                fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fp.flush()
                print(f"[{args.arm}][{pid}][r{rnd}] "
                      f"{rec.get('exec_status')} "
                      f"solver={rec.get('solver_status')} "
                      f"obj={rec.get('objective')} "
                      f"llm={rec['llm_latency_s']}s", flush=True)
                prev = rec
                prev_text = text
                if rec.get("exec_status") == "llm_error":
                    break


if __name__ == "__main__":
    main()
