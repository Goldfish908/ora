#!/usr/bin/env python3
"""SAC-Opt + L1 hybrid arm: SAC-Opt's anchor-alignment loop unchanged, but
when the final code CRASHES on execution, fall back to our deterministic
crash-guard repair loop (guard_report feedback, max 3 repair turns).

Purpose: remove the "SAC-Opt never reached the semantic layer" confound —
with crash recovery granted, do its anchors then match our loop?

Usage:
  python3 scripts/sac_opt_l1.py --scenarios-file work/mem_evo/dev40_rows.jsonl \
      --out-dir runs/sac_opt --out-tag _l1
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
from scripts.m1_pilot import (  # noqa: E402
    SCHEMA_PRELUDE, SCIP_OUTPUT_FORMAT_SOL, adapt_prompt_schema,
    extract_code, run_code, run_witness, grade)
from scripts.m1_presolve_loop import guard_report  # noqa: E402
from scripts.guard_check import guard_source  # noqa: E402
from scripts.sac_opt import (  # noqa: E402
    ANCHOR_EXTRACT, ANCHOR_RECONSTRUCT, ALIGN_AND_FIX, MAX_CORRECTIONS)

MAX_L1_TURNS = 3


def chat(prompt: str, cfg, max_tokens=32768) -> str:
    resp = llm_mod.chat([{"role": "user", "content": prompt}],
                        max_tokens=max_tokens, temperature=0.6,
                        extra={"reasoning_effort": "medium"}, config=cfg)
    return resp.get("content") or ""


def run_cell(row: dict, cfg, out_dir: Path) -> dict:
    sid = row["scenario_id"]
    base_prompt = adapt_prompt_schema(row["prompt_schema"],
                                      SCIP_OUTPUT_FORMAT_SOL)
    rec = {"scenario_id": sid, "thinking": "on", "method": "sac_opt_l1",
           "reference_objective": row["reference_objective"],
           "reference_status": row["reference_status"]}
    llm_calls = 0
    t0 = time.time()

    anchors = chat(ANCHOR_EXTRACT + "\n\n" + base_prompt, cfg)
    llm_calls += 1
    gen_prompt = ("Here are the semantic anchors extracted from the problem. "
                  "Your model MUST faithfully encode every one of them.\n\n"
                  + anchors + "\n\n" + base_prompt)
    code = extract_code(chat(gen_prompt, cfg))
    llm_calls += 1

    aligned = False
    for _ in range(MAX_CORRECTIONS):
        recon = chat(ANCHOR_RECONSTRUCT.format(code=code), cfg)
        fix = chat(ALIGN_AND_FIX.format(anchors=anchors, recon=recon,
                                        code=code), cfg)
        llm_calls += 2
        if fix.strip().startswith("ALIGNED"):
            aligned = True
            break
        new_code = extract_code(fix)
        if len(new_code) < 200:
            break
        code = new_code

    # L1 fallback: deterministic crash-guard repair loop (only on crash)
    l1_turns = 0
    sandbox = out_dir / "sandbox" / f"sacoptl1__{sid}__on"
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "data.json").write_text(row["data"])
    result = run_code(SCHEMA_PRELUDE + code, sandbox)
    while result.get("exec_status") == "crash" and l1_turns < MAX_L1_TURNS:
        hits = guard_source(SCHEMA_PRELUDE + code)
        if not hits:
            break
        l1_turns += 1
        fixed = chat(guard_report(hits) + "\n\nYour code:\n```python\n"
                     + code + "\n```", cfg)
        llm_calls += 1
        new_code = extract_code(fixed)
        if len(new_code) < 200:
            break
        code = new_code
        result = run_code(SCHEMA_PRELUDE + code, sandbox)

    rec.update(result)
    rec["grade"] = grade(rec.get("objective"), row["reference_objective"],
                         rec.get("solver_status"))
    rec.update(run_witness(row, sandbox))
    rec["llm_calls"] = llm_calls
    rec["aligned"] = aligned
    rec["l1_turns"] = l1_turns
    rec["llm_s"] = round(time.time() - t0, 1)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios-file", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--out-tag", default="_l1")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = [json.loads(l) for l in
            Path(args.scenarios_file).read_text().splitlines() if l.strip()]
    rows.sort(key=lambda r: r["scenario_id"])
    if args.limit:
        rows = rows[: args.limit]

    cfg = llm_mod.load_config()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"sac_opt{args.out_tag}.jsonl"
    done = set()
    if out_path.exists():
        for l in out_path.read_text().splitlines():
            if l.strip():
                done.add(json.loads(l)["scenario_id"])

    with out_path.open("a", encoding="utf-8") as fp:
        for row in rows:
            sid = row["scenario_id"]
            if sid in done:
                print(f"[skip] {sid}")
                continue
            try:
                rec = run_cell(row, cfg, out_dir)
            except Exception as e:  # fail-open
                rec = {"scenario_id": sid, "thinking": "on",
                       "method": "sac_opt_l1", "exec_status": "harness_error",
                       "error": f"{type(e).__name__}: {e}",
                       "reference_objective": row["reference_objective"],
                       "reference_status": row["reference_status"]}
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fp.flush()
            print(f"[{sid}] exec={rec.get('exec_status')} "
                  f"grade={rec.get('grade')} witness={rec.get('witness', '-')} "
                  f"l1={rec.get('l1_turns', '-')} "
                  f"calls={rec.get('llm_calls', '-')}", flush=True)


if __name__ == "__main__":
    main()
