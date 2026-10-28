#!/usr/bin/env python3
"""Freeze pre-execution predictions for fork-sampling candidates.

Writes one prediction file per candidate into <workdir>/frozen_predictions/
BEFORE any candidate is executed. Uses the same QwenShadowPredictor as the
live agent loop. Run fork_sample.py only after this completes.

Usage:
  source ~/.leagent_env
  export ORA_LLM_BASE_URL="$DISTILL_BASE_URL" ORA_LLM_API_KEY="$DISTILL_API_KEY" ORA_LLM_MODEL="qwen3.8-27b"
  python3 scripts/freeze_predictions.py \
    --trajectory runs/<job>/<trial>/agent/ora/trajectory.jsonl \
    --upto-seq 6 --candidates candidates.json --workdir runs/fork_x
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ora_agent import llm as llm_mod
from ora_agent.predict import QwenShadowPredictor


def history_summary(trajectory: Path, upto_seq: int) -> str:
    lines = []
    outcomes = {}
    for line in trajectory.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e.get("event") == "outcome" and e.get("seq") is not None:
            outcomes[e["seq"]] = e.get("classification")
    for line in trajectory.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e.get("event") != "action":
            continue
        a = e.get("action") or {}
        seq = e.get("seq")
        if seq is None or seq > upto_seq or a.get("tool") != "bash":
            continue
        cls = outcomes.get(seq, "?")
        lines.append(f"seq{seq} [{a.get('action_kind')}] "
                     f"{(a.get('command') or '')[:120]!r} -> {cls}")
    return "\n".join(lines[-12:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trajectory", required=True, type=Path)
    ap.add_argument("--upto-seq", required=True, type=int)
    ap.add_argument("--candidates", required=True, type=Path)
    ap.add_argument("--workdir", required=True, type=Path)
    args = ap.parse_args()

    summary = history_summary(args.trajectory, args.upto_seq)
    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    cfg = llm_mod.load_config()
    predictor = QwenShadowPredictor(
        lambda m, **kw: llm_mod.chat(m, config=cfg, **kw))

    out_dir = args.workdir / "frozen_predictions"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, cand in enumerate(candidates):
        action = {"tool": "bash", "command": cand["command"],
                  "action_kind": cand.get("action_kind", "other"),
                  "rationale": cand.get("rationale", "")}
        ahash = hashlib.sha256(action["command"].encode()).hexdigest()[:16]
        pred = predictor.predict(summary, action, {"fork_index": i})
        rec = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "frozen_before_execution": True,
            "fork_index": i,
            "action": action,
            "action_hash": ahash,
            "history_summary": summary,
            "prediction_input_sha256": hashlib.sha256(
                json.dumps({"history": summary, "action": action},
                           ensure_ascii=False).encode()).hexdigest(),
            "prediction": pred,
        }
        p = out_dir / f"cand{i}_{ahash}.json"
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
        manifest.append({"fork_index": i, "action_hash": ahash,
                         "file": str(p.name),
                         "will_succeed_prob": pred.get("will_succeed_prob"),
                         "unknown": pred.get("unknown", False)})
        print(f"[freeze] cand{i} hash={ahash} "
              f"p={pred.get('will_succeed_prob')} unknown={pred.get('unknown', False)}")
    (args.workdir / "frozen_predictions_manifest.json").write_text(
        json.dumps({"upto_seq": args.upto_seq,
                    "n_candidates": len(candidates),
                    "predictor": predictor.mode,
                    "frozen_at": datetime.now(timezone.utc).isoformat(),
                    "candidates": manifest}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
