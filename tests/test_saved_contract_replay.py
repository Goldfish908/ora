import hashlib
import json

from scripts import bwor_saved_contract_replay as replay


def test_saved_responses_gain_execution_not_semantic_repair(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.bwor_scoped_loop.relative", lambda path: str(path))
    analysis = replay.run_cohort(
        replay.SOURCE, replay.IDS, tmp_path, replay.PROTOCOL,
        "bwor.saved_response.contract_replay.v0.2",
        "historical_saved_response_replay_not_frozen")
    counts = analysis["denominators"]
    assert counts["legacy_initial_business_correct"] == 2
    assert counts["initial_business_correct"] == 5
    assert counts["business_recovered_after_normalization"] == 3
    assert counts["contract_recovered"] == 2
    assert counts["contract_invalid"] == 1
    assert counts["initial_solver_runs_this_replay"] == 5
    assert analysis["cost"]["new_llm_calls"] == 0
    assert analysis["cost"]["repair_solver_runs_this_replay"] == 0
    for arm in ("fixed", "progress"):
        row = analysis["arms"][arm]
        assert row["initial_reference_correct"] == row["final_reference_correct"] == 5
        assert row["improved"] == row["reference_bound_development_recoveries"] == 0
        assert row["deterministic_transforms"] == 0
        assert row["harmed_win"] == row["accepted_but_reference_incorrect"] == 0
        assert row["llm_calls"] == row["tokens"] == 0
    for problem_id in ("BWOR-002", "BWOR-010", "BWOR-012"):
        initial = json.loads((tmp_path / problem_id / "initial/result.json").read_text())
        assert initial["score"]["business_correct"] is True
        assert initial["normalization_applied"] is True
        assert initial["path_normalizations"]
        source = replay.SOURCE / problem_id / "initial/response.json"
        assert hashlib.sha256(source.read_bytes()).hexdigest() == initial["source_response"]["sha256"]
    assert not (tmp_path / "BWOR-005/initial/candidate.json").exists()
    truncated = json.loads((tmp_path / "BWOR-005/initial/result.json").read_text())
    assert truncated["status"] == "contract_invalid"
    assert truncated["score"]["business_correct"] is False
    assert analysis["run_config"]["missing_source_artifacts"] == [
        "BWOR-002/prompt.txt", "BWOR-003/prompt.txt", "BWOR-005/prompt.txt"]
