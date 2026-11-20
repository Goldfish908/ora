import json
from collections import Counter

from scripts.build_retailopt_result_ledger import build


def test_retailopt_ledger_keeps_splits_and_recomputes_current_counts(tmp_path):
    out = tmp_path / "ledger"
    manifest = build(out)
    assert manifest["best_reviewed_gapcheck60_single_candidate"]["true_correct"] == 57
    assert manifest["n_task_records"] == 120

    runs = [json.loads(line) for line in (out / "retailopt_runs.jsonl").read_text().splitlines()]
    tasks = [json.loads(line) for line in (out / "retailopt_gapcheck60_tasks.jsonl").read_text().splitlines()]
    assert {row["split"] for row in runs} == {"gapcheck60", "full190", "dev20"}
    assert all(row.get("proxy_match") is None for row in runs if row["evidence"] == "documented_aggregate")

    counts = Counter((row["candidate_idx"], row["outcome"]) for row in tasks)
    assert counts[(0, "true_correct")] == 3
    assert counts[(0, "phantom_proxy")] == 17
    assert counts[(1, "true_correct")] == 57
    assert counts[(1, "phantom_proxy")] == 0
    assert len({row["scenario_id"] for row in tasks}) == 60
    assert len({row["scenario_id"] for row in tasks if row["candidate_idx"] == 1 and not row["true_correct"]}) == 3
    assert (out / "retailopt_detailed_report.md").exists()
    assert (out / "retailopt_gapcheck60_tasks.csv").exists()
