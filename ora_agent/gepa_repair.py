"""GEPA-backed parent selection and checked merges for decision repair."""

from __future__ import annotations

import copy
import math
import os
import random
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

from .declarative_neighborhood import DecisionArtifact
from .population_repair import (
    ELITE,
    EXPLORATION,
    FEASIBLE,
    INFEASIBLE,
    UNKNOWN,
)

if sys.version_info < (3, 10):  # noqa: UP036 - provide a clear error to the Python 3.9 regression environment.
    raise ImportError("ora_agent.gepa_repair requires Python >=3.10 because GEPA requires Python >=3.10")

GEPA_SRC = Path(
    os.environ.get(
        "GEPA_SRC",
        str(Path(__file__).resolve().parents[2] / "ext" / "gepa" / "src"),
    )
).resolve()
if not (GEPA_SRC / "gepa" / "gepa_utils.py").is_file():
    raise ImportError("GEPA source is required; set GEPA_SRC to the checkout's src directory")
sys.path.insert(0, str(GEPA_SRC))

from gepa.gepa_utils import (
    find_dominator_programs,
    select_program_candidate_from_pareto_front,
)
from gepa.proposer.merge import (
    sample_and_attempt_merge_programs_by_common_predictors,
)

DEFAULT_OPERATION = "default_declarative_neighborhood"
DIRECT_FULL_REOPTIMIZATION = "direct_full_reoptimization"
FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION = "feasible_parent_objective_optimization"
SYSTEM_AWARE_MERGE = "system_aware_merge"
REPAIR_OPERATIONS = (
    DEFAULT_OPERATION,
    DIRECT_FULL_REOPTIMIZATION,
    FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION,
)

Score = float | None
ArtifactBuilder = Callable[[Mapping[str, Any], DecisionArtifact], DecisionArtifact]


def _status(value: Any) -> str:
    normalized = str(value).strip().upper()
    if normalized in {FEASIBLE, "PASS", "PASSED"}:
        return FEASIBLE
    if normalized in {INFEASIBLE, "FAIL", "FAILED"}:
        return INFEASIBLE
    return UNKNOWN


def _score(value: Any) -> Score:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _instance_scores(values: Mapping[str, Any] | None) -> dict[str, Score]:
    if values is None:
        return {}
    return {str(key): _score(value) for key, value in values.items()}


def _failure_type_scores(
    values: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Score]]:
    if values is None:
        return {}
    return {
        str(instance): {str(failure_type): _score(value) for failure_type, value in scores.items()}
        for instance, scores in values.items()
    }


def _known_instance_scores(candidate: RepairCandidate) -> dict[str, float]:
    result = {instance: value for instance, value in candidate.instance_scores.items() if value is not None}
    for instance, failure_scores in candidate.failure_type_scores.items():
        if instance in result:
            continue
        known = [value for value in failure_scores.values() if value is not None]
        if known:
            result[instance] = sum(known) / len(known)
    return result


def _aggregate_score(candidate: RepairCandidate) -> float:
    scores = _known_instance_scores(candidate)
    if not scores:
        return float("-inf")
    return sum(scores.values()) / len(scores)


def _eligible(candidate: RepairCandidate) -> bool:
    return candidate.status != UNKNOWN and candidate.role == ELITE and math.isfinite(_aggregate_score(candidate))


@dataclass(frozen=True)
class PublicEvaluation:
    """Full public-check output; scores are optional and must be higher-is-better."""

    status: str
    instance_scores: Mapping[str, Score] = field(default_factory=dict)
    failure_type_scores: Mapping[str, Mapping[str, Score]] = field(default_factory=dict)
    report: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _status(self.status))
        object.__setattr__(self, "instance_scores", _instance_scores(self.instance_scores))
        object.__setattr__(self, "failure_type_scores", _failure_type_scores(self.failure_type_scores))
        object.__setattr__(self, "report", copy.deepcopy(dict(self.report)))


@dataclass(frozen=True)
class RepairCandidate:
    """A DecisionArtifact plus the lineage and public evidence needed by GEPA."""

    id: str
    artifact: DecisionArtifact
    components: Mapping[str, Any]
    parent_ids: tuple[str, ...] = ()
    instance_scores: Mapping[str, Score] = field(default_factory=dict)
    failure_type_scores: Mapping[str, Mapping[str, Score]] = field(default_factory=dict)
    changed_components: frozenset[str] = frozenset()
    operation: str = "initial"
    status: str = FEASIBLE
    role: str = ELITE
    public_checker: Any = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not self.id or not self.operation:
            raise ValueError("candidate id and operation must be nonempty")
        if not isinstance(self.artifact, DecisionArtifact):
            raise TypeError("artifact must be a DecisionArtifact")
        if self.id in self.parent_ids or len(set(self.parent_ids)) != len(self.parent_ids):
            raise ValueError("parent_ids must be unique and cannot contain the candidate")
        components = copy.deepcopy(dict(self.components))
        changed = frozenset(str(component) for component in self.changed_components)
        if not changed.issubset(components):
            raise ValueError("changed_components must name existing components")
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "parent_ids", tuple(str(parent) for parent in self.parent_ids))
        object.__setattr__(self, "instance_scores", _instance_scores(self.instance_scores))
        object.__setattr__(self, "failure_type_scores", _failure_type_scores(self.failure_type_scores))
        object.__setattr__(self, "changed_components", changed)
        object.__setattr__(self, "status", _status(self.status))
        object.__setattr__(self, "role", str(self.role).lower())

    @property
    def aggregate_score(self) -> float:
        return _aggregate_score(self)


@dataclass(frozen=True)
class OperationParentAssignment:
    parent: Any
    operation: str

    @property
    def parent_id(self) -> str:
        return str(self.parent.id)


@dataclass(frozen=True)
class MergeOutcome:
    candidate: RepairCandidate | None
    fallback: RepairCandidate | None
    reason: str
    ancestor_id: str | None = None
    parent_ids: tuple[str, ...] = ()
    evaluation: PublicEvaluation | None = None

    @property
    def accepted(self) -> bool:
        return self.candidate is not None

    @property
    def selected(self) -> RepairCandidate | None:
        return self.candidate if self.candidate is not None else self.fallback


def native_per_key_winners(candidates: Sequence[RepairCandidate]) -> dict[str, set[int]]:
    """Return native per-instance winners among elites; this is not a non-dominated archive."""
    fronts: dict[str, set[int]] = {}
    best: dict[str, float] = {}
    for index, candidate in enumerate(candidates):
        if not _eligible(candidate):
            continue
        for instance, score in _known_instance_scores(candidate).items():
            previous = best.get(instance, float("-inf"))
            if score > previous:
                best[instance] = score
                fronts[instance] = {index}
            elif score == previous:
                fronts[instance].add(index)
    return fronts


def build_instance_pareto_fronts(candidates: Sequence[RepairCandidate]) -> dict[str, set[int]]:
    """Compatibility alias for the native per-key GEPA frontier mapping."""
    return native_per_key_winners(candidates)


def _dominates_on_equal_coverage(left: Mapping[str, float], right: Mapping[str, float]) -> bool:
    if left.keys() != right.keys():
        return False
    return all(left[key] >= right[key] for key in left) and any(left[key] > right[key] for key in left)


def non_dominated_archive(candidates: Sequence[RepairCandidate]) -> tuple[RepairCandidate, ...]:
    """Retain every elite not pairwise dominated on an identical instance-score vector."""
    vectors = [(candidate, _known_instance_scores(candidate)) for candidate in candidates if _eligible(candidate)]
    return tuple(
        candidate
        for candidate, scores in vectors
        if not any(_dominates_on_equal_coverage(other_scores, scores) for _, other_scores in vectors)
    )


def _gepa_scores(candidates: Sequence[RepairCandidate]) -> list[float]:
    return [_aggregate_score(candidate) for candidate in candidates]


def pareto_elite_candidates(candidates: Sequence[RepairCandidate]) -> tuple[RepairCandidate, ...]:
    """Return GEPA-pruned native per-key winners, not the complete non-dominated archive."""
    fronts = native_per_key_winners(candidates)
    if not fronts:
        return ()
    dominators = set(find_dominator_programs(fronts, _gepa_scores(candidates)))
    return tuple(candidate for index, candidate in enumerate(candidates) if index in dominators)


def select_pareto_parents(
    candidates: Sequence[RepairCandidate],
    k: int = 1,
    *,
    rng: random.Random | None = None,
) -> tuple[RepairCandidate, ...]:
    """Sample distinct parents with the real GEPA frequency-biased Pareto selector."""
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    rng = random.Random(0) if rng is None else rng
    elites = pareto_elite_candidates(candidates)
    if not elites:
        raise ValueError("no known candidate has finite validation scores")
    positions = {id(candidate): index for index, candidate in enumerate(candidates)}
    remaining = {positions[id(candidate)] for candidate in elites}
    fronts = build_instance_pareto_fronts(candidates)
    scores = _gepa_scores(candidates)
    selected: list[RepairCandidate] = []
    while remaining and len(selected) < k:
        remaining_fronts = {instance: front & remaining for instance, front in fronts.items() if front & remaining}
        index = select_program_candidate_from_pareto_front(remaining_fronts, scores, rng)
        selected.append(candidates[index])
        remaining.remove(index)
    return tuple(selected)


def select_pareto_parent(
    candidates: Sequence[RepairCandidate],
    *,
    rng: random.Random | None = None,
) -> RepairCandidate:
    return select_pareto_parents(candidates, rng=rng)[0]


def _parent_status(parent: Any) -> str:
    if isinstance(parent, RepairCandidate):
        return parent.status
    return _status(parent.business_result.status)


def _operation_score(parent: Any, operation: str, previous_pairs: set[tuple[str, str]]) -> float | None:
    status = _parent_status(parent)
    if status == UNKNOWN:
        return None
    parent_operation = str(parent.operation)
    score = 0.0
    if operation == FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION:
        if status != FEASIBLE:
            return None
        score += 6.0
        if parent_operation == DIRECT_FULL_REOPTIMIZATION:
            score += 5.0
    elif operation == DEFAULT_OPERATION:
        score += 4.0 if status == INFEASIBLE else 1.0
    elif operation == DIRECT_FULL_REOPTIMIZATION:
        score += 3.0 if status == INFEASIBLE else 0.0
        if parent_operation == DIRECT_FULL_REOPTIMIZATION:
            score -= 7.0
    if operation == parent_operation:
        score -= 2.0
    if (str(parent.id), operation) in previous_pairs:
        score -= 4.0
    return score


def assign_operations_to_parents(
    parents: Sequence[Any],
    operations: Sequence[str] = REPAIR_OPERATIONS,
    *,
    previous_pairs: Iterable[tuple[str, str]] = (),
    rng: random.Random | None = None,
) -> tuple[OperationParentAssignment, ...]:
    """Assign compatible operations by parent state rather than generation/branch rotation."""
    if not operations:
        raise ValueError("at least one operation is required")
    if any(_parent_status(parent) == UNKNOWN for parent in parents):
        raise ValueError("UNKNOWN candidates cannot be repair parents")
    rng = random.Random(0) if rng is None else rng
    history = {(str(parent_id), str(operation)) for parent_id, operation in previous_pairs}
    remaining_parents = list(parents)
    remaining_operations = list(operations)
    assignments: list[OperationParentAssignment] = []

    mandatory = [
        parent
        for parent in remaining_parents
        if parent.operation == DIRECT_FULL_REOPTIMIZATION and str(getattr(parent, "role", ELITE)).lower() == EXPLORATION
    ]
    if mandatory and FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION not in operations:
        raise ValueError("direct-full exploration requires the feasible-parent objective operation")
    for parent in mandatory:
        if _parent_status(parent) != FEASIBLE:
            raise ValueError("direct-full exploration parent is not feasible")
        assignments.append(OperationParentAssignment(parent, FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION))
        remaining_parents.remove(parent)
        if FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION in remaining_operations:
            remaining_operations.remove(FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION)

    while remaining_parents:
        if not remaining_operations:
            remaining_operations = list(operations)
        scored: list[tuple[float, Any, str]] = []
        for parent in remaining_parents:
            for operation in remaining_operations:
                score = _operation_score(parent, operation, history)
                if score is not None:
                    scored.append((score, parent, operation))
        if not scored and len(remaining_operations) != len(operations):
            remaining_operations = list(operations)
            continue
        if not scored:
            raise ValueError("no compatible operation-parent assignment exists")
        best_score = max(score for score, _, _ in scored)
        best = [(parent, operation) for score, parent, operation in scored if score == best_score]
        parent, operation = rng.choice(best)
        assignments.append(OperationParentAssignment(parent, operation))
        remaining_parents.remove(parent)
        remaining_operations.remove(operation)
    return tuple(assignments)


def _fallback(candidates: Sequence[RepairCandidate]) -> RepairCandidate | None:
    known = [candidate for candidate in candidates if _eligible(candidate)]
    if not known:
        return None
    return max(known, key=lambda candidate: candidate.aggregate_score)


def _outcome(
    candidates: Sequence[RepairCandidate],
    reason: str,
    **kwargs: Any,
) -> MergeOutcome:
    return MergeOutcome(candidate=None, fallback=_fallback(candidates), reason=reason, **kwargs)


def _coerce_evaluation(value: Any) -> PublicEvaluation:
    if isinstance(value, PublicEvaluation):
        return value
    if not isinstance(value, Mapping):
        return PublicEvaluation(UNKNOWN)
    return PublicEvaluation(
        status=value.get("business_status", value.get("status", UNKNOWN)),
        instance_scores=value.get("instance_scores", {}),
        failure_type_scores=value.get("failure_type_scores", {}),
        report=value,
    )


def _run_public_checker(checker: Any, artifact: DecisionArtifact) -> PublicEvaluation:
    method = getattr(checker, "check", None)
    if callable(method):
        return _coerce_evaluation(method(artifact.decisions))
    if callable(checker):
        return _coerce_evaluation(checker(artifact))
    raise TypeError("public_checker must be callable or provide check(decisions)")


def _default_artifact_builder(components: Mapping[str, Any], base: DecisionArtifact) -> DecisionArtifact:
    decisions = copy.deepcopy(base.decisions)
    decisions.update(copy.deepcopy(dict(components)))
    return DecisionArtifact.create(decisions)


def _effective_changes(
    ancestor: RepairCandidate,
    candidate: RepairCandidate,
) -> frozenset[str]:
    return frozenset(name for name, value in ancestor.components.items() if candidate.components[name] != value)


def _shared_checker(
    left: RepairCandidate,
    right: RepairCandidate,
    ancestor: RepairCandidate,
    override: Any,
) -> Any:
    if override is not None:
        return override
    checkers = [
        candidate.public_checker for candidate in (left, right, ancestor) if candidate.public_checker is not None
    ]
    if not checkers:
        return None
    if any(checker is not checkers[0] for checker in checkers[1:]):
        return None
    return checkers[0]


def propose_system_aware_merge(
    candidates: Sequence[RepairCandidate],
    *,
    min_validation_overlap: int = 5,
    artifact_builder: ArtifactBuilder | None = None,
    public_checker: Any = None,
    rng: random.Random | None = None,
    max_attempts: int = 10,
    merged_id: str | None = None,
) -> MergeOutcome:
    """Use GEPA lineage/component merging, then require disjoint changes and a full public PASS."""
    if (
        isinstance(min_validation_overlap, bool)
        or not isinstance(min_validation_overlap, int)
        or min_validation_overlap <= 0
    ):
        raise ValueError("min_validation_overlap must be a positive integer")
    rng = random.Random(0) if rng is None else rng
    artifact_builder = _default_artifact_builder if artifact_builder is None else artifact_builder
    by_id = {candidate.id: index for index, candidate in enumerate(candidates)}
    if len(by_id) != len(candidates):
        raise ValueError("candidate ids must be unique")
    if len(candidates) < 3:
        return _outcome(candidates, "insufficient_lineage")
    if any(parent not in by_id for candidate in candidates for parent in candidate.parent_ids):
        return _outcome(candidates, "incomplete_lineage")
    schemas = {frozenset(candidate.components) for candidate in candidates}
    if len(schemas) != 1:
        return _outcome(candidates, "component_schema_mismatch")

    parent_list = [[by_id[parent] for parent in candidate.parent_ids] for candidate in candidates]
    component_values = [dict(candidate.components) for candidate in candidates]
    aggregate_scores = _gepa_scores(candidates)
    eligible = [index for index, candidate in enumerate(candidates) if _eligible(candidate)]
    merges_performed: tuple[list[Any], list[Any]] = ([], [])

    def enough_overlap(id1: int, id2: int) -> bool:
        common = set(_known_instance_scores(candidates[id1])) & set(_known_instance_scores(candidates[id2]))
        return len(common) >= min_validation_overlap

    for left_index, right_index in combinations(eligible, 2):
        left = candidates[left_index]
        right = candidates[right_index]
        if not left.changed_components or not right.changed_components:
            continue
        if left.changed_components & right.changed_components:
            continue
        if not enough_overlap(left_index, right_index):
            continue
        merge = sample_and_attempt_merge_programs_by_common_predictors(
            agg_scores=aggregate_scores,
            rng=rng,
            merge_candidates=[left_index, right_index],
            merges_performed=merges_performed,
            program_candidates=component_values,
            parent_program_for_candidate=parent_list,
            has_val_support_overlap=enough_overlap,
            max_attempts=max_attempts,
        )
        if merge is None:
            continue
        new_components, id1, id2, ancestor_index = merge
        left, right = candidates[id1], candidates[id2]
        ancestor = candidates[ancestor_index]
        parent_ids = (left.id, right.id)
        if not _eligible(ancestor) or not math.isfinite(aggregate_scores[ancestor_index]):
            return _outcome(candidates, "unknown_or_unscored_ancestor", ancestor_id=ancestor.id, parent_ids=parent_ids)
        left_changes = _effective_changes(ancestor, left)
        right_changes = _effective_changes(ancestor, right)
        if not left_changes or not right_changes or left_changes & right_changes:
            continue
        expected = copy.deepcopy(ancestor.components)
        for name in left_changes:
            expected[name] = copy.deepcopy(left.components[name])
        for name in right_changes:
            expected[name] = copy.deepcopy(right.components[name])
        if new_components != expected:
            continue
        checker = _shared_checker(left, right, ancestor, public_checker)
        if checker is None:
            return _outcome(
                candidates, "missing_or_mismatched_public_checker", ancestor_id=ancestor.id, parent_ids=parent_ids
            )
        try:
            merged_artifact = artifact_builder(new_components, ancestor.artifact)
        except Exception:  # noqa: BLE001 - adapter failures must fall back without a new elite.
            return _outcome(candidates, "artifact_builder_failed", ancestor_id=ancestor.id, parent_ids=parent_ids)
        if not isinstance(merged_artifact, DecisionArtifact):
            return _outcome(candidates, "artifact_builder_failed", ancestor_id=ancestor.id, parent_ids=parent_ids)
        if any(
            candidate.artifact.sha256 == merged_artifact.sha256
            or candidate.artifact.decisions == merged_artifact.decisions
            for candidate in candidates
        ):
            return _outcome(candidates, "duplicate_candidate", ancestor_id=ancestor.id, parent_ids=parent_ids)
        try:
            evaluation = _run_public_checker(checker, merged_artifact)
        except Exception:  # noqa: BLE001 - adapter failures must fall back without a new elite.
            return _outcome(candidates, "public_check_failed", ancestor_id=ancestor.id, parent_ids=parent_ids)
        if evaluation.status == UNKNOWN:
            return _outcome(
                candidates,
                "public_check_unknown",
                ancestor_id=ancestor.id,
                parent_ids=parent_ids,
                evaluation=evaluation,
            )
        if evaluation.status != FEASIBLE:
            return _outcome(
                candidates,
                "public_check_failed",
                ancestor_id=ancestor.id,
                parent_ids=parent_ids,
                evaluation=evaluation,
            )
        candidate_id = merged_id or f"merge({left.id},{right.id})"
        if candidate_id in by_id:
            return _outcome(candidates, "duplicate_candidate_id", ancestor_id=ancestor.id, parent_ids=parent_ids)
        merged = RepairCandidate(
            id=candidate_id,
            artifact=merged_artifact,
            components=new_components,
            parent_ids=parent_ids,
            instance_scores=evaluation.instance_scores,
            failure_type_scores=evaluation.failure_type_scores,
            changed_components=left_changes | right_changes,
            operation=SYSTEM_AWARE_MERGE,
            status=FEASIBLE,
            role=ELITE,
            public_checker=checker,
        )
        return MergeOutcome(
            candidate=merged,
            fallback=_fallback(candidates),
            reason="merged",
            ancestor_id=ancestor.id,
            parent_ids=parent_ids,
            evaluation=evaluation,
        )
    return _outcome(candidates, "no_compatible_merge")
