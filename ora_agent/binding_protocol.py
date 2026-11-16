"""Dataset-neutral semantic binding proposals and independent validation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ora_agent.scoped_assets import compile_asset, load_asset
from scripts.scoped_ir_gate import gate

ROOT = Path(__file__).resolve().parents[1]
ORIGINS = {"reference_assisted", "cold_start_proposal", "frozen_reuse"}


@dataclass(frozen=True)
class BindingProposal:
    mechanism_id: str
    origin: str
    source_span: str
    payload: dict


def registry(root: Path | None = None) -> dict:
    root = root or ROOT
    path = root / "assets/scoped_ir/registry_v0.1.json"
    entries = json.loads(path.read_text())["assets"]
    result = {}
    for filename in entries:
        asset = load_asset(path.parent / filename)
        result[asset["mechanism_id"]] = path.parent / filename
    return result


def proposal_digest(proposal: BindingProposal) -> str:
    value = {"mechanism_id": proposal.mechanism_id, "origin": proposal.origin,
             "source_span": proposal.source_span, "payload": proposal.payload}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def protocol_errors(proposal: BindingProposal, question: str, cells: list[dict],
                    available: dict) -> list[str]:
    errors = []
    if proposal.origin not in ORIGINS:
        errors.append("unsupported binding origin")
    if proposal.mechanism_id not in available:
        errors.append(f"unregistered mechanism: {proposal.mechanism_id}")
    if not isinstance(proposal.source_span, str) or not proposal.source_span or proposal.source_span not in question:
        errors.append("source_span is not verbatim problem text")
    if not isinstance(proposal.payload, dict) or not proposal.payload:
        errors.append("payload must be a nonempty declarative object")
    try:
        json.dumps(proposal.payload, allow_nan=False)
    except (TypeError, ValueError):
        errors.append("payload must be finite JSON data")
    if not isinstance(cells, list) or not cells:
        errors.append("independent cells are required")
        return errors
    for cell in cells:
        if not isinstance(cell, dict):
            errors.append("each independent cell must be an object")
            continue
        if not isinstance(cell.get("label_source"), str) or not cell["label_source"].strip():
            errors.append(f"independent label_source is required: {cell.get('key')}")
        if not isinstance(cell.get("wrong"), bool):
            errors.append(f"wrong label must be boolean: {cell.get('key')}")
    if not any(isinstance(cell, dict) and cell.get("wrong") is False for cell in cells):
        errors.append("a clean cell is required")
    if not any(isinstance(cell, dict) and cell.get("wrong") is True for cell in cells):
        errors.append("a wrong cell is required")
    return errors


def validate_proposal(proposal: BindingProposal, question: str, cells: list[dict],
                      business_scorer=None, registry_paths: dict | None = None) -> dict:
    available = registry_paths or registry()
    errors = protocol_errors(proposal, question, cells, available)
    base = {"mechanism_id": proposal.mechanism_id, "origin": proposal.origin,
            "source_span": proposal.source_span, "payload": proposal.payload,
            "binding_sha256": proposal_digest(proposal), "llm_calls_this_validation": 0}
    if errors:
        return {**base, "status": "unknown", "accepted": False, "errors": errors}
    try:
        spec = compile_asset(load_asset(available[proposal.mechanism_id]), proposal.payload)
        gate_result = gate(spec, question, cells, proposal_digest(proposal)[:16])
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return {**base, "status": "unknown", "accepted": False, "errors": [str(exc)]}
    result = {**base, "spec": spec, "gate": gate_result,
              "errors": [] if gate_result["accepted"] else ["independent gate rejected"]}
    if not gate_result["accepted"]:
        evaluation = gate_result["evaluation"]
        status = "unknown" if evaluation["unknown"] or evaluation["rejected_count"] else "rejected"
        return {**result, "status": status, "accepted": False}
    if business_scorer is not None:
        clean = next((cell for cell in cells if cell["key"] == "reference_clean"), None)
        if clean is None:
            return {**result, "status": "unknown", "accepted": False,
                    "errors": ["reference_clean is required for business scoring"]}
        business = business_scorer(clean["solution"], proposal)
        result["business_audit"] = business
        if business.get("status") == "UNKNOWN":
            return {**result, "status": "unknown", "accepted": False,
                    "errors": ["independent business semantics are unknown or conflicting"]}
        if not business.get("business_correct"):
            return {**result, "status": "rejected", "accepted": False,
                    "errors": ["independent business scorer rejected reference_clean"]}
    return {**result, "status": "validated", "accepted": True}


def evaluate_alternatives(proposals: list[BindingProposal], question: str, cells: list[dict],
                          business_scorer=None, registry_paths: dict | None = None) -> dict:
    evaluations = [validate_proposal(proposal, question, cells, business_scorer, registry_paths)
                   for proposal in proposals]
    valid = [result for result in evaluations if result["accepted"]]
    response = {"evaluations": evaluations, "new_llm_calls": 0}
    if any(result["status"] == "unknown" for result in evaluations):
        return {**response, "status": "unknown", "accepted": False,
                "error": "an unknown or conflicting binding blocks favorable selection"}
    if len(valid) == 1:
        return {**response, "status": "validated", "accepted": True,
                "selected": valid[0], "selection_reason": "unique_valid_binding"}
    if valid:
        outcomes = [tuple(record["fired"] for record in result["gate"]["evaluation"]["records"])
                    for result in valid]
        if len(set(outcomes)) == 1:
            return {**response, "status": "validated", "accepted": True,
                    "selected": valid[0], "equivalent_binding_count": len(valid),
                    "selection_reason": "all_valid_bindings_agree"}
        return {**response, "status": "unknown", "accepted": False,
                "error": "multiple valid bindings disagree; no favorable binding may be selected"}
    status = "rejected" if any(result["status"] == "rejected" for result in evaluations) else "unknown"
    return {**response, "status": status, "accepted": False,
            "error": "no binding passed independent validation"}
