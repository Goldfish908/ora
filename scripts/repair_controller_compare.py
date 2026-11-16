#!/usr/bin/env python3
"""Replay the fixed repair loop and compare the progress controller on prob_021."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.repair_controller import failure_signature
from scripts.m1_pilot import run_code
from scripts.scoped_ir_e2e import audit, load_initial, run_arm, score_nlp4lp
from scripts.scoped_ir_e2e_data import normalized_rows


def replay_fixed(outdir: Path, initial: dict, reference: dict, witness: dict,
                 source: dict) -> dict:
    problem_dir = outdir / "prob_021" / "fixed"
    problem_dir.mkdir(parents=True, exist_ok=True)
    current = initial
    history = [{"round": 0, "code_sha256": source["history"][0]["code_sha256"],
                "audit": audit("scoped_ir", witness, current["solution"],
                               reference["description"], [], "prob_021"),
                "execution": current["record"]}]
    for round_idx, previous in enumerate(source["history"][1:], 1):
        sandbox = problem_dir / f"round_{round_idx}"
        code = (ROOT / "work/scoped_ir_e2e/prob_021/scoped_ir" /
                f"round_{round_idx}/gen.py").read_text()
        record = run_code(code, sandbox)
        record["replayed_llm_usage"] = previous["execution"].get("usage")
        solution_path = sandbox / "solution.json"
        solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
        current = {"code": code, "solution": solution, "record": record}
        history.append({"round": round_idx,
                        "code_sha256": previous["code_sha256"],
                        "audit": audit("scoped_ir", witness, solution,
                                       reference["description"], [], "prob_021"),
                        "execution": record})
    author_usage = source.get("authoring_usage") or {}
    total_usage = source["usage"]
    repair_usage = {key: (total_usage.get(key, 0) or 0) - (author_usage.get(key, 0) or 0)
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
    initial_score = score_nlp4lp(reference, initial["solution"])
    final_score = score_nlp4lp(reference, current["solution"])
    signatures = [failure_signature(row["execution"], row["audit"]) for row in history]
    result = {
        "id": "prob_021", "arm": "fixed", "mode": "saved_llm_response_scip_replay",
        "initial_score": initial_score, "final_score": final_score,
        "initial_code": initial["code"], "final_code": current["code"],
        "history": history, "repair_calls": source["repair_calls"],
        "controller_transforms": 0,
        "same_failure_repairs": sum(a == b for a, b in zip(signatures, signatures[1:])),
        "authoring_usage": author_usage, "repair_usage": repair_usage,
        "usage": total_usage, "llm_calls_this_run": 0,
        "semantic_recovery": False,
        "improved": not initial_score["business_correct"] and final_score["business_correct"],
        "harmed_win": initial_score["business_correct"] and not final_score["business_correct"],
    }
    (problem_dir / "final.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    return result


def summary(row: dict) -> dict:
    return {
        "final_business_correct": row["final_score"]["business_correct"],
        "final_objective": row["history"][-1]["execution"].get("objective"),
        "objective_absolute_error": row["final_score"].get("objective_absolute_error"),
        "llm_repair_calls": row["repair_calls"],
        "repair_tokens": row["repair_usage"]["total_tokens"],
        "recorded_total_tokens_including_shared_authoring": row["usage"]["total_tokens"],
        "no_progress_repairs": row.get("same_failure_repairs", row.get("controller_no_progress")),
        "controller_transforms": row["controller_transforms"],
        "semantic_recovery": row["semantic_recovery"],
        "harmed_win": row["harmed_win"],
    }


def reference_cells(reference: dict) -> list[dict]:
    if reference["id"] != "prob_021":
        raise ValueError("these independent mutations are specific to prob_021")
    clean = reference["solution"]

    def cell(key, wrong, changes=None):
        solution = {"variables": dict(clean["variables"]), "objective": clean["objective"]}
        solution.update(changes or {})
        return {"key": key, "wrong": wrong, "mutation": key,
                "reference_violations": [key] if wrong else [], "solution": solution}

    regular = "RegularModelsProduced"
    return [cell("clean_reference", False),
            cell("objective_error", True, {"objective": clean["objective"] + 1000}),
            cell("capacity_error", True, {"variables": {**clean["variables"], regular: 9}}),
            cell("negative_error", True, {"variables": {**clean["variables"], regular: -1}})]


def main() -> None:
    outdir = ROOT / "work/repair_controller_v0.3"
    source_dir = ROOT / "work/scoped_ir_e2e/prob_021/scoped_ir"
    source = json.loads((source_dir / "final.json").read_text())
    reference = next(row for row in normalized_rows() if row["id"] == "prob_021")
    initial = load_initial("prob_021", ROOT / "runs/industryor/m3_z0_scoped_e2e_s0.jsonl")
    witness = json.loads((source_dir / "author.json").read_text())
    fixed = replay_fixed(outdir, initial, reference, witness, source)
    destination = outdir / "prob_021/scoped_ir"
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("author.json", "spec.json"):
        (destination / name).write_text((source_dir / name).read_text())
    controlled = run_arm("prob_021", "scoped_ir", reference["description"], [], initial,
                         score_nlp4lp(reference, initial["solution"]), reference,
                         outdir, max_repairs=2, temperature=0.2, cfg={},
                         gate_cells=reference_cells(reference), progress_controller=True)
    controlled["same_failure_repairs"] = controlled["controller_no_progress"]
    (destination / "final.json").write_text(json.dumps(controlled, ensure_ascii=False, indent=1) + "\n")
    result = {
        "id": "prob_021", "case_type": "natural_execution_failure",
        "shared_initial_code_sha256": fixed["history"][0]["code_sha256"],
        "fixed_repair_llm_source": str(source_dir.relative_to(ROOT)),
        "new_llm_calls": controlled["llm_calls_this_run"],
        "arms": {"fixed_two_llm_repairs": summary(fixed),
                 "progress_controller": summary(controlled)},
        "interpretation": ("Execution recovery, not semantic recovery. Repair-token accounting "
                           "uses recorded LLM usage; both current runs replay the same frozen "
                           "witness and make no new LLM calls."),
    }
    (outdir / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if not controlled["final_score"]["business_correct"] or controlled["harmed_win"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
