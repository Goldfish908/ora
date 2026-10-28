"""JSONL trajectory writer for ora_agent. Stdlib only.

Event types: llm_request / llm_response / action / prediction / outcome /
budget / finish (plus "error" surfaced via an `error` field on any event).

Every record carries: ts (UTC ISO-8601), run_id, task_id, model, state_id
(monotonically increasing within the run) and parent_state (previous
state_id, forming a chain). Event-specific fields (action_hash, usage,
error classification, prediction file references, ...) are passed through.

Writes are flushed and fsync'd per event: trajectory completeness matters
more than throughput here (a crashed run must still leave its trace).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPES = frozenset({
    "llm_request", "llm_response", "action", "prediction", "outcome",
    "budget", "finish", "run_meta",
})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrajectoryWriter:
    def __init__(self, path, *, run_id: str, task_id: str, model: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.task_id = task_id
        self.model = model
        self._state_id = 0
        self._fp = open(self.path, "a", encoding="utf-8")

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
        return record

    def close(self) -> None:
        if not self._fp.closed:
            self._fp.close()

    def __enter__(self) -> "TrajectoryWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
