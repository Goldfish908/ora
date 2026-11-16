#!/usr/bin/env python3
"""Blind no-memory versus text-memory LLM review of identical DVSA artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from ora_agent.dvsa_model import extract_json  # noqa: E402
from ora_agent.dvsa_templates import load_library  # noqa: E402
from scripts.dvsa_reference_select import select_reference  # noqa: E402
from scripts.dvsa_template_audit import controlled_mutations  # noqa: E402

PROMPT = """You are auditing returned optimization solutions against the natural-language requirements.
Judge each artifact independently. Do not infer correctness from artifact IDs, ordering, objective quality, or whether a solver might have produced it.
A better objective is not evidence of feasibility. A script/schema failure is UNKNOWN, not a business violation.

[PROBLEM]
{question}

[SHARED VARIABLE SCHEMA]
{schema}

{memory_block}

[ARTIFACTS]
{artifacts}

Return exactly one JSON object:
{{"verdicts": [{{"artifact_id": "opaque_ID", "verdict": "VALID|INVALID|UNKNOWN", "violations": [{{"rule": "short_rule", "detail": "concrete numeric evidence, including lhs/rhs where applicable"}}]}}]}}
Include every input artifact exactly once. Use INVALID only for a genuine requirement violation supported by numeric evidence. Do not output Python or explanatory text outside JSON.
"""


def public_artifacts(reference):
    cells = controlled_mutations(reference["model"], reference["solution"])
    grouped = {}
    for cell in cells:
        encoded = json.dumps(cell["solution"], sort_keys=True).encode()
        opaque = f"A_{hashlib.sha256(encoded).hexdigest()[:12]}"
        if opaque not in grouped:
            grouped[opaque] = {"artifact_id": opaque, "original_key": cell["key"],
                               "original_keys": [cell["key"]], "wrong": cell["wrong"],
                               "expected_rule": cell["expected_rule"],
                               "expected_rules": [cell["expected_rule"]],
                               "solution": cell["solution"]}
        else:
            grouped[opaque]["original_keys"].append(cell["key"])
            grouped[opaque]["expected_rules"].append(cell["expected_rule"])
            grouped[opaque]["wrong"] = grouped[opaque]["wrong"] or cell["wrong"]
    rows = list(grouped.values())
    random.Random(f"dvsa-judge-v0.1:{reference['model']['problem_id']}").shuffle(rows)
    return rows


def render_prompt(reference, artifacts, memory):
    schema = json.dumps(reference["model"]["variables"], ensure_ascii=False, indent=2)
    public = [{"artifact_id": row["artifact_id"], **row["solution"]} for row in artifacts]
    memory_block = "[TEXT MEMORY]\n" + memory if memory else "[TEXT MEMORY]\nNone."
    return PROMPT.replace("{question}", reference["question"]).replace(
        "{schema}", schema).replace("{memory_block}", memory_block).replace(
        "{artifacts}", json.dumps(public, ensure_ascii=False, indent=2))


def evaluate_verdicts(artifacts, proposal):
    supplied = proposal.get("verdicts", []) if isinstance(proposal, dict) else []
    supplied = supplied if isinstance(supplied, list) else []
    by_id, counts = {}, {}
    for row in supplied:
        if isinstance(row, dict) and isinstance(row.get("artifact_id"), str):
            artifact_id = row["artifact_id"]
            by_id[artifact_id] = row
            counts[artifact_id] = counts.get(artifact_id, 0) + 1
    records = []
    for artifact in artifacts:
        verdict_row = by_id.get(artifact["artifact_id"], {})
        verdict = str(verdict_row.get("verdict", "UNKNOWN")).upper()
        violations = verdict_row.get("violations", [])
        evidence_ok = any(isinstance(item, dict) and re.search(r"\d", str(item.get("detail", "")))
                          for item in violations) if isinstance(violations, list) else False
        if counts.get(artifact["artifact_id"], 0) > 1:
            verdict = "UNKNOWN"
            reason = "duplicate_artifact_id"
        elif verdict == "VALID" and violations:
            verdict = "UNKNOWN"
            reason = "valid_with_reported_violations"
        elif verdict == "INVALID" and not evidence_ok:
            verdict = "UNKNOWN"
            reason = "invalid_without_numeric_evidence"
        elif verdict not in {"VALID", "INVALID", "UNKNOWN"}:
            verdict = "UNKNOWN"
            reason = "invalid_verdict"
        else:
            reason = None
        detected = verdict == "INVALID"
        records.append({"artifact_id": artifact["artifact_id"], "original_key": artifact["original_key"],
                        "original_keys": artifact["original_keys"],
                        "wrong": artifact["wrong"], "expected_rule": artifact["expected_rule"],
                        "expected_rules": artifact["expected_rules"],
                        "verdict": verdict, "detected": detected,
                        "false_positive": not artifact["wrong"] and detected,
                        "unknown": verdict == "UNKNOWN", "reason": reason,
                        "llm_violations": violations})
    wrong = [row for row in records if row["wrong"]]
    clean = [row for row in records if not row["wrong"]]
    input_ids = {row["artifact_id"] for row in artifacts}
    supplied_ids = set(counts)
    duplicates = sum(count - 1 for count in counts.values())
    return {"artifacts": len(records), "wrong": len(wrong),
            "detection": sum(row["detected"] for row in wrong) / max(len(wrong), 1),
            "detected_n": sum(row["detected"] for row in wrong),
            "false_positive": sum(row["false_positive"] for row in clean) / max(len(clean), 1),
            "false_positive_n": sum(row["false_positive"] for row in clean),
            "unknown": sum(row["unknown"] for row in records),
            "missing_or_duplicate_ids": len(input_ids - supplied_ids) + duplicates,
            "extra_ids": len(supplied_ids - input_ids)}, records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "validation", "frozen"], default="dev")
    parser.add_argument("--ids", nargs="+", required=True)
    parser.add_argument("--arms", nargs="+", choices=["no_memory", "text_memory"],
                        default=["no_memory", "text_memory"])
    parser.add_argument("--library", default="assets/dvsa/bwor_primitives_v0.1.json")
    parser.add_argument("--out")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    library_path = Path(args.library)
    if not library_path.is_absolute():
        library_path = ROOT / library_path
    _, templates = load_library(library_path)
    memory = "\n\n".join(asset["text"] for _, asset in sorted(templates.items()))
    out = Path(args.out) if args.out else ROOT / f"work/dvsa/bwor_llm_judge/{args.split}"
    if not out.is_absolute():
        out = ROOT / out
    config = llm_mod.load_config()
    for problem_id in args.ids:
        reference = select_reference(args.split, problem_id)
        artifacts = public_artifacts(reference)
        for arm in args.arms:
            target = out / problem_id / arm
            target.mkdir(parents=True, exist_ok=True)
            result_path = target / "result.json"
            if args.resume and result_path.exists():
                print(f"{problem_id}/{arm}: resume_skip", flush=True)
                continue
            prompt = render_prompt(reference, artifacts, memory if arm == "text_memory" else "")
            (target / "prompt.txt").write_text(prompt)
            started = time.monotonic()
            response = llm_mod.chat([{"role": "user", "content": prompt}],
                                    max_tokens=32768, temperature=0.0,
                                    extra={"reasoning_effort": "medium"}, config=config)
            (target / "response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
            try:
                proposal = extract_json(response.get("content"))
                summary, records = evaluate_verdicts(artifacts, proposal)
                status = "evaluated"
                error = None
            except (ValueError, TypeError) as exc:
                summary = {"artifacts": len(artifacts), "detection": 0, "false_positive": 0,
                           "unknown": len(artifacts)}
                records = []
                status = "invalid_judge_response"
                error = str(exc)
            result = {"problem_id": problem_id, "split": args.split, "arm": arm,
                      "status": status, "error": error, "summary": summary,
                      "llm_calls": 1, "usage": response.get("usage"),
                      "llm_latency_s": response.get("latency_s"),
                      "wall_s": round(time.monotonic() - started, 3),
                      "input_contract": {"opaque_shuffled_artifact_ids": True,
                                         "labels_hidden": True, "public_answer_hidden": True,
                                         "reference_constraints_hidden": True,
                                         "shared_schema": True}}
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            (target / "cells.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records))
            print(f"{problem_id}/{arm}: {json.dumps(summary, ensure_ascii=False)}", flush=True)


if __name__ == "__main__":
    main()
