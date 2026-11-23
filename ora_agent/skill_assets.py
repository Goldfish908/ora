"""Method-level skill assets with replay-gated lifecycle governance."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

CANDIDATE = "candidate"
DEV_PASSED = "dev_passed"
PROMOTED = "promoted"
REJECTED = "rejected"
RETIRED = "retired"
STATUSES = {CANDIDATE, DEV_PASSED, PROMOTED, REJECTED, RETIRED}
LAYERS = ("dev", "gapcheck")
SCHEMA_VERSION = 1

_HASH = re.compile(r"[0-9a-f]{64}")
_TRANSITIONS = {
    CANDIDATE: {DEV_PASSED, REJECTED},
    DEV_PASSED: {PROMOTED, REJECTED},
    PROMOTED: {RETIRED},
    REJECTED: set(),
    RETIRED: set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def _digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest_json(value: Any) -> str:
    return _digest_text(_canonical(value))


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _strings(value: Iterable[str], name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError(f"{name} must be a sequence of strings")
    result = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise ValueError(f"{name} must contain nonempty strings")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must not contain duplicates")
    return result


def _cost(value: dict[str, float]) -> dict[str, float]:
    if not isinstance(value, dict):
        raise TypeError("cost must be an object")
    result = {}
    for key, number in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("cost keys must be nonempty strings")
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise TypeError("cost values must be numeric")
        if not math.isfinite(number) or number < 0:
            raise ValueError("cost values must be finite and nonnegative")
        result[key] = number
    return result


@dataclass
class SkillAsset:
    method_id: str
    version: str
    trigger_signature: dict[str, Any]
    required_inputs: tuple[str, ...]
    dataset_scope: tuple[str, ...]
    domain_scope: tuple[str, ...]
    api_scope: tuple[str, ...]
    schema_scope: tuple[str, ...]
    operations: tuple[str, ...]
    allowed_edits: tuple[str, ...]
    invariants: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    positive_examples: tuple[Any, ...]
    negative_examples: tuple[Any, ...]
    near_miss_examples: tuple[Any, ...]
    ambiguous_examples: tuple[Any, ...]
    out_of_scope_examples: tuple[Any, ...]
    code: str
    text: str
    baseline_implementation_sha256: str
    evaluator_sha256: str
    task_coverage: dict[str, tuple[str, ...]]
    required_seeds: tuple[int, ...]
    cost: dict[str, float] = field(default_factory=dict)
    min_gained_true: dict[str, int] = field(
        default_factory=lambda: {"dev": 1, "gapcheck": 1})
    asset_id: str = field(init=False)
    code_sha256: str = field(init=False)
    text_sha256: str = field(init=False)
    evidence_binding_sha256: str = field(init=False)
    parent_id: str | None = field(init=False, default=None)
    lineage: tuple[str, ...] = field(init=False, default=())
    revision: int = field(init=False, default=0)
    status: str = field(init=False, default=CANDIDATE)
    activation_log: list[dict] = field(init=False, default_factory=list)
    state_history: list[dict] = field(init=False, default_factory=list)
    validation_reports: list[dict] = field(init=False, default_factory=list)
    dev_evidence_sha256: str | None = field(init=False, default=None)
    promotion_evidence_sha256: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if not isinstance(self.method_id, str) or not self.method_id.strip():
            raise ValueError("method_id must be a nonempty string")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version must be a nonempty string")
        if ":" in self.method_id or ":" in self.version:
            raise ValueError("method_id and version must not contain ':'")
        self.asset_id = f"{self.method_id}:{self.version}"
        if not isinstance(self.trigger_signature, dict) or not self.trigger_signature:
            raise ValueError("trigger_signature must be a nonempty object")
        _canonical(self.trigger_signature)
        for name in ("required_inputs", "dataset_scope", "domain_scope", "api_scope",
                     "schema_scope", "operations", "allowed_edits", "invariants",
                     "forbidden_actions"):
            setattr(self, name, _strings(getattr(self, name), name))
        for name in ("positive_examples", "negative_examples", "near_miss_examples",
                     "ambiguous_examples", "out_of_scope_examples"):
            examples = tuple(getattr(self, name))
            _canonical(examples)
            setattr(self, name, examples)
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValueError("code must be nonempty source text")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text must be nonempty")
        self.code_sha256 = _digest_text(self.code)
        self.text_sha256 = _digest_text(self.text)
        if not _valid_hash(self.baseline_implementation_sha256):
            raise ValueError("baseline_implementation_sha256 must be a lowercase SHA-256 digest")
        if self.baseline_implementation_sha256 == self.code_sha256:
            raise ValueError("baseline implementation must differ from the skill implementation")
        if not _valid_hash(self.evaluator_sha256):
            raise ValueError("evaluator_sha256 must be a lowercase SHA-256 digest")
        self.evidence_binding_sha256 = _digest_json({
            "baseline_implementation_sha256": self.baseline_implementation_sha256,
            "treatment_implementation_sha256": self.code_sha256,
            "evaluator_sha256": self.evaluator_sha256,
        })
        if not isinstance(self.task_coverage, dict) or set(self.task_coverage) != set(LAYERS):
            raise ValueError("task_coverage must define exactly dev and gapcheck")
        coverage = {}
        for layer in LAYERS:
            coverage[layer] = _strings(self.task_coverage[layer], f"task_coverage.{layer}")
            if not coverage[layer]:
                raise ValueError(f"task_coverage.{layer} must not be empty")
        if set(coverage["dev"]) & set(coverage["gapcheck"]):
            raise ValueError("dev and gapcheck tasks must be disjoint")
        self.task_coverage = coverage
        if isinstance(self.required_seeds, (str, bytes)):
            raise TypeError("required_seeds must be a sequence of integers")
        self.required_seeds = tuple(self.required_seeds)
        if not self.required_seeds:
            raise ValueError("required_seeds must not be empty")
        if any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
               for seed in self.required_seeds):
            raise ValueError("required_seeds must contain nonnegative integers")
        if len(set(self.required_seeds)) != len(self.required_seeds):
            raise ValueError("required_seeds must not contain duplicates")
        self.cost = _cost(self.cost)
        if not isinstance(self.min_gained_true, dict) or set(self.min_gained_true) != set(LAYERS):
            raise ValueError("min_gained_true must define exactly dev and gapcheck")
        thresholds = {}
        for layer in LAYERS:
            threshold = self.min_gained_true[layer]
            if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 1:
                raise ValueError("min_gained_true thresholds must be positive integers")
            thresholds[layer] = threshold
        self.min_gained_true = thresholds
        self.state_history.append({
            "from": None, "to": CANDIDATE, "reason": "proposed", "at": _now(),
        })

    @property
    def skill_id(self) -> str:
        return self.asset_id

    @property
    def root_id(self) -> str:
        return self.lineage[0] if self.lineage else self.asset_id

    @property
    def status_history(self) -> list[dict]:
        return self.state_history

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SkillAsset":
        if not isinstance(data, dict):
            raise TypeError("serialized asset must be an object")
        definition = {}
        for item in fields(cls):
            if item.init:
                if item.name not in data:
                    raise ValueError(f"serialized asset is missing {item.name}")
                definition[item.name] = copy.deepcopy(data[item.name])
        asset = cls(**definition)
        if data.get("asset_id") != asset.asset_id:
            raise ValueError("serialized asset id does not match method and version")
        if data.get("code_sha256") != asset.code_sha256:
            raise ValueError("code hash mismatch")
        if data.get("text_sha256") != asset.text_sha256:
            raise ValueError("text hash mismatch")
        if data.get("evidence_binding_sha256") != asset.evidence_binding_sha256:
            raise ValueError("evidence binding hash mismatch")
        lineage = tuple(data.get("lineage", ()))
        if any(not isinstance(item, str) or not item for item in lineage):
            raise ValueError("invalid lineage")
        if len(set(lineage)) != len(lineage) or asset.asset_id in lineage:
            raise ValueError("lineage must be acyclic")
        parent_id = data.get("parent_id")
        if parent_id != (lineage[-1] if lineage else None):
            raise ValueError("parent_id does not match lineage")
        revision = data.get("revision")
        if revision != len(lineage):
            raise ValueError("revision does not match lineage")
        asset.parent_id = parent_id
        asset.lineage = lineage
        asset.revision = revision
        status = data.get("status")
        if status not in STATUSES:
            raise ValueError("invalid asset status")
        history = data.get("state_history")
        if not isinstance(history, list) or not history:
            raise ValueError("state_history must not be empty")
        previous = None
        for entry in history:
            if not isinstance(entry, dict) or entry.get("from") != previous:
                raise ValueError("broken state history")
            current = entry.get("to")
            if previous is None:
                if current != CANDIDATE:
                    raise ValueError("state history must start at candidate")
            elif current not in _TRANSITIONS[previous]:
                raise ValueError(f"invalid state transition {previous}->{current}")
            previous = current
        if previous != status:
            raise ValueError("status does not match state history")
        asset.status = status
        asset.state_history = copy.deepcopy(history)
        asset.activation_log = copy.deepcopy(data.get("activation_log", []))
        asset.validation_reports = copy.deepcopy(data.get("validation_reports", []))
        if not isinstance(asset.activation_log, list) or not isinstance(asset.validation_reports, list):
            raise ValueError("asset logs must be arrays")
        _canonical(asset.activation_log)
        _canonical(asset.validation_reports)
        for name in ("dev_evidence_sha256", "promotion_evidence_sha256"):
            value = data.get(name)
            if value is not None and not _valid_hash(value):
                raise ValueError(f"invalid {name}")
            setattr(asset, name, value)
        if status in {DEV_PASSED, PROMOTED} and asset.dev_evidence_sha256 is None:
            raise ValueError("validated assets require dev evidence provenance")
        if status == PROMOTED and asset.promotion_evidence_sha256 is None:
            raise ValueError("promoted assets require promotion evidence provenance")
        if status in {CANDIDATE, REJECTED} and asset.promotion_evidence_sha256 is not None:
            raise ValueError("unpromoted assets cannot have promotion evidence provenance")
        return asset


def _normalise_records(evidence: Any) -> tuple[list[dict], list[str]]:
    issues = []
    if not isinstance(evidence, dict):
        return [], ["invalid_evidence:evidence must be an object"]
    if "records" in evidence:
        records = evidence["records"]
        if not isinstance(records, list):
            return [], ["missing_pair:records must be an array"]
    else:
        records = []
        for layer in LAYERS:
            layered = evidence.get(layer, [])
            if not isinstance(layered, list):
                issues.append(f"missing_pair:{layer} must be an array")
                continue
            for record in layered:
                if isinstance(record, dict):
                    record = {**record, "split": record.get("split", layer)}
                records.append(record)
    normalised = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            issues.append(f"invalid_evidence:record {index} is not an object")
            continue
        try:
            _canonical(record)
        except (TypeError, ValueError):
            issues.append(f"invalid_evidence:record {index} is not finite JSON")
            continue
        normalised.append(copy.deepcopy(record))
    if not normalised:
        issues.append("missing_pair:no raw paired records")
    return normalised, issues


def _records_digest(records: list[dict], binding_sha256: str) -> str:
    ordered = sorted(records, key=lambda row: (
        str(row.get("split")), str(row.get("task_id")), str(row.get("seed")), _canonical(row)))
    return _digest_json({"evidence_binding_sha256": binding_sha256, "records": ordered})


def replay_paired_evidence(asset: SkillAsset, evidence: dict,
                           layers: Iterable[str] = LAYERS) -> dict:
    """Recompute acceptance from raw no-skill/skill outcomes, ignoring summaries."""
    layers = tuple(layers)
    if not layers or any(layer not in LAYERS for layer in layers):
        raise ValueError("layers must be dev, gapcheck, or both")
    records, issues = _normalise_records(evidence)
    issue_layers: dict[str, str | None] = {}
    for issue in issues:
        issue_layers[issue] = None

    def reject(code: str, detail: str = "", layer: str | None = None) -> None:
        reason = code + (f":{detail}" if detail else "")
        if reason not in issue_layers:
            issue_layers[reason] = layer

    if asset.code_sha256 != _digest_text(asset.code):
        reject("implementation_hash:asset code hash mismatch")
    if asset.text_sha256 != _digest_text(asset.text):
        reject("text_hash:asset text hash mismatch")
    if not _valid_hash(asset.baseline_implementation_sha256):
        reject("baseline_implementation_hash:invalid asset baseline hash")
    if asset.baseline_implementation_sha256 == asset.code_sha256:
        reject("baseline_implementation_hash:baseline and skill implementations must differ")
    if not _valid_hash(asset.evaluator_sha256):
        reject("evaluator_hash:invalid asset evaluator hash")
    expected_binding = _digest_json({
        "baseline_implementation_sha256": asset.baseline_implementation_sha256,
        "treatment_implementation_sha256": asset.code_sha256,
        "evaluator_sha256": asset.evaluator_sha256,
    })
    if asset.evidence_binding_sha256 != expected_binding:
        reject("evidence_binding:asset implementation/evaluator binding hash mismatch")

    derived = []
    actual_keys = {layer: set() for layer in LAYERS}
    seen = set()
    for record in records:
        split = record.get("split")
        task_id = record.get("task_id")
        seed = record.get("seed")
        if split not in LAYERS:
            reject("invalid_layer", str(split))
            continue
        if split not in layers:
            continue
        valid_key = True
        if not isinstance(task_id, str) or not task_id.strip():
            reject("task_coverage", "task_id must be a nonempty string", split)
            valid_key = False
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            reject("seed_coverage", f"explicit nonnegative seed required for {task_id}", split)
            valid_key = False
        key = (split, task_id, seed)
        if valid_key:
            if key in seen:
                reject("duplicate_pair", f"{split}/{task_id}/{seed}", split)
            seen.add(key)
            actual_keys[split].add(key)
        pair_name = f"{split}/{task_id}/{seed}"
        control = record.get("control")
        treatment = record.get("treatment")
        if not isinstance(control, dict) or not isinstance(treatment, dict):
            reject("missing_pair", pair_name, split)
            continue
        outcomes = {}
        pair_unknown = False
        for arm_name, arm in (("control", control), ("treatment", treatment)):
            prefix = f"{pair_name}/{arm_name}"
            initial = arm.get("initial_artifact_sha256")
            implementation = arm.get("implementation_sha256")
            evaluator = arm.get("evaluator_sha256")
            expected_implementation = (asset.baseline_implementation_sha256
                                       if arm_name == "control" else asset.code_sha256)
            implementation_error = ("baseline_implementation_hash"
                                    if arm_name == "control" else "implementation_hash")
            if not _valid_hash(initial):
                reject("initial_artifact", f"{prefix} has invalid initial artifact hash", split)
            if implementation != expected_implementation or not _valid_hash(implementation):
                reject(implementation_error, prefix, split)
            if evaluator != asset.evaluator_sha256 or not _valid_hash(evaluator):
                reject("evaluator_hash", prefix, split)
            status = arm.get("status")
            true_correct = arm.get("true_correct")
            proxy_correct = arm.get("proxy_correct")
            unknown = (status != "OK" or not isinstance(true_correct, bool)
                       or not isinstance(proxy_correct, bool))
            if unknown:
                pair_unknown = True
                reject("UNKNOWN", prefix, split)
            outcomes[arm_name] = {
                "initial": initial,
                "true_correct": true_correct,
                "proxy_correct": proxy_correct,
                "unknown": unknown,
            }
        if control.get("initial_artifact_sha256") != treatment.get("initial_artifact_sha256"):
            reject("initial_artifact", f"{pair_name} control/treatment differ", split)
        if control.get("evaluator_sha256") != treatment.get("evaluator_sha256"):
            reject("evaluator_hash", f"{pair_name} control/treatment differ", split)
        gained_true = False
        lost_true = False
        new_phantom = False
        if not pair_unknown:
            old_true = outcomes["control"]["true_correct"]
            new_true = outcomes["treatment"]["true_correct"]
            old_phantom = (outcomes["control"]["proxy_correct"]
                           and not outcomes["control"]["true_correct"])
            new_phantom_value = (outcomes["treatment"]["proxy_correct"]
                                 and not outcomes["treatment"]["true_correct"])
            gained_true = not old_true and new_true
            lost_true = old_true and not new_true
            new_phantom = not old_phantom and new_phantom_value
            if lost_true:
                reject("lost_true", pair_name, split)
            if new_phantom:
                reject("new_phantom", pair_name, split)
        derived.append({
            "split": split, "task_id": task_id, "seed": seed,
            "unknown": pair_unknown, "gained_true": gained_true,
            "lost_true": lost_true, "new_phantom": new_phantom,
        })

    for layer in layers:
        expected = {(layer, task, seed) for task in asset.task_coverage[layer]
                    for seed in asset.required_seeds}
        missing = sorted(expected - actual_keys[layer], key=lambda item: (item[1], item[2]))
        extra = sorted(actual_keys[layer] - expected, key=lambda item: (item[1], item[2]))
        for _, task, seed in missing:
            reject("missing_pair", f"required {layer}/{task}/{seed}", layer)
        for _, task, seed in extra:
            expected_tasks = asset.task_coverage[layer]
            code = "task_coverage" if task not in expected_tasks else "seed_coverage"
            reject(code, f"unexpected {layer}/{task}/{seed}", layer)
        if not actual_keys[layer]:
            reject("missing_pair", f"no {layer} pairs", layer)
        gained = sum(row["gained_true"] for row in derived if row["split"] == layer)
        required = asset.min_gained_true[layer]
        if gained < required:
            code = "no_gained_true" if gained == 0 else "insufficient_gained_true"
            reject(code, f"{layer} requires {required}, observed {gained}", layer)

    dev_records = [record for record in records if record.get("split") == "dev"]
    layer_reports = {}
    for layer in layers:
        layer_reasons = [reason for reason, owner in issue_layers.items()
                         if owner is None or owner == layer]
        rows = [row for row in derived if row["split"] == layer]
        layer_reports[layer] = {
            "pairs": len(rows),
            "gained_true": sum(row["gained_true"] for row in rows),
            "required_gained_true": asset.min_gained_true[layer],
            "lost_true": sum(row["lost_true"] for row in rows),
            "new_phantom": sum(row["new_phantom"] for row in rows),
            "unknown": sum(row["unknown"] for row in rows),
            "passed": not layer_reasons,
            "reasons": layer_reasons,
        }
    reasons = list(issue_layers)
    return {
        "schema_version": SCHEMA_VERSION,
        "metrics_used": False,
        "passed": not reasons,
        "status": "passed" if not reasons else REJECTED,
        "reasons": reasons,
        "layers": layer_reports,
        "records": derived,
        "evidence_binding_sha256": asset.evidence_binding_sha256,
        "dev_evidence_sha256": _records_digest(dev_records, asset.evidence_binding_sha256),
        "evidence_sha256": _records_digest(records, asset.evidence_binding_sha256),
        "gapcheck_failed": (layers == LAYERS and not layer_reports["gapcheck"]["passed"]),
    }


class SkillRegistry:
    def __init__(self, *, frozen: bool = False, read_only: bool = False):
        self.assets: dict[str, SkillAsset] = {}
        self.frozen = bool(frozen)
        self.read_only = bool(read_only)

    def _writable(self) -> None:
        if self.read_only:
            raise RuntimeError("skill registry is read-only")
        if self.frozen:
            raise RuntimeError("skill registry is frozen")

    def _asset(self, asset_id: str) -> SkillAsset:
        try:
            return self.assets[asset_id]
        except KeyError as exc:
            raise KeyError(f"unknown skill asset: {asset_id}") from exc

    def propose(self, asset: SkillAsset) -> SkillAsset:
        self._writable()
        if not isinstance(asset, SkillAsset):
            raise TypeError("asset must be a SkillAsset")
        if asset.parent_id is not None or asset.lineage or asset.revision:
            raise ValueError("revisions must be created with revise")
        if asset.status != CANDIDATE:
            raise ValueError("new assets must start as candidate")
        if asset.asset_id in self.assets:
            raise ValueError(f"duplicate skill asset: {asset.asset_id}")
        self.assets[asset.asset_id] = asset
        return asset

    def validate(self, asset_id: str, evidence: dict) -> dict:
        self._writable()
        asset = self._asset(asset_id)
        if asset.status != CANDIDATE:
            raise ValueError("only candidate assets can enter dev validation")
        report = replay_paired_evidence(asset, evidence, ("dev",))
        report.update({"asset_id": asset_id, "action": "validate", "at": _now()})
        asset.validation_reports.append(copy.deepcopy(report))
        if report["passed"]:
            asset.dev_evidence_sha256 = report["dev_evidence_sha256"]
            self._transition(asset, DEV_PASSED, "raw dev evidence passed", report)
        else:
            self._transition(asset, REJECTED, "raw dev evidence rejected", report)
        report["status"] = asset.status
        return report

    def promote(self, asset_id: str, evidence: dict) -> dict:
        self._writable()
        asset = self._asset(asset_id)
        if asset.status != DEV_PASSED:
            raise ValueError("only dev_passed assets can be promoted")
        report = replay_paired_evidence(asset, evidence, LAYERS)
        reasons = list(report["reasons"])
        if report["dev_evidence_sha256"] != asset.dev_evidence_sha256:
            reasons.append("dev_evidence_changed:promotion must replay the validated dev records")
        report["passed"] = not reasons
        report["reasons"] = reasons
        report.update({"asset_id": asset_id, "action": "promote", "at": _now()})
        asset.validation_reports.append(copy.deepcopy(report))
        if report["passed"]:
            asset.promotion_evidence_sha256 = report["evidence_sha256"]
            self._transition(asset, PROMOTED, "raw dev and gapcheck evidence passed", report)
        else:
            self._transition(asset, REJECTED, "promotion evidence rejected", report)
        report["status"] = asset.status
        return report

    def _transition(self, asset: SkillAsset, status: str, reason: str, report: dict | None = None) -> None:
        if status not in _TRANSITIONS[asset.status]:
            raise ValueError(f"invalid state transition {asset.status}->{status}")
        entry = {"from": asset.status, "to": status, "reason": reason, "at": _now()}
        if report is not None:
            entry["evidence_sha256"] = report["evidence_sha256"]
            entry["reasons"] = list(report["reasons"])
        asset.state_history.append(entry)
        asset.status = status

    def retire(self, asset_id: str, reason: str) -> SkillAsset:
        self._writable()
        asset = self._asset(asset_id)
        if asset.status != PROMOTED:
            raise ValueError("only promoted assets can be retired")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("retirement reason must be nonempty")
        self._transition(asset, RETIRED, reason)
        return asset

    def revise(self, asset_id: str, new_version: str | None = None, **changes: Any) -> SkillAsset:
        self._writable()
        old = self._asset(asset_id)
        if new_version is None:
            new_version = changes.pop("version", None)
        if not isinstance(new_version, str) or not new_version.strip():
            raise ValueError("a new version is required")
        forbidden = {"method_id", "asset_id", "skill_id", "status", "parent_id", "lineage",
                     "revision", "code_sha256", "text_sha256", "activation_log",
                     "state_history", "status_history", "validation_reports",
                     "dev_evidence_sha256", "promotion_evidence_sha256"}
        unknown = set(changes) - {item.name for item in fields(SkillAsset) if item.init}
        if unknown or set(changes) & forbidden:
            raise ValueError(f"invalid revision fields: {sorted(unknown | (set(changes) & forbidden))}")
        definition = {item.name: copy.deepcopy(getattr(old, item.name))
                      for item in fields(SkillAsset) if item.init}
        definition.update(changes)
        definition["version"] = new_version
        revised = SkillAsset(**definition)
        if revised.asset_id in self.assets:
            raise ValueError("revision must use a new asset id")
        revised.parent_id = old.asset_id
        revised.lineage = (*old.lineage, old.asset_id)
        revised.revision = old.revision + 1
        revised.state_history[0]["reason"] = f"revision of {old.asset_id}; returned to dev"
        self.assets[revised.asset_id] = revised
        return revised

    def select(self, *, trigger: dict | None = None, dataset: str | None = None,
               domain: str | None = None, api: str | None = None,
               schema: str | None = None) -> list[SkillAsset]:
        selected = []
        for asset in self.assets.values():
            if asset.status != PROMOTED:
                continue
            if trigger is not None:
                if not isinstance(trigger, dict):
                    raise TypeError("trigger must be an object")
                if any(asset.trigger_signature.get(key) != value for key, value in trigger.items()):
                    continue
            scopes = ((dataset, asset.dataset_scope), (domain, asset.domain_scope),
                      (api, asset.api_scope), (schema, asset.schema_scope))
            if any(value is not None and value not in allowed for value, allowed in scopes):
                continue
            selected.append(asset)
        return sorted(selected, key=lambda asset: asset.asset_id)

    def activate(self, asset_id: str, *, task_id: str, trigger: dict | None = None,
                 dataset: str | None = None, domain: str | None = None,
                 api: str | None = None, schema: str | None = None,
                 context: dict | None = None, seed: int | None = None,
                 cost: dict[str, float] | None = None) -> dict:
        if self.read_only:
            raise RuntimeError("skill registry is read-only")
        asset = self._asset(asset_id)
        if asset.status != PROMOTED:
            raise ValueError("only promoted, non-retired assets can be activated")
        supplied = {"trigger": trigger, "dataset": dataset, "domain": domain,
                    "api": api, "schema": schema}
        if context is not None:
            if not isinstance(context, dict):
                raise ValueError("activation context must be an object")
            _canonical(context)
            for key in supplied:
                if key not in context:
                    continue
                if supplied[key] is not None and supplied[key] != context[key]:
                    raise ValueError(f"conflicting activation context field: {key}")
                supplied[key] = context[key]
        trigger = supplied["trigger"]
        dataset, domain, api, schema = (supplied[key] for key in ("dataset", "domain", "api", "schema"))
        scopes = (dataset, domain, api, schema)
        if (not isinstance(trigger, dict) or not trigger
                or any(not isinstance(value, str) or not value.strip() for value in scopes)):
            raise ValueError("complete trigger/dataset/domain/api/schema activation context is required")
        _canonical(trigger)
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("activation task_id must be nonempty")
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or seed < 0):
            raise ValueError("activation seed must be a nonnegative integer")
        eligible = self.select(trigger=trigger, dataset=dataset, domain=domain,
                               api=api, schema=schema)
        if asset_id not in {candidate.asset_id for candidate in eligible}:
            raise ValueError("activation trigger/scope does not match the skill asset")
        activation_cost = copy.deepcopy(asset.cost if cost is None else _cost(cost))
        record = {
            "activation_id": len(asset.activation_log) + 1,
            "task_id": task_id, "seed": seed,
            "trigger": copy.deepcopy(trigger), "dataset": dataset, "domain": domain,
            "api": api, "schema": schema, "cost": activation_cost, "at": _now(),
        }
        asset.activation_log.append(record)
        return copy.deepcopy(record)

    def freeze(self) -> None:
        self.frozen = True

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "frozen": self.frozen,
            "assets": [self.assets[key].to_dict() for key in sorted(self.assets)],
        }

    def save(self, path: str | Path) -> None:
        if self.read_only:
            raise RuntimeError("read-only registry cannot be saved")
        Path(path).write_text(_canonical(self.to_dict()) + "\n", encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict, *, read_only: bool = True) -> "SkillRegistry":
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported skill registry schema")
        serialized_assets = data.get("assets")
        if not isinstance(serialized_assets, list):
            raise ValueError("serialized registry assets must be an array")
        registry = cls(frozen=bool(data.get("frozen", False)), read_only=read_only)
        for serialized in serialized_assets:
            asset = SkillAsset.from_dict(serialized)
            if asset.asset_id in registry.assets:
                raise ValueError(f"duplicate skill asset: {asset.asset_id}")
            registry.assets[asset.asset_id] = asset
        for asset in registry.assets.values():
            if asset.parent_id is not None and asset.parent_id not in registry.assets:
                raise ValueError(f"missing parent asset: {asset.parent_id}")
        return registry

    @classmethod
    def load(cls, path: str | Path, *, read_only: bool = True) -> "SkillRegistry":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data, read_only=read_only)


def load_registry(path: str | Path, *, read_only: bool = True) -> SkillRegistry:
    return SkillRegistry.load(path, read_only=read_only)


__all__ = [
    "CANDIDATE", "DEV_PASSED", "PROMOTED", "REJECTED", "RETIRED",
    "SkillAsset", "SkillRegistry", "load_registry", "replay_paired_evidence",
]
