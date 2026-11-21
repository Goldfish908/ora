import json

from scripts.cleanroom_experiment import digest
from scripts.cleanroom_gepa_report import build_analysis


def write_record(run, spec, task, correct):
    candidate_hash = digest(spec)
    workspace = run / "rollouts" / candidate_hash / task / "attempt_0/app"
    generation = workspace.parent / "generation"
    generation.mkdir(parents=True)
    (generation / "model_generation.json").write_text(json.dumps({"response": {
        "usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10,
                  "completion_tokens_details": {"reasoning_tokens": 0}}, "request_wall_s": 1.0}}))
    record = {"task": task, "split": "dev" if task == "dev" else "transfer",
              "candidate_sha256": candidate_hash, "attempt": 0, "workspace": str(workspace),
              "execution": {"return_code": 0}, "official": {"runner": {"return_code": 0},
              "evaluation": {"errors": [] if correct else ["bad"]}, "reward_details": {}},
              "feasible": correct, "quality": 0.8 if correct else 0.0, "true_correct": correct,
              "objective": None, "proxy_match": correct, "phantom_proxy": False, "generation_error": None}
    (workspace.parent / "record.json").write_text(json.dumps(record))


def test_gepa_report_covers_dev_transfer_and_sums_costs(tmp_path):
    run = tmp_path / "run"
    (run / "iterations/seed/components").mkdir(parents=True)
    (run / "iterations/c1/components").mkdir(parents=True)
    (run / "iterations/seed/components/conventions.txt").write_text("")
    (run / "iterations/c1/components/conventions.txt").write_text("spec")
    (run / "iterations/seed/meta.json").write_text(json.dumps({"accepted": True}))
    (run / "iterations/c1/meta.json").write_text(json.dumps({"accepted": True}))
    (run / "implementation.json").write_text("{}")
    (run / "gepa_result.json").write_text(json.dumps({
        "candidates": [{"conventions": ""}, {"conventions": "spec"}], "parents": [[None], [0]]}))
    (run / "analysis.json").write_text(json.dumps({
        "train_ids": ["dev"], "val_ids": ["transfer"], "total_metric_calls": 6, "wall_seconds": 12}))
    for spec in ("", "spec"):
        write_record(run, spec, "dev", True)
        write_record(run, spec, "transfer", False)
    (run / "iterations/rejected").mkdir()
    (run / "iterations/rejected/meta.json").write_text(json.dumps({
        "iteration_id": "rejected", "trace_i": 2, "accepted": False,
        "subsample_scores_before": [0.0], "subsample_scores_after": [0.0]}))
    result = build_analysis(run)
    assert result["n_rejected_proposals"] == 1
    assert result["proposal_history"][-1]["candidate_sha256"] is None
    assert result["candidates"][1]["dev"]["true_correct"] == 1
    assert result["candidates"][1]["transfer"]["true_correct"] == 0
    assert result["candidates"][1]["cost"]["total_tokens"] == 20
    assert result["candidates"][1]["accepted_meta"]["accepted"]
    assert "Neither" in result["evaluation_boundary"]
    from scripts.cleanroom_gepa_report import evaluation_for_hash
    missing = evaluation_for_hash(run, digest("not_evaluated"), ["transfer"])
    assert missing["status"] == "not_run"
    assert missing["n"] == 0
    assert missing["not_run_tasks"] == ["transfer"]
