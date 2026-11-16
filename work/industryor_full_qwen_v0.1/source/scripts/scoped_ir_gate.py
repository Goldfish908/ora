#!/usr/bin/env python3
"""Gate scoped IR assets on independent reference artifacts before repair."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.scoped_ir import evaluate_spec, independent_gate_passed
from scripts.memory_witness_cegis import load_cells


def gate(spec: dict, question: str, cells: list[dict], problem_id: str) -> dict:
    evaluation = evaluate_spec(spec, question, cells, problem_id)
    accepted = evaluation["dev_passed"] and independent_gate_passed(evaluation)
    return {"accepted": accepted, "status": "accepted" if accepted else "rejected",
            "evaluation": evaluation}


def main() -> None:
    problem_id = "prob_104"
    artifact_dir = ROOT / "work/memory_witness/nlp4lp_artifacts_v2/validation"
    cells = load_cells(artifact_dir / "cells.jsonl", [problem_id])[problem_id]
    question = (artifact_dir / f"{problem_id}__question.txt").read_text()
    specs = {
        "llm_authored_shared_bias": ROOT / "work/scoped_ir_e2e/prob_104/scoped_ir/spec.json",
        "curated_makespan": ROOT / "work/scoped_ir_e2e_demo_v0.4/prob_104/scoped_ir/spec.json",
    }
    results = {}
    for name, path in specs.items():
        spec = json.loads(path.read_text())
        results[name] = gate(spec, question, cells, problem_id)
        results[name]["spec_path"] = str(path)
        print(name, results[name]["status"],
              f"det={results[name]['evaluation']['detection']:.1%}",
              f"fp={results[name]['evaluation']['false_positive']:.1%}",
              f"unknown={results[name]['evaluation']['unknown']}")
    outdir = ROOT / "work/scoped_ir_gate_v0.1"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "analysis.json").write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
