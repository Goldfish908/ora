from __future__ import annotations

import copy
import json

import pytest

from ora_agent.federated_skill_candidate import (
    CONTROL_SOURCE,
    DEV_TASKS,
    GAPCHECK_TASKS,
    METHOD_ID,
    TREATMENT_SOURCE,
    audit_candidate,
    load_source_audit,
    prepare_candidate,
    promotion_gate_allows,
)
from ora_agent.skill_assets import CANDIDATE, REJECTED, SkillRegistry
from scripts.federated_skill_audit import run


@pytest.fixture()
def source():
    return load_source_audit()


@pytest.fixture()
def bundle(source):
    return prepare_candidate(source)


def test_method_level_asset_has_complete_scope_and_real_cost(bundle):
    asset = bundle.asset
    assert asset.method_id == METHOD_ID == "federated_sub_milp_v0.1"
    assert asset.version == "0.1"
    assert asset.trigger_signature["asset_level"] == "method"
    assert asset.status == CANDIDATE
    assert asset.task_coverage == {"dev": DEV_TASKS, "gapcheck": GAPCHECK_TASKS}
    assert asset.required_seeds == (20261123,)
    for field in (
        "required_inputs", "dataset_scope", "domain_scope", "api_scope", "schema_scope",
        "operations", "allowed_edits", "invariants", "forbidden_actions",
        "positive_examples", "negative_examples", "near_miss_examples",
        "ambiguous_examples", "out_of_scope_examples",
    ):
        assert getattr(asset, field), field
    assert asset.code_sha256 == bundle.source["implementation_sha256"][TREATMENT_SOURCE]
    assert asset.baseline_implementation_sha256 == (
        bundle.source["implementation_sha256"][CONTROL_SOURCE])
    assert asset.baseline_implementation_sha256 != asset.code_sha256
    expected_search = sum(
        pair["treatment"]["cost"]["search_seconds"] for pair in bundle.pairs) / 3
    expected_total = sum(
        pair["treatment"]["cost"]["total_seconds"] for pair in bundle.pairs) / 3
    assert asset.cost["mean_search_seconds_across_3_predeclared_scenarios"] == pytest.approx(
        expected_search)
    assert asset.cost["mean_total_seconds_across_3_predeclared_scenarios"] == pytest.approx(
        expected_total)
    assert asset.cost["llm_calls"] == 0


def test_real_pairs_recompute_official_records_and_keep_clean_separate(bundle):
    keys = {(row["split"], row["task_id"], row["seed"])
            for row in bundle.evidence["records"]}
    assert keys == {
        ("dev", "duplicate_client", 20261123),
        ("dev", "stream_minimums", 20261123),
        ("gapcheck", "all_budgets", 20261123),
    }
    assert bundle.clean_control["scenario"] == "clean_control"
    assert clean_key_not_in_records(bundle.evidence["records"])
    for pair in [*bundle.pairs, bundle.clean_control]:
        assert pair["checks"]["same_initial_root"] is True
        assert pair["checks"]["official_records_recomputed"] is True
        assert pair["checks"]["frozen_artifacts_verified"] is True
        assert pair["checks"]["costs_reconciled"] is True
        assert pair["control"]["initial_artifact_sha256"] == pair["initial_sha256"]
        assert pair["treatment"]["initial_artifact_sha256"] == pair["initial_sha256"]
        assert pair["control"]["implementation_sha256"] == (
            bundle.asset.baseline_implementation_sha256)
        assert pair["treatment"]["implementation_sha256"] == bundle.asset.code_sha256
        assert pair["control"]["evaluator_sha256"] == bundle.asset.evaluator_sha256
        assert pair["treatment"]["evaluator_sha256"] == bundle.asset.evaluator_sha256
        assert pair["control"]["cost"]["ledger_total_seconds"] == pytest.approx(
            pair["control"]["cost"]["search_seconds"])
        assert pair["treatment"]["cost"]["ledger_total_seconds"] == pytest.approx(
            pair["treatment"]["cost"]["search_seconds"])
    assert bundle.provenance["official_records_recomputed"] == 8
    assert bundle.provenance["frozen_final_artifacts_verified"] == 8


def clean_key_not_in_records(records):
    return all(row["task_id"] != "clean_control" for row in records)


def test_real_registry_rejects_zero_gained_true_and_does_not_promote(bundle):
    audit = audit_candidate(bundle)
    assert audit["decision"]["promoted"] is False
    assert audit["decision"]["status"] == REJECTED
    assert audit["registry"]["dev"]["passed"] is False
    assert audit["registry"]["dev"]["layers"]["dev"]["gained_true"] == 0
    assert audit["registry"]["full_replay"]["layers"]["gapcheck"]["gained_true"] == 0
    assert audit["registry"]["promotion_attempted"] is False
    assert audit["registry"]["selectable_asset_ids"] == []
    assert any("no_gained_true" in reason for reason in audit["decision"]["reasons"])
    assert any("cross_task_evidence_missing" in reason for reason in audit["decision"]["reasons"])
    assert audit["coverage"]["distinct_problem_count"] == 1
    assert audit["coverage"]["cross_task_evidence"] is False
    assert audit["coverage"]["independent_gapcheck"] is False
    assert audit["scoped_findings"]["scope_limited_quality_and_objective_evidence"] is True
    assert audit["scoped_findings"]["search_cost_not_worse_in_all_scenarios"] is False
    assert audit["scoped_findings"]["equal_evaluation_budget"] is False
    assert audit["scoped_findings"]["cross_task_superiority_supported"] is False


def test_clean_control_is_a_non_regression_check_not_a_repair_gain(bundle):
    clean = bundle.clean_control
    assert clean["split"] == "clean_control"
    assert clean["control"]["unchanged"] is True
    assert clean["treatment"]["unchanged"] is False
    assert clean["checks"]["both_official_true"] is True
    assert clean["checks"]["gained_true"] is False
    assert clean["checks"]["lost_true"] is False
    assert clean["checks"]["quality_not_worse"] is True
    assert clean["checks"]["objective_not_worse"] is True
    audit = audit_candidate(bundle)
    assert audit["scoped_findings"]["clean_control_preserved"] is True
    assert len(audit["paired_evidence"]["records"]) == 3


def test_source_official_metric_tampering_is_rejected(source):
    changed = copy.deepcopy(source)
    changed["scenarios"][0]["arms"]["single"]["official"]["quality"] += 1.0
    with pytest.raises(ValueError, match="official metric mismatch"):
        prepare_candidate(changed)


def test_different_arm_roots_are_rejected(source):
    changed = copy.deepcopy(source)
    changed["scenarios"][0]["arms"]["single"]["initial_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="same initial root"):
        prepare_candidate(changed)


def test_unreconciled_cost_is_rejected(source):
    changed = copy.deepcopy(source)
    changed["scenarios"][0]["arms"]["single"]["total_search_seconds"] += 1.0
    with pytest.raises(ValueError, match="cost"):
        prepare_candidate(changed)


def test_required_task_seed_pairs_cannot_be_dropped(bundle):
    registry = SkillRegistry()
    registry.propose(bundle.asset)
    records = [copy.deepcopy(row) for row in bundle.evidence["records"]
               if row["split"] == "dev"]
    records.pop()
    report = registry.validate(bundle.asset.asset_id, {"schema_version": 1, "records": records})
    assert report["passed"] is False
    assert any("missing_pair" in reason for reason in report["reasons"])
    assert bundle.asset.status == REJECTED


def test_cross_task_gate_blocks_promotion_even_if_dev_could_pass():
    scope = {"cross_task_evidence": False, "independent_gapcheck": False}
    assert promotion_gate_allows({"passed": True}, scope) is False
    assert promotion_gate_allows({"passed": False}, {
        "cross_task_evidence": True, "independent_gapcheck": True}) is False
    assert promotion_gate_allows({"passed": True}, {
        "cross_task_evidence": True, "independent_gapcheck": True}) is True


def test_real_audit_writes_standalone_json_and_report(tmp_path):
    out = tmp_path / "federated_skill_audit_v0.1"
    audit = run(out=out)
    saved = json.loads((out / "audit.json").read_text(encoding="utf-8"))
    report = (out / "report.md").read_text(encoding="utf-8")
    assert saved["schema_version"] == "federated_skill_audit_v0.1"
    assert saved["decision"]["promoted"] is False
    assert saved["asset"]["asset_id"] == "federated_sub_milp_v0.1:0.1"
    assert saved["repository_head"]
    assert "结论：不晋升" in report
    assert "dev 为 0/2" in report
    assert "gapcheck 为 0/1" in report
    assert "Clean control" in report
    assert "后续仍缺证据" in report
