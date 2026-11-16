#!/usr/bin/env python3
"""Blind LLM review of saved RetailOpt solutions with and without asset text."""
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
from ora_agent.dvsa_model import extract_json  # noqa: E402
from scripts.dvsa_llm_judge import evaluate_verdicts  # noqa: E402
from scripts.dvsa_retail_core import business_score, load_assets  # noqa: E402

PROMPT = """Audit one returned optimization solution against the business problem and data.
The artifact ID is opaque and carries no correctness label. You have NOT seen the reference objective, a reference solution, or a witness verdict.
Do not infer correctness from a better objective or solver success. Use concrete numeric evidence for every violation.

[BUSINESS PROBLEM]
{problem}

[DATA]
{data}

[SOLUTION]
{solution}

[TEXT MEMORY]
{memory}

Return exactly one JSON object:
{{"verdicts": [{{"artifact_id": "{artifact_id}", "verdict": "VALID|INVALID|UNKNOWN", "violations": [{{"rule": "short_rule", "detail": "concrete numeric evidence with lhs/rhs where applicable"}}]}}]}}
Use INVALID only for genuine requirement violations, not code/style preferences. Use UNKNOWN when the schema or evidence is insufficient. Do not output Python or explanations outside JSON.
"""


def eligible_artifacts(baseline_path, sandbox_root):
    rows = [json.loads(line) for line in baseline_path.read_text().splitlines() if line.strip()]
    rows.sort(key=lambda row: row["scenario_id"])
    problems = {}
    for line in (ROOT / "work/mem_evo/dev40_rows.jsonl").read_text().splitlines():
        row = json.loads(line)
        problems[row["scenario_id"]] = row["prompt_schema"]
    artifacts = []
    for row in rows:
        scenario = row["scenario_id"]
        directory = sandbox_root / f"schema_sol__{scenario}__on"
        solution_path = directory / "solution.json"
        if not solution_path.exists():
            continue
        data = json.loads((directory / "data.json").read_text())
        solution = json.loads(solution_path.read_text())
        score = business_score(data, row["reference_objective"], solution)
        if not score["semantic_valid"] and not score["business_correct"]:
            wrong = True
        elif score["business_correct"]:
            wrong = False
        else:
            continue
        artifact_id = hashlib.sha256((scenario + json.dumps(solution, sort_keys=True)).encode()).hexdigest()[:12]
        rules = sorted({rule for rule, _ in score["legacy_reference_audit"]["violations"]})
        artifacts.append({"artifact_id": f"A_{artifact_id}", "original_key": scenario,
                          "original_keys": [scenario], "wrong": wrong,
                          "expected_rule": rules[0] if rules else None,
                          "expected_rules": rules, "solution": solution,
                          "data": data, "problem": problems[scenario],
                          "initial_score": score})
    return artifacts


def render_prompt(artifact, memory):
    serialized = json.dumps(artifact["data"], ensure_ascii=False)
    if "reference_objective" in serialized:
        raise ValueError("reference objective leaked into judge data")
    return PROMPT.replace("{problem}", artifact["problem"]).replace(
        "{data}", serialized).replace("{solution}", json.dumps(artifact["solution"], ensure_ascii=False)).replace(
        "{memory}", memory).replace("{artifact_id}", artifact["artifact_id"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="work/mem_evo/replay_gen1/m1_pilot_schema_sol_gen1.jsonl")
    parser.add_argument("--sandbox-root", default="work/mem_evo/replay_gen1/sandbox")
    parser.add_argument("--out", default="work/dvsa/retailopt_llm_judge")
    parser.add_argument("--arms", nargs="+", choices=["no_memory", "text_memory"], default=["no_memory", "text_memory"])
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--shard", nargs=2, type=int, metavar=("INDEX", "COUNT"))
    parser.add_argument("--thinking", choices=["off", "medium"], default="off")
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    baseline = Path(args.baseline)
    sandbox_root = Path(args.sandbox_root)
    out = Path(args.out)
    if not baseline.is_absolute():
        baseline = ROOT / baseline
    if not sandbox_root.is_absolute():
        sandbox_root = ROOT / sandbox_root
    if not out.is_absolute():
        out = ROOT / out
    artifacts = eligible_artifacts(baseline, sandbox_root)
    if args.ids:
        selected = set(args.ids)
        artifacts = [row for row in artifacts if row["original_key"] in selected]
    if args.shard:
        index, count = args.shard
        if not 0 <= index < count:
            raise ValueError("shard requires 0 <= index < count")
        artifacts = artifacts[index::count]
    assets, _ = load_assets()
    memory = "\n\n".join(asset["text"] for asset in assets)
    config = llm_mod.load_config()
    for artifact in artifacts:
        scenario = artifact["original_key"]
        for arm in args.arms:
            target = out / scenario / arm
            target.mkdir(parents=True, exist_ok=True)
            result_path = target / "result.json"
            if args.resume and result_path.exists():
                print(f"{scenario}/{arm}: resume_skip", flush=True)
                continue
            prompt = render_prompt(artifact, memory if arm == "text_memory" else "")
            (target / "prompt.txt").write_text(prompt)
            started = time.monotonic()
            extra = ({"chat_template_kwargs": {"enable_thinking": False}}
                     if args.thinking == "off" else {"reasoning_effort": "medium"})
            response = llm_mod.chat([{"role": "user", "content": prompt}],
                                    max_tokens=args.max_tokens, temperature=0.0,
                                    extra=extra, config=config)
            (target / "response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
            try:
                proposal = extract_json(response.get("content"))
                summary, records = evaluate_verdicts([artifact], proposal)
                status, error = "evaluated", None
            except (ValueError, TypeError) as exc:
                summary = {"artifacts": 1, "detection": 0, "false_positive": 0, "unknown": 1}
                records = []
                status, error = "invalid_judge_response", str(exc)
            result = {"scenario_id": scenario, "arm": arm, "status": status, "error": error,
                      "summary": summary, "llm_calls": 1, "usage": response.get("usage"),
                      "llm_latency_s": response.get("latency_s"),
                      "wall_s": round(time.monotonic() - started, 3),
                      "thinking": args.thinking, "max_tokens": args.max_tokens,
                      "input_contract": {"opaque_id": True, "labels_hidden": True,
                                         "reference_objective_hidden": True,
                                         "reference_solution_hidden": True}}
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            (target / "cells.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records))
            print(f"{scenario}/{arm}: {json.dumps(summary, ensure_ascii=False)}", flush=True)


if __name__ == "__main__":
    main()
