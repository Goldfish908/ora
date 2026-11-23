import copy
import hashlib
import json

import pytest

from ora_agent.skill_assets import (
    CANDIDATE,
    DEV_PASSED,
    PROMOTED,
    REJECTED,
    RETIRED,
    SkillAsset,
    SkillRegistry,
    load_registry,
    replay_paired_evidence,
)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def make_asset(method_id="export_rebind", version="1.0", min_gained_true=None):
    if min_gained_true is None:
        min_gained_true = {"dev": 1, "gapcheck": 1}
    return SkillAsset(
        method_id=method_id,
        version=version,
        trigger_signature={"event": "missing_semantic_export", "language": "python"},
        required_inputs=("problem", "candidate_code", "semantic_names"),
        dataset_scope=("industryor-dev", "industryor-gapcheck"),
        domain_scope=("manufacturing",),
        api_scope=("pyscipopt>=5",),
        schema_scope=("semantic-dag-v1",),
        operations=("bind_names", "export_solution"),
        allowed_edits=("aliases", "export_block"),
        invariants=("objective_unchanged", "constraints_unchanged"),
        forbidden_actions=("invent_objective", "delete_constraint"),
        positive_examples=({"task": "dev-1", "alias": "production"},),
        negative_examples=({"task": "bad", "edit": "invented objective"},),
        near_miss_examples=({"task": "near", "missing": "canonical name"},),
        ambiguous_examples=({"task": "ambiguous", "resolution": "UNKNOWN"},),
        out_of_scope_examples=({"task": "other-domain", "domain": "routing"},),
        code="def rebind(candidate, aliases):\n    return candidate.bind(aliases)\n",
        text="Rebind verified semantic names; never invent business semantics.",
        baseline_implementation_sha256=digest("baseline-without-skill-v1"),
        evaluator_sha256=digest("independent-evaluator-v1"),
        task_coverage={"dev": ("dev-1", "dev-2"), "gapcheck": ("gap-1",)},
        required_seeds=(11, 29),
        cost={"llm_calls": 0, "seconds": 1.25},
        min_gained_true=min_gained_true,
    )


def outcome(asset, true_correct, proxy_correct=None, status="OK", arm="treatment"):
    implementation = (asset.baseline_implementation_sha256
                      if arm == "control" else asset.code_sha256)
    return {
        "initial_artifact_sha256": digest("same-initial-artifact"),
        "implementation_sha256": implementation,
        "evaluator_sha256": asset.evaluator_sha256,
        "status": status,
        "true_correct": true_correct,
        "proxy_correct": true_correct if proxy_correct is None else proxy_correct,
    }


def make_evidence(asset):
    records = []
    for split in ("dev", "gapcheck"):
        for task_id in asset.task_coverage[split]:
            for seed in asset.required_seeds:
                control_true = seed == 11
                records.append({
                    "split": split,
                    "task_id": task_id,
                    "seed": seed,
                    "control": outcome(asset, control_true, arm="control"),
                    "treatment": outcome(asset, True),
                })
    return {"schema_version": 1, "records": records}


def dev_evidence(asset, evidence=None):
    evidence = make_evidence(asset) if evidence is None else evidence
    return {**evidence, "records": [row for row in evidence["records"]
                                    if row["split"] == "dev"]}


def registry_at(asset, status):
    registry = SkillRegistry()
    registry.propose(asset)
    evidence = make_evidence(asset)
    if status in {DEV_PASSED, PROMOTED}:
        assert registry.validate(asset.asset_id, dev_evidence(asset, evidence))["passed"]
    if status == PROMOTED:
        assert registry.promote(asset.asset_id, evidence)["passed"]
    return registry, evidence


def assert_reason(report, reason):
    assert not report["passed"]
    assert any(reason in item for item in report["reasons"]), report["reasons"]


def activation_context(asset, **changes):
    context = {
        "trigger": dict(asset.trigger_signature),
        "dataset": asset.dataset_scope[0],
        "domain": asset.domain_scope[0],
        "api": asset.api_scope[0],
        "schema": asset.schema_scope[0],
    }
    context.update(changes)
    return context


def test_asset_metadata_and_raw_evidence_lifecycle():
    asset = make_asset()
    registry, evidence = registry_at(asset, CANDIDATE)
    assert asset.asset_id == "export_rebind:1.0"
    assert asset.code_sha256 == digest(asset.code)
    assert asset.text_sha256 == digest(asset.text)
    assert asset.baseline_implementation_sha256 != asset.code_sha256
    assert asset.root_id == asset.asset_id
    assert asset.status == CANDIDATE
    for row in evidence["records"]:
        assert row["control"]["implementation_sha256"] == asset.baseline_implementation_sha256
        assert row["treatment"]["implementation_sha256"] == asset.code_sha256
        assert row["control"]["evaluator_sha256"] == row["treatment"]["evaluator_sha256"]

    evidence["metrics"] = {"lost_true": 999, "new_phantom": 999, "UNKNOWN": 999}
    dev_report = registry.validate(asset.asset_id, dev_evidence(asset, evidence))
    assert dev_report["passed"]
    assert dev_report["metrics_used"] is False
    assert dev_report["layers"]["dev"]["pairs"] == 4
    assert dev_report["layers"]["dev"]["gained_true"] == 2
    assert asset.status == DEV_PASSED
    assert asset.dev_evidence_sha256 == dev_report["dev_evidence_sha256"]

    promotion = registry.promote(asset.asset_id, evidence)
    assert promotion["passed"], promotion["reasons"]
    assert promotion["layers"]["gapcheck"]["pairs"] == 2
    assert promotion["layers"]["gapcheck"]["gained_true"] == 1
    assert not promotion["gapcheck_failed"]
    assert asset.status == PROMOTED
    assert asset.promotion_evidence_sha256 == promotion["evidence_sha256"]
    assert [entry["to"] for entry in asset.state_history] == [
        CANDIDATE, DEV_PASSED, PROMOTED]

    selected = registry.select(trigger={"event": "missing_semantic_export"},
                               dataset="industryor-dev", domain="manufacturing",
                               api="pyscipopt>=5", schema="semantic-dag-v1")
    assert selected == [asset]
    assert registry.select(dataset="other-dataset") == []
    activation = registry.activate(asset.asset_id, task_id="deployment-1", seed=101,
                                   **activation_context(asset))
    assert activation["cost"] == asset.cost
    assert activation["dataset"] == asset.dataset_scope[0]
    assert asset.activation_log == [activation]


@pytest.mark.parametrize("case,expected_reason", [
    ("lost_true", "lost_true"),
    ("new_phantom", "new_phantom"),
    ("unknown", "UNKNOWN"),
    ("missing_arm", "missing_pair"),
    ("initial_mismatch", "initial_artifact"),
    ("baseline_mismatch", "baseline_implementation_hash"),
    ("implementation_mismatch", "implementation_hash"),
    ("evaluator_mismatch", "evaluator_hash"),
    ("missing_seed", "seed_coverage"),
    ("wrong_task", "task_coverage"),
])
def test_dev_negative_controls_reject(case, expected_reason):
    asset = make_asset()
    registry = SkillRegistry()
    registry.propose(asset)
    evidence = dev_evidence(asset)
    row = evidence["records"][0]
    if case == "lost_true":
        row["treatment"] = outcome(asset, False)
    elif case == "new_phantom":
        row["treatment"] = outcome(asset, False, proxy_correct=True)
    elif case == "unknown":
        row["treatment"]["status"] = "UNKNOWN"
    elif case == "missing_arm":
        del row["treatment"]
    elif case == "initial_mismatch":
        row["treatment"]["initial_artifact_sha256"] = digest("different-initial")
    elif case == "baseline_mismatch":
        row["control"]["implementation_sha256"] = asset.code_sha256
    elif case == "implementation_mismatch":
        row["treatment"]["implementation_sha256"] = digest("different-implementation")
    elif case == "evaluator_mismatch":
        row["treatment"]["evaluator_sha256"] = digest("different-evaluator")
    elif case == "missing_seed":
        row["seed"] = None
    elif case == "wrong_task":
        row["task_id"] = "unregistered-task"

    report = registry.validate(asset.asset_id, evidence)
    assert_reason(report, expected_reason)
    assert report["status"] == REJECTED
    assert asset.status == REJECTED
    assert asset.dev_evidence_sha256 is None
    assert asset.state_history[-1]["to"] == REJECTED


@pytest.mark.parametrize("case", ["lost_true", "new_phantom", "unknown", "missing_layer"])
def test_gapcheck_negative_controls_block_promotion(case):
    asset = make_asset()
    registry, evidence = registry_at(asset, DEV_PASSED)
    if case == "missing_layer":
        evidence = dev_evidence(asset, evidence)
    else:
        row = next(row for row in evidence["records"]
                   if row["split"] == "gapcheck" and row["seed"] == 11)
        if case == "lost_true":
            row["treatment"] = outcome(asset, False)
        elif case == "new_phantom":
            row["treatment"] = outcome(asset, False, proxy_correct=True)
        else:
            row["treatment"]["status"] = "UNKNOWN"

    report = registry.promote(asset.asset_id, evidence)
    assert not report["passed"]
    assert report["gapcheck_failed"]
    assert asset.status == REJECTED
    assert asset.promotion_evidence_sha256 is None


def test_missing_dev_task_or_seed_is_a_missing_pair_not_silent_coverage():
    asset = make_asset()
    registry = SkillRegistry()
    registry.propose(asset)
    evidence = dev_evidence(asset)
    evidence["records"].pop()
    report = registry.validate(asset.asset_id, evidence)
    assert_reason(report, "missing_pair")
    assert asset.status == REJECTED


def test_caller_metrics_cannot_hide_raw_regression():
    asset = make_asset()
    registry = SkillRegistry()
    registry.propose(asset)
    evidence = dev_evidence(asset)
    evidence["records"][0]["treatment"] = outcome(asset, False)
    evidence["metrics"] = {"lost_true": 0, "new_phantom": 0, "unknown": 0,
                           "task_coverage": 1.0, "passed": True}
    report = registry.validate(asset.asset_id, evidence)
    assert_reason(report, "lost_true")
    assert report["metrics_used"] is False
    assert asset.status == REJECTED


def test_promotion_replays_the_same_dev_records_that_were_validated():
    asset = make_asset()
    registry, evidence = registry_at(asset, DEV_PASSED)
    changed = next(row for row in evidence["records"]
                   if row["split"] == "dev" and row["seed"] == 29)
    changed["control"] = outcome(asset, True, arm="control")
    report = registry.promote(asset.asset_id, evidence)
    assert_reason(report, "dev_evidence_changed")
    assert asset.status == REJECTED


def test_lifecycle_cannot_skip_dev_or_revalidate_terminal_rejection():
    asset = make_asset()
    registry = SkillRegistry()
    registry.propose(asset)
    with pytest.raises(ValueError, match="only dev_passed"):
        registry.promote(asset.asset_id, make_evidence(asset))
    evidence = dev_evidence(asset)
    evidence["records"][0]["treatment"]["status"] = "UNKNOWN"
    assert not registry.validate(asset.asset_id, evidence)["passed"]
    with pytest.raises(ValueError, match="only candidate"):
        registry.validate(asset.asset_id, dev_evidence(asset))


def test_retirement_is_terminal_and_not_selectable():
    asset = make_asset()
    registry, _ = registry_at(asset, PROMOTED)
    registry.retire(asset.asset_id, "superseded")
    assert asset.status == RETIRED
    assert registry.select() == []
    with pytest.raises(ValueError, match="only promoted, non-retired"):
        registry.activate(asset.asset_id, task_id="deployment-1", **activation_context(asset))
    with pytest.raises(ValueError, match="only promoted"):
        registry.retire(asset.asset_id, "again")
    assert [entry["to"] for entry in asset.state_history] == [
        CANDIDATE, DEV_PASSED, PROMOTED, RETIRED]


def test_revision_has_new_lineage_and_returns_to_dev():
    original = make_asset()
    registry, _ = registry_at(original, PROMOTED)
    registry.activate(original.asset_id, task_id="old-deployment",
                      **activation_context(original))
    revised = registry.revise(original.asset_id, "2.0",
                              text=" revised with a narrower ambiguity rule")
    assert revised.asset_id != original.asset_id
    assert revised.parent_id == original.asset_id
    assert revised.lineage == (original.asset_id,)
    assert revised.root_id == original.asset_id
    assert revised.revision == 1
    assert revised.status == CANDIDATE
    assert revised.activation_log == []
    assert revised.validation_reports == []
    assert revised.dev_evidence_sha256 is None
    assert revised.text_sha256 != original.text_sha256
    assert original.status == PROMOTED
    assert registry.select() == [original]
    with pytest.raises(ValueError, match="only dev_passed"):
        registry.promote(revised.asset_id, make_evidence(revised))

    evidence = make_evidence(revised)
    assert registry.validate(revised.asset_id, dev_evidence(revised, evidence))["passed"]
    assert registry.promote(revised.asset_id, evidence)["passed"]
    registry.retire(original.asset_id, "replaced by 2.0")
    assert registry.select() == [revised]


def test_freeze_hard_fails_every_lifecycle_mutation():
    promoted = make_asset("promoted")
    candidate = make_asset("candidate")
    dev = make_asset("dev")
    registry, evidence = registry_at(promoted, PROMOTED)
    registry.propose(candidate)
    dev_full = make_evidence(dev)
    registry.propose(dev)
    registry.validate(dev.asset_id, dev_evidence(dev, dev_full))
    registry.freeze()

    calls = [
        lambda: registry.propose(make_asset("new")),
        lambda: registry.validate(candidate.asset_id, dev_evidence(candidate)),
        lambda: registry.promote(dev.asset_id, dev_full),
        lambda: registry.retire(promoted.asset_id, "retire"),
        lambda: registry.revise(promoted.asset_id, "2.0"),
    ]
    for call in calls:
        with pytest.raises(RuntimeError, match="frozen"):
            call()
    assert candidate.status == CANDIDATE
    assert dev.status == DEV_PASSED
    assert promoted.status == PROMOTED
    assert registry.select() == [promoted]


def test_read_only_load_preserves_audit_data_and_blocks_writes(tmp_path):
    promoted = make_asset("promoted")
    candidate = make_asset("candidate")
    dev = make_asset("dev")
    registry, _ = registry_at(promoted, PROMOTED)
    registry.propose(candidate)
    registry.propose(dev)
    dev_full = make_evidence(dev)
    registry.validate(dev.asset_id, dev_evidence(dev, dev_full))
    path = tmp_path / "registry.json"
    registry.save(path)
    original_bytes = path.read_bytes()

    loaded = load_registry(path)
    assert loaded.read_only
    assert loaded.select()[0].asset_id == promoted.asset_id
    assert loaded.assets[promoted.asset_id].state_history == promoted.state_history
    calls = [
        lambda: loaded.propose(make_asset("new")),
        lambda: loaded.validate(candidate.asset_id, dev_evidence(candidate)),
        lambda: loaded.promote(dev.asset_id, dev_full),
        lambda: loaded.retire(promoted.asset_id, "retire"),
        lambda: loaded.revise(promoted.asset_id, "2.0"),
        lambda: loaded.activate(promoted.asset_id, task_id="deployment"),
        lambda: loaded.save(tmp_path / "copy.json"),
    ]
    for call in calls:
        with pytest.raises(RuntimeError, match="read-only"):
            call()
    assert path.read_bytes() == original_bytes


def test_read_only_loader_verifies_code_and_text_hashes(tmp_path):
    registry = SkillRegistry()
    asset = make_asset()
    registry.propose(asset)
    path = tmp_path / "registry.json"
    registry.save(path)
    data = json.loads(path.read_text())
    data["assets"][0]["text"] = "tampered instructions"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="text hash mismatch"):
        load_registry(path)


def test_frozen_state_survives_round_trip(tmp_path):
    asset = make_asset()
    registry, _ = registry_at(asset, PROMOTED)
    registry.freeze()
    path = tmp_path / "frozen.json"
    registry.save(path)
    loaded = load_registry(path, read_only=False)
    assert loaded.frozen
    with pytest.raises(RuntimeError, match="frozen"):
        loaded.revise(asset.asset_id, "2.0")


def test_layered_evidence_can_be_supplied_as_dev_and_gapcheck_arrays():
    asset = make_asset()
    registry = SkillRegistry()
    registry.propose(asset)
    records = make_evidence(asset)["records"]
    layered = {
        "dev": [copy.deepcopy(row) for row in records if row["split"] == "dev"],
        "gapcheck": [copy.deepcopy(row) for row in records if row["split"] == "gapcheck"],
    }
    dev_only = {"dev": layered["dev"]}
    assert registry.validate(asset.asset_id, dev_only)["passed"]
    assert registry.promote(asset.asset_id, layered)["passed"]


def test_revision_lineage_round_trip_does_not_depend_on_asset_order(tmp_path):
    original = make_asset("lineage", "2.0")
    registry, _ = registry_at(original, PROMOTED)
    revised = registry.revise(original.asset_id, "10.0", text="new lineage")
    assert revised.asset_id < original.asset_id
    path = tmp_path / "lineage.json"
    registry.save(path)
    loaded = load_registry(path)
    assert loaded.assets[revised.asset_id].parent_id == original.asset_id
    assert loaded.assets[revised.asset_id].lineage == (original.asset_id,)


def remove_gained_true(asset, evidence, split):
    for row in evidence["records"]:
        if row["split"] == split:
            row["control"] = outcome(asset, True, arm="control")
            row["treatment"] = outcome(asset, True)


@pytest.mark.parametrize("split", ["dev", "gapcheck"])
def test_zero_gained_true_is_rejected_even_without_regressions(split):
    asset = make_asset()
    registry, evidence = registry_at(asset, DEV_PASSED if split == "gapcheck" else CANDIDATE)
    remove_gained_true(asset, evidence, split)
    evidence["metrics"] = {"gained_true": 999, "passed": True}
    if split == "dev":
        report = registry.validate(asset.asset_id, dev_evidence(asset, evidence))
    else:
        report = registry.promote(asset.asset_id, evidence)
    assert_reason(report, "no_gained_true")
    layer = report["layers"][split]
    assert layer["gained_true"] == 0
    assert layer["lost_true"] == 0
    assert layer["new_phantom"] == 0
    assert layer["unknown"] == 0
    assert report["metrics_used"] is False
    assert asset.status == REJECTED


def test_asset_can_require_a_stricter_gained_true_threshold():
    asset = make_asset(min_gained_true={"dev": 2, "gapcheck": 2})
    registry, evidence = registry_at(asset, DEV_PASSED)
    report = registry.promote(asset.asset_id, evidence)
    assert_reason(report, "insufficient_gained_true")
    assert report["layers"]["gapcheck"]["gained_true"] == 1
    assert report["layers"]["gapcheck"]["required_gained_true"] == 2
    with pytest.raises(ValueError, match="positive integers"):
        make_asset("invalid-threshold", min_gained_true={"dev": 0, "gapcheck": 1})


@pytest.mark.parametrize("field", ["trigger", "dataset", "domain", "api", "schema"])
def test_activate_rejects_incomplete_context_without_logging(field):
    asset = make_asset()
    registry, _ = registry_at(asset, PROMOTED)
    context = activation_context(asset, **{field: None})
    with pytest.raises(ValueError, match="complete trigger/dataset/domain/api/schema"):
        registry.activate(asset.asset_id, task_id="deployment", **context)
    assert asset.activation_log == []


@pytest.mark.parametrize("field,bad_value", [
    ("trigger", {"event": "different-event"}),
    ("dataset", "different-dataset"),
    ("domain", "different-domain"),
    ("api", "different-api"),
    ("schema", "different-schema"),
])
def test_activate_rejects_out_of_scope_context_without_logging(field, bad_value):
    asset = make_asset()
    registry, _ = registry_at(asset, PROMOTED)
    context = activation_context(asset, **{field: bad_value})
    with pytest.raises(ValueError, match="does not match"):
        registry.activate(asset.asset_id, task_id="deployment", **context)
    assert asset.activation_log == []


def test_baseline_is_bound_into_raw_evidence_hash():
    asset = make_asset()
    evidence = make_evidence(asset)
    passed = replay_paired_evidence(asset, evidence)
    assert passed["passed"]
    tampered = copy.deepcopy(evidence)
    tampered["records"][0]["control"]["implementation_sha256"] = asset.code_sha256
    rejected = replay_paired_evidence(asset, tampered)
    assert_reason(rejected, "baseline_implementation_hash")
    assert rejected["evidence_sha256"] != passed["evidence_sha256"]
    assert rejected["dev_evidence_sha256"] != passed["dev_evidence_sha256"]


def test_read_only_loader_verifies_baseline_evidence_binding(tmp_path):
    asset = make_asset()
    registry = SkillRegistry()
    registry.propose(asset)
    path = tmp_path / "baseline-binding.json"
    registry.save(path)
    loaded = load_registry(path)
    assert loaded.assets[asset.asset_id].baseline_implementation_sha256 == (
        asset.baseline_implementation_sha256)
    data = json.loads(path.read_text())
    data["assets"][0]["baseline_implementation_sha256"] = digest("tampered-baseline")
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="evidence binding hash mismatch"):
        load_registry(path)


def test_activate_context_mapping_must_be_complete_and_conflict_free():
    asset = make_asset()
    registry, _ = registry_at(asset, PROMOTED)
    with pytest.raises(ValueError, match="complete trigger/dataset/domain/api/schema"):
        registry.activate(asset.asset_id, task_id="legacy-partial",
                          context={"dataset": asset.dataset_scope[0]})
    assert asset.activation_log == []
    with pytest.raises(ValueError, match="conflicting activation context"):
        registry.activate(asset.asset_id, task_id="conflicting",
                          dataset="other-dataset", context=activation_context(asset))
    assert asset.activation_log == []
    record = registry.activate(asset.asset_id, task_id="complete-mapping",
                               context=activation_context(asset))
    assert record["trigger"] == asset.trigger_signature
    assert asset.activation_log == [record]
