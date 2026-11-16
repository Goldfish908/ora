#!/usr/bin/env python3
"""Analyze shared-initial RetailOpt four-arm feedback and execution recovery."""
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


def load_arm(directory):
    parent_path = directory / "result.json"
    parent = json.loads(parent_path.read_text())
    stages = [parent]
    recovery_path = directory / "execution_recovery/result.json"
    if recovery_path.exists():
        stages.append(json.loads(recovery_path.read_text()))
    final = stages[-1]
    usages = [stage.get("usage") or {} for stage in stages]
    return {"scenario_id": parent["scenario_id"], "arm": parent["arm"],
            "initial_score": parent["initial_score"], "final_score": final["final_score"],
            "initial_code_sha256": parent["initial_code_sha256"],
            "repair_trigger": parent["repair_trigger"],
            "final_status": final.get("status", final.get("repair_trigger")),
            "improved": final["improved"], "harmed_win": final["harmed_win"],
            "execution_recovery_used": len(stages) > 1,
            "llm_calls": sum(stage["llm_calls"] for stage in stages),
            "solver_calls": sum(stage.get("solver_calls", 0) for stage in stages),
            "llm_latency_s": sum(stage.get("llm_latency_s", 0) or 0 for stage in stages),
            "solver_wall_s": sum(stage.get("run", {}).get("wall_s", 0) or 0 for stage in stages),
            "prompt_tokens": sum(item.get("prompt_tokens", 0) or 0 for item in usages),
            "completion_tokens": sum(item.get("completion_tokens", 0) or 0 for item in usages),
            "total_tokens": sum(item.get("total_tokens", 0) or 0 for item in usages),
            "feedback": parent["feedback"]}


def metrics(rows):
    return {"business_correct_n": sum(row["final_score"]["business_correct"] for row in rows),
            "semantic_valid_n": sum(row["final_score"].get("semantic_valid", False) for row in rows),
            "objective_correct_n": sum(row["final_score"].get("objective_correct", False) for row in rows),
            "improved_n": sum(row["improved"] for row in rows),
            "harmed_win_n": sum(row["harmed_win"] for row in rows),
            "llm_calls": sum(row["llm_calls"] for row in rows),
            "solver_calls": sum(row["solver_calls"] for row in rows),
            "execution_recovery_n": sum(row["execution_recovery_used"] for row in rows),
            "llm_latency_s": round(sum(row["llm_latency_s"] for row in rows), 3),
            "solver_wall_s": round(sum(row["solver_wall_s"] for row in rows), 3),
            "prompt_tokens": sum(row["prompt_tokens"] for row in rows),
            "completion_tokens": sum(row["completion_tokens"] for row in rows),
            "total_tokens": sum(row["total_tokens"] for row in rows),
            "repair_triggers": dict(Counter(row["repair_trigger"] for row in rows))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="work/mem_evo/replay_gen1/m1_pilot_schema_sol_gen1.jsonl")
    parser.add_argument("--run-dir", default="work/dvsa/retailopt_repair/dev")
    parser.add_argument("--out", default="work/dvsa/retailopt_repair_analysis")
    parser.add_argument("--figure", default="/home/hewj13/paper_icml2027/figures/dvsa_retailopt_dev_repair.png")
    args = parser.parse_args()
    baseline = Path(args.baseline)
    run_dir = Path(args.run_dir)
    if not baseline.is_absolute():
        baseline = ROOT / baseline
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    scenarios = [json.loads(line)["scenario_id"] for line in baseline.read_text().splitlines() if line.strip()]
    scenarios.sort()
    records = {scenario: {arm: load_arm(run_dir / scenario / arm) for arm in ARMS}
               for scenario in scenarios}
    for scenario, arms in records.items():
        assert len({row["initial_code_sha256"] for row in arms.values()}) == 1, scenario
    combined = {arm: [records[scenario][arm] for scenario in scenarios] for arm in ARMS}
    arm_metrics = {arm: metrics(rows) for arm, rows in combined.items()}
    initial = next(iter(records.values()))["dvsa"]["initial_score"]
    initial_business = {scenario: records[scenario]["dvsa"]["initial_score"]["business_correct"]
                        for scenario in scenarios}
    comparisons = {}
    for other in ("no_memory", "text_memory", "direct_legacy_witness"):
        dvsa_only = sum(records[scenario]["dvsa"]["final_score"]["business_correct"]
                        and not records[scenario][other]["final_score"]["business_correct"]
                        for scenario in scenarios)
        other_only = sum(records[scenario][other]["final_score"]["business_correct"]
                         and not records[scenario]["dvsa"]["final_score"]["business_correct"]
                         for scenario in scenarios)
        comparisons[f"dvsa_vs_{other}"] = {"dvsa_only": dvsa_only, "other_only": other_only,
                                           "mcnemar_exact_p": mcnemar_exact(dvsa_only, other_only)}
    dvsa = combined["dvsa"]
    initial_win = [row for row in dvsa if row["initial_score"]["business_correct"]]
    semantic_triggers = [row for row in dvsa if row["repair_trigger"] == "dvsa_violation"]
    result = {
        "protocol": "retailopt-shared-initial-dvsa-four-arm-v0.1",
        "scope": "Twenty saved RetailOpt dev scenarios from one shared replay; repair-only incremental cost, not a fresh full-pipeline run.",
        "scenario_ids": scenarios,
        "initial": {"business_correct_n": sum(initial_business.values()),
                    "semantic_valid_n": sum(records[scenario]["dvsa"]["initial_score"].get("semantic_valid", False)
                                            for scenario in scenarios),
                    "objective_correct_n": sum(records[scenario]["dvsa"]["initial_score"].get("objective_correct", False)
                                               for scenario in scenarios),
                    "cached_llm_calls": 0},
        "arms": arm_metrics,
        "comparisons": comparisons,
        "gate": {
            "initial_business_correct": len(initial_win),
            "dvsa_false_positive_on_initial_business_correct": sum(
                row["feedback"]["status"] == "VIOLATED" for row in initial_win),
            "dvsa_false_positive_rate": sum(row["feedback"]["status"] == "VIOLATED" for row in initial_win) / max(len(initial_win), 1),
            "dvsa_semantic_triggers": len(semantic_triggers),
            "dvsa_semantic_trigger_business_correct": sum(row["final_score"]["business_correct"] for row in semantic_triggers),
            "dvsa_semantic_trigger_execution_recovery": sum(row["execution_recovery_used"] for row in semantic_triggers),
        },
        "per_problem": {scenario: {
            "initial_score": records[scenario]["dvsa"]["initial_score"],
            "arms": {arm: {"repair_trigger": records[scenario][arm]["repair_trigger"],
                           "final_status": records[scenario][arm]["final_status"],
                           "final_score": records[scenario][arm]["final_score"],
                           "llm_calls": records[scenario][arm]["llm_calls"],
                           "solver_calls": records[scenario][arm]["solver_calls"],
                           "execution_recovery_used": records[scenario][arm]["execution_recovery_used"],
                           "improved": records[scenario][arm]["improved"],
                           "harmed_win": records[scenario][arm]["harmed_win"]}
                     for arm in ARMS},
        } for scenario in scenarios},
        "scoring_note": "Business correctness uses frozen legacy-witness feasibility plus reference objective. Legacy is also A3 feedback; this is not independent semantic truth or model equivalence.",
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
    correct = [result["initial"]["business_correct_n"]] + [arm_metrics[arm]["business_correct_n"] for arm in ARMS]
    feedback_calls = [0] + [arm_metrics[arm]["llm_calls"] - arm_metrics[arm]["execution_recovery_n"] for arm in ARMS]
    recovery_calls = [0] + [arm_metrics[arm]["execution_recovery_n"] for arm in ARMS]
    improvements = [0] + [arm_metrics[arm]["improved_n"] for arm in ARMS]
    harmed = [0] + [arm_metrics[arm]["harmed_win_n"] for arm in ARMS]
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.2))
    axes[0].bar(labels, correct, color=colors)
    axes[0].set_title("Business-correct solutions")
    axes[0].set_ylim(0, len(scenarios) + 1)
    axes[1].bar(labels, feedback_calls, color=colors, label="feedback/self-review")
    axes[1].bar(labels, recovery_calls, bottom=feedback_calls, color="#475569", label="execution recovery")
    axes[1].set_title("LLM calls by stage")
    axes[1].legend(fontsize=8)
    axes[2].bar(labels, improvements, color="#0f766e", label="improved")
    axes[2].bar(labels, harmed, bottom=improvements, color="#b91c1c", label="harmed win")
    axes[2].set_title("Paired outcome count")
    axes[2].legend(fontsize=8)
    for axis, values in zip(axes, (correct, [a + b for a, b in zip(feedback_calls, recovery_calls)], improvements)):
        for index, value in enumerate(values):
            axis.text(index, value + 0.15, str(value), ha="center", fontsize=9)
    fig.suptitle("RetailOpt shared-initial repair: 20 dev scenarios")
    fig.subplots_adjust(left=0.06, right=0.98, bottom=0.18, top=0.82, wspace=0.32)
    figure = Path(args.figure)
    figure.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure, dpi=180)
    plt.close(fig)
    print(json.dumps({"initial": result["initial"], "arms": arm_metrics,
                      "comparisons": comparisons, "gate": result["gate"]}, indent=2))
    print(f"figure={figure}")


if __name__ == "__main__":
    main()
