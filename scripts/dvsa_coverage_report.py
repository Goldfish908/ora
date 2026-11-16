#!/usr/bin/env python3
"""Report qualified and full-cohort coverage without hiding reference failures."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARMS = ["no_memory", "text_memory", "dvsa", "direct_legacy_witness"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "validation", "frozen"], required=True)
    parser.add_argument("--fixed", required=True)
    parser.add_argument("--repair", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--figure", required=True)
    args = parser.parse_args()
    split = args.split
    ids = (ROOT / f"data/dvsa/bwor/{split}.txt").read_text().splitlines()
    reference = json.loads((ROOT / f"work/dvsa/bwor_reference/{split}/summary.json").read_text())
    fixed = json.loads((ROOT / args.fixed).read_text()) if not Path(args.fixed).is_absolute() else json.loads(Path(args.fixed).read_text())
    repair = json.loads((ROOT / args.repair).read_text()) if not Path(args.repair).is_absolute() else json.loads(Path(args.repair).read_text())
    eligible = set(reference["summary"]["eligible_ids"])
    conservative = {}
    for arm in ARMS:
        metrics = repair["arms"][arm]
        conservative[arm] = {
            "business_correct_n": metrics["business_correct_n"],
            "business_correct": metrics["business_correct_n"] / len(ids),
            "objective_correct_n": metrics["objective_correct_n"],
            "objective_correct": metrics["objective_correct_n"] / len(ids),
            "unscored_reference_n": len(ids) - len(eligible),
            "note": "Conservative lower bound: reference failures count as not business-correct; not a comparable public leaderboard score.",
        }
    result = {
        "protocol": "dvsa-full-cohort-coverage-v0.1",
        "split": split, "all_ids": ids, "eligible_ids": sorted(eligible),
        "reference_coverage": {"eligible_n": len(eligible), "all_n": len(ids),
                               "coverage": len(eligible) / len(ids),
                               "ineligible": reference["summary"]["ineligible_ids"]},
        "qualified_fixed_artifacts": {"arms": fixed["arms"], "comparisons": fixed["comparisons"],
                                      "costs": fixed["costs"]},
        "qualified_repair": {"initial": repair["initial"], "arms": repair["arms"],
                             "comparisons": repair["comparisons"]},
        "conservative_full_cohort": conservative,
        "per_problem": {problem_id: {
            "reference_eligible": problem_id in eligible,
            "reference_status": next(row["final_status"] for row in reference["records"] if row["problem_id"] == problem_id),
            "arms": repair["per_problem"].get(problem_id, {}).get("arms", "unscored_reference"),
        } for problem_id in ids},
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
    labels = ["No\nmemory", "Text\nmemory", "DVSA", "Legacy\nwitness"]
    colors = ["#94a3b8", "#f59e0b", "#0f766e", "#cbd5e1"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
    axes[0].bar(["Reference\nqualified", "Reference\nfailure"],
                [len(eligible), len(ids) - len(eligible)], color=["#0f766e", "#cbd5e1"])
    axes[0].set_title(f"Reference coverage (n={len(ids)})")
    for index, value in enumerate([len(eligible), len(ids) - len(eligible)]):
        axes[0].text(index, value + 0.15, str(value), ha="center")
    qualified = [repair["arms"][arm]["business_correct_n"] for arm in ARMS]
    lower = [conservative[arm]["business_correct_n"] for arm in ARMS]
    axes[1].bar(labels, qualified, color=colors)
    axes[1].set_title(f"Business-correct (qualified n={len(eligible)})")
    axes[1].set_ylim(0, len(ids) + 1)
    axes[2].bar(labels, lower, color=colors)
    axes[2].set_title(f"Conservative lower bound (full n={len(ids)})")
    axes[2].set_ylim(0, len(ids) + 1)
    for axis, values in ((axes[1], qualified), (axes[2], lower)):
        for index, value in enumerate(values):
            axis.text(index, value + 0.15, str(value), ha="center", fontsize=9)
    fig.suptitle(f"DVSA BWOR {split}: qualified and full-cohort views")
    fig.subplots_adjust(left=0.07, right=0.98, bottom=0.18, top=0.82, wspace=0.32)
    figure = Path(args.figure)
    figure.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure, dpi=180)
    plt.close(fig)
    print(json.dumps({"reference_coverage": result["reference_coverage"],
                      "conservative_full_cohort": conservative}, indent=2))
    print(f"figure={figure}")


if __name__ == "__main__":
    main()
