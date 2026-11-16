import hashlib
import json
from pathlib import Path

from scripts.cross_family_dag import bwor_case, industry_case

ROOT = Path(__file__).resolve().parents[1]


def test_bwor_dag_matches_single_line_and_preserves_cold_negative(tmp_path):
    result = bwor_case(tmp_path)
    assert result["accepted_node_ids"] == ["root/reference_objective_patch:1"]
    assert set(result["negative_node_ids"]) == {"root", "root/candidate_derived_binding:0"}
    assert result["single_line"]["business_audit"]["business_correct"] is True
    assert result["single_line"]["solver_runs"] == 1
    assert result["comparison"]["same_business_correct"] is True
    assert result["comparison"]["extra_dag_solver_runs"] == 0
    assert result["comparison"]["dag_gain"] == "not_demonstrated"
    accepted = next(node for node in result["nodes"] if node["node_id"] == "root/reference_objective_patch:1")
    assert accepted["business_audit"]["objective_absolute_error"] == 0
    assert accepted["candidate_hash"] == result["single_line"]["candidate_hash"]
    assert result["source_inputs"]["initial_candidate"]["sha256"]
    assert any(event["type"] == "rollback" for event in result["events"])


def test_industry_objective_only_is_rejected_then_rolls_back_to_composite(tmp_path):
    result = industry_case(tmp_path)
    assert result["accepted_node_ids"] == ["root/objective_and_indicator:1"]
    failed = next(node for node in result["nodes"] if node["node_id"] == "root/objective_only:0")
    assert failed["business_audit"]["business_correct"] is False
    assert failed["binding_status"] == "rejected"
    assert failed["execution"]["solution"]["objective"] == 4000
    assert failed["execution"]["solution"]["variables"]["x_B"] == 0
    assert failed["execution"]["solution"]["variables"]["y_B"] == 1
    rollback = next(event for event in result["events"] if event["type"] == "rollback")
    assert rollback["from_node_id"] == failed["node_id"]
    assert rollback["to_node_id"] == "root"
    assert rollback["snapshot_restored"] is True
    accepted = next(node for node in result["nodes"] if node["node_id"] == "root/objective_and_indicator:1")
    assert accepted["business_audit"]["business_correct"] is True
    assert accepted["binding_status"] == "validated"
    assert result["single_line"]["business_audit"]["business_correct"] is True
    assert result["single_line"]["candidate_hash"] == accepted["candidate_hash"]
    assert result["comparison"]["extra_dag_solver_runs"] == 1
    assert result["comparison"]["dag_gain"] == "not_demonstrated_extra_scip_for_rejected_objective_only"
    assert result["finished"] is True


def test_cross_family_manifest_and_implementation_hashes():
    analysis = json.loads((ROOT / "work/cross_family_dag_v0.1/analysis.json").read_text())
    summary = analysis["summary"]
    assert summary["dag_business_correct"] == 2
    assert summary["single_line_business_correct"] == 2
    assert summary["dag_solver_runs"] == 3
    assert summary["single_line_solver_runs"] == 2
    assert summary["extra_dag_solver_runs"] == 1
    assert summary["rollback_events"] == 2
    assert summary["accepted_but_business_incorrect"] == 0
    assert summary["harmed_win"] == 0
    assert summary["new_llm_calls"] == 0
    for name, expected in analysis["run_config"]["implementation_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
