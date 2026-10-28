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

Prompt version v2 (task book 2.7):
- Optional context_provider(action) injects structured evidence context
  (requirements, open findings, relevant check results, referenced finding
  full text for repair actions) from the EvidenceStore. Without a provider,
  or when the store is empty, the input degrades to the plain history
  summary; the prediction file records context_source accordingly, plus the
  provider's raw output for full input reviewability.
- The system prompt branches by action_kind: validate/check actions get
  expected_observations + indistinguishable_hypotheses; repair actions get
  likely_resolved + potential_regressions + post_state_guess; solve actions
  get expected_solution_validity + expected_quality_change +
  likely_failure_modes + resource_estimate. All kinds keep the unknown
  option, will_succeed_prob and a scope_note.
- Semantic separation: the prompt asks for the outcome as confirmed by
  independent test execution (prediction_target="independent_outcome"), not
  the judgment a reviewer/audit LLM would later give.

Prediction input is hashed (sha256, canonical JSON over history summary,
action, budget state, evidence context, prompt version and prediction
target) and recorded alongside the prediction content. Predictions may
legitimately be {"unknown": true} — an honest "I don't know" is a valid
datapoint; self-reported confidence is recorded but NOT claimed to be
calibrated.
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

PROMPT_VERSION = "v2"
PREDICTION_TARGET = "independent_outcome"

_SYSTEM_V2_CORE = (
    "You are a predictor module attached to an operations-research agent. "
    "Given the recent history summary, structured evidence context "
    "(requirements, open findings, check results — when available), the "
    "action the agent is about to run, and the remaining budget, predict the "
    "action's consequence BEFORE it runs.\n"
    "Prediction target: predict the TRUE outcome as it would be confirmed by "
    "independent test execution (prediction_target=independent_outcome) — "
    "NOT the judgment a reviewer or audit LLM would later give. A reviewer's "
    "verdict is not ground truth.\n"
    "Always include keys: will_succeed_prob (0..1 number or null), "
    "expected_outcome (string), scope_note (string: the scope and "
    "applicability conditions of this prediction), confidence (0..1). "
    "If you cannot judge, respond with {\"unknown\": true}. "
    "Do not overstate certainty."
)

_KIND_BRANCHES = {
    "validate": (
        "This is a CHECK/VALIDATE action. Additionally include: "
        "expected_observations (array of strings: observations or findings "
        "you expect the check to produce), indistinguishable_hypotheses "
        "(array of strings: explanations this check may still be unable to "
        "distinguish)."
    ),
    "repair": (
        "This is a REPAIR action. Additionally include: likely_resolved "
        "(array of strings: ids of known problems/findings this repair is "
        "likely to resolve), potential_regressions (array of strings: "
        "previously working behavior this patch may break), post_state_guess "
        "(string: key filesystem/solver state after execution)."
    ),
    "solve": (
        "This is a SOLVE action. Additionally include: "
        "expected_solution_validity (string: whether a valid/feasible "
        "solution is expected, and why), expected_quality_change (string: "
        "expected objective/quality change vs the current state), "
        "likely_failure_modes (array of strings), resource_estimate "
        "(string: expected runtime/memory/solver effort)."
    ),
}

_DEFAULT_BRANCH = (
    "Additionally include: likely_failure_modes (array of strings), "
    "post_state_guess (string describing expected filesystem/solver state "
    "after the action)."
)


def build_system_prompt(action_kind: str) -> str:
    """v2 prediction system prompt, branched by action_kind (2.7)."""
    return (_SYSTEM_V2_CORE + "\n"
            + _KIND_BRANCHES.get(action_kind, _DEFAULT_BRANCH))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_fsync(path: Path, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def hash_prediction_input(history_summary: str, action: dict,
                          budget_state: dict, *, context: dict | None = None,
                          prompt_version: str = PROMPT_VERSION) -> str:
    """sha256 over the full prediction input — in v2 that includes the
    injected evidence context, the prompt version and the prediction target,
    so the hash changes iff any prediction input changes."""
    canonical = json.dumps(
        {"history_summary": history_summary, "action": action,
         "budget_state": budget_state, "evidence_context": context,
         "prompt_version": prompt_version,
         "prediction_target": PREDICTION_TARGET},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Predictor:
    """Interface: predict(history_summary, action, budget_state, *,
    evidence_context=None) -> dict."""

    mode = "off"

    def predict(self, history_summary: str, action: dict, budget_state: dict,
                *, evidence_context: dict | None = None) -> dict:
        raise NotImplementedError


class NullPredictor(Predictor):
    mode = "off"

    def predict(self, history_summary, action, budget_state, *,
                evidence_context=None):  # pragma: no cover
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


_UNSET = object()

# Finding-id references in an action's rationale/command (worker findings
# look like "F-001").
_FINDING_REF_RE = re.compile(r"\bF-\d+\b")


def make_evidence_context_provider(store, *, max_requirements: int = 20,
                                   max_findings: int = 20,
                                   max_checks: int = 5):
    """Build a context_provider(action) -> dict | None over an EvidenceStore.

    Returns None (degrade to history summary) when the store has no
    requirements, findings or check results at all. Otherwise returns a dict
    with context_source="evidence_store" and:
    - requirements: up to max_requirements entries {req_id, statement
      (<=200 chars), hardness, source_refs}.
    - open_findings: up to max_findings entries {finding_id, status,
      problem_type, detail (<=300 chars), artifact_hash}.
    - recent_check_results: up to max_checks recent checks {check_id,
      artifact_version, input_hash, actual_result, evidence_source, ts};
      when a repair action references a finding id, checks pinned to that
      finding's artifact_hash are preferred.
    - referenced_finding: the full latest record of the finding referenced
      by a repair action's rationale/command, when any.
    """

    def provider(action: dict) -> dict | None:
        action = action or {}
        reqs = store.records("requirement")[:max_requirements]
        findings = store.open_findings()[:max_findings]
        checks = store.records("check_result")
        if not (reqs or findings or checks):
            return None

        referenced = None
        if action.get("action_kind") == "repair":
            text = f"{action.get('rationale', '')}\n{action.get('command', '')}"
            latest = store.latest_findings()
            for fid in dict.fromkeys(_FINDING_REF_RE.findall(text)):
                if fid in latest:
                    referenced = latest[fid]
                    break

        if referenced is not None:
            av = referenced.get("artifact_hash")
            matching = [c for c in checks
                        if c.get("artifact_version") == av][-max_checks:]
            rest = [c for c in checks if c.get("artifact_version") != av]
            remaining = max_checks - len(matching)
            selected = matching + (rest[-remaining:] if remaining > 0 else [])
        else:
            selected = checks[-max_checks:]

        ctx = {
            "context_source": "evidence_store",
            "requirements": [
                {"req_id": r.get("req_id"),
                 "statement": str(r.get("statement", ""))[:200],
                 "hardness": r.get("hardness"),
                 "source_refs": r.get("source_refs") or []}
                for r in reqs],
            "open_findings": [
                {"finding_id": f.get("finding_id"),
                 "status": f.get("status"),
                 "problem_type": f.get("problem_type"),
                 "detail": str(f.get("detail", ""))[:300],
                 "artifact_hash": f.get("artifact_hash")}
                for f in findings],
            "recent_check_results": [
                {"check_id": c.get("check_id"),
                 "artifact_version": c.get("artifact_version"),
                 "input_hash": c.get("input_hash"),
                 "actual_result": c.get("actual_result"),
                 "evidence_source": c.get("evidence_source"),
                 "ts": c.get("ts")}
                for c in selected],
        }
        if referenced is not None:
            ctx["referenced_finding"] = referenced
        return ctx

    return provider


class QwenShadowPredictor(Predictor):
    """Untrained prior-prediction baseline using the same chat model.

    context_provider (optional): callable(action) -> dict | None supplying
    structured evidence context (see make_evidence_context_provider). The
    PredictionRecorder normally owns the provider and passes its output
    explicitly via predict(..., evidence_context=...); the constructor arg
    is the standalone-use fallback."""

    mode = "shadow"

    def __init__(self, llm_fn, *, max_tokens: int = 1024,
                 temperature: float = 0.0, context_provider=None):
        self._llm_fn = llm_fn
        self._max_tokens = max_tokens
        self._temperature = temperature
        self.context_provider = context_provider

    def predict(self, history_summary: str, action: dict, budget_state: dict,
                *, evidence_context=_UNSET) -> dict:
        if evidence_context is _UNSET:
            evidence_context = (self.context_provider(action)
                                if self.context_provider is not None else None)
        context_source = ((evidence_context or {}).get("context_source")
                          or "history_summary")
        user = json.dumps({
            "history_summary": history_summary,
            "action": action,
            "budget_state": budget_state,
            "prediction_target": PREDICTION_TARGET,
            "context_source": context_source,
            "evidence_context": evidence_context,
        }, ensure_ascii=False, default=str)
        messages = [
            {"role": "system",
             "content": build_system_prompt(action.get("action_kind", "other"))},
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
        parsed["predictor_meta"] = {
            "model": out.get("model"),
            "usage": out.get("usage") or {},
            "latency_s": out.get("latency_s"),
            "finish_reason": out.get("finish_reason"),
            "prompt_version": PROMPT_VERSION,
            "prediction_target": PREDICTION_TARGET,
            "context_source": context_source,
        }
        return parsed


class QwenActivePredictor(QwenShadowPredictor):
    # TODO(v1+): active mode currently records exactly like shadow; predictions
    # are NOT yet fed back into action selection. Kept as a distinct mode so
    # trajectories already distinguish the experimental arm.
    mode = "active"


def make_predictor(mode: str | None, llm_fn, *, context_provider=None) -> Predictor:
    mode = (mode or "off").strip().lower()
    if mode not in PREDICT_MODES:
        raise ValueError(
            f"ora_agent: invalid predict mode {mode!r}; expected one of "
            f"{sorted(PREDICT_MODES)}"
        )
    if mode == "off":
        return NullPredictor()
    if mode == "shadow":
        return QwenShadowPredictor(llm_fn, context_provider=context_provider)
    return QwenActivePredictor(llm_fn, context_provider=context_provider)


class PredictionRecorder:
    """Writes prediction files before execution and outcome files after.

    Invariant: for a predicted action, the prediction file is fully written
    and fsync'd before the action is executed; the outcome file references
    the prediction file by name and is written after execution. Neither file
    is ever modified after creation (no backfilling).

    Cost accounting: predictor LLM calls are recorded exactly once, here,
    from prediction["predictor_meta"]["usage"] — into the shared
    BudgetTracker when one is provided, otherwise into a local cumulative
    ``usage`` dict. Callers must NOT record predictor calls elsewhere.

    context_provider (task book 2.7): optional callable(action) -> dict|None
    (e.g. make_evidence_context_provider(store)). Called once per predicted
    action in before_exec; the raw output is written into the prediction
    file and covered by input_hash. None (or an empty store) degrades to the
    plain history summary with context_source="history_summary".
    """

    def __init__(self, root_dir, *, writer=None, predictor: Predictor | None = None,
                 tracker=None, context_provider=None):
        self.root_dir = Path(root_dir)
        self.predictions_dir = self.root_dir / "predictions"
        self.outcomes_dir = self.root_dir / "outcomes"
        self.predictions_dir.mkdir(parents=True, exist_ok=True)
        self.outcomes_dir.mkdir(parents=True, exist_ok=True)
        self.writer = writer
        self.predictor = predictor or NullPredictor()
        self.tracker = tracker
        # context_provider(action) -> dict | None: injects structured
        # evidence context (task book 2.7); its raw output is stored in the
        # prediction file and covered by input_hash.
        self.context_provider = context_provider
        self._usage = {"n_calls": 0, "prompt_tokens": 0,
                       "completion_tokens": 0, "latency_s": 0.0}

    @property
    def usage(self) -> dict:
        """Cumulative predictor usage {n_calls, prompt_tokens,
        completion_tokens, latency_s}. Reads from the shared tracker when
        attached so there is a single aggregation entry point."""
        if self.tracker is not None:
            t = self.tracker.role_totals().get("predictor", {})
            return {"n_calls": t.get("calls", 0),
                    "prompt_tokens": t.get("prompt_tokens", 0),
                    "completion_tokens": t.get("completion_tokens", 0),
                    "latency_s": t.get("latency_s", 0.0)}
        return dict(self._usage)

    def _record_usage(self, prediction: dict) -> None:
        meta = (prediction or {}).get("predictor_meta") or {}
        u = meta.get("usage") or {}
        latency = meta.get("latency_s")
        if self.tracker is not None:
            self.tracker.record("predictor", u, latency)
        else:
            self._usage["n_calls"] += 1
            self._usage["prompt_tokens"] += u.get("prompt_tokens") or 0
            self._usage["completion_tokens"] += u.get("completion_tokens") or 0
            self._usage["latency_s"] = round(
                self._usage["latency_s"] + (latency or 0.0), 3)

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
        context = (self.context_provider(action)
                   if self.context_provider is not None else None)
        context_source = ((context or {}).get("context_source")
                          or "history_summary")
        input_hash = hash_prediction_input(history_summary, action,
                                           budget_state, context=context)
        prediction = self.predictor.predict(history_summary, action,
                                            budget_state,
                                            evidence_context=context)
        self._record_usage(prediction)
        fname = f"{seq:04d}_{action_hash}.json"
        rel = f"predictions/{fname}"
        payload = {
            "ts": _utc_now_iso(),
            "seq": seq,
            "action_hash": action_hash,
            "predictor_mode": self.predictor.mode,
            "prompt_version": PROMPT_VERSION,
            "prediction_target": PREDICTION_TARGET,
            "context_source": context_source,
            "evidence_context": context,
            "input_hash": input_hash,
            "history_summary": history_summary,
            "budget_state": budget_state,
            "action": action,
            "prediction": prediction,
        }
        _write_json_fsync(self.predictions_dir / fname, payload)
        if self.writer is not None:
            self.writer.emit(
                "prediction", seq=seq, action_hash=action_hash,
                prediction_file=rel, input_hash=input_hash,
                predictor_mode=self.predictor.mode,
                prompt_version=PROMPT_VERSION,
                context_source=context_source, prediction=prediction,
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
