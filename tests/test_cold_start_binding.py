import copy

import pytest

from ora_agent.binding_protocol import registry
from ora_agent.evidence_dag import CandidateNode, EvidenceDAG
from ora_agent.scoped_assets import compile_asset, load_asset
from scripts.cold_start_binding import objective_case, real_error_dag, resource_case


@pytest.mark.parametrize("builder", [objective_case, resource_case])
def test_new_mechanism_families_have_independent_binding_validation(builder):
    case = builder(registry())
    assert case["valid"]["status"] == "validated"
    assert case["valid"]["accepted"] is True
    assert case["valid"]["business_audit"]["business_correct"] is True
    assert case["wrong_binding"]["status"] == "rejected"
    assert case["wrong_binding"]["accepted"] is False
    assert case["missing_evidence"]["status"] == "unknown"
    assert case["conflict_alternatives"]["status"] == "unknown"
    assert case["conflict_alternatives"]["accepted"] is False
    assert case["valid"]["llm_calls_this_validation"] == 0


def test_real_error_dag_matches_single_line_and_preserves_negative_branches(tmp_path):
    case = objective_case(registry())
    result = real_error_dag(case, tmp_path)
    assert result["accepted_node_ids"] == ["reference_objective_patch"]
    assert set(result["negative_node_ids"]) == {"root_initial", "candidate_derived_binding"}
    assert result["finished"] is True
    assert result["score_based_pruning"] is False
    assert result["total_solver_runs"] == 1
    assert result["total_llm_calls"] == 0
    assert result["comparison"]["same_business_correct"] is True
    assert result["comparison"]["same_solver_runs"] is True
    assert result["comparison"]["dag_incremental_benefit"] == "not_demonstrated"
    assert result["comparison"]["negative_branches_preserved"] == 2
    accepted = next(node for node in result["nodes"] if node["node_id"] == "reference_objective_patch")
    assert accepted["candidate_hash"] == result["single_line"]["candidate_hash"]
    assert accepted["business_audit"]["business_correct"] is True
    assert accepted["business_audit"]["objective_absolute_error"] == 0
    assert result["single_line"]["execution"]["solution"]["objective"] == 28
    assert result["source_inputs"]["initial_candidate"]["sha256"]


def test_dag_does_not_accept_business_success_without_validated_binding():
    dag = EvidenceDAG()
    node = CandidateNode("n0", "hash", None, "initial", None, "rejected",
                         {"status": "optimal"}, {"business_correct": True})
    dag.add(node)
    assert dag.accepted() == []
    assert dag.negative_branches() == [node]
    with pytest.raises(ValueError, match="duplicate node id"):
        dag.add(node)
    with pytest.raises(ValueError, match="missing parent"):
        dag.add(CandidateNode("n1", "hash2", "missing", "patch", None, "validated",
                              {"status": "optimal"}, {"business_correct": True}))


def test_objective_compiler_handles_constant_and_source_evidence():
    asset = load_asset("assets/scoped_ir/objective_recompute_v0.1.json")
    binding = copy.deepcopy(asset["validation"]["binding"])
    binding["constant"] = 5
    evidence = {"type": "independent_reference", "reference": "controlled",
                "text": "controlled objective", "span": "objective",
                "sha256": "0" * 64}
    binding["source_evidence"] = evidence
    spec = compile_asset(asset, binding)
    invariant = spec["invariants"][0]
    assert invariant["rhs"]["add"][-1] == 5
    assert invariant["source_evidence"] == evidence
