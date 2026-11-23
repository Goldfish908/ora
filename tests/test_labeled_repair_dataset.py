from __future__ import annotations

import base64
import copy
import hashlib
import json
import sys
from dataclasses import replace

import pytest

if sys.version_info < (3, 10):
    pytest.skip("Labeled repair dataset tests require Python >=3.10", allow_module_level=True)

from ora_agent.labeled_repair_dataset import (
    BUSINESS_UNVERIFIED,
    EXPERIENCE,
    FINAL_EVALUATION,
    PARETO,
    PROMOTE,
    PROPOSE,
    TEST,
    TRAIN,
    UNKNOWN,
    VAL,
    DatasetValidationError,
    LabeledRepairDataset,
    LabeledRepairSample,
    MissingLabelError,
    SplitAccessError,
)


_DEFAULT = object()


def sample(
    problem_id,
    split,
    *,
    root=None,
    official=_DEFAULT,
    root_sha256=None,
    public_data_sha256=None,
    evaluator_sha256=None,
):
    if official is _DEFAULT:
        official = {
            "true_correct": True,
            "feasible": True,
            "quality": 0.8,
            "objective": 12.0,
            "errors": [{"rule": "capacity", "detail": "capacity exceeded"}],
        }
    return LabeledRepairSample(
        problem_id=problem_id,
        split=split,
        root_artifact=root if root is not None else f"{problem_id}:root".encode(),
        root_sha256=root_sha256,
        public_data={"public.json": b'{"capacity": 1}'},
        public_data_sha256=public_data_sha256,
        evaluator=b"def evaluate(artifact): return official_score(artifact)\n",
        evaluator_sha256=evaluator_sha256,
        official=official,
        feedback=f"{problem_id} official feedback: repair capacity",
        counterexamples=[{"artifact": "bad", "violation": "capacity"}],
        near_boundary=[{"artifact": "edge", "margin": 0.001}],
        source={"dataset": "toy-official", "official_run": f"run/{problem_id}"},
    )


def dataset(*, train=None, val=None, test=None, val_score_keys=("feasible", "quality"), objective_sense="max"):
    return LabeledRepairDataset(
        [
            sample("train-1", TRAIN) if train is None else train,
            sample("val-1", VAL) if val is None else val,
            sample("test-1", TEST) if test is None else test,
        ],
        val_score_keys=val_score_keys,
        objective_sense=objective_sense,
    )


def test_manifest_round_trip_contains_all_required_provenance_and_hashes():
    original = dataset()

    manifest = original.manifest
    encoded = json.dumps(manifest, allow_nan=False)
    restored = LabeledRepairDataset.from_manifest(json.loads(encoded))

    row = manifest["samples"][0]
    assert {
        "problem_id", "split", "root_artifact", "root_sha256", "public_data", "public_data_sha256",
        "evaluator", "evaluator_sha256", "official", "feedback", "counterexamples", "near_boundary", "source",
    } <= set(row)
    assert row["official"]["true"] is True
    assert row["official"]["feasible"] is True
    assert row["official"]["quality"] == pytest.approx(0.8)
    assert row["official"]["objective"] == pytest.approx(12.0)
    assert row["root_sha256"] == hashlib.sha256(b"train-1:root").hexdigest()
    assert restored.manifest == manifest
    assert restored.view("train-1", purpose=PROPOSE)["feedback"] == "train-1 official feedback: repair capacity"


@pytest.mark.parametrize("target", ["root", "public", "evaluator"])
def test_manifest_rejects_artifact_public_data_and_evaluator_hash_mismatch(target):
    manifest = dataset().manifest
    row = manifest["samples"][0]
    replacement = base64.b64encode(b"tampered").decode("ascii")
    if target == "root":
        row["root_artifact"]["data_base64"] = replacement
        message = "root artifact SHA256"
    elif target == "public":
        row["public_data"]["files"]["public.json"]["data_base64"] = replacement
        message = "public data SHA256"
    else:
        row["evaluator"]["data_base64"] = replacement
        message = "evaluator SHA256"

    with pytest.raises(DatasetValidationError, match=message):
        LabeledRepairDataset.from_manifest(manifest)


def test_constructor_checks_declared_hashes_not_just_digest_shape():
    for kwargs, message in (
        ({"root_sha256": "0" * 64}, "root artifact SHA256"),
        ({"public_data_sha256": "0" * 64}, "public data SHA256"),
        ({"evaluator_sha256": "0" * 64}, "evaluator SHA256"),
    ):
        with pytest.raises(DatasetValidationError, match=message):
            sample("bad-hash", TRAIN, **kwargs)


def test_problem_id_cannot_overlap_splits():
    train = sample("shared-id", TRAIN)
    val = replace(train, split=VAL)
    test = sample("test-1", TEST)

    with pytest.raises(DatasetValidationError, match="overlapping splits"):
        LabeledRepairDataset([train, val, test])


def test_same_root_cannot_be_reused_across_splits_with_different_ids():
    train = sample("train-1", TRAIN)
    val = replace(train, problem_id="val-copy", split=VAL)
    test = sample("test-1", TEST)

    with pytest.raises(DatasetValidationError, match="root artifact is reused across splits"):
        LabeledRepairDataset([train, val, test])


def test_unknown_official_values_become_null_not_false_truth():
    unknown = sample("train-unknown", TRAIN, official={
        "true_correct": True,
        "feasible": True,
        "quality": 1.0,
        "objective": 100.0,
        "evaluation_unknown": True,
    })
    data = dataset(train=unknown)

    assert unknown.official.label_status == UNKNOWN
    assert unknown.official.true is None
    assert unknown.official.feasible is None
    assert unknown.official.quality is None
    assert unknown.official.objective is None
    with pytest.raises(MissingLabelError, match="UNKNOWN.*cannot be used as truth"):
        data.gepa_evaluation_batch(TRAIN, capture_traces=True)
    with pytest.raises(MissingLabelError):
        data.propose("train-unknown", lambda view: view)


def test_raw_failed_official_runner_is_unknown_not_a_true_or_feasible_label():
    raw = {
        "evaluation": {"feasible": True, "objective": 100.0, "errors": []},
        "reward": {"feasibility": 1.0, "quality": 1.0},
        "reward_details": {},
        "runner": {"return_code": 1, "timed_out": False},
    }
    unknown = sample("train-unknown", TRAIN, official=raw)

    assert unknown.official.label_status == UNKNOWN
    assert unknown.official.to_dict() == {
        "true": None, "feasible": None, "quality": None, "objective": None,
        "label_status": UNKNOWN, "errors": [],
    }


def test_direct_label_objects_cannot_bypass_unknown_or_missing_label_rules():
    from ora_agent.labeled_repair_dataset import OfficialLabel

    unknown = OfficialLabel(True, True, 1.0, 100.0, UNKNOWN)
    assert unknown.to_dict() == {
        "true": None, "feasible": None, "quality": None, "objective": None,
        "label_status": UNKNOWN, "errors": [],
    }
    with pytest.raises(MissingLabelError):
        OfficialLabel(None, None, None, None)
    with pytest.raises(DatasetValidationError, match="cannot claim"):
        OfficialLabel(True, True, 1.0, 100.0, BUSINESS_UNVERIFIED)


@pytest.mark.parametrize("official", [None, {}, {"true": True}, {"true": None, "feasible": None, "quality": None}])
def test_missing_or_partial_official_labels_are_rejected(official):
    with pytest.raises(MissingLabelError):
        sample("no-label", TRAIN, official=official)


def test_business_unverified_is_not_truth_and_cannot_enter_gepa():
    unverified = sample("train-unverified", TRAIN, official={
        "true_correct": False,
        "feasible": True,
        "quality": 0.9,
        "objective": 9.0,
        "business_unverified": True,
        "audit_status": "business_unverified",
    })
    data = dataset(train=unverified)

    assert unverified.official.label_status == BUSINESS_UNVERIFIED
    assert unverified.official.true is None
    assert unverified.official.feasible is True
    with pytest.raises(MissingLabelError, match="BUSINESS_UNVERIFIED"):
        data.gepa_evaluation_batch(TRAIN)

    with pytest.raises(DatasetValidationError, match="cannot claim"):
        sample("contradictory", TRAIN, official={
            "true_correct": True, "feasible": True, "quality": 1.0,
            "business_unverified": True,
        })


def test_val_view_and_batch_expose_only_protocol_scores_and_no_feedback():
    data = dataset(val_score_keys=("quality", "objective"))

    view = data.view("val-1", purpose=PARETO)
    assert set(view) == {
        "problem_id", "split", "root_sha256", "public_data_sha256", "evaluator_sha256", "scores",
    }
    assert view["scores"] == {"quality": pytest.approx(0.8), "objective": pytest.approx(12.0)}
    assert "feedback" not in view and "official" not in view and "counterexamples" not in view

    batch = data.gepa_evaluation_batch(VAL)
    assert batch.scores == [pytest.approx((0.8 + 12.0) / 2)]
    assert batch.objective_scores == [{"quality": pytest.approx(0.8), "objective": pytest.approx(12.0)}]
    assert batch.trajectories is None
    assert set(batch.outputs[0]) == set(view)

    with pytest.raises(SplitAccessError, match="val cannot enter propose"):
        data.view("val-1", purpose=PROPOSE)
    with pytest.raises(SplitAccessError, match="val detailed feedback"):
        data.gepa_evaluation_batch(VAL, capture_traces=True)
    with pytest.raises(SplitAccessError, match="only problem_id and scores"):
        data.promote("candidate", [{
            "problem_id": "val-1", "scores": {"quality": 0.9, "objective": 13.0},
            "feedback": "hidden feedback must not be promoted",
        }])


def test_test_is_final_evaluation_only_and_cannot_reach_propose_promote_or_experience():
    data = dataset()
    writes = []

    with pytest.raises(SplitAccessError, match="test cannot enter propose"):
        data.propose("test-1", lambda view: view)
    with pytest.raises(SplitAccessError, match="test cannot enter promotion"):
        data.promote("candidate", [{"problem_id": "test-1", "scores": {"feasible": 1.0, "quality": 1.0}}])
    with pytest.raises(SplitAccessError, match="test cannot be written back"):
        data.write_experience("test-1", {"text": "must not persist"}, writes.append)
    with pytest.raises(SplitAccessError, match="test detailed feedback"):
        data.gepa_evaluation_batch(TEST, capture_traces=True)
    assert writes == []

    final_view = data.view("test-1", purpose=FINAL_EVALUATION)
    assert "feedback" not in final_view
    assert "errors" not in final_view["official"]
    batch = data.gepa_evaluation_batch(TEST)
    assert batch.trajectories is None
    assert "feedback" not in batch.outputs[0]
    denied = [event for event in data.access_audit(TEST) if not event["allowed"]]
    assert {event["purpose"] for event in denied} >= {PROPOSE, EXPERIENCE, FINAL_EVALUATION}


def test_train_gepa_trajectory_propose_and_experience_follow_normal_path():
    data = dataset()

    batch = data.gepa_evaluation_batch(TRAIN, capture_traces=True)

    from gepa.core.adapter import EvaluationBatch

    assert isinstance(batch, EvaluationBatch)
    assert batch.scores == [pytest.approx(0.9)]
    assert batch.objective_scores == [{"feasible": 1.0, "quality": pytest.approx(0.8)}]
    assert batch.num_metric_calls == 0
    trajectory = batch.trajectories[0]
    assert trajectory["problem_id"] == "train-1"
    assert trajectory["official"]["true"] is True
    assert trajectory["official"]["errors"] == [{"rule": "capacity", "detail": "capacity exceeded"}]
    assert trajectory["feedback"] == "train-1 official feedback: repair capacity"
    assert trajectory["counterexamples"][0]["violation"] == "capacity"
    assert trajectory["near_boundary"][0]["margin"] == pytest.approx(0.001)
    assert trajectory["source"]["official_run"] == "run/train-1"
    assert "evaluator" not in trajectory

    proposal = data.propose("train-1", lambda view: {
        "problem_id": view["problem_id"], "reflection": view["feedback"],
    })
    assert proposal == {
        "problem_id": "train-1", "reflection": "train-1 official feedback: repair capacity",
    }
    writes = []
    returned = data.write_experience("train-1", {"text": "general capacity repair"}, writes.append)
    assert writes[0]["split"] == TRAIN
    assert writes[0]["experience"]["text"] == "general capacity repair"
    assert returned["problem_id"] == "train-1"


def test_val_promotion_accepts_only_exact_numeric_protocol_evidence():
    data = dataset(val_score_keys=("quality",))

    receipt = data.promote("candidate-7", {"val-1": {"quality": 0.95}})

    assert receipt["candidate_id"] == "candidate-7"
    assert receipt["evidence_split"] == VAL
    assert receipt["evidence"][0]["scores"] == {"quality": pytest.approx(0.95)}
    assert "feedback" not in receipt["evidence"][0]
    with pytest.raises(SplitAccessError, match="exactly match"):
        data.promote("candidate-7", {"val-1": {"quality": 0.95, "true": 1.0}})


def test_train_experience_rejects_nested_test_provenance_before_sink():
    data = dataset()
    writes = []

    with pytest.raises(SplitAccessError, match="test cannot be written back"):
        data.write_experience("train-1", {
            "text": "illegally imported experience",
            "origin": {"source_problem_id": "test-1", "source_split": TEST},
        }, writes.append)

    assert writes == []
    event = data.access_audit()[-1]
    assert event["action"] == EXPERIENCE
    assert event["allowed"] is False


def test_views_are_read_only_and_audit_records_allowed_and_denied_access():
    data = dataset()

    view = data.view("train-1", purpose=PROPOSE)
    with pytest.raises(TypeError):
        view["feedback"] = "mutated"
    with pytest.raises(TypeError):
        view["official"]["true"] = False
    assert data.view("train-1", purpose=PROPOSE)["official"]["true"] is True

    manifest = data.manifest
    manifest["samples"][0]["feedback"] = "detached mutation"
    assert "detached mutation" not in data.manifest["samples"][0]["feedback"]

    with pytest.raises(SplitAccessError):
        data.view("test-1", purpose=PROMOTE)
    audit = data.access_audit()
    assert [event["event_index"] for event in audit] == list(range(len(audit)))
    assert any(event["allowed"] and event["purpose"] == PROPOSE for event in audit)
    assert any(not event["allowed"] and event["split"] == TEST for event in audit)


def test_minimization_objective_is_converted_to_higher_is_better_score():
    labeled = sample("train-min", TRAIN, official={
        "true": False, "feasible": True, "quality": 0.2, "objective": 7.5,
    })
    data = dataset(train=labeled, val_score_keys=("objective",), objective_sense="min")

    assert data.gepa_evaluation_batch(TRAIN).scores == [pytest.approx(-7.5)]
