import json

import pytest

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
