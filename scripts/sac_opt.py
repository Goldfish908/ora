#!/usr/bin/env python3
"""SAC-Opt replication (arXiv 2510.05115) on RetailOpt cells.

Backward semantic-anchored correction:
  round 0: extract semantic anchors from problem text -> generate code
           conditioned on the anchors
  round k: reconstruct anchors FROM the generated code -> align with the
           original anchors -> if mismatches, correct ONLY those components
  stop   : anchors aligned (no mismatch) or max correction rounds reached

Evaluation uses OUR trust anchors (deterministic witness + reference
objective grade), so SAC-Opt's blind spots (e.g. text-consistent phantoms)
are measurable. Gold/reference never enters any prompt.

Usage:
  python3 scripts/sac_opt.py --scenarios-file work/mem_evo/replay_gen1.jsonl \
      --out-dir runs/sac_opt --out-tag _dev
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
    extract_code, run_code, run_witness, grade, DATA)

MAX_CORRECTIONS = 3

ANCHOR_EXTRACT = """You are given an optimization problem description and its data schema.
Extract the SEMANTIC ANCHORS of the problem as a structured list:
1. ENTITIES and index sets (products, locations, periods, age buckets, ...).
2. DECISION VARIABLES: name, index sets, domain (continuous/integer/binary),
   physical unit, meaning.
3. CONSTRAINTS: one line each, as a math statement with its index set and the
   business meaning it encodes (e.g. "demand balance: what is sold plus what
   is lost equals demand, per product-location-period").
4. OBJECTIVE: every cost/revenue term and its sign.
5. DATA-FIELD ACTIVATION: which data fields switch which mechanisms on
   (a zero/null/empty field means the mechanism is inactive).
Be exhaustive but terse. Output ONLY the anchor list."""

ANCHOR_RECONSTRUCT = """Below is a PySCIPOpt script that claims to model an optimization problem.
Reconstruct the SEMANTIC ANCHORS the CODE actually encodes, in the SAME
structure (entities / variables+domains / constraints as math one-liners /
objective terms / data-field activation).
Report only what the code literally implements, not what it should implement.
Output ONLY the reconstructed anchor list.

```python
{code}
```"""

ALIGN_AND_FIX = """Original semantic anchors (from the problem text):
<original>
{anchors}
</original>

Reconstructed anchors (from your generated code):
<reconstructed>
{recon}
</reconstructed>

Your previous code:
```python
{code}
```

Compare the two anchor lists component by component. If they FULLY agree,
reply with exactly: ALIGNED
Otherwise list each mismatch (what the text requires vs what the code does),
then rewrite the COMPLETE corrected script fixing ONLY the mismatched
components. Output ONLY executable Python code in that case."""


def chat(prompt: str, cfg, max_tokens=32768) -> str:
    resp = llm_mod.chat([{"role": "user", "content": prompt}],
                        max_tokens=max_tokens, temperature=0.6,
                        extra={"reasoning_effort": "medium"}, config=cfg)
    return resp.get("content") or "", resp


def run_cell(row: dict, cfg, out_dir: Path) -> dict:
    sid = row["scenario_id"]
    base_prompt = adapt_prompt_schema(row["prompt_schema"],
                                      SCIP_OUTPUT_FORMAT_SOL)
    rec = {"scenario_id": sid, "thinking": "on", "method": "sac_opt",
           "reference_objective": row["reference_objective"],
           "reference_status": row["reference_status"],
           "rounds": []}
    llm_calls = 0
    t0 = time.time()

    # round 0: anchor extraction, then anchored generation
    anchors, _ = chat(ANCHOR_EXTRACT + "\n\n" + base_prompt, cfg)
    llm_calls += 1
    gen_prompt = ("Here are the semantic anchors extracted from the problem. "
                  "Your model MUST faithfully encode every one of them.\n\n"
                  + anchors + "\n\n" + base_prompt)
    text, resp = chat(gen_prompt, cfg)
    llm_calls += 1
    code = extract_code(text)
    rec["rounds"].append({"round": 0, "anchors": anchors[:2000],
                          "code_chars": len(code)})

    # correction loop
    aligned = False
    for k in range(1, MAX_CORRECTIONS + 1):
        recon, _ = chat(ANCHOR_RECONSTRUCT.format(code=code), cfg)
        llm_calls += 1
        fix, _ = chat(ALIGN_AND_FIX.format(anchors=anchors, recon=recon,
                                           code=code), cfg)
        llm_calls += 1
        if fix.strip().startswith("ALIGNED"):
            aligned = True
            rec["rounds"].append({"round": k, "aligned": True})
            break
        new_code = extract_code(fix)
        rec["rounds"].append({"round": k, "aligned": False,
                              "recon_chars": len(recon),
                              "code_chars": len(new_code)})
        if len(new_code) < 200:  # degenerate output; keep previous code
            break
        code = new_code

    sandbox = out_dir / "sandbox" / f"sacopt__{sid}__on"
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "data.json").write_text(row["data"])
    full_code = SCHEMA_PRELUDE + code
    rec.update(run_code(full_code, sandbox))
    rec["grade"] = grade(rec.get("objective"), row["reference_objective"],
                         rec.get("solver_status"))
    rec.update(run_witness(row, sandbox))
    rec["llm_calls"] = llm_calls
    rec["aligned"] = aligned
    rec["llm_s"] = round(time.time() - t0, 1)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios-file", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--out-tag", default="_sacopt")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = [json.loads(l) for l in
            Path(args.scenarios_file).read_text().splitlines() if l.strip()]
    rows.sort(key=lambda r: r["scenario_id"])
    if args.limit:
        rows = rows[: args.limit]

    cfg = llm_mod.load_config()
    out_dir = Path(args.out_dir).resolve()
    (out_dir).mkdir(parents=True, exist_ok=True)
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
            except Exception as e:  # fail-open: record and continue
                rec = {"scenario_id": sid, "thinking": "on",
                       "method": "sac_opt", "exec_status": "harness_error",
                       "error": f"{type(e).__name__}: {e}",
                       "reference_objective": row["reference_objective"],
                       "reference_status": row["reference_status"]}
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fp.flush()
            print(f"[{sid}] exec={rec.get('exec_status')} "
                  f"solver={rec.get('solver_status')} "
                  f"grade={rec.get('grade')} witness={rec.get('witness', '-')} "
                  f"calls={rec.get('llm_calls', '-')} "
                  f"t={rec.get('llm_s', '-')}s", flush=True)


if __name__ == "__main__":
    main()
