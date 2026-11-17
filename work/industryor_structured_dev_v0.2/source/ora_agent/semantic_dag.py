"""Scoped sibling evaluation that preserves the legacy DAG executor contract."""
from __future__ import annotations

import copy

from ora_agent.acceptance import can_accept
from ora_agent.evidence_dag import (
    CandidateNode,
    DagBudget,
    EvidenceDAGExecutor,
    Proposal,
    candidate_digest,
)


class SemanticDAGExecutor(EvidenceDAGExecutor):
    def __init__(self, budget: DagBudget | None = None, stop_on_accept: bool = True):
        super().__init__(budget)
        self.stop_on_accept = stop_on_accept

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
            if solution is None and execution.get("status") is None:
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
            accepted = node in self.dag.accepted()
            if accepted:
                self.dag.mark_done(action_id, "accepted")
                if self.stop_on_accept:
                    self.dag.mark_done(parent_id, "accepted_child")
                    break
            if proposal.done and not accepted:
                self.dag.mark_done(action_id, str(business.get("status", "rejected")))
        if not parent.done and all(self.nodes[child].done for child in parent.children):
            accepted_children = [self.nodes[child] for child in parent.children
                                 if self.nodes[child] in self.dag.accepted()]
            if accepted_children:
                self.dag.mark_done(parent_id, "accepted_children")
            else:
                self.dag.mark_done(parent_id, "no_accepted_child")
        return added
