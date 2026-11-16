"""RetailOpt DVSA assets, deterministic feedback and legacy-reference scoring."""
from __future__ import annotations

import json
from pathlib import Path

from m1_witness import retailopt as legacy
from ora_agent.dvsa import asset_sha256, run_asset

ROOT = Path(__file__).resolve().parents[1]
ASSET_PATHS = [ROOT / "assets/dvsa/retailopt_demand_v0.1.json",
               ROOT / "assets/dvsa/retailopt_initial_inventory_v0.1.json"]


def load_assets(paths=None):
    assets = [json.loads(path.read_text()) for path in (paths or ASSET_PATHS)]
    return assets, {asset["asset_id"]: asset_sha256(asset) for asset in assets}


def asset_audit(assets, data, solution):
    return [run_asset(asset, data, solution, domain="retailopt") for asset in assets]


def semantic_feedback(assets, data, solution):
    if solution is None:
        return {"status": "UNKNOWN", "reason": "no_solution", "violations": [], "unknown": []}, []
    audits = asset_audit(assets, data, solution)
    violations = [{"asset_id": audit["asset_id"], "implementation_sha256": audit["implementation_sha256"],
                   "violations": audit["violations"]}
                  for audit in audits if audit["status"] == "VIOLATED"]
    unknown = [{"asset_id": audit["asset_id"], "unknown": audit["unknown"]}
               for audit in audits if audit["status"] == "UNKNOWN"]
    return {"status": "VIOLATED" if violations else "UNKNOWN" if unknown else "SATISFIED",
            "violations": violations, "unknown": unknown}, audits


def legacy_feedback(data, solution):
    if solution is None:
        return {"status": "UNKNOWN", "reason": "no_solution", "violations": []}
    result = legacy.check(data, solution)
    return {"status": "VIOLATED" if result["violations"] else "SATISFIED",
            "violations": [{"rule": rule, "detail": detail}
                           for rule, detail in result["violations"]],
            "warnings": result["warnings"]}


def business_score(data, reference_objective, solution):
    if solution is None:
        return {"business_correct": False, "semantic_valid": False,
                "objective_correct": False, "status": "no_solution"}
    result = legacy.check(data, solution)
    semantic_valid = not result["violations"]
    objective = solution.get("objective")
    error = None
    if isinstance(objective, (int, float)):
        error = abs(float(objective) - float(reference_objective)) / max(abs(float(reference_objective)), 1e-9)
    objective_correct = error is not None and error <= 1e-3
    return {"business_correct": semantic_valid and objective_correct,
            "semantic_valid": semantic_valid, "objective_correct": objective_correct,
            "objective_relative_error": error, "status": "scored",
            "legacy_reference_audit": result,
            "note": "Legacy-witness business feasibility plus reference objective; not a proof of model equivalence or independent semantic truth."}


def select_win_safe_solution(data, reference_objective, initial_solution, initial_score,
                             candidate_solution):
    candidate_score = business_score(data, reference_objective, candidate_solution)
    if initial_score.get("business_correct") and not candidate_score["business_correct"]:
        return {"solution": initial_solution, "score": initial_score,
                "candidate_score": candidate_score, "baseline_fallback": True}
    return {"solution": candidate_solution, "score": candidate_score,
            "candidate_score": candidate_score, "baseline_fallback": False}
