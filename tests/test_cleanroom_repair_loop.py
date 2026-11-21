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
