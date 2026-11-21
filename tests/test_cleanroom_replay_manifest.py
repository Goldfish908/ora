import json
import sys
from pathlib import Path
from types import SimpleNamespace

from ora_agent.cleanroom_analysis import generation_cost
from scripts.cleanroom_experiment import digest
from scripts import cleanroom_replay


def test_replay_manifest_records_no_evolution_and_disjoint_batch(tmp_path, monkeypatch):
    result = tmp_path / "gepa_result.json"
    result.write_text(json.dumps({"candidates": [{"conventions": ""}, {"conventions": "new spec"}]}))
    (tmp_path / "analysis.json").write_text(json.dumps({"train_ids": ["dev"], "val_ids": ["transfer"]}))
    packets = [SimpleNamespace(name="new_task", domain="manufacturing", split="final",
                               scope={"dataset": "oragentbench", "domain": "manufacturing"})]
    monkeypatch.setattr(cleanroom_replay, "load_tasks", lambda _: packets)
    monkeypatch.setattr(cleanroom_replay.llm_mod, "load_config", lambda: SimpleNamespace(model="test-model"))

    def fake_rollout(self, packet, candidate):
        workspace = self.outdir / "rollouts" / digest(candidate["conventions"]) / packet.name / "attempt_0/app"
        workspace.mkdir(parents=True)
        record = {"task": packet.name, "split": packet.split,
                  "candidate_sha256": digest(candidate["conventions"]), "attempt": 0,
                  "workspace": str(workspace), "execution": {"return_code": 0},
                  "official": {"runner": {"return_code": 0}, "evaluation": {"errors": []},
                               "reward_details": {}}, "feasible": True, "quality": 0.8,
                  "true_correct": True, "objective": 1.0, "proxy_match": True, "phantom_proxy": False,
                  "generation_error": None}
        (workspace.parent / "record.json").write_text(json.dumps(record))
        return record

    monkeypatch.setattr(cleanroom_replay.CleanroomAdapter, "_rollout", fake_rollout)
    out = tmp_path / "replay"
    monkeypatch.setattr(sys, "argv", ["cleanroom_replay.py", "--tasks",
                                     "configs/cleanroom_manufacturing_smoke_tasks.json",
                                     "--run-dir", str(out), "--gepa-result", str(result),
                                     "--candidate-idx", "1"])
    cleanroom_replay.main()
    summary = json.loads((out / "replay_result.json").read_text())
    manifest = json.loads((out / "run.json").read_text())
    assert summary["true_correct"] == 1
    assert summary["provenance"] == "subsequent_disjoint_replay"
    assert summary["evolution_performed"] is False
    assert summary["feedback_returned_to_generator"] is False
    assert summary["specification_sha256"]["new_task"] == digest("new spec")
    assert manifest["evaluation"]["memory_frozen"] is False
    assert Path(manifest["records"][0]["record_path"]).exists()
