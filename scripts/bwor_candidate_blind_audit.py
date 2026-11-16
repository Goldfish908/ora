#!/usr/bin/env python3
"""Correct saved candidate-blind error labels without replaying or changing decisions."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.bwor_candidate_blind_replay import IDS
from scripts.bwor_scoped_loop import reference_violation_labels


def run_audit(outdir: Path) -> dict:
    source = ROOT / "work/bwor_candidate_blind_replay_v0.1"
    original_analysis = json.loads((source / "analysis.json").read_text())
    rows = []
    for problem_id in IDS:
        gate_path = source / problem_id / "scoped_ir/gate.json"
        gate = json.loads(gate_path.read_text())
        initial_path = source / problem_id / "initial/result.json"
        initial = json.loads(initial_path.read_text())
        score = initial["score"]
        labels = reference_violation_labels(score) if not score["business_correct"] else []
        record = next(row for row in gate["evaluation"]["records"] if row["key"] == "natural_initial")
        rows.append({
            "id": problem_id,
            "original_label": {"mutation": record["mutation"],
                               "reference_violations": record["reference_violations"]},
            "corrected_label": {
                "mutation": "natural_initial_clean" if score["business_correct"] else
                            "natural_initial_objective_error" if labels == ["OBJECTIVE"]
                            else "natural_initial_reference_error",
                "reference_violations": labels,
            },
            "decision_evidence_unchanged": {"wrong": record["wrong"], "fired": record["fired"],
                                            "status": record["status"], "gate_accepted": gate["accepted"]},
            "independent_score": score,
            "original_gate_sha256": hashlib.sha256(gate_path.read_bytes()).hexdigest(),
            "initial_result_sha256": hashlib.sha256(initial_path.read_bytes()).hexdigest(),
        })
    result = {
        "schema_version": "bwor.candidate_blind.label_audit.v0.1",
        "source_analysis_sha256": hashlib.sha256((source / "analysis.json").read_bytes()).hexdigest(),
        "executed_implementation_sha256": original_analysis["run_config"]["implementation_sha256"],
        "status": "posthoc_label_correction_no_replay",
        "behavior_changed": False,
        "new_llm_calls": 0, "new_solver_runs": 0,
        "rows": rows,
    }
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "label_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    return result


def main() -> None:
    result = run_audit(ROOT / "work/bwor_candidate_blind_replay_v0.1")
    print(json.dumps({"status": result["status"], "behavior_changed": result["behavior_changed"],
                      "corrected": [row["id"] for row in result["rows"]
                                    if row["original_label"] != row["corrected_label"]]}, indent=1))


if __name__ == "__main__":
    main()
