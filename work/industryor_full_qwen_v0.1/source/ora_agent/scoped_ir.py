"""Evidence-scoped invariant construction and deterministic evaluation."""
from __future__ import annotations

import hashlib
import json
import math

from ora_agent.dvsa import (
    InvalidSpec,
    RELATIONS,
    SCHEMA_VERSION,
    asset_sha256,
    run_asset,
    validate_asset,
)

INTEGER_KINDS = {"domain_integer", "integer", "integrality"}
INTEGER_MARKERS = (
    "integer", "whole number", "whole numbers", "integral", "indivisible",
    "whole unit", "whole units", "discrete unit", "discrete units",
)


def extract_spec(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in response")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise TypeError("spec must be a JSON object")
    return value


def validate_expression(expr, allowed_paths: set[str]) -> None:
    if isinstance(expr, bool):
        raise InvalidSpec("boolean is not a numeric expression")
    if isinstance(expr, (int, float)):
        if not math.isfinite(expr):
            raise InvalidSpec("non-finite constant")
        return
    if not isinstance(expr, dict) or len(expr) != 1:
        raise InvalidSpec("expression must be a number or single-operator object")
    op, arg = next(iter(expr.items()))
    if op == "path":
        if arg not in allowed_paths:
            raise InvalidSpec(f"unbound or disallowed path: {arg}")
        return
    if op in {"add", "mul"}:
        if not isinstance(arg, list):
            raise InvalidSpec(f"{op} requires a list")
        for item in arg:
            validate_expression(item, allowed_paths)
        return
    if op in {"max", "min"}:
        if not isinstance(arg, list) or not arg:
            raise InvalidSpec(f"{op} requires a nonempty list")
        for item in arg:
            validate_expression(item, allowed_paths)
        return
    if op in {"sub", "div"}:
        if not isinstance(arg, list) or len(arg) != 2:
            raise InvalidSpec(f"{op} requires two operands")
        for item in arg:
            validate_expression(item, allowed_paths)
        return
    if op in {"neg", "abs", "round"}:
        validate_expression(arg, allowed_paths)
        return
    raise InvalidSpec(f"unsupported expression operator: {op}")


def source_evidence(raw: dict, kind: str) -> dict | None:
    evidence = raw.get("source_evidence")
    if evidence is None:
        if kind.startswith(("indicator_", "job_precedence")):
            raise InvalidSpec(f"{kind} semantics require independent source evidence")
        return None
    if not isinstance(evidence, dict) or evidence.get("type") != "independent_reference":
        raise InvalidSpec("source_evidence must be an independent_reference object")
    for field in ("reference", "text", "span", "sha256"):
        if not isinstance(evidence.get(field), str) or not evidence[field].strip():
            raise InvalidSpec(f"source_evidence.{field} is required")
    if evidence["span"] not in evidence["text"]:
        raise InvalidSpec("source_evidence.span is not present in its reference text")
    actual = hashlib.sha256(evidence["text"].encode()).hexdigest()
    if actual != evidence["sha256"]:
        raise InvalidSpec("source_evidence reference hash does not match its text")
    return evidence


def prepare_asset(spec: dict, question: str, variable_names: set[str],
                  problem_id: str) -> tuple[dict, list[dict]]:
    allowed_paths = {"solution.objective"} | {
        f"solution.variables.{name}" for name in variable_names}
    rejected = []
    if isinstance(spec, dict):
        raw_invariants = spec.get("invariants", [])
        if not isinstance(raw_invariants, list):
            rejected.append({"invariant_id": "spec",
                             "reason": "invariants must be a list"})
            raw_invariants = []
    else:
        rejected.append({"invariant_id": "spec", "reason": "spec must be an object"})
        raw_invariants = []
    valid, evidence_records = [], []
    for position, raw in enumerate(raw_invariants, 1):
        if not isinstance(raw, dict):
            rejected.append({"invariant_id": f"I{position:02d}",
                             "reason": "invariant is not an object"})
            continue
        rule = str(raw.get("invariant_id") or f"I{position:02d}")
        try:
            span = raw.get("source_span")
            if not isinstance(span, str) or not span.strip():
                raise InvalidSpec("source_span is required")
            if span not in question:
                raise InvalidSpec("source_span is not verbatim problem text")
            kind = str(raw.get("kind") or "constraint").lower()
            evidence = source_evidence(raw, kind)
            if (kind in INTEGER_KINDS and evidence is None
                    and not any(marker in span.lower() for marker in INTEGER_MARKERS)):
                raise InvalidSpec("integer requirement lacks explicit textual evidence")
            if evidence is not None:
                evidence_records.append(evidence)
            relation = raw.get("relation")
            if not isinstance(relation, str) or relation not in RELATIONS:
                raise InvalidSpec("invariant has an unsupported relation")
            validate_expression(raw.get("lhs"), allowed_paths)
            validate_expression(raw.get("rhs"), allowed_paths)
            invariant = {"invariant_id": rule,
                         "relation": relation,
                         "lhs": raw["lhs"], "rhs": raw["rhs"],
                         "kind": kind, "source_span": span, "strict": raw.get("strict", False)}
            valid.append(invariant)
        except (InvalidSpec, KeyError, TypeError) as exc:
            rejected.append({"invariant_id": rule, "reason": str(exc),
                             "source_span": raw.get("source_span")})
    evidence_hash = (hashlib.sha256(json.dumps(evidence_records, sort_keys=True,
                                               ensure_ascii=False).encode()).hexdigest()
                     if evidence_records else None)
    asset = {
        "asset_id": f"scoped_ir.{problem_id}",
        "schema_version": SCHEMA_VERSION,
        "asset_version": "0.2.0",
        "source": {"type": "independent_reference" if evidence_records else "natural_language",
                   "reference": problem_id, "text_or_requirement_hash": evidence_hash},
        "scope": {},
        "bindings": {},
        "invariants": valid,
        "tolerance": {"abs": 1e-6, "rel": 1e-6},
    }
    return asset, rejected


def empty_records(cells: list[dict], rejected: list[dict], reason: str) -> dict:
    records = [{"key": cell["key"], "wrong": cell["wrong"],
                "mutation": cell["mutation"],
                "reference_violations": cell["reference_violations"],
                "status": "unknown", "fired": False, "error": reason,
                "violations": [], "unknown_evidence": [],
                "rejected": rejected} for cell in cells]
    return {"records": records, "tp": 0, "fn": sum(c["wrong"] for c in cells),
            "fp": 0, "tn": sum(not c["wrong"] for c in cells),
            "unknown": len(records), "not_applicable": 0,
            "detection": 0.0, "false_positive": 0.0,
            "dev_passed": False, "rejected_count": len(rejected),
            "valid_invariant_count": 0}


def _known_record(record: dict) -> bool:
    return (record.get("status") == "ok"
            and not record.get("unknown_evidence")
            and not record.get("rejected"))


def independent_gate_passed(evaluation: dict) -> bool:
    """Validate only the encoded invariants against independent reference cells."""
    records = evaluation.get("records")
    if not isinstance(records, list):
        return False
    clean = [record for record in records if record.get("wrong") is False]
    wrong = [record for record in records if record.get("wrong") is True]
    return (bool(clean) and bool(wrong)
            and len(clean) + len(wrong) == len(records)
            and evaluation.get("rejected_count") == 0
            and evaluation.get("unknown") == 0
            and evaluation.get("not_applicable", 0) == 0
            and all(_known_record(record) and record.get("fired") is True
                    for record in wrong)
            and all(_known_record(record) and record.get("fired") is False
                    for record in clean))


def _candidate_record(cell: dict, result: dict, rejected: list[dict],
                      digest: str) -> dict:
    raw_status = result.get("status")
    violations = result.get("violations") or []
    unknown_evidence = result.get("unknown") or []
    fired = raw_status == "VIOLATED" or bool(violations)
    if unknown_evidence or raw_status == "UNKNOWN":
        status = "unknown"
    elif raw_status == "NOT_APPLICABLE":
        status = "not_applicable"
    elif rejected:
        status = "unknown"
    elif raw_status in {"SATISFIED", "VIOLATED"}:
        status = "ok"
    else:
        status = "unknown"
        unknown_evidence = [*unknown_evidence, {
            "rule": "asset", "detail": f"unsupported asset status: {raw_status}"}]
    return {"key": cell["key"], "wrong": cell["wrong"],
            "mutation": cell["mutation"],
            "reference_violations": cell["reference_violations"],
            "status": status, "asset_status": raw_status, "fired": fired,
            "violations": violations, "unknown_evidence": unknown_evidence,
            "rejected": rejected, "asset_sha256": digest}


def evaluate_spec(spec: dict, question: str, cells: list[dict], problem_id: str) -> dict:
    if not cells:
        return empty_records([], [], "no_cells")
    variable_names = set(cells[0]["solution"]["variables"])
    asset, rejected = prepare_asset(spec, question, variable_names, problem_id)
    if not asset["invariants"]:
        return empty_records(cells, rejected, "no_valid_invariants")
    try:
        validate_asset(asset)
        digest = asset_sha256(asset)
    except (InvalidSpec, TypeError, ValueError) as exc:
        rejected.append({"invariant_id": "asset", "reason": str(exc)})
        return empty_records(cells, rejected, "invalid_asset")
    records = [_candidate_record(cell, run_asset(asset, {}, cell["solution"]),
                                 rejected, digest) for cell in cells]
    wrong = [r for r in records if r["wrong"]]
    clean = [r for r in records if not r["wrong"]]
    tp = sum(r["fired"] for r in wrong)
    fn = len(wrong) - tp
    fp = sum(r["fired"] for r in clean)
    tn = len(clean) - fp
    unknown = sum(r["status"] == "unknown" or bool(r["unknown_evidence"])
                  for r in records)
    not_applicable = sum(r.get("asset_status") == "NOT_APPLICABLE" for r in records)
    detection = tp / max(tp + fn, 1)
    fpr = fp / max(fp + tn, 1)
    evaluation = {"records": records, "tp": tp, "fn": fn, "fp": fp, "tn": tn,
                  "unknown": unknown, "not_applicable": not_applicable,
                  "detection": detection, "false_positive": fpr,
                  "dev_passed": False, "rejected_count": len(rejected),
                  "valid_invariant_count": len(asset["invariants"])}
    evaluation["dev_passed"] = independent_gate_passed(evaluation)
    return evaluation
