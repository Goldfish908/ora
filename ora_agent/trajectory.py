"""JSONL trajectory writer for ora_agent. Stdlib only.

Event types: run_meta / context_init / msg_append / llm_request /
llm_response / action / prediction / outcome / budget / finish / warning
(plus "error" surfaced via an `error` field on any event).

Every record carries: ts (UTC ISO-8601), run_id, task_id, model, state_id
(monotonically increasing within the run) and parent_state (previous
state_id, forming a chain). Event-specific fields (action_hash, usage,
error classification, prediction file references, ...) are passed through.

Writes are flushed and fsync'd per event: trajectory completeness matters
more than throughput here (a crashed run must still leave its trace).

run_summary.json: after EVERY event the writer incrementally rewrites
<out_dir>/run_summary.json (atomically, tmp+rename+fsync) with the latest
status / per-role usage / n_steps / last_state_id / last artifact
observation. If the process is killed (e.g. harbor agent timeout), the
summary still reflects the most recent event; a clean finish overwrites
status with the terminal state via update_summary(status=...).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPES = frozenset({
    "run_meta", "context_init", "msg_append", "llm_request", "llm_response",
    "action", "prediction", "outcome", "budget", "finish", "warning",
    "worker_call", "worker_response",
})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_role_usage() -> dict:
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "latency_s": 0.0}


class TrajectoryWriter:
    def __init__(self, path, *, run_id: str, task_id: str, model: str,
                 summary_path=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.task_id = task_id
        self.model = model
        self._state_id = 0
        self._fp = open(self.path, "a", encoding="utf-8")
        self.summary_path = (Path(summary_path) if summary_path
                             else self.path.parent / "run_summary.json")
        self._summary = {
            "run_id": run_id,
            "task_id": task_id,
            "model": model,
            "status": "running",
            "ts_started": _utc_now_iso(),
            "n_steps": 0,
            "last_state_id": 0,
            "actor_usage": _empty_role_usage(),
            "predictor_usage": _empty_role_usage(),
            "worker_usage": _empty_role_usage(),
            "artifacts_last_observed": None,
        }
        self._write_summary()

    # -- summary maintenance -------------------------------------------------

    def _write_summary(self) -> None:
        tmp = self.summary_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._summary, f, ensure_ascii=False, indent=2,
                      default=str)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.summary_path)

    def _auto_summary(self, record: dict) -> None:
        """Fold a just-written event into the incremental summary."""
        self._summary["last_state_id"] = record["state_id"]
        self._summary["ts_updated"] = record["ts"]
        ev = record.get("event")
        if ev == "llm_response" and not record.get("error"):
            u = record.get("usage") or {}
            a = self._summary["actor_usage"]
            a["calls"] += 1
            a["prompt_tokens"] += u.get("prompt_tokens") or 0
            a["completion_tokens"] += u.get("completion_tokens") or 0
            a["latency_s"] = round(a["latency_s"]
                                   + (record.get("latency_s") or 0.0), 3)
        elif ev == "prediction":
            meta = (record.get("prediction") or {}).get("predictor_meta") or {}
            u = meta.get("usage") or {}
            p = self._summary["predictor_usage"]
            p["calls"] += 1
            p["prompt_tokens"] += u.get("prompt_tokens") or 0
            p["completion_tokens"] += u.get("completion_tokens") or 0
            p["latency_s"] = round(p["latency_s"]
                                   + (meta.get("latency_s") or 0.0), 3)
        elif ev == "worker_response" and not record.get("error"):
            u = record.get("usage") or {}
            w = self._summary["worker_usage"]
            w["calls"] += 1
            w["prompt_tokens"] += u.get("prompt_tokens") or 0
            w["completion_tokens"] += u.get("completion_tokens") or 0
            w["latency_s"] = round(w["latency_s"]
                                   + (record.get("latency_s") or 0.0), 3)
        elif ev == "action" and isinstance(record.get("seq"), int):
            self._summary["n_steps"] = max(self._summary["n_steps"],
                                           record["seq"])
        self._write_summary()

    def update_summary(self, **fields) -> None:
        """Merge fields into run_summary.json (e.g. terminal status,
        artifacts_last_observed, decision_integration)."""
        self._summary.update(fields)
        self._write_summary()

    @property
    def summary(self) -> dict:
        return dict(self._summary)

    # -- event stream ---------------------------------------------------------

    def emit(self, event: str, **fields) -> dict:
        record = {
            "ts": _utc_now_iso(),
            "event": event,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "model": self.model,
            "state_id": self._state_id + 1,
            "parent_state": self._state_id or None,
        }
        record.update(fields)
        self._fp.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._fp.flush()
        os.fsync(self._fp.fileno())
        self._state_id += 1
        self._auto_summary(record)
        return record

    def close(self) -> None:
        if not self._fp.closed:
            self._fp.close()

    def __enter__(self) -> "TrajectoryWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
