#!/usr/bin/env python3
"""Aggregate the four fixed-artifact arms with unique solutions and paired tests."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dvsa_llm_judge import public_artifacts  # noqa: E402
from scripts.dvsa_reference_select import select_reference  # noqa: E402

IDS = ["BWOR-001", "BWOR-011", "BWOR-042", "BWOR-043", "BWOR-062", "BWOR-066", "BWOR-069"]
ARMS = ["no_memory", "text_memory", "dvsa", "direct_legacy_witness"]


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def metrics(cells):
    wrong = [row for row in cells if row["wrong"]]
    clean = [row for row in cells if not row["wrong"]]
    return {"artifacts": len(cells), "wrong": len(wrong), "clean": len(clean),
            "detected_n": sum(row["detected"] for row in wrong),
            "detection": sum(row["detected"] for row in wrong) / max(len(wrong), 1),
            "false_positive_n": sum(row["false_positive"] for row in clean),
            "false_positive": sum(row["false_positive"] for row in clean) / max(len(clean), 1),
            "unknown": sum(row["unknown"] for row in cells)}


def pair(cells_a, cells_b, field):
    a = {row["artifact_id"]: bool(row[field]) for row in cells_a}
    b = {row["artifact_id"]: bool(row[field]) for row in cells_b}
    assert set(a) == set(b)
    only_a = sum(a[key] and not b[key] for key in a)
    only_b = sum(b[key] and not a[key] for key in a)
    return {"a_only": only_a, "b_only": only_b,
            "mcnemar_exact_p": mcnemar_exact(only_a, only_b)}


def judge_cells(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [{**row, "unknown": bool(row["unknown"])} for row in rows]


def dvsa_cells(reference, evaluation):
    artifacts = public_artifacts(reference)
    by_key = {(row.get("original_key") or row["key"]): row for row in evaluation["cells"]}
    output = []
    for artifact in artifacts:
        matches = [by_key[key] for key in artifact["original_keys"]]
        detected = any(row["detected"] for row in matches)
        unknown = any(status == "UNKNOWN" for row in matches
                      for status in row["candidate_statuses"].values()) and not detected
        output.append({"artifact_id": artifact["artifact_id"], "original_key": artifact["original_key"],
                       "wrong": artifact["wrong"], "expected_rule": artifact["expected_rule"],
                       "detected": detected, "false_positive": not artifact["wrong"] and detected,
                       "unknown": unknown, "verdict": "INVALID" if detected else "UNKNOWN" if unknown else "VALID"})
    return output


def load_problem(split, problem_id, judge_root, dedup_root):
    reference = select_reference(split, problem_id)
    artifacts = public_artifacts(reference)
    cells = {}
    costs = {}
    for arm in ("no_memory", "text_memory"):
        source = dedup_root / problem_id / arm
        if not source.exists():
            source = judge_root / problem_id / arm
        result = json.loads((source / "result.json").read_text())
        rows = judge_cells(source / "cells.jsonl")
        cells[arm] = rows
        costs[arm] = {"generation_llm_calls": result.get("original_generation_llm_calls", result.get("llm_calls", 0)),
                      "incremental_llm_calls": result.get("llm_calls", 0),
                      "usage": result.get("original_usage", result.get("usage")),
                      "latency_s": result.get("original_llm_latency_s", result.get("llm_latency_s")),
                      "response_status": result["status"]}
    evaluation = json.loads((ROOT / f"work/dvsa/bwor_binding_eval/{split}/{problem_id}/evaluation.json").read_text())
    cells["dvsa"] = dvsa_cells(reference, evaluation)
    authoring = evaluation["authoring"]
    costs["dvsa"] = {"generation_llm_calls": authoring["llm_calls"], "incremental_llm_calls": 0,
                     "usage": authoring.get("usage"), "latency_s": authoring.get("llm_latency_s"),
                     "response_status": "fresh_binding_author"}
    cells["direct_legacy_witness"] = [
        {"artifact_id": row["artifact_id"], "original_key": row["original_key"],
         "wrong": row["wrong"], "expected_rule": row["expected_rule"],
         "detected": False, "false_positive": False, "unknown": True,
         "verdict": "UNKNOWN", "reason": "unknown_schema_retailopt"} for row in artifacts]
    costs["direct_legacy_witness"] = {"generation_llm_calls": 0, "incremental_llm_calls": 0,
                                      "usage": {}, "latency_s": 0, "response_status": "not_applicable_schema"}
    assert all(len(cells[arm]) == len(artifacts) for arm in ARMS)
    return {"problem_id": problem_id, "reference_revision": reference["revision"],
            "cells": cells, "costs": costs,
            "behavioral_rule_coverage": evaluation["summary"]["behavioral_rule_coverage"]}


def usage_totals(costs):
    usage = [cost.get("usage") or {} for cost in costs.values()]
    return {"prompt_tokens": sum(item.get("prompt_tokens", 0) or 0 for item in usage),
            "completion_tokens": sum(item.get("completion_tokens", 0) or 0 for item in usage),
            "total_tokens": sum(item.get("total_tokens", 0) or 0 for item in usage)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "validation", "frozen"], default="dev")
    parser.add_argument("--ids", nargs="+", default=IDS)
    parser.add_argument("--judge-root", default="work/dvsa/bwor_llm_judge/dev")
    parser.add_argument("--dedup-root", default="work/dvsa/bwor_llm_judge_dedup/dev")
    parser.add_argument("--out", default="work/dvsa/bwor_fixed_arms_dev")
    parser.add_argument("--figure", default="/home/hewj13/paper_icml2027/figures/dvsa_bwor_dev_fixed_arms.png")
    args = parser.parse_args()
    judge_root, dedup_root = ROOT / args.judge_root, ROOT / args.dedup_root
    problems = [load_problem(args.split, problem_id, judge_root, dedup_root) for problem_id in args.ids]
    combined = {arm: [row for problem in problems for row in problem["cells"][arm]] for arm in ARMS}
    arm_metrics = {arm: metrics(combined[arm]) for arm in ARMS}
    comparisons = {}
    for other in ("no_memory", "text_memory", "direct_legacy_witness"):
        comparisons[f"dvsa_vs_{other}"] = {
            "wrong_detection": pair(combined["dvsa"], combined[other], "detected"),
            "clean_false_positive": pair(combined["dvsa"], combined[other], "false_positive")}
    per_problem = []
    for problem in problems:
        row = {"problem_id": problem["problem_id"], "reference_revision": problem["reference_revision"],
               "behavioral_rule_coverage": problem["behavioral_rule_coverage"],
               "arms": {arm: metrics(problem["cells"][arm]) for arm in ARMS},
               "costs": problem["costs"]}
        per_problem.append(row)
    costs = {arm: {"generation_llm_calls": sum(problem["costs"][arm]["generation_llm_calls"] for problem in problems),
                   "incremental_llm_calls": sum(problem["costs"][arm]["incremental_llm_calls"] for problem in problems),
                   "latency_s": round(sum((problem["costs"][arm]["latency_s"] or 0) for problem in problems), 3),
                   **usage_totals({problem_id: problem["costs"][arm] for problem_id, problem in enumerate(problems)})}
             for arm in ARMS}
    result = {
        "protocol": f"dvsa-bwor-fixed-four-arm-{args.split}-v0.1",
        "scope": f"{len(args.ids)} reference-qualified BWOR {args.split} problems; conditional on shared reference variable schema; not end-to-end repair or full-cohort accuracy.",
        "unique_solution_artifacts": True,
        "problem_ids": args.ids,
        "arms": arm_metrics,
        "comparisons": comparisons,
        "costs": costs,
        "per_problem": per_problem,
        "cells": combined,
        "notes": [
            "DVSA bindings were authored without reference constraints/objective/answer, but share the reference variable declarations.",
            ("BWOR-011/042 text judgments are re-evaluations of saved responses after duplicate-solution removal, not fresh samples."
             if args.split == "dev" else f"All {args.split} judgments are fresh generations; no saved dev responses are reused."),
            "Direct legacy witness is a negative control: RetailOpt schema is incompatible, so all artifacts are UNKNOWN.",
            "Fixed-artifact McNemar is exploratory; final claims require per-question end-to-end frozen evaluation.",
        ],
    }
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 4, figsize=(15, 4.2))
    labels = ["No\nmemory", "Text\nmemory", "DVSA", "Legacy\nwitness"]
    colors = ["#94a3b8", "#f59e0b", "#0f766e", "#cbd5e1"]
    for axis, metric, title in zip(axes[:3], ("detection", "false_positive", "unknown"),
                                   ("Error detection", "Clean false positive", "UNKNOWN / artifacts")):
        values = [arm_metrics[arm][metric] * 100 for arm in ARMS]
        axis.bar(labels, values, color=colors)
        axis.set_title(title)
        axis.set_ylim(0, 105)
        axis.set_ylabel("%")
        for index, value in enumerate(values):
            axis.text(index, value + 2, f"{value:.1f}", ha="center", fontsize=9)
    call_values = [costs[arm]["generation_llm_calls"] for arm in ARMS]
    axes[3].bar(labels, call_values, color=colors)
    axes[3].set_title("LLM calls")
    for index, value in enumerate(call_values):
        axes[3].text(index, value + 0.15, str(value), ha="center", fontsize=9)
    fig.suptitle(f"DVSA fixed-artifact {args.split}: {len(args.ids)} reference-qualified BWOR problems")
    fig.subplots_adjust(left=0.06, right=0.98, bottom=0.18, top=0.82, wspace=0.35)
    figure = Path(args.figure)
    figure.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure, dpi=180)
    plt.close(fig)
    print(json.dumps({"arms": arm_metrics, "comparisons": comparisons, "costs": costs}, indent=2))
    print(f"figure={figure}")


if __name__ == "__main__":
    main()
