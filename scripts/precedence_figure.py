#!/usr/bin/env python3
"""Render natural alternative preservation and the separate controlled repair."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def load_results() -> dict:
    natural = json.loads((ROOT / "work/precedence_witness_v0.1/analysis.json").read_text())
    lifecycle = json.loads((ROOT / "work/precedence_witness_v0.1/controlled_repair/lifecycle.json").read_text())
    assert natural["summary"]["independent_business_correct"] == 2
    assert natural["summary"]["repair_required"] == 0
    for arm in natural["arms"].values():
        assert arm["final_business_correct"] == 2 and arm["round0_unchanged"] == 2
        assert arm["harmed_win"] == arm["accepted_but_business_incorrect"] == 0
    assert natural["candidate_dag"]["status"] == "not_run_no_natural_repair_opportunity"
    assert lifecycle["registry_decision"] == "not_promoted_controlled_only"
    assert lifecycle["independent_business_correct"] is True
    return {"natural": natural, "lifecycle": lifecycle}


def build_figure(outdir: Path) -> tuple[Path, Path]:
    results = load_results()
    outdir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    fig.suptitle("Precedence witness: preserve valid alternatives; repair only verified structure", fontsize=13)
    natural = results["natural"]
    labels = ("Reference-only", "Independent", "Fixed", "Progress")
    values = (natural["summary"]["legacy_reference_correct"],
              natural["summary"]["independent_business_correct"],
              natural["arms"]["fixed"]["final_business_correct"],
              natural["arms"]["progress"]["final_business_correct"])
    bars = axes[0].bar(range(4), values, color=("#9ca3af", "#0ea5e9", "#2563eb", "#059669"), width=0.62)
    for bar, value in zip(bars, values):
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + 0.05, f"{value}/2", ha="center")
    axes[0].set_xticks(range(4), labels, rotation=15)
    axes[0].set_ylim(0, 2.5)
    axes[0].set_ylabel("Cases accepted (n=2)")
    axes[0].set_title("Natural models: both valid; no repair")
    axes[0].text(0.03, 0.94, "024: cut; 025: position-job completion",
                 transform=axes[0].transAxes, va="top", fontsize=9)
    lifecycle = results["lifecycle"]
    bars = axes[1].bar((0, 1), (0, 1), color=("#9ca3af", "#059669"), width=0.5)
    for bar, value in zip(bars, (0, 1)):
        axes[1].text(bar.get_x() + bar.get_width() / 2, value + 0.04,
                     "invalid" if value == 0 else "valid / 81", ha="center")
    axes[1].set_xticks((0, 1), ("Controlled mutation", "Repaired + SCIP"))
    axes[1].set_ylim(0, 1.35)
    axes[1].set_yticks((0, 1))
    axes[1].set_ylabel("Independent business pass")
    axes[1].set_title("Controlled only: not promoted")
    fig.text(0.5, 0.03,
             "Different scoring semantics: reference-only and formulation-aware results are not one accuracy scale.\n"
             "No natural repair or DAG benefit. Controlled repair: one SCIP run, zero LLM calls; source and rollback preserved.",
             ha="center", fontsize=9, color="#444444")
    fig.tight_layout(rect=(0, 0.12, 1, 0.90))
    image = outdir / "precedence_witness_v0.1.png"
    fig.savefig(image, dpi=160, bbox_inches="tight")
    plt.close(fig)
    data = {
        "scope": "historical development; two valid natural alternatives and one controlled repair; not frozen or SOTA",
        "natural": {"legacy_reference_correct": 0, "independent_correct": 2,
                    "forms": {"BWOR-024": "cut", "BWOR-025": "completion/position_job"},
                    "natural_repairs": 0, "dag_evaluated": False},
        "arms": natural["arms"],
        "controlled_repair": {"independent_correct": True, "objective": 81,
                              "registry_decision": lifecycle["registry_decision"],
                              "solver_runs": 1, "llm_calls": 0},
        "sources": ["work/precedence_witness_v0.1/analysis.json",
                    "work/precedence_witness_v0.1/controlled_repair/lifecycle.json"],
    }
    path = outdir / "precedence_witness_v0.1.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    return image, path


def main() -> None:
    print(build_figure(ROOT / "docs/paper/figures"))


if __name__ == "__main__":
    main()
