#!/usr/bin/env python3
"""Plot accepted, rejected and UNKNOWN binding outcomes without conflating them."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def load_results():
    return json.loads((ROOT / "work/binding_validation_v0.1/analysis.json").read_text())


def build_figure(outdir: Path) -> tuple[Path, Path]:
    analysis = load_results()
    summary = analysis["summary"]
    outdir.mkdir(parents=True, exist_ok=True)
    labels = ("Valid bindings", "Wrong bindings\nrejected", "Missing evidence\nUNKNOWN",
              "Conflicts\nUNKNOWN")
    keys = ("valid_bindings", "wrong_bindings_rejected", "missing_evidence_unknown", "conflicts_unknown")
    values = [summary[key] for key in keys]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    bars = ax.bar(range(4), values, color=("#059669", "#dc2626", "#64748b", "#94a3b8"), width=0.6)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.05, f"{value}/2", ha="center")
    ax.set_xticks(range(4), labels)
    ax.set_ylim(0, 2.5)
    ax.set_ylabel("Number of problem families")
    ax.set_title("Same binding validator across IndustryOR and BWOR")
    fig.text(0.5, 0.025,
             "Reference-assisted controlled proposals; no LLM calls. UNKNOWN is not acceptance or detection. "
             "Protocol reuse is not universal transfer.",
             ha="center", fontsize=9, color="#444444")
    fig.tight_layout(rect=(0, 0.10, 1, 0.95))
    image = outdir / "binding_validation_v0.1.png"
    fig.savefig(image, dpi=160, bbox_inches="tight")
    plt.close(fig)
    data = {"scope": analysis["run_config"]["exposure"], "summary": summary,
            "accepted_but_business_incorrect": summary["accepted_but_business_incorrect"],
            "new_llm_calls": 0,
            "sources": ["work/binding_validation_v0.1/analysis.json"]}
    path = outdir / "binding_validation_v0.1.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    return image, path


def main() -> None:
    print(build_figure(ROOT / "docs/paper/figures"))


if __name__ == "__main__":
    main()
