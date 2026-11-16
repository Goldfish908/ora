#!/usr/bin/env python3
"""Generate one shared initial candidate for all DVSA repair arms."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from ora_agent.dvsa_model import (extract_json, normalize_candidate,  # noqa: E402
                                  normalize_candidate_paths, solve_model,
                                  validate_candidate_paths, validate_model)
from ora_agent.dvsa_repair import schema_errors, score_solution  # noqa: E402
from scripts.dvsa_bwor_reference import load_rows  # noqa: E402
from scripts.dvsa_reference_select import select_reference  # noqa: E402

PROMPT = """Generate an optimization model from the natural-language problem and the shared variable schema.
You have not seen any independent reference model, public answer, learned memory clause, or semantic witness.
Every compared repair arm will start from your returned model, so produce a complete best-effort candidate rather than reviewing a reference.

Return exactly one dvsa.model.v0.1 JSON object with:
- schema_version equal to "dvsa.model.v0.1";
- problem_id equal to {problem_id};
- variables exactly matching the supplied declarations in names, domains, lb and ub;
- numeric data constants;
- constraints as objects with constraint_id, source, relation (le/ge/eq), lhs and rhs;
- objective with sense (minimize/maximize) and expression;
- assumptions and modeling_conflicts lists.

Expressions use numeric constants or single-operator objects: var, path, add, sub, mul, div, neg, abs, round, index, lookup, sum. Every decision term uses {"var": "declared_variable_name"}. Arguments to add/mul/sub/div are ALWAYS JSON arrays. Use linear arithmetic only. Each data.path must exist in data.
Each constraint source should be an exact problem span. Cover every explicit requirement and derive the objective from stated coefficients. Do not write Python or a preferred target objective.

[PROBLEM]
{question}

[SHARED VARIABLE SCHEMA]
{schema}
"""


def render_prompt(problem_id, question, schema):
    return PROMPT.replace("{problem_id}", problem_id).replace("{question}", question).replace("{schema}", schema)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "validation", "frozen"], default="dev")
    parser.add_argument("--ids", nargs="+", required=True)
    parser.add_argument("--out")
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    answers = {row["id"]: float(row["answer"]) for row in load_rows(args.split)}
    out = Path(args.out) if args.out else ROOT / f"work/dvsa/bwor_repair/{args.split}"
    if not out.is_absolute():
        out = ROOT / out
    config = llm_mod.load_config()
    for problem_id in args.ids:
        reference = select_reference(args.split, problem_id)
        target = out / problem_id / "initial"
        target.mkdir(parents=True, exist_ok=True)
        result_path = target / "result.json"
        if args.resume and result_path.exists():
            print(f"{problem_id}: resume_skip", flush=True)
            continue
        schema = json.dumps(reference["model"]["variables"], ensure_ascii=False, indent=2)
        prompt = render_prompt(problem_id, reference["question"], schema)
        (target / "prompt.txt").write_text(prompt)
        started = time.monotonic()
        response = llm_mod.chat([{"role": "user", "content": prompt}],
                                max_tokens=32768, temperature=0.0,
                                extra={"reasoning_effort": "medium"}, config=config)
        (target / "response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
        record = {"problem_id": problem_id, "split": args.split,
                  "reference_schema_revision": reference["revision"],
                  "llm_calls": 1, "usage": response.get("usage"),
                  "llm_latency_s": response.get("latency_s"),
                  "public_answer_hidden_from_prompt": True}
        try:
            candidate = extract_json(response.get("content"))
            candidate = normalize_candidate(candidate)
            if candidate.get("problem_id") != problem_id:
                raise ValueError("problem_id mismatch")
            validate_model(candidate)
            candidate, path_normalizations = normalize_candidate_paths(candidate)
            record["path_normalizations"] = path_normalizations
            validate_candidate_paths(candidate)
            errors = schema_errors(candidate, reference["model"]["variables"])
            (target / "candidate.json").write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")
            if errors:
                record["status"] = "invalid_shared_schema"
                record["schema_errors"] = errors
            else:
                solved = solve_model(candidate, time_limit=args.time_limit)
                record["solve"] = solved
                if solved["status"] == "optimal":
                    (target / "solution.json").write_text(json.dumps(solved["solution"], indent=2) + "\n")
                    record["score"] = score_solution(reference, solved["solution"], answers[problem_id])
                    record["status"] = "initial_scored"
                else:
                    record["status"] = "solve_failed"
        except (ValueError, TypeError) as exc:
            record["status"] = "contract_invalid"
            record["error"] = str(exc)
        record["wall_s"] = round(time.monotonic() - started, 3)
        result_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        print(f"{problem_id}: {record['status']} "
              f"business={record.get('score', {}).get('business_correct')}", flush=True)


if __name__ == "__main__":
    main()
