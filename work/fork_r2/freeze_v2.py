#!/usr/bin/env python3
"""Freeze v2 predictions for fork candidates (thinking off, fast).

Mirrors scripts/freeze_predictions.py but injects extra={"enable_thinking":
false} — freeze_predictions itself keeps the actor default (thinking on).
"""
import sys, json, hashlib
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from ora_agent import llm as llm_mod
from ora_agent.predict import QwenShadowPredictor
from freeze_predictions import history_summary

ROOT = Path(__file__).resolve().parents[2]
TRAJ = ROOT / "runs/b2_round2/cell_tower_coverage_expansion__Ysywe9y/agent/ora/trajectory.jsonl"
CANDS = ROOT / "work/fork_r2/candidates.json"
OUT = ROOT / "runs/fork_r2_celltower/frozen_predictions"
UPTO = 17

def main():
    summary = history_summary(TRAJ, UPTO)
    candidates = json.loads(CANDS.read_text())
    cfg = llm_mod.load_config()
    llm_fn = lambda m, **kw: llm_mod.chat(m, config=cfg,
                                          extra={"enable_thinking": False}, **kw)
    predictor = QwenShadowPredictor(llm_fn)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, cand in enumerate(candidates):
        action = {"tool": "bash", "command": cand["command"],
                  "action_kind": cand.get("action_kind", "other"),
                  "rationale": cand.get("rationale", "")}
        ahash = hashlib.sha256(action["command"].encode()).hexdigest()[:16]
        pred = predictor.predict(summary, action, {"fork_index": i})
        rec = {"created_at": datetime.now(timezone.utc).isoformat(),
               "frozen_before_execution": True,
               "fork_index": i, "action": action, "action_hash": ahash,
               "history_summary": summary,
               "prediction_input_sha256": hashlib.sha256(
                   json.dumps({"history": summary, "action": action},
                              ensure_ascii=False).encode()).hexdigest(),
               "prediction": pred}
        p = OUT / f"cand{i}_{ahash}.json"
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
        manifest.append({"fork_index": i, "action_hash": ahash,
                         "file": p.name,
                         "will_succeed_prob": pred.get("will_succeed_prob"),
                         "unknown": pred.get("unknown", False)})
        print(f"[freeze] cand{i} hash={ahash} "
              f"p={pred.get('will_succeed_prob')} unknown={pred.get('unknown', False)}",
              flush=True)
    (OUT.parent / "frozen_predictions_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n")

if __name__ == "__main__":
    main()
