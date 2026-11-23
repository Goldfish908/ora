#!/usr/bin/env python3
"""Three-scenario, five-arm GEPA discrimination experiment for federated repair."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import platform
import random
import subprocess
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ora_agent.declarative_neighborhood import DecisionArtifact
from ora_agent.federated_neighborhood import FederatedNeighborhoodRepair
from ora_agent.federated_public_ir import (
    load_public_files,
    load_public_problem,
    pair_key,
    solution_file_to_artifact,
    split_variable_name,
    variable_name,
)
from ora_agent.gepa_repair import (
    DIRECT_FULL_REOPTIMIZATION,
    FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION,
    SYSTEM_AWARE_MERGE,
    RepairCandidate,
    native_per_key_winners,
    non_dominated_archive,
    pareto_elite_candidates,
    propose_system_aware_merge,
    select_pareto_parents,
)
from ora_agent.oragentbench import (
    TaskPacket,
    official_evaluate,
    official_metrics,
    prepare_workspace,
    write_json,
)
from ora_agent.population_repair import (
    ELITE,
    EXPLORATION,
    FEASIBLE,
    REJECTED,
    UNKNOWN,
    Candidate,
    Evaluation,
    Mutation,
    PopulationRepairController,
    RepairRun,
    payload_digest,
)
from scripts.federated_population_audit import (
    DIRECT_OPERATION,
    OBJECTIVE_OPERATION,
    OPERATIONS,
    _business_from_public,
    _business_key,
    _spec_signature,
    make_initial,
    make_operators,
    run_strategies,
    summarize_run,
)
from scripts.federated_repair_audit import (
    CLEAN_PATH,
    all_budgets,
    duplicate_client,
    stream_minimums,
)

DIRECT_FULL = "direct-full"
SINGLE = "single"
OLD_POPULATION = "old-population"
PARETO_ONLY = "pareto-only"
PARETO_MERGE = "pareto+compatible+merge"
ARMS = (DIRECT_FULL, SINGLE, OLD_POPULATION, PARETO_ONLY, PARETO_MERGE)
NEW_ARMS = (PARETO_ONLY, PARETO_MERGE)
BASELINE_ARMS = {
    DIRECT_FULL: "direct_full",
    SINGLE: "single_chain",
    OLD_POPULATION: "population",
}
SCENARIO_BUILDERS = {
    "duplicate_client": duplicate_client,
    "stream_minimums": stream_minimums,
    "all_budgets": all_budgets,
}
EXPECTED_VIOLATIONS = {
    "duplicate_client": {"client_unique_stream"},
    "stream_minimums": {"stream_client_bounds", "stream_local_examples", "stream_secure_enclave_clients"},
    "all_budgets": {"privacy_budget", "upload_budget", "gpu_minute_budget"},
}
SEED = 20261123
K = 3
DEPTH = 2
EVALUATION_BUDGET = 6
DIRECT_FULL_BUDGET = 1
TIME_LIMIT_SECONDS = 60.0
RELATIVE_GAP = 0.0005
COST_SCALE_SECONDS = TIME_LIMIT_SECONDS
SCORE_KEYS = ("feasibility", "public_objective", "negative_cost")
PRIOR_BASELINE = ROOT / "work/federated_population_audit_v0.1/audit.json"
IMPLEMENTATION_FILES = (
    "ora_agent/declarative_neighborhood.py",
    "ora_agent/population_repair.py",
    "ora_agent/federated_neighborhood.py",
    "ora_agent/federated_public_ir.py",
    "ora_agent/gepa_repair.py",
    "scripts/federated_population_audit.py",
    "scripts/gepa_federated_experiment.py",
)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _public_file_hashes(public_files: Mapping[str, str]) -> dict[str, str]:
    return {name: _sha256_bytes(content.encode("utf-8")) for name, content in sorted(public_files.items())}


def _generic_components(artifact: DecisionArtifact) -> dict[str, Any]:
    return copy.deepcopy(artifact.decisions)


def _generic_artifact_builder(components: Mapping[str, Any], base: DecisionArtifact) -> DecisionArtifact:
    return DecisionArtifact.create(components)


def _federated_components(artifact: DecisionArtifact) -> dict[str, int]:
    return {f"selected.{key}": value for key, value in artifact.decisions["selected"].items()}


@dataclass(frozen=True)
class CandidateBridge:
    objective_scale: float
    checker: Any
    cost_scale: float = COST_SCALE_SECONDS
    components_fn: Callable[[DecisionArtifact], Mapping[str, Any]] = _generic_components
    artifact_builder: Callable[[Mapping[str, Any], DecisionArtifact], DecisionArtifact] = _generic_artifact_builder

    def __post_init__(self) -> None:
        for value in (self.objective_scale, self.cost_scale):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("score scales must be finite positive numbers")

    def scores(self, candidate: Candidate) -> dict[str, float]:
        result = candidate.business_result
        if result.status == UNKNOWN or result.objective is None:
            return {}
        return {
            "feasibility": 1.0 if result.status == FEASIBLE else 0.0,
            "public_objective": float(result.objective) / self.objective_scale,
            "negative_cost": -float(candidate.cost) / self.cost_scale,
        }

    def convert_all(self, candidates: Sequence[Candidate]) -> tuple[RepairCandidate, ...]:
        by_id = {candidate.id: candidate for candidate in candidates}
        if len(by_id) != len(candidates):
            raise ValueError("candidate ids must be unique")
        components = {candidate.id: dict(self.components_fn(candidate.checkpoint)) for candidate in candidates}
        converted = []
        for candidate in candidates:
            parent_ids = tuple(candidate.payload.get("merge_parent_ids", ()))
            if not parent_ids and candidate.parent_id is not None:
                parent_ids = (candidate.parent_id,)
            if any(parent not in by_id for parent in parent_ids):
                raise ValueError("candidate lineage is incomplete")
            reference = by_id[parent_ids[0]] if parent_ids else None
            ancestor_components = components[reference.id] if reference is not None else {}
            changed = frozenset(
                name for name, value in components[candidate.id].items()
                if reference is None and value != value
            ) if reference is None else frozenset(
                name for name, value in components[candidate.id].items()
                if ancestor_components.get(name) != value
            )
            converted.append(RepairCandidate(
                id=candidate.id,
                artifact=candidate.checkpoint,
                components=components[candidate.id],
                parent_ids=parent_ids,
                instance_scores=self.scores(candidate),
                changed_components=changed,
                operation=candidate.operation,
                status=candidate.business_result.status,
                role=candidate.role,
                public_checker=self.checker,
            ))
        return tuple(converted)


def _federated_bridge(initial: Candidate, repair: FederatedNeighborhoodRepair) -> CandidateBridge:
    objective = initial.business_result.objective
    scale = max(1.0, abs(float(objective))) if objective is not None else 1.0

    def build(components: Mapping[str, Any], base: DecisionArtifact) -> DecisionArtifact:
        from ora_agent.federated_public_ir import decisions_to_artifact

        selected = {}
        for name, value in components.items():
            client_id, stream_id = split_variable_name(name)
            selected[pair_key(client_id, stream_id)] = value
        return decisions_to_artifact({"selected": selected}, repair.public_files)

    return CandidateBridge(
        objective_scale=scale,
        checker=repair.checker,
        components_fn=_federated_components,
        artifact_builder=build,
    )


@dataclass(frozen=True)
class MergeAttempt:
    outcome: Any
    seconds: float
    record: dict[str, Any]


@dataclass(frozen=True)
class GepaSearchResult:
    run: RepairRun
    merge_events: tuple[dict[str, Any], ...]
    parent_selections: tuple[dict[str, Any], ...]
    proposals: tuple[dict[str, Any], ...]


def frontier_summary(candidates: Sequence[Candidate], bridge: CandidateBridge) -> dict[str, Any]:
    converted = bridge.convert_all(candidates)
    native_indices = native_per_key_winners(converted)
    native = {
        key: sorted(converted[index].id for index in indices)
        for key, indices in sorted(native_indices.items())
    }
    native_ids = sorted({candidate_id for ids in native.values() for candidate_id in ids})
    elites = pareto_elite_candidates(converted)
    archive = non_dominated_archive(converted)
    return {
        "score_keys": list(SCORE_KEYS),
        "native_per_key_winners": native,
        "native_per_key_winner_count": len(native_ids),
        "native_per_key_winner_ids": native_ids,
        "native_pareto_elite_count": len(elites),
        "native_pareto_elite_ids": [candidate.id for candidate in elites],
        "non_dominated_archive_count": len(archive),
        "non_dominated_archive_ids": [candidate.id for candidate in archive],
        "frontier_semantics": (
            "native_per_key_winners are GEPA per-objective winners over elites; "
            "non_dominated_archive is the full pairwise non-dominated set on identical three-key coverage"
        ),
    }


def operations_for_generation(generation: int, k: int = K) -> tuple[str, ...]:
    return tuple(OPERATIONS[((generation - 1) * k + branch) % len(OPERATIONS)] for branch in range(k))


def select_gepa_parents(
    candidates: Sequence[Candidate],
    exploration: Sequence[Candidate],
    bridge: CandidateBridge,
    *,
    generation: int,
    k: int = K,
    rng: random.Random,
) -> tuple[Candidate, ...]:
    """Replace only old-population parent selection; retain its positional operation schedule."""
    converted = bridge.convert_all(candidates)
    selected = select_pareto_parents(converted, k, rng=rng)
    by_id = {candidate.id: candidate for candidate in candidates}
    elite_pool = [by_id[candidate.id] for candidate in selected]
    if not elite_pool:
        raise ValueError("GEPA selected no elite parents")
    operations = operations_for_generation(generation, k)
    parents: list[Candidate | None] = [None] * k
    direct = sorted(
        (
            candidate for candidate in exploration
            if candidate.operation == DIRECT_FULL_REOPTIMIZATION
            and candidate.business_result.status == FEASIBLE
            and candidate.role == EXPLORATION
        ),
        key=lambda candidate: (candidate.generation, candidate.id),
        reverse=True,
    )
    for branch, operation in enumerate(operations):
        if operation == OBJECTIVE_OPERATION and direct:
            parents[branch] = direct.pop(0)
    for branch in range(k):
        if parents[branch] is None:
            parents[branch] = elite_pool[branch % len(elite_pool)]
    return tuple(parent for parent in parents if parent is not None)


def attempt_compatible_merge(
    candidates: Sequence[Candidate],
    bridge: CandidateBridge,
    *,
    rng: random.Random,
    merged_id: str,
) -> MergeAttempt:
    started = time.perf_counter()
    outcome = propose_system_aware_merge(
        bridge.convert_all(candidates),
        min_validation_overlap=len(SCORE_KEYS),
        artifact_builder=bridge.artifact_builder,
        public_checker=bridge.checker,
        rng=rng,
        merged_id=merged_id,
    )
    elapsed = time.perf_counter() - started
    compatible_reasons = {
        "unknown_or_unscored_ancestor",
        "missing_or_mismatched_public_checker",
        "artifact_builder_failed",
        "duplicate_candidate",
        "duplicate_candidate_id",
        "public_check_failed",
        "public_check_unknown",
        "merged",
    }
    novel_reasons = {"public_check_failed", "public_check_unknown", "merged"}
    compatible = outcome.reason in compatible_reasons
    novel = outcome.reason in novel_reasons
    valid = outcome.reason == "merged" and outcome.accepted
    tested = compatible and novel and valid
    record = {
        "reason": outcome.reason,
        "ancestor_id": outcome.ancestor_id,
        "parent_ids": list(outcome.parent_ids),
        "compatible_observed": compatible,
        "novel_observed": novel,
        "valid_full_public_pass": valid,
        "tested": tested,
        "not_tested": not tested,
        "accepted": False,
        "accepted_role": None,
        "candidate_id": None,
        "fallback_mutation_executed": False,
        "seconds": elapsed,
    }
    return MergeAttempt(outcome, elapsed, record)


def _merge_evaluation(attempt: MergeAttempt, candidate_id: str) -> tuple[Mutation, Evaluation]:
    merged = attempt.outcome.candidate
    if merged is None or attempt.outcome.evaluation is None:
        raise ValueError("a tested merge must contain a candidate and full public evaluation")
    report = dict(attempt.outcome.evaluation.report)
    parent_ids = tuple(attempt.outcome.parent_ids)
    payload = {
        "operation": SYSTEM_AWARE_MERGE,
        "parent_sha256": merged.artifact.sha256,
        "merge_parent_ids": list(parent_ids),
        "merge_ancestor_id": attempt.outcome.ancestor_id,
        "candidate_sha256": merged.artifact.sha256,
    }
    mutation = Mutation(SYSTEM_AWARE_MERGE, payload, cost=0.0)
    execution = {
        "repair_accepted": True,
        "repair_reason": "merged",
        "solver": {},
        "candidate_sha256": merged.artifact.sha256,
        "candidate_public_status": report.get("business_status"),
        "candidate_public_objective": report.get("objective"),
        "merge_parent_ids": list(parent_ids),
        "merge_ancestor_id": attempt.outcome.ancestor_id,
    }
    evaluation = Evaluation(
        execution,
        _business_from_public(report),
        cost=attempt.seconds,
        checkpoint=merged.artifact,
        structure=merged.artifact.sha256,
    )
    return mutation, evaluation


def run_gepa_search(
    initial: Candidate,
    evaluator: Callable[[Mutation, Candidate], Evaluation],
    operators: Sequence[Callable[[Candidate], Mutation]],
    bridge: CandidateBridge,
    *,
    merge_enabled: bool,
    seed: int = SEED,
    k: int = K,
    depth: int = DEPTH,
    evaluation_budget: int = EVALUATION_BUDGET,
) -> GepaSearchResult:
    """Run two-generation population search with optional in-budget merge substitution."""
    controller = PopulationRepairController(k=k, depth=depth, evaluation_budget=evaluation_budget)
    parent_rng = random.Random(seed)
    merge_rng = random.Random(seed)
    accepted = [initial]
    elites = [initial]
    exploration: list[Candidate] = []
    candidates = [initial]
    rejections = []
    seen = {initial.payload_hash}
    active = initial
    evaluations = 0
    proposal_cost = 0.0
    evaluation_cost = 0.0
    generation_evaluations = []
    merge_events: list[dict[str, Any]] = []
    parent_selections: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    stop_reason = "depth_exhausted"

    for generation in range(1, depth + 1):
        if evaluations >= evaluation_budget:
            stop_reason = "budget_exhausted"
            break
        parents = select_gepa_parents(
            candidates, exploration, bridge,
            generation=generation, k=k, rng=parent_rng,
        )
        operations = operations_for_generation(generation, k)
        for branch, parent in enumerate(parents):
            parent_selections.append({
                "event": "parent_selected",
                "generation": generation,
                "branch": branch + 1,
                "parent_id": parent.id,
                "parent_operation": parent.operation,
                "parent_role": parent.role,
                "operation": operations[branch],
            })
        before = evaluations
        for branch in range(k):
            if evaluations >= evaluation_budget:
                stop_reason = "budget_exhausted"
                break
            parent = parents[branch % len(parents)]
            operation = operations[branch]
            candidate_id = f"{initial.id}/g{generation}/c{branch + 1}"
            reserved_direct_objective = (
                parent.role == EXPLORATION
                and parent.operation == DIRECT_FULL_REOPTIMIZATION
                and operation == OBJECTIVE_OPERATION
            )
            attempt: MergeAttempt | None = None
            merge_record: dict[str, Any] | None = None
            if merge_enabled and not reserved_direct_objective:
                attempt = attempt_compatible_merge(
                    candidates, bridge, rng=merge_rng, merged_id=candidate_id,
                )
                merge_record = {
                    "generation": generation,
                    "branch": branch + 1,
                    "replaced_parent_id": parent.id,
                    "replaced_operation": operation,
                    **attempt.record,
                }
                merge_events.append(merge_record)

            if attempt is not None and attempt.outcome.accepted:
                mutation, evaluation = _merge_evaluation(attempt, candidate_id)
                primary_parent_id = attempt.outcome.parent_ids[0]
                primary_parent = next(candidate for candidate in candidates if candidate.id == primary_parent_id)
                mutation.payload["parent_sha256"] = primary_parent.checkpoint.sha256
                proposal_kind = "merge"
            else:
                mutation = operators[((generation - 1) * k + branch) % len(operators)](parent)
                if mutation.operation != operation:
                    raise AssertionError("operator schedule changed under the Pareto arm")
                if attempt is not None:
                    mutation = Mutation(
                        mutation.operation, mutation.payload,
                        cost=mutation.cost + attempt.seconds,
                    )
                primary_parent = parent
                proposal_kind = "mutation"

            proposal_cost += mutation.cost
            digest = payload_digest(mutation.payload)
            if digest in seen:
                from ora_agent.population_repair import Rejection

                rejections.append(Rejection(
                    generation=generation,
                    parent_id=primary_parent.id,
                    operation=mutation.operation,
                    payload_hash=digest,
                    reasons=("duplicate_hash",),
                    proposal_cost=mutation.cost,
                ))
                proposals.append({
                    "generation": generation,
                    "branch": branch + 1,
                    "parent_id": primary_parent.id,
                    "operation": mutation.operation,
                    "kind": proposal_kind,
                    "outcome": "duplicate_hash",
                    "solver_called": False,
                })
                if merge_record is not None:
                    merge_record["fallback_mutation_executed"] = False
                    merge_record["fallback_outcome"] = "duplicate_hash"
                continue
            seen.add(digest)
            if proposal_kind == "mutation":
                evaluation = evaluator(mutation, primary_parent)
            if not isinstance(evaluation, Evaluation):
                raise TypeError("candidate evaluators must return Evaluation")
            evaluation_cost += evaluation.cost
            if evaluation.business_result.sense != initial.business_result.sense:
                raise ValueError("all candidates must use the initial objective sense")
            candidate = Candidate(
                id=candidate_id,
                parent_id=primary_parent.id,
                operation=mutation.operation,
                payload=mutation.payload,
                execution_result=evaluation.execution_result,
                business_result=evaluation.business_result,
                cost=mutation.cost + evaluation.cost,
                checkpoint=evaluation.checkpoint,
                generation=generation,
                structure=evaluation.structure,
                proposal_cost=mutation.cost,
                evaluation_cost=evaluation.cost,
            )
            evaluations += 1
            solver_called = evaluation.execution_result.get("solver", {}).get("solve_seconds") is not None
            proposals.append({
                "generation": generation,
                "branch": branch + 1,
                "parent_id": primary_parent.id,
                "operation": mutation.operation,
                "kind": proposal_kind,
                "outcome": "evaluated",
                "candidate_id": candidate.id,
                "solver_called": solver_called,
            })
            if merge_record is not None:
                merge_record["fallback_mutation_executed"] = proposal_kind == "mutation"
                merge_record["fallback_outcome"] = "evaluated" if proposal_kind == "mutation" else None
                merge_record["candidate_id"] = candidate.id
            incumbent = min(elites, key=_business_key)
            reasons = controller._rejection_reasons(candidate, primary_parent, initial, incumbent)
            explore = bool(reasons) and controller._can_explore(candidate, reasons)
            if reasons and not explore:
                candidate = Candidate(
                    id=candidate.id,
                    parent_id=candidate.parent_id,
                    operation=candidate.operation,
                    payload=candidate.payload,
                    execution_result=candidate.execution_result,
                    business_result=candidate.business_result,
                    cost=candidate.cost,
                    checkpoint=candidate.checkpoint,
                    generation=candidate.generation,
                    structure=candidate.structure,
                    proposal_cost=candidate.proposal_cost,
                    evaluation_cost=candidate.evaluation_cost,
                    role=REJECTED,
                )
                from ora_agent.population_repair import Rejection

                candidates.append(candidate)
                rejections.append(Rejection(
                    generation=generation,
                    parent_id=primary_parent.id,
                    operation=mutation.operation,
                    payload_hash=digest,
                    reasons=reasons,
                    candidate=candidate,
                    proposal_cost=mutation.cost,
                    evaluation_cost=evaluation.cost,
                ))
            else:
                role = EXPLORATION if explore else ELITE
                if role != candidate.role:
                    candidate = Candidate(
                        id=candidate.id,
                        parent_id=candidate.parent_id,
                        operation=candidate.operation,
                        payload=candidate.payload,
                        execution_result=candidate.execution_result,
                        business_result=candidate.business_result,
                        cost=candidate.cost,
                        checkpoint=candidate.checkpoint,
                        generation=candidate.generation,
                        structure=candidate.structure,
                        proposal_cost=candidate.proposal_cost,
                        evaluation_cost=candidate.evaluation_cost,
                        role=role,
                    )
                if explore:
                    exploration.append(candidate)
                else:
                    elites.append(candidate)
                candidates.append(candidate)
                accepted.append(candidate)
                active = candidate
                if merge_record is not None and proposal_kind == "merge":
                    merge_record["accepted"] = True
                    merge_record["accepted_role"] = role
        generation_evaluations.append(evaluations - before)
        if evaluations == before:
            stop_reason = "no_new_evaluations"
            break
        if evaluations >= evaluation_budget:
            stop_reason = "budget_exhausted"
            break
    else:
        stop_reason = "depth_exhausted"

    best = min(elites, key=_business_key)
    elite_population = controller.select_parents(elites, k)
    population = controller.select_parents(elites, k, exploration)
    run = RepairRun(
        mode=PARETO_MERGE if merge_enabled else PARETO_ONLY,
        initial=initial,
        best=best,
        population=population,
        elite_population=elite_population,
        candidates=tuple(candidates),
        accepted=tuple(accepted),
        elites=tuple(elites),
        exploration=tuple(exploration),
        rejections=tuple(rejections),
        evaluations=evaluations,
        proposal_cost=proposal_cost,
        evaluation_cost=evaluation_cost,
        total_cost=proposal_cost + evaluation_cost,
        generation_evaluations=tuple(generation_evaluations),
        stop_reason=stop_reason,
    )
    return GepaSearchResult(run, tuple(merge_events), tuple(parent_selections), tuple(proposals))


def direct_path_events(run: RepairRun) -> list[dict[str, Any]]:
    events = []
    direct_exploration = {}
    for candidate in run.candidates[1:]:
        if candidate.operation == DIRECT_OPERATION and candidate.business_result.status == FEASIBLE:
            events.append({
                "event": "direct_exploration_generated",
                "candidate_id": candidate.id,
                "generation": candidate.generation,
                "artifact_sha256": candidate.checkpoint.sha256,
            })
            if candidate.role == EXPLORATION:
                direct_exploration[candidate.id] = candidate
                events.append({
                    "event": "direct_exploration_accepted",
                    "candidate_id": candidate.id,
                    "generation": candidate.generation,
                    "role": candidate.role,
                })
    for candidate in run.candidates[1:]:
        if candidate.operation != OBJECTIVE_OPERATION or candidate.parent_id not in direct_exploration:
            continue
        solver_called = candidate.execution_result.get("solver", {}).get("solve_seconds") is not None
        events.append({
            "event": "parent_selected",
            "candidate_id": candidate.parent_id,
            "child_id": candidate.id,
            "generation": candidate.generation,
            "operation": candidate.operation,
        })
        events.append({
            "event": "objective_operation_executed",
            "candidate_id": candidate.parent_id,
            "child_id": candidate.id,
            "generation": candidate.generation,
            "operation": candidate.operation,
            "solver_called": solver_called,
            "solver_status": candidate.execution_result.get("solver", {}).get("solver_status"),
        })
    return events


def direct_path_coverage(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    generated = {event["candidate_id"] for event in events if event["event"] == "direct_exploration_generated"}
    accepted = {event["candidate_id"] for event in events if event["event"] == "direct_exploration_accepted"}
    selected = {event["candidate_id"] for event in events if event["event"] == "parent_selected"}
    executed = {
        event["candidate_id"] for event in events
        if event["event"] == "objective_operation_executed" and event.get("solver_called")
    }
    covered = sorted(generated & accepted & selected & executed)
    return {
        "generated_count": len(generated),
        "accepted_count": len(accepted),
        "selected_count": len(selected),
        "executed_count": len(executed),
        "covered_direct_candidate_ids": covered,
        "mechanism_success": bool(covered),
        "success_meaning": "the full generate/accept/select/execute path occurred; it is not a claim of objective improvement",
    }


def merge_summary(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    tested = sum(bool(event["tested"]) for event in events)
    return {
        "attempted": len(events),
        "compatible": sum(bool(event["compatible_observed"]) for event in events),
        "novel": sum(bool(event["novel_observed"]) for event in events),
        "valid": sum(bool(event["valid_full_public_pass"]) for event in events),
        "tested": tested,
        "accepted": sum(bool(event["accepted"]) for event in events),
        "not_tested": len(events) - tested,
        "invalid": 0,
        "not_tested_reasons": dict(Counter(
            str(event["reason"]) for event in events if not event["tested"]
        )),
        "events": copy.deepcopy(list(events)),
        "tested_definition": "compatible + novel + complete public PASS; every other attempt is not_tested, not invalid",
    }


def _cost_ledger(run: RepairRun) -> list[dict[str, Any]]:
    ledger = [{
        "kind": "shared_root_public_check",
        "candidate_id": run.initial.id,
        "proposal_seconds": 0.0,
        "evaluation_seconds": run.initial.evaluation_cost,
        "total_seconds": run.initial.evaluation_cost,
    }]
    for candidate in run.candidates[1:]:
        ledger.append({
            "kind": "evaluated_child",
            "candidate_id": candidate.id,
            "operation": candidate.operation,
            "proposal_seconds": candidate.proposal_cost,
            "evaluation_seconds": candidate.evaluation_cost,
            "total_seconds": candidate.cost,
        })
    for rejection in run.rejections:
        if rejection.candidate is None:
            ledger.append({
                "kind": "duplicate_proposal",
                "parent_id": rejection.parent_id,
                "operation": rejection.operation,
                "payload_hash": rejection.payload_hash,
                "proposal_seconds": rejection.proposal_cost,
                "evaluation_seconds": rejection.evaluation_cost,
                "total_seconds": rejection.proposal_cost + rejection.evaluation_cost,
            })
    return ledger


def summarize_search(
    value: RepairRun | GepaSearchResult,
    bridge: CandidateBridge,
    arm: str,
) -> dict[str, Any]:
    result = value if isinstance(value, GepaSearchResult) else None
    run = result.run if result is not None else value
    summary = summarize_run(run)
    events = merge_summary(result.merge_events if result is not None else ())
    path_events = direct_path_events(run)
    summary.update({
        "arm": arm,
        "evaluation_budget": DIRECT_FULL_BUDGET if arm == DIRECT_FULL else EVALUATION_BUDGET,
        "solver_call_count": sum(
            candidate.execution_result.get("solver", {}).get("solve_seconds") is not None
            for candidate in run.candidates[1:]
        ),
        "frontiers": frontier_summary(run.candidates, bridge),
        "merge": events,
        "direct_path_events": path_events,
        "direct_path_coverage": direct_path_coverage(path_events),
        "parent_selections": list(result.parent_selections) if result is not None else [],
        "proposal_trace": list(result.proposals) if result is not None else [],
        "cost_ledger": _cost_ledger(run),
        "official_wall_seconds": None,
        "total_cost_seconds_including_official": None,
        "expansion_stopped": True,
        "expansion_stop_reason": run.stop_reason,
        "official": None,
    })
    ledger_total = sum(float(entry["total_seconds"]) for entry in summary["cost_ledger"])
    if not math.isclose(ledger_total, summary["total_search_seconds"], rel_tol=0.0, abs_tol=1e-8):
        raise AssertionError("independent arm cost ledger does not reconcile")
    summary["cost_ledger_reconciled"] = True
    for candidate in summary["candidates"]:
        original = next(item for item in run.candidates if item.id == candidate["id"])
        if original.payload.get("merge_parent_ids"):
            candidate["merge_parent_ids"] = list(original.payload["merge_parent_ids"])
            candidate["merge_ancestor_id"] = original.payload.get("merge_ancestor_id")
    return summary


def _verify_prior_baseline(
    path: Path,
    roots: Mapping[str, DecisionArtifact],
    clean: DecisionArtifact,
    public_files: Mapping[str, str],
) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "present": False, "used_for_results": False}
    audit = json.loads(path.read_text(encoding="utf-8"))
    if audit.get("schema_version") != "federated_population_audit_v0.1":
        raise ValueError("unexpected prior baseline schema")
    if audit.get("common_clean_sha256") != clean.sha256:
        raise ValueError("prior baseline clean hash mismatch")
    baseline_root = path.parent
    current_public = _public_file_hashes(public_files)
    checks = []
    for scenario, artifact in roots.items():
        row = next(item for item in audit["scenarios"] if item["scenario"] == scenario)
        if row["initial_sha256"] != artifact.sha256:
            raise ValueError(f"prior baseline root hash mismatch: {scenario}")
    for row in [*audit["scenarios"], audit["clean_control"]]:
        for strategy, arm in row["arms"].items():
            final_path = baseline_root / "final" / row["scenario"] / strategy / "solution.csv"
            actual = _sha256_file(final_path)
            if actual != arm["best_sha256"]:
                raise ValueError(f"prior baseline final hash mismatch: {row['scenario']}/{strategy}")
            official = arm.get("official")
            if official is not None:
                if official.get("candidate_sha256") != actual:
                    raise ValueError("prior baseline official candidate hash mismatch")
                official_app = baseline_root / official["output_dir"]
                official_app = official_app.parent / "app"
                if _public_file_hashes(load_public_files(official_app)) != current_public:
                    raise ValueError("prior baseline public-file hash mismatch")
            checks.append({
                "scenario": row["scenario"],
                "strategy": strategy,
                "best_sha256": actual,
                "final_hash_verified": True,
                "official_candidate_hash_verified": official is not None,
            })
    return {
        "path": str(path),
        "present": True,
        "used_for_results": False,
        "audit_sha256": _sha256_file(path),
        "selection_complete": audit.get("selection_complete"),
        "official_complete": audit.get("official_complete"),
        "clean_and_scenario_root_hashes_verified": True,
        "public_file_hashes_verified_against_official_workspaces": True,
        "final_artifacts": checks,
        "note": "Prior baseline is hash-audited but all five arms are rerun under one runtime for this experiment.",
    }


def _assert_run_contract(label: str, runs: Mapping[str, RepairRun | GepaSearchResult], variable_count: int) -> None:
    initial = runs[DIRECT_FULL].run.initial if isinstance(runs[DIRECT_FULL], GepaSearchResult) else runs[DIRECT_FULL].initial
    for arm, value in runs.items():
        run = value.run if isinstance(value, GepaSearchResult) else value
        if run.initial is not initial:
            raise AssertionError(f"{label}/{arm} does not share the exact root Candidate")
        if run.evaluations > (DIRECT_FULL_BUDGET if arm == DIRECT_FULL else EVALUATION_BUDGET):
            raise AssertionError(f"{label}/{arm} exceeded its child evaluation budget")
    direct = runs[DIRECT_FULL]
    direct_run = direct.run if isinstance(direct, GepaSearchResult) else direct
    if direct_run.evaluations != 1:
        raise AssertionError(f"{label}/direct-full did not execute exactly once")
    for candidate in direct_run.candidates[1:]:
        signature = candidate.payload.get("spec_signature") or {}
        if signature.get("released_variable_count") != variable_count:
            raise AssertionError(f"{label}/direct-full did not release every variable")


def _generate_case(
    label: str,
    artifact: DecisionArtifact,
    repair: FederatedNeighborhoodRepair,
    out: Path,
) -> dict[str, Any]:
    initial = make_initial(artifact, repair)
    operators = make_operators(repair)
    evaluator = lambda mutation, parent: __import__(
        "scripts.federated_population_audit", fromlist=["evaluate_mutation"]
    ).evaluate_mutation(mutation, parent, repair)
    baseline_runs, _ = run_strategies(initial, evaluator, operators)
    bridge = _federated_bridge(initial, repair)
    pareto = run_gepa_search(initial, evaluator, operators, bridge, merge_enabled=False)
    merge = run_gepa_search(initial, evaluator, operators, bridge, merge_enabled=True)
    runs: dict[str, RepairRun | GepaSearchResult] = {
        DIRECT_FULL: baseline_runs["direct_full"],
        SINGLE: baseline_runs["single_chain"],
        OLD_POPULATION: baseline_runs["population"],
        PARETO_ONLY: pareto,
        PARETO_MERGE: merge,
    }
    _assert_run_contract(label, runs, len(repair.variable_names))
    arms = {arm: summarize_search(value, bridge, arm) for arm, value in runs.items()}
    for arm, value in runs.items():
        run = value.run if isinstance(value, GepaSearchResult) else value
        path = out / "final" / label / arm / "solution.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(run.best.checkpoint.raw_bytes)
        if arms[arm]["solver_call_count"] > arms[arm]["evaluation_budget"]:
            raise AssertionError(f"{label}/{arm} exceeded its solver budget")
    if label == "clean_control":
        for arm, value in runs.items():
            run = value.run if isinstance(value, GepaSearchResult) else value
            if _business_key(run.best) > _business_key(run.initial):
                raise AssertionError("clean control regressed")
    return {
        "scenario": label,
        "initial_sha256": artifact.sha256,
        "initial_public": {
            "status": initial.business_result.status,
            "objective": initial.business_result.objective,
            "violation_count": initial.business_result.violation_count,
        },
        "arms_share_exact_initial_candidate": True,
        "random_seed": SEED,
        "arms": arms,
    }


def _frozen_manifest(rows: Sequence[Mapping[str, Any]], out: Path) -> dict[str, str]:
    manifest = {}
    for row in rows:
        for arm in ARMS:
            path = out / "final" / row["scenario"] / arm / "solution.csv"
            digest = _sha256_file(path)
            if digest != row["arms"][arm]["best_sha256"]:
                raise ValueError("elite-best artifact changed while freezing")
            manifest[f"{row['scenario']}/{arm}"] = digest
    return manifest


def generate_audit(out: Path, prior_baseline: Path = PRIOR_BASELINE) -> dict[str, Any]:
    public_files = load_public_files()
    problem = load_public_problem(public_files)
    clean = solution_file_to_artifact(CLEAN_PATH, public_files)
    repair = FederatedNeighborhoodRepair(
        public_files,
        time_limit_seconds=TIME_LIMIT_SECONDS,
        relative_gap=RELATIVE_GAP,
    )
    roots = {}
    for label, builder in SCENARIO_BUILDERS.items():
        artifact = builder(clean, problem, public_files)
        present = {row["requirement_id"] for row in repair.checker.check(artifact.decisions)["violations"]}
        if not EXPECTED_VIOLATIONS[label].issubset(present):
            raise ValueError(f"{label} lacks expected violations")
        roots[label] = artifact
    prior = _verify_prior_baseline(prior_baseline, roots, clean, public_files)
    rows = [_generate_case(label, artifact, repair, out) for label, artifact in roots.items()]
    clean_row = _generate_case("clean_control", clean, repair, out)
    all_rows = [*rows, clean_row]
    if prior.get("present"):
        prior_audit = json.loads(prior_baseline.read_text(encoding="utf-8"))
        comparisons = []
        for row in all_rows:
            prior_row = next(
                item for item in [*prior_audit["scenarios"], prior_audit["clean_control"]]
                if item["scenario"] == row["scenario"]
            )
            for arm, strategy in BASELINE_ARMS.items():
                comparisons.append({
                    "scenario": row["scenario"],
                    "arm": arm,
                    "prior_best_sha256": prior_row["arms"][strategy]["best_sha256"],
                    "current_best_sha256": row["arms"][arm]["best_sha256"],
                    "matches_prior": row["arms"][arm]["best_sha256"] == prior_row["arms"][strategy]["best_sha256"],
                })
        prior["rerun_best_hash_comparisons"] = comparisons
    try:
        solver_version = importlib.metadata.version("pyscipopt")
    except importlib.metadata.PackageNotFoundError:
        solver_version = None
    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    audit = {
        "schema_version": "gepa_federated_experiment_v0.1",
        "settings": {
            "k": K,
            "depth": DEPTH,
            "evaluation_budget": EVALUATION_BUDGET,
            "direct_full_evaluation_budget": DIRECT_FULL_BUDGET,
            "time_limit_seconds": TIME_LIMIT_SECONDS,
            "relative_gap": RELATIVE_GAP,
            "random_seed": SEED,
            "score_objective_scale": "max(1, abs(shared-root public objective)) per scenario",
            "score_cost_scale_seconds": COST_SCALE_SECONDS,
            "merge_validation_overlap": len(SCORE_KEYS),
        },
        "arms": list(ARMS),
        "scenarios": rows,
        "clean_control": clean_row,
        "common_clean_sha256": clean.sha256,
        "public_file_sha256": _public_file_hashes(public_files),
        "implementation_sha256": {name: _sha256_file(ROOT / name) for name in IMPLEMENTATION_FILES},
        "generation_runtime": {
            "python_version": platform.python_version(),
            "pyscipopt_version": solver_version,
            "git_head": git_head,
            "gepa_src": str(Path(__import__("os").environ.get("GEPA_SRC", "")).resolve()),
            "scip_random_seed_shift": "SCIP library default; identical for every arm",
        },
        "multiobjective_score_protocol": {
            "keys": list(SCORE_KEYS),
            "feasibility": "1 for FEASIBLE, 0 for INFEASIBLE; UNKNOWN is not scored",
            "public_objective": "public maximize objective divided by the fixed shared-root absolute-objective scale",
            "negative_cost": "negative candidate proposal+evaluation seconds divided by 60 seconds",
            "native_vs_archive": "native per-key winners and GEPA-pruned elites are reported separately from the complete non-dominated archive",
        },
        "parent_policy": (
            "pareto-only changes only old-population parent selection/order; the original positional default/direct/objective "
            "mutation schedule and acceptance checks are unchanged. Direct exploration is ordered into an existing objective slot."
        ),
        "merge_policy": (
            "The merge arm alone attempts compatible GEPA merges in non-reserved slots. A tested merge replaces that slot's "
            "mutation and consumes one child evaluation but no solver call. Untested attempts fall back to the original mutation."
        ),
        "cost_protocol": (
            "Each arm has an independent ledger. The shared root check is charged to each arm ledger; proposal, evaluation, "
            "merge, duplicate, and solver-inclusive costs are not shared across arms. Official wall time is added only post-freeze."
        ),
        "expansion_stop_rule": (
            "Predeclared stop at two generations or six child evaluations, whichever comes first; also stop on a generation "
            "with no new evaluation. Direct-full stops after one. No extra solve is allowed to force direct or merge coverage, "
            "and no official result triggers expansion."
        ),
        "prior_baseline": prior,
        "llm_calls": 0,
        "official_feedback_used_for_candidate_selection": False,
        "selection_complete": True,
        "official_complete": False,
        "frozen_final_sha256": _frozen_manifest(all_rows, out),
        "summary": {},
    }
    return audit


def _official_rows(audit: Mapping[str, Any]):
    for row in audit["scenarios"]:
        yield row
    yield audit["clean_control"]


def official_stage(packet: TaskPacket, audit: dict[str, Any], out: Path) -> dict[str, Any]:
    if not audit.get("selection_complete") or audit.get("official_feedback_used_for_candidate_selection"):
        raise ValueError("official scoring requires completed feedback-free selection")
    for row in _official_rows(audit):
        for arm in ARMS:
            key = f"{row['scenario']}/{arm}"
            final_path = out / "final" / row["scenario"] / arm / "solution.csv"
            actual = _sha256_file(final_path)
            if actual != audit["frozen_final_sha256"][key] or actual != row["arms"][arm]["best_sha256"]:
                raise ValueError(f"frozen elite-best changed before official evaluation: {key}")
    for row in _official_rows(audit):
        for arm in ARMS:
            data = row["arms"][arm]
            if data.get("official") is not None:
                continue
            final_path = out / "final" / row["scenario"] / arm / "solution.csv"
            raw = final_path.read_bytes()
            safe_arm = arm.replace("+", "_")
            official_dir = out / "official" / f"{row['scenario']}__{safe_arm}__{uuid.uuid4().hex[:10]}"
            workspace = official_dir / "app"
            prepare_workspace(packet, workspace, {
                "model_md": "offline five-arm GEPA federated experiment",
                "solve_py": "# decision-only final evaluation; no search solver is invoked\n",
                "solve_log_md": "offline five-arm GEPA federated experiment",
            }, validate=False)
            (workspace / "submissions/solution.csv").write_bytes(raw)
            official = official_evaluate(packet, workspace, official_dir / "result")
            metrics = official_metrics(official)
            data["official"] = {
                **metrics,
                "candidate_sha256": _sha256_bytes(raw),
                "runner_return_code": official.get("runner", {}).get("return_code"),
                "runner_timed_out": official.get("runner", {}).get("timed_out"),
                "runner_wall_seconds": official.get("runner", {}).get("wall_seconds"),
                "output_dir": str((official_dir / "result").relative_to(out)),
            }
            data["official_wall_seconds"] = data["official"]["runner_wall_seconds"]
            data["total_cost_seconds_including_official"] = (
                data["total_search_seconds"] + float(data["official_wall_seconds"] or 0.0)
            )
            write_json(out / "audit.json", audit)
    audit["official_complete"] = True
    audit["summary"] = {
        "official_true_correct_by_arm": {
            arm: sum(row["arms"][arm]["official"]["true_correct"] is True for row in audit["scenarios"])
            for arm in ARMS
        },
        "direct_path_success_by_scenario_and_arm": {
            f"{row['scenario']}/{arm}": row["arms"][arm]["direct_path_coverage"]["mechanism_success"]
            for row in audit["scenarios"] for arm in ARMS
        },
        "merge_tested_by_scenario": {
            row["scenario"]: row["arms"][PARETO_MERGE]["merge"]["tested"]
            for row in audit["scenarios"]
        },
        "note": "Official measurements are strictly post-freeze and were never used for parent selection or expansion.",
    }
    return audit


def _number(value: Any, digits: int = 6) -> str:
    if value is None:
        return "NA"
    return f"{float(value):.{digits}f}"


def _official_value(arm: Mapping[str, Any], key: str) -> str:
    official = arm.get("official")
    return "not_run" if official is None else str(official.get(key))


def render_report(audit: Mapping[str, Any]) -> str:
    settings = audit["settings"]
    lines = [
        "# 三场景五臂 GEPA 联邦修复判别实验",
        "",
        (f"五臂均使用同一 root Candidate、公开文件和评价器。搜索臂最多 {settings['evaluation_budget']} 次 child evaluation，"
         f"direct-full 恰好 1 次；population 为 k={settings['k']}、depth={settings['depth']}，随机种子 {settings['random_seed']}。"
         "merge 替换槽位 mutation，不占额外槽位或求解预算。所有臂在本次运行中真实执行；旧 baseline 仅做哈希交叉核验。"),
        "",
        ("多目标 score 为 feasibility、归一化 public objective、归一化负成本。`native_per_key_winners`、GEPA 剪枝后的 "
         "native elites 与完整 `non_dominated_archive` 分别报告。完整审计保留未舍入数值和逐条成本 ledger。"),
        "",
        ("所有 final elite-best 先冻结并核验 SHA256，再进行官方复评；官方结果不进入选父、接受或扩展决策。"
         "总成本 = 独立搜索 ledger + 最终官方 runner wall time，solver 时间已含在 evaluation 中，不重复相加。"),
        "",
        "| Scenario | Arm | Official true | Official quality | Official objective | Search s | Official s | Total s | Child eval | Solver calls | Native winners | Native elites | Full non-dominated |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in audit["scenarios"]:
        for arm_name in ARMS:
            arm = row["arms"][arm_name]
            frontiers = arm["frontiers"]
            lines.append(
                f"| {row['scenario']} | {arm_name} | {_official_value(arm, 'true_correct')} | "
                f"{_official_value(arm, 'quality')} | {_official_value(arm, 'objective')} | "
                f"{_number(arm['total_search_seconds'])} | {_number(arm['official_wall_seconds'])} | "
                f"{_number(arm['total_cost_seconds_including_official'])} | {arm['child_evaluations']} | "
                f"{arm['solver_call_count']} | {frontiers['native_per_key_winner_count']} | "
                f"{frontiers['native_pareto_elite_count']} | {frontiers['non_dominated_archive_count']} |"
            )
    lines.extend([
        "",
        "## 关键路径与 merge 判别",
        "",
        ("direct 路径成功只表示同一 direct-full exploration 完成生成、以 exploration 接受、选为 "
         "feasible-parent-objective 父代并真实执行求解，不表示目标值提升。merge 只有真实兼容、非重复且完整公开检查 PASS "
         "才计 tested；其余全部计 not_tested，不计 invalid。"),
        "",
        "| Scenario | Arm | Direct generated | Accepted | Selected | Executed | Path success | Merge attempted | Compatible | Novel | Valid | Tested | Accepted | Not tested | Stop |",
        "|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ])
    for row in audit["scenarios"]:
        for arm_name in ARMS:
            arm = row["arms"][arm_name]
            path = arm["direct_path_coverage"]
            merge = arm["merge"]
            lines.append(
                f"| {row['scenario']} | {arm_name} | {path['generated_count']} | {path['accepted_count']} | "
                f"{path['selected_count']} | {path['executed_count']} | {path['mechanism_success']} | "
                f"{merge['attempted']} | {merge['compatible']} | {merge['novel']} | {merge['valid']} | "
                f"{merge['tested']} | {merge['accepted']} | {merge['not_tested']} | {arm['stop_reason']} |"
            )
    lines.extend([
        "",
        "## 官方目标差分（最大化，正数表示前者更好）",
        "",
        "| Scenario | Pareto-only − old-population | Merge − Pareto-only | Merge − old-population |",
        "|---|---:|---:|---:|",
    ])
    for row in audit["scenarios"]:
        values = []
        for left, right in ((PARETO_ONLY, OLD_POPULATION), (PARETO_MERGE, PARETO_ONLY), (PARETO_MERGE, OLD_POPULATION)):
            left_official = row["arms"][left].get("official")
            right_official = row["arms"][right].get("official")
            delta = None
            if left_official and right_official and left_official.get("objective") is not None and right_official.get("objective") is not None:
                delta = float(left_official["objective"]) - float(right_official["objective"])
            values.append(_number(delta))
        lines.append(f"| {row['scenario']} | {values[0]} | {values[1]} | {values[2]} |")
    lines.extend([
        "",
        "## Clean control",
        "",
        "| Arm | Not worse than root | Public status | Public objective | Official true | Official quality | Official objective |",
        "|---|---|---|---:|---|---:|---:|",
    ])
    for arm_name in ARMS:
        arm = audit["clean_control"]["arms"][arm_name]
        lines.append(
            f"| {arm_name} | {arm['best_not_worse_than_initial']} | {arm['best_public']['status']} | "
            f"{_number(arm['best_public']['objective'])} | {_official_value(arm, 'true_correct')} | "
            f"{_official_value(arm, 'quality')} | {_official_value(arm, 'objective')} |"
        )
    prior = audit.get("prior_baseline", {})
    lines.extend([
        "",
        "## 扩展停止与 baseline 核验",
        "",
        audit["expansion_stop_rule"],
        "",
        (f"本轮已按预声明规则停止，未因官方正负结果追加实验。旧 audit SHA256：`{prior.get('audit_sha256', 'NA')}`；"
         f"root/final/public-file hash checks=`{prior.get('clean_and_scenario_root_hashes_verified', False)}/"
         f"{all(item.get('final_hash_verified') for item in prior.get('final_artifacts', []))}/"
         f"{prior.get('public_file_hashes_verified_against_official_workspaces', False)}`。"
         "baseline 的搜索结果未复用，因此不存在旧运行时或旧官方评价混入新搜索。"),
        "",
    ])
    return "\n".join(lines)


def _write_outputs(out: Path, audit: Mapping[str, Any]) -> None:
    write_json(out / "audit.json", audit)
    (out / "report.md").write_text(render_report(audit), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="work/gepa_federated_experiment_v0.1")
    parser.add_argument("--prior-baseline", default=str(PRIOR_BASELINE))
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
        audit = generate_audit(out, Path(args.prior_baseline).resolve())
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
