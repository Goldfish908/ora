"""Fail-closed population repair with pluggable mutation and evaluation callables.

The initial candidate is already evaluated and is not charged to the child
candidate evaluation budget. The defaults evaluate six children: two population
generations of three proposals, or six single-chain steps. Duplicate payloads
are rejected before evaluation but their mutation proposal costs are retained.
Optional exploration retains feasible objective regressions for parenting only;
final elites and delivery always remain fail-closed relative to the seed.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, Sequence

FEASIBLE = "FEASIBLE"
INFEASIBLE = "INFEASIBLE"
UNKNOWN = "UNKNOWN"
ELITE = "elite"
EXPLORATION = "exploration"
REJECTED = "rejected"


def _cost(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("cost must be a finite non-negative number")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("cost must be a finite non-negative number")
    return value


def payload_digest(payload: Any) -> str:
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    elif isinstance(payload, bytes):
        raw = payload
    else:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         allow_nan=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class BusinessResult:
    status: str
    objective: float | None = None
    sense: str = "min"
    violation_count: int = 0
    violation_score: float = 0.0
    hard_errors: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        status = self.status.upper()
        if status not in {FEASIBLE, INFEASIBLE, UNKNOWN}:
            raise ValueError(f"unsupported business status: {self.status!r}")
        object.__setattr__(self, "status", status)
        senses = {"min": "min", "minimize": "min", "max": "max", "maximize": "max"}
        try:
            sense = senses[self.sense.lower()]
        except (AttributeError, KeyError) as exc:
            raise ValueError(f"unsupported objective sense: {self.sense!r}") from exc
        object.__setattr__(self, "sense", sense)
        if self.objective is not None:
            if (isinstance(self.objective, bool)
                    or not isinstance(self.objective, (int, float))
                    or not math.isfinite(self.objective)):
                raise ValueError("objective must be finite or None")
            object.__setattr__(self, "objective", float(self.objective))
        if (isinstance(self.violation_count, bool)
                or not isinstance(self.violation_count, int)
                or self.violation_count < 0):
            raise ValueError("violation_count must be a non-negative integer")
        if (isinstance(self.violation_score, bool)
                or not isinstance(self.violation_score, (int, float))
                or not math.isfinite(self.violation_score)
                or self.violation_score < 0):
            raise ValueError("violation_score must be finite and non-negative")
        object.__setattr__(self, "violation_score", float(self.violation_score))
        object.__setattr__(self, "hard_errors",
                           frozenset(str(error) for error in self.hard_errors))


@dataclass(frozen=True)
class Mutation:
    operation: str
    payload: Any
    cost: float = 0.0

    def __post_init__(self) -> None:
        if not self.operation or not self.operation.strip():
            raise ValueError("mutation operation must be non-empty")
        object.__setattr__(self, "cost", _cost(self.cost))


@dataclass(frozen=True)
class Evaluation:
    execution_result: Any
    business_result: BusinessResult
    cost: float
    checkpoint: Any
    structure: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cost", _cost(self.cost))


@dataclass(frozen=True)
class Candidate:
    id: str
    parent_id: str | None
    operation: str
    payload: Any
    execution_result: Any
    business_result: BusinessResult
    cost: float
    checkpoint: Any
    generation: int = 0
    structure: str | None = None
    proposal_cost: float = 0.0
    evaluation_cost: float | None = None
    role: str = ELITE
    payload_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.id or not self.operation:
            raise ValueError("candidate id and operation must be non-empty")
        if self.generation < 0:
            raise ValueError("candidate generation must be non-negative")
        cost = _cost(self.cost)
        proposal_cost = _cost(self.proposal_cost)
        evaluation_cost = (cost - proposal_cost if self.evaluation_cost is None
                           else _cost(self.evaluation_cost))
        evaluation_cost = _cost(evaluation_cost)
        if not math.isclose(cost, proposal_cost + evaluation_cost,
                            rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("candidate cost must equal proposal_cost + evaluation_cost")
        if self.role not in {ELITE, EXPLORATION, REJECTED}:
            raise ValueError(f"unsupported candidate role: {self.role!r}")
        object.__setattr__(self, "cost", cost)
        object.__setattr__(self, "proposal_cost", proposal_cost)
        object.__setattr__(self, "evaluation_cost", evaluation_cost)
        object.__setattr__(self, "payload_hash", payload_digest(self.payload))

    @classmethod
    def seed(cls, payload: Any, evaluation: Evaluation, id: str = "seed") -> Candidate:
        return cls(id=id, parent_id=None, operation="initial", payload=payload,
                   execution_result=evaluation.execution_result,
                   business_result=evaluation.business_result,
                   cost=evaluation.cost, checkpoint=evaluation.checkpoint,
                   structure=evaluation.structure, proposal_cost=0.0,
                   evaluation_cost=evaluation.cost, role=ELITE)

    @property
    def structure_key(self) -> str:
        return self.structure or self.payload_hash


class MutationOperator(Protocol):
    def __call__(self, parent: Candidate, /) -> Mutation:
        ...


class CandidateEvaluator(Protocol):
    def __call__(self, mutation: Mutation, parent: Candidate, /) -> Evaluation:
        ...


@dataclass(frozen=True)
class Rejection:
    generation: int
    parent_id: str
    operation: str
    payload_hash: str
    reasons: tuple[str, ...]
    candidate: Candidate | None = None
    proposal_cost: float = 0.0
    evaluation_cost: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposal_cost", _cost(self.proposal_cost))
        object.__setattr__(self, "evaluation_cost", _cost(self.evaluation_cost))


@dataclass(frozen=True)
class RepairRun:
    mode: str
    initial: Candidate
    best: Candidate
    population: tuple[Candidate, ...]
    elite_population: tuple[Candidate, ...]
    candidates: tuple[Candidate, ...]
    accepted: tuple[Candidate, ...]
    elites: tuple[Candidate, ...]
    exploration: tuple[Candidate, ...]
    rejections: tuple[Rejection, ...]
    evaluations: int
    proposal_cost: float
    evaluation_cost: float
    total_cost: float
    generation_evaluations: tuple[int, ...]
    stop_reason: str

    def __post_init__(self) -> None:
        if not math.isclose(self.total_cost, self.proposal_cost + self.evaluation_cost,
                            rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("total_cost must equal proposal_cost + evaluation_cost")

    @property
    def checkpoint(self) -> Any:
        return self.best.checkpoint

    @property
    def improved_over_initial(self) -> bool:
        return _business_key(self.best) < _business_key(self.initial)

    def lineage(self, candidate: Candidate | str | None = None) -> tuple[Candidate, ...]:
        if candidate is None:
            candidate = self.best
        candidate_id = candidate if isinstance(candidate, str) else candidate.id
        by_id = {item.id: item for item in self.candidates}
        lineage = []
        seen = set()
        while candidate_id is not None:
            if candidate_id in seen:
                raise ValueError("candidate lineage contains a cycle")
            seen.add(candidate_id)
            item = by_id[candidate_id]
            lineage.append(item)
            candidate_id = item.parent_id
        return tuple(reversed(lineage))


@dataclass(frozen=True)
class StrategyComparison:
    population: RepairRun
    single_chain: RepairRun
    population_better: bool
    winner: str
    population_advantage: float | None

    @property
    def negative_result(self) -> bool:
        return not self.population_better


def _quality_key(candidate: Candidate) -> tuple[int, float]:
    objective = candidate.business_result.objective
    if objective is None:
        return (1, 0.0)
    if candidate.business_result.sense == "max":
        objective = -objective
    return (0, objective)


def _feasibility_key(candidate: Candidate) -> tuple[int, int, float]:
    result = candidate.business_result
    return (0 if result.status == FEASIBLE else 1,
            result.violation_count, result.violation_score)


def _business_key(candidate: Candidate) -> tuple:
    return (*_feasibility_key(candidate), *_quality_key(candidate))


def _recency_key(candidate: Candidate) -> tuple[int, str]:
    return (-candidate.generation, candidate.id)


class PopulationRepairController:
    def __init__(self, k: int = 3, depth: int = 2, evaluation_budget: int = 6):
        if (isinstance(k, bool) or not isinstance(k, int) or k <= 0
                or isinstance(depth, bool) or not isinstance(depth, int) or depth <= 0
                or isinstance(evaluation_budget, bool)
                or not isinstance(evaluation_budget, int) or evaluation_budget <= 0):
            raise ValueError("k, depth and evaluation_budget must be positive integers")
        self.k = k
        self.depth = depth
        self.evaluation_budget = evaluation_budget

    def select_parents(self, candidates: Sequence[Candidate], k: int | None = None,
                       exploration: Sequence[Candidate] | None = None
                       ) -> tuple[Candidate, ...]:
        if not candidates:
            return ()
        k = self.k if k is None else k
        selected = self._select_elite_parents(candidates, k)
        if not exploration:
            return selected
        if k == 1:
            return (max((*selected, *exploration),
                        key=lambda item: (item.generation, item.id)),)
        retained_elites = list(selected[:k - 1])
        remaining_elites = list(selected[k - 1:])
        structures = {candidate.structure_key for candidate in retained_elites}
        remaining_exploration = list(exploration)
        parents = list(retained_elites)
        while remaining_exploration and len(parents) < k:
            candidate = min(remaining_exploration,
                            key=lambda item: (item.structure_key in structures,
                                              _recency_key(item)))
            remaining_exploration.remove(candidate)
            parents.append(candidate)
            structures.add(candidate.structure_key)
        parents.extend(remaining_elites[:k - len(parents)])
        return tuple(parents)

    @staticmethod
    def _select_elite_parents(candidates: Sequence[Candidate],
                              k: int) -> tuple[Candidate, ...]:
        ordered = sorted(candidates,
                         key=lambda item: (_business_key(item), _recency_key(item)))
        best = ordered[0]
        most_feasible = min(candidates,
                            key=lambda item: (_feasibility_key(item), _quality_key(item),
                                              _recency_key(item)))
        selected = []
        for candidate in (most_feasible, best):
            if candidate not in selected:
                selected.append(candidate)
        structures = {candidate.structure_key for candidate in selected}
        best_business = _business_key(best)
        diverse = [candidate for candidate in candidates
                   if candidate not in selected and _business_key(candidate) == best_business]
        while diverse and len(selected) < k:
            candidate = min(diverse, key=lambda item: (item.structure_key in structures,
                                                       _recency_key(item)))
            diverse.remove(candidate)
            selected.append(candidate)
            structures.add(candidate.structure_key)
        return tuple(selected)

    def run(self, initial: Candidate, evaluator: CandidateEvaluator,
            operators: Sequence[MutationOperator], *, single_chain: bool = False,
            allow_exploration: bool = False) -> RepairRun:
        if initial.business_result.status == UNKNOWN:
            raise ValueError("an UNKNOWN initial candidate cannot seed repair")
        if not operators:
            raise ValueError("at least one mutation operator is required")
        k = 1 if single_chain else self.k
        depth = self.evaluation_budget if single_chain else self.depth
        mode = "single_chain" if single_chain else "population"
        accepted = [initial]
        elites = [initial]
        exploration = []
        candidates = [initial]
        rejections = []
        seen = {initial.payload_hash}
        active = initial
        evaluations = 0
        proposal_cost = 0.0
        evaluation_cost = 0.0
        generation_evaluations = []
        stop_reason = "depth_exhausted"

        for generation in range(1, depth + 1):
            if evaluations >= self.evaluation_budget:
                stop_reason = "budget_exhausted"
                break
            if single_chain:
                parents = (active,)
            else:
                parents = self.select_parents(
                    elites, k, exploration if allow_exploration else None)
            before = evaluations
            for branch in range(k):
                if evaluations >= self.evaluation_budget:
                    break
                parent = parents[branch % len(parents)]
                operator = operators[((generation - 1) * k + branch) % len(operators)]
                mutation = operator(parent)
                if not isinstance(mutation, Mutation):
                    raise TypeError("mutation operators must return Mutation")
                proposal_cost += mutation.cost
                digest = payload_digest(mutation.payload)
                if digest in seen:
                    rejections.append(Rejection(
                        generation=generation, parent_id=parent.id,
                        operation=mutation.operation, payload_hash=digest,
                        reasons=("duplicate_hash",), proposal_cost=mutation.cost))
                    continue
                seen.add(digest)
                evaluation = evaluator(mutation, parent)
                if not isinstance(evaluation, Evaluation):
                    raise TypeError("candidate evaluators must return Evaluation")
                evaluation_cost += evaluation.cost
                if evaluation.business_result.sense != initial.business_result.sense:
                    raise ValueError("all candidates must use the initial objective sense")
                candidate = Candidate(
                    id=f"{initial.id}/g{generation}/c{branch + 1}",
                    parent_id=parent.id, operation=mutation.operation,
                    payload=mutation.payload,
                    execution_result=evaluation.execution_result,
                    business_result=evaluation.business_result,
                    cost=mutation.cost + evaluation.cost,
                    checkpoint=evaluation.checkpoint, generation=generation,
                    structure=evaluation.structure, proposal_cost=mutation.cost,
                    evaluation_cost=evaluation.cost)
                evaluations += 1
                incumbent = min(elites, key=_business_key)
                reasons = self._rejection_reasons(candidate, parent, initial, incumbent)
                explore = (allow_exploration and bool(reasons)
                           and self._can_explore(candidate, reasons))
                if reasons and not explore:
                    candidate = replace(candidate, role=REJECTED)
                    candidates.append(candidate)
                    rejections.append(Rejection(
                        generation=generation, parent_id=parent.id,
                        operation=mutation.operation, payload_hash=digest,
                        reasons=reasons, candidate=candidate,
                        proposal_cost=mutation.cost, evaluation_cost=evaluation.cost))
                    continue
                if explore:
                    candidate = replace(candidate, role=EXPLORATION)
                    exploration.append(candidate)
                else:
                    candidate = replace(candidate, role=ELITE)
                    elites.append(candidate)
                candidates.append(candidate)
                accepted.append(candidate)
                active = candidate
            generation_evaluations.append(evaluations - before)
            if evaluations == before:
                stop_reason = "no_new_evaluations"
                break
            if evaluations >= self.evaluation_budget:
                stop_reason = "budget_exhausted"
                break
        else:
            stop_reason = "depth_exhausted"

        best = min(elites, key=_business_key)
        elite_population = self.select_parents(elites, k)
        population = ((active,) if single_chain else self.select_parents(
            elites, k, exploration if allow_exploration else None))
        return RepairRun(
            mode=mode, initial=initial, best=best, population=population,
            elite_population=elite_population, candidates=tuple(candidates),
            accepted=tuple(accepted), elites=tuple(elites),
            exploration=tuple(exploration), rejections=tuple(rejections),
            evaluations=evaluations, proposal_cost=proposal_cost,
            evaluation_cost=evaluation_cost,
            total_cost=proposal_cost + evaluation_cost,
            generation_evaluations=tuple(generation_evaluations),
            stop_reason=stop_reason)

    def compare(self, initial: Candidate, evaluator: CandidateEvaluator,
                operators: Sequence[MutationOperator], *,
                chain_operators: Sequence[MutationOperator] | None = None,
                allow_exploration: bool = False) -> StrategyComparison:
        population = self.run(initial, evaluator, operators,
                              allow_exploration=allow_exploration)
        single_chain = self.run(initial, evaluator,
                                operators if chain_operators is None else chain_operators,
                                single_chain=True, allow_exploration=allow_exploration)
        population_key = _business_key(population.best)
        chain_key = _business_key(single_chain.best)
        population_better = population_key < chain_key
        winner = ("population" if population_better
                  else "single_chain" if chain_key < population_key else "tie")
        advantage = None
        population_objective = population.best.business_result.objective
        chain_objective = single_chain.best.business_result.objective
        if (population.best.business_result.status == FEASIBLE
                and single_chain.best.business_result.status == FEASIBLE
                and population_objective is not None and chain_objective is not None):
            if initial.business_result.sense == "min":
                advantage = chain_objective - population_objective
            else:
                advantage = population_objective - chain_objective
        return StrategyComparison(
            population=population, single_chain=single_chain,
            population_better=population_better, winner=winner,
            population_advantage=advantage)

    @staticmethod
    def _can_explore(candidate: Candidate, reasons: tuple[str, ...]) -> bool:
        return (candidate.business_result.status == FEASIBLE
                and "new_hard_error" not in reasons
                and set(reasons) <= {"lost_win", "worse_business"})

    @staticmethod
    def _rejection_reasons(candidate: Candidate, parent: Candidate,
                           initial: Candidate, incumbent: Candidate) -> tuple[str, ...]:
        result = candidate.business_result
        reasons = []
        if result.status == UNKNOWN:
            reasons.append("unknown")
        if result.hard_errors - parent.business_result.hard_errors:
            reasons.append("new_hard_error")
        if result.status != UNKNOWN:
            initial_result = initial.business_result
            lost_feasibility = (initial_result.status == FEASIBLE
                                and result.status != FEASIBLE)
            lost_objective = (initial_result.status == FEASIBLE
                              and result.status == FEASIBLE
                              and _business_key(candidate) > _business_key(initial))
            if lost_feasibility or lost_objective:
                reasons.append("lost_win")
            if _business_key(candidate) > _business_key(incumbent):
                reasons.append("worse_business")
        return tuple(reasons)
