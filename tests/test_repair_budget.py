from ora_agent.repair_controller import BudgetPolicy, FailureKind, ProgressController


def audit(rules, status="ok", reason=None, unknown=None):
    return {"status": status, "fired": bool(rules), "reason": reason,
            "violations": [{"rule": rule, "delta": delta} for rule, delta in rules],
            "unknown_evidence": unknown or [], "rejected": []}


def test_lower_violation_delta_is_progress_and_keeps_local_patch():
    controller = ProgressController()
    first = controller.decide("code_v1", {}, audit([("capacity", 10)]), remaining=3)
    assert first.action == "local_patch"
    controller.record(first, "code_v2")
    second = controller.decide("code_v2", {}, audit([("capacity", 4)]), remaining=2)
    assert second.action == "local_patch"
    assert second.reason == "evidence_improved"
    assert controller.no_progress_count == 0
    assert controller.evidence_improved_count == 1


def test_new_error_after_local_patch_switches_candidate_and_stops_on_recurrence():
    controller = ProgressController()
    first = controller.decide("code_v1", {}, audit([("capacity", 10)]), remaining=3)
    controller.record(first, "code_v2")
    second = controller.decide("code_v2", {}, audit([("domain", 1)]), remaining=2)
    assert second.action == "regenerate"
    assert second.reason == "new_error_after_local_patch"
    assert controller.new_error_count == 1
    controller.record(second, "code_v3")
    third = controller.decide("code_v3", {}, audit([("domain", 1)]), remaining=1)
    assert third.action == "stop"
    assert third.reason == "new_error_after_regenerate"


def test_exact_duplicate_action_is_rejected_for_complex_failure():
    controller = ProgressController()
    problem = [("A", 2), ("B", 1)]
    first = controller.decide("code_v1", {}, audit(problem), remaining=3)
    controller.record(first, "code_v2")
    second = controller.decide("code_v2", {}, audit(problem), remaining=2)
    assert second.action == "regenerate"
    controller.record(second, "code_v2")
    third = controller.decide("code_v2", {}, audit(problem), remaining=1)
    assert third.action == "stop"
    assert third.reason == "duplicate_action"


def test_complex_budget_allows_one_more_regeneration_then_stops():
    controller = ProgressController()
    problem = [("A", 2), ("B", 1)]
    code = "code_v1"
    first = controller.decide(code, {}, audit(problem), remaining=3)
    controller.record(first, "code_v2")
    second = controller.decide("code_v2", {}, audit(problem), remaining=2)
    controller.record(second, "code_v3")
    third = controller.decide("code_v3", {}, audit(problem), remaining=1)
    assert third.action == "regenerate"
    controller.record(third, "code_v4")
    fourth = controller.decide("code_v4", {}, audit(problem), remaining=1)
    assert fourth.action == "stop"
    assert fourth.reason == "budget_exhausted_for_semantic_complex"


def test_missing_data_path_requires_clarification_not_model_patch():
    controller = ProgressController()
    result = controller.decide(
        "code", {}, audit([], status="unknown", reason="missing_data",
                          unknown=[{"detail": "missing path: supply_1"}]), remaining=3)
    assert result.action == "acquire_evidence"
    assert result.reason == "needs_clarification"
    assert result.failure_kind == FailureKind.UNKNOWN
    assert controller.trace() == []


def test_constraint_explosion_only_allows_one_new_candidate():
    controller = ProgressController()
    problem = [(f"R{i}", i + 1) for i in range(8)]
    first = controller.decide("code_v1", {}, audit(problem), remaining=3)
    assert first.action == "regenerate"
    assert first.failure_kind == FailureKind.CONSTRAINT_EXPLOSION
    controller.record(first, "code_v2")
    second = controller.decide("code_v2", {}, audit(problem), remaining=2)
    assert second.action == "stop"
    assert second.reason == "constraint_complexity_exceeded"


def test_custom_violation_threshold_and_execution_budget_are_explicit():
    controller = ProgressController(BudgetPolicy(violation_explosion_threshold=2))
    problem = [("A", 2), ("B", 1)]
    result = controller.decide("code", {}, audit(problem), remaining=3)
    assert result.failure_kind == FailureKind.CONSTRAINT_EXPLOSION
    assert controller.budget.execution == 2
    assert controller.budget.api == 1


def test_repeated_precedence_family_is_not_constraint_explosion():
    controller = ProgressController()
    problem = [(f"job_precedence:p{i}", i) for i in range(1, 13)]
    result = controller.decide("code_v1", {}, audit(problem), remaining=3)
    assert result.failure_kind == FailureKind.SEMANTIC_COMPLEX
    assert result.action == "local_patch"
