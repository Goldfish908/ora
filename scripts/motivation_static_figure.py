#!/usr/bin/env python3
"""Build the publication-style static proxy–semantic gap figure from saved artifacts."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
A0_RUN = ROOT / "work/retailopt_gepa_stream_a0_v0.3"
PILOT = ROOT / "work/motivation_phantom_cases_v0.1.json"
EVALPLUS = ROOT / "work/evalplus_gepa_full_v0.1/analysis.json"
AUDIT = ROOT / "work/motivation_witness_reference_v0.1/summary.json"
GAP = ROOT / "data/m1_retailopt/gapcheck60_f1f4.jsonl"
CASE_ID = "retail_f3_storage_bottleneck_v2"

BLUE = "#0072B2"
ORANGE = "#D55E00"
GRAY = "#C7C7C7"
DARK = "#222222"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def outcome(record: dict) -> str:
    if record["true_correct"]:
        return "true"
    if record["phantom_proxy"]:
        return "phantom"
    return "unknown"


def load_evidence() -> dict:
    a0 = read_json(A0_RUN / "analysis.json")
    seed, accepted = a0["curves"][:2]
    transitions = Counter()
    transition_ids = {}
    for scenario_id in a0["val_ids"]:
        records = []
        for candidate in (seed, accepted):
            path = A0_RUN / "rollouts" / candidate["candidate_sha256"] / f"{scenario_id}.json"
            records.append(read_json(path))
        pair = tuple(outcome(record) for record in records)
        key = f"{pair[0]}_to_{pair[1]}"
        transitions[key] += 1
        transition_ids.setdefault(key, []).append(scenario_id)

    pilot = read_json(PILOT)
    case = next(row for row in pilot["cases"] if row["scenario_id"] == CASE_ID)
    references = {
        row["scenario_id"]: row["reference_objective"]
        for row in (json.loads(line) for line in GAP.read_text().splitlines() if line)
    }
    evalplus = read_json(EVALPLUS)
    audit = read_json(AUDIT)
    return {
        "seed": seed,
        "accepted": accepted,
        "transitions": dict(transitions),
        "transition_ids": transition_ids,
        "case": case,
        "case_reference_objective": references[CASE_ID],
        "evalplus": evalplus["curves"],
        "audit": audit,
        "pilot": {key: pilot[key] for key in ("candidate_records", "proxy_match", "phantom_proxy", "phantom_rule_counts")},
        "sources": [str(path.relative_to(ROOT)) for path in (A0_RUN / "analysis.json", PILOT, EVALPLUS, AUDIT)],
    }


def panel_title(axis, label: str, title: str) -> None:
    axis.set_title(f"({label})  {title}", loc="left", fontsize=11, fontweight="semibold", pad=10)


def box(axis, x: float, y: float, width: float, height: float, text: str,
        facecolor: str = "#F7F7F7", edgecolor: str = "#777777", fontsize: float = 9) -> None:
    patch = FancyBboxPatch((x, y), width, height,
                           boxstyle="round,pad=0.012,rounding_size=0.018",
                           linewidth=0.9, edgecolor=edgecolor, facecolor=facecolor)
    axis.add_patch(patch)
    axis.text(x + width / 2, y + height / 2, text, ha="center", va="center", fontsize=fontsize)


def arrow(axis, start: tuple[float, float], end: tuple[float, float], text: str = "") -> None:
    axis.annotate("", xy=end, xytext=start,
                  arrowprops={"arrowstyle": "-|>", "lw": 1.1, "color": "#666666", "shrinkA": 2, "shrinkB": 2})
    if text:
        axis.text((start[0] + end[0]) / 2, (start[1] + end[1]) / 2 + 0.035,
                  text, ha="center", va="bottom", fontsize=8, color="#555555")


def build_figure(evidence: dict, outdir: Path) -> tuple[Path, Path]:
    seed = evidence["seed"]
    assert seed["n"] == 60 and seed["records"] == 60
    assert seed["true_correct"] + seed["phantom_proxy"] + seed["truth_unknown"] == 60
    assert evidence["transitions"].get("true_to_phantom", 0) == 0
    assert evidence["transitions"].get("unknown_to_phantom", 0) == 0

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.labelsize": 9,
        "axes.edgecolor": "#666666",
        "axes.linewidth": 0.8,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "legend.fontsize": 8,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })
    fig, axes = plt.subplots(2, 2, figsize=(7.25, 5.65))
    fig.subplots_adjust(left=0.075, right=0.985, top=0.93, bottom=0.17, wspace=0.42, hspace=0.73)

    axis = axes[0, 0]
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")
    panel_title(axis, "a", "Proxy–semantic gap")
    box(axis, 0.02, 0.68, 0.26, 0.18, "LLM-generated\nmodel")
    box(axis, 0.38, 0.68, 0.24, 0.18, "SCIP optimal\nobjective")
    box(axis, 0.72, 0.68, 0.26, 0.18, "Objective\nacceptable", "#EAF2F8", BLUE)
    arrow(axis, (0.28, 0.77), (0.38, 0.77))
    arrow(axis, (0.62, 0.77), (0.72, 0.77), "proxy")
    axis.text(0.85, 0.56, "PROXY PASS", color=BLUE, ha="center", fontsize=9, fontweight="bold")
    arrow(axis, (0.85, 0.66), (0.85, 0.42))
    axis.text(0.60, 0.50, "independent Witness", ha="center", fontsize=8, color="#555555")
    box(axis, 0.08, 0.15, 0.34, 0.2, "Witness PASS\nTrue correct", "#EAF4EF", "#238B45")
    box(axis, 0.58, 0.15, 0.34, 0.2, "Witness FAIL\nPhantom success", "#FCEDE6", ORANGE)
    arrow(axis, (0.79, 0.48), (0.25, 0.35))
    arrow(axis, (0.85, 0.48), (0.75, 0.35))
    axis.text(0.5, 0.025, "Solver success does not establish business feasibility.",
              ha="center", fontsize=8, color="#555555")

    axis = axes[0, 1]
    panel_title(axis, "b", "RetailOpt seed (N=60)")
    true = seed["true_correct"]
    phantom = seed["phantom_proxy"]
    unknown = seed["truth_unknown"]
    left = 0
    for value, color in ((true, BLUE), (phantom, ORANGE), (unknown, GRAY)):
        axis.barh([0], [value], left=left, height=0.36, color=color, edgecolor="white", linewidth=0.8)
        left += value
    axis.annotate(f"True correct: {true}", xy=(true / 2, 0.18), xytext=(0, 0.56),
                  ha="left", color=BLUE, fontsize=9,
                  arrowprops={"arrowstyle": "-", "color": BLUE, "lw": 0.8})
    axis.text(true + phantom / 2, 0, f"Phantom: {phantom}", ha="center", va="center",
              color="white", fontsize=9, fontweight="bold")
    axis.text(true + phantom + unknown / 2, 0, f"UNKNOWN: {unknown}",
              ha="center", va="center", color=DARK, fontsize=9)
    axis.text((true + phantom) / 2, 0.28, f"Proxy pass = {true + phantom}",
              ha="center", va="bottom", fontsize=8.5)
    axis.text(true + phantom + 1.5, -0.43,
              f"Phantom / proxy pass\n= {phantom}/{true + phantom} = {phantom / (true + phantom):.0%}",
              ha="left", va="top", color=ORANGE, fontsize=9, fontweight="semibold")
    axis.set_xlim(0, 60)
    axis.set_ylim(-0.85, 0.72)
    axis.set_yticks([])
    axis.set_xlabel("Tasks")
    axis.set_xticks([0, 20, 40, 60])
    axis.spines[["left", "top", "right"]].set_visible(False)

    axis = axes[1, 0]
    axis.axis("off")
    panel_title(axis, "c", "Case: lower cost, wrong semantics")
    case = evidence["case"]
    candidate_objective = case["objective"]
    reference_objective = evidence["case_reference_objective"]
    inset = axis.inset_axes([0.04, 0.56, 0.92, 0.29])
    inset.barh([1], [reference_objective], height=0.48, color=GRAY, label="Reference")
    inset.barh([0], [candidate_objective], height=0.48, color=ORANGE, label="Candidate")
    inset.set_yticks([0, 1], ["Candidate", "Reference"])
    inset.set_xlim(0, reference_objective * 1.27)
    inset.set_xticks([])
    inset.spines[["left", "top", "right", "bottom"]].set_visible(False)
    inset.tick_params(axis="y", length=0, labelsize=8)
    for value, objective in ((0, candidate_objective), (1, reference_objective)):
        inset.text(objective + reference_objective * 0.025, value, f"{objective:,.0f}", va="center", fontsize=8.5)
    inset.set_title(f"Objective (minimize): {candidate_objective / reference_objective - 1:.1%}",
                    fontsize=8.5, pad=2, color=ORANGE)
    axis.text(0.03, 0.47, CASE_ID, fontsize=8, family="DejaVu Sans Mono", color="#555555")
    axis.text(0.03, 0.34, r"$I[\mathrm{Basic,DC1},t=1,r=9]=36.99\neq 0$",
              fontsize=9, color=DARK)
    axis.text(0.03, 0.21, "Demand balance:  $-39.50 \\neq 43.25$", fontsize=9, color=DARK)
    axis.text(0.03, 0.07, "Proxy: better_than_reference    Witness: INFEASIBLE",
              fontsize=8.5, color=ORANGE, fontweight="semibold")

    axis = axes[1, 1]
    panel_title(axis, "d", "EvalPlus static gap (N=60)")
    rows = evidence["evalplus"]
    x = [0, 1]
    passed = [row["true_correct"] for row in rows]
    phantom_eval = [row["phantom_proxy"] for row in rows]
    axis.bar(x, passed, width=0.5, color=BLUE, label="Both test suites pass")
    axis.bar(x, phantom_eval, bottom=passed, width=0.5, color=ORANGE,
             label="Base pass / Plus fail")
    for index, row in enumerate(rows):
        axis.text(index, row["true_correct"] / 2, str(row["true_correct"]),
                  ha="center", va="center", color="white", fontsize=9, fontweight="bold")
        axis.text(index, row["true_correct"] + row["phantom_proxy"] / 2,
                  str(row["phantom_proxy"]), ha="center", va="center", color="white",
                  fontsize=8, fontweight="bold")
    axis.set_xticks(x, ["Seed\nBase: 60/60", "Accepted\nBase: 60/60"])
    axis.set_ylim(0, 74)
    axis.set_ylabel("Tasks")
    axis.set_yticks([0, 20, 40, 60])
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(loc="upper left", frameon=False, handlelength=1.2, borderaxespad=0.1, fontsize=7.5)

    fig.text(0.075, 0.065,
             "Static evidence only; UNKNOWN is not counted as correct. "
             "The pilot is proxy-selected, not a population sample.",
             ha="left", fontsize=8, color="#444444")
    fig.text(0.075, 0.032,
             "Reference/Witness audit: 100/100 pass; saved objectives match 95/100. "
             "Witness coverage remains incomplete.",
             ha="left", fontsize=8, color="#444444")

    outdir.mkdir(parents=True, exist_ok=True)
    png = outdir / "motivation_static_evidence_v0.2.png"
    pdf = outdir / "motivation_static_evidence_v0.2.pdf"
    fig.savefig(png, dpi=320, bbox_inches="tight", facecolor="white")
    fig.savefig(pdf, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return png, pdf


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", default="docs/paper/figures")
    args = parser.parse_args()
    evidence = load_evidence()
    paths = build_figure(evidence, ROOT / args.outdir)
    data_path = ROOT / "work/motivation_static_evidence_v0.2_data.json"
    data_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"figures": [str(path) for path in paths], "data": str(data_path)}, indent=1))


if __name__ == "__main__":
    main()
