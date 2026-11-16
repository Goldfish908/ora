#!/usr/bin/env python3
"""Blind-to-candidate triage of NLP4LP expert/reference consistency."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod
from scripts.mamo_witness_author import parse_json

PROMPT = """You are auditing the internal consistency of an optimization benchmark REFERENCE, not any candidate checker.
You see the natural-language problem, the expert formulation metadata, and the expert solution. You do NOT see any candidate witness output.

Decide whether the reference can safely serve as a clean semantic label:
- "consistent": formulation and solution are consistent with each other and with the natural language;
- "ambiguous": there is a real semantic conflict/under-specification (strict > encoded as >=, integer/countable wording but continuous expert variables, constraint direction conflicts, etc.), so the sample must be reviewed separately;
- "inconsistent": expert formulation or solution is clearly wrong, unbounded, or pathological.

Do not call something inconsistent merely because a different valid modeling convention exists. Distinguish reference problems from mistakes a candidate checker might make (e.g. summing a makespan objective).

Reply with exactly one JSON object:
{{"label": "consistent|ambiguous|inconsistent",
 "category": "strict_inequality|variable_type|constraint_direction|objective_mismatch|unbounded_or_pathological|other|none",
 "reason": "one sentence citing the concrete conflict",
 "evidence": "an exact short quote from the natural-language problem or expert code"}}

[NATURAL LANGUAGE]
{question}

[PROBLEM TYPE]
{problem_type}

[EXPERT FORMULATION]
{info}

[EXPERT SOLUTION]
{solution}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    source = ROOT / "data/external/ORThought/datasets/processed/NLP4LP/nlp4lp.csv"
    with source.open(newline="", encoding="utf-8") as f:
        rows = {r["id"]: r for r in csv.DictReader(f)}
    cfg = llm_mod.load_config()
    with Path(args.out).open("w") as out:
        for pid in args.ids:
            row = rows[pid]
            info = json.loads(row["problem_info"])
            solution = json.loads(row["solution"])
            resp = llm_mod.chat([{"role": "user", "content": PROMPT.format(
                question=row["description"], problem_type=row["problem_type"],
                info=json.dumps(info, ensure_ascii=False),
                solution=json.dumps(solution, ensure_ascii=False))}],
                max_tokens=4096, temperature=0.0,
                extra={"chat_template_kwargs": {"enable_thinking": False}}, config=cfg)
            rec = parse_json(resp.get("content") or "")
            result = {"id": pid, "review": rec, "usage": resp.get("usage"),
                      "expected_clean": row["problem_type"]}
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            out.flush()
            print(pid, (rec or {}).get("label"), (rec or {}).get("category"),
                  (rec or {}).get("reason"), flush=True)


if __name__ == "__main__":
    main()
