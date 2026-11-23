#!/usr/bin/env python3
"""Render the actual ID20 pipeline and per-generation outcomes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
ARMS = ["direct-full", "declarative", "single", "old-population", "pareto-only"]
LABELS = {
    "direct-full": "Direct full",
    "declarative": "Declarative",
    "single": "Single chain",
    "old-population": "Old population",
    "pareto-only": "Pareto only",
}
OPERATIONS = {
    "default_declarative_neighborhood": "local",
    "direct_full_reoptimization": "full",
    "feasible_parent_objective_optimization": "objective",
}
COLORS = {"elite": "#187a68", "exploration": "#d5a03c", "rejected": "#a84b43"}


def pipeline_box(axis, x, y, width, height, title, lines, color):
    axis.add_patch(FancyBboxPatch(
        (x, y), width, height,
        boxstyle="round,pad=0.012,rounding_size=0.018",
        linewidth=1.0, edgecolor=color, facecolor=color + "18",
    ))
    axis.text(x + width / 2, y + height - 0.04, title,
              ha="center", va="top", fontsize=8.5, fontweight="bold", color=color)
    for index, line in enumerate(lines):
        axis.text(x + width / 2, y + height - 0.085 - index * 0.035, line,
                  ha="center", va="top", fontsize=7.1, color="#25313b")


def reason(candidate):
    text = candidate.get("repair_reason") or "rejected"
    return {
        "solver_error:NotReadyError": "not ready",
        "optimization_requires_feasible_parent": "infeasible",
        "empty_neighborhood": "empty",
    }.get(text, text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    audit = json.loads((ROOT / args.audit).read_text())
    scenario = next(row for row in audit["scenarios"] if row["role"] == "narrow_failure")

    plt.rcParams.update({"font.family": "DejaVu Sans", "figure.dpi": 160})
    figure, axis = plt.subplots(figsize=(12.2, 6.8))
    axis.set_xlim(0, 1.12)
    axis.set_ylim(0, 1)
    axis.axis("off")

    axis.text(0.53, 0.975, "IndustryOR ID20: all five strategies recover, one local repair is enough",
              ha="center", va="top", fontsize=13, fontweight="bold")
    axis.text(0.53, 0.93,
              "Failed root: objective 960 and three violations  →  final: objective 956, zero violations, proven optimal",
              ha="center", va="top", fontsize=9, color="#4d5560")

    pipeline_box(axis, 0.02, 0.72, 0.22, 0.14, "Gen0 — failed root", [
        "x1=0, x2=120, x3=0, x4=0",
        "cars_imply_blocks / x3_y3 / x4_y4",
        "Registered business = False",
    ], "#a84b43")
    pipeline_box(axis, 0.30, 0.72, 0.25, 0.14, "Public evaluation", [
        "Build violation keys and dependency graph",
        "Release only relevant variables",
        "Keep unrelated variables fixed",
    ], "#9a741d")
    pipeline_box(axis, 0.61, 0.72, 0.20, 0.14, "Gen1 — accepted elite", [
        "Objective = 956",
        "No introduced violation",
        "Registered business = True",
    ], "#187a68")
    pipeline_box(axis, 0.87, 0.72, 0.21, 0.14, "Independent audit", [
        "proven_optimal",
        "en_answer = 956 matched",
        "Correct control bytes preserved",
    ], "#187a68")
    for x0, x1 in ((0.24, 0.30), (0.55, 0.61), (0.81, 0.87)):
        axis.annotate("", xy=(x1, 0.79), xytext=(x0, 0.79),
                      arrowprops={"arrowstyle": "-|>", "color": "#66717c", "lw": 1.3})

    axis.text(0.03, 0.66, "Actual candidate outcomes by generation", fontsize=10,
              fontweight="bold", color="#25313b")
    generation_x = {1: 0.23, 2: 0.44, 3: 0.65, 4: 0.86}
    for generation, x in generation_x.items():
        axis.text(x + 0.085, 0.62, f"Gen{generation}", ha="center", va="top",
                  fontsize=9, fontweight="bold", color="#4d5560")

    for row_index, arm in enumerate(ARMS):
        center_y = 0.52 - row_index * 0.105
        axis.text(0.02, center_y, LABELS[arm], ha="left", va="center",
                  fontsize=8.5, fontweight="bold", color="#25313b")
        candidates = scenario["arms"][arm]["candidates"]
        for generation, x in generation_x.items():
            current = [candidate for candidate in candidates if candidate["generation"] == generation]
            if not current:
                continue
            axis.add_patch(FancyBboxPatch(
                (x, center_y - 0.043), 0.17, 0.086,
                boxstyle="round,pad=0.004,rounding_size=0.008",
                linewidth=0.7, edgecolor="#c8ced5", facecolor="#f7f8fa",
            ))
            for line_index, candidate in enumerate(current):
                operation = OPERATIONS.get(candidate["operation"], candidate["operation"])
                result = (f"{operation} {candidate['objective']:.0f}" if candidate["objective"] is not None
                          else f"{operation} {reason(candidate)}")
                axis.text(x + 0.085, center_y + 0.027 - line_index * 0.026, result,
                          ha="center", va="center", fontsize=6.8,
                          color=COLORS.get(candidate["role"], "#66717c"))

    axis.text(0.02, 0.045,
              "Merge: attempted 12 / tested 0 / not_tested 12 (no compatible lineage). "
              "LLM calls = 0; SCIP sub-MILPs = 17; total search ledger = 4.72 s.",
              ha="left", va="center", fontsize=8.2, color="#4d5560")
    axis.text(0.02, 0.005,
              "Development validation only. All final artifacts were frozen before fresh independent business scoring.",
              ha="left", va="center", fontsize=8.2, color="#6a737d")

    output = ROOT / args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, bbox_inches="tight")
    plt.close(figure)
    print(output)


if __name__ == "__main__":
    main()
