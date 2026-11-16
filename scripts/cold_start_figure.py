#!/usr/bin/env python3
"""Render new binding families and the real evidence-DAG comparison."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def load_results() -> dict:
    return json.loads((ROOT / "work/cold_start_binding_v0.1/analysis.json").read_text())


def build_figure(outdir: Path) -> tuple[Path, Path]:
    analysis = load_results()
    summary = analysis["summary"]
    dag = analysis["dag"]
    outdir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    labels = ("Valid", "Wrong\nrejected", "Missing\nUNKNOWN", "Conflict\nUNKNOWN")
    values = (summary["valid_bindings"], summary["wrong_bindings_rejected"],
              summary["missing_evidence_unknown"], summary["conflicts_unknown"])
    bars = axes[0].bar(range(4), values, color=("#059669", "#dc2626", "#64748b", "#94a3b8"), width=0.6)
    for bar, value in zip(bars, values):
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + 0.05, f"{value}/2", ha="center")
    axes[0].set_xticks(range(4), labels)
    axes[0].set_ylim(0, 2.5)
    axes[0].set_ylabel("Mechanism families")
    axes[0].set_title("Objective recompute + resource bound")
    labels = ("Initial\n36.4", "Reference\npatch / 28", "Candidate\nrejected", "Single-line\npatch / 28")
    values = (0, 1, 0, 1)
    bars = axes[1].bar(range(4), values, color=("#9ca3af", "#059669", "#dc2626", "#2563eb"), width=0.6)
    for bar, label in zip(bars, ("invalid", "valid", "rejected", "valid")):
        axes[1].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.04, label, ha="center")
    axes[1].set_xticks(range(4), labels)
    axes[1].set_ylim(0, 1.35)
    axes[1].set_yticks((0, 1))
    axes[1].set_ylabel("Independent business pass")
    axes[1].set_title("Real error: DAG = single-line (1 SCIP each)")
    fig.text(0.5, 0.03,
             "Candidate-derived and reference-assisted proposals are not new LLM calls. "
             "Negative branches are preserved; no DAG gain or universal transfer is claimed.",
             ha="center", fontsize=9, color="#444444")
    fig.tight_layout(rect=(0, 0.11, 1, 0.93))
    image = outdir / "cold_start_binding_v0.1.png"
    fig.savefig(image, dpi=160, bbox_inches="tight")
    plt.close(fig)
    data = {"scope": analysis["run_config"]["exposure"], "summary": summary,
            "dag_comparison": dag["comparison"], "single_line_solver_runs": 1,
            "accepted_node_ids": dag["accepted_node_ids"], "negative_node_ids": dag["negative_node_ids"],
            "sources": ["work/cold_start_binding_v0.1/analysis.json",
                        "work/cold_start_binding_v0.1/dag.json"]}
    path = outdir / "cold_start_binding_v0.1.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    return image, path


def main() -> None:
    print(build_figure(ROOT / "docs/paper/figures"))


if __name__ == "__main__":
    main()
