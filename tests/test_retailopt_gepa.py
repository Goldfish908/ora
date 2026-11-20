import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

if sys.version_info < (3, 10):
    pytest.skip("official GEPA requires Python 3.10+", allow_module_level=True)

from scripts.retailopt_gepa import RetailOptAdapter, summarize_records

ROOT = Path(__file__).resolve().parents[1]


def test_reflective_dataset_has_problem_and_proxy_but_no_witness_or_answer():
    record = {"scenario_id": "retail_f1_base_v0", "problem": "natural language problem",
              "code": "print('status: optimal')", "feedback": "proxy objective match: False",
              "witness": "infeasible", "witness_details": ["C-INIT: fabricated inventory"],
              "true_correct": False, "phantom": True, "reference_objective": 12345}
    batch = SimpleNamespace(trajectories=[record])
    dataset = RetailOptAdapter.make_reflective_dataset(
        object(), {"conventions": "seed"}, batch, ["conventions"])
    assert dataset["conventions"][0]["Inputs"]["problem"] == "natural language problem"
    serialized = json.dumps(dataset)
    assert "natural language problem" in serialized
    assert "proxy objective match" in serialized
    for forbidden in ("witness_details", "C-INIT", "phantom", "true_correct", "reference_objective", "12345"):
        assert forbidden not in serialized


def test_metric_summary_separates_proxy_truth_and_phantom():
    records = [
        {"executable": True, "proxy_match": True, "true_correct": True,
         "phantom": False, "phantom_proxy": False,
         "new_llm_calls": 1, "completion_tokens": 5, "total_tokens": 10, "llm_latency_s": 1},
        {"executable": True, "proxy_match": True, "true_correct": False,
         "phantom": True, "phantom_proxy": True,
         "new_llm_calls": 1, "completion_tokens": 6, "total_tokens": 11, "llm_latency_s": 2},
        {"executable": False, "proxy_match": False, "true_correct": False,
         "phantom": False, "phantom_proxy": False, "generation_error": "HTTP 503",
         "new_llm_calls": 1, "completion_tokens": 0, "total_tokens": 0, "llm_latency_s": 3},
    ]
    summary = summarize_records(records, 4)
    assert summary["n"] == 4
    assert summary["runner_errors"] == 2
    assert summary["missing_records"] == 1
    assert summary["generation_errors"] == 1
    assert summary["observed"] == 2
    assert summary["truth_unknown"] == 2
    assert summary["executable"] == 2
    assert summary["proxy_match"] == 2
    assert summary["true_correct"] == 1
    assert summary["phantom"] == 1
    assert summary["phantom_proxy"] == 1
    assert summary["completion_tokens"] == 11


def test_verification_evolution_is_dev_only_and_requires_audit(tmp_path):
    import threading
    from scripts.retailopt_governance import build_governor

    cases_path = ROOT / "work/retailopt_governance_smoke_v0.2/cases.json"
    if not cases_path.exists():
        pytest.skip("trusted RetailOpt cases have not been generated")
    manifest = json.loads(cases_path.read_text())
    row = json.loads((ROOT / "data/m1_retailopt/example01.jsonl").read_text().splitlines()[0])
    row["_split"] = "dev"
    governor = build_governor(manifest, include_demand=False)
    adapter = RetailOptAdapter.__new__(RetailOptAdapter)
    adapter.governor = governor
    adapter.audit_manifest = manifest
    adapter.evolve_verification = True
    adapter.governance_lock = threading.Lock()
    adapter.outdir = tmp_path
    adapter._maybe_evolve(row, {"witness_rules": ["C-DEMAND"]})
    assert governor.checks["L2_demand_balance"].status == "veto_enabled"
    assert (tmp_path / "governor.json").exists()

    frozen_governor = build_governor(manifest, include_demand=False)
    adapter.governor = frozen_governor
    row["_split"] = "gapcheck"
    adapter._maybe_evolve(row, {"witness_rules": ["C-DEMAND"]})
    assert "L2_demand_balance" not in frozen_governor.checks


def test_cached_api_error_is_retried_not_reused(tmp_path):
    adapter = RetailOptAdapter.__new__(RetailOptAdapter)
    path = tmp_path / "rollout.json"
    path.write_text(json.dumps({"candidate_sha256": "abc", "scenario_id": "s",
                                "generation_error": "HTTP 502"}))
    assert adapter._cached(path, "abc", "s") is None
    path.write_text(json.dumps({"candidate_sha256": "abc", "scenario_id": "s",
                                "generation_error": None, "new_llm_calls": 1}))
    cached = adapter._cached(path, "abc", "s")
    assert cached["new_llm_calls"] == 0


def test_summary_counts_cached_generation_errors_and_truth_coverage():
    records = [
        {"executable": True, "proxy_match": True, "true_correct": False,
         "phantom": True, "phantom_proxy": True, "generation_error": None,
         "witness": "infeasible", "new_llm_calls": 1,
         "completion_tokens": 4, "total_tokens": 8, "llm_latency_s": 1},
        {"executable": False, "proxy_match": False, "true_correct": False,
         "phantom": False, "phantom_proxy": False, "generation_error": "HTTP 503",
         "witness": "runner_error", "new_llm_calls": 1,
         "completion_tokens": 0, "total_tokens": 0, "llm_latency_s": 0},
    ]
    summary = summarize_records(records, 3)
    assert summary["records"] == 2
    assert summary["missing_records"] == 1
    assert summary["generation_errors"] == 1
    assert summary["runner_errors"] == 2
    assert summary["observed"] == 1
    assert summary["truth_unknown"] == 2
    assert summary["true_correct"] == 0
    assert summary["phantom_proxy"] == 1
