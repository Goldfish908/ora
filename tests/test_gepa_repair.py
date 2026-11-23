from __future__ import annotations

import copy
import random
import sys
from dataclasses import replace

import pytest

if sys.version_info < (3, 10):  # noqa: UP036 - required by the Python 3.9 regression environment.
    pytest.skip(
        "GEPA repair tests require Python >=3.10 because GEPA does not support Python 3.9",
        allow_module_level=True,
    )

from ora_agent.declarative_neighborhood import DecisionArtifact
from ora_agent.gepa_repair import (
    DEFAULT_OPERATION,
    DIRECT_FULL_REOPTIMIZATION,
    FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION,
    SYSTEM_AWARE_MERGE,
    PublicEvaluation,
    RepairCandidate,
    assign_operations_to_parents,
    build_instance_pareto_fronts,
    native_per_key_winners,
    non_dominated_archive,
    pareto_elite_candidates,
    propose_system_aware_merge,
    select_pareto_parent,
    select_pareto_parents,
)
from ora_agent.population_repair import (
    ELITE,
    EXPLORATION,
    FEASIBLE,
    INFEASIBLE,
    UNKNOWN,
    BusinessResult,
    Candidate,
    Evaluation,
)


class RecordingChecker:
    def __init__(self, status=FEASIBLE):
        self.status = status
        self.calls = []

    def check(self, decisions):
        self.calls.append(copy.deepcopy(decisions))
        return PublicEvaluation(
            self.status,
            instance_scores={"i1": 3.0, "i2": 3.0},
            failure_type_scores={
                "i1": {"privacy_budget": 3.0},
                "i2": {"upload_budget": 3.0},
            },
            report={"business_status": self.status},
        )


def candidate(
    candidate_id,
    components,
    scores,
    *,
    parents=(),
    changed=(),
    operation="initial",
    status=FEASIBLE,
    role=ELITE,
    checker=None,
):
    return RepairCandidate(
        id=candidate_id,
        artifact=DecisionArtifact.create(components, f"{candidate_id}:original-bytes".encode()),
        components=components,
        parent_ids=tuple(parents),
        instance_scores=scores,
        changed_components=frozenset(changed),
        operation=operation,
        status=status,
        role=role,
        public_checker=checker,
    )


def merge_lineage(checker=None):
    root = candidate("root", {"a": 0, "b": 0}, {"i1": 0.0, "i2": 0.0}, checker=checker)
    left = candidate(
        "left",
        {"a": 1, "b": 0},
        {"i1": 2.0, "i2": 1.0},
        parents=("root",),
        changed=("a",),
        operation=DEFAULT_OPERATION,
        checker=checker,
    )
    right = candidate(
        "right",
        {"a": 0, "b": 1},
        {"i1": 1.0, "i2": 2.0},
        parents=("root",),
        changed=("b",),
        operation=DIRECT_FULL_REOPTIMIZATION,
        checker=checker,
    )
    return root, left, right


def population_candidate(candidate_id, operation, status, role):
    artifact = DecisionArtifact.create({"id": candidate_id}, candidate_id.encode())
    return (
        Candidate.seed(
            {"artifact_sha256": artifact.sha256},
            Evaluation(
                {"source": "test"},
                BusinessResult(status, objective=1.0, sense="max"),
                cost=0.0,
                checkpoint=artifact,
                structure=artifact.sha256,
            ),
            id=candidate_id,
        )
        if operation == "initial"
        else replace(
            population_candidate(candidate_id, "initial", status, role),
            operation=operation,
            role=role,
        )
    )


def test_all_budgets_direct_exploration_gets_objective_operation():
    root = population_candidate("all_budgets/root", "initial", INFEASIBLE, ELITE)
    direct_exploration = population_candidate(
        "all_budgets/direct-exploration",
        DIRECT_FULL_REOPTIMIZATION,
        FEASIBLE,
        EXPLORATION,
    )

    assignments = assign_operations_to_parents(
        [root, direct_exploration],
        rng=random.Random(7),
    )
    by_parent = {assignment.parent_id: assignment.operation for assignment in assignments}

    assert by_parent[direct_exploration.id] == FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION
    assert by_parent[root.id] == DEFAULT_OPERATION


def test_operation_assignment_is_compatible_not_positional_rotation():
    infeasible = candidate("infeasible", {"a": 0}, {"i1": 0.0}, status=INFEASIBLE)
    feasible = candidate("feasible", {"a": 1}, {"i1": 1.0})

    assignments = assign_operations_to_parents(
        [infeasible, feasible],
        [FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION, DEFAULT_OPERATION],
        rng=random.Random(0),
    )
    by_parent = {assignment.parent_id: assignment.operation for assignment in assignments}

    assert by_parent == {
        infeasible.id: DEFAULT_OPERATION,
        feasible.id: FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION,
    }


def test_instance_pareto_retains_complementary_candidates_and_rejects_unknown():
    privacy = candidate("privacy", {"a": 1}, {"privacy_case": 2.0, "upload_case": 0.0})
    upload = candidate("upload", {"a": 2}, {"privacy_case": 0.0, "upload_case": 2.0})
    weak = candidate("weak", {"a": 3}, {"privacy_case": 0.0, "upload_case": 0.0})
    unknown = candidate(
        "unknown",
        {"a": 4},
        {"privacy_case": 100.0, "upload_case": 100.0},
        status=UNKNOWN,
    )
    candidates = [weak, privacy, unknown, upload]

    fronts = build_instance_pareto_fronts(candidates)
    elites = pareto_elite_candidates(candidates)
    selected = select_pareto_parents(candidates, 2, rng=random.Random(4))

    assert fronts == {"privacy_case": {1}, "upload_case": {3}}
    assert {item.id for item in elites} == {"privacy", "upload"}
    assert {item.id for item in selected} == {"privacy", "upload"}
    assert select_pareto_parent(candidates, rng=random.Random(0)).status != UNKNOWN
    with pytest.raises(ValueError, match="no known candidate"):
        select_pareto_parent([unknown])


def test_non_dominated_archive_keeps_middle_candidate_not_winning_any_key():
    accuracy_best = candidate("accuracy-best", {"a": 1}, {"accuracy": 3.0, "speed": 1.0})
    speed_best = candidate("speed-best", {"a": 2}, {"accuracy": 1.0, "speed": 3.0})
    middle = candidate("middle", {"a": 3}, {"accuracy": 2.0, "speed": 2.0})
    dominated = candidate("dominated", {"a": 4}, {"accuracy": 1.0, "speed": 1.0})
    candidates = [accuracy_best, speed_best, middle, dominated]

    native = native_per_key_winners(candidates)
    archive = non_dominated_archive(candidates)

    assert native == {"accuracy": {0}, "speed": {1}}
    assert build_instance_pareto_fronts(candidates) == native
    assert middle not in pareto_elite_candidates(candidates)
    assert {item.id for item in archive} == {"accuracy-best", "speed-best", "middle"}


def test_non_dominated_archive_compares_only_identical_instance_coverage():
    dominated = candidate("dominated", {"a": 1}, {"accuracy": 1.0, "speed": 1.0})
    dominator = candidate("dominator", {"a": 2}, {"accuracy": 2.0, "speed": 2.0})
    partial_coverage = candidate("partial", {"a": 3}, {"accuracy": 0.0})

    archive = non_dominated_archive([dominated, dominator, partial_coverage])

    assert {item.id for item in archive} == {"dominator", "partial"}


def test_direct_full_exploration_is_not_elite_frontier_but_remains_assignable():
    elite = candidate("elite", {"a": 0}, {"accuracy": 1.0})
    exploration = candidate(
        "direct-exploration",
        {"a": 1},
        {"accuracy": 100.0},
        operation=DIRECT_FULL_REOPTIMIZATION,
        role=EXPLORATION,
    )

    assert native_per_key_winners([elite, exploration]) == {"accuracy": {0}}
    assert non_dominated_archive([elite, exploration]) == (elite,)
    assert pareto_elite_candidates([elite, exploration]) == (elite,)
    assert select_pareto_parent([elite, exploration]) is elite
    assert pareto_elite_candidates([exploration]) == ()

    assignments = assign_operations_to_parents([exploration], rng=random.Random(0))
    assert [(item.parent, item.operation) for item in assignments] == [
        (exploration, FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION)
    ]


def test_system_aware_merge_uses_common_ancestor_and_preserves_parent_bytes():
    checker = RecordingChecker()
    root, left, right = merge_lineage(checker)
    parent_bytes = {item.id: item.artifact.raw_bytes for item in (root, left, right)}

    outcome = propose_system_aware_merge(
        [root, left, right],
        min_validation_overlap=2,
        rng=random.Random(3),
    )

    assert outcome.accepted
    assert outcome.reason == "merged"
    assert outcome.ancestor_id == root.id
    assert outcome.parent_ids == (left.id, right.id)
    assert outcome.candidate.operation == SYSTEM_AWARE_MERGE
    assert outcome.candidate.components == {"a": 1, "b": 1}
    assert outcome.candidate.artifact.decisions == {"a": 1, "b": 1}
    assert outcome.candidate.changed_components == frozenset({"a", "b"})
    assert checker.calls == [{"a": 1, "b": 1}]
    assert all(item.artifact.raw_bytes == parent_bytes[item.id] for item in (root, left, right))


def test_merge_requires_a_common_ancestor_and_descendants_not_worse_than_it():
    root_a, left, _ = merge_lineage(RecordingChecker())
    root_b = candidate("root-b", {"a": 0, "b": 0}, {"i1": 0.0, "i2": 0.0})
    right = candidate(
        "right",
        {"a": 0, "b": 1},
        {"i1": 2.0, "i2": 2.0},
        parents=("root-b",),
        changed=("b",),
    )
    no_common = propose_system_aware_merge(
        [root_a, root_b, left, right],
        min_validation_overlap=2,
    )
    assert not no_common.accepted

    better_root, worse_left, worse_right = merge_lineage(RecordingChecker())
    better_root = replace(better_root, instance_scores={"i1": 10.0, "i2": 10.0})
    worse_ancestor = propose_system_aware_merge(
        [better_root, worse_left, worse_right],
        min_validation_overlap=2,
    )
    assert not worse_ancestor.accepted


def test_merge_rejects_mutual_ancestor_lineage():
    root = candidate("root", {"a": 0, "b": 0}, {"i1": 0.0, "i2": 0.0})
    left = candidate("left", {"a": 1, "b": 0}, {"i1": 1.0, "i2": 1.0}, parents=("root",), changed=("a",))
    descendant = candidate(
        "descendant",
        {"a": 1, "b": 1},
        {"i1": 2.0, "i2": 2.0},
        parents=("left",),
        changed=("b",),
    )

    outcome = propose_system_aware_merge([root, left, descendant], min_validation_overlap=2)

    assert not outcome.accepted


def test_no_complementary_components_means_no_merge_and_no_public_check():
    checker = RecordingChecker()
    root = candidate("root", {"a": 0, "b": 0}, {"i1": 0.0, "i2": 0.0}, checker=checker)
    left = candidate(
        "left", {"a": 1, "b": 0}, {"i1": 1.0, "i2": 1.0}, parents=("root",), changed=("a",), checker=checker
    )
    overlapping = candidate(
        "overlapping",
        {"a": 2, "b": 0},
        {"i1": 2.0, "i2": 2.0},
        parents=("root",),
        changed=("a",),
        checker=checker,
    )

    outcome = propose_system_aware_merge([root, left, overlapping], min_validation_overlap=2)

    assert not outcome.accepted
    assert outcome.reason == "no_compatible_merge"
    assert checker.calls == []


def test_duplicate_combination_is_not_merged_or_checked():
    checker = RecordingChecker()
    root, left, right = merge_lineage(checker)
    existing = candidate(
        "existing",
        {"a": 1, "b": 1},
        {"i1": 3.0, "i2": 3.0},
        parents=("root",),
        changed=("a", "b"),
        checker=checker,
    )

    outcome = propose_system_aware_merge([root, left, right, existing], min_validation_overlap=2)

    assert not outcome.accepted
    assert outcome.reason == "no_compatible_merge"
    assert checker.calls == []


def test_merge_requires_enough_common_validation_coverage():
    checker = RecordingChecker()
    root, left, right = merge_lineage(checker)
    left = replace(left, instance_scores={"i1": 2.0})
    right = replace(right, instance_scores={"i2": 2.0})

    outcome = propose_system_aware_merge([root, left, right], min_validation_overlap=1)

    assert not outcome.accepted
    assert outcome.reason == "no_compatible_merge"
    assert checker.calls == []


def test_unknown_public_check_falls_back_to_exact_parent_and_bytes():
    checker = RecordingChecker(UNKNOWN)
    root, left, right = merge_lineage(checker)
    original_bytes = left.artifact.raw_bytes

    outcome = propose_system_aware_merge([root, left, right], min_validation_overlap=2)

    assert not outcome.accepted
    assert outcome.reason == "public_check_unknown"
    assert outcome.candidate is None
    assert outcome.selected is left
    assert outcome.selected.artifact is left.artifact
    assert outcome.selected.artifact.raw_bytes == original_bytes
    assert left.artifact.raw_bytes == original_bytes


def test_failed_public_check_also_falls_back_without_new_elite():
    checker = RecordingChecker(INFEASIBLE)
    root, left, right = merge_lineage(checker)

    outcome = propose_system_aware_merge([root, left, right], min_validation_overlap=2)

    assert not outcome.accepted
    assert outcome.reason == "public_check_failed"
    assert outcome.selected in (left, right)
    assert outcome.selected.status != UNKNOWN
