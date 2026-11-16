#!/usr/bin/env python3
"""Repair only invalid DVSA reference syntax without revealing public answers."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from ora_agent.dvsa_model import extract_json, solve_model, verify_sources  # noqa: E402
from scripts.dvsa_bwor_reference import load_rows  # noqa: E402

PROMPT = """You are repairing ONLY the formal syntax of an independent reference model.
The reference answer is intentionally hidden. Do not change the business requirements, quantities, inequality directions or objective to obtain a preferred result.
The compiler reported: {error}

Return one complete corrected dvsa.model.v0.1 JSON object. Keep the same problem_id and business model.
All add/mul/sub/div operands must be JSON arrays. Numeric constants can be written directly; every data.path must exist in data.
Every decision must be declared in variables. All constraints must retain exact source spans from the question.
Do not write Python or explanatory text.

[QUESTION]
{question}

[CURRENT MODEL]
{model}
"""


def render_prompt(error, question, model):
    return PROMPT.replace("{error}", error).replace("{question}", question).replace("{model}", model)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "validation", "frozen"], default="dev")
    parser.add_argument("--ids", nargs="+", required=True)
    parser.add_argument("--reference-dir")
    parser.add_argument("--time-limit", type=float, default=60.0)
    args = parser.parse_args()
    rows = {row["id"]: row for row in load_rows(args.split)}
    if set(args.ids) - set(rows):
        raise ValueError("all IDs must belong to the authorized non-frozen split")
    base = Path(args.reference_dir) if args.reference_dir else ROOT / f"work/dvsa/bwor_reference/{args.split}"
    if not base.is_absolute():
        base = ROOT / base
    config = llm_mod.load_config()
    for problem_id in args.ids:
        target = base / problem_id
        original = json.loads((target / "result.json").read_text())
        solve = original.get("solve", {})
        if solve.get("status") != "invalid_model":
            print(f"{problem_id}: skip_{original.get('status')}", flush=True)
            continue
        question = (target / "question.txt").read_text()
        model_text = (target / "model.json").read_text()
        prompt = render_prompt(solve.get("error", "invalid model"), question, model_text)
        started = time.monotonic()
        response = llm_mod.chat([{"role": "user", "content": prompt}],
                                max_tokens=32768, temperature=0.0,
                                extra={"reasoning_effort": "medium"}, config=config)
        (target / "syntax_response_r1.json").write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
        record = {"problem_id": problem_id, "split": args.split,
                  "revision": "syntax_only_r1", "llm_calls": 1,
                  "usage": response.get("usage"), "model": response.get("model"),
                  "original_status": original["status"], "original_error": solve.get("error"),
                  "reference_answer_hidden_from_prompt": True}
        try:
            model = extract_json(response.get("content"))
            if model.get("problem_id") != problem_id:
                raise ValueError("problem_id mismatch")
            (target / "model_syntax_r1.json").write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n")
            missing = verify_sources(model, question)
            record["missing_sources"] = missing
            if missing:
                record["status"] = "unverified_source"
            else:
                solved = solve_model(model, time_limit=args.time_limit)
                record["solve"] = solved
                if solved["status"] == "optimal":
                    (target / "solution_syntax_r1.json").write_text(json.dumps(solved["solution"], indent=2) + "\n")
                    error = abs(solved["solution"]["objective"] - float(rows[problem_id]["answer"]))
                    record["objective_absolute_error"] = error
                    record["status"] = ("candidate_reference_syntax_repair"
                                        if error <= 0.1 and solved["audit"]["verdict"] == "VALID"
                                        else "reference_conflict")
                else:
                    record["status"] = "solve_failed"
        except (ValueError, TypeError) as exc:
            record["status"] = "invalid_reference"
            record["error"] = str(exc)
        record["wall_s"] = round(time.monotonic() - started, 3)
        (target / "result_syntax_r1.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        print(f"{problem_id}: {record['status']} error={record.get('objective_absolute_error', 'NA')}", flush=True)


if __name__ == "__main__":
    main()
