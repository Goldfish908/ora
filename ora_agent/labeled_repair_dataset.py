"""Hash-bound official labels with fail-closed train/val/test access controls."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

SCHEMA_VERSION = "labeled_repair_dataset.v1"
PROTOCOL_NAME = "official_label_train_val_test.v1"
TRAIN = "train"
VAL = "val"
TEST = "test"
SPLITS = (TRAIN, VAL, TEST)
PROPOSE = "propose"
PARETO = "pareto"
PROMOTE = "promote"
FINAL_EVALUATION = "final_evaluation"
EXPERIENCE = "experience"
SCORE_KEYS = ("true", "feasible", "quality", "objective")
VERIFIED = "VERIFIED"
UNKNOWN = "UNKNOWN"
BUSINESS_UNVERIFIED = "BUSINESS_UNVERIFIED"
PROTOCOL_PERMISSIONS = {
    TRAIN: [PROPOSE, EXPERIENCE, "gepa_trajectories"],
    VAL: [PARETO, PROMOTE],
    TEST: [FINAL_EVALUATION],
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MISSING = object()


class DatasetValidationError(ValueError):
    """The manifest, hashes, or official labels violate the dataset contract."""


class MissingLabelError(DatasetValidationError):
    """A verified official label is required but absent or unknown."""


class SplitAccessError(PermissionError):
    """A split was requested for a purpose forbidden by the protocol."""


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def _json_frozen(value: Any, label: str) -> Any:
    try:
        payload = json.dumps(_thaw(value), ensure_ascii=False, sort_keys=True, allow_nan=False)
        decoded = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise DatasetValidationError(f"{label} must be finite JSON data") from exc
    return _freeze(decoded)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_hash(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise DatasetValidationError(f"{label} must be a SHA256 hex digest")
    normalized = value.lower()
    if not _SHA256.fullmatch(normalized):
        raise DatasetValidationError(f"{label} must be a SHA256 hex digest")
    return normalized


def _path_content(path: Path) -> bytes | dict[str, bytes]:
    if path.is_file():
        return path.read_bytes()
    if path.is_dir():
        result = {}
        for item in sorted(path.rglob("*")):
            if item.is_file():
                result[item.relative_to(path).as_posix()] = item.read_bytes()
        if not result:
            raise DatasetValidationError(f"content directory is empty: {path}")
        return result
    raise DatasetValidationError(f"content path does not exist: {path}")


def _decode_content(value: Any, base_dir: Path | None = None) -> Any:
    if hasattr(value, "raw_bytes"):
        value = value.raw_bytes
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, Path):
        return _path_content(value)
    if not isinstance(value, Mapping):
        raise DatasetValidationError(
            "artifact, public data, and evaluator content must be bytes, text, paths, or file maps"
        )
    if "data_base64" in value:
        try:
            return base64.b64decode(value["data_base64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise DatasetValidationError("invalid base64 content") from exc
    if "path" in value:
        path = Path(value["path"])
        if not path.is_absolute() and base_dir is not None:
            path = base_dir / path
        return _path_content(path)
    entries = value.get("files", value)
    if not isinstance(entries, Mapping):
        raise DatasetValidationError("files must be a mapping")
    return {str(name): _decode_content(content, base_dir) for name, content in entries.items()}


def _content_digest(content: Any) -> str:
    if isinstance(content, Mapping):
        hashes = {str(name): _content_digest(value) for name, value in content.items()}
        raw = json.dumps(hashes, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return _sha256_bytes(raw)
    if not isinstance(content, bytes):
        raise DatasetValidationError("decoded content leaves must be bytes")
    return _sha256_bytes(content)


def _encode_content(content: Any) -> Any:
    if isinstance(content, Mapping):
        return {str(name): _encode_content(value) for name, value in content.items()}
    return {"data_base64": base64.b64encode(content).decode("ascii")}


def _bind_content(value: Any, expected: str | None, label: str, base_dir: Path | None = None) -> tuple[Any, str]:
    declared = expected
    if declared is None and hasattr(value, "sha256"):
        declared = value.sha256
    content = _decode_content(value, base_dir)
    actual = _content_digest(content)
    if declared is None:
        declared = actual
    declared = _valid_hash(declared, f"{label} SHA256")
    if actual != declared:
        raise DatasetValidationError(f"{label} SHA256 does not match its content")
    return content, declared


def _finite_number(value: Any, label: str, *, optional: bool = False) -> float | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DatasetValidationError(f"{label} must be a finite number")
    return float(value)


def _optional_bool(value: Any, label: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise DatasetValidationError(f"{label} must be boolean or null")
    return value


def _raw_official_unknown(value: Mapping[str, Any]) -> bool:
    runner = value.get("runner")
    evaluation = value.get("evaluation")
    reward = value.get("reward")
    if not isinstance(runner, Mapping) or runner.get("return_code") != 0 or runner.get("timed_out"):
        return True
    if not isinstance(evaluation, Mapping) or not isinstance(reward, Mapping):
        return True
    errors = evaluation.get("errors") or []
    if not isinstance(errors, list):
        return True
    if any("official evaluator did not produce" in str(error) for error in errors):
        return True
    feasibility = reward.get("feasibility")
    quality = reward.get("quality")
    try:
        feasibility_number = _finite_number(feasibility, "official feasibility")
        quality_number = _finite_number(quality, "official quality")
    except DatasetValidationError:
        return True
    if feasibility_number not in {0.0, 1.0} or quality_number < 0:
        return True
    if "feasible" in evaluation and (
        not isinstance(evaluation["feasible"], bool)
        or evaluation["feasible"] != (feasibility_number == 1.0)
    ):
        return True
    if feasibility_number == 1.0 and errors:
        return True
    for key in ("objective", "profit", "score", "total_cost"):
        if key in evaluation and evaluation[key] is not None:
            try:
                _finite_number(evaluation[key], f"official {key}")
            except DatasetValidationError:
                return True
    details = value.get("reward_details") or {}
    if not isinstance(details, Mapping):
        return True
    return any(key in details and details[key] != reward[key] for key in ("feasibility", "quality"))


def _business_unverified(value: Mapping[str, Any]) -> bool:
    if value.get("business_unverified") is True:
        return True
    nested = value.get("business")
    nested = nested if isinstance(nested, Mapping) else {}
    evaluation = value.get("evaluation")
    evaluation = evaluation if isinstance(evaluation, Mapping) else {}
    statuses = (
        value.get("label_status"), value.get("audit_status"), value.get("business_status"),
        nested.get("audit_status"), nested.get("status"), evaluation.get("audit_status"),
    )
    return any(str(status).strip().upper() in {BUSINESS_UNVERIFIED, "UNVERIFIED"} for status in statuses)


@dataclass(frozen=True)
class OfficialLabel:
    """Official values; unknown and business-unverified truth are always null."""

    true: bool | None
    feasible: bool | None
    quality: float | None
    objective: float | None
    label_status: str = VERIFIED
    errors: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        if self.label_status not in {VERIFIED, UNKNOWN, BUSINESS_UNVERIFIED}:
            raise DatasetValidationError("unsupported official label status")
        if self.label_status == UNKNOWN:
            object.__setattr__(self, "true", None)
            object.__setattr__(self, "feasible", None)
            object.__setattr__(self, "quality", None)
            object.__setattr__(self, "objective", None)
        elif self.label_status == BUSINESS_UNVERIFIED:
            if self.true is True:
                raise DatasetValidationError("business-unverified evaluation cannot claim an official true label")
            object.__setattr__(self, "true", None)
        true = _optional_bool(self.true, "official true")
        feasible = _optional_bool(self.feasible, "official feasible")
        quality = _finite_number(self.quality, "official quality", optional=True)
        objective = _finite_number(self.objective, "official objective", optional=True)
        if self.label_status == VERIFIED and (true is None or feasible is None or quality is None):
            raise MissingLabelError("verified official true, feasible, and quality labels are required")
        if quality is not None and quality < 0:
            raise DatasetValidationError("official quality must be nonnegative")
        object.__setattr__(self, "true", true)
        object.__setattr__(self, "feasible", feasible)
        object.__setattr__(self, "quality", quality)
        object.__setattr__(self, "objective", objective)
        object.__setattr__(self, "errors", _json_frozen(tuple(self.errors), "official errors"))

    @property
    def is_verified(self) -> bool:
        return self.label_status == VERIFIED

    @classmethod
    def from_value(cls, value: Any) -> "OfficialLabel":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping) or not value:
            raise MissingLabelError("each sample requires an official label object")
        if any(key in value for key in ("evaluation", "reward", "runner")):
            evaluation = value.get("evaluation") if isinstance(value.get("evaluation"), Mapping) else {}
            errors = tuple(evaluation.get("errors") or ())
            if _raw_official_unknown(value):
                return cls(None, None, None, None, UNKNOWN, errors)
            reward = value["reward"]
            feasible = float(reward["feasibility"]) == 1.0
            quality = float(reward["quality"])
            true = feasible and quality > 0.4
            objective = next(
                (float(evaluation[key]) for key in ("objective", "profit", "score", "total_cost")
                 if key in evaluation and evaluation[key] is not None),
                None,
            )
            if _business_unverified(value):
                return cls(None, feasible, quality, objective, BUSINESS_UNVERIFIED, errors)
            return cls(true, feasible, quality, objective, VERIFIED, errors)

        raw_status = str(value.get("label_status", value.get("status", ""))).strip().upper()
        unknown = (
            value.get("evaluation_unknown") is True or value.get("unknown") is True
            or raw_status in {UNKNOWN, "EVALUATION_UNKNOWN"}
        )
        errors = tuple(value.get("errors") or value.get("official_errors") or ())
        if unknown:
            return cls(None, None, None, None, UNKNOWN, errors)
        true = value.get("true", value.get("true_correct"))
        feasible = value.get("feasible")
        quality = value.get("quality")
        objective = value.get("objective")
        if _business_unverified(value):
            if true is True:
                raise DatasetValidationError("business-unverified evaluation cannot claim an official true label")
            return cls(
                None,
                _optional_bool(feasible, "official feasible"),
                _finite_number(quality, "official quality", optional=True),
                _finite_number(objective, "official objective", optional=True),
                BUSINESS_UNVERIFIED,
                errors,
            )
        if not isinstance(true, bool) or not isinstance(feasible, bool) or quality is None:
            raise MissingLabelError("verified official true, feasible, and quality labels are required")
        quality_number = _finite_number(quality, "official quality")
        if quality_number < 0:
            raise DatasetValidationError("official quality must be nonnegative")
        return cls(
            true,
            feasible,
            quality_number,
            _finite_number(objective, "official objective", optional=True),
            VERIFIED,
            errors,
        )

    def require_verified(self) -> None:
        if not self.is_verified:
            raise MissingLabelError(f"{self.label_status} official evaluation cannot be used as truth")

    def scores(self, keys: Sequence[str], objective_sense: str) -> dict[str, float]:
        self.require_verified()
        result = {}
        for key in keys:
            if key == "objective":
                if self.objective is None:
                    raise MissingLabelError("an objective score requires a known official objective")
                result[key] = self.objective if objective_sense == "max" else -self.objective
            else:
                value = getattr(self, key)
                if value is None:
                    raise MissingLabelError(f"official {key} label is unavailable")
                result[key] = float(value)
        return result

    def to_dict(self, *, include_errors: bool = True) -> dict[str, Any]:
        result = {
            "true": self.true,
            "feasible": self.feasible,
            "quality": self.quality,
            "objective": self.objective,
            "label_status": self.label_status,
        }
        if include_errors:
            result["errors"] = _thaw(self.errors)
        return result


@dataclass(frozen=True)
class LabeledRepairSample:
    """One hash-bound root and its official evaluation, stored without write APIs."""

    problem_id: str
    split: str
    root_artifact: Any
    public_data: Any
    evaluator: Any
    official: OfficialLabel | Mapping[str, Any]
    feedback: str = ""
    counterexamples: Any = ()
    near_boundary: Any = ()
    source: Mapping[str, Any] = field(default_factory=dict)
    root_sha256: str | None = None
    public_data_sha256: str | None = None
    evaluator_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.problem_id, str) or not self.problem_id.strip():
            raise DatasetValidationError("problem_id must be nonempty")
        if self.split not in SPLITS:
            raise DatasetValidationError("split must be exactly train, val, or test")
        if not isinstance(self.feedback, str):
            raise DatasetValidationError("feedback must be text")
        if not isinstance(self.source, Mapping) or not self.source:
            raise DatasetValidationError("source provenance must be a nonempty object")
        root, root_hash = _bind_content(self.root_artifact, self.root_sha256, "root artifact")
        if not isinstance(root, bytes):
            raise DatasetValidationError("root artifact must be one byte string, not a file map")
        public, public_hash = _bind_content(self.public_data, self.public_data_sha256, "public data")
        evaluator, evaluator_hash = _bind_content(self.evaluator, self.evaluator_sha256, "evaluator")
        object.__setattr__(self, "problem_id", self.problem_id.strip())
        object.__setattr__(self, "root_artifact", root)
        object.__setattr__(self, "root_sha256", root_hash)
        object.__setattr__(self, "public_data", _freeze(public))
        object.__setattr__(self, "public_data_sha256", public_hash)
        object.__setattr__(self, "evaluator", _freeze(evaluator))
        object.__setattr__(self, "evaluator_sha256", evaluator_hash)
        object.__setattr__(self, "official", OfficialLabel.from_value(self.official))
        object.__setattr__(self, "counterexamples", _json_frozen(self.counterexamples, "counterexamples"))
        object.__setattr__(self, "near_boundary", _json_frozen(self.near_boundary, "near_boundary"))
        object.__setattr__(self, "source", _json_frozen(self.source, "source provenance"))
        for key, actual in (("root_sha256", root_hash), ("evaluator_sha256", evaluator_hash)):
            declared = self.source.get(key)
            if declared is not None and str(declared).lower() != actual:
                raise DatasetValidationError(f"source provenance {key} disagrees with the sample")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, base_dir: str | Path | None = None) -> "LabeledRepairSample":
        if not isinstance(value, Mapping):
            raise DatasetValidationError("manifest samples must be objects")
        for key in (
            "problem_id", "split", "root_artifact", "root_sha256", "public_data", "public_data_sha256",
            "evaluator", "evaluator_sha256", "official", "feedback", "counterexamples", "near_boundary", "source",
        ):
            if key not in value:
                raise DatasetValidationError(f"manifest sample is missing {key}")
        return cls(
            problem_id=value["problem_id"], split=value["split"],
            root_artifact=_decode_content(value["root_artifact"], Path(base_dir) if base_dir else None),
            root_sha256=value["root_sha256"],
            public_data=_decode_content(value["public_data"], Path(base_dir) if base_dir else None),
            public_data_sha256=value["public_data_sha256"],
            evaluator=_decode_content(value["evaluator"], Path(base_dir) if base_dir else None),
            evaluator_sha256=value["evaluator_sha256"],
            official=value["official"], feedback=value["feedback"],
            counterexamples=value["counterexamples"], near_boundary=value["near_boundary"], source=value["source"],
        )

    def verify_hashes(self) -> None:
        for content, expected, label in (
            (self.root_artifact, self.root_sha256, "root artifact"),
            (self.public_data, self.public_data_sha256, "public data"),
            (self.evaluator, self.evaluator_sha256, "evaluator"),
        ):
            if _content_digest(content) != expected:
                raise DatasetValidationError(f"{label} SHA256 does not match its content")

    def to_dict(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "split": self.split,
            "root_artifact": _encode_content(self.root_artifact),
            "root_sha256": self.root_sha256,
            "public_data": {"files": _encode_content(self.public_data)} if isinstance(self.public_data, Mapping)
                else _encode_content(self.public_data),
            "public_data_sha256": self.public_data_sha256,
            "evaluator": {"files": _encode_content(self.evaluator)} if isinstance(self.evaluator, Mapping)
                else _encode_content(self.evaluator),
            "evaluator_sha256": self.evaluator_sha256,
            "official": self.official.to_dict(),
            "feedback": self.feedback,
            "counterexamples": _thaw(self.counterexamples),
            "near_boundary": _thaw(self.near_boundary),
            "source": _thaw(self.source),
        }


def _evaluation_batch_class() -> type:
    if sys.version_info < (3, 10):
        raise ImportError("GEPA evaluation batches require Python >=3.10")
    try:
        from gepa.core.adapter import EvaluationBatch
        return EvaluationBatch
    except ModuleNotFoundError as exc:
        if exc.name != "gepa":
            raise
    source = Path(os.environ.get("GEPA_SRC", str(Path(__file__).resolve().parents[2] / "ext" / "gepa" / "src")))
    if not (source / "gepa" / "core" / "adapter.py").is_file():
        raise ImportError("GEPA source is required; set GEPA_SRC to the checkout's src directory")
    sys.path.insert(0, str(source.resolve()))
    from gepa.core.adapter import EvaluationBatch
    return EvaluationBatch


class LabeledRepairDataset:
    """Read-only split views, offline GEPA conversion, and access auditing."""

    def __init__(
        self,
        samples: Iterable[LabeledRepairSample | Mapping[str, Any]],
        *,
        val_score_keys: Sequence[str] = ("quality",),
        objective_sense: str = "max",
        base_dir: str | Path | None = None,
    ) -> None:
        if isinstance(val_score_keys, str) or not val_score_keys:
            raise DatasetValidationError("val_score_keys must be a nonempty sequence")
        if len(set(val_score_keys)) != len(val_score_keys) or any(key not in SCORE_KEYS for key in val_score_keys):
            raise DatasetValidationError(f"val_score_keys must be unique values from {SCORE_KEYS}")
        sense_aliases = {"max": "max", "maximize": "max", "min": "min", "minimize": "min"}
        if objective_sense not in sense_aliases:
            raise DatasetValidationError("objective_sense must be max or min")
        self.val_score_keys = tuple(val_score_keys)
        self.objective_sense = sense_aliases[objective_sense]
        materialized = tuple(
            sample if isinstance(sample, LabeledRepairSample) else LabeledRepairSample.from_dict(
                sample, base_dir=base_dir,
            )
            for sample in samples
        )
        by_id = {}
        roots = {}
        for sample in materialized:
            if sample.problem_id in by_id:
                other = by_id[sample.problem_id]
                if other.split != sample.split:
                    raise DatasetValidationError(f"problem_id appears in overlapping splits: {sample.problem_id}")
                raise DatasetValidationError(f"duplicate problem_id: {sample.problem_id}")
            by_id[sample.problem_id] = sample
            previous_split = roots.setdefault(sample.root_sha256, sample.split)
            if previous_split != sample.split:
                raise DatasetValidationError(f"root artifact is reused across splits: {sample.root_sha256}")
            sample.verify_hashes()
        self._samples = materialized
        self._by_id = by_id
        self._audit: list[dict[str, Any]] = []
        missing = [split for split in SPLITS if not any(sample.split == split for sample in materialized)]
        if missing:
            raise DatasetValidationError(f"train/val/test protocol requires nonempty splits; missing {missing}")

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any] | str | Path) -> "LabeledRepairDataset":
        base_dir = None
        if isinstance(manifest, (str, Path)):
            path = Path(manifest)
            base_dir = path.resolve().parent
            manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, Mapping) or manifest.get("schema_version") != SCHEMA_VERSION:
            raise DatasetValidationError("unsupported labeled repair manifest schema")
        protocol = manifest.get("protocol")
        if not isinstance(protocol, Mapping) or protocol.get("name") != PROTOCOL_NAME:
            raise DatasetValidationError("unsupported train/val/test protocol")
        if protocol.get("permissions") != PROTOCOL_PERMISSIONS:
            raise DatasetValidationError("manifest split permissions do not match the protocol")
        samples = manifest.get("samples")
        if not isinstance(samples, list):
            raise DatasetValidationError("manifest samples must be a list")
        return cls(
            samples,
            val_score_keys=protocol.get("val_score_keys", ()),
            objective_sense=protocol.get("objective_sense", "max"),
            base_dir=base_dir,
        )

    def to_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "protocol": {
                "name": PROTOCOL_NAME,
                "permissions": _thaw(PROTOCOL_PERMISSIONS),
                "val_score_keys": list(self.val_score_keys),
                "objective_sense": self.objective_sense,
                "score_semantics": "higher is better; scalar GEPA score is the mean of val_score_keys",
            },
            "samples": [sample.to_dict() for sample in self._samples],
        }

    @property
    def manifest(self) -> dict[str, Any]:
        return self.to_manifest()

    def verify_hashes(self) -> None:
        for sample in self._samples:
            sample.verify_hashes()

    def _record(
        self,
        action: str,
        split: str | None,
        problem_ids: Iterable[str],
        allowed: bool,
        *,
        purpose: str,
        fields: Iterable[str] = (),
        reason: str | None = None,
    ) -> None:
        self._audit.append({
            "event_index": len(self._audit),
            "action": action,
            "split": split,
            "problem_ids": tuple(problem_ids),
            "purpose": purpose,
            "allowed": allowed,
            "fields": tuple(sorted(fields)),
            "reason": reason,
        })

    def access_audit(self, split: str | None = None) -> tuple[dict[str, Any], ...]:
        if split is not None and split not in SPLITS:
            raise ValueError("split must be train, val, or test")
        return tuple(_thaw(event) for event in self._audit if split is None or event["split"] == split)

    def _sample(self, problem_id: str) -> LabeledRepairSample:
        try:
            return self._by_id[problem_id]
        except KeyError as exc:
            raise KeyError(f"unknown problem_id: {problem_id}") from exc

    def _scores_view(self, sample: LabeledRepairSample) -> dict[str, Any]:
        return {
            "problem_id": sample.problem_id,
            "split": sample.split,
            "root_sha256": sample.root_sha256,
            "public_data_sha256": sample.public_data_sha256,
            "evaluator_sha256": sample.evaluator_sha256,
            "scores": sample.official.scores(self.val_score_keys, self.objective_sense),
        }

    def _train_view(self, sample: LabeledRepairSample) -> dict[str, Any]:
        sample.official.require_verified()
        return {
            "problem_id": sample.problem_id,
            "split": sample.split,
            "root_artifact": _encode_content(sample.root_artifact),
            "root_sha256": sample.root_sha256,
            "public_data": _encode_content(sample.public_data),
            "public_data_sha256": sample.public_data_sha256,
            "evaluator_sha256": sample.evaluator_sha256,
            "official": sample.official.to_dict(),
            "feedback": sample.feedback,
            "counterexamples": _thaw(sample.counterexamples),
            "near_boundary": _thaw(sample.near_boundary),
            "source": _thaw(sample.source),
        }

    def _test_view(self, sample: LabeledRepairSample) -> dict[str, Any]:
        sample.official.require_verified()
        return {
            "problem_id": sample.problem_id,
            "split": sample.split,
            "root_artifact": _encode_content(sample.root_artifact),
            "root_sha256": sample.root_sha256,
            "public_data": _encode_content(sample.public_data),
            "public_data_sha256": sample.public_data_sha256,
            "evaluator_sha256": sample.evaluator_sha256,
            "official": sample.official.to_dict(include_errors=False),
            "counterexamples": _thaw(sample.counterexamples),
            "near_boundary": _thaw(sample.near_boundary),
            "source": _thaw(sample.source),
        }

    def _view(self, sample: LabeledRepairSample, purpose: str, action: str) -> Any:
        try:
            if purpose in {PROPOSE, EXPERIENCE}:
                if sample.split != TRAIN:
                    raise SplitAccessError(f"{sample.split} cannot enter {purpose}")
                result = self._train_view(sample)
            elif purpose in {PARETO, PROMOTE}:
                if sample.split != VAL:
                    raise SplitAccessError(f"{sample.split} cannot enter {purpose}; val evidence is required")
                result = self._scores_view(sample)
            elif purpose == FINAL_EVALUATION:
                if sample.split != TEST:
                    raise SplitAccessError("final test evaluation view is only for test samples")
                result = self._test_view(sample)
            else:
                raise ValueError(f"unsupported access purpose: {purpose}")
        except (SplitAccessError, MissingLabelError) as exc:
            self._record(action, sample.split, (sample.problem_id,), False, purpose=purpose, reason=str(exc))
            raise
        frozen = _freeze(result)
        self._record(
            action, sample.split, (sample.problem_id,), True, purpose=purpose, fields=result.keys(),
        )
        return frozen

    def view(self, problem_id: str, *, purpose: str) -> Any:
        """Return a recursively read-only view allowed for exactly one purpose."""
        return self._view(self._sample(problem_id), purpose, "read")

    def propose(self, problem_id: str, proposer: Callable[[Mapping[str, Any]], Any]) -> Any:
        """Invoke a proposer with a train-only, verified-label reflection view."""
        if not callable(proposer):
            raise TypeError("proposer must be callable")
        return proposer(self._view(self._sample(problem_id), PROPOSE, PROPOSE))

    def gepa_evaluation_batch(self, split: str, *, capture_traces: bool = False) -> Any:
        """Convert offline official labels to a real GEPA EvaluationBatch.

        Train may include full reflection trajectories. Val emits only protocol scores and
        never trajectories. Test is marked/audited as final evaluation and never trajectories.
        No official evaluator is called, so num_metric_calls is zero.
        """
        if split not in SPLITS:
            raise ValueError("split must be train, val, or test")
        samples = tuple(sample for sample in self._samples if sample.split == split)
        purpose = PROPOSE if split == TRAIN else PARETO if split == VAL else FINAL_EVALUATION
        ids = tuple(sample.problem_id for sample in samples)
        try:
            if capture_traces and split != TRAIN:
                raise SplitAccessError(f"{split} detailed feedback cannot enter GEPA trajectories")
            if split == TRAIN:
                rows = [self._train_view(sample) for sample in samples]
                outputs = [
                    {key: row[key] for key in ("problem_id", "split", "root_sha256")}
                    | {"scores": sample.official.scores(self.val_score_keys, self.objective_sense)}
                    for sample, row in zip(samples, rows)
                ]
            else:
                rows = [self._scores_view(sample) for sample in samples]
                outputs = rows
            objective_scores = [dict(row["scores"]) for row in outputs]
            scores = [sum(row.values()) / len(row) for row in objective_scores]
            trajectories = rows if capture_traces else None
        except (SplitAccessError, MissingLabelError) as exc:
            self._record("gepa_evaluation_batch", split, ids, False, purpose=purpose, reason=str(exc))
            raise
        batch = _evaluation_batch_class()(
            outputs=_thaw(outputs),
            scores=scores,
            trajectories=_thaw(trajectories) if trajectories is not None else None,
            objective_scores=_thaw(objective_scores),
            num_metric_calls=0,
        )
        self._record(
            "gepa_evaluation_batch", split, ids, True, purpose=purpose,
            fields=("outputs", "scores", "objective_scores") + (("trajectories",) if capture_traces else ()),
        )
        return batch

    def promote(
        self,
        candidate_id: str,
        evidence: Iterable[Mapping[str, Any]] | Mapping[str, Mapping[str, float]],
        promoter: Callable[[Mapping[str, Any]], Any] | None = None,
    ) -> Any:
        """Guard promotion with val-only numeric evidence; no feedback fields are accepted."""
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ValueError("candidate_id must be nonempty")
        if isinstance(evidence, Mapping):
            rows = [{"problem_id": problem_id, "scores": scores} for problem_id, scores in evidence.items()]
        elif not isinstance(evidence, (str, bytes)):
            rows = list(evidence)
        else:
            rows = []
        ids = tuple(str(row.get("problem_id")) for row in rows if isinstance(row, Mapping))
        encountered_splits = []
        try:
            if not rows:
                raise SplitAccessError("promotion requires nonempty val evidence")
            sanitized = []
            seen = set()
            for row in rows:
                if not isinstance(row, Mapping) or set(row) != {"problem_id", "scores"}:
                    raise SplitAccessError("promotion evidence may contain only problem_id and scores")
                problem_id = row["problem_id"]
                sample = self._sample(problem_id)
                encountered_splits.append(sample.split)
                if sample.split != VAL:
                    raise SplitAccessError(f"{sample.split} cannot enter promotion")
                if problem_id in seen:
                    raise SplitAccessError("promotion evidence contains duplicate val problem_ids")
                seen.add(problem_id)
                sample.official.require_verified()
                supplied = row["scores"]
                if not isinstance(supplied, Mapping) or set(supplied) != set(self.val_score_keys):
                    raise SplitAccessError("promotion scores must exactly match the val score protocol")
                scores = {
                    key: _finite_number(supplied[key], f"promotion score {key}")
                    for key in self.val_score_keys
                }
                sanitized.append({
                    "problem_id": problem_id,
                    "split": VAL,
                    "root_sha256": sample.root_sha256,
                    "evaluator_sha256": sample.evaluator_sha256,
                    "scores": scores,
                })
        except (KeyError, SplitAccessError, MissingLabelError, DatasetValidationError) as exc:
            denied_split = next((split for split in encountered_splits if split != VAL), None)
            if denied_split is None and encountered_splits:
                denied_split = VAL
            self._record(PROMOTE, denied_split, ids, False, purpose=PROMOTE, reason=str(exc))
            if isinstance(exc, (KeyError, DatasetValidationError)) and not isinstance(exc, MissingLabelError):
                raise SplitAccessError(str(exc)) from exc
            raise
        receipt = _freeze({
            "candidate_id": candidate_id.strip(),
            "evidence_split": VAL,
            "evidence": sanitized,
            "read_only": True,
        })
        self._record(PROMOTE, VAL, ids, True, purpose=PROMOTE, fields=("problem_id", "scores"))
        return promoter(receipt) if promoter is not None else receipt

    def _validate_experience_origin(self, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if key in {"split", "origin_split", "source_split"} and item != TRAIN:
                    raise SplitAccessError("only train provenance can be written to experience")
                if key in {"problem_id", "origin_problem_id", "source_problem_id"} and isinstance(item, str):
                    sample = self._sample(item)
                    if sample.split != TRAIN:
                        raise SplitAccessError(f"{sample.split} cannot be written back to experience")
                self._validate_experience_origin(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._validate_experience_origin(item)

    def write_experience(
        self,
        problem_id: str,
        experience: Mapping[str, Any],
        sink: Callable[[Mapping[str, Any]], Any] | None = None,
    ) -> Any:
        """Build and optionally emit a train-only experience record; test/val are denied before sink."""
        sample = self._sample(problem_id)
        try:
            if sample.split != TRAIN:
                raise SplitAccessError(f"{sample.split} cannot be written back to experience")
            sample.official.require_verified()
            if not isinstance(experience, Mapping) or not experience:
                raise SplitAccessError("experience must be a nonempty object")
            self._validate_experience_origin(experience)
            record = {
                "problem_id": problem_id,
                "split": TRAIN,
                "root_sha256": sample.root_sha256,
                "source": _thaw(sample.source),
                "experience": _json_frozen(experience, "experience"),
            }
        except (SplitAccessError, MissingLabelError) as exc:
            self._record(EXPERIENCE, sample.split, (problem_id,), False, purpose=EXPERIENCE, reason=str(exc))
            raise
        frozen = _freeze(record)
        self._record(
            EXPERIENCE, TRAIN, (problem_id,), True, purpose=EXPERIENCE,
            fields=("problem_id", "split", "root_sha256", "source", "experience"),
        )
        if sink is not None:
            sink(_thaw(frozen))
        return frozen
