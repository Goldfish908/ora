import pytest

from ora_agent.verification_governance import (
    FAIL,
    PASS,
    UNKNOWN,
    VETO_ENABLED,
    CheckAsset,
    TrustedCase,
    Verdict,
    VerificationGovernor,
    convention_source,
    verbatim_source,
)


def evaluator(artifact):
    return Verdict(PASS) if artifact["ok"] else Verdict(FAIL)


def source():
    return verbatim_source("initial inventory is zero", "The initial inventory is zero for every product.")


def cases():
    return [TrustedCase("clean1", {"ok": True}, PASS), TrustedCase("clean2", {"ok": True}, PASS),
            TrustedCase("wrong1", {"ok": False}, FAIL), TrustedCase("wrong2", {"ok": False}, FAIL)]


def promoted_governor():
    governor = VerificationGovernor(min_clean=2, min_wrong=2)
    governor.register(CheckAsset("inventory", 2, evaluator, source()))
    assert governor.promote("inventory", cases())["passed"] is True
    return governor


def test_new_check_is_hint_only_until_independent_replay():
    governor = VerificationGovernor(min_clean=2, min_wrong=2)
    governor.register(CheckAsset("inventory", 2, evaluator, source()))
    assert governor.checks["inventory"].status == "hint_only"
    assert governor.final_accept({"inventory": PASS}) == (False, ["no_veto_enabled_check"])
    governor.promote("inventory", cases())
    assert governor.checks["inventory"].status == VETO_ENABLED
    assert governor.final_accept({"inventory": PASS}) == (True, [])
    assert governor.final_accept({"inventory": FAIL}) == (False, ["inventory:fail"])
    assert governor.final_accept({"inventory": UNKNOWN}) == (False, ["inventory:unknown"])


def test_false_positive_unknown_and_missing_source_block_veto():
    false_positive = VerificationGovernor(min_clean=2, min_wrong=2)
    false_positive.register(CheckAsset("inventory", 2, lambda artifact: FAIL, source()))
    assert false_positive.promote("inventory", cases())["passed"] is False
    assert false_positive.checks["inventory"].status == "rejected"

    def sometimes_unknown(artifact):
        return UNKNOWN if artifact.get("error") else evaluator(artifact)

    unknown = VerificationGovernor(min_clean=2, min_wrong=2)
    unknown.register(CheckAsset("inventory", 2, sometimes_unknown, source()))
    unknown_cases = cases()
    unknown_cases[0].artifact["error"] = True
    audit = unknown.promote("inventory", unknown_cases)
    assert audit["passed"] is False and "unknown_on_trusted_cases" in audit["reasons"]

    missing = VerificationGovernor(min_clean=2, min_wrong=2)
    missing.register(CheckAsset("inventory", 2, evaluator,
                                verbatim_source("not in question", "actual question")))
    assert missing.promote("inventory", cases())["passed"] is False
    assert missing.checks["inventory"].status == "rejected"


def test_low_detection_cannot_gain_veto_by_never_firing():
    governor = VerificationGovernor(min_clean=2, min_wrong=2)
    governor.register(CheckAsset("inventory", 2, lambda artifact: PASS, source()))
    audit = governor.promote("inventory", cases())
    assert audit["passed"] is False
    assert "detection_below_threshold" in audit["reasons"]


def test_validated_convention_requires_independent_registry_evidence():
    valid = convention_source("inventory_v1", "a" * 64, True)
    invalid = convention_source("inventory_v1", "a" * 64, False)
    governor = VerificationGovernor(min_clean=2, min_wrong=2)
    governor.register(CheckAsset("inventory", 2, evaluator, valid))
    assert governor.promote("inventory", cases())["passed"] is True
    other = VerificationGovernor(min_clean=2, min_wrong=2)
    other.register(CheckAsset("inventory", 2, evaluator, invalid))
    assert other.promote("inventory", cases())["passed"] is False


def test_layered_repair_requires_every_higher_verdict_unchanged():
    governor = promoted_governor()
    assert governor.repair_allowed(1, {"inventory": PASS}, {"inventory": PASS}) == (True, [])
    allowed, reasons = governor.repair_allowed(1, {"inventory": PASS}, {"inventory": FAIL})
    assert not allowed and "higher_check_changed:inventory:pass->fail" in reasons
    allowed, reasons = governor.repair_allowed(1, {"inventory": FAIL}, {"inventory": PASS})
    assert not allowed and "higher_check_changed:inventory:fail->pass" in reasons
    assert governor.repair_allowed(2, {"inventory": FAIL}, {"inventory": PASS}) == (True, [])
    assert governor.final_accept({"inventory": PASS}) == (True, [])


def test_freeze_prevents_registry_mutation_and_retirement_removes_check():
    governor = promoted_governor()
    governor.retire("inventory", "development counterexample")
    assert governor.evaluate({"ok": False}) == {}
    with pytest.raises(ValueError):
        governor.retire("inventory", "second retirement")
    governor.freeze()
    with pytest.raises(RuntimeError, match="frozen"):
        governor.register(CheckAsset("new", 1, evaluator, source()))
    with pytest.raises(RuntimeError, match="frozen"):
        governor.promote("inventory", cases())
