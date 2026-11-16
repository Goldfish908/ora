#!/usr/bin/env python3
"""Plot saved-response contract recovery and the candidate-blind negative control."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BLIND_IMPLEMENTATION = {
    "scripts/bwor_saved_contract_replay.py": "e22b5bfb88faf19c92c7bf40e311c7a1988c04d2e4dc70ff9d817e05ece2a82f",
    "ora_agent/dvsa_model.py": "e690e5eafe87dc615fc31c2d3712586997eea55fd6a06e40db12dc8ae18da670",
    "scripts/frozen_scoped_evaluate.py": "699a62af894ced669c673080b518dbb008fe7297589e4405c4cd1e5ac0d89e46",
    "scripts/bwor_scoped_loop.py": "d424a10817465008137afaf0645174459b86d45d223263192faa8915b104c3fd",
}


def load_results() -> dict:
    development = json.loads((ROOT / "work/bwor_saved_contract_replay_v0.2/analysis.json").read_text())
    blind = json.loads((ROOT / "work/bwor_candidate_blind_replay_v0.1/analysis.json").read_text())
    assert blind["run_config"]["implementation_sha256"] == EXPECTED_BLIND_IMPLEMENTATION
    for analysis in (development, blind):
        assert analysis["cost"]["new_llm_calls"] == 0
        for arm in ("fixed", "progress"):
            assert analysis["arms"][arm]["harmed_win"] == 0
            assert analysis["arms"][arm]["accepted_but_reference_incorrect"] == 0
    return {"development": development, "blind": blind}


def build_figure(outdir: Path) -> tuple[Path, Path]:
    results = load_results()
    outdir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    fig.suptitle("Saved-response replay: execution recovery, no controller gain", fontsize=14)
    colors = ("#9ca3af", "#0ea5e9", "#2563eb", "#059669")
    for ax, key, title in zip(axes, ("development", "blind"),
                            ("Development-exposed six responses", "Candidate-blind six responses")):
        analysis = results[key]
        legacy = analysis["denominators"]["legacy_initial_business_correct"]
        normalized = analysis["denominators"]["initial_business_correct"]
        fixed = analysis["arms"]["fixed"]["final_reference_correct"]
        progress = analysis["arms"]["progress"]["final_reference_correct"]
        values = (legacy, normalized, fixed, progress)
        bars = ax.bar(range(4), values, color=colors, width=0.65)
        for bar, value in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, value + 0.1, f"{value}/6", ha="center")
        ax.set_xticks(range(4), ("Legacy", "Normalized", "Fixed", "Progress"), rotation=15)
        ax.set_ylim(0, 6.8)
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.2)
    axes[0].set_ylabel("Independent reference-correct tasks")
    fig.text(0.5, 0.035,
             "Development: 3 execution recoveries from deterministic path/list-index normalization. "
             "Candidate-blind: 0 recoveries.\n"
             "Historical replay, not new generation/frozen evaluation. "
             "No LLM calls, harmed wins, or incorrect acceptances.",
             ha="center", fontsize=9, color="#444444")
    fig.tight_layout(rect=(0, 0.12, 1, 0.91))
    image = outdir / "contract_recovery_v0.1.png"
    fig.savefig(image, dpi=160, bbox_inches="tight")
    plt.close(fig)
    data = {
        "scope": "historical saved-response and candidate-blind replays; not new generation or frozen evaluation",
        "development": {
            "legacy_correct": results["development"]["denominators"]["legacy_initial_business_correct"],
            "normalized_correct": results["development"]["denominators"]["initial_business_correct"],
            "business_recovered_after_normalization": results["development"]["denominators"]["business_recovered_after_normalization"],
            "fixed_correct": results["development"]["arms"]["fixed"]["final_reference_correct"],
            "progress_correct": results["development"]["arms"]["progress"]["final_reference_correct"],
        },
        "blind": {
            "legacy_correct": results["blind"]["denominators"]["legacy_initial_business_correct"],
            "normalized_correct": results["blind"]["denominators"]["initial_business_correct"],
            "fixed_correct": results["blind"]["arms"]["fixed"]["final_reference_correct"],
            "progress_correct": results["blind"]["arms"]["progress"]["final_reference_correct"],
            "failed_ids": ["BWOR-024", "BWOR-025"],
            "failure_scope": "reference-schema mismatch, not proven model errors; both alternatives independently validated in precedence_reaudit",
        },
        "new_llm_calls": 0,
        "sources": ["work/bwor_saved_contract_replay_v0.2/analysis.json",
                    "work/bwor_candidate_blind_replay_v0.1/analysis.json",
                    "work/bwor_candidate_blind_replay_v0.1/label_audit.json"],
    }
    path = outdir / "contract_recovery_v0.1.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    return image, path


def main() -> None:
    print(build_figure(ROOT / "docs/paper/figures"))


if __name__ == "__main__":
    main()
