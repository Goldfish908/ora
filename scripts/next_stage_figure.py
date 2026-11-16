#!/usr/bin/env python3
"""Render the verified next-stage development results without frozen-set claims."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def load_results() -> dict:
    industry = json.loads((ROOT / "work/industryor_scoped_loop_v0.6/analysis.json").read_text())
    bwor = json.loads((ROOT / "work/bwor_scoped_loop_v0.2/summary.json").read_text())
    retail = json.loads((ROOT / "work/dvsa/retailopt_win_safe_v0.1/analysis.json").read_text())
    mamo = json.loads((ROOT / "work/scoped_ir_mamo_scope_v0.2/analysis.json").read_text())
    ranker = json.loads((ROOT / "work/repair_ranker_v0.1/metrics.json").read_text())
    validation = json.loads((ROOT / "work/repair_ranker_v0.1/top_choice_validation.json").read_text())
    for policy in ("fixed", "progress"):
        assert industry["arms"][policy]["final_business_correct"] == 6
        assert industry["arms"][policy]["harmed_win"] == 0
        assert bwor["arms"][policy]["final_reference_correct"] == 6
        assert bwor["arms"][policy]["harmed_win"] == 0
    assert retail["summary"]["no_memory"]["safe_final_business_correct"] == 6
    assert retail["summary"]["no_memory"]["safe_harmed_win"] == 0
    assert mamo["summary"]["activated"] == 0 and mamo["summary"]["harmed_win"] == 0
    assert validation["independent_pass"] == 35 and validation["attempted"] == 38
    return {"industry": industry, "bwor": bwor, "retail": retail, "mamo": mamo,
            "ranker": ranker, "validation": validation}


def build_figure(outdir: Path) -> tuple[Path, Path]:
    results = load_results()
    outdir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    fig.suptitle("Development evidence: verified repair and candidate ranking", fontsize=14)
    fig.text(0.5, 0.91, "Historical development cohorts; no frozen/sealed evaluation",
             ha="center", fontsize=10, color="#444444")

    policies = ("no_repair", "fixed", "progress")
    labels = ("No repair", "Fixed", "Progress")
    colors = ("#9ca3af", "#2563eb", "#059669")
    industry = results["industry"]["arms"]
    bwor = results["bwor"]["arms"]
    series = [
        ("IndustryOR", 7, [industry[p]["final_business_correct"] for p in policies]),
        ("BWOR", 6, [bwor[p]["final_reference_correct"] for p in policies]),
    ]
    x = range(2)
    width = 0.24
    ax = axes[0]
    for index, (policy, label, color) in enumerate(zip(policies, labels, colors)):
        positions = [value + (index - 1) * width for value in x]
        values = [100 * row[2][index] / row[1] for row in series]
        bars = ax.bar(positions, values, width, label=label, color=color)
        for bar, (_, denominator, counts) in zip(bars, series):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2,
                    f"{counts[index]}/{denominator}", ha="center", fontsize=9)
    ax.set_xticks(list(x), [row[0] for row in series])
    ax.set_ylim(0, 115)
    ax.set_yticks(range(0, 101, 20))
    ax.set_ylabel("Business/reference correct (%)")
    ax.set_title("Shared-initial repair controls")
    ax.legend(frameon=False, loc="lower right")

    models = (("length_only", "Length"), ("style_logreg", "Style"),
              ("ast_logreg", "AST"), ("tfidf_logreg", "TF-IDF"))
    ax = axes[1]
    bars = []
    for key, label in models:
        dev = results["ranker"][key]["dev"]
        bars.append((label, dev["correct"], dev["pairs"]))
    positions = range(len(bars))
    bars_plot = ax.bar(positions, [100 * correct / total for _, correct, total in bars],
                       color=("#9ca3af", "#60a5fa", "#1d4ed8", "#059669"), width=0.62)
    for bar, (_, correct, total) in zip(bars_plot, bars):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2,
                f"{correct}/{total}", ha="center", fontsize=9)
    ax.set_xticks(list(positions), [label for label, _, _ in bars])
    ax.set_ylim(0, 115)
    ax.set_yticks(range(0, 101, 20))
    ax.set_ylabel("Pairwise accuracy (%)")
    ax.set_title("Non-LLM repair-candidate rankers")

    fig.text(0.01, 0.025,
             "IndustryOR: 3 independent recoveries; BWOR-058: reference-bound replay; "
             "RetailOpt dev20 no-memory: 5 to 6 by win-safe fallback.\n"
             "MAMO: integer-domain transfer rejected for missing evidence. "
             "TF-IDF top-choice replay: 35/38; no end-to-end ranking uplift claimed.",
             fontsize=9, color="#444444")
    fig.tight_layout(rect=(0, 0.09, 1, 0.88))
    figure_path = outdir / "next_stage_overview_v0.2.png"
    fig.savefig(figure_path, dpi=160, bbox_inches="tight")
    plt.close(fig)

    data = {
        "scope": "historical development; not frozen/sealed evaluation",
        "industryor": {policy: {"n": 7, "correct": industry[policy]["final_business_correct"],
                               "harmed_win": industry[policy]["harmed_win"]} for policy in policies},
        "bwor": {policy: {"n": 6, "correct": bwor[policy]["final_reference_correct"],
                         "reference_bound_recoveries": bwor[policy]["reference_bound_development_recoveries"],
                         "harmed_win": bwor[policy]["harmed_win"]} for policy in policies},
        "retailopt_no_memory_dev20": results["retail"]["summary"]["no_memory"],
        "mamo_mix8": results["mamo"]["summary"],
        "ranker_dev": {key: results["ranker"][key]["dev"] for key, _ in models},
        "tfidf_independent_top_choice": {
            "passed": results["validation"]["independent_pass"],
            "attempted": results["validation"]["attempted"],
        },
        "sources": ["work/industryor_scoped_loop_v0.6/analysis.json",
                    "work/bwor_scoped_loop_v0.2/summary.json",
                    "work/dvsa/retailopt_win_safe_v0.1/analysis.json",
                    "work/scoped_ir_mamo_scope_v0.2/analysis.json",
                    "work/repair_ranker_v0.1/metrics.json",
                    "work/repair_ranker_v0.1/top_choice_validation.json"],
    }
    data_path = outdir / "next_stage_overview_v0.2.json"
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    return figure_path, data_path


def main() -> None:
    figure, data = build_figure(ROOT / "docs/paper/figures")
    print(figure)
    print(data)


if __name__ == "__main__":
    main()
