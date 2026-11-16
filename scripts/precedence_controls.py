#!/usr/bin/env python3
"""Shared-initial no-repair/fixed/progress controls for the precedence witness."""
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.acceptance import can_accept
from ora_agent.dvsa_model import solve_model
from ora_agent.flow_shop import audit_candidate, binding_for
from ora_agent.flow_shop_repair import model_digest, repair_completion_model
from ora_agent.repair_controller import ProgressController
from scripts.precedence_reaudit import run

POLICIES = ("no_repair", "fixed", "progress")


def audit_record(audit: dict) -> dict:
    correct = audit["business_correct"]
    if audit["status"] == "UNKNOWN":
        return {"status": "unknown", "fired": False, "violations": [],
                "unknown_evidence": audit.get("unknown", []), "rejected": []}
    return {"status": "ok", "fired": not correct,
            "violations": audit.get("violations", []), "unknown_evidence": [],
            "rejected": []}


def run_problem(case: dict, policy: str, outdir: Path) -> dict:
    root = Path(case["artifacts"])
    candidate = json.loads((root / "candidate.json").read_text())
    solution = json.loads((root / "solution.json").read_text())
    initial_audit = json.loads((root / "audit.json").read_text())
    reference = json.loads((ROOT / case["inputs"]["reference_model"]["path"]).read_text())
    question = (ROOT / case["inputs"]["question"]["path"]).read_text()
    binding = binding_for(reference, question)
    current = {"model": candidate, "solution": solution, "audit": initial_audit}
    initial = copy.deepcopy(current)
    accepted = None
    history = []
    transforms = 0
    solver_runs = 0
    controller = ProgressController() if policy == "progress" else None
    stop_reason = None
    for round_idx in range(3):
        record = audit_record(current["audit"])
        entry = {"round": round_idx, "model_sha256": model_digest(current["model"]),
                 "audit": record, "llm_calls": 0}
        history.append(entry)
        if can_accept(record, "accepted"):
            accepted = current
            stop_reason = "accepted"
            entry["action"] = "accept"
            break
        if policy == "no_repair" or round_idx >= 2:
            stop_reason = "no_repair" if policy == "no_repair" else "budget_exhausted"
            entry["action"] = "stop"
            break
        action = "local_patch"
        if controller is not None:
            decision = controller.decide(json.dumps(current["model"], sort_keys=True), {}, record,
                                         2 - round_idx)
            entry["controller_decision"] = decision.__dict__
            action = decision.action
            if action != "local_patch":
                stop_reason = decision.reason
                entry["action"] = action
                break
        try:
            repaired, repair_record = repair_completion_model(current["model"], reference, question)
        except ValueError as exc:
            stop_reason = str(exc)
            entry["action"] = "repair_not_applicable"
            break
        replay = solve_model(repaired, time_limit=60.0)
        transforms += 1
        solver_runs += 1
        entry["action"] = {"name": action, "transform": repair_record["transform"],
                           "before_sha256": repair_record["before_sha256"],
                           "after_sha256": repair_record["after_sha256"],
                           "rollback": repair_record["rollback"], "llm_calls": 0}
        if replay["status"] != "optimal":
            stop_reason = "repair_solve_failed"
            break
        current = {"model": repaired, "solution": replay["solution"],
                   "audit": audit_candidate(repaired, replay["solution"], binding)}
        entry["independent_score"] = current["audit"]
        if controller is not None:
            controller.record(decision, json.dumps(repaired, sort_keys=True))
    final = accepted or initial
    correct = final["audit"]["business_correct"]
    result = {
        "id": case["id"], "policy": policy,
        "initial_score": initial_audit, "final_score": final["audit"],
        "initial_model_sha256": model_digest(initial["model"]),
        "final_model_sha256": model_digest(final["model"]),
        "accepted_round": next((row["round"] for row in history if row["action"] == "accept"), None),
        "round0_unchanged": bool(accepted is not None and not transforms
                                 and model_digest(accepted["model"]) == model_digest(initial["model"])),
        "accepted": accepted is not None,
        "baseline_fallback": accepted is None,
        "stop_reason": stop_reason, "history": history,
        "controller_trace": controller.trace() if controller else [],
        "deterministic_transforms": transforms, "solver_runs_this_run": solver_runs,
        "llm_calls": 0, "tokens": 0,
        "improved": not initial_audit["business_correct"] and correct,
        "harmed_win": initial_audit["business_correct"] and not correct,
        "accepted_but_business_incorrect": accepted is not None and not correct,
    }
    directory = outdir / "controls" / policy / case["id"]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    (directory / "model.json").write_text(json.dumps(final["model"], ensure_ascii=False, indent=1) + "\n")
    (directory / "solution.json").write_text(json.dumps(final["solution"], ensure_ascii=False, indent=1) + "\n")
    return result


def summarize(rows: list[dict]) -> dict:
    return {
        "n": len(rows),
        "initial_business_correct": sum(row["initial_score"]["business_correct"] for row in rows),
        "final_business_correct": sum(row["final_score"]["business_correct"] for row in rows),
        "recoveries": sum(row["improved"] for row in rows),
        "round0_unchanged": sum(row["round0_unchanged"] for row in rows),
        "harmed_win": sum(row["harmed_win"] for row in rows),
        "accepted_but_business_incorrect": sum(row["accepted_but_business_incorrect"] for row in rows),
        "baseline_fallback": sum(row["baseline_fallback"] for row in rows),
        "deterministic_transforms": sum(row["deterministic_transforms"] for row in rows),
        "solver_runs_this_run": sum(row["solver_runs_this_run"] for row in rows),
        "llm_calls": 0, "tokens": 0,
    }


def run_controls(analysis: dict, outdir: Path) -> dict:
    results = [run_problem(case, policy, outdir)
               for case in analysis["results"] for policy in POLICIES]
    analysis["arms"] = {policy: summarize([row for row in results if row["policy"] == policy])
                        for policy in POLICIES}
    analysis["control_results"] = results
    analysis["run_config"]["policies"] = list(POLICIES)
    analysis["run_config"]["max_repairs"] = 2
    analysis["run_config"]["implementation_sha256"].update({
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
            "scripts/precedence_controls.py", "ora_agent/flow_shop_repair.py",
            "ora_agent/repair_controller.py", "assets/scoped_ir/job_precedence_v0.1.json")})
    analysis["candidate_dag"] = {
        "status": "not_run_no_natural_repair_opportunity",
        "reason": "All shared natural initials are independently correct; no valid repair trigger exists.",
        "simulated_recoveries_claimed": False,
    }
    (outdir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=1) + "\n")
    return analysis


def main() -> None:
    analysis = run_controls(run(ROOT / "work/precedence_witness_v0.1"),
                            ROOT / "work/precedence_witness_v0.1")
    print(json.dumps(analysis["arms"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
