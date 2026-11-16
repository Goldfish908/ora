from ora_agent.acceptance import can_accept
from ora_agent.scoped_ir import evaluate_spec
from scripts.scoped_ir_gate import gate


QUESTION = "At most 100 units."


def cell(key, wrong, x):
    return {"key": key, "wrong": wrong, "mutation": "clean" if not wrong else "bound",
            "reference_violations": [], "solution": {"variables": {"x": x},
                                                    "objective": 0}}


def spec_with_invalid_rule():
    return {"invariants": [
        {"invariant_id": "capacity", "kind": "constraint", "relation": "le",
         "lhs": {"path": "solution.variables.x"}, "rhs": 100,
         "source_span": QUESTION},
        {"invariant_id": "invalid", "kind": "constraint", "relation": "ne",
         "lhs": {"path": "solution.variables.x"}, "rhs": 0,
         "source_span": QUESTION},
    ]}


def valid_spec():
    return {"invariants": [
        {"invariant_id": "capacity", "kind": "constraint", "relation": "le",
         "lhs": {"path": "solution.variables.x"}, "rhs": 100,
         "source_span": QUESTION},
    ]}


def test_can_accept_requires_clean_record_and_accepted_checker():
    record = {"status": "ok", "fired": False, "violations": [],
              "unknown_evidence": [], "rejected": []}
    assert can_accept(record, "accepted") is True
    assert can_accept(record, "rejected") is False
    assert can_accept(record, {"accepted": True, "status": "accepted"}) is True
    assert can_accept(record, {"accepted": True, "status": "rejected"}) is False


def test_can_accept_rejects_every_unknown_or_rejected_evidence_channel():
    base = {"status": "ok", "fired": False}
    blocked = [
        {"status": "unknown"},
        {"fired": True},
        {"rejected": [{"invariant_id": "bad"}]},
        {"rejected_count": 1},
        {"unknown": 1},
        {"unknown_count": 1},
        {"unknown_evidence": [{"rule": "missing"}]},
        {"violations": [{"rule": "bound"}]},
        {"status": "not_applicable"},
        {"asset_status": "NOT_APPLICABLE"},
        {"asset_status": "VIOLATED"},
    ]
    for changes in blocked:
        assert can_accept({**base, **changes}, "accepted") is False, changes


def test_surface_clean_candidate_cannot_bypass_rejected_checker():
    cells = [cell("clean", False, 50), cell("bad", True, 101)]
    evaluation = evaluate_spec(valid_spec(), QUESTION, cells, "p0")
    clean = evaluation["records"][0]
    assert clean["status"] == "ok"
    assert clean["fired"] is False
    assert can_accept(clean, "accepted") is True
    assert can_accept(clean, "rejected") is False


def test_partial_rejection_blocks_gate_and_candidate_despite_valid_detection():
    cells = [cell("clean", False, 50), cell("bad", True, 101)]
    result = gate(spec_with_invalid_rule(), QUESTION, cells, "p0")
    evaluation = result["evaluation"]
    assert evaluation["detection"] == 1.0
    assert evaluation["rejected_count"] == 1
    assert evaluation["dev_passed"] is False
    assert result["accepted"] is False
    assert evaluation["records"][1]["violations"][0]["rule"] == "capacity"
    assert can_accept(evaluation["records"][0], "accepted") is False


def test_gate_requires_full_detection_and_both_reference_cell_kinds():
    cells = [cell("clean", False, 50), cell("bad1", True, 101),
             cell("missed", True, 90), cell("bad2", True, 102)]
    partial = gate(valid_spec(), QUESTION, cells, "p0")
    assert partial["evaluation"]["detection"] == 2 / 3
    assert partial["accepted"] is False
    wrong_only = gate(valid_spec(), QUESTION, [cell("bad", True, 101)], "p0")
    assert wrong_only["evaluation"]["detection"] == 1.0
    assert wrong_only["accepted"] is False
    clean_only = gate(valid_spec(), QUESTION, [cell("clean", False, 50)], "p0")
    assert clean_only["accepted"] is False


def test_gate_accepts_only_strictly_valid_encoded_invariants():
    cells = [cell("clean", False, 50), cell("bad", True, 101)]
    result = gate(valid_spec(), QUESTION, cells, "p0")
    assert result["accepted"] is True
    assert result["evaluation"]["dev_passed"] is True
    assert result["evaluation"]["unknown"] == 0
    assert result["evaluation"]["rejected_count"] == 0


def test_gate_safely_rejects_none_spec_and_empty_cells():
    cells = [cell("clean", False, 50), cell("bad", True, 101)]
    assert gate(None, QUESTION, cells, "p0")["accepted"] is False
    empty = gate(valid_spec(), QUESTION, [], "p0")
    assert empty["accepted"] is False
    assert empty["evaluation"]["records"] == []
