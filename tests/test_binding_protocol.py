import copy
import hashlib

import pytest

from ora_agent.binding_protocol import BindingProposal, evaluate_alternatives, registry, validate_proposal
from ora_agent.scoped_assets import load_asset
from scripts.binding_validation_demo import evidence, flow_case, industry_case


@pytest.mark.parametrize("case_builder", [industry_case, flow_case])
def test_two_families_accept_valid_and_reject_bad_bindings(case_builder):
    case = case_builder(registry())
    assert case["valid"]["status"] == "validated"
    assert case["valid"]["accepted"] is True
    assert case["valid"]["business_audit"]["business_correct"] is True
    assert case["wrong_binding"]["status"] == "rejected"
    assert case["wrong_binding"]["accepted"] is False
    assert case["missing_evidence"]["status"] == "unknown"
    assert case["missing_evidence"]["accepted"] is False
    assert case["conflict_alternatives"]["status"] == "unknown"
    assert case["conflict_alternatives"]["accepted"] is False
    assert case["valid"]["llm_calls_this_validation"] == 0


def test_evidence_span_is_nonempty_and_hash_verified():
    path = flow_case.__globals__["ROOT"] / "work/dvsa/bwor_reference/frozen/BWOR-025/model.json"
    result = evidence(path, "C38")
    assert result["span"]
    assert result["span"] in result["text"]
    assert json_constraint_id(result["span"]) == "C38"
    assert hashlib.sha256(result["text"].encode()).hexdigest() == result["sha256"]


def json_constraint_id(span):
    import json
    return json.loads(span)["constraint_id"]


def test_protocol_rejects_missing_labels_and_bad_origins():
    proposal = BindingProposal("indicator_link", "invalid_origin", "not in question", {})
    result = validate_proposal(proposal, "question", [])
    assert result["status"] == "unknown"
    assert result["accepted"] is False
    assert "unsupported binding origin" in result["errors"]
    assert "source_span is not verbatim problem text" in result["errors"]
    assert "payload must be a nonempty declarative object" in result["errors"]
    assert "independent cells are required" in result["errors"]


def precedence_fixture():
    asset = load_asset("assets/scoped_ir/job_precedence_v0.1.json")
    question = asset["validation"]["question"]
    payload = copy.deepcopy(asset["validation"]["binding"])
    cells = [
        {"key": "reference_clean", "wrong": False, "mutation": "clean",
         "reference_violations": [], "label_source": "controlled time audit",
         "solution": {"variables": {"end_a": 5.0, "start_b": 5.0}, "objective": 0.0}},
        {"key": "wrong_early", "wrong": True, "mutation": "early",
         "reference_violations": ["precedence"], "label_source": "controlled time audit",
         "solution": {"variables": {"end_a": 5.0, "start_b": 4.0}, "objective": 0.0}},
    ]
    return asset, question, payload, cells


def test_business_unknown_cannot_choose_the_other_favorable_binding():
    _, question, payload, cells = precedence_fixture()
    good = BindingProposal("job_precedence", "cold_start_proposal", payload["source_span"], payload)
    conflicting_payload = copy.deepcopy(payload)
    conflicting_payload["conflict"] = True
    conflicting = BindingProposal("job_precedence", "cold_start_proposal",
                                  payload["source_span"], conflicting_payload)

    def scorer(solution, proposal):
        if proposal.payload.get("conflict"):
            return {"status": "UNKNOWN", "business_correct": False}
        return {"status": "SATISFIED", "business_correct": True}

    result = evaluate_alternatives([good, conflicting], question, cells, scorer)
    assert result["evaluations"][0]["accepted"] is True
    assert result["evaluations"][1]["status"] == "unknown"
    assert result["status"] == "unknown"
    assert result["accepted"] is False


def test_missing_reference_clean_is_unknown_when_business_scoring():
    _, question, payload, cells = precedence_fixture()
    cells[0]["key"] = "clean"
    proposal = BindingProposal("job_precedence", "reference_assisted", payload["source_span"], payload)
    result = validate_proposal(proposal, question, cells, lambda solution, _: {
        "status": "SATISFIED", "business_correct": True})
    assert result["status"] == "unknown"
    assert result["accepted"] is False
    assert "reference_clean is required" in result["errors"][0]


def test_missing_label_source_cannot_be_silently_accepted():
    _, question, payload, cells = precedence_fixture()
    del cells[0]["label_source"]
    proposal = BindingProposal("job_precedence", "reference_assisted", payload["source_span"], payload)
    result = validate_proposal(proposal, question, cells)
    assert result["status"] == "unknown"
    assert result["accepted"] is False
    assert any("label_source" in error for error in result["errors"])
