"""Single-bash-tool agent loop for ora_agent. Stdlib only.

Protocol: native OpenAI tool calling (verified supported by the Aliyun MaaS
qwen3.8-27b endpoint on 2026-10-24 — minimal tools request returned
finish_reason="tool_calls" with a well-formed tool_calls array; see llm.py
docstring). One action per LLM turn: if the model emits multiple tool calls,
the first is executed and the rest are reported back as ignored.

Loop: LLM -> parse action -> (shadow prediction hook, fsync'd before exec)
-> exec_fn (environment.exec in production, injectable for tests)
-> truncated observation (<= result_max_chars) fed back as a tool message
-> until finish() / no tool call / budget exhausted.

Message reconstructability: the trajectory carries everything needed to
byte-rebuild what the model saw at each step — a `context_init` event with
the full system prompt + instruction + prompt sha256, then one `msg_append`
event per appended message with the exact payload (assistant content and
tool_calls verbatim, the *truncated* observation string actually sent, error
re-injection text). Each `llm_request` event carries messages_sha256 over
the serialized messages for verification.

Budgets: max_steps (executed actions), cumulative prompt-token circuit
breaker (token_budget, actor-only for back-compat; the shared BudgetTracker
additionally aggregates actor/predictor/worker usage), per-command exec
timeout (default 360s; the agent may override per call, clamped to <= 600s).

llm_fn signature: llm_fn(messages, max_tokens=..., temperature=..., extra=...)
-> dict as returned by llm.chat. exec_fn signature:
await exec_fn(command: str, timeout_sec: int) -> {"stdout", "stderr",
"return_code", optional "timed_out", optional "error"}.
artifacts_probe (optional): async callable returning a short listing of
/app/submissions; invoked after actions whose command touches submissions,
recorded as artifacts_last_observed in run_summary.json.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field

from .workers import WORKER_TOOLS

ACTION_KINDS = ("recon", "model", "code", "solve", "validate", "repair", "other")

# Solver self-reported time-limit signatures (SCIP prints "TIME LIMIT" as its
# status and "limits/time" in its statistics) — used to distinguish a
# solver-internal timeout from an exec-level kill.
_SOLVER_TIME_LIMIT_RE = re.compile(r"time limit|limits/time", re.IGNORECASE)

BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": (
            "Run one bash command inside the task container (working "
            "directory /app). Exactly one action per turn."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to run."},
                "action_kind": {
                    "type": "string",
                    "enum": list(ACTION_KINDS),
                    "description": (
                        "What this action is for: recon (reading problem/data), "
                        "model (writing model.md), code (writing solve.py), "
                        "solve (running the solver), validate (checking outputs "
                        "against the schema), repair (fixing failures), other."
                    ),
                },
                "rationale": {
                    "type": "string",
                    "description": "Why this action, why now (1-3 sentences).",
                },
                "timeout_sec": {
                    "type": "integer",
                    "description": "Optional per-command timeout in seconds (max 600).",
                },
            },
            "required": ["command", "action_kind", "rationale"],
        },
    },
}

FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": (
            "Declare the task complete. Call only when all required artifacts "
            "under /app/submissions/ exist and have been validated."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Honest summary of artifacts produced and observed results.",
                },
            },
            "required": ["summary"],
        },
    },
}

TOOLS = [BASH_TOOL, FINISH_TOOL]


@dataclass
class LoopConfig:
    max_steps: int = 40
    token_budget: int = 1_200_000          # cumulative prompt tokens, ALL roles
                                           # (actor+predictor+worker) when a
                                           # BudgetTracker is attached
    exec_timeout_sec: int = 360            # default per-command timeout
    max_exec_timeout_sec: int = 600        # hard cap on per-command timeout
    max_tokens: int = 8192                 # per-LLM-call completion budget
    temperature: float = 0.6
    result_max_chars: int = 6000           # observation truncation
    enable_workers: bool = False           # B0 when False: tools/prompt as v1
    worker_calls_budget: int = 8           # separate sub-budget; worker calls
                                           # do not consume max_steps
    worker_max_tokens: int = 4096          # per worker call completion budget


@dataclass
class LoopResult:
    status: str = "max_steps"   # finished | model_stopped | max_steps
                                # | token_budget_exceeded | llm_error | error
    n_steps: int = 0
    n_llm_calls: int = 0
    finish_summary: str | None = None
    usage: dict = field(default_factory=lambda: {
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
    })


def action_hash(action: dict) -> str:
    canonical = json.dumps(action, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def messages_sha256(messages: list[dict]) -> str:
    """Stable hash over the serialized message list, for reconstruction checks."""
    canonical = json.dumps(messages, sort_keys=True, ensure_ascii=False,
                           default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def prompt_sha256(system_prompt: str, instruction: str) -> str:
    canonical = json.dumps({"system_prompt": system_prompt,
                            "instruction": instruction},
                           sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _classify_result(result: dict, error: str | None) -> str:
    text = f"{error or ''} {result.get('error') or ''}".lower()
    if result.get("timed_out") or "timed out" in text or "timeout" in text:
        return "timeout"
    if error or result.get("error"):
        return "exec_error"
    if result.get("return_code") == 0:
        return "ok"
    return "nonzero_exit"


def _timeout_layer(result: dict, classification: str) -> str | None:
    """Which layer reports the timeout: "exec" (the command was killed by the
    exec timeout), "solver_reported" (the solver printed its own time-limit
    status and exited), or None."""
    if result.get("timed_out") or classification == "timeout":
        return "exec"
    text = (result.get("stdout") or "") + (result.get("stderr") or "")
    if _SOLVER_TIME_LIMIT_RE.search(text):
        return "solver_reported"
    return None


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = limit // 2
    return (text[:head]
            + f"\n...[truncated {len(text) - limit} chars]...\n"
            + text[-(limit - head):])


def _format_observation(result: dict, error: str | None, max_chars: int) -> str:
    rc = result.get("return_code")
    stdout = result.get("stdout") or ""
    stderr = result.get("stderr") or ""
    parts = [f"[exit_code={rc}]"]
    if error:
        parts.append(f"[exec_error] {error}")
    if result.get("timed_out"):
        parts.append("[timed_out] command exceeded its time limit")
    budget = max(max_chars - sum(len(p) for p in parts) - 100, 500)
    out_limit = budget * 2 // 3
    err_limit = budget - out_limit
    parts.append("<stdout>\n" + _truncate(stdout, out_limit) + "\n</stdout>")
    if stderr.strip():
        parts.append("<stderr>\n" + _truncate(stderr, err_limit) + "\n</stderr>")
    return "\n".join(parts)


async def run_loop(*, system_prompt: str, instruction: str, config: LoopConfig,
                   llm_fn, exec_fn, writer, recorder=None,
                   budget_tracker=None, artifacts_probe=None, worker_manager=None,
                   model: str = "unknown") -> LoopResult:
    result = LoopResult()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": instruction},
    ]
    history: list[str] = []  # one short line per executed action
    worker_calls = 0
    # B0 purity: workers disabled -> tool list byte-identical to v1.
    tools = TOOLS + WORKER_TOOLS if config.enable_workers else TOOLS

    def append_message(msg: dict) -> None:
        messages.append(msg)
        writer.emit("msg_append", index=len(messages) - 1, message=msg)

    def spent_prompt_tokens() -> int:
        # Shared-budget view: actor+predictor+worker via the tracker when
        # attached; actor-only fallback otherwise.
        if budget_tracker is not None:
            return budget_tracker.combined()["prompt_tokens"]
        return result.usage["prompt_tokens"]

    predictor_mode = getattr(getattr(recorder, "predictor", None), "mode", "off")
    # v1/round2: predictions are recorded but never fed back into decisions.
    decision_integration = False
    writer.emit("run_meta", config={
        "max_steps": config.max_steps, "token_budget": config.token_budget,
        "exec_timeout_sec": config.exec_timeout_sec,
        "max_tokens": config.max_tokens, "temperature": config.temperature,
        "predictor_mode": predictor_mode,
        "decision_integration": decision_integration,
    })
    writer.update_summary(predictor_mode=predictor_mode,
                          decision_integration=decision_integration)
    if predictor_mode == "active":
        writer.emit(
            "warning", kind="active_not_integrated",
            message="active mode records like shadow; predictions NOT wired "
                    "into decisions")

    writer.emit("context_init", system_prompt=system_prompt,
                instruction=instruction,
                prompt_sha256=prompt_sha256(system_prompt, instruction),
                tools=tools)

    def _role_usages() -> dict:
        if budget_tracker is not None:
            totals = budget_tracker.role_totals()
            return {
                "actor_usage": totals.get("actor"),
                "predictor_usage": totals.get("predictor"),
                "worker_usage": totals.get("worker"),
            }
        return {
            "actor_usage": {
                "calls": result.n_llm_calls,
                "prompt_tokens": result.usage["prompt_tokens"],
                "completion_tokens": result.usage["completion_tokens"],
                "latency_s": None,
            },
            "predictor_usage": (recorder.usage if recorder is not None else None),
            "worker_usage": None,
        }

    try:
        for step in range(1, config.max_steps + 1):
            writer.emit("llm_request", n_messages=len(messages),
                        messages_sha256=messages_sha256(messages),
                        max_tokens=config.max_tokens,
                        temperature=config.temperature)
            try:
                # llm_fn is synchronous (blocking HTTP); run it off the event
                # loop so a stalled request cannot freeze sibling trials.
                out = await asyncio.to_thread(
                    llm_fn, messages, max_tokens=config.max_tokens,
                    temperature=config.temperature, extra={"tools": tools})
            except Exception as e:
                writer.emit("llm_response", error="llm_request_failed",
                            error_message=f"{type(e).__name__}: {e}"[:500])
                result.status = "llm_error"
                break
            result.n_llm_calls += 1

            usage = out.get("usage") or {}
            result.usage["prompt_tokens"] += usage.get("prompt_tokens") or 0
            result.usage["completion_tokens"] += usage.get("completion_tokens") or 0
            result.usage["total_tokens"] += usage.get("total_tokens") or 0
            if budget_tracker is not None:
                budget_tracker.record("actor", usage, out.get("latency_s"))

            content = out.get("content") or ""
            finish_reason = out.get("finish_reason")
            tool_calls = out.get("tool_calls") or []
            writer.emit("llm_response", content=content, tool_calls=tool_calls,
                        usage=usage, finish_reason=finish_reason,
                        latency_s=out.get("latency_s"), api_model=out.get("model"),
                        truncated=(finish_reason == "length"))

            # Token circuit breaker (combined actor+predictor+worker when a
            # tracker is attached): stop before spending more.
            if spent_prompt_tokens() > config.token_budget:
                writer.emit("budget", kind="token_budget_exceeded",
                            prompt_tokens=spent_prompt_tokens(),
                            token_budget=config.token_budget)
                result.status = "token_budget_exceeded"
                break

            append_message({
                "role": "assistant",
                "content": content or None,
                **({"tool_calls": tool_calls} if tool_calls else {}),
            })

            if not tool_calls:
                # finish_reason == "length" with empty content is reported
                # truthfully above; either way the model produced no action.
                result.status = "model_stopped"
                break

            tc = tool_calls[0]
            n_ignored = len(tool_calls) - 1
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            raw_args = fn.get("arguments") or ""
            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
                if not isinstance(args, dict):
                    raise ValueError("tool arguments must be a JSON object")
            except (json.JSONDecodeError, ValueError) as e:
                writer.emit("action", tool=name, error="bad_arguments",
                            error_message=str(e)[:300], raw_arguments=raw_args[:500])
                append_message({
                    "role": "tool", "tool_call_id": tc.get("id"),
                    "content": f"[error] could not parse tool arguments as JSON: {e}",
                })
                continue

            if name == "finish":
                summary = str(args.get("summary", ""))
                writer.emit("action", tool="finish", summary=summary)
                writer.emit("finish", summary=summary, n_steps=result.n_steps,
                            usage=dict(result.usage))
                result.status = "finished"
                result.finish_summary = summary
                break

            if name in ("audit", "repair"):
                if worker_manager is None:
                    writer.emit("action", tool=name, error="workers_disabled")
                    append_message({
                        "role": "tool", "tool_call_id": tc.get("id"),
                        "content": f"[error] tool {name!r} is not enabled in this run",
                    })
                    continue
                if worker_calls >= config.worker_calls_budget:
                    writer.emit("action", tool=name,
                                error="worker_calls_budget_exceeded")
                    append_message({
                        "role": "tool", "tool_call_id": tc.get("id"),
                        "content": (f"[error] worker call budget exhausted "
                                    f"({config.worker_calls_budget} calls); "
                                    "continue with bash or finish"),
                    })
                    continue
                worker_calls += 1
                writer.emit("action", tool=name, args={
                    k: args.get(k) for k in ("focus", "question", "mode",
                                             "finding_id", "guidance")
                    if k in args})
                try:
                    reply = await worker_manager.handle(name, args)
                except Exception as e:
                    reply = json.dumps(
                        {"error": f"worker crashed: {type(e).__name__}: {e}"[:300]})
                reply = _truncate(reply, config.result_max_chars)
                if n_ignored:
                    reply += (f"\n[note] {n_ignored} additional tool call(s) in "
                              "your last message were ignored: exactly one "
                              "action per turn.")
                append_message({
                    "role": "tool", "tool_call_id": tc.get("id"),
                    "content": reply,
                })
                # Worker tokens count toward the shared budget: re-check.
                if spent_prompt_tokens() > config.token_budget:
                    writer.emit("budget", kind="token_budget_exceeded",
                                prompt_tokens=spent_prompt_tokens(),
                                token_budget=config.token_budget,
                                after="worker_call")
                    result.status = "token_budget_exceeded"
                    break
                continue

            if name != "bash":
                writer.emit("action", tool=name, error="unknown_tool")
                available = "bash, finish" + (", audit, repair"
                                              if config.enable_workers else "")
                append_message({
                    "role": "tool", "tool_call_id": tc.get("id"),
                    "content": f"[error] unknown tool {name!r}; available: {available}",
                })
                continue

            command = args.get("command")
            if not isinstance(command, str) or not command.strip():
                writer.emit("action", tool="bash", error="missing_command")
                append_message({
                    "role": "tool", "tool_call_id": tc.get("id"),
                    "content": "[error] bash tool requires a non-empty 'command' string",
                })
                continue

            action_kind = args.get("action_kind")
            if action_kind not in ACTION_KINDS:
                action_kind = "other"
            try:
                timeout_sec = int(args.get("timeout_sec") or config.exec_timeout_sec)
            except (TypeError, ValueError):
                timeout_sec = config.exec_timeout_sec
            timeout_sec = max(1, min(timeout_sec, config.max_exec_timeout_sec))

            action = {
                "tool": "bash",
                "command": command,
                "action_kind": action_kind,
                "rationale": str(args.get("rationale", "")),
                "timeout_sec": timeout_sec,
            }
            ahash = action_hash(action)
            result.n_steps += 1
            writer.emit("action", seq=result.n_steps, action=action,
                        action_hash=ahash)

            budget_state = {
                "step": result.n_steps, "max_steps": config.max_steps,
                "cum_prompt_tokens": result.usage["prompt_tokens"],
                "token_budget": config.token_budget,
            }
            history_summary = "\n".join(history[-8:])

            # Prediction hook: file is fsync'd inside before_exec, i.e. the
            # prediction is durably recorded BEFORE the action runs.
            prediction_file = None
            if recorder is not None:
                # before_exec may call the LLM synchronously (shadow
                # predictor); keep it off the event loop like llm_fn.
                prediction_file = await asyncio.to_thread(
                    recorder.before_exec,
                    seq=result.n_steps, action=action, action_hash=ahash,
                    history_summary=history_summary, budget_state=budget_state)

            exec_error = None
            try:
                exec_result = await exec_fn(command, timeout_sec)
            except Exception as e:
                exec_error = f"{type(e).__name__}: {e}"
                exec_result = {"stdout": "", "stderr": "", "return_code": -1}
            classification = _classify_result(exec_result, exec_error)
            exec_result = dict(exec_result)
            exec_result["classification"] = classification
            timeout_layer = _timeout_layer(exec_result, classification)

            outcome_file = None
            if recorder is not None:
                outcome_file = recorder.after_exec(
                    seq=result.n_steps, action=action, action_hash=ahash,
                    prediction_file=prediction_file, result=exec_result)
            # Trajectory outcome event for EVERY action (files only for
            # predicted ones).
            writer.emit("outcome", seq=result.n_steps, action_hash=ahash,
                        return_code=exec_result.get("return_code"),
                        classification=classification, error=exec_error,
                        timeout_layer=timeout_layer,
                        prediction_file=prediction_file,
                        outcome_file=outcome_file)

            # Artifact observation for run_summary.json: probe only after
            # actions that plausibly touched the submissions tree.
            if artifacts_probe is not None and "/app/submissions" in command:
                try:
                    listing = await artifacts_probe()
                    writer.update_summary(artifacts_last_observed={
                        "after_seq": result.n_steps, "listing": listing,
                    })
                except Exception:
                    pass  # probe is best-effort; never break the loop

            observation = _format_observation(exec_result, exec_error,
                                              config.result_max_chars)
            if n_ignored:
                observation += (f"\n[note] {n_ignored} additional tool call(s) in your "
                                "last message were ignored: exactly one action per turn.")
            append_message({
                "role": "tool", "tool_call_id": tc.get("id"), "content": observation,
            })
            history.append(
                f"step {result.n_steps} [{action_kind}] rc={exec_result.get('return_code')} "
                f"{classification}: {command[:120]}")
    except BaseException as e:
        # Includes KeyboardInterrupt / asyncio.CancelledError (harbor timeout
        # kill): mark the status, leave the trace, then re-raise.
        result.status = "error"
        writer.emit("warning", kind="loop_crashed",
                    message=f"{type(e).__name__}: {e}"[:500])
        raise
    finally:
        # The final budget event fires on EVERY exit path (finish, circuit
        # break, llm_error, unexpected crash) so usage is never lost. Guarded:
        # a writer failure here must not mask the original exception.
        try:
            writer.emit("budget", kind="final", status=result.status,
                        n_steps=result.n_steps, usage=dict(result.usage),
                        **_role_usages(),
                        token_budget=config.token_budget,
                        max_steps=config.max_steps)
            writer.update_summary(status=result.status,
                                  finish_summary=result.finish_summary,
                                  **_role_usages())
        except Exception:
            pass
    return result
