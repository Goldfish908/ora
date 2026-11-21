"""Public-source specification audit; supporting evidence, never independent truth."""
from __future__ import annotations

import json
from pathlib import Path

from . import llm as llm_mod
from .oragentbench import TaskPacket, write_json

SPEC_AUDIT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_spec_audit",
        "description": "Report whether every changed specification rule is grounded in public task text.",
        "parameters": {
            "type": "object",
            "properties": {
                "changed_features_covered": {"type": "boolean"},
                "scope_confirmed": {"type": "boolean"},
                "ungrounded_rules": {"type": "array", "items": {"type": "string"}},
                "changed_rules": {"type": "array", "items": {"type": "string"}},
                "coverage_note": {"type": "string"},
            },
            "required": ["changed_features_covered", "scope_confirmed", "ungrounded_rules",
                         "changed_rules", "coverage_note"],
        },
    },
}


def audit_specification(packets: list[TaskPacket], parent_spec: str, candidate_spec: str,
                        config: llm_mod.LLMConfig, outdir: Path) -> dict:
    public_documents = "\n\n".join(
        f"TASK {packet.name}\n{packet.instruction}\n{packet.problem_statement}" for packet in packets)
    messages = [
        {"role": "system", "content": (
            "You are a provenance auditor. Compare parent and candidate modeling specifications against "
            "the public task documents. Check added, removed and semantically changed rules, not merely "
            "formatting. changed_features_covered is true only when every changed business/API rule has "
            "an explicit public source or a precise justification in the supplied documents. "
            "scope_confirmed is true only if the candidate is restricted to the demonstrated task domain. "
            "Do not infer missing business rules and do not use hidden answers. Return one submit_spec_audit call.")},
        {"role": "user", "content": (
            f"PARENT SPECIFICATION\n{parent_spec}\n\nCANDIDATE SPECIFICATION\n{candidate_spec}\n\n"
            f"PUBLIC DOCUMENTS\n{public_documents}")},
    ]
    response = None
    try:
        response = llm_mod.chat(messages, max_tokens=4096, temperature=0.0,
                                extra={"reasoning_effort": "low", "tools": [SPEC_AUDIT_TOOL],
                                       "tool_choice": {"type": "function",
                                                       "function": {"name": "submit_spec_audit"}}},
                                config=config)
        calls = response.get("tool_calls") or []
        if len(calls) != 1:
            raise ValueError("expected one specification audit tool call")
        audit = json.loads(calls[0]["function"]["arguments"])
        if not isinstance(audit.get("changed_features_covered"), bool) \
                or not isinstance(audit.get("scope_confirmed"), bool):
            raise ValueError("audit booleans are missing")
        audit["error"] = None
    except Exception as exc:
        audit = {"changed_features_covered": False, "scope_confirmed": False,
                 "ungrounded_rules": ["audit_failed"], "changed_rules": [],
                 "coverage_note": "Specification audit failed; candidate cannot be promoted.",
                 "error": f"{type(exc).__name__}: {exc}"}
    audit.update(independent_semantic_truth=False,
                 note="This is provenance support only. Independent official replay is required separately.")
    write_json(outdir / "specification_audit.json", {
        "audit": audit, "response": response,
        "task_ids": [packet.name for packet in packets]})
    return audit
