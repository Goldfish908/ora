#!/usr/bin/env python3
"""Author independent scalar BWOR reference models on non-frozen splits only."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from ora_agent.dvsa_model import (extract_json, solve_model,  # noqa: E402
                                  validate_model, verify_sources)

SOURCE = ROOT / "data/external/or_llm_agent/data/datasets/bwor.jsonl"
PROMPT = """You are the independent reference author for a natural-language optimization problem.
You have NOT seen any candidate answer, candidate solver code, learned memory clause, or semantic witness.
Construct the mathematical model from the problem itself. Do not invent requirements to obtain a preferred objective.

Return exactly one JSON object with this structure:
{
 "schema_version": "dvsa.model.v0.1",
 "problem_id": "{problem_id}",
 "variables": {"x": {"domain": "real|integer|binary", "lb": 0, "ub": null}},
 "data": {"constant_name": 1.0},
 "constraints": [
   {"constraint_id": "C01", "source": "an exact verbatim span from the problem",
    "relation": "le|ge|eq", "lhs": {"add": [{"var": "x"}]}, "rhs": {"path": "data.constant_name"}}
 ],
 "objective": {"sense": "minimize|maximize", "expression": {"var": "x"}},
 "assumptions": ["every modeling convention or ambiguity, including missing table cells"],
 "modeling_conflicts": ["any unresolved source ambiguity; empty if none"]
}

Rules:
- Use only scalar decision variables and linear arithmetic. Expand small indexed sums so every decision term uses {"var": "declared_variable_name"} directly. Do not refer to decisions through strings in data or lookup tables.
- Expressions may be numeric constants or single-operator objects: var, path, add, sub, mul, div, neg, abs, round, index, lookup, sum. The solver accepts only linear expressions; do not multiply or divide decision variables.
- Arguments to add, mul, sub, div and comparisons are ALWAYS JSON arrays, even with only two operands. For example, write {"mul": [2, {"var": "x"}]}, not {"mul": {"var": "x"}}. Numeric constants may be written directly instead of inventing paths such as data.one.
- Use data.path for numeric constants. All data must be numeric JSON scalars/lists/objects. Variable lower bounds are explicit; omit ub or use null for no upper bound.
- Every explicit requirement must have a constraint with a source span of at least 8 characters copied verbatim from the problem. Normalize whitespace only when matching; do not paraphrase the source span.
- Respect units, percentages, strict/indivisible quantities and the direction of every inequality. Use only le/ge/eq constraints.
- Do not include a reference answer or target objective in the model. Do not write executable Python.
- If the source is under-specified, retain only justified requirements and explain the ambiguity in assumptions/modeling_conflicts. Never fabricate a table value.

[PROBLEM]
{question}
"""


def load_rows(split):
    allowed = set((ROOT / f"data/dvsa/bwor/{split}.txt").read_text().splitlines())
    rows = []
    for line in SOURCE.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row["id"]) in allowed:
            rows.append(row)
    return sorted(rows, key=lambda row: str(row["id"]))


def render_prompt(problem_id, question):
    return PROMPT.replace("{problem_id}", problem_id).replace("{question}", question)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "validation", "frozen"], default="dev")
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--solve", action="store_true")
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()
    rows = load_rows(args.split)
    if args.ids:
        selected = set(args.ids)
        unknown = selected - {row["id"] for row in rows}
        if unknown:
            raise ValueError(f"IDs outside authorized {args.split} split: {sorted(unknown)}")
        rows = [row for row in rows if row["id"] in selected]
    if args.limit:
        rows = rows[:args.limit]
    out = Path(args.out) if args.out else ROOT / f"work/dvsa/bwor_reference/{args.split}"
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    config = llm_mod.load_config()
    for row in rows:
        problem_id = str(row["id"])
        target = out / problem_id
        target.mkdir(parents=True, exist_ok=True)
        result_path = target / "result.json"
        if args.resume and result_path.exists():
            print(f"{problem_id}: resume_skip", flush=True)
            continue
        question = row["en_question"]
        prompt = render_prompt(problem_id, question)
        (target / "question.txt").write_text(question)
        (target / "prompt.txt").write_text(prompt)
        started = time.monotonic()
        response = llm_mod.chat([{"role": "user", "content": prompt}],
                                max_tokens=32768, temperature=args.temperature,
                                extra={"reasoning_effort": "medium"}, config=config)
        record = {"problem_id": problem_id, "split": args.split,
                  "model": response.get("model"), "usage": response.get("usage"),
                  "finish_reason": response.get("finish_reason"),
                  "llm_latency_s": round(response.get("latency_s", 0), 3),
                  "llm_calls": 1, "reference_answer_hidden_from_prompt": True}
        (target / "response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
        try:
            model = extract_json(response.get("content"))
            if model.get("problem_id") != problem_id:
                raise ValueError("problem_id does not match authorized source row")
            validate_model(model)
            (target / "model.json").write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n")
            missing_sources = verify_sources(model, question)
            record["missing_sources"] = missing_sources
            if missing_sources:
                record["status"] = "unverified_source"
            else:
                record["status"] = "authored_not_solved"
                if args.solve:
                    solve_started = time.monotonic()
                    solved = solve_model(model, time_limit=args.time_limit)
                    record["solve"] = solved
                    record["solve_wall_s"] = round(time.monotonic() - solve_started, 3)
                    if solved["status"] == "optimal":
                        (target / "solution.json").write_text(json.dumps(solved["solution"], indent=2) + "\n")
                        answer = float(row["answer"])
                        predicted = solved["solution"]["objective"]
                        record["public_answer"] = answer
                        record["objective_absolute_error"] = abs(predicted - answer)
                        record["objective_correct_abs_0_1"] = abs(predicted - answer) <= 0.1
                        if record["objective_correct_abs_0_1"] and solved["audit"]["verdict"] == "VALID":
                            record["status"] = "candidate_reference"
                        else:
                            record["status"] = "reference_conflict"
                    else:
                        record["status"] = "solve_failed"
        except (ValueError, TypeError) as exc:
            record["status"] = "invalid_reference"
            record["error"] = str(exc)
        record["wall_s"] = round(time.monotonic() - started, 3)
        result_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        print(f"{problem_id}: {record['status']} "
              f"objective_error={record.get('objective_absolute_error', 'NA')} "
              f"missing_sources={len(record.get('missing_sources', []))}", flush=True)


if __name__ == "__main__":
    main()
