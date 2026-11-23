#!/usr/bin/env python3
"""Same-root population, single-chain, and direct-full federated repair audit."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ora_agent.cleanroom import PASS
from ora_agent.declarative_neighborhood import (
    DECISION_REPAIR,
    OBJECTIVE_OPTIMIZATION,
    DecisionArtifact,
    EmptyNeighborhoodError,
    NeighborhoodSpec,
)
from ora_agent.federated_neighborhood import FederatedNeighborhoodRepair
from ora_agent.federated_public_ir import (
    CLIENT_UNIQUE,
    GPU_BUDGET,
    PRIVACY_BUDGET,
    STREAM_CLIENTS,
    STREAM_ENCLAVES,
    STREAM_EXAMPLES,
    UPLOAD_BUDGET,
    load_public_files,
    load_public_problem,
    pair_key,
    solution_file_to_artifact,
    variable_name,
)
from ora_agent.oragentbench import (
    TaskPacket,
    official_evaluate,
    official_metrics,
    prepare_workspace,
    write_json,
)
from ora_agent.population_repair import (
    FEASIBLE,
    INFEASIBLE,
    UNKNOWN,
    BusinessResult,
    Candidate,
    Evaluation,
    Mutation,
    PopulationRepairController,
    RepairRun,
)
from scripts.federated_repair_audit import (
    CLEAN_PATH,
    all_budgets,
    duplicate_client,
    stream_minimums,
)

DEFAULT_OPERATION = "default_declarative_neighborhood"
DIRECT_OPERATION = "direct_full_reoptimization"
OBJECTIVE_OPERATION = "feasible_parent_objective_optimization"
OPERATIONS = (DEFAULT_OPERATION, DIRECT_OPERATION, OBJECTIVE_OPERATION)
STRATEGIES = ("single_chain", "population", "direct_full")
SCENARIO_BUILDERS = {
    "duplicate_client": duplicate_client,
    "stream_minimums": stream_minimums,
    "all_budgets": all_budgets,
}
EXPECTED_VIOLATIONS = {
    "duplicate_client": {CLIENT_UNIQUE},
    "stream_minimums": {STREAM_CLIENTS, STREAM_EXAMPLES, STREAM_ENCLAVES},
    "all_budgets": {PRIVACY_BUDGET, UPLOAD_BUDGET, GPU_BUDGET},
}
SEARCH_SETTINGS = {
    "k": 3,
    "depth": 2,
    "evaluation_budget": 6,
    "allow_exploration": True,
    "direct_full_evaluation_budget": 1,
    "time_limit_seconds": 60.0,
    "relative_gap": 0.0005,
}


def _digest_json(value) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                     allow_nan=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _business_key(candidate: Candidate) -> tuple:
    result = candidate.business_result
    objective = result.objective
    quality = (1, 0.0) if objective is None else (
        0, -objective if result.sense == "max" else objective)
    return (0 if result.status == FEASIBLE else 1,
            result.violation_count, result.violation_score, *quality)


def _business_from_public(report: dict, extra_errors=()) -> BusinessResult:
    status = str(report.get("business_status", "unknown")).lower()
    mapped = {"pass": FEASIBLE, "fail": INFEASIBLE}.get(status, UNKNOWN)
    violations = report.get("violations") or []
    keys = [str(row["key"]) for row in violations]
    objective = report.get("objective") if mapped != UNKNOWN else None
    return BusinessResult(
        status=mapped,
        objective=objective,
        sense="max",
        violation_count=len(violations),
        violation_score=float(len(violations)),
        hard_errors=frozenset(keys).union(str(error) for error in extra_errors),
    )


def make_initial(artifact: DecisionArtifact, repair: FederatedNeighborhoodRepair,
                 candidate_id: str = "root") -> Candidate:
    started = time.perf_counter()
    report = repair.checker.check(artifact.decisions)
    business = _business_from_public(report)
    elapsed = time.perf_counter() - started
    return Candidate.seed(
        {"artifact_sha256": artifact.sha256, "root": True},
        Evaluation(
            {"source": "shared_initial_artifact", "public_status": report["business_status"]},
            business,
            cost=elapsed,
            checkpoint=artifact,
            structure=artifact.sha256,
        ),
        id=candidate_id,
    )


def _spec_signature(spec: NeighborhoodSpec) -> dict:
    return {
        "mode": spec.mode,
        "released_variable_count": len(spec.released_variables),
        "fixed_variable_count": len(spec.fixed_variables),
        "released_variables_sha256": _digest_json(list(spec.released_variables)),
        "violation_keys_sha256": _digest_json(list(spec.violation_keys)),
    }


def _payload(parent: Candidate, operation: str, seed_scope: str,
             spec: NeighborhoodSpec | None = None, unavailable: str | None = None) -> dict:
    payload = {
        "operation": operation,
        "parent_sha256": parent.checkpoint.sha256,
        "seed_scope": seed_scope,
    }
    if spec is not None:
        payload["spec_signature"] = _spec_signature(spec)
    if unavailable is not None:
        payload["unavailable"] = unavailable
    return payload


def _positive_variables(artifact: DecisionArtifact, repair: FederatedNeighborhoodRepair) -> tuple[str, ...]:
    selected = artifact.decisions["selected"]
    return tuple(
        variable_name(*pair) for pair in repair.problem.pair_order
        if selected[pair_key(*pair)] == 1
    )


def _propose(parent: Candidate, repair: FederatedNeighborhoodRepair,
             operation: str, seed_scope: str) -> Mutation:
    started = time.perf_counter()
    artifact = parent.checkpoint
    try:
        if operation == DEFAULT_OPERATION:
            spec = repair.build(artifact)
        else:
            report = repair.checker.check(artifact.decisions)
            mode = DECISION_REPAIR if report["business_status"] != PASS else OBJECTIVE_OPTIMIZATION
            if operation == DIRECT_OPERATION:
                seeds = repair.variable_names
            elif operation == OBJECTIVE_OPERATION:
                seeds = _positive_variables(artifact, repair)
                mode = OBJECTIVE_OPTIMIZATION
            else:
                raise ValueError(f"unsupported operation: {operation}")
            spec = repair.build(
                artifact,
                violations=report["violations"],
                seed_variables=seeds,
                mode=mode,
                objective_sense=repair.checker.ir.objective_sense,
            )
        payload = _payload(parent, operation, seed_scope, spec=spec)
    except EmptyNeighborhoodError:
        payload = _payload(parent, operation, seed_scope, unavailable="empty_neighborhood")
    return Mutation(operation, payload, cost=time.perf_counter() - started)


def make_operators(repair: FederatedNeighborhoodRepair):
    scopes = {
        DEFAULT_OPERATION: "violations_and_one_hop",
        DIRECT_OPERATION: "all_variables",
        OBJECTIVE_OPERATION: "positive_variables_and_one_hop",
    }
    return [
        lambda parent, operation=operation, scope=scopes[operation]: _propose(
            parent, repair, operation, scope)
        for operation in OPERATIONS
    ]


def _seeds(mutation: Mutation, artifact: DecisionArtifact,
           repair: FederatedNeighborhoodRepair):
    scope = mutation.payload["seed_scope"]
    if scope == "violations_and_one_hop":
        return ()
    if scope == "all_variables":
        return repair.variable_names
    if scope == "positive_variables_and_one_hop":
        return _positive_variables(artifact, repair)
    raise ValueError(f"unsupported seed scope: {scope}")


def _solver_summary(outcome: dict) -> dict:
    keys = (
        "status", "solver_status", "solver_version", "solve_seconds", "node_count",
        "released_variable_count", "fixed_variable_count", "scip_objective",
        "primal_bound", "dual_bound", "reason",
    )
    return {key: outcome[key] for key in keys if key in outcome}


def evaluate_mutation(mutation: Mutation, parent: Candidate,
                      repair: FederatedNeighborhoodRepair) -> Evaluation:
    started = time.perf_counter()
    artifact = parent.checkpoint
    if mutation.payload.get("parent_sha256") != artifact.sha256:
        raise ValueError("mutation parent hash does not match the supplied parent")
    if "unavailable" in mutation.payload:
        reason = mutation.payload["unavailable"]
        return Evaluation(
            {"repair_accepted": False, "repair_reason": reason, "solver": {}},
            BusinessResult(UNKNOWN, sense="max", hard_errors={reason}),
            cost=time.perf_counter() - started,
            checkpoint=artifact,
            structure=artifact.sha256,
        )

    raw_outcome = {}
    mode = mutation.payload["spec_signature"]["mode"]
    seeds = _seeds(mutation, artifact, repair)

    def solve(spec):
        if spec.parent_sha256 != mutation.payload["parent_sha256"]:
            raise ValueError("rebuilt neighborhood parent hash mismatch")
        if _spec_signature(spec) != mutation.payload["spec_signature"]:
            raise ValueError("rebuilt neighborhood signature mismatch")
        outcome = repair.solve(spec)
        raw_outcome.update(outcome)
        return outcome

    try:
        result = repair.repair(
            artifact,
            mode=mode,
            seed_variables=seeds,
            solver=solve,
        )
    except Exception as exc:
        reason = f"evaluator_error:{type(exc).__name__}"
        return Evaluation(
            {"repair_accepted": False, "repair_reason": reason,
             "solver": _solver_summary(raw_outcome)},
            BusinessResult(UNKNOWN, sense="max", hard_errors={reason}),
            cost=time.perf_counter() - started,
            checkpoint=artifact,
            structure=artifact.sha256,
        )

    execution = {
        "repair_accepted": result.accepted,
        "repair_reason": result.reason,
        "solve_status": result.solve_status,
        "introduced_violations": list(result.introduced_violations),
        "fixed_violations": list(result.fixed_violations),
        "remaining_violations": list(result.remaining_violations),
        "solver": _solver_summary(raw_outcome),
    }
    if result.candidate is None or result.candidate_report is None:
        business = BusinessResult(
            UNKNOWN, sense="max", hard_errors={f"no_candidate:{result.reason}"})
        selected = artifact
        structure = artifact.sha256
    else:
        selected = result.candidate
        business = _business_from_public(result.candidate_report)
        structure = selected.sha256
        execution["candidate_sha256"] = selected.sha256
        execution["candidate_public_status"] = result.candidate_report["business_status"]
        execution["candidate_public_objective"] = result.candidate_report["objective"]
    return Evaluation(
        execution,
        business,
        cost=time.perf_counter() - started,
        checkpoint=selected,
        structure=structure,
    )


def run_strategies(initial: Candidate, evaluator, operators) -> tuple[dict[str, RepairRun], object]:
    controller = PopulationRepairController(k=3, depth=2, evaluation_budget=6)
    comparison = controller.compare(initial, evaluator, operators, allow_exploration=True)
    direct = PopulationRepairController(k=1, depth=1, evaluation_budget=1).run(
        initial,
        evaluator,
        [operators[OPERATIONS.index(DIRECT_OPERATION)]],
        single_chain=True,
        allow_exploration=True,
    )
    runs = {
        "single_chain": comparison.single_chain,
        "population": comparison.population,
        "direct_full": direct,
    }
    if any(run.initial is not initial for run in runs.values()):
        raise AssertionError("all strategies must share the exact same initial candidate")
    return runs, comparison


def _lost_win(candidate: Candidate, initial: Candidate) -> bool:
    if initial.business_result.status != FEASIBLE or candidate.business_result.status == UNKNOWN:
        return False
    if candidate.business_result.status != FEASIBLE:
        return True
    return _business_key(candidate) > _business_key(initial)


def _candidate_summary(candidate: Candidate, rejection_by_id: dict) -> dict:
    execution = candidate.execution_result
    solver = execution.get("solver", {})
    rejection = rejection_by_id.get(candidate.id)
    return {
        "id": candidate.id,
        "parent_id": candidate.parent_id,
        "parent_sha256": candidate.payload.get("parent_sha256"),
        "operation": candidate.operation,
        "generation": candidate.generation,
        "role": candidate.role,
        "payload_hash": candidate.payload_hash,
        "status": candidate.business_result.status,
        "objective": candidate.business_result.objective,
        "violation_count": candidate.business_result.violation_count,
        "proposal_seconds": candidate.proposal_cost,
        "evaluation_seconds": candidate.evaluation_cost,
        "total_seconds": candidate.cost,
        "solver_seconds": solver.get("solve_seconds"),
        "solver_status": solver.get("solver_status"),
        "solver_nodes": solver.get("node_count"),
        "spec_signature": candidate.payload.get("spec_signature"),
        "repair_accepted": execution.get("repair_accepted"),
        "repair_reason": execution.get("repair_reason"),
        "introduced_violation_count": len(execution.get("introduced_violations", [])),
        "fixed_violation_count": len(execution.get("fixed_violations", [])),
        "remaining_violation_count": len(execution.get("remaining_violations", [])),
        "rejection_reasons": list(rejection.reasons) if rejection else [],
        "artifact_sha256": candidate.checkpoint.sha256,
    }


def summarize_run(run: RepairRun) -> dict:
    rejection_by_id = {
        rejection.candidate.id: rejection for rejection in run.rejections
        if rejection.candidate is not None
    }
    duplicates = [rejection for rejection in run.rejections if rejection.candidate is None]
    initial_cost = run.initial.evaluation_cost or 0.0
    total = run.total_cost + initial_cost
    accounted = initial_cost + sum(candidate.cost for candidate in run.candidates[1:])
    accounted += sum(rejection.proposal_cost + rejection.evaluation_cost for rejection in duplicates)
    if not math.isclose(total, accounted, rel_tol=0.0, abs_tol=1e-8):
        raise AssertionError("proposal/evaluation cost accounting does not reconcile")
    if run.best not in run.elites or run.best.business_result.status == UNKNOWN:
        raise AssertionError("best must be a known elite candidate")
    if _business_key(run.best) > _business_key(run.initial):
        raise AssertionError("best regressed beyond the initial artifact")
    by_id = {candidate.id: candidate for candidate in run.candidates}
    for candidate in run.candidates[1:]:
        parent = by_id[candidate.parent_id]
        if candidate.payload.get("parent_sha256") != parent.checkpoint.sha256:
            raise AssertionError("candidate lineage and payload parent hash disagree")
    candidates = [_candidate_summary(candidate, rejection_by_id)
                  for candidate in run.candidates[1:]]
    return {
        "mode": run.mode,
        "initial_sha256": run.initial.checkpoint.sha256,
        "best_candidate_id": run.best.id,
        "best_sha256": run.best.checkpoint.sha256,
        "best_role": run.best.role,
        "best_from_elite": True,
        "best_public": {
            "status": run.best.business_result.status,
            "objective": run.best.business_result.objective,
            "violation_count": run.best.business_result.violation_count,
        },
        "best_not_worse_than_initial": True,
        "unchanged": run.best.checkpoint.raw_bytes == run.initial.checkpoint.raw_bytes,
        "evaluation_budget": 1 if run.mode == "single_chain" and run.initial.id.endswith("direct-full") else None,
        "child_evaluations": run.evaluations,
        "generation_evaluations": list(run.generation_evaluations),
        "stop_reason": run.stop_reason,
        "candidate_count_including_initial": len(run.candidates),
        "evaluated_candidate_count": len(run.candidates) - 1,
        "proposal_count_including_duplicates": run.evaluations + len(duplicates),
        "accepted_count_excluding_initial": len(run.accepted) - 1,
        "elite_count_excluding_initial": len(run.elites) - 1,
        "exploration_count": len(run.exploration),
        "duplicate_rejection_count": len(duplicates),
        "unknown_candidate_count": sum(
            candidate.business_result.status == UNKNOWN for candidate in run.candidates[1:]),
        "lost_win_event_count": sum(
            _lost_win(candidate, run.initial) for candidate in run.candidates[1:]),
        "lost_win_rejection_count": sum(
            "lost_win" in rejection.reasons for rejection in run.rejections),
        "new_hard_error_rejection_count": sum(
            "new_hard_error" in rejection.reasons for rejection in run.rejections),
        "new_violation_candidate_count": sum(
            bool(candidate.execution_result.get("introduced_violations"))
            for candidate in run.candidates[1:]),
        "initial_evaluation_seconds": initial_cost,
        "proposal_seconds": run.proposal_cost,
        "evaluation_seconds": run.evaluation_cost,
        "solver_seconds": sum(
            float(candidate.execution_result.get("solver", {}).get("solve_seconds", 0.0))
            for candidate in run.candidates[1:]),
        "total_search_seconds": total,
        "cost_reconciled": True,
        "official": None,
        "candidates": candidates,
    }


def _public_comparison(population: RepairRun, other: RepairRun) -> dict:
    population_key = _business_key(population.best)
    other_key = _business_key(other.best)
    winner = "population" if population_key < other_key else (
        "other" if other_key < population_key else "tie")
    population_objective = population.best.business_result.objective
    other_objective = other.best.business_result.objective
    delta = None
    if population_objective is not None and other_objective is not None:
        delta = population_objective - other_objective
    return {"winner": winner, "objective_delta_population_minus_other": delta}


def _official_comparison(population: dict | None, other: dict | None) -> dict:
    if population is None or other is None:
        return {"gain": "not_evaluated", "objective_delta_population_minus_other": None}
    if population.get("evaluation_unknown") or other.get("evaluation_unknown"):
        return {"gain": "unknown", "objective_delta_population_minus_other": None}
    for field in ("true_correct", "feasible"):
        if population[field] != other[field]:
            return {
                "gain": "positive" if population[field] else "negative",
                "objective_delta_population_minus_other": None,
                "basis": field,
            }
    population_objective = population.get("objective")
    other_objective = other.get("objective")
    delta = None
    if population_objective is not None and other_objective is not None:
        delta = float(population_objective) - float(other_objective)
        tolerance = 1e-9 * max(1.0, abs(delta), abs(float(population_objective)),
                               abs(float(other_objective)))
        gain = "positive" if delta > tolerance else "negative" if delta < -tolerance else "tie"
    else:
        quality_delta = float(population["quality"]) - float(other["quality"])
        gain = "positive" if quality_delta > 0 else "negative" if quality_delta < 0 else "tie"
    return {
        "gain": gain,
        "objective_delta_population_minus_other": delta,
        "basis": "official_objective_maximize",
    }


def _save_final_best(out: Path, scenario: str, runs: dict[str, RepairRun]) -> None:
    for strategy, run in runs.items():
        path = out / "final" / scenario / strategy / "solution.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(run.best.checkpoint.raw_bytes)


def _generate_case(label: str, artifact: DecisionArtifact,
                   repair: FederatedNeighborhoodRepair, out: Path,
                   require_all_operations: bool) -> dict:
    initial = make_initial(artifact, repair)
    operators = make_operators(repair)
    evaluator = lambda mutation, parent: evaluate_mutation(mutation, parent, repair)
    runs, comparison = run_strategies(initial, evaluator, operators)
    if runs["single_chain"].evaluations > 6 or runs["population"].evaluations > 6:
        raise AssertionError("single-chain or population exceeded the six-evaluation budget")
    if runs["direct_full"].evaluations != 1:
        raise AssertionError("direct-full baseline must perform exactly one evaluation")
    if require_all_operations:
        for strategy in ("single_chain", "population"):
            for operation in OPERATIONS:
                if not any(
                    candidate.operation == operation
                    and candidate.execution_result.get("solver", {}).get("solve_seconds") is not None
                    for candidate in runs[strategy].candidates[1:]
                ):
                    raise RuntimeError(f"{label}/{strategy} did not really solve {operation}")
    for candidate in runs["direct_full"].candidates[1:]:
        signature = candidate.payload.get("spec_signature") or {}
        if signature.get("released_variable_count") != len(repair.variable_names):
            raise AssertionError("direct-full did not release every variable")
    _save_final_best(out, label, runs)
    arms = {strategy: summarize_run(run) for strategy, run in runs.items()}
    for arm in arms.values():
        arm["evaluation_budget"] = 1 if arm is arms["direct_full"] else 6
        arm["allow_exploration"] = True
    return {
        "scenario": label,
        "initial_sha256": artifact.sha256,
        "initial_public": {
            "status": initial.business_result.status,
            "objective": initial.business_result.objective,
            "violation_count": initial.business_result.violation_count,
        },
        "arms_share_exact_initial_candidate": True,
        "arms": arms,
        "public_comparisons": {
            "population_vs_single_chain": {
                "winner": comparison.winner,
                "objective_delta_population_minus_single": comparison.population_advantage,
            },
            "population_vs_direct_full": _public_comparison(
                runs["population"], runs["direct_full"]),
        },
        "official_comparisons": {},
    }


def generate_audit(out: Path) -> dict:
    public_files = load_public_files()
    problem = load_public_problem(public_files)
    clean = solution_file_to_artifact(CLEAN_PATH, public_files)
    repair = FederatedNeighborhoodRepair(
        public_files,
        time_limit_seconds=SEARCH_SETTINGS["time_limit_seconds"],
        relative_gap=SEARCH_SETTINGS["relative_gap"],
    )
    scenarios = {}
    for label, builder in SCENARIO_BUILDERS.items():
        artifact = builder(clean, problem, public_files)
        present = {row["requirement_id"]
                   for row in repair.checker.check(artifact.decisions)["violations"]}
        if not EXPECTED_VIOLATIONS[label].issubset(present):
            raise ValueError(f"{label} lacks expected violations: {sorted(present)}")
        scenarios[label] = artifact
    rows = [
        _generate_case(label, artifact, repair, out, require_all_operations=True)
        for label, artifact in scenarios.items()
    ]
    clean_row = _generate_case("clean_control", clean, repair, out,
                               require_all_operations=False)
    try:
        solver_version = importlib.metadata.version("pyscipopt")
    except importlib.metadata.PackageNotFoundError:
        solver_version = None
    return {
        "schema_version": "federated_population_audit_v0.1",
        "settings": dict(SEARCH_SETTINGS),
        "operations": list(OPERATIONS),
        "strategies": list(STRATEGIES),
        "direct_full_protocol": "one full-variable reoptimization from the shared initial artifact",
        "candidate_count_protocol": "candidate_count_including_initial includes the unevaluated-budget root",
        "cost_protocol": (
            "total_search_seconds includes initial public checking, every mutation proposal, "
            "every candidate evaluation, solver time, and duplicate proposal costs; official final scoring is separate"
        ),
        "llm_calls": 0,
        "official_feedback_used_for_candidate_selection": False,
        "selection_complete": True,
        "official_complete": False,
        "common_clean_sha256": clean.sha256,
        "common_clean_public_objective": repair.checker.check(clean.decisions)["objective"],
        "generation_runtime": {
            "python_version": platform.python_version(),
            "pyscipopt_version": solver_version,
        },
        "scenarios": rows,
        "clean_control": clean_row,
        "summary": {},
    }


def _official_cases(audit: dict):
    for row in audit["scenarios"]:
        yield row, False
    yield audit["clean_control"], True


def official_stage(packet: TaskPacket, audit: dict, out: Path) -> dict:
    if not audit.get("selection_complete") or audit.get("official_feedback_used_for_candidate_selection"):
        raise ValueError("official scoring requires a completed, feedback-free selection stage")
    for row, _ in _official_cases(audit):
        label = row["scenario"]
        for strategy in STRATEGIES:
            arm = row["arms"][strategy]
            final_path = out / "final" / label / strategy / "solution.csv"
            raw = final_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != arm["best_sha256"]:
                raise ValueError(f"final artifact hash changed for {label}/{strategy}")
            official_dir = out / "official" / f"{label}__{strategy}__{uuid.uuid4().hex[:10]}"
            workspace = official_dir / "app"
            prepare_workspace(packet, workspace, {
                "model_md": "offline same-root population repair audit",
                "solve_py": "# decision-only final evaluation; no solver is invoked\n",
                "solve_log_md": "offline same-root population repair audit",
            }, validate=False)
            (workspace / "submissions/solution.csv").write_bytes(raw)
            official = official_evaluate(packet, workspace, official_dir / "result")
            metrics = official_metrics(official)
            arm["official"] = {
                **metrics,
                "candidate_sha256": arm["best_sha256"],
                "runner_return_code": official.get("runner", {}).get("return_code"),
                "runner_timed_out": official.get("runner", {}).get("timed_out"),
                "runner_wall_seconds": official.get("runner", {}).get("wall_seconds"),
                "output_dir": str((official_dir / "result").relative_to(out)),
            }
    for row in audit["scenarios"]:
        arms = row["arms"]
        row["official_comparisons"] = {
            "population_vs_single_chain": _official_comparison(
                arms["population"]["official"], arms["single_chain"]["official"]),
            "population_vs_direct_full": _official_comparison(
                arms["population"]["official"], arms["direct_full"]["official"]),
        }
    gains = [row["official_comparisons"]["population_vs_single_chain"]["gain"]
             for row in audit["scenarios"]]
    positive = gains.count("positive")
    negative = gains.count("negative")
    ties = gains.count("tie")
    verdict = "mixed" if positive and negative else (
        "positive" if positive else "negative" if negative else "tie" if ties == len(gains) else "incomplete")
    audit["official_complete"] = True
    audit["summary"] = {
        "basis": "posthoc_official_population_vs_single_chain",
        "population_vs_single_chain_gain": verdict,
        "positive_scenarios": positive,
        "negative_scenarios": negative,
        "tie_scenarios": ties,
        "official_true_correct_by_strategy": {
            strategy: sum(
                row["arms"][strategy]["official"]["true_correct"] is True
                for row in audit["scenarios"])
            for strategy in STRATEGIES
        },
        "note": "Official results are post-hoc final-best measurements and never fed back into candidate selection.",
    }
    return audit


def _number(value, digits=6) -> str:
    if value is None:
        return "NA"
    return f"{float(value):.{digits}f}"


def _official_value(arm: dict, key: str) -> str:
    official = arm.get("official")
    return "not_run" if official is None else str(official.get(key))


def render_report(audit: dict) -> str:
    settings = audit["settings"]
    lines = [
        "# Federated same-root population audit",
        "",
        (f"Population: k={settings['k']}, depth={settings['depth']}, "
         f"evaluation_budget={settings['evaluation_budget']}, allow_exploration=True. "
         "Single-chain uses the same six-evaluation cap and operators. "
         "Direct-full is one full-variable reoptimization from the identical root."),
        "",
        ("All proposals carry the parent artifact hash and a neighborhood signature. "
         "Candidates use the real public checker and PySCIPOpt sub-MILPs. "
         "Official evaluation is run only after all final elite-best artifacts are frozen; "
         "official results never enter candidate selection."),
        "",
        ("Search cost includes root checking, all proposals (including duplicates), all candidate checks, "
         "and solver time. Candidate counts include the root; evaluated counts exclude it. "
         "Official wall time is stored separately in audit.json."),
        "",
        "| Scenario | Strategy | Official true | Official feasible | Official quality | Official objective | Total search s | Solver s | Candidates (evaluated) | Exploration | Lost-win events | New-hard-error rejections |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in audit["scenarios"]:
        for strategy in STRATEGIES:
            arm = row["arms"][strategy]
            lines.append(
                f"| {row['scenario']} | {strategy} | {_official_value(arm, 'true_correct')} | "
                f"{_official_value(arm, 'feasible')} | {_official_value(arm, 'quality')} | "
                f"{_official_value(arm, 'objective')} | {_number(arm['total_search_seconds'])} | "
                f"{_number(arm['solver_seconds'])} | {arm['candidate_count_including_initial']} "
                f"({arm['evaluated_candidate_count']}) | {arm['exploration_count']} | "
                f"{arm['lost_win_event_count']} | {arm['new_hard_error_rejection_count']} |"
            )
    scenario_arms = [arm for row in audit["scenarios"] for arm in row["arms"].values()]
    unknown_count = sum(arm["unknown_candidate_count"] for arm in scenario_arms)
    new_violation_count = sum(arm["new_violation_candidate_count"] for arm in scenario_arms)
    lost_win_count = sum(arm["lost_win_event_count"] for arm in scenario_arms)
    lines.extend([
        "",
        (f"Guard totals: {unknown_count} UNKNOWN candidates (all rejected), "
         f"{new_violation_count} candidates with introduced public violations, and "
         f"{lost_win_count} lost-win events. New-hard-error rejections also include "
         "UNKNOWN/no-candidate errors; the separate introduced-violation count avoids conflating them."),
        "",
        "## Population comparisons",
        "",
        "Objective deltas are population minus comparator; the objective is maximized.",
        "",
        "| Scenario | Public population vs single | Public Δ objective | Official gain vs single | Official Δ objective | Official gain vs direct-full |",
        "|---|---|---:|---|---:|---|",
    ])
    for row in audit["scenarios"]:
        public = row["public_comparisons"]["population_vs_single_chain"]
        official = row["official_comparisons"].get("population_vs_single_chain", {})
        direct = row["official_comparisons"].get("population_vs_direct_full", {})
        lines.append(
            f"| {row['scenario']} | {public['winner']} | "
            f"{_number(public['objective_delta_population_minus_single'])} | "
            f"{official.get('gain', 'not_evaluated')} | "
            f"{_number(official.get('objective_delta_population_minus_other'))} | "
            f"{direct.get('gain', 'not_evaluated')} |"
        )
    summary = audit.get("summary") or {}
    lines.extend([
        "",
        f"Overall post-hoc official population-vs-single verdict: **{summary.get('population_vs_single_chain_gain', 'not_evaluated')}**.",
        "",
        "## Clean control",
        "",
        "| Strategy | Unchanged | Not worse than root | Best from elite | Public status | Public objective | Official true | Official feasible |",
        "|---|---|---|---|---|---:|---|---|",
    ])
    for strategy in STRATEGIES:
        arm = audit["clean_control"]["arms"][strategy]
        lines.append(
            f"| {strategy} | {arm['unchanged']} | {arm['best_not_worse_than_initial']} | "
            f"{arm['best_from_elite']} | {arm['best_public']['status']} | "
            f"{_number(arm['best_public']['objective'])} | {_official_value(arm, 'true_correct')} | "
            f"{_official_value(arm, 'feasible')} |"
        )
    lines.extend([
        "",
        (f"Common clean root: `{audit['common_clean_sha256']}`. "
         "Each scenario builds its corrupted root once from this clean artifact and reuses that exact root "
         "for all three strategies. Public checks are not official business truth; no global-optimality claim is made."),
        "",
    ])
    return "\n".join(lines)


def _write_outputs(out: Path, audit: dict) -> None:
    write_json(out / "audit.json", audit)
    (out / "report.md").write_text(render_report(audit), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="work/federated_population_audit_v0.1")
    phase = parser.add_mutually_exclusive_group()
    phase.add_argument("--skip-official", action="store_true")
    phase.add_argument("--official-only", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.official_only:
        audit = json.loads((out / "audit.json").read_text(encoding="utf-8"))
    else:
        audit = generate_audit(out)
        _write_outputs(out, audit)
    if not args.skip_official:
        packet = TaskPacket.load(
            ROOT / "ORAgentBench/harbor_tasks/federated_learning_cohort_selection",
            "logistics", "transfer",
        )
        audit = official_stage(packet, audit, out)
        _write_outputs(out, audit)
    print(json.dumps({
        "out": str(out),
        "selection_complete": audit["selection_complete"],
        "official_complete": audit["official_complete"],
        "summary": audit.get("summary", {}),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
