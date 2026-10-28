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

Budgets: max_steps (executed actions), cumulative prompt-token circuit
breaker (token_budget, from API usage), per-command exec timeout
(default 360s; the agent may override per call, clamped to <= 600s).

llm_fn signature: llm_fn(messages, max_tokens=..., temperature=..., extra=...)
-> dict as returned by llm.chat. exec_fn signature:
await exec_fn(command: str, timeout_sec: int) -> {"stdout", "stderr",
"return_code", optional "timed_out", optional "error"}.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field

ACTION_KINDS = ("recon", "model", "code", "solve", "validate", "repair", "other")

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
    token_budget: int = 1_200_000          # cumulative prompt tokens
    exec_timeout_sec: int = 360            # default per-command timeout
    max_exec_timeout_sec: int = 600        # hard cap on per-command timeout
    max_tokens: int = 8192                 # per-LLM-call completion budget
    temperature: float = 0.6
    result_max_chars: int = 6000           # observation truncation


@dataclass
class LoopResult:
    status: str = "max_steps"   # finished | model_stopped | max_steps
                                # | token_budget_exceeded | llm_error
    n_steps: int = 0
    n_llm_calls: int = 0
    finish_summary: str | None = None
    usage: dict = field(default_factory=lambda: {
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
    })


def action_hash(action: dict) -> str:
    canonical = json.dumps(action, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _classify_result(result: dict, error: str | None) -> str:
    text = f"{error or ''} {result.get('error') or ''}".lower()
    if result.get("timed_out") or "timed out" in text or "timeout" in text:
        return "timeout"
    if error or result.get("error"):
        return "exec_error"
    if result.get("return_code") == 0:
        return "ok"
    return "nonzero_exit"


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
                   model: str = "unknown") -> LoopResult:
    result = LoopResult()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": instruction},
    ]
    history: list[str] = []  # one short line per executed action

    writer.emit("run_meta", config={
        "max_steps": config.max_steps, "token_budget": config.token_budget,
        "exec_timeout_sec": config.exec_timeout_sec,
        "max_tokens": config.max_tokens, "temperature": config.temperature,
        "predictor_mode": getattr(getattr(recorder, "predictor", None), "mode", "off"),
    })

    for step in range(1, config.max_steps + 1):
        writer.emit("llm_request", n_messages=len(messages),
                    max_tokens=config.max_tokens, temperature=config.temperature)
        try:
            # llm_fn is synchronous (blocking HTTP); run it off the event
            # loop so a stalled request cannot freeze sibling trials.
            out = await asyncio.to_thread(
                llm_fn, messages, max_tokens=config.max_tokens,
                temperature=config.temperature, extra={"tools": TOOLS})
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

        content = out.get("content") or ""
        finish_reason = out.get("finish_reason")
        tool_calls = out.get("tool_calls") or []
        writer.emit("llm_response", content=content, tool_calls=tool_calls,
                    usage=usage, finish_reason=finish_reason,
                    latency_s=out.get("latency_s"), api_model=out.get("model"),
                    truncated=(finish_reason == "length"))

        # Token circuit breaker: stop before spending more.
        if result.usage["prompt_tokens"] > config.token_budget:
            writer.emit("budget", kind="token_budget_exceeded",
                        prompt_tokens=result.usage["prompt_tokens"],
                        token_budget=config.token_budget)
            result.status = "token_budget_exceeded"
            break

        messages.append({
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
            messages.append({
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

        if name != "bash":
            writer.emit("action", tool=name, error="unknown_tool")
            messages.append({
                "role": "tool", "tool_call_id": tc.get("id"),
                "content": f"[error] unknown tool {name!r}; available: bash, finish",
            })
            continue

        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            writer.emit("action", tool="bash", error="missing_command")
            messages.append({
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
        writer.emit("action", seq=result.n_steps, action=action, action_hash=ahash)

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
            # before_exec may call the LLM synchronously (shadow predictor);
            # keep it off the event loop for the same reason as llm_fn.
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

        outcome_file = None
        if recorder is not None:
            outcome_file = recorder.after_exec(
                seq=result.n_steps, action=action, action_hash=ahash,
                prediction_file=prediction_file, result=exec_result)
        # Trajectory outcome event for EVERY action (files only for predicted ones).
        writer.emit("outcome", seq=result.n_steps, action_hash=ahash,
                    return_code=exec_result.get("return_code"),
                    classification=classification, error=exec_error,
                    prediction_file=prediction_file, outcome_file=outcome_file)

        observation = _format_observation(exec_result, exec_error,
                                          config.result_max_chars)
        if n_ignored:
            observation += (f"\n[note] {n_ignored} additional tool call(s) in your "
                            "last message were ignored: exactly one action per turn.")
        messages.append({
            "role": "tool", "tool_call_id": tc.get("id"), "content": observation,
        })
        history.append(
            f"step {result.n_steps} [{action_kind}] rc={exec_result.get('return_code')} "
            f"{classification}: {command[:120]}")

    writer.emit("budget", kind="final", status=result.status,
                n_steps=result.n_steps, usage=dict(result.usage),
                token_budget=config.token_budget, max_steps=config.max_steps)
    return result
