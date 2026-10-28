"""Shared budget tracker for ora_agent. Stdlib only.

One mutable BudgetTracker per run is the single aggregation entry point for
LLM cost across roles: actor (the decision-making agent loop), predictor
(shadow/active pre-action predictions), and worker (reserved for future
sub-task workers — the interface accepts the role already).

Single-recording-point discipline (do NOT record the same call twice):
- actor calls are recorded by loop.run_loop (from llm_response usage).
- predictor calls are recorded by predict.PredictionRecorder (from
  prediction["predictor_meta"]["usage"]). The llm_fn wrapper in
  harbor_agent does NOT record predictor calls itself.
- future worker calls should be recorded by their own caller site.

The optional token_budget check uses combined prompt tokens across roles.
The loop's actor-only circuit breaker predates the tracker and is kept for
back-compat; the tracker provides the all-roles view for run_summary.json
and the final budget event.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RoleUsage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "latency_s": round(self.latency_s, 3),
        }


class BudgetTracker:
    """Mutable per-run usage accumulator across LLM-calling roles."""

    KNOWN_ROLES = ("actor", "predictor", "worker")

    def __init__(self, token_budget: int | None = None):
        self.token_budget = token_budget
        self._roles: dict[str, RoleUsage] = {
            r: RoleUsage() for r in self.KNOWN_ROLES
        }

    def record(self, role: str, usage: dict | None,
               latency_s: float | None = None) -> None:
        """Record one LLM call. ``usage`` is the API usage dict (may be {})."""
        r = self._roles.setdefault(role, RoleUsage())
        r.calls += 1
        u = usage or {}
        r.prompt_tokens += u.get("prompt_tokens") or 0
        r.completion_tokens += u.get("completion_tokens") or 0
        r.latency_s += latency_s or 0.0

    def role_totals(self) -> dict[str, dict]:
        return {role: usage.to_dict() for role, usage in self._roles.items()}

    def combined(self) -> dict:
        return {
            "calls": sum(r.calls for r in self._roles.values()),
            "prompt_tokens": sum(r.prompt_tokens for r in self._roles.values()),
            "completion_tokens": sum(r.completion_tokens
                                     for r in self._roles.values()),
            "latency_s": round(sum(r.latency_s for r in self._roles.values()), 3),
        }

    def over_budget(self) -> bool:
        """True when a total budget is set and combined prompt tokens exceed it."""
        return (self.token_budget is not None
                and self.combined()["prompt_tokens"] > self.token_budget)
