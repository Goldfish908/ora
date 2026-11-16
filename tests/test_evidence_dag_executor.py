import pytest

from ora_agent.evidence_dag import DagBudget, EvidenceDAGExecutor, Proposal
from ora_agent.semantic_dag import SemanticDAGExecutor


def clean(_solution):
    return {"status": "ok", "fired": False, "unknown_evidence": [], "rejected": []}


def accepted_proposal(candidate):
    return Proposal("patch", candidate, "dvsa_model",
                    lambda: {"status": "optimal", "solution": {"x": 1}},
                    lambda solution: {"business_correct": True}, binding_audit=clean)


def test_executor_accepts_only_validated_optimal_business_branch():
    executor = EvidenceDAGExecutor()
    root = executor.root({"x": 0}, "dvsa_model", {"status": "optimal", "solution": {"x": 0}},
                         {"business_correct": False}, "rejected")
    added = executor.expand(root.node_id, [accepted_proposal({"x": 1})])
    assert len(added) == 1
    assert added[0].depth == 1
    assert added[0].snapshot == {"x": 1}
    assert executor.dag.accepted()[0].node_id == added[0].node_id
    assert executor.dag.finished() is True
    assert executor.dag.lineage(added[0].node_id) == ["root", added[0].node_id]
    assert executor.dag.to_dict()["total_solver_runs"] == 1


def test_real_rollback_reopens_parent_and_preserves_rejected_snapshot():
    executor = EvidenceDAGExecutor()
    root = executor.root({"objective": 1}, "dvsa_model",
                         {"status": "optimal", "solution": {"objective": 1}},
                         {"business_correct": False}, "rejected")
    bad = Proposal("bad_patch", {"objective": 2}, "dvsa_model",
                   lambda: {"status": "optimal", "solution": {"objective": 2}},
                   lambda solution: {"business_correct": False}, binding_status="rejected")
    failed = executor.expand(root.node_id, [bad])[0]
    restored = executor.rollback(failed.node_id, root.node_id)
    assert root.done is False
    assert restored is not root.snapshot
    assert restored == {"objective": 1}
    restored["objective"] = 3
    assert root.snapshot == {"objective": 1}
    good = accepted_proposal(restored)
    succeeded = executor.expand(root.node_id, [good])[0]
    assert executor.dag.accepted()[0].node_id == succeeded.node_id
    assert failed.node_id in executor.dag.to_dict()["negative_node_ids"]
    assert failed.snapshot == {"objective": 2}
    assert any(event["type"] == "rollback" for event in executor.dag.events)


def test_budgets_and_done_nodes_prevent_unbounded_expansion():
    executor = EvidenceDAGExecutor(DagBudget(max_nodes=1))
    root = executor.root({"x": 0}, "dvsa_model", {}, {"business_correct": False}, "rejected")
    assert executor.expand(root.node_id, [accepted_proposal({"x": 1})]) == []
    assert root.stop_reason == "node_budget"
    with pytest.raises(ValueError, match="done node"):
        executor.expand(root.node_id, [])

    executor = EvidenceDAGExecutor(DagBudget(max_depth=0))
    root = executor.root({"x": 0}, "dvsa_model", {}, {"business_correct": False}, "rejected")
    assert executor.expand(root.node_id, []) == []
    assert root.stop_reason == "max_depth"

    executor = EvidenceDAGExecutor(DagBudget(max_solver_runs=0))
    root = executor.root({"x": 0}, "dvsa_model", {}, {"business_correct": False}, "rejected")
    assert executor.expand(root.node_id, [accepted_proposal({"x": 1})]) == []
    assert root.stop_reason == "solver_budget"
    assert executor.dag.to_dict()["total_solver_runs"] == 0


def test_execution_failure_is_preserved_not_accepted():
    def fail():
        raise ValueError("invalid model")

    executor = EvidenceDAGExecutor()
    root = executor.root({"x": 0}, "dvsa_model", {}, {"business_correct": False}, "rejected")
    proposal = Proposal("bad_execute", {"x": 1}, "dvsa_model", fail,
                        lambda solution: {"business_correct": True}, binding_status="validated")
    failed = executor.expand(root.node_id, [proposal])[0]
    assert failed.execution["status"] == "error"
    assert failed.business_audit["business_correct"] is False
    assert executor.dag.accepted() == []
    assert executor.dag.to_dict()["score_based_pruning"] is False


def test_development_mode_evaluates_sibling_branches_and_selects_cheapest_accepted():
    executor = SemanticDAGExecutor(DagBudget(max_llm_calls=1, max_solver_runs=3),
                                   stop_on_accept=False)
    root = executor.root({"x": 0}, "dvsa_model", {"status": "optimal", "solution": {"x": 0}},
                         {"business_correct": False}, "rejected")
    local = Proposal("local_patch", {"x": 1}, "dvsa_model",
                     lambda: {"status": "optimal", "solution": {"x": 1}},
                     lambda solution: {"business_correct": True}, binding_audit=clean,
                     solver_runs=1, llm_calls=0)
    regenerated = Proposal("regenerate", {"x": 2}, "dvsa_model",
                           lambda: {"status": "optimal", "solution": {"x": 2}},
                           lambda solution: {"business_correct": True}, binding_audit=clean,
                           solver_runs=1, llm_calls=1)
    added = executor.expand(root.node_id, [local, regenerated])
    assert len(added) == 2
    assert [node.parent_id for node in added] == [root.node_id, root.node_id]
    assert len(executor.dag.accepted()) == 2
    selected = min(executor.dag.accepted(),
                   key=lambda node: (node.llm_calls, node.solver_runs, node.depth, node.node_id))
    assert selected.action == "local_patch"
    assert root.stop_reason == "accepted_children"
    assert executor.dag.to_dict()["total_llm_calls"] == 1
    assert executor.dag.to_dict()["total_solver_runs"] == 2
    assert sum(event["type"] == "candidate_evaluated" for event in executor.dag.events) == 2
