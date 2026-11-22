import json
from types import SimpleNamespace

import pytest

from scripts.cleanroom_experiment import run_oracle_batch
from scripts.cleanroom_health_report import collect_health


def test_collect_health_binds_roles_to_hashed_oracle_results(tmp_path):
    roles = tmp_path / "roles.json"
    roles.write_text(json.dumps({"version": "test", "tasks": [
        {"name": "task", "domain": "energy", "split": "audit", "role": "independent_audit"}]}))
    source = tmp_path / "oracle_results.json"
    source.write_text(json.dumps({"task": {
        "metrics": {"true_correct": True, "feasible": True, "quality": 2.0, "objective": 3.0}}}))

    result = collect_health(roles, {"task": source})

    assert result["n_healthy"] == 1 and result["all_true_correct"]
    assert result["tasks"][0]["source_sha256"]
    assert result["tasks"][0]["role"] == "independent_audit"
    source.write_text(json.dumps({"task": {
        "metrics": {"true_correct": False, "feasible": False, "quality": 0.0}}}))
    with pytest.raises(ValueError, match="health did not pass"):
        collect_health(roles, {"task": source})


def test_oracle_batch_saves_each_result_and_resumes_without_repeating(tmp_path, monkeypatch):
    calls = []

    def fake_oracle(packet, workspace):
        calls.append(packet.name)
        return {"metrics": {"true_correct": True, "feasible": True, "quality": 2.0}}

    monkeypatch.setattr("scripts.cleanroom_experiment.run_oracle", fake_oracle)
    packets = [SimpleNamespace(name="one"), SimpleNamespace(name="two")]
    first = run_oracle_batch(packets[:1], tmp_path)
    assert calls == ["one"]
    assert (tmp_path / "one/oracle/result.json").exists()
    second = run_oracle_batch(packets, tmp_path, resume=True)
    assert calls == ["one", "two"]
    assert set(second) == {"one", "two"}
    assert first["one"] == second["one"]
    assert (tmp_path / "oracle_results.json").exists()
