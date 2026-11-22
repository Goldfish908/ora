import json

from scripts.cleanroom_batch_report import build
from scripts.cleanroom_experiment import digest


def replay(root, name, spec, outcomes):
    run = root / name
    records = []
    for task, correct in outcomes.items():
        workspace = run / "records" / task / "app"
        workspace.mkdir(parents=True)
        record = {"task": task, "split": "audit", "candidate_sha256": digest(spec), "attempt": 0,
                  "workspace": str(workspace), "execution": {"return_code": 0},
                  "official": {"runner": {"return_code": 0}, "evaluation": {"errors": [] if correct else ["bad"]},
                               "reward_details": {}}, "feasible": correct, "quality": 0.8 if correct else 0.0,
                  "true_correct": correct, "objective": None, "proxy_match": correct,
                  "phantom_proxy": False, "generation_error": None}
        path = workspace.parent / "record.json"
        path.write_text(json.dumps(record))
        records.append({"task": task, "record_path": str(path)})
    (run / "run.json").write_text(json.dumps({
        "evaluation": {"task_ids": list(outcomes), "provenance": "subsequent_disjoint_replay"},
        "records": records}))
    (run / "replay_result.json").write_text(json.dumps({
        "provenance": "subsequent_disjoint_replay",
        "specification_sha256": {task: digest(spec) for task in outcomes}}))
    return run


def repair(root, task, record_path, status, attempts):
    record = json.loads(record_path.read_text())
    result = {"record": record, "status": status, "attempts_used": attempts}
    path = root / f"repair_{task}.json"
    path.write_text(json.dumps(result))
    return path


def test_batch_report_pairs_tasks_and_marks_identical_memory(tmp_path):
    b0 = replay(tmp_path, "b0", "", {"a": True, "b": False})
    b1 = replay(tmp_path, "b1", "spec", {"a": True, "b": True})
    b3 = replay(tmp_path, "b3", "spec", {"a": True, "b": True})
    records = [b1 / "records/a/record.json", b1 / "records/b/record.json"]
    repairs = [repair(tmp_path, "a", records[0], "preserved_win", 0),
               repair(tmp_path, "b", records[1], "accepted", 1)]
    result = build(b0, b1, b1, repairs, b3, repairs, tmp_path / "out")
    assert result["arms"][0]["direct"]["true_correct"] == 1
    assert result["arms"][1]["final"]["true_correct"] == 2
    assert result["b0_to_b1"]["gained_true_correct"] == ["b"]
    assert result["arms"][1]["pair_win_safe"]["win_safe"]
    assert result["arms"][2]["final"]["coverage"] == 1.0
    assert result["b0_to_b2"]["gained_true_correct"] == ["b"]
    assert result["b0_to_b2"]["win_safe"]
    assert result["b0_to_b3"]["win_safe"]
    assert all(row["coverage"] and row["win_safe"] and not row["unknown"]
               for row in result["arms"][2]["tasks"])
    assert result["b3_same_generator_specification_as_b1"]
    assert "not_run" not in result["arms"][2]
    report = (tmp_path / "out/report.md").read_text()
    assert "| Win-safe | Tokens |" in report
    assert "True→True" in report


def test_batch_report_does_not_zero_fill_missing_repairs(tmp_path):
    b0 = replay(tmp_path, "b0", "", {"a": True, "b": False})
    b1 = replay(tmp_path, "b1", "spec", {"a": True, "b": True})
    one_repair = repair(tmp_path, "a", b1 / "records/a/record.json", "preserved_win", 0)
    result = build(b0, b1, b1, [one_repair], None, [], tmp_path / "out")
    assert result["arms"][2]["final"]["n"] == 1
    assert result["arms"][2]["final"]["coverage"] == 0.5
    assert not result["arms"][2]["pair_win_safe"]["win_safe"]
    assert result["arms"][3]["status"] == "not_run"


def test_batch_report_cli_uses_argparse_singular_destinations(tmp_path, monkeypatch):
    import sys
    from scripts.cleanroom_batch_report import main

    calls = {}
    def fake_build(*args):
        calls["args"] = args
        return {}
    monkeypatch.setattr("scripts.cleanroom_batch_report.build", fake_build)
    monkeypatch.setattr(sys, "argv", ["cleanroom_batch_report.py", "--b0", "b0", "--b1", "b1",
                                     "--b2", "b1", "--b2-repair", "r1", "--b2-repair", "r2",
                                     "--b3", "b3", "--b3-repair", "r3", "--out", "out"])
    main()
    assert len(calls["args"][3]) == 2
    assert len(calls["args"][5]) == 1
