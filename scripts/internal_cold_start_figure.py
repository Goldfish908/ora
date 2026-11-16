#!/usr/bin/env python3
"""Render real internal-Qwen binding evidence and generation cost."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def load_results() -> dict:
    return json.loads((ROOT / "work/internal_cold_start_v0.1/analysis.json").read_text())


def build_figure(outdir: Path) -> tuple[Path, Path]:
    analysis = load_results()
    summary = analysis["summary"]
    outdir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.7))
    labels = ("Cold-start\nvalidated", "Reference\nvalidated", "Wrong\nrejected",
              "Missing\nUNKNOWN", "Conflict\nUNKNOWN")
    keys = ("cold_start_valid", "reference_assisted_valid", "wrong_bindings_rejected",
            "missing_evidence_unknown", "conflicts_unknown")
    colors = ("#0ea5e9", "#2563eb", "#dc2626", "#64748b", "#94a3b8")
    bars = axes[0].bar(range(5), [summary[key] for key in keys], color=colors, width=0.62)
    for bar, key in zip(bars, keys):
        axes[0].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                     f"{summary[key]}/2", ha="center")
    axes[0].set_xticks(range(5), labels, fontsize=8)
    axes[0].set_ylim(0, 2.5)
    axes[0].set_ylabel("Mechanism families")
    axes[0].set_title("Both internal-Qwen proposals independently validated")
    cost_labels = ("LLM proposal\ncalls", "SCIP replay\nruns")
    costs = (summary["proposal_generation_llm_calls"], summary["new_solver_runs"])
    bars = axes[1].bar(range(2), costs, color=("#7c3aed", "#059669"), width=0.48)
    for bar, value in zip(bars, costs):
        axes[1].text(bar.get_x() + bar.get_width() / 2, value + 0.06, str(value), ha="center")
    axes[1].set_xticks(range(2), cost_labels)
    axes[1].set_ylim(0, 2.7)
    axes[1].set_ylabel("Actual operations")
    axes[1].set_title("Generation and verification cost")
    axes[1].text(0.04, 0.90,
                 f"Tokens: {summary['total_tokens']}\nLatency: {summary['llm_latency_s']}s\nResume calls: {summary['new_llm_calls']}",
                 transform=axes[1].transAxes, va="top", fontsize=10)
    fig.text(0.5, 0.03,
             "Schema/source-span assisted; not fully autonomous modeling, universal transfer, DAG gain or evolution. "
             "Wrong/missing/conflicting bindings are not accepted.",
             ha="center", fontsize=9, color="#444444")
    fig.tight_layout(rect=(0, 0.11, 1, 0.93))
    image = outdir / "internal_cold_start_v0.1.png"
    fig.savefig(image, dpi=160, bbox_inches="tight")
    plt.close(fig)
    data = {"scope": analysis["run_config"]["exposure"], "summary": summary,
            "api_key_recorded": False,
            "sources": ["work/internal_cold_start_v0.1/analysis.json",
                        "work/internal_cold_start_v0.1/objective_recompute/generation.json",
                        "work/internal_cold_start_v0.1/resource_bound/generation.json"]}
    path = outdir / "internal_cold_start_v0.1.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    return image, path


def main() -> None:
    print(build_figure(ROOT / "docs/paper/figures"))


if __name__ == "__main__":
    main()
