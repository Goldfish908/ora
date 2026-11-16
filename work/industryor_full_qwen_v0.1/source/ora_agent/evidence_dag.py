"""Evidence-gated candidate DAG with snapshots, bounded expansion and real rollback."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field

from ora_agent.acceptance import can_accept


@dataclass
class CandidateNode:
    node_id: str
    candidate_hash: str
    parent_id: str | None
    action: str
    binding_sha256: str | None
    binding_status: str
    execution: dict
    business_audit: dict
    solver_runs: int = 0
    llm_calls: int = 0
    done: bool = True
    children: list[str] = field(default_factory=list)
    depth: int = 0
    snapshot: dict | str | None = None
    candidate_kind: str = "dvsa_model"
    stop_reason: str | None = None


@dataclass(frozen=True)
class DagBudget:
    max_nodes: int = 8
    max_depth: int = 2
    max_solver_runs: int = 4
    max_llm_calls: int = 0


@dataclass(frozen=True)
class Proposal:
    action: str
    candidate: dict | str
    candidate_kind: str
    execute: object
    business_audit: object
    binding_sha256: str | None = None
    binding_audit: object | None = None
    binding_status: str = "unvalidated"
    solver_runs: int = 1
    llm_calls: int = 0
    done: bool = True


def candidate_digest(candidate, kind: str) -> str:
    if kind == "pyscipopt_code":
        if not isinstance(candidate, str):
            raise TypeError("PySCIPOpt candidate must be source text")
        return hashlib.sha256(candidate.encode()).hexdigest()
    if kind == "dvsa_model":
        return hashlib.sha256(json.dumps(candidate, sort_keys=True, ensure_ascii=False,
                                         allow_nan=False).encode()).hexdigest()
    raise ValueError(f"unsupported candidate kind: {kind}")


class EvidenceDAG:
    def __init__(self):
        self.nodes: dict[str, CandidateNode] = {}
        self.events: list[dict] = []

    def add(self, node: CandidateNode) -> None:
        if node.node_id in self.nodes:
            raise ValueError(f"duplicate node id: {node.node_id}")
        if node.parent_id is not None:
            if node.parent_id not in self.nodes:
                raise ValueError(f"missing parent: {node.parent_id}")
            parent = self.nodes[node.parent_id]
            parent.children.append(node.node_id)
            node.depth = parent.depth + 1
        if any(existing.candidate_hash == node.candidate_hash
               and existing.action == node.action
               and existing.binding_sha256 == node.binding_sha256
               for existing in self.nodes.values()):
            raise ValueError("duplicate candidate/action/binding branch")
        self.nodes[node.node_id] = node

    def accepted(self) -> list[CandidateNode]:
        return [node for node in self.nodes.values()
                if node.binding_status == "validated"
                and node.execution.get("status", node.execution.get("solver_status")) == "optimal"
                and node.business_audit.get("business_correct") is True]

    def negative_branches(self) -> list[CandidateNode]:
        accepted_ids = {node.node_id for node in self.accepted()}
        return [node for node in self.nodes.values() if node.node_id not in accepted_ids]

    def leaves(self) -> list[CandidateNode]:
        return [node for node in self.nodes.values() if not node.children]

    def open_leaves(self) -> list[CandidateNode]:
        return [node for node in self.leaves() if not node.done]

    def finished(self) -> bool:
        return bool(self.nodes) and all(node.done for node in self.leaves())

    def mark_done(self, node_id: str, reason: str) -> None:
        node = self.nodes[node_id]
        node.done = True
        node.stop_reason = reason
        self.events.append({"type": "done", "node_id": node_id, "reason": reason})

    def rollback(self, from_node_id: str, to_node_id: str) -> dict | str | None:
        source = self.nodes[from_node_id]
        target = self.nodes[to_node_id]
        self.mark_done(from_node_id, "rollback_rejected_branch")
        target.done = False
        target.stop_reason = "rollback_resumed"
        event = {"type": "rollback", "from_node_id": from_node_id, "to_node_id": to_node_id,
                 "candidate_hash": target.candidate_hash, "snapshot_restored": True}
        self.events.append(event)
        return copy.deepcopy(target.snapshot)

    def lineage(self, node_id: str) -> list[str]:
        lineage = []
        seen = set()
        current = node_id
        while current is not None:
            if current in seen:
                raise ValueError("cycle in candidate lineage")
            seen.add(current)
            lineage.append(current)
            current = self.nodes[current].parent_id
        return list(reversed(lineage))

    def to_dict(self) -> dict:
        return {
            "nodes": [asdict(node) for node in self.nodes.values()],
            "events": self.events,
            "accepted_node_ids": [node.node_id for node in self.accepted()],
            "negative_node_ids": [node.node_id for node in self.negative_branches()],
            "leaf_node_ids": [node.node_id for node in self.leaves()],
            "finished": self.finished(),
            "score_based_pruning": False,
            "total_solver_runs": sum(node.solver_runs for node in self.nodes.values()),
            "total_llm_calls": sum(node.llm_calls for node in self.nodes.values()),
        }


class EvidenceDAGExecutor:
    def __init__(self, budget: DagBudget | None = None):
        self.budget = budget or DagBudget()
        self.dag = EvidenceDAG()

    @property
    def nodes(self) -> dict[str, CandidateNode]:
        return self.dag.nodes

    def root(self, candidate, candidate_kind: str, execution: dict, business_audit: dict,
             binding_status: str, binding_sha256: str | None = None) -> CandidateNode:
        node = CandidateNode("root", candidate_digest(candidate, candidate_kind), None,
                             "initial", binding_sha256, binding_status, execution,
                             business_audit, solver_runs=0, llm_calls=0, done=False,
                             snapshot=copy.deepcopy(candidate), candidate_kind=candidate_kind)
        self.dag.add(node)
        return node

    def expand(self, parent_id: str, proposals: list[Proposal]) -> list[CandidateNode]:
        parent = self.nodes[parent_id]
        if parent.done:
            raise ValueError("cannot expand a done node")
        if parent.depth >= self.budget.max_depth:
            self.dag.mark_done(parent_id, "max_depth")
            return []
        if not proposals:
            self.dag.mark_done(parent_id, "no_actions")
            return []
        added = []
        for proposal in proposals:
            if len(self.nodes) >= self.budget.max_nodes:
                self.dag.mark_done(parent_id, "node_budget")
                break
            if self.dag.to_dict()["total_solver_runs"] + proposal.solver_runs > self.budget.max_solver_runs:
                self.dag.mark_done(parent_id, "solver_budget")
                continue
            if self.dag.to_dict()["total_llm_calls"] + proposal.llm_calls > self.budget.max_llm_calls:
                self.dag.mark_done(parent_id, "llm_budget")
                continue
            try:
                execution = proposal.execute()
            except (ValueError, TypeError, OSError) as exc:
                execution = {"status": "error", "error": f"{type(exc).__name__}: {exc}",
                             "solution": None}
            if isinstance(execution, tuple):
                record, solution = execution
                execution = {**record, "solution": solution}
            execution.setdefault("status", execution.get("solver_status"))
            solution = execution.get("solution")
            if solution is None and execution.get("status") != "error":
                execution["status"] = "no_solution"
            business = (proposal.business_audit(solution) if solution is not None
                        else {"business_correct": False, "status": "no_solution"})
            if proposal.binding_audit is not None:
                binding_record = proposal.binding_audit(solution)
                binding_status = "validated" if can_accept(binding_record, "accepted") else "rejected"
            else:
                binding_status = proposal.binding_status
            action_id = f"{parent_id}/{proposal.action}:{len(parent.children)}"
            node = CandidateNode(
                action_id, candidate_digest(proposal.candidate, proposal.candidate_kind), parent_id,
                proposal.action, proposal.binding_sha256, binding_status, execution, business,
                solver_runs=proposal.solver_runs, llm_calls=proposal.llm_calls, done=proposal.done,
                snapshot=copy.deepcopy(proposal.candidate), candidate_kind=proposal.candidate_kind)
            self.dag.add(node)
            added.append(node)
            self.dag.events.append({"type": "candidate_evaluated", "node_id": action_id,
                                    "parent_id": parent_id, "action": proposal.action,
                                    "candidate_hash": node.candidate_hash})
            if node in self.dag.accepted():
                self.dag.mark_done(action_id, "accepted")
                self.dag.mark_done(parent_id, "accepted_child")
                break
            if proposal.done:
                self.dag.mark_done(action_id, str(business.get("status", "rejected")))
        if not parent.done and all(self.nodes[child].done for child in parent.children):
            self.dag.mark_done(parent_id, "no_accepted_child")
        return added

    def rollback(self, from_node_id: str, to_node_id: str):
        return self.dag.rollback(from_node_id, to_node_id)
