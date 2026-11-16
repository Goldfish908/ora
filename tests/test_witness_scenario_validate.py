import json
import sys

from scripts import witness_scenario_validate as validation


def test_scenario_manifest_and_asset_lifecycle_are_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["witness_scenario_validate.py", "--out", str(tmp_path)])
    validation.main()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    scenarios = [json.loads(line) for line in (tmp_path / "scenarios.jsonl").read_text().splitlines()]
    assert manifest["scenario_count"] == len(scenarios) == 62
    assert manifest["business_scored_scenarios"] == 38
    assert manifest["controlled_counterexamples"] == 21
    assert manifest["negative_transfer_scenarios"] == 3
    assert manifest["required_coverage_missing"] == []
    assert manifest["controller_tests"]["passed"] is True
    assert manifest["new_llm_calls"] == 0
    assert len({row["scenario_id"] for row in scenarios}) == len(scenarios)
    for row in scenarios:
        if row["source_kind"] == "manually_labelled_controlled_counterexample":
            assert row["validation"]["status"] == "passed"
        else:
            assert row["validation"] == {"status": "replayed", "new_llm_calls": 0}
    lifecycle = json.loads((tmp_path / "asset_lifecycle.json").read_text())
    assert lifecycle["decision"] == "rejected_and_rolled_back"
    assert lifecycle["registry_status"] == "not_promoted"
    assert lifecycle["rollback"]["initial_solution_retained"] is True
    assert lifecycle["gate"]["accepted"] is False
    assert lifecycle["cost"]["solver_runs_this_run"] == 0
