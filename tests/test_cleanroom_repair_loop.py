from types import SimpleNamespace

from ora_agent.cleanroom import EvidenceMemory
from ora_agent import cleanroom_witness


def setup_loop(monkeypatch, outcomes):
    memory = EvidenceMemory()
    packet = SimpleNamespace(name="task", domain="manufacturing", split="dev",
                             scope={"dataset": "oragentbench", "domain": "manufacturing"})
    record = {"task": "task", "true_correct": False, "phantom_proxy": False,
              "execution": {"return_code": 1}, "official": {"evaluation": {"errors": ["bad"]}},
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


def test_changed_error_text_without_progress_stops(tmp_path, monkeypatch):
    memory, packet, record, _ = setup_loop(monkeypatch, outcomes=99)

    def unchanged(memory, packet, current, specification, config, outdir, run_seed, **kwargs):
        child = dict(current)
        child.update(workspace="different/app", official={"evaluation": {"errors": ["different"]}})
        return {"status": "rejected", "record": child, "node_id": "different",
                "before": {"execution_contract": "fail"}, "after": {"execution_contract": "fail"},
                "edge_accepted": False, "final_accept": False}

    monkeypatch.setattr(cleanroom_witness, "repair_once", unchanged)
    result = cleanroom_witness.repair_bounded(memory, packet, record, "spec", None, tmp_path)
    assert result["status"] == "no_verified_progress"
    assert result["attempts_used"] == 1
    assert result["record"] is record
    assert result["history"][0]["evidence_transition"] == "unchanged"
