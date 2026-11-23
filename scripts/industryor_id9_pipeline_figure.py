#!/usr/bin/env python3
"""Draw the verified IndustryOR ID9 repair pipeline."""
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "work/industryor_id9_pipeline_v0.1/pipeline_gen0_gen1.png"


def box(axis, x, y, width, height, title, lines, color):
    patch = FancyBboxPatch(
        (x, y), width, height,
        boxstyle="round,pad=0.018,rounding_size=0.025",
        linewidth=1.2, edgecolor=color, facecolor=color + "18",
    )
    axis.add_patch(patch)
    axis.text(x + width / 2, y + height - 0.07, title,
              ha="center", va="top", fontsize=10, fontweight="bold", color=color)
    for index, line in enumerate(lines):
        axis.text(x + width / 2, y + height - 0.16 - index * 0.065, line,
                  ha="center", va="top", fontsize=8.2, color="#25313b")


def arrow(axis, start, end, text, color="#5f6b76"):
    patch = FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=16,
                            linewidth=1.4, color=color)
    axis.add_patch(patch)
    axis.text((start[0] + end[0]) / 2, (start[1] + end[1]) / 2 + 0.035, text,
              ha="center", va="bottom", fontsize=8, color=color)


def main() -> None:
    plt.rcParams.update({"font.family": "DejaVu Sans", "figure.dpi": 160})
    figure, axis = plt.subplots(figsize=(11.5, 4.7))
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")

    box(axis, 0.025, 0.36, 0.25, 0.42, "Gen0 — failed root", [
        "x3 = 0, y2 = 1",
        "Violation: link_x3_y2",
        "Public objective = 623",
        "Registered business = False",
    ], "#a84b43")
    box(axis, 0.375, 0.36, 0.25, 0.42, "Declarative neighborhood", [
        "Release: x1, x2, x3, x4, y2",
        "Fixed: y1, y_A, y_R",
        "Solve one SCIP sub-MILP",
        "Recheck the complete decision",
    ], "#9a741d")
    box(axis, 0.725, 0.36, 0.25, 0.42, "Gen1 — accepted elite", [
        "y2 = 0; fixed values unchanged",
        "No introduced violation",
        "Public objective = 623",
        "Business = True; proven optimal",
    ], "#187a68")

    arrow(axis, (0.275, 0.57), (0.375, 0.57), "dependency")
    arrow(axis, (0.625, 0.57), (0.725, 0.57), "full check")

    axis.text(0.5, 0.94, "IndustryOR ID9: one declarative repair is enough",
              ha="center", va="top", fontsize=14, fontweight="bold")
    axis.text(0.5, 0.86, "The objective already matched; the business relationship was wrong",
              ha="center", va="top", fontsize=9.5, color="#4d5560")
    axis.text(0.5, 0.26,
              "Correct control root: no neighborhood is built; original bytes and SHA256 are preserved.",
              ha="center", va="top", fontsize=8.8, color="#4d5560")
    axis.text(0.5, 0.17,
              "Current population budget: Gen0 root + at most Gen1 and Gen2; early stop on duplicates, UNKNOWN or no progress.",
              ha="center", va="top", fontsize=8.8, color="#4d5560")
    axis.text(0.5, 0.08,
              "This is a verified repair-only case, not a held-out or full natural-language generation result.",
              ha="center", va="top", fontsize=8.2, color="#6a737d")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(OUT, bbox_inches="tight")
    plt.close(figure)
    print(OUT)


if __name__ == "__main__":
    main()
