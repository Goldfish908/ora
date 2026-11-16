import json
from pathlib import Path

from ora_agent.repair_controller import (
    ProgressController,
    code_sha256,
    repair_scip_sense,
)
from scripts.scoped_ir_e2e import load_initial, run_arm, score_nlp4lp
from scripts.scoped_ir_e2e_data import normalized_rows
from scripts.repair_controller_compare import reference_cells

ROOT = Path(__file__).resolve().parents[1]


def failed(record=None, reason="no_solution"):
    return {"status": "unknown", "fired": False, "reason": reason,
            "violations": []}, record or {"exec_status": "crash", "stderr_tail": "ValueError: bad"}


def test_known_scip_sense_is_a_structural_repair_not_text_replacement():
    code = 'm.setObjective(3 * x, sense="max")\n'
    repaired = repair_scip_sense(code, "max")
    assert 'sense=\'maximize\'' in repaired
    assert repair_scip_sense('m.setObjective(x, sense="min")', "min") == (
        "m.setObjective(x, sense='minimize')")


def test_repeated_failure_changes_action_then_stops_instead_of_looping():
    controller = ProgressController()
    audit, record = failed()
    code = "first = 1\n"
    decision = controller.decide(code, record, audit, remaining=3)
    assert decision.action == "local_patch"
    changed = "renamed = 1\n"
    controller.record(decision, changed)
    decision = controller.decide(changed, record, audit, remaining=2)
    assert decision.action == "regenerate"
    assert controller.no_progress_count == 1
    controller.record(decision, changed)
    decision = controller.decide(changed, record, audit, remaining=1)
    assert decision.action == "stop"
    assert decision.reason == "no_progress_after_local_patch_and_regenerate"
    assert controller.no_progress_count == 2
    assert [item["action"] for item in controller.trace()] == ["local_patch", "regenerate"]


def test_identical_code_and_identical_action_cannot_repeat():
    controller = ProgressController()
    audit, record = failed()
    code = "x = unknown\n"
    decision = controller.decide(code, record, audit, remaining=2)
    controller.record(decision, code)
    assert controller.decide(code, record, audit, remaining=1).action == "regenerate"
    assert controller.no_progress_count == 1


def test_accepted_candidate_stops_and_cannot_be_repaired_again():
    controller = ProgressController()
    decision = controller.decide("code", {}, {"status": "ok", "fired": False}, remaining=3)
    assert decision.action == "stop"
    assert decision.reason == "accepted"
    assert controller.trace() == []


def test_unknown_and_rejected_checker_are_not_accepted():
    controller = ProgressController()
    decision = controller.decide("code", {}, {"status": "unknown", "fired": False}, remaining=3)
    assert decision.action == "acquire_evidence"
    audit, record = failed()
    decision = controller.decide("code", record, audit, remaining=3,
                                 checker_status="rejected")
    assert decision.action == "repair_checker"


def test_specialized_api_repair_is_not_retried_on_the_same_failure():
    controller = ProgressController()
    record = {"exec_status": "crash", "stderr_tail": "unrecognized optimization sense: max"}
    audit = {"status": "unknown", "fired": False, "reason": "no_solution"}
    code = 'm.setObjective(x, sense="max")'
    decision = controller.decide(code, record, audit, remaining=2)
    assert decision.action == "specialized_api_repair"
    controller.record(decision, code)
    decision = controller.decide(code, record, audit, remaining=1)
    assert decision.action == "stop"
    assert decision.reason == "specialized_api_repair_did_not_change_failure"


def test_budget_exhaustion_stops_before_another_repair():
    controller = ProgressController()
    audit, record = failed()
    assert controller.decide("code", record, audit, remaining=0).reason == "budget_exhausted"


def test_full_pipeline_recovers_scip_sense_without_llm_repair(tmp_path, monkeypatch):
    problem_id = "prob_021"
    reference = next(row for row in normalized_rows() if row["id"] == problem_id)
    initial = load_initial(problem_id, ROOT / "runs/industryor/m3_z0_scoped_e2e_s0.jsonl")
    source = ROOT / "work/scoped_ir_e2e" / problem_id / "scoped_ir"
    destination = tmp_path / problem_id / "scoped_ir"
    destination.mkdir(parents=True)
    for name in ("author.json", "spec.json"):
        (destination / name).write_text((source / name).read_text())

    def no_llm(*args, **kwargs):
        raise AssertionError("the known API error must not invoke LLM repair")

    monkeypatch.setattr("scripts.scoped_ir_e2e.llm_mod.chat", no_llm)
    result = run_arm(problem_id, "scoped_ir", reference["description"], [], initial,
                     score_nlp4lp(reference, initial["solution"]), reference,
                     tmp_path, max_repairs=2, temperature=0.2, cfg={},
                     gate_cells=reference_cells(reference), progress_controller=True)
    assert result["final_score"]["business_correct"] is True
    assert result["history"][-1]["execution"]["objective"] == 81000
    assert result["final_score"]["objective_absolute_error"] == 0
    assert result["repair_calls"] == 0
    assert result["repair_usage"]["total_tokens"] == 0
    assert result["controller_transforms"] == 1
    assert result["controller_no_progress"] == 0
    assert result["harmed_win"] is False
    assert result["semantic_recovery"] is False
    assert [row["controller_decision"]["action"] for row in result["history"]] == [
        "specialized_api_repair", "stop"]
    assert code_sha256(result["initial_code"]) != code_sha256(result["final_code"])



def test_integrated_controller_changes_action_after_same_failure(tmp_path, monkeypatch):
    problem_id = "prob_021"
    reference = next(row for row in normalized_rows() if row["id"] == problem_id)
    initial = load_initial(problem_id, ROOT / "runs/industryor/m3_z0_scoped_e2e_s0.jsonl")
    initial["record"] = {"exec_status": "crash", "stderr_tail": "ValueError: synthetic failure"}
    source = ROOT / "work/scoped_ir_e2e" / problem_id / "scoped_ir"
    destination = tmp_path / problem_id / "scoped_ir"
    destination.mkdir(parents=True)
    for name in ("author.json", "spec.json"):
        (destination / name).write_text((source / name).read_text())
    responses = [initial["code"].replace("x1", "renamed"),
                 initial["code"].replace("x2", "alternate")]
    calls = []

    def llm_response(messages, **kwargs):
        calls.append(messages)
        return {"content": responses[len(calls) - 1],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    def same_failure(code, sandbox):
        return {"exec_status": "crash", "stderr_tail": "ValueError: synthetic failure"}

    monkeypatch.setattr("scripts.scoped_ir_e2e.llm_mod.chat", llm_response)
    monkeypatch.setattr("scripts.scoped_ir_e2e.run_code", same_failure)
    result = run_arm(problem_id, "scoped_ir", reference["description"], [], initial,
                     score_nlp4lp(reference, None), reference, tmp_path,
                     max_repairs=3, temperature=0.2, cfg={}, progress_controller=True)
    assert len(calls) == 2
    assert [row["action"] for row in result["controller_trace"]] == [
        "local_patch", "regenerate"]
    assert result["controller_no_progress"] == 2
    assert result["repair_usage"]["total_tokens"] == 30
    assert result["stop_reason"] == "no_progress_after_local_patch_and_regenerate"
    assert result["final_status"] == "unverified"
    assert "different COMPLETE model" in calls[1][-1]["content"]



def test_unvalidated_checker_cannot_accept_surface_clean_candidate():
    controller = ProgressController()
    decision = controller.decide("code", {}, {"status": "ok", "fired": False},
                                 remaining=3, checker_status="unvalidated")
    assert decision.action == "acquire_evidence"
    assert decision.reason == "checker_validation_required"


def test_unverified_last_candidate_falls_back_to_correct_initial(tmp_path, monkeypatch):
    problem_id = "prob_021"
    reference = next(row for row in normalized_rows() if row["id"] == problem_id)
    initial = load_initial(problem_id, ROOT / "runs/industryor/m3_z0_scoped_e2e_s0.jsonl")
    initial["solution"] = reference["solution"]
    initial["record"] = {"exec_status": "ok", "stderr_tail": ""}
    problem_dir = tmp_path / problem_id / "scoped_ir"
    problem_dir.mkdir(parents=True)
    witness = {"spec": {"invariants": []}, "gate": {"accepted": True}}
    (problem_dir / "author.json").write_text(json.dumps(witness))
    (problem_dir / "spec.json").write_text(json.dumps(witness["spec"]))
    monkeypatch.setattr("scripts.scoped_ir_e2e.audit",
                        lambda *args, **kwargs: {"status": "unknown", "fired": False,
                                                 "reason": "no_solution", "violations": []})
    monkeypatch.setattr("scripts.scoped_ir_e2e.llm_mod.chat",
                        lambda *args, **kwargs: {"content": "invalid code", "usage": {}})
    monkeypatch.setattr("scripts.scoped_ir_e2e.run_code",
                        lambda *args, **kwargs: {"exec_status": "crash",
                                                "stderr_tail": "SyntaxError: invalid"})
    initial_score = score_nlp4lp(reference, initial["solution"])
    result = run_arm(problem_id, "scoped_ir", reference["description"], [], initial,
                     initial_score, reference, tmp_path, max_repairs=1,
                     temperature=0.2, cfg={}, progress_controller=True)
    assert initial_score["business_correct"] is True
    assert result["baseline_fallback"] is True
    assert result["final_status"] == "baseline_fallback"
    assert result["final_score"]["business_correct"] is True
    assert result["last_candidate_score"]["business_correct"] is False
    assert result["harmed_win"] is False
