import json

from scripts.cleanroom_saved_artifact_audit import best_checkpoint, repair_result_audit


def test_saved_attempts_restore_feasible_checkpoint_after_later_failure(tmp_path):
    baseline = {
        "task": "task", "workspace": "baseline/app", "true_correct": False,
        "feasible": False, "quality": 0.0, "execution": {"return_code": 0},
        "official": {"evaluation": {"errors": ["bad"]}},
    }
    feasible = {
        "task": "task", "workspace": str(tmp_path / "feasible/app"), "true_correct": False,
        "feasible": True, "quality": 0.0, "objective": 100.0,
        "execution": {"return_code": 0},
        "official": {"evaluation": {"errors": []},
                     "reward_details": {"objective_sense": "minimize"}},
    }
    failed = {
        "task": "task", "workspace": "failed/app", "true_correct": False,
        "feasible": False, "quality": 0.0, "execution": {"return_code": 1},
        "official": {"evaluation": {"errors": ["No solution file found."]}},
    }
    assert best_checkpoint([baseline, feasible, failed]) is feasible
    attempt_path = tmp_path / "feasible/record.json"
    attempt_path.parent.mkdir()
    attempt_path.write_text(json.dumps(feasible))
    result_path = tmp_path / "repair_result.json"
    result_path.write_text(json.dumps({
        "record": baseline, "status": "rejected_regression", "attempts_used": 2,
        "attempt_record_paths": [str(attempt_path)],
    }))
    audit = repair_result_audit(json.loads(result_path.read_text()), result_path)
    assert audit["route"] == "objective_optimization"
    assert audit["feasible"]
    assert audit["checkpoint_reconstructed_from_saved_attempts"]
    assert not audit["business_rechecked"]
