"""Versioned, evidence-gated memory assets with a frozen evaluation mode."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ora_agent.memory_guards import validate_guard_contract

SCHEMA_VERSION = "evolving_memory.registry.v0.1"
STATUSES = {"candidate", "dev_passed", "promoted", "rejected", "retired"}
FORMS = {"prompt", "guard"}
KINDS = {"execution", "business"}
FORBIDDEN_PROMPT = re.compile(
    r"en_answer|reference\s+(?:objective|answer)|ground\s*truth|"
    r"\bprob_?\d+\b|\bIDs?\s*\d+", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest_json(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json_atomic(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=path.name + ".", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    os.replace(temporary, path)


def execution_signature(record: dict | None) -> str | None:
    record = record or {}
    stderr = record.get("stderr_tail") or ""
    export_error = record.get("export_error") or ""
    combined = stderr + "\n" + export_error
    if "addVar() got an unexpected keyword argument 'v'" in combined:
        return "pyscipopt_addvar_v"
    if re.search(r"unrecognized optimization sense:\s*(?:max|min)\b", combined, re.I):
        return "pyscipopt_sense"
    if "Nonlinear objective functions are not supported" in combined:
        return "pyscipopt_nonlinear_objective"
    if "expected exactly one top-level model.optimize() call" in combined:
        return "export_optimize_contract"
    if record.get("exec_status") == "timeout":
        return "timeout"
    if record.get("exec_status") not in (None, "ok"):
        return "crash_other"
    if record.get("solver_status") in {"infeasible", "unbounded"}:
        return str(record["solver_status"])
    if export_error:
        return "export_other"
    solution = record.get("solution")
    objective = solution.get("objective") if isinstance(solution, dict) else record.get("objective")
    if objective is None:
        return "no_objective"
    return None


def business_signatures(score: dict | None) -> list[str]:
    if not isinstance(score, dict) or score.get("audit_status") != "complete":
        return []
    signatures = set()
    for item in score.get("violations") or []:
        if isinstance(item, dict):
            rule = item.get("rule")
        else:
            rule = str(item).split(":", 1)[0]
        if rule:
            signatures.add(str(rule))
    return sorted(signatures)


@dataclass(frozen=True)
class PromotionPolicy:
    min_dev_problems: int = 2
    min_gap_problems: int = 1
    dev_quality_gain: float = 0.20
    gap_quality_gain: float = 0.05
    cost_noninferiority_margin: float = 0.05
    min_llm_call_reduction: float = 0.80
    max_execution_harm: int = 0
    max_false_business_accepts: int = 0


class EvolvingMemoryRegistry:
    def __init__(self, path: str | Path, policy: PromotionPolicy | None = None):
        self.path = Path(path)
        self.policy = policy or PromotionPolicy()
        self._frozen_manifest = None
        if self.path.exists():
            payload = json.loads(self.path.read_text())
            if payload.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("unsupported memory registry schema")
            self.assets = payload.get("assets") or []
            self.events = payload.get("events") or []
            if any(asset.get("status") not in STATUSES for asset in self.assets):
                raise ValueError("invalid asset status")
        else:
            self.assets = []
            self.events = []
        default_freeze = self.path.with_suffix(self.path.suffix + ".freeze.json")
        if default_freeze.exists():
            manifest = json.loads(default_freeze.read_text())
            if manifest.get("registry_sha256") != digest_file(self.path):
                raise ValueError("frozen registry content differs from its manifest")
            self._frozen_manifest = manifest

    @property
    def frozen(self) -> bool:
        return self._frozen_manifest is not None

    def _assert_writable(self) -> None:
        if self.frozen:
            raise RuntimeError("frozen memory registry is read-only")

    def _save(self) -> None:
        self._assert_writable()
        write_json_atomic(self.path, {"schema_version": SCHEMA_VERSION,
                                      "assets": self.assets, "events": self.events})

    def _event(self, action: str, asset_id: str, detail: dict | None = None) -> None:
        self.events.append({"event_index": len(self.events), "action": action,
                            "asset_id": asset_id, "at": utc_now(), "detail": detail or {}})

    def get(self, asset_id: str) -> dict:
        matches = [asset for asset in self.assets if asset["asset_id"] == asset_id]
        if len(matches) != 1:
            raise KeyError(asset_id)
        return matches[0]

    def propose(self, spec: dict, origin: dict, parent_id: str | None = None) -> dict:
        self._assert_writable()
        if origin.get("split") != "dev":
            raise ValueError("new memory may only be proposed from dev traces")
        if not origin.get("source_ids") or not origin.get("trace_sha256"):
            raise ValueError("candidate provenance is incomplete")
        kind = spec.get("kind")
        form = spec.get("form")
        signature = spec.get("signature")
        text = spec.get("text")
        guard = spec.get("guard")
        if kind not in KINDS or form not in FORMS or not isinstance(signature, str) or not signature:
            raise ValueError("invalid memory kind, form, or trigger")
        if not isinstance(text, str) or not 20 <= len(text.strip()) <= 2000:
            raise ValueError("memory text must contain 20–2000 characters")
        if FORBIDDEN_PROMPT.search(text):
            raise ValueError("memory text contains an instance identifier or answer reference")
        if form == "prompt" and guard is not None:
            raise ValueError("prompt-only assets cannot contain a guard")
        if form == "guard":
            contract = validate_guard_contract(guard)
            if not contract.get("passed"):
                raise ValueError("guard failed its independent contract")
        if parent_id is not None:
            parent = self.get(parent_id)
            crystallization = (form == "guard" and parent["form"] == "prompt"
                               and parent["status"] == "candidate"
                               and parent["kind"] == kind and parent["signature"] == signature)
            if parent["status"] != "rejected" and not crystallization:
                raise ValueError("a revision must descend from a rejected candidate or a compatible prompt")
        asset_id = f"{form}_{signature}_{sum(a['signature'] == signature for a in self.assets) + 1:03d}"
        if any(asset["asset_id"] == asset_id for asset in self.assets):
            raise ValueError("duplicate asset id")
        content = {"kind": kind, "form": form, "signature": signature,
                   "text": text.strip(), "guard": guard, "origin": origin,
                   "parent_id": parent_id}
        asset = {"asset_id": asset_id, "version": 1, **content,
                 "content_sha256": digest_json(content), "status": "candidate",
                 "created_at": utc_now(), "validations": {}}
        self.assets.append(asset)
        self._event("proposed", asset_id, {"content_sha256": asset["content_sha256"]})
        self._save()
        return asset

    def validate(self, asset_id: str, tier: str, metrics: dict) -> dict:
        self._assert_writable()
        asset = self.get(asset_id)
        if tier not in {"dev", "gapcheck"}:
            raise ValueError("validation tier must be dev or gapcheck")
        expected = "candidate" if tier == "dev" else "dev_passed"
        if asset["status"] != expected:
            raise ValueError(f"{tier} validation requires status {expected}")
        if tier in asset["validations"]:
            raise ValueError("validation tier already recorded; create a revised candidate")
        required = {"n_problems", "execution_gain", "execution_harm",
                    "false_business_accepts", "llm_call_reduction"}
        if not required <= set(metrics):
            raise ValueError("validation metrics are incomplete")
        minimum_n = self.policy.min_dev_problems if tier == "dev" else self.policy.min_gap_problems
        quality_gain = (self.policy.dev_quality_gain if tier == "dev"
                        else self.policy.gap_quality_gain)
        reasons = []
        if metrics["n_problems"] < minimum_n:
            reasons.append("insufficient_independent_problems")
        if metrics.get("runner_errors"):
            reasons.append("runner_errors")
        if metrics["execution_harm"] > self.policy.max_execution_harm:
            reasons.append("execution_harm")
        if metrics["false_business_accepts"] > self.policy.max_false_business_accepts:
            reasons.append("false_business_accept")
        quality = metrics["execution_gain"] >= quality_gain
        if asset["kind"] == "business":
            if not metrics.get("business_labels_complete"):
                reasons.append("business_labels_not_independent")
            if metrics.get("business_gain") is None or metrics.get("business_harm") is None:
                reasons.append("business_metrics_missing")
                quality = False
            else:
                quality = (metrics["business_gain"] >= quality_gain
                           and metrics["business_harm"] == 0)
        cost = (asset["kind"] == "execution" and asset["form"] == "guard"
                and metrics["execution_gain"] >= -self.policy.cost_noninferiority_margin
                and metrics["llm_call_reduction"] >= self.policy.min_llm_call_reduction)
        if asset["form"] == "guard" and not metrics.get("guard_contract_passed"):
            reasons.append("guard_contract_failed")
            cost = False
        passed = not reasons and (quality or cost)
        if not quality and not cost:
            reasons.append("neither_quality_nor_cost_path_passed")
        asset["validations"][tier] = {"metrics": metrics, "quality_path": quality,
                                      "cost_path": cost, "passed": passed,
                                      "reasons": reasons, "at": utc_now()}
        asset["status"] = ("dev_passed" if tier == "dev" else "promoted") if passed else "rejected"
        self._event("dev_validated" if tier == "dev" else "gapcheck_validated",
                    asset_id, {"passed": passed, "reasons": reasons})
        self._save()
        return asset

    def retire(self, asset_id: str, reason: str, evidence: dict) -> dict:
        self._assert_writable()
        asset = self.get(asset_id)
        if asset["status"] != "promoted":
            raise ValueError("only a promoted asset can be retired")
        if not reason.strip():
            raise ValueError("retirement requires a reason")
        asset["status"] = "retired"
        asset["retirement"] = {"reason": reason, "evidence": evidence, "at": utc_now()}
        self._event("retired", asset_id, {"reason": reason})
        self._save()
        return asset

    def freeze(self, protocol: str | Path, implementation: list[str | Path]) -> dict:
        self._assert_writable()
        if not self.path.exists():
            self._save()
        manifest = {"schema_version": "evolving_memory.freeze.v0.1",
                    "registry_sha256": digest_file(self.path),
                    "protocol_path": str(Path(protocol).resolve()),
                    "protocol_sha256": digest_file(Path(protocol)),
                    "implementation_sha256": {str(path): digest_file(Path(path))
                                               for path in implementation},
                    "promoted_asset_ids": [asset["asset_id"] for asset in self.assets
                                           if asset["status"] == "promoted"],
                    "frozen_at": utc_now()}
        destination = self.path.with_suffix(self.path.suffix + ".freeze.json")
        write_json_atomic(destination, manifest)
        self._frozen_manifest = manifest
        return manifest

    def select(self, record: dict, score: dict | None = None,
               statuses: tuple[str, ...] = ("promoted",), forms: tuple[str, ...] = FORMS) -> list[dict]:
        execution = execution_signature(record)
        business = set(business_signatures(score))
        selected = []
        for asset in self.assets:
            if asset["status"] not in statuses or asset["form"] not in forms:
                continue
            if asset["kind"] == "execution" and asset["signature"] == execution:
                selected.append(asset)
            if asset["kind"] == "business" and asset["signature"] in business:
                selected.append(asset)
        return sorted(selected, key=lambda asset: asset["asset_id"])

    def verify_frozen_implementation(self) -> None:
        if not self.frozen:
            raise RuntimeError("registry is not frozen")
        protocol = self._frozen_manifest.get("protocol_path")
        if protocol and digest_file(Path(protocol)) != self._frozen_manifest["protocol_sha256"]:
            raise RuntimeError("frozen protocol changed")
        for path, expected in self._frozen_manifest["implementation_sha256"].items():
            if digest_file(Path(path)) != expected:
                raise RuntimeError(f"frozen implementation changed: {path}")


def memory_view(assets: list[dict], include_prompt: bool = True,
                include_guards: bool = True) -> dict:
    prompt_assets = [asset for asset in assets if include_prompt]
    guard_assets = [asset for asset in assets if include_guards and asset["form"] == "guard"]
    text = "\n\n".join(f"[{asset['asset_id']}@v{asset['version']}]\n{asset['text']}"
                       for asset in prompt_assets)
    return {"text": text, "asset_ids": [asset["asset_id"] for asset in assets],
            "guards": [asset["guard"] for asset in guard_assets],
            "memory_sha256": hashlib.sha256(text.encode()).hexdigest() if text else None,
            "read_only": True, "online_learning": False,
            "asset_scopes": sorted({asset["kind"] for asset in assets})}
