"""Provenance-gated veto authority and layered repair acceptance."""
from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"
HINT_ONLY = "hint_only"
VETO_ENABLED = "veto_enabled"
REJECTED = "rejected"
RETIRED = "retired"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def verbatim_source(quote: str, document: str) -> dict:
    return {"kind": "verbatim_problem", "quote": quote, "document": document}


def convention_source(asset_id: str, registry_sha256: str, independently_validated: bool) -> dict:
    return {"kind": "validated_convention", "asset_id": asset_id,
            "registry_sha256": registry_sha256,
            "independently_validated": independently_validated}


def valid_source(source: dict) -> bool:
    kind = source.get("kind")
    if kind == "verbatim_problem":
        quote = source.get("quote")
        document = source.get("document")
        return bool(isinstance(quote, str) and quote.strip()
                    and isinstance(document, str) and quote in document)
    if kind == "validated_convention":
        digest = source.get("registry_sha256")
        return bool(source.get("asset_id") and source.get("independently_validated") is True
                    and isinstance(digest, str) and len(digest) == 64
                    and all(character in "0123456789abcdef" for character in digest))
    return False


@dataclass(frozen=True)
class Verdict:
    status: str
    evidence: str = ""

    def __post_init__(self):
        if self.status not in {PASS, FAIL, UNKNOWN}:
            raise ValueError("verdict must be pass, fail, or unknown")


@dataclass(frozen=True)
class TrustedCase:
    case_id: str
    artifact: dict
    expected: str

    def __post_init__(self):
        if self.expected not in {PASS, FAIL}:
            raise ValueError("trusted label must be pass or fail")


@dataclass
class CheckAsset:
    check_id: str
    level: int
    evaluator: Callable[[dict], Verdict]
    source: dict
    parent_id: str | None = None
    status: str = HINT_ONLY
    code_sha256: str = ""
    audits: list[dict] = None

    def __post_init__(self):
        if self.level < 0:
            raise ValueError("check level must be nonnegative")
        if self.status != HINT_ONLY:
            raise ValueError("new checks always start as hint_only")
        if not self.code_sha256:
            try:
                payload = inspect.getsource(self.evaluator)
            except (OSError, TypeError):
                payload = repr(self.evaluator)
            self.code_sha256 = hashlib.sha256(payload.encode()).hexdigest()
        self.audits = self.audits or []


class VerificationGovernor:
    def __init__(self, min_clean: int = 3, min_wrong: int = 3,
                 min_precision: float = 1.0, min_detection: float = 0.6):
        self.min_clean = min_clean
        self.min_wrong = min_wrong
        self.min_precision = min_precision
        self.min_detection = min_detection
        self.checks: dict[str, CheckAsset] = {}
        self.events: list[dict] = []
        self.frozen = False

    def _writable(self) -> None:
        if self.frozen:
            raise RuntimeError("verification registry is frozen")

    def register(self, asset: CheckAsset) -> CheckAsset:
        self._writable()
        if asset.check_id in self.checks:
            raise ValueError("duplicate check id")
        if asset.parent_id is not None and asset.parent_id not in self.checks:
            raise ValueError("unknown parent check")
        self.checks[asset.check_id] = asset
        self.events.append({"action": "registered_hint_only", "check_id": asset.check_id,
                            "parent_id": asset.parent_id, "at": utc_now()})
        return asset

    def replay(self, check_id: str, cases: list[TrustedCase]) -> dict:
        asset = self.checks[check_id]
        records = []
        for case in cases:
            try:
                verdict = asset.evaluator(case.artifact)
                if not isinstance(verdict, Verdict):
                    raise TypeError("evaluator did not return Verdict")
            except Exception as exc:
                verdict = Verdict(UNKNOWN, f"{type(exc).__name__}: {exc}")
            records.append({"case_id": case.case_id, "expected": case.expected,
                            "observed": verdict.status, "evidence": verdict.evidence})
        clean = [record for record in records if record["expected"] == PASS]
        wrong = [record for record in records if record["expected"] == FAIL]
        tp = sum(record["observed"] == FAIL for record in wrong)
        fn = sum(record["observed"] != FAIL for record in wrong)
        fp = sum(record["observed"] == FAIL for record in clean)
        tn = sum(record["observed"] == PASS for record in clean)
        unknown = sum(record["observed"] == UNKNOWN for record in records)
        precision = tp / (tp + fp) if tp + fp else 0.0
        detection = tp / (tp + fn) if tp + fn else 0.0
        return {"records": records, "n_clean": len(clean), "n_wrong": len(wrong),
                "tp": tp, "fn": fn, "fp": fp, "tn": tn, "unknown": unknown,
                "precision": precision, "detection": detection}

    def promote(self, check_id: str, cases: list[TrustedCase]) -> dict:
        self._writable()
        asset = self.checks[check_id]
        audit = self.replay(check_id, cases)
        reasons = []
        if not valid_source(asset.source):
            reasons.append("source_not_independently_grounded")
        if audit["n_clean"] < self.min_clean or audit["n_wrong"] < self.min_wrong:
            reasons.append("insufficient_trusted_cases")
        if audit["unknown"]:
            reasons.append("unknown_on_trusted_cases")
        if audit["precision"] < self.min_precision:
            reasons.append("precision_below_threshold")
        if audit["detection"] < self.min_detection:
            reasons.append("detection_below_threshold")
        passed = not reasons
        asset.status = VETO_ENABLED if passed else REJECTED
        audit.update(passed=passed, reasons=reasons, at=utc_now())
        asset.audits.append(audit)
        self.events.append({"action": "veto_enabled" if passed else "rejected",
                            "check_id": check_id, "reasons": reasons, "at": utc_now()})
        return audit

    def evaluate(self, artifact: dict, include_hints: bool = True) -> dict[str, str]:
        verdicts = {}
        for check_id, asset in self.checks.items():
            if asset.status == RETIRED or (not include_hints and asset.status != VETO_ENABLED):
                continue
            try:
                verdict = asset.evaluator(artifact)
                if not isinstance(verdict, Verdict):
                    raise TypeError("evaluator did not return Verdict")
            except Exception as exc:
                verdict = Verdict(UNKNOWN, f"{type(exc).__name__}: {exc}")
            verdicts[check_id] = verdict.status
        return verdicts

    def repair_allowed(self, target_level: int, before: dict[str, str],
                       after: dict[str, str]) -> tuple[bool, list[str]]:
        reasons = []
        for check_id, asset in self.checks.items():
            if asset.status != VETO_ENABLED or asset.level <= target_level:
                continue
            old = before.get(check_id)
            new = after.get(check_id)
            if old is None or new is None:
                reasons.append(f"missing_higher_check:{check_id}")
            elif old != new:
                reasons.append(f"higher_check_changed:{check_id}:{old}->{new}")
        return not reasons, reasons

    def final_accept(self, verdicts: dict[str, str]) -> tuple[bool, list[str]]:
        authorized = [check_id for check_id, asset in self.checks.items()
                      if asset.status == VETO_ENABLED]
        if not authorized:
            return False, ["no_veto_enabled_check"]
        reasons = [f"{check_id}:{verdicts.get(check_id, UNKNOWN)}"
                   for check_id in authorized if verdicts.get(check_id) != PASS]
        return not reasons, reasons

    def retire(self, check_id: str, reason: str) -> None:
        self._writable()
        asset = self.checks[check_id]
        if asset.status != VETO_ENABLED:
            raise ValueError("only veto-enabled checks can be retired")
        asset.status = RETIRED
        self.events.append({"action": "retired", "check_id": check_id,
                            "reason": reason, "at": utc_now()})

    def freeze(self) -> dict:
        self.frozen = True
        return {"veto_enabled": sorted(check_id for check_id, asset in self.checks.items()
                                      if asset.status == VETO_ENABLED),
                "events": len(self.events)}

    def public_state(self) -> dict:
        return {"frozen": self.frozen, "events": self.events,
                "checks": [{"check_id": asset.check_id, "level": asset.level,
                            "parent_id": asset.parent_id, "status": asset.status,
                            "code_sha256": asset.code_sha256, "source_kind": asset.source.get("kind"),
                            "audits": asset.audits}
                           for asset in self.checks.values()]}


class LayeredAcceptance:
    def __init__(self, governor: VerificationGovernor, base_criterion=None, target_level: int = 0,
                 require_final: bool = True):
        from gepa.strategies.acceptance import StrictImprovementAcceptance
        self.governor = governor
        self.base = base_criterion or StrictImprovementAcceptance()
        self.target_level = target_level
        self.require_final = require_final
        self.reason = ""

    def should_accept(self, proposal, state) -> bool:
        if not self.base.should_accept(proposal, state):
            self.reason = "proxy_not_improved"
            return False
        before = proposal.eval_before.outputs if proposal.eval_before else []
        after = proposal.eval_after.outputs if proposal.eval_after else []
        if len(before) != len(after) or not after:
            self.reason = "missing_paired_check_outputs"
            return False
        for old, new in zip(before, after):
            allowed, reasons = self.governor.repair_allowed(
                self.target_level, old.get("check_verdicts", {}), new.get("check_verdicts", {}))
            if not allowed:
                self.reason = ";".join(reasons)
                return False
            if self.require_final:
                accepted, final_reasons = self.governor.final_accept(new.get("check_verdicts", {}))
                if not accepted:
                    self.reason = "final_check_failed:" + ";".join(final_reasons)
                    return False
        self.reason = ""
        return True

    def reject_reason(self, proposal, state) -> str:
        return self.reason or "layered_acceptance_rejected"
