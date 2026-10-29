"""Audit and repair workers for ora_agent (task book 2.3/2.4). Stdlib only.

These are role invocations by the orchestrating agent, not independent
subagents: the master calls them through the `audit` / `repair` tools; each
invocation assembles fresh context (via real exec_fn reads), makes ONE LLM
call (recorded under the "worker" role in the shared BudgetTracker), writes
evidence records, and returns a JSON summary to the master.

Hard rules implemented here:
- Workers NEVER execute the checks they propose: proposed_checks /
  patch_commands / regression_plan are returned to the master, which runs
  them via bash. Context-gathering reads (cat/ls of /app) are the only
  exec_fn use.
- audit mode="blind" hides the problem statement (input-control experiment,
  task book 2.5): data overview and code are kept, symbols/data semantics
  preserved, no expected-constraint expression is shown.
- New findings are forced to evidence_level="llm_judgment", status
  "suspected" — the worker cannot self-certify stronger evidence. Upgrades
  to actual_test happen only through focus="confirm" with observed results.
- unknown/unresolved never counts as passed (enforced in evidence.py).
- Workers only read /app; they never touch tests/, solution/, or any
  reference material (those live outside the container anyway).
"""

from __future__ import annotations

import asyncio
import hashlib
import json

from .evidence import (
    CheckResult, Finding, RepairResult, Requirement,
    FINDING_STATUS, HARDNESS, PROBLEM_TYPES, REQUIREMENT_STATUS,
)
from .predict import _extract_json

AUDIT_TOOL = {
    "type": "function",
    "function": {
        "name": "audit",
        "description": (
            "Call the evidence-review worker: audits model.md/solve.py against "
            "the problem statement and data, writes requirements/findings to "
            "the evidence store, and proposes executable witness checks. The "
            "worker never runs commands; run proposed_checks yourself via "
            "bash, then call audit(focus='confirm', question=<observations>). "
            "After applying a repair patch, call audit(focus='verify_fix', "
            "question=<patch and check outcomes>)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "Audit focus. 'confirm' upgrades findings with "
                                   "observed check results; 'verify_fix' classifies "
                                   "a repair outcome.",
                },
                "question": {
                    "type": "string",
                    "description": "What to audit, or the observed evidence for "
                                   "confirm/verify_fix.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["full", "blind"],
                    "description": "blind hides the problem statement "
                                   "(input-control experiment). Default full.",
                },
            },
            "required": ["focus", "question"],
        },
    },
}

REPAIR_TOOL = {
    "type": "function",
    "function": {
        "name": "repair",
        "description": (
            "Call the repair worker for a specific finding: proposes a minimal "
            "patch (patch_commands applied on a backup copy) and a "
            "regression_plan. The worker never runs commands; you execute the "
            "patch and checks via bash, then verify via audit(focus='verify_fix')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "finding_id": {"type": "string",
                               "description": "Finding id from the evidence store."},
                "guidance": {"type": "string",
                             "description": "What to fix and any constraints on the patch."},
            },
            "required": ["finding_id", "guidance"],
        },
    },
}

WORKER_TOOLS = [AUDIT_TOOL, REPAIR_TOOL]

# Appended to the master system prompt only when workers are enabled (B2 arm).
# Kept short on purpose: master context is expensive.
WORKERS_PROMPT_ADDENDUM = """
Additional tools (evidence workflow):
- audit(focus, question, mode="full"|"blind"): an evidence reviewer audits your model/code against the problem statement and data, records requirements/findings, and returns proposed_checks (small witness tests). It never runs commands — run promising proposed_checks via bash, then call audit(focus="confirm", question=<what you observed>) to upgrade findings with real evidence.
- repair(finding_id, guidance): a repair specialist proposes patch_commands (always on a backup copy) plus a regression_plan for a finding.
After your first feasible solution and before finish, run at least one audit covering constraint completeness and witness checks; use repair for confirmed semantic problems. Evidence levels: llm_judgment < actual_test < deterministic; unknown or unresolved never counts as passed.
"""

_AUDIT_SYSTEM = """\
You are an evidence-based reviewer for an operations-research solution built by another agent. You receive the problem statement, a data overview, the current model.md and solve.py, and the current evidence records. You NEVER execute commands; you propose checks for the orchestrator to run.

Audit coverage (all five, every time):
1. Requirements in the problem statement or data that the model/code omits; variable domains and objective completeness.
2. Direction, quantifiers, index ranges, conditions, units, and data mappings.
3. Whether the code actually builds each constraint — read the code itself; never trust comments or model.md claims.
4. Constraints added without a source in the problem statement, or hard requirements demoted to penalized preferences.
5. Whether the final business solution satisfies the original constraints and whether the objective can be recomputed independently.

For every finding, propose proposed_checks: small executable witness tests using only /app materials and in-container tools (python3, bash). Prefer minimal positive/negative instances — e.g. for a rule "B <= 50", a tiny instance where B=40 must be ACCEPTED and B=60 must be REJECTED. Such pairs catch both missing and spurious constraints.

Respond with a single JSON object, no prose:
{"requirements_new": [{"req_id": str, "statement": str, "source_refs": [str], "scope": str, "units": str, "hardness": "hard"|"soft", "status": "explicit"|"unresolved_ambiguity"}],
 "findings": [{"req_ids": [str], "problem_type": "implementation"|"semantic"|"feasibility"|"quality", "detail": str, "evidence_level": "llm_judgment", "status": "suspected", "proposed_checks": ["bash command", ...]}]}
Omit "requirements_new" unless the request asks for requirement extraction. Return empty "findings" if nothing is wrong. Do not overstate: your judgments are llm_judgment/suspected until the orchestrator runs the checks.

A finding is a DEFECT CLAIM only: a specific statement of something wrong (missing constraint, wrong direction, wrong index, unsourced objective term, ...). Never record a positive statement ("constraint X is correctly implemented") as a finding — correct behavior is the absence of findings, not a finding.
"""

_AUDIT_CONFIRM_ADDENDUM = """\
This is a CONFIRM call: the orchestrator executed proposed checks and reports the real observations in the question. Re-classify the affected findings based ONLY on that observed evidence.

Status semantics (strict):
- "confirmed" = the DEFECT IS REAL: the observation demonstrates the claimed violation. A confirmed finding asserts a defect exists.
- "refuted" = the observation shows the behavior is CORRECT (the claimed violation does not occur), or the finding was a positive statement that should never have been filed. Refuted closes the finding; it never counts as a defect.
- "unresolved" = the observation is inconclusive.

If the observation says or implies that a constraint is correctly implemented, the only valid status is "refuted" — never "confirmed".

Respond with a single JSON object, no prose:
{"finding_updates": [{"finding_id": str, "status": "confirmed"|"refuted"|"unresolved", "witness_ref": str, "detail": str}],
 "check_results": [{"artifact_version": str, "input_hash": str, "actual_result": "pass"|"fail"|"unknown", "evidence_source": str}]}
unknown/unresolved never counts as passed. If the observation is inconclusive, use "unresolved", not "confirmed".
"""

_AUDIT_VERIFY_FIX_ADDENDUM = """\
This is a VERIFY_FIX call: a repair patch was applied and the orchestrator reports the patch and the real outcomes of the regression plan in the question. Classify the repair outcome:
- resolved: known problems fixed under comparable checks (list finding ids).
- confirmed_regressions: checks the parent version passed that the patched version fails (list finding/check ids).
- newly_discovered: problems first seen in this round, not proven introduced by the patch.
- unresolved: insufficient evidence or still unfixed.

Respond with a single JSON object, no prose:
{"repair_result": {"patch_hash": str, "target_finding": str, "resolved": [str], "confirmed_regressions": [str], "newly_discovered": [str], "unresolved": [str]},
 "finding_updates": [{"finding_id": str, "status": "confirmed"|"refuted"|"unresolved", "witness_ref": str, "detail": str}]}
"""

_AUDIT_BLIND_NOTE = """\
INPUT CONTROL: the problem statement is intentionally hidden in this call. Keep symbol meanings, data, and code; do NOT invent expected constraints and do NOT guess hidden requirement directions. Mark requirement-shaped claims as status "unresolved_ambiguity".
"""

_REPAIR_SYSTEM = """\
You are a repair specialist for an operations-research solution. You receive a specific finding with its evidence, the current model.md and solve.py, and the original requirement context. Propose a targeted patch; the orchestrator executes it — you never run commands.

Route by problem_type: implementation -> fix the code; semantic -> fix the formulation/model; feasibility -> fix solution construction; quality -> improve the objective path. Prefer local changes; allow a justified full rewrite only when necessary (scope of change is not evidence of correctness). NEVER change the task's judging criteria or output schema. ALWAYS back up before modifying (e.g. `cp solve.py solve_v<N>.py`), so the parent version stays recoverable.

Respond with a single JSON object, no prose:
{"patch_commands": ["bash command", ...],
 "regression_plan": ["bash command", ...],
 "rationale": str,
 "expected_resolved": [str],
 "risk_notes": str}
"""


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class WorkerManager:
    """Handles audit/repair tool invocations for the master loop."""

    def __init__(self, *, llm_fn, exec_fn, evidence_store, writer,
                 tracker=None, max_tokens: int = 4096, temperature: float = 0.0,
                 llm_extra: dict | None = None):
        self._llm_fn = llm_fn
        self._exec_fn = exec_fn
        self._store = evidence_store
        self._writer = writer
        self._tracker = tracker
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._llm_extra = llm_extra
        self.n_calls = 0

    # -- plumbing ---------------------------------------------------------------

    async def _read(self, command: str, limit: int) -> str:
        """Context-gathering read inside the container (the only exec use)."""
        try:
            r = await self._exec_fn(command, 60)
        except Exception as e:
            return f"[read failed: {type(e).__name__}: {e}]"
        text = (r.get("stdout") or "")
        err = (r.get("stderr") or "").strip()
        if err:
            text += f"\n<stderr>\n{err}\n</stderr>"
        return text[:limit]

    async def _gather_context(self, mode: str) -> dict[str, str]:
        ctx: dict[str, str] = {}
        if mode != "blind":
            ctx["problem_statement"] = await self._read(
                "cat /app/PROBLEM_STATEMENT.md", 8000)
        ctx["data_overview"] = await self._read(
            'ls -la /app/data/ 2>&1; '
            'for f in /app/data/*; do echo "=== $f ==="; head -c 1500 "$f"; '
            "echo; done", 6000)
        ctx["model_md"] = await self._read(
            "cat /app/submissions/model.md 2>/dev/null || echo MISSING", 6000)
        ctx["solve_py"] = await self._read(
            "cat /app/submissions/solve.py 2>/dev/null || echo MISSING", 8000)
        return ctx

    async def _call_llm(self, worker: str, messages: list[dict],
                        event_fields: dict) -> dict | None:
        """One worker LLM call with trajectory + budget accounting."""
        self._writer.emit("worker_call", worker=worker, n_call=self.n_calls,
                          **event_fields)
        try:
            out = await asyncio.to_thread(
                self._llm_fn, messages, max_tokens=self._max_tokens,
                temperature=self._temperature,
                **({"extra": self._llm_extra} if self._llm_extra else {}))
        except Exception as e:
            self._writer.emit("worker_response", worker=worker,
                              n_call=self.n_calls,
                              error=f"{type(e).__name__}: {e}"[:300],
                              **event_fields)
            return None
        usage = out.get("usage") or {}
        if self._tracker is not None:
            self._tracker.record("worker", usage, out.get("latency_s"))
        self._writer.emit("worker_response", worker=worker, n_call=self.n_calls,
                          content=out.get("content") or "", usage=usage,
                          latency_s=out.get("latency_s"),
                          finish_reason=out.get("finish_reason"), **event_fields)
        return out

    # -- evidence writes ----------------------------------------------------------

    def _write_requirements(self, reqs) -> list[str]:
        existing = {r.get("req_id")
                    for r in self._store.records("requirement")}
        written = []
        for r in reqs or []:
            if not isinstance(r, dict):
                continue
            req_id = str(r.get("req_id") or "").strip()
            if not req_id or req_id in existing:
                continue
            hardness = r.get("hardness")
            status = r.get("status")
            try:
                self._store.append(Requirement(
                    req_id=req_id, statement=str(r.get("statement", "")),
                    source_refs=[str(x) for x in (r.get("source_refs") or [])],
                    scope=str(r.get("scope", "")), units=str(r.get("units", "")),
                    hardness=hardness if hardness in HARDNESS else "hard",
                    status=status if status in REQUIREMENT_STATUS else "explicit"))
            except ValueError:
                continue
            written.append(req_id)
            existing.add(req_id)
        return written

    def _write_findings(self, findings, artifact_hash: str) -> list[dict]:
        """New findings are forced to llm_judgment/suspected (the worker
        cannot self-certify stronger evidence). proposed_checks ride along in
        the returned summary for the master to execute."""
        written = []
        for f in findings or []:
            if not isinstance(f, dict):
                continue
            fid = str(f.get("finding_id") or "").strip()
            if not fid:
                fid = f"F-{self._store.records('finding').__len__() + 1:03d}"
            ptype = f.get("problem_type")
            self._store.append(Finding(
                finding_id=fid,
                req_ids=[str(x) for x in (f.get("req_ids") or [])],
                artifact_hash=artifact_hash,
                problem_type=ptype if ptype in PROBLEM_TYPES else "implementation",
                evidence_level="llm_judgment",   # forced, see docstring
                status="suspected",              # forced, see docstring
                detail=str(f.get("detail", "")),
                witness_ref=""))
            written.append({"finding_id": fid,
                            "proposed_checks": [str(c) for c in
                                                (f.get("proposed_checks") or [])]})
        return written

    def _apply_finding_updates(self, updates) -> list[str]:
        """Confirm/verify_fix flow: re-classify existing findings from real
        observations; evidence_level is upgraded to actual_test."""
        latest = self._store.latest_findings()
        applied = []
        for u in updates or []:
            if not isinstance(u, dict):
                continue
            fid = str(u.get("finding_id") or "").strip()
            orig = latest.get(fid)
            if not fid or orig is None:
                continue
            status = u.get("status")
            if status not in FINDING_STATUS - {"suspected"}:
                status = "unresolved"
            self._store.append(Finding(
                finding_id=fid,
                req_ids=orig.get("req_ids") or [],
                artifact_hash=orig.get("artifact_hash", ""),
                problem_type=orig.get("problem_type", "implementation"),
                evidence_level="actual_test",    # upgraded from real observation
                status=status,
                detail=str(u.get("detail") or orig.get("detail", "")),
                witness_ref=str(u.get("witness_ref", ""))))
            applied.append(fid)
        return applied

    def _write_check_results(self, checks) -> list[str]:
        written = []
        for c in checks or []:
            if not isinstance(c, dict):
                continue
            cid = str(c.get("check_id") or "").strip() or \
                f"chk-{len(self._store.records('check_result')) + 1:03d}"
            self._store.append(CheckResult(
                check_id=cid,
                artifact_version=str(c.get("artifact_version", "")),
                input_hash=str(c.get("input_hash", "")),
                actual_result=str(c.get("actual_result", "unknown")),
                evidence_source=str(c.get("evidence_source", "audit-confirm"))))
            written.append(cid)
        return written

    # -- tool handlers -----------------------------------------------------------

    async def handle(self, name: str, args: dict) -> str:
        if name == "audit":
            return await self.audit(
                focus=str(args.get("focus") or "general"),
                question=str(args.get("question") or ""),
                mode=str(args.get("mode") or "full"))
        if name == "repair":
            return await self.repair(
                finding_id=str(args.get("finding_id") or ""),
                guidance=str(args.get("guidance") or ""))
        return json.dumps({"error": f"unknown worker tool: {name}"})

    async def audit(self, *, focus: str, question: str, mode: str = "full") -> str:
        mode = "blind" if mode == "blind" else "full"
        self.n_calls += 1
        ctx = await self._gather_context(mode)
        artifact_hash = _sha16(ctx.get("solve_py", ""))

        requirements = self._store.records("requirement")
        open_findings = self._store.open_findings()
        need_reqs = not requirements and mode != "blind"

        system = _AUDIT_SYSTEM
        if focus == "confirm":
            system += "\n" + _AUDIT_CONFIRM_ADDENDUM
        elif focus == "verify_fix":
            system += "\n" + _AUDIT_VERIFY_FIX_ADDENDUM
        if mode == "blind":
            system += "\n" + _AUDIT_BLIND_NOTE

        sections = []
        if mode != "blind":
            sections.append("## Problem statement\n" + ctx["problem_statement"])
        else:
            sections.append("## Problem statement\n[hidden: blind mode]")
        sections.append("## Data overview\n" + ctx["data_overview"])
        sections.append("## /app/submissions/model.md\n" + ctx["model_md"])
        sections.append("## /app/submissions/solve.py\n" + ctx["solve_py"])
        sections.append("## Current requirements\n"
                        + json.dumps(requirements, ensure_ascii=False))
        sections.append("## Open findings\n"
                        + json.dumps(open_findings, ensure_ascii=False))
        request = f"focus: {focus}\nquestion: {question}"
        if need_reqs:
            request += ("\n\nNo requirements are recorded yet: FIRST extract "
                        "the requirements from the problem statement into "
                        "requirements_new, then audit.")
        sections.append("# Request\n" + request)
        user = "\n\n".join(sections)

        out = await self._call_llm(
            "audit", [{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            {"focus": focus, "mode": mode,
             "context_sha256": _sha16(system + user)})
        if out is None:
            return json.dumps({"error": "audit worker LLM call failed"})
        parsed = _extract_json(out.get("content") or "")
        if parsed is None:
            return json.dumps({
                "error": "audit worker returned unparseable JSON",
                "raw": (out.get("content") or "")[:500]})

        summary: dict = {"focus": focus, "mode": mode,
                         "artifact_version": artifact_hash}
        written_reqs = self._write_requirements(parsed.get("requirements_new"))
        if written_reqs:
            summary["requirements_written"] = written_reqs
        findings = self._write_findings(parsed.get("findings"), artifact_hash)
        summary["findings"] = findings
        if focus in ("confirm", "verify_fix"):
            summary["finding_updates_applied"] = self._apply_finding_updates(
                parsed.get("finding_updates"))
            written_checks = self._write_check_results(
                parsed.get("check_results"))
            if written_checks:
                summary["check_results_written"] = written_checks
        if focus == "verify_fix":
            rr = parsed.get("repair_result")
            if isinstance(rr, dict):
                row = self._store.append(RepairResult(
                    patch_hash=str(rr.get("patch_hash", "")),
                    target_finding=str(rr.get("target_finding", "")),
                    resolved=[str(x) for x in (rr.get("resolved") or [])],
                    confirmed_regressions=[str(x) for x in
                                           (rr.get("confirmed_regressions") or [])],
                    newly_discovered=[str(x) for x in
                                      (rr.get("newly_discovered") or [])],
                    unresolved=[str(x) for x in (rr.get("unresolved") or [])]))
                summary["repair_result_written"] = row["repair_id"]
        return json.dumps(summary, ensure_ascii=False)

    async def repair(self, *, finding_id: str, guidance: str) -> str:
        self.n_calls += 1
        latest = self._store.latest_findings()
        finding = latest.get(finding_id)
        if finding is None:
            return json.dumps({
                "error": f"finding not found: {finding_id!r}",
                "known_findings": sorted(latest.keys())[:20]})

        ctx = await self._gather_context("full")
        requirements = self._store.records("requirement")
        req_ids = finding.get("req_ids") or []
        req_context = [r for r in requirements if r.get("req_id") in req_ids]

        user = "\n\n".join([
            "## Finding to repair\n" + json.dumps(finding, ensure_ascii=False),
            "## Related requirements\n" + json.dumps(req_context, ensure_ascii=False),
            "## Problem statement\n" + ctx["problem_statement"],
            "## Data overview\n" + ctx["data_overview"],
            "## /app/submissions/model.md\n" + ctx["model_md"],
            "## /app/submissions/solve.py\n" + ctx["solve_py"],
            f"# Guidance from the orchestrator\n{guidance}",
        ])
        out = await self._call_llm(
            "repair", [{"role": "system", "content": _REPAIR_SYSTEM},
                       {"role": "user", "content": user}],
            {"finding_id": finding_id,
             "context_sha256": _sha16(_REPAIR_SYSTEM + user)})
        if out is None:
            return json.dumps({"error": "repair worker LLM call failed"})
        parsed = _extract_json(out.get("content") or "")
        if parsed is None:
            return json.dumps({
                "error": "repair worker returned unparseable JSON",
                "raw": (out.get("content") or "")[:500]})
        return json.dumps({
            "finding_id": finding_id,
            "patch_commands": [str(c) for c in (parsed.get("patch_commands") or [])],
            "regression_plan": [str(c) for c in (parsed.get("regression_plan") or [])],
            "rationale": str(parsed.get("rationale", "")),
            "expected_resolved": [str(x) for x in
                                  (parsed.get("expected_resolved") or [])],
            "risk_notes": str(parsed.get("risk_notes", "")),
            "note": "execute patch_commands via bash, run regression_plan, "
                    "then call audit(focus='verify_fix', question=<outcomes>)",
        }, ensure_ascii=False)
