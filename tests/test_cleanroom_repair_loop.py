from types import SimpleNamespace

from ora_agent.cleanroom import EvidenceMemory
from ora_agent import cleanroom_witness


def setup_loop(monkeypatch, outcomes):
    memory = EvidenceMemory()
    packet = SimpleNamespace(name="task", domain="manufacturing", split="dev",
                             scope={"dataset": "oragentbench", "domain": "manufacturing"})
    record = {"task": "task", "true_correct": False, "phantom_proxy": False,
              "execution": {"return_code": 1},
              "official": {"evaluation": {"errors": ["bad"]},
                           "reward": {"feasibility": 0.0, "quality": 0.0}, "reward_details": {},
                           "runner": {"return_code": 0, "timed_out": False}},
              "artifacts": {"solve_py": "old"}, "workspace": "original/app",
              "feasible": False, "quality": 0.0, "objective": None, "candidate_sha256": "spec"}
    monkeypatch.setattr(cleanroom_witness, "evaluate_witness",
                        lambda *args: {"execution_contract": "fail"})
    calls = []

    def fake_repair(memory, packet, current, specification, config, outdir, run_seed, **kwargs):
        calls.append(kwargs)
        accepted = len(calls) == outcomes
        child = dict(current)
        child.update(true_correct=accepted, workspace=f"child{len(calls)}/app",
                     execution={"return_code": 0}, feasible=accepted, quality=1.0 if accepted else 0.0)
        return {"status": "accepted" if accepted else "rejected", "record": child,
                "node_id": f"node{len(calls)}", "before": {"execution_contract": "fail"},
                "after": {"execution_contract": "pass" if accepted else "fail"},
                "edge_accepted": accepted, "final_accept": accepted}

    monkeypatch.setattr(cleanroom_witness, "repair_once", fake_repair)
    return memory, packet, record, calls


def test_bounded_loop_preserves_direct_baseline_until_final_acceptance(tmp_path, monkeypatch):
    memory, packet, record, calls = setup_loop(monkeypatch, outcomes=2)
    result = cleanroom_witness.repair_bounded(memory, packet, record, "spec", None, tmp_path)
    assert result["status"] == "accepted"
    assert result["attempts_used"] == 2
    assert result["record"]["true_correct"]
    assert result["win_safe"]
    assert result["memory_frozen"]
    assert len(calls) == 2
    assert calls[0]["parent_id"] == "root"
    assert calls[1]["parent_id"] == "node1"
    assert result["cost"]["llm_calls"] == 0


def test_bounded_loop_never_repairs_existing_win(tmp_path, monkeypatch):
    memory, packet, record, calls = setup_loop(monkeypatch, outcomes=1)
    record["true_correct"] = True
    result = cleanroom_witness.repair_bounded(memory, packet, record, "spec", None, tmp_path)
    assert result["status"] == "preserved_win"
    assert result["attempts_used"] == 0
    assert calls == []


def test_bounded_loop_stops_on_duplicate_and_keeps_baseline(tmp_path, monkeypatch):
    memory, packet, record, calls = setup_loop(monkeypatch, outcomes=1)

    def duplicate(*args, **kwargs):
        return {"status": "duplicate_repair", "record": dict(record),
                "before": {"execution_contract": "fail"}, "after": {"execution_contract": "fail"}}

    monkeypatch.setattr(cleanroom_witness, "repair_once", duplicate)
    result = cleanroom_witness.repair_bounded(memory, packet, record, "spec", None, tmp_path)
    assert result["status"] == "duplicate_repair"
    assert result["attempts_used"] == 1
    assert result["record"] is record
    assert not result["record"]["true_correct"]
    assert not result["final_accept"]


def test_rejected_regression_retries_from_best_parent(tmp_path, monkeypatch):
    memory, packet, record, _ = setup_loop(monkeypatch, outcomes=99)
    parents = []

    def branch(memory, packet, current, specification, config, outdir, run_seed, **kwargs):
        attempt = len(parents) + 1
        parents.append(kwargs["parent_id"])
        child = dict(current)
        child["workspace"] = f"branch{attempt}/app"
        status = "rejected"
        if attempt == 1:
            child.update(execution={"return_code": 0}, official={"evaluation": {"errors": ["one"]}})
            node_id = "best"
        elif attempt == 2:
            child.update(official={"evaluation": {"errors": ["one", "two", "three"]}})
            node_id = "bad"
        else:
            child.update(true_correct=True, feasible=True, quality=1.0,
                         official={"evaluation": {"errors": []}})
            node_id = "win"
            status = "accepted"
        return {"status": status, "record": child, "node_id": node_id,
                "before": {"execution_contract": "fail"},
                "after": {"execution_contract": "pass" if status == "accepted" else "fail"},
                "edge_accepted": status == "accepted", "final_accept": status == "accepted"}

    monkeypatch.setattr(cleanroom_witness, "repair_once", branch)
    result = cleanroom_witness.repair_bounded(memory, packet, record, "spec", None, tmp_path)
    assert parents == ["root", "best", "best"]
    assert result["status"] == "accepted"
    assert result["attempts_used"] == 3
    assert result["record"]["true_correct"]
    assert [row["evidence_transition"] for row in result["history"]] == [
        "progress", "regression", "progress"]


def test_runtime_diagnostic_advances_only_the_working_branch(tmp_path, monkeypatch):
    memory, packet, record, _ = setup_loop(monkeypatch, outcomes=99)
    record["execution"]["stderr"] = "initial runtime error"
    parents = []

    def branch(memory, packet, current, specification, config, outdir, run_seed, **kwargs):
        attempt = len(parents) + 1
        parents.append(kwargs["parent_id"])
        child = dict(current)
        child["workspace"] = f"runtime{attempt}/app"
        child["execution"] = {"return_code": 1, "stderr": f"runtime error {attempt}"}
        status = "rejected"
        if attempt == 3:
            child.update(true_correct=True, feasible=True, quality=1.0,
                         execution={"return_code": 0}, official={"evaluation": {"errors": []}})
            status = "accepted"
        return {"status": status, "record": child, "node_id": f"runtime_node{attempt}",
                "before": {"execution_contract": "fail"},
                "after": {"execution_contract": "pass" if status == "accepted" else "fail"},
                "edge_accepted": status == "accepted", "final_accept": status == "accepted"}

    monkeypatch.setattr(cleanroom_witness, "repair_once", branch)
    result = cleanroom_witness.repair_bounded(memory, packet, record, "spec", None, tmp_path)
    assert parents == ["root", "runtime_node1", "runtime_node2"]
    assert result["status"] == "accepted"
    assert result["attempts_used"] == 3
    assert [row["evidence_transition"] for row in result["history"]] == [
        "unchanged", "unchanged", "progress"]
    assert [row.get("working_branch_advanced", False) for row in result["history"]] == [
        True, True, False]


def test_changed_error_text_without_progress_stops(tmp_path, monkeypatch):
    memory, packet, record, _ = setup_loop(monkeypatch, outcomes=99)
    attempts = []

    def unchanged(memory, packet, current, specification, config, outdir, run_seed, **kwargs):
        attempts.append(kwargs["attempt"])
        child = dict(current)
        child.update(workspace="different/app", official={"evaluation": {"errors": ["different"]}})
        return {"status": "rejected", "record": child, "node_id": "different",
                "before": {"execution_contract": "fail"}, "after": {"execution_contract": "fail"},
                "edge_accepted": False, "final_accept": False}

    monkeypatch.setattr(cleanroom_witness, "repair_once", unchanged)
    result = cleanroom_witness.repair_bounded(memory, packet, record, "spec", None, tmp_path)
    assert result["status"] == "no_verified_progress"
    assert result["attempts_used"] == 2
    assert attempts == [1, 2]
    assert result["record"] is record
    assert [row["evidence_transition"] for row in result["history"]] == ["unchanged", "unchanged"]


def test_generation_failure_is_supplied_to_the_next_attempt(tmp_path, monkeypatch):
    memory, packet, record, _ = setup_loop(monkeypatch, outcomes=99)
    attempts = []

    def branch(memory, packet, current, specification, config, outdir, run_seed, **kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            return {"status": "repair_failed", "error": "ValueError: ambiguous patch",
                    "before": {"execution_contract": "fail"}}
        child = dict(current)
        child.update(true_correct=True, workspace="recovered/app", execution={"return_code": 0},
                     feasible=True, quality=1.0, official={"evaluation": {"errors": []}})
        return {"status": "accepted", "record": child, "node_id": "recovered",
                "before": {"execution_contract": "fail"}, "after": {"execution_contract": "pass"},
                "edge_accepted": True, "final_accept": True}

    monkeypatch.setattr(cleanroom_witness, "repair_once", branch)
    result = cleanroom_witness.repair_bounded(memory, packet, record, "spec", None, tmp_path)
    assert result["status"] == "accepted"
    assert attempts[0]["previous_generation_failure"] is None
    assert attempts[1]["previous_generation_failure"] == "ValueError: ambiguous patch"


def test_repeated_incomplete_artifact_switches_to_evidence_regeneration():
    record = {"generation_error": "ValueError: incomplete_artifact: no solver optimize call",
              "execution": {"return_code": -1}}
    assert not cleanroom_witness._regenerate_from_evidence(record, 1, None)
    assert not cleanroom_witness._regenerate_from_evidence(record, 2, None)
    assert cleanroom_witness._regenerate_from_evidence(
        record, 2, "ValueError: incomplete_artifact: no solver optimize call")
    record["generation_error"] = None
    assert not cleanroom_witness._regenerate_from_evidence(
        record, 2, "ValueError: incomplete_artifact")
    record["execution"] = {"return_code": 0}
    assert cleanroom_witness._regenerate_from_evidence(record, 2, None)


def test_execution_recovery_is_progress_even_with_more_specific_business_errors():
    current = {"true_correct": False, "feasible": False, "phantom_proxy": False,
               "unknown": False, "objective": None, "quality": 0.0,
               "execution": {"return_code": 1}, "official": {"evaluation": {"errors": ["No solution file found."]}}}
    child = dict(current, execution={"return_code": 0},
                 official={"evaluation": {"errors": ["missing patient p0", "missing patient p1"]}})
    assert cleanroom_witness._evidence_transition(current, child) == "progress"
    child["phantom_proxy"] = True
    assert cleanroom_witness._evidence_transition(current, child) == "regression"


def test_quality_shortfall_has_explicit_objective_guidance_without_a_reference_target():
    guidance = cleanroom_witness._quality_guidance(
        {"feasible": True, "true_correct": False, "quality": 0.0, "objective": 123.0,
         "official": {"reward_details": {"objective_sense": "minimize",
                                        "quality_status": "bound_gap_below_mip_gap"}}})
    assert guidance["status"] == "quality_shortfall"
    assert guidance["objective"] == 123.0
    assert guidance["objective_sense"] == "minimize"
    assert guidance["quality_status"] == "bound_gap_below_mip_gap"
    assert "emitted decisions" in guidance["instruction"]
    assert "fabricate a reference objective" in guidance["instruction"]
    assert cleanroom_witness._quality_guidance({"feasible": False, "true_correct": False}) is None


def test_second_semantic_regeneration_uses_empty_specification_branch(tmp_path, monkeypatch):
    memory, packet, record, _ = setup_loop(monkeypatch, outcomes=99)
    specifications = []

    def branch(memory, packet, current, specification, config, outdir, run_seed, **kwargs):
        specifications.append(specification)
        accepted = len(specifications) == 2
        child = dict(current)
        child.update(true_correct=accepted, workspace=f"branch{len(specifications)}/app",
                     execution={"return_code": 0}, feasible=accepted, quality=1.0 if accepted else 0.0)
        return {"status": "accepted" if accepted else "rejected", "record": child,
                "node_id": f"node{len(specifications)}", "before": {"execution_contract": "fail"},
                "after": {"execution_contract": "pass" if accepted else "fail"},
                "edge_accepted": accepted, "final_accept": accepted}

    monkeypatch.setattr(cleanroom_witness, "repair_once", branch)
    result = cleanroom_witness.repair_bounded(memory, packet, record, "spec", None, tmp_path)
    assert result["status"] == "accepted"
    assert specifications == ["spec", ""]
    assert result["attempts_used"] == 2
    assert result["history"][1]["specification_sha256"] == \
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_feasible_nonphantom_is_best_effort_not_accepted(tmp_path, monkeypatch):
    memory, packet, record, _ = setup_loop(monkeypatch, outcomes=99)
    record.update(phantom_proxy=True, feasible=False, quality=0.0, objective=100.0)
    record["official"]["reward_details"] = {"objective_sense": "minimize"}

    def better(*args, **kwargs):
        child = dict(record)
        child.update(workspace="better/app", feasible=True, phantom_proxy=False, objective=90.0,
                     execution={"return_code": 0})
        return {"status": "rejected", "record": child, "node_id": "better",
                "before": {"execution_contract": "pass"}, "after": {"execution_contract": "pass"},
                "edge_accepted": False, "final_accept": False}

    monkeypatch.setattr(cleanroom_witness, "repair_once", better)
    result = cleanroom_witness.repair_bounded(memory, packet, record, "spec", None, tmp_path,
                                              max_attempts=1)
    assert result["status"] == "best_effort_fallback"
    assert not result["final_accept"]
    assert not result["record"]["true_correct"]
    assert result["record"]["feasible"]
    assert not result["record"]["phantom_proxy"]
    assert result["pair_win_safe"]["removed_phantom"] == ["task"]
    assert result["after"] == {"execution_contract": "pass"}


def test_best_effort_cannot_accept_infeasible_or_new_true_candidate():
    baseline = {"true_correct": False, "phantom_proxy": True, "feasible": False,
                "quality": 0.0, "execution": {"return_code": 0}}
    infeasible = dict(baseline, phantom_proxy=False)
    assert not cleanroom_witness._best_effort_fallback(baseline, infeasible)
    new_true = dict(infeasible, feasible=True, true_correct=True)
    assert not cleanroom_witness._best_effort_fallback(baseline, new_true)


def test_decision_repair_requires_incumbent_and_business_failure(tmp_path):
    workspace = tmp_path / "app"
    (workspace / "submissions").mkdir(parents=True)
    incumbent = workspace / "submissions/solution.csv"
    incumbent.write_text("a,b\n1,2\n")
    record = {"workspace": str(workspace), "true_correct": False, "feasible": False,
              "execution": {"return_code": 0}, "official": {"evaluation": {"errors": ["bad"]}}}
    assert cleanroom_witness._decision_repair_eligible(record)
    record["feasible"] = True
    assert not cleanroom_witness._decision_repair_eligible(record)
    record["feasible"] = False
    incumbent.unlink()
    assert not cleanroom_witness._decision_repair_eligible(record)


def test_decision_runtime_patch_route_requires_failed_decision_script():
    record = {"artifacts": {"repair_solution_py": "code"},
              "execution": {"return_code": 1, "stderr": "TypeError"}}
    assert cleanroom_witness._decision_repair_mode(record, 2) == "decision_runtime_patch"
    record["execution"]["return_code"] = 0
    assert cleanroom_witness._decision_repair_mode(record, 2) is None


def test_decision_business_failure_gets_one_followup_before_model_rebuild(tmp_path):
    workspace = tmp_path / "app"
    (workspace / "submissions").mkdir(parents=True)
    (workspace / "submissions/solution.csv").write_text("a,b\n1,2\n")
    record = {"workspace": str(workspace), "true_correct": False, "feasible": False,
              "execution": {"return_code": 0}, "official": {"evaluation": {"errors": ["bad"]}},
              "artifacts": {"repair_solution_py": "old repair code"}}
    assert cleanroom_witness._decision_repair_mode(record, 1) == "decision_repair"
    assert cleanroom_witness._decision_repair_mode(record, 2) == "decision_repair"
    assert cleanroom_witness._decision_repair_mode(record, 3) is None


def test_objective_improvement_is_progress_and_best_effort_rejects_degradation():
    current = {
        "true_correct": False, "feasible": True, "phantom_proxy": False,
        "quality": 0.0, "objective": 100.0, "execution": {"return_code": 0},
        "official": {"evaluation": {"errors": []},
                     "reward_details": {"objective_sense": "minimize"}},
    }
    child = dict(current, objective=80.0)
    assert cleanroom_witness._evidence_transition(current, child) == "progress"
    baseline = dict(current, feasible=False, phantom_proxy=True)
    degraded = dict(current, objective=10000.0)
    assert not cleanroom_witness._best_effort_fallback(baseline, degraded)
    assert cleanroom_witness._best_effort_fallback(baseline, child)


def test_objective_change_without_sense_is_not_verified_progress():
    current = {
        "true_correct": False, "feasible": True, "phantom_proxy": False,
        "quality": 0.0, "objective": 100.0, "execution": {"return_code": 0},
        "official": {"evaluation": {"errors": []}, "reward_details": {}},
    }
    child = dict(current, objective=80.0)
    assert cleanroom_witness._evidence_transition(current, child) == "unchanged"
    baseline = dict(current, feasible=False, phantom_proxy=True)
    assert not cleanroom_witness._best_effort_fallback(baseline, child)


def test_all_unmet_fallback_routes_to_model_diagnosis_not_decision_repair(tmp_path):
    workspace = tmp_path / "app"
    (workspace / "submissions").mkdir(parents=True)
    solution = workspace / "submissions/solution.csv"
    solution.write_text("row_type,locker_id,zone_id,value\nunmet,,z1,10\nunmet,,z2,20\n")
    record = {
        "workspace": str(workspace), "true_correct": False, "feasible": False,
        "execution": {"return_code": 0}, "official": {"evaluation": {"errors": ["service floor"]}},
    }
    assert not cleanroom_witness.has_genuine_incumbent(record)
    assert cleanroom_witness.repair_route(record) == "model_diagnosis"
    assert cleanroom_witness._decision_repair_mode(record, 1) is None
    solution.write_text(
        "row_type,locker_id,zone_id,value\nassignment,l1,z1,5\nunmet,,z1,5\nunmet,,z2,20\n",
    )
    assert cleanroom_witness.has_genuine_incumbent(record)
    assert cleanroom_witness.repair_route(record) == "decision_repair"
    assert cleanroom_witness._decision_repair_mode(record, 1) == "decision_repair"


def test_feasible_quality_shortfall_routes_to_objective_optimization():
    record = {
        "true_correct": False, "feasible": True, "quality": 0.0,
        "execution": {"return_code": 0}, "workspace": "unused",
    }
    assert cleanroom_witness.repair_route(record) == "objective_optimization"


def test_feasible_checkpoint_survives_later_runtime_regression(tmp_path, monkeypatch):
    memory, packet, record, _ = setup_loop(monkeypatch, outcomes=99)

    def branch(memory, packet, current, specification, config, outdir, run_seed, **kwargs):
        attempt = kwargs["attempt"]
        child = dict(current)
        child["workspace"] = f"checkpoint{attempt}/app"
        if attempt == 1:
            child.update(execution={"return_code": 0}, feasible=False,
                         official={"evaluation": {"errors": ["one"]}})
            after = {"execution_contract": "pass"}
        elif attempt == 2:
            child.update(execution={"return_code": 0}, feasible=True, quality=0.0, objective=477.0,
                         official={"evaluation": {"errors": []},
                                   "reward_details": {"objective_sense": "minimize"}})
            after = {"execution_contract": "pass"}
        else:
            child.update(execution={"return_code": 1, "stderr": "quicksum received list"},
                         feasible=False, objective=None,
                         official={"evaluation": {"errors": ["No solution file found."]}})
            after = {"execution_contract": "fail"}
        return {"status": "rejected", "record": child, "node_id": f"checkpoint{attempt}",
                "before": {"execution_contract": "pass"}, "after": after,
                "edge_accepted": False, "final_accept": False}

    monkeypatch.setattr(cleanroom_witness, "repair_once", branch)
    result = cleanroom_witness.repair_bounded(memory, packet, record, "spec", None, tmp_path)
    assert result["attempts_used"] == 3
    assert result["record"] is record
    assert result["checkpoint_record"]["workspace"] == "checkpoint2/app"
    assert result["checkpoint_record"]["feasible"]
    assert result["checkpoint_route"] == "objective_optimization"
    assert result["checkpoint_record_path"] == "checkpoint2/record.json"


def test_fixed_specification_regeneration_does_not_silently_switch_to_empty(tmp_path, monkeypatch):
    memory, packet, record, _ = setup_loop(monkeypatch, outcomes=99)
    specifications = []

    def branch(memory, packet, current, specification, config, outdir, run_seed, **kwargs):
        specifications.append(specification)
        accepted = len(specifications) == 2
        child = dict(current)
        child.update(true_correct=accepted, workspace=f"fixed{len(specifications)}/app",
                     execution={"return_code": 0}, feasible=accepted, quality=1.0 if accepted else 0.0)
        return {"status": "accepted" if accepted else "rejected", "record": child,
                "node_id": f"fixed{len(specifications)}", "before": {"execution_contract": "fail"},
                "after": {"execution_contract": "pass" if accepted else "fail"},
                "edge_accepted": accepted, "final_accept": accepted}

    monkeypatch.setattr(cleanroom_witness, "repair_once", branch)
    result = cleanroom_witness.repair_bounded(
        memory, packet, record, "frozen-spec", None, tmp_path,
        allow_empty_spec_regeneration=False,
    )
    assert result["status"] == "accepted"
    assert specifications == ["frozen-spec", "frozen-spec"]
