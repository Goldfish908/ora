"""Action-consequence prediction for ora_agent. Stdlib only.

Modes (kwarg ``predict_mode`` or env ORA_PREDICT_MODE):
- off (default): no LLM prediction calls, zero overhead baseline.
- shadow: for actions with action_kind in {solve, validate, repair}, call the
  LLM *before* execution to produce a prior prediction, write it to
  predictions/<seq>_<action_hash>.json (fsync'd BEFORE the action runs), then
  write the observed result to outcomes/<seq>_<action_hash>.json (referencing
  the prediction file). Prediction and outcome never backfill each other.
- active: v1 placeholder — records exactly like shadow but is not wired into
  any decision. TODO(v1+): use predictions to gate/modify actions.

Prediction input is hashed (sha256, canonical JSON) and recorded alongside
the prediction content. Predictions may legitimately be {"unknown": true} —
an honest "I don't know" is a valid datapoint; self-reported confidence is
recorded but NOT claimed to be calibrated.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

PREDICT_ACTION_KINDS = frozenset({"solve", "validate", "repair"})
PREDICT_MODES = frozenset({"off", "shadow", "active"})

_PREDICTION_KEYS = (
    "will_succeed_prob", "expected_outcome", "likely_failure_modes",
    "post_state_guess", "confidence",
)

_SYSTEM = (
    "You are a predictor module attached to an operations-research agent. "
    "Given a short history summary, the action the agent is about to run, and "
    "the remaining budget, predict the action's consequence BEFORE it runs. "
    "Respond with a single JSON object, no prose, with keys: "
    "will_succeed_prob (0..1 number or null), expected_outcome (string), "
    "likely_failure_modes (array of strings), post_state_guess (string "
    "describing expected filesystem/solver state after the action), "
    "confidence (0..1). If you cannot judge, respond with {\"unknown\": true}. "
    "Do not overstate certainty."
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_fsync(path: Path, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def hash_prediction_input(history_summary: str, action: dict, budget_state: dict) -> str:
    canonical = json.dumps(
        {"history_summary": history_summary, "action": action,
         "budget_state": budget_state},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Predictor:
    """Interface: predict(history_summary, action, budget_state) -> dict."""

    mode = "off"

    def predict(self, history_summary: str, action: dict, budget_state: dict) -> dict:
        raise NotImplementedError


class NullPredictor(Predictor):
    mode = "off"

    def predict(self, history_summary, action, budget_state):  # pragma: no cover
        return {"unknown": True, "mode": "off"}


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    # Strip markdown code fences if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fence.group(1).strip() if fence else text
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # Last resort: first {...} span.
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            obj = json.loads(text[start:end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


class QwenShadowPredictor(Predictor):
    """Untrained prior-prediction baseline using the same chat model."""

    mode = "shadow"

    def __init__(self, llm_fn, *, max_tokens: int = 1024, temperature: float = 0.0):
        self._llm_fn = llm_fn
        self._max_tokens = max_tokens
        self._temperature = temperature

    def predict(self, history_summary: str, action: dict, budget_state: dict) -> dict:
        user = json.dumps({
            "history_summary": history_summary,
            "action": action,
            "budget_state": budget_state,
        }, ensure_ascii=False, default=str)
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ]
        try:
            out = self._llm_fn(messages, max_tokens=self._max_tokens,
                               temperature=self._temperature)
        except Exception as e:
            return {"unknown": True, "predictor_error": f"{type(e).__name__}: {e}"[:300]}
        parsed = _extract_json(out.get("content") or "")
        if parsed is None:
            parsed = {"unknown": True, "parse_error": True,
                      "raw_content": (out.get("content") or "")[:500]}
        parsed.setdefault("predictor_meta", {})
        parsed["predictor_meta"] = {
            "model": out.get("model"),
            "usage": out.get("usage") or {},
            "latency_s": out.get("latency_s"),
            "finish_reason": out.get("finish_reason"),
        }
        return parsed


class QwenActivePredictor(QwenShadowPredictor):
    # TODO(v1+): active mode currently records exactly like shadow; predictions
    # are NOT yet fed back into action selection. Kept as a distinct mode so
    # trajectories already distinguish the experimental arm.
    mode = "active"


def make_predictor(mode: str | None, llm_fn) -> Predictor:
    mode = (mode or "off").strip().lower()
    if mode not in PREDICT_MODES:
        raise ValueError(
            f"ora_agent: invalid predict mode {mode!r}; expected one of "
            f"{sorted(PREDICT_MODES)}"
        )
    if mode == "off":
        return NullPredictor()
    if mode == "shadow":
        return QwenShadowPredictor(llm_fn)
    return QwenActivePredictor(llm_fn)


class PredictionRecorder:
    """Writes prediction files before execution and outcome files after.

    Invariant: for a predicted action, the prediction file is fully written
    and fsync'd before the action is executed; the outcome file references
    the prediction file by name and is written after execution. Neither file
    is ever modified after creation (no backfilling).
    """

    def __init__(self, root_dir, *, writer=None, predictor: Predictor | None = None):
        self.root_dir = Path(root_dir)
        self.predictions_dir = self.root_dir / "predictions"
        self.outcomes_dir = self.root_dir / "outcomes"
        self.predictions_dir.mkdir(parents=True, exist_ok=True)
        self.outcomes_dir.mkdir(parents=True, exist_ok=True)
        self.writer = writer
        self.predictor = predictor or NullPredictor()

    def should_predict(self, action_kind: str) -> bool:
        return (self.predictor.mode != "off"
                and action_kind in PREDICT_ACTION_KINDS)

    def before_exec(self, *, seq: int, action: dict, action_hash: str,
                    history_summary: str, budget_state: dict) -> str | None:
        """Return the prediction filename (relative to root) or None.

        When a prediction is produced, its file is fsync'd before returning,
        so the caller can safely execute the action afterwards.
        """
        if not self.should_predict(action.get("action_kind", "other")):
            return None
        input_hash = hash_prediction_input(history_summary, action, budget_state)
        prediction = self.predictor.predict(history_summary, action, budget_state)
        fname = f"{seq:04d}_{action_hash}.json"
        rel = f"predictions/{fname}"
        payload = {
            "ts": _utc_now_iso(),
            "seq": seq,
            "action_hash": action_hash,
            "predictor_mode": self.predictor.mode,
            "input_hash": input_hash,
            "action": action,
            "prediction": prediction,
        }
        _write_json_fsync(self.predictions_dir / fname, payload)
        if self.writer is not None:
            self.writer.emit(
                "prediction", seq=seq, action_hash=action_hash,
                prediction_file=rel, input_hash=input_hash,
                predictor_mode=self.predictor.mode, prediction=prediction,
            )
        return rel

    def after_exec(self, *, seq: int, action: dict, action_hash: str,
                   prediction_file: str | None, result: dict) -> str | None:
        """Record the observed outcome. Returns the outcome filename or None.

        A file is only written for actions that were predicted; the trajectory
        outcome event (emitted by the loop) covers all actions.
        """
        if prediction_file is None:
            return None
        fname = f"{seq:04d}_{action_hash}.json"
        rel = f"outcomes/{fname}"
        payload = {
            "ts": _utc_now_iso(),
            "seq": seq,
            "action_hash": action_hash,
            "prediction_file": prediction_file,
            "action": action,
            "outcome": {
                "return_code": result.get("return_code"),
                "timed_out": bool(result.get("timed_out")),
                "error": result.get("error"),
                "stdout_tail": (result.get("stdout") or "")[-1000:],
                "stderr_tail": (result.get("stderr") or "")[-1000:],
                "classification": result.get("classification"),
            },
        }
        _write_json_fsync(self.outcomes_dir / fname, payload)
        # No writer event here: the loop emits the trajectory "outcome" event
        # for every action (predicted or not) with both file references.
        return rel
