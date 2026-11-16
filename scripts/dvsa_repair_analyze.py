#!/usr/bin/env python3
"""Analyze shared-initial natural repair, win safety, paired outcomes and cost."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dvsa_fixed_arm_analyze import mcnemar_exact  # noqa: E402

ARMS = ["no_memory", "text_memory", "dvsa", "direct_legacy_witness"]
IDS = ["BWOR-001", "BWOR-011", "BWOR-042", "BWOR-043", "BWOR-062", "BWOR-066", "BWOR-069"]


def usage(result, equivalent=False):
    if result["llm_calls"] == 0 and not equivalent:
        return {}
    return result.get("usage") or {}


def totals(results, equivalent=False):
    usages = [usage(result, equivalent) for result in results]
    return {"prompt_tokens": sum(item.get("prompt_tokens", 0) or 0 for item in usages),
            "completion_tokens": sum(item.get("completion_tokens", 0) or 0 for item in usages),
            "total_tokens": sum(item.get("total_tokens", 0) or 0 for item in usages)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "validation", "frozen"], default="dev")
    parser.add_argument("--ids", nargs="+", default=IDS)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--figure", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    records = {}
    initial_records = []
    for problem_id in args.ids:
        initial = json.loads((run_dir / problem_id / "initial/result.json").read_text())
        initial_records.append(initial)
        for arm in ARMS:
            result = json.loads((run_dir / problem_id / arm / "result.json").read_text())
            records.setdefault(problem_id, {})[arm] = result
        hashes = {records[problem_id][arm]["initial_candidate_sha256"] for arm in ARMS}
        assert len(hashes) == 1, f"initial candidate differs across arms: {problem_id}"
    initial_business = {problem_id: records[problem_id]["dvsa"]["initial_score"]["business_correct"]
                        for problem_id in args.ids}
    metrics = {}
    for arm in ARMS:
        arm_records = [records[problem_id][arm] for problem_id in args.ids]
        metrics[arm] = {
            "business_correct_n": sum(result["final_score"]["business_correct"] for result in arm_records),
            "business_correct": sum(result["final_score"]["business_correct"] for result in arm_records) / len(args.ids),
            "semantic_valid_n": sum(result["final_score"].get("semantic_valid", False) for result in arm_records),
            "objective_correct_n": sum(result["final_score"].get("objective_correct", False) for result in arm_records),
            "improved_n": sum(result["improved"] for result in arm_records),
            "harmed_win_n": sum(result["harmed_win"] for result in arm_records),
            "actual_repair_llm_calls": sum(result["llm_calls"] for result in arm_records),
            "equivalent_repair_llm_calls": sum(result["equivalent_generation_llm_calls"] for result in arm_records),
            "repair_latency_s": round(sum((result.get("llm_latency_s") or 0) if result["llm_calls"] else 0
                                          for result in arm_records), 3),
            "actual_repair_tokens": totals(arm_records),
            "equivalent_repair_tokens": totals(arm_records, equivalent=True),
            "repair_triggers": dict(Counter(result.get("repair_trigger", "unknown")
                                            for result in arm_records)),
        }
    comparisons = {}
    for other in ("no_memory", "text_memory", "direct_legacy_witness"):
        dvsa_only = sum(records[problem_id]["dvsa"]["final_score"]["business_correct"]
                        and not records[problem_id][other]["final_score"]["business_correct"]
                        for problem_id in args.ids)
        other_only = sum(records[problem_id][other]["final_score"]["business_correct"]
                         and not records[problem_id]["dvsa"]["final_score"]["business_correct"]
                         for problem_id in args.ids)
        comparisons[f"dvsa_vs_{other}"] = {"dvsa_only": dvsa_only, "other_only": other_only,
                                           "mcnemar_exact_p": mcnemar_exact(dvsa_only, other_only)}
    initial_usage = totals(initial_records, equivalent=True)
    initial_calls = sum(result["llm_calls"] for result in initial_records)
    result = {
        "protocol": "dvsa-shared-initial-natural-repair-v0.1",
        "label": args.label,
        "scope": f"{len(args.ids)} reference-qualified BWOR {args.split} problems, conditional on shared reference variable schema; current-solution business correctness, not model equivalence.",
        "problem_ids": args.ids,
        "initial": {"business_correct_n": sum(initial_business.values()),
                    "business_correct": sum(initial_business.values()) / len(args.ids),
                    "llm_calls": initial_calls,
                    "latency_s": round(sum(result.get("llm_latency_s", 0) or 0 for result in initial_records), 3),
                    **initial_usage},
        "arms": metrics,
        "comparisons": comparisons,
        "shared_run_actual_llm_calls": initial_calls + sum(metrics[arm]["actual_repair_llm_calls"] for arm in ARMS),
        "standalone_equivalent_llm_calls": {arm: initial_calls + metrics[arm]["equivalent_repair_llm_calls"]
                                             for arm in ARMS},
        "per_problem": {problem_id: {
            "initial_business_correct": initial_business[problem_id],
            "arms": {arm: {"status": records[problem_id][arm]["status"],
                           "repair_trigger": records[problem_id][arm].get("repair_trigger"),
                           "llm_calls": records[problem_id][arm]["llm_calls"],
                           "final_score": records[problem_id][arm]["final_score"],
                           "improved": records[problem_id][arm]["improved"],
                           "harmed_win": records[problem_id][arm]["harmed_win"]}
                     for arm in ARMS},
        } for problem_id in args.ids},
        "semantic_repair_observed": any(result.get("repair_trigger") == "dvsa_violation"
                                        for problem_id in args.ids for result in [records[problem_id]["dvsa"]]),
        "win_safe_pass": all(metrics[arm]["harmed_win_n"] == 0 for arm in ARMS),
        "significance_pass": comparisons["dvsa_vs_text_memory"]["mcnemar_exact_p"] < 0.05,
        "sota_started": False,
    }
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    labels = ["Initial", "No\nmemory", "Text\nmemory", "DVSA", "Legacy\nwitness"]
    colors = ["#64748b", "#94a3b8", "#f59e0b", "#0f766e", "#cbd5e1"]
    correct = [result["initial"]["business_correct_n"]] + [metrics[arm]["business_correct_n"] for arm in ARMS]
    calls = [0] + [metrics[arm]["equivalent_repair_llm_calls"] for arm in ARMS]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    axes[0].bar(labels, correct, color=colors)
    axes[0].set_title("Business-correct solutions")
    axes[0].set_ylim(0, len(args.ids) + 0.5)
    axes[1].bar(labels, calls, color=colors)
    axes[1].set_title("Standalone-equivalent repair LLM calls")
    for axis, values in zip(axes, (correct, calls)):
        for index, value in enumerate(values):
            axis.text(index, value + 0.12, str(value), ha="center")
    fig.suptitle(f"Shared-initial repair: {args.label}")
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.18, top=0.82, wspace=0.3)
    figure = Path(args.figure)
    figure.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure, dpi=180)
    plt.close(fig)
    print(json.dumps({"initial": result["initial"], "arms": metrics,
                      "comparisons": comparisons,
                      "semantic_repair_observed": result["semantic_repair_observed"]}, indent=2))
    print(f"figure={figure}")


if __name__ == "__main__":
    main()
