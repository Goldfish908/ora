import json
import types
from contextlib import nullcontext

import pytest

from scripts.open_jev_offline_eval import evaluate_model, pairwise_metrics


def prediction(pair, side, group, yes, no=0.0, tokens=10, latency=0.1):
    return {"id": f"{pair}:{side}", "group_id": group,
            "scores": [no, yes], "target": [0.0, 1.0],
            "input_tokens": tokens, "latency_seconds": latency}


def test_pairwise_metrics_groups_by_scenario_and_candidate_pair():
    rows = [prediction("p1", "chosen", "s1", 2.0),
            prediction("p1", "rejected", "s1", 1.0),
            prediction("p2", "chosen", "s1", 0.5),
            prediction("p2", "rejected", "s1", 1.5),
            prediction("p3", "chosen", "s2", 3.0),
            prediction("p3", "rejected", "s2", 0.5)]
    result = pairwise_metrics(rows)
    assert result["pairs"] == 3
    assert result["scenarios"] == 2
    assert result["correct"] == 2
    assert result["pairwise_accuracy"] == pytest.approx(2 / 3)
    assert result["macro_scenario_accuracy"] == pytest.approx(0.75)
    assert result["nonzero_margin_coverage"] == 1.0
    assert result["total_input_tokens"] == 60
    assert result["total_latency_seconds"] == pytest.approx(0.6)


def test_pairwise_metrics_rejects_incomplete_and_duplicate_pairs():
    with pytest.raises(ValueError, match="incomplete"):
        pairwise_metrics([prediction("p1", "chosen", "s1", 1.0)])
    with pytest.raises(ValueError, match="duplicate"):
        pairwise_metrics([prediction("p1", "chosen", "s1", 1.0),
                          prediction("p1", "chosen", "s1", 2.0),
                          prediction("p1", "rejected", "s1", 0.0)])


def test_pairwise_metrics_rejects_empty_input():
    with pytest.raises(ValueError, match="no candidate pairs"):
        pairwise_metrics([])



def test_evaluate_model_writes_tenth_progress_record(tmp_path, monkeypatch):
    class Scores:
        def float(self):
            return self

        def cpu(self):
            return self

        def tolist(self):
            return [0.0, 1.0]

    class Model:
        last_input_tokens = 10

        @classmethod
        def load(cls, checkpoint, device):
            return cls()

        def __call__(self, rows):
            return [Scores()]

    fake_torch = types.SimpleNamespace(
        inference_mode=lambda: nullcontext(),
        cuda=types.SimpleNamespace(synchronize=lambda: None, empty_cache=lambda: None),
    )
    monkeypatch.setitem(__import__("sys").modules, "torch", fake_torch)
    monkeypatch.setitem(__import__("sys").modules, "jev", types.ModuleType("jev"))
    monkeypatch.setitem(__import__("sys").modules, "jev.model",
                        types.SimpleNamespace(DecisionModel=Model))
    rows = [{"id": f"p{i}:chosen", "group_id": "s1", "target": [0.0, 1.0]}
            for i in range(10)]
    output = tmp_path / "predictions.jsonl"
    predictions = evaluate_model(tmp_path / "checkpoint", rows, "cuda:0", output)
    assert len(predictions) == 10
    assert len(output.read_text().splitlines()) == 10
    assert json.loads(output.read_text().splitlines()[-1])["scores"] == [0.0, 1.0]
