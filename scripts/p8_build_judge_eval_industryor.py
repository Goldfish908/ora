#!/usr/bin/env python3
"""P8: build judge eval cells for IndustryOR (cross-dataset L3 eval).

The judge was trained only on RetailOpt F1-F4 cells, so IndustryOR is a true
cross-dataset transfer test. Input format follows the TRAINING prompt
(JUDGE_PROMPT) — the model is an artifact trained on that format; what must
NOT be hardcoded is the RetailOpt-specific solution digest, so [SOLUTION]
carries only a generic digest (returned objective; reference is never shown,
it defines the label).

Labels: cell-level `wrong` from the IndustryOR harness (objective-vs-reference
mismatch, 234/240 consistent with direct recomputation).

Output: work/judge_data/eval_industryor.jsonl, same {key, wrong, system, user}
schema as eval_v3.jsonl / eval_f5f8.jsonl.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CELLS = ROOT / "runs" / "industryor" / "industryor_judge_cells.jsonl"
OUT = ROOT / "work" / "judge_data" / "eval_industryor.jsonl"

import sys
sys.path.insert(0, str(ROOT))
from scripts.p5_judge_rs import JUDGE_PROMPT  # noqa: E402

GENERIC_DATA_NOTE = "N/A - instance parameters are embedded in the problem statement and the model code below."


def main() -> None:
    rows = [json.loads(l) for l in CELLS.read_text().splitlines()]
    cells = []
    for r in rows:
        sol_digest = {"objective": r.get("objective")}
        user = JUDGE_PROMPT.format(
            prompt=(r.get("prompt") or "")[:4000],
            data_digest=GENERIC_DATA_NOTE,
            code=(r.get("code") or "")[:4000],
            solution_digest=json.dumps(sol_digest, ensure_ascii=False))
        cells.append({
            "key": f"industryor_{r['arm']}_{r['id']}|real|{r.get('difficulty')}|{'wrong' if r['wrong'] else 'correct'}",
            "wrong": bool(r["wrong"]),
            "system": "",
            "user": user,
        })
    with OUT.open("w") as f:
        for c in cells:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"cells: {len(cells)}")
    print("by label:", Counter(c["wrong"] for c in cells))
    print("by arm/label:", sorted(Counter(
        (c["key"].split("_")[1], c["wrong"]) for c in cells).items()))


if __name__ == "__main__":
    main()
