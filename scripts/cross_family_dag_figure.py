#!/usr/bin/env python3
"""Plot cross-family DAG recovery and its explicit solver overhead."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def load_results() -> dict:
    return json.loads((ROOT / "work/cross_family_dag_v0.1/analysis.json").read_text())


def build_figure(outdir: Path) -> tuple[Path, Path]:
    analysis = load_results()
    outdir.mkdir(parents=True, exist_ok=True)
    summary = analysis["summary"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.7))
    families = ("BWOR", "IndustryOR")
    dag_correct = [result["accepted_node_ids"].__len__() for result in analysis["results"].values()]
    single_correct = [result["single_line"]["business_audit"]["business_correct"]
                      for result in analysis["results"].values()]
    x = range(2)
    bars1 = axes[0].bar([value - 0.17 for value in x], dag_correct, width=0.34,
                        label="Evidence DAG", color="#059669")
    bars2 = axes[0].bar([value + 0.17 for value in x], single_correct, width=0.34,
                        label="Single-line", color="#2563eb")
    for bars in (bars1, bars2):
        for bar in bars:
            axes[0].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.04,
                         str(int(bar.get_height())), ha="center")
    axes[0].set_xticks(list(x), families)
    axes[0].set_ylim(0, 1.35)
    axes[0].set_yticks((0, 1))
    axes[0].set_ylabel("Independent recoveries")
    axes[0].set_title("Same recoveries: 1 per family")
    axes[0].legend(frameon=False, fontsize=9)
    dag_cost = [result["total_solver_runs"] for result in analysis["results"].values()]
    single_cost = [result["single_line"]["solver_runs"] for result in analysis["results"].values()]
    bars1 = axes[1].bar([value - 0.17 for value in x], dag_cost, width=0.34,
                        label="Evidence DAG", color="#059669")
    bars2 = axes[1].bar([value + 0.17 for value in x], single_cost, width=0.34,
                        label="Single-line", color="#2563eb")
    for bars in (bars1, bars2):
        for bar in bars:
            axes[1].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.06,
                         str(int(bar.get_height())), ha="center")
    axes[1].set_xticks(list(x), families)
    axes[1].set_ylim(0, 3.2)
    axes[1].set_yticks((0, 1, 2, 3))
    axes[1].set_ylabel("SCIP runs")
    axes[1].set_title("DAG overhead: +1 rejected branch")
    axes[1].legend(frameon=False, fontsize=9)
    fig.text(0.5, 0.03,
             "BWOR: 1 vs 1 SCIP. IndustryOR: 2 vs 1 SCIP. Rollback preserves the rejected objective-only model. "
             "No DAG quality or cost gain; historical development, not frozen.",
             ha="center", fontsize=9, color="#444444")
    fig.tight_layout(rect=(0, 0.11, 1, 0.93))
    image = outdir / "cross_family_dag_v0.1.png"
    fig.savefig(image, dpi=160, bbox_inches="tight")
    plt.close(fig)
    data = {"scope": analysis["run_config"]["exposure"], "summary": summary,
            "sources": ["work/cross_family_dag_v0.1/analysis.json"]}
    path = outdir / "cross_family_dag_v0.1.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    return image, path


def main() -> None:
    print(build_figure(ROOT / "docs/paper/figures"))


if __name__ == "__main__":
    main()
