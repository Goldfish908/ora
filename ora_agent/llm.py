"""OpenAI-compatible chat client for ora_agent. Python stdlib only (urllib).

Endpoint reality check (2026-10-24, Aliyun MaaS compatible-mode gateway,
model ``qwen3.8-27b``): a minimal request carrying an OpenAI ``tools``
parameter succeeds and returns ``finish_reason="tool_calls"`` with a
well-formed ``tool_calls`` array. ora_agent therefore uses native tool
calling; no text-protocol fallback is implemented. If the endpoint ever
loses tools support, add a JSON-action text protocol in loop.py.

Credential discipline: the API key is read from the process environment
only (ORA_LLM_API_KEY). It is never written to code, logs, trajectories,
or error messages.

Proxy discipline: the host exports http_proxy/https_proxy which must NOT
be used for the LLM endpoint (see docs/fitgap.md). We build an opener with
an empty ProxyHandler so env proxies are bypassed unconditionally.

TLS verification is ON by default; set ORA_LLM_INSECURE=1 to disable it
(only for debugging against self-signed gateways).
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace

DEFAULT_MODEL = "qwen3.8-27b"
REQUEST_TIMEOUT_SEC = 600.0
MAX_RETRIES = 2  # retries after the initial attempt (so <= 3 total tries)
_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})


class LLMConfigError(RuntimeError):
    """Missing/invalid LLM configuration (environment variables)."""


class LLMRequestError(RuntimeError):
    """LLM HTTP request failed (after retries where applicable).

    Carries a status code when the server responded; the message never
    contains credentials or request headers.
    """

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str = DEFAULT_MODEL
    insecure: bool = False

    def with_model(self, model: str) -> "LLMConfig":
        return replace(self, model=model)


def load_config(env: dict | None = None) -> LLMConfig:
    """Resolve LLM config from an env mapping (defaults to os.environ).

    Raises LLMConfigError with a clear message when required variables are
    missing. Never raises with secret values embedded.
    """
    env = os.environ if env is None else env
    base_url = env.get("ORA_LLM_BASE_URL")
    api_key = env.get("ORA_LLM_API_KEY")
    model = env.get("ORA_LLM_MODEL") or DEFAULT_MODEL
    missing = [
        name
        for name, value in (("ORA_LLM_BASE_URL", base_url), ("ORA_LLM_API_KEY", api_key))
        if not value
    ]
    if missing:
        raise LLMConfigError(
            "ora_agent: missing required environment variable(s): "
            + ", ".join(missing)
            + ". Export them before `harbor run` (e.g. "
            "`export ORA_LLM_BASE_URL=$DISTILL_BASE_URL; "
            "export ORA_LLM_API_KEY=$DISTILL_API_KEY` after sourcing your env "
            "file). Credentials are read from the environment only, never "
            "from files."
        )
    insecure = env.get("ORA_LLM_INSECURE") == "1"
    return LLMConfig(base_url=base_url.rstrip("/"), api_key=api_key, model=model,
                     insecure=insecure)


def _build_opener(insecure: bool):
    # Empty ProxyHandler({}) => ignore http_proxy/https_proxy/no_proxy env vars.
    handlers: list = [urllib.request.ProxyHandler({})]
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def _normalize_content(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts = []
        for part in raw:
            if isinstance(part, dict):
                parts.append(str(part.get("text", "")))
            else:
                parts.append(str(part))
        return "".join(parts)
    return str(raw)


def _normalize_tool_calls(raw) -> list[dict]:
    calls = []
    for i, tc in enumerate(raw or []):
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        calls.append({
            "id": tc.get("id") or f"call_{i}",
            "type": tc.get("type") or "function",
            "function": {
                "name": fn.get("name") or "",
                "arguments": fn.get("arguments") or "",
            },
        })
    return calls


def chat(messages: list[dict], *, max_tokens: int = 8192, temperature: float = 0.6,
         extra: dict | None = None, config: LLMConfig | None = None,
         opener=None, sleep_fn=time.sleep) -> dict:
    """One chat completion call.

    Returns a normalized dict:
        content: str (may be empty; when finish_reason == "length" and content
                 is empty the response is reported truthfully, not fabricated)
        tool_calls: list of {id, type, function: {name, arguments}}
        usage: dict as returned by the API ({} if absent)
        model: model id echoed by the API (falls back to configured model)
        latency_s: wall-clock seconds for the successful request
        finish_reason: str | None (reported as-is, e.g. "stop"/"length"/"tool_calls")

    ``extra`` is merged into the request body (e.g. {"tools": [...]}).
    Network-layer failures and retryable HTTP statuses are retried up to
    MAX_RETRIES times with exponential backoff; other HTTP errors fail loud.
    """
    config = config or load_config()
    body = {
        "model": config.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if extra:
        body.update(extra)
    data = json.dumps(body).encode("utf-8")
    url = config.base_url + "/chat/completions"
    if opener is None:
        opener = _build_opener(config.insecure)

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.api_key}",
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            with opener.open(request, timeout=REQUEST_TIMEOUT_SEC) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            latency_s = time.monotonic() - started
            break
        except urllib.error.HTTPError as e:
            # Read the body for diagnostics; never includes our headers.
            try:
                snippet = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                snippet = ""
            last_error = LLMRequestError(
                f"LLM request failed with HTTP {e.code}: {snippet}", status=e.code
            )
            if e.code not in _RETRYABLE_HTTP_STATUSES or attempt >= MAX_RETRIES:
                raise last_error from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = LLMRequestError(f"LLM request network error: {e}")
            if attempt >= MAX_RETRIES:
                raise last_error from e
        sleep_fn(min(2.0 * (2 ** attempt), 30.0))
    else:  # pragma: no cover - loop always raises or breaks
        raise last_error  # type: ignore[misc]

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise LLMRequestError(
            f"LLM response was not valid JSON: {raw[:300]!r}"
        ) from e
    choices = payload.get("choices") or []
    if not choices:
        raise LLMRequestError(
            f"LLM response has no choices: keys={sorted(payload.keys())}"
        )
    choice = choices[0]
    message = choice.get("message") or {}
    return {
        "content": _normalize_content(message.get("content")),
        "tool_calls": _normalize_tool_calls(message.get("tool_calls")),
        "usage": payload.get("usage") or {},
        "model": payload.get("model") or config.model,
        "latency_s": latency_s,
        "finish_reason": choice.get("finish_reason"),
    }
