import hashlib
import json
import sys
from pathlib import Path

import pytest

from scripts.cleanroom_experiment import digest
from scripts.cleanroom_memory import GENERATOR_FILES, replay_evidence, select_candidate

ROOT = Path(__file__).resolve().parents[1]


def gepa_inputs(tmp_path):
    result = tmp_path / "result.json"
    result.write_text(json.dumps({
        "candidates": [{"conventions": ""}, {"conventions": "integer production"}],
        "parents": [[None], [0]]}))
    (tmp_path / "analysis.json").write_text(json.dumps({
        "val_ids": ["selection_task"], "curves": [
            {"candidate_idx": 0, "official_proxy_mean": 0.0, "n": 1,
             "generation_errors": 0, "true_correct": 0, "phantom_proxy": 0},
            {"candidate_idx": 1, "official_proxy_mean": 1.0, "n": 1,
             "generation_errors": 0, "true_correct": 1, "phantom_proxy": 0},
        ]}))
    (tmp_path / "implementation.json").write_text(json.dumps({
        "files": dict.fromkeys(GENERATOR_FILES, "hash"), "model": "test-model", "generation": {"max_tokens": 16},
        "arguments": {"api_guard": True}}))
    return result


def replay_manifest(tmp_path, name, specification, true, source=None, unknown=False):
    run = tmp_path / name
    workspace = run / "rollouts" / digest(specification) / "audit_task" / "attempt_0/app"
    workspace.mkdir(parents=True)
    record = {"task": "audit_task", "split": "audit", "candidate_sha256": digest(specification),
              "attempt": 0, "workspace": str(workspace), "execution": {"return_code": 0, "wall_seconds": 1.0},
              "official": {"runner": {"return_code": 0, "timed_out": False, "wall_seconds": 0.1},
                           "evaluation": {"errors": ["official evaluator did not produce evaluation.json"]
                                          if unknown else []},
                           "reward": {"feasibility": 1.0 if true else 0.0,
                                      "quality": 0.8 if true else 0.0},
                           "reward_details": {}},
              "feasible": true, "quality": 0.8 if true else 0.0, "true_correct": true,
              "objective": 1.0, "proxy_match": true, "phantom_proxy": False, "generation_error": None}
    record_path = workspace.parent / "record.json"
    record_path.write_text(json.dumps(record))
    manifest = {"model": "test-model", "generation": {"max_tokens": 16},
                "arguments": {"api_guard": True}, "files": dict.fromkeys(GENERATOR_FILES, "hash"),
                "evaluation": {"provenance": "subsequent_disjoint_replay" if source else "frozen_replay",
                               "task_ids": ["audit_task"],
                               "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest() if source else None},
                "records": [{"task": "audit_task", "record_path": str(record_path)}]}
    (run / "run.json").write_text(json.dumps(manifest))
    return run / "run.json"


def run_promotion(tmp_path, monkeypatch, capsys, result, replay=None, baseline=None):
    monkeypatch.setattr("scripts.cleanroom_memory.audit_specification", lambda *args, **kwargs: {
        "changed_features_covered": True, "scope_confirmed": True})
    monkeypatch.setattr("scripts.cleanroom_memory.probe_pyscipopt_api", lambda *args: {"stdout": "verified API"})
    monkeypatch.setattr("scripts.cleanroom_memory.llm_mod.load_config", lambda: None)
    argv = ["cleanroom_memory.py", "--tasks", "configs/cleanroom_smoke_tasks.json",
            "--gepa-result", str(result), "--analysis", str(tmp_path / "analysis.json"),
            "--run-dir", str(tmp_path / "out")]
    if replay:
        argv += ["--independent-replay", str(replay), "--independent-baseline", str(baseline)]
    monkeypatch.setattr(sys, "argv", argv)
    from scripts.cleanroom_memory import main
    main()
    return json.loads(capsys.readouterr().out)


def test_memory_does_not_promote_without_independent_replay(tmp_path, monkeypatch, capsys):
    result = gepa_inputs(tmp_path)
    summary = run_promotion(tmp_path, monkeypatch, capsys, result)
    assert summary["specification_status"] == "rejected"
    assert not summary["independent_replay"]


def test_memory_promotes_only_with_disjoint_replay_and_provenance(tmp_path, monkeypatch, capsys):
    result = gepa_inputs(tmp_path)
    replay = replay_manifest(tmp_path, "candidate", "integer production", True, result)
    baseline = replay_manifest(tmp_path, "baseline", "", False)
    summary = run_promotion(tmp_path, monkeypatch, capsys, result, replay, baseline)
    assert summary["specification_status"] == "promoted"
    assert summary["independent_replay"]
    assert summary["specification_scope"]["domain"] == "manufacturing"
    evidence = json.loads((tmp_path / "out/independent_replay_evidence.json").read_text())
    assert evidence["paired_comparison"]["gained_true_correct"] == ["audit_task"]
    assert evidence["paired_comparison"]["win_safe"]


def test_replay_rejects_wrong_specification_hash(tmp_path):
    result = gepa_inputs(tmp_path)
    replay = replay_manifest(tmp_path, "candidate", "integer production", True, result)
    with pytest.raises(ValueError, match="different specification"):
        replay_evidence(replay, "different", result, "subsequent_disjoint_replay")


def test_transfer_tie_uses_dev_proxy_instead_of_default_seed(tmp_path):
    result = gepa_inputs(tmp_path)
    analysis = {"train_ids": ["dev"], "curves": [
        {"candidate_idx": 0, "official_proxy_mean": 0.0},
        {"candidate_idx": 1, "official_proxy_mean": 0.0}]}
    for specification, score in (("", 0.0), ("integer production", 1.0)):
        path = tmp_path / "rollouts" / digest(specification) / "dev/attempt_0/record.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"proxy_score": score}))
    selected = select_candidate(result, json.loads(result.read_text()), analysis)
    assert selected["candidate_idx"] == 1
    assert selected["dev_proxy_mean"] == 1.0
    assert selected["selection_rule"].startswith("transfer_proxy_desc")
