"""Clean-room assets, scoped evidence memory, trust decisions and repair lineage."""
from __future__ import annotations

import hashlib
import inspect
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable

PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"
NOT_APPLICABLE = "not_applicable"
VERDICTS = {PASS, FAIL, UNKNOWN, NOT_APPLICABLE}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def scope_matches(asset_scope: dict, requested: dict) -> bool:
    for key, expected in asset_scope.items():
        if expected == "*":
            continue
        if key not in requested or requested[key] != expected:
            return False
    return True


@dataclass(frozen=True)
class Verdict:
    status: str
    evidence: str = ""

    def __post_init__(self):
        if self.status not in VERDICTS:
            raise ValueError(f"unsupported verdict: {self.status}")


@dataclass(frozen=True)
class AuditCase:
    case_id: str
    artifact: dict
    expected: str

    def __post_init__(self):
        if self.expected not in {PASS, FAIL}:
            raise ValueError("audit expectation must be pass or fail")


@dataclass
class SpecificationAsset:
    spec_id: str
    text: str
    scope: dict
    parent_id: str | None = None
    source_refs: list[str] = field(default_factory=list)
    status: str = "candidate"
    text_sha256: str = ""
    audits: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self):
        if self.status != "candidate":
            raise ValueError("new specifications always start as candidates")
        if not self.scope:
            raise ValueError("specification scope is required")
        if not self.text_sha256:
            self.text_sha256 = text_hash(self.text)


@dataclass
class CleanCheckAsset:
    check_id: str
    evaluator: Callable[[dict], Verdict]
    scope: dict
    source_quote: str
    source_document: str
    status: str = "hint_only"
    code_sha256: str = ""
    audits: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if self.status != "hint_only":
            raise ValueError("new checks always start as hint_only")
        if not self.scope:
            raise ValueError("check scope is required")
        if not self.code_sha256:
            try:
                payload = inspect.getsource(self.evaluator)
            except (OSError, TypeError):
                payload = repr(self.evaluator)
            self.code_sha256 = text_hash(payload)


class EvidenceMemory:
    def __init__(self, min_clean: int = 3, min_wrong: int = 3):
        self.min_clean = min_clean
        self.min_wrong = min_wrong
        self.specifications: dict[str, SpecificationAsset] = {}
        self.checks: dict[str, CleanCheckAsset] = {}
        self.events: list[dict] = []
        self.frozen = False

    def _writable(self):
        if self.frozen:
            raise RuntimeError("clean-room evidence memory is frozen")

    def register_specification(self, asset: SpecificationAsset) -> None:
        self._writable()
        if asset.spec_id in self.specifications:
            raise ValueError("duplicate specification id")
        if asset.parent_id is not None and asset.parent_id not in self.specifications:
            raise ValueError("unknown parent specification")
        self.specifications[asset.spec_id] = asset
        self.events.append({"event": "spec_candidate", "spec_id": asset.spec_id, "at": utc_now()})

    def promote_specification(self, spec_id: str, audit: dict) -> None:
        self._writable()
        asset = self.specifications[spec_id]
        required = ("independent_replay", "changed_features_covered", "scope_confirmed")
        failed = [key for key in required if audit.get(key) is not True]
        record = dict(audit)
        record.update(passed=not failed, failed_requirements=failed, at=utc_now())
        asset.audits.append(record)
        asset.status = "promoted" if not failed else "rejected"
        self.events.append({"event": f"spec_{asset.status}", "spec_id": spec_id, "at": utc_now()})

    def generator_specification(self, scope: dict) -> SpecificationAsset | None:
        candidates = [asset for asset in self.specifications.values()
                      if asset.status == "promoted" and scope_matches(asset.scope, scope)]
        if not candidates:
            return None
        return max(candidates, key=lambda asset: asset.created_at)

    def register_check(self, asset: CleanCheckAsset) -> None:
        self._writable()
        if asset.check_id in self.checks:
            raise ValueError("duplicate check id")
        self.checks[asset.check_id] = asset
        self.events.append({"event": "check_hint_only", "check_id": asset.check_id, "at": utc_now()})

    def authorize_check(self, check_id: str, cases: list[AuditCase]) -> dict:
        self._writable()
        asset = self.checks[check_id]
        records = []
        for case in cases:
            try:
                verdict = asset.evaluator(case.artifact)
                if not isinstance(verdict, Verdict):
                    raise TypeError("evaluator must return Verdict")
            except Exception as exc:
                verdict = Verdict(UNKNOWN, f"{type(exc).__name__}: {exc}")
            records.append({"case_id": case.case_id, "expected": case.expected, "observed": verdict.status})
        applicable = [record for record in records if record["observed"] != NOT_APPLICABLE]
        clean = [record for record in applicable if record["expected"] == PASS]
        wrong = [record for record in applicable if record["expected"] == FAIL]
        tp = sum(record["observed"] == FAIL for record in wrong)
        fp = sum(record["observed"] == FAIL for record in clean)
        fn = sum(record["observed"] != FAIL for record in wrong)
        unknown = sum(record["observed"] == UNKNOWN for record in records)
        precision = tp / (tp + fp) if tp + fp else 0.0
        detection = tp / (tp + fn) if tp + fn else 0.0
        grounded = bool(asset.source_quote.strip() and asset.source_quote in asset.source_document)
        reasons = []
        if not grounded:
            reasons.append("source_not_grounded")
        if len(clean) < self.min_clean or len(wrong) < self.min_wrong:
            reasons.append("insufficient_applicable_audit_cases")
        if fp or precision < 1.0:
            reasons.append("clean_false_positive")
        if detection < 0.6:
            reasons.append("detection_below_threshold")
        if unknown:
            reasons.append("unknown_on_audit")
        passed = not reasons
        asset.status = "veto_enabled" if passed else "rejected"
        audit = {"records": records, "n_clean": len(clean), "n_wrong": len(wrong),
                 "precision": precision, "detection": detection, "unknown": unknown,
                 "passed": passed, "reasons": reasons, "at": utc_now()}
        asset.audits.append(audit)
        self.events.append({"event": f"check_{asset.status}", "check_id": check_id, "at": utc_now()})
        return audit

    def authorized_checks(self, scope: dict) -> list[CleanCheckAsset]:
        return [asset for asset in self.checks.values()
                if asset.status == "veto_enabled" and scope_matches(asset.scope, scope)]

    def retire_check(self, check_id: str, reason: str) -> None:
        self._writable()
        asset = self.checks[check_id]
        if asset.status != "veto_enabled":
            raise ValueError("only authorized checks can be retired")
        asset.status = "retired"
        self.events.append({"event": "check_retired", "check_id": check_id,
                            "reason": reason, "at": utc_now()})

    def freeze(self) -> None:
        self.frozen = True
        self.events.append({"event": "memory_frozen", "at": utc_now()})

    def public_state(self, include_spec_text: bool = False) -> dict:
        return {"frozen": self.frozen, "events": self.events,
                "specifications": [{**asdict(asset), "text": asset.text if include_spec_text else None}
                                   for asset in self.specifications.values()],
                "checks": [{"check_id": asset.check_id, "scope": asset.scope,
                            "source_quote": asset.source_quote, "status": asset.status,
                            "code_sha256": asset.code_sha256, "audits": asset.audits}
                           for asset in self.checks.values()]}


class TrustController:
    def __init__(self, memory: EvidenceMemory):
        self.memory = memory

    def repair_allowed(self, scope: dict, target_check: str,
                       before: dict[str, str], after: dict[str, str]) -> tuple[bool, list[str]]:
        checks = self.memory.authorized_checks(scope)
        if not checks:
            return False, ["no_authorized_check"]
        reasons = []
        downstream_improvements = []
        for asset in checks:
            check_id = asset.check_id
            old = before.get(check_id, UNKNOWN)
            new = after.get(check_id, UNKNOWN)
            if UNKNOWN in {old, new}:
                reasons.append(f"unknown:{check_id}")
            elif check_id == target_check:
                if (old, new) not in {(FAIL, PASS), (PASS, PASS), (NOT_APPLICABLE, NOT_APPLICABLE)}:
                    reasons.append(f"target_not_improved:{check_id}:{old}->{new}")
            elif old == FAIL and new == PASS:
                downstream_improvements.append(check_id)
            elif old != new:
                reasons.append(f"non_target_changed:{check_id}:{old}->{new}")
        if reasons:
            return False, reasons
        if downstream_improvements:
            final_passed, final_reasons = self.final_accept(scope, after)
            if not final_passed:
                return False, ["unverified_non_target_improvement", *final_reasons]
        return True, []

    def final_accept(self, scope: dict, verdicts: dict[str, str]) -> tuple[bool, list[str]]:
        checks = self.memory.authorized_checks(scope)
        applicable = [asset for asset in checks if verdicts.get(asset.check_id) != NOT_APPLICABLE]
        if not applicable:
            return False, ["no_applicable_authorized_check"]
        reasons = [f"{asset.check_id}:{verdicts.get(asset.check_id, UNKNOWN)}"
                   for asset in applicable if verdicts.get(asset.check_id) != PASS]
        return not reasons, reasons


@dataclass
class RepairNode:
    node_id: str
    parent_id: str | None
    code_sha256: str
    target_check: str | None
    before: dict[str, str]
    after: dict[str, str]
    accepted: bool
    reasons: list[str]


class RepairDAG:
    def __init__(self, controller: TrustController):
        self.controller = controller
        self.nodes: dict[str, RepairNode] = {}
        self.code_hashes: set[str] = set()

    def add_root(self, code: str, verdicts: dict[str, str]) -> RepairNode:
        digest = text_hash(code)
        if digest in self.code_hashes:
            raise ValueError("duplicate root code")
        node = RepairNode("root", None, digest, None, {}, verdicts, True, [])
        self.nodes[node.node_id] = node
        self.code_hashes.add(digest)
        return node

    def add_repair(self, parent_id: str, code: str, target_check: str,
                   before: dict[str, str], after: dict[str, str], scope: dict) -> RepairNode:
        digest = text_hash(code)
        if digest in self.code_hashes:
            raise ValueError("repair produced duplicate code")
        accepted, reasons = self.controller.repair_allowed(scope, target_check, before, after)
        node = RepairNode(f"{parent_id}/repair:{len(self.nodes)}", parent_id, digest,
                          target_check, before, after, accepted, reasons)
        self.nodes[node.node_id] = node
        self.code_hashes.add(digest)
        return node

    def rollback(self, node_id: str) -> str:
        node = self.nodes[node_id]
        node.accepted = False
        if "rollback_rejected" not in node.reasons:
            node.reasons.append("rollback_rejected")
        if node.parent_id is None:
            raise ValueError("cannot rollback to a parent of root")
        return node.parent_id

    def to_dict(self) -> dict:
        return {"nodes": [asdict(node) for node in self.nodes.values()]}


def restore_specifications(payload: dict) -> EvidenceMemory:
    memory = EvidenceMemory()
    for record in payload.get("specifications", []):
        asset = SpecificationAsset(
            spec_id=record["spec_id"], text=record["text"], scope=record["scope"],
            parent_id=record.get("parent_id"), source_refs=record.get("source_refs", []),
            text_sha256=record["text_sha256"], audits=record.get("audits", []),
            created_at=record["created_at"])
        status = record["status"]
        if status == "promoted" and not any(audit.get("passed") for audit in asset.audits):
            raise ValueError("promoted specification lacks a passing audit")
        asset.status = status
        memory.register_specification(asset)
    if payload.get("frozen"):
        memory.freeze()
    return memory
