import pytest

from ora_agent.cleanroom import (
    FAIL,
    NOT_APPLICABLE,
    PASS,
    UNKNOWN,
    AuditCase,
    CleanCheckAsset,
    EvidenceMemory,
    RepairDAG,
    SpecificationAsset,
    TrustController,
    Verdict,
)

DOC = "Machine activation requires nonnegative integer production."
SCOPE = {"dataset": "oragentbench", "family": "manufacturing"}


def integer_check(artifact):
    if artifact.get("missing"):
        return Verdict(UNKNOWN)
    if artifact.get("inactive"):
        return Verdict(NOT_APPLICABLE)
    return Verdict(PASS if float(artifact["x"]).is_integer() else FAIL)


def make_memory():
    memory = EvidenceMemory()
    memory.register_check(CleanCheckAsset("integer_domain", integer_check, SCOPE, "integer production", DOC))
    cases = []
    for index in range(3):
        cases.append(AuditCase(f"clean{index}", {"x": index}, PASS))
        cases.append(AuditCase(f"wrong{index}", {"x": index + 0.5}, FAIL))
    memory.authorize_check("integer_domain", cases)
    return memory


def test_specification_requires_independent_promotion_and_scope():
    memory = EvidenceMemory()
    asset = SpecificationAsset("spec_v1", "use integer production", SCOPE)
    memory.register_specification(asset)
    assert memory.generator_specification(SCOPE) is None
    memory.promote_specification("spec_v1", {"independent_replay": True,
                                             "changed_features_covered": True,
                                             "scope_confirmed": True})
    assert memory.generator_specification(SCOPE) is asset
    assert memory.generator_specification({"dataset": "other"}) is None
    memory.freeze()
    with pytest.raises(RuntimeError):
        memory.register_specification(SpecificationAsset("spec_v2", "new", SCOPE))


def test_check_authorization_and_not_applicable():
    memory = make_memory()
    assert [asset.check_id for asset in memory.authorized_checks(SCOPE)] == ["integer_domain"]
    assert memory.authorized_checks({"dataset": "other"}) == []

    insufficient = EvidenceMemory()
    insufficient.register_check(CleanCheckAsset("integer_domain", integer_check, SCOPE,
                                               "integer production", DOC))
    audit = insufficient.authorize_check("integer_domain", [AuditCase("clean", {"x": 1}, PASS)])
    assert not audit["passed"]
    assert "insufficient_applicable_audit_cases" in audit["reasons"]


def test_targeted_repair_preserves_non_target_checks():
    memory = make_memory()
    memory.register_check(CleanCheckAsset("activation", lambda artifact: Verdict(
        FAIL if artifact.get("bad_activation") else PASS), SCOPE, "activation", DOC))
    cases = [AuditCase(f"clean{i}", {"bad_activation": False}, PASS) for i in range(3)]
    cases += [AuditCase(f"wrong{i}", {"bad_activation": True}, FAIL) for i in range(3)]
    memory.authorize_check("activation", cases)
    controller = TrustController(memory)

    allowed, reasons = controller.repair_allowed(
        SCOPE, "activation", {"integer_domain": PASS, "activation": FAIL},
        {"integer_domain": PASS, "activation": PASS})
    assert allowed, reasons
    rejected, _ = controller.repair_allowed(
        SCOPE, "activation", {"integer_domain": PASS, "activation": FAIL},
        {"integer_domain": FAIL, "activation": PASS})
    assert not rejected
    rejected, _ = controller.repair_allowed(
        SCOPE, "activation", {"integer_domain": PASS, "activation": FAIL},
        {"integer_domain": PASS, "activation": UNKNOWN})
    assert not rejected
    assert controller.final_accept(SCOPE, {"integer_domain": PASS, "activation": PASS})[0]
    downstream, reasons = controller.repair_allowed(
        SCOPE, "activation", {"integer_domain": FAIL, "activation": FAIL},
        {"integer_domain": PASS, "activation": PASS})
    assert downstream, reasons


def test_dag_rejects_duplicate_code_and_supports_rollback():
    controller = TrustController(make_memory())
    dag = RepairDAG(controller)
    root = dag.add_root("x = 1", {"integer_domain": FAIL})
    child = dag.add_repair(root.node_id, "x = 2", "integer_domain",
                           {"integer_domain": FAIL}, {"integer_domain": PASS}, SCOPE)
    assert child.accepted
    with pytest.raises(ValueError):
        dag.add_repair(root.node_id, "x = 2", "integer_domain",
                       {"integer_domain": FAIL}, {"integer_domain": PASS}, SCOPE)
    assert dag.rollback(child.node_id) == root.node_id
    assert not child.accepted
