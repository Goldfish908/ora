#!/usr/bin/env python3
"""Convert ORA DPO repair pairs to candidate-level Open-Jev import records.

Only the Python standard library is used. Exact duplicate pairs are removed.
Conflicting candidate labels are rejected or dropped as complete pairs, while
scenario/context leakage is always an error. Original dev data is historical
development data mapped to test, not a newly held-out evaluation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "work" / "sft_data" / "dpo.jsonl"
DEFAULT_OUTPUT = ROOT / "work" / "jev_repair_data_v0.1"
SOURCE_URL = "local:///work/sft_data/dpo.jsonl"
LICENSE_NAME = "unspecified"
DATASET_VERSION = "ora-jev-repair-v0.1"
QUESTION = (
    "Was this candidate the preferred code in the independent execution-based "
    "pairwise repair evaluation?"
)
KIND = "noul"
OPTIONS = ["no", "yes"]
CHOSEN_TARGET = (0.0, 1.0)
REJECTED_TARGET = (1.0, 0.0)
TARGET_BASIS = "independent_execution_pairwise_preference"
SPLIT_POLICY = "ora_dpo_dev_test_wrong_constant_scenario_ood_group_sha256_80_20_v1"
MODEL_INPUT_FIELDS = ["state", "question", "kind", "options"]
SPLITS = ("train", "calibration", "test", "ood")
INPUT_FIELDS = {
    "scenario_id", "mutant", "prompt", "chosen", "rejected", "source", "split",
}
OUTPUT_FIELDS = {
    "id", "group_id", "split", "source", "state", "question", "kind",
    "options", "target", "metadata",
}
DATA_LIMITATIONS = [
    "Original dev pairs were used in historical development and are mapped to test; test is not a new held-out set.",
    "Targets encode relative preferences from previously independently executed pairs, not absolute correctness or calibrated correctness probabilities; this conversion does not re-execute candidates.",
    "Every original-train scenario containing a wrong_constant pair is assigned wholesale to OOD, so training sees neither that error family nor those scenarios.",
    "OOD also contains other error families from wrong_constant scenarios; it is a scenario-coherent error-family holdout from original train, not sealed or frozen evaluation data.",
    "Scenario-level OOD removal, whole-pair duplicate consolidation and conflict rejection leave a small train/calibration pool; the hash rule targets 80/20 scenarios rather than forcing exact pair proportions.",
    "The input has no declared license; provenance license is unspecified and no redistribution license is asserted.",
    "No sealed/frozen data, LLM, external API, or Open-Jev runtime dependency is used by this converter.",
]


class DataPreparationError(ValueError):
    """Base error for invalid or unsafe input."""


class DataConflictError(DataPreparationError):
    """Raised when candidate labels or residual duplicate inputs conflict."""


class DataLeakageError(DataPreparationError):
    """Raised when scenario groups or prompt contexts leak."""


@dataclass(frozen=True)
class NumberedPair:
    line_number: int
    value: dict


@dataclass(frozen=True)
class PreparedData:
    records: list[dict]
    report: dict


@dataclass(frozen=True)
class _Candidate:
    pair: NumberedPair
    split: str
    role: str
    state: dict
    target: tuple[float, float]
    fingerprint: str


def _canonical(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def _hash(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def scenario_bucket(scenario_id: str, seed: int = 42) -> int:
    payload = _canonical([seed, scenario_id]).encode("utf-8")
    return int(hashlib.sha256(payload).hexdigest()[:16], 16) % 10000


def remaining_train_split(scenario_id: str, seed: int = 42) -> str:
    return "train" if scenario_bucket(scenario_id, seed) < 8000 else "calibration"


def read_input_pairs(path: str | Path) -> tuple[list[NumberedPair], str]:
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    pairs = []
    for line_number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DataPreparationError(
                f"{path}:{line_number}: invalid JSON: {exc.msg}"
            ) from exc
        pairs.append(NumberedPair(line_number, value))
    return pairs, digest


def _validate_input(pair: NumberedPair) -> None:
    value = pair.value
    prefix = f"input line {pair.line_number}: "
    if not isinstance(value, dict) or set(value) != INPUT_FIELDS:
        raise DataPreparationError(
            prefix + f"expected exactly {sorted(INPUT_FIELDS)}"
        )
    for field in INPUT_FIELDS:
        if not isinstance(value[field], str) or not value[field].strip():
            raise DataPreparationError(prefix + f"{field} must be nonempty text")
    if value["split"] not in ("train", "dev"):
        raise DataPreparationError(prefix + "split must be train or dev")


def _sanitize(text: str, scenario_ids: set[str], sources: set[str]) -> str:
    result = re.sub(
        r"(?im)^[ \t]*Scenario ID[ \t]*:[^\n]*(?:\n|$)", "", text,
    )
    for scenario_id in sorted(scenario_ids, key=lambda x: (-len(x), x)):
        result = result.replace(scenario_id, "redacted_scenario")
    for source in sorted(sources, key=lambda x: (-len(x), x)):
        result = result.replace(source, "redacted_source")
    return result


def _candidate_state(
    raw: dict, role: str, scenario_ids: set[str], sources: set[str],
) -> dict:
    return {
        "prompt": _sanitize(raw["prompt"], scenario_ids, sources),
        "candidate_code": _sanitize(raw[role], scenario_ids, sources),
    }


def _fingerprint(state: dict) -> str:
    return _hash({
        "state": state,
        "question": " ".join(QUESTION.split()),
        "kind": KIND,
        "options": sorted(OPTIONS),
    })


def _expand_pair(
    pair: NumberedPair, split: str, scenario_ids: set[str], sources: set[str],
) -> list[_Candidate]:
    return [
        _Candidate(
            pair=pair,
            split=split,
            role=role,
            state=_candidate_state(pair.value, role, scenario_ids, sources),
            target=target,
            fingerprint="",
        )
        for role, target in (("chosen", CHOSEN_TARGET), ("rejected", REJECTED_TARGET))
    ]


def _with_fingerprint(candidate: _Candidate) -> _Candidate:
    return _Candidate(
        pair=candidate.pair,
        split=candidate.split,
        role=candidate.role,
        state=candidate.state,
        target=candidate.target,
        fingerprint=_fingerprint(candidate.state),
    )


def _assign_splits(
    pairs: list[NumberedPair], seed: int,
) -> tuple[dict[str, str], dict]:
    original_splits = defaultdict(set)
    for pair in pairs:
        original_splits[pair.value["scenario_id"]].add(pair.value["split"])
    bad_groups = sorted(
        group for group, values in original_splits.items() if len(values) != 1
    )
    if bad_groups:
        raise DataLeakageError(
            f"{len(bad_groups)} scenario_ids have conflicting original splits: "
            + ", ".join(bad_groups)
        )

    dev_scenarios = sorted(
        group for group, values in original_splits.items() if values == {"dev"}
    )
    wrong_constant_scenarios = sorted({
        pair.value["scenario_id"]
        for pair in pairs
        if pair.value["split"] == "train"
        and pair.value["mutant"] == "wrong_constant"
    })
    wrong_constant_set = set(wrong_constant_scenarios)
    assignment = {}
    for group, values in original_splits.items():
        if values == {"dev"}:
            assignment[group] = "test"
        elif group in wrong_constant_set:
            assignment[group] = "ood"
        else:
            assignment[group] = remaining_train_split(group, seed)
    details = {
        "policy": SPLIT_POLICY,
        "seed": seed,
        "hash": "sha256(canonical_json([seed, scenario_id]))[:16] interpreted as integer, modulo 10000",
        "train_threshold": 8000,
        "original_dev_scenarios": len(dev_scenarios),
        "wrong_constant_scenarios": len(wrong_constant_scenarios),
        "remaining_original_train_scenarios": (
            len(original_splits) - len(dev_scenarios) - len(wrong_constant_scenarios)
        ),
        "scenario_buckets": {
            group: scenario_bucket(group, seed)
            for group in sorted(original_splits)
            if group not in wrong_constant_set and original_splits[group] != {"dev"}
        },
    }
    return assignment, details


def _deduplicate(pairs: list[NumberedPair]) -> tuple[list[NumberedPair], dict]:
    first_by_value = {}
    unique = []
    duplicate_groups = []
    for pair in pairs:
        key = _canonical(pair.value)
        if key not in first_by_value:
            first_by_value[key] = pair
            unique.append(pair)
        else:
            kept = first_by_value[key]
            duplicate_groups.append({
                "kept_input_line": kept.line_number,
                "duplicate_input_line": pair.line_number,
                "scenario_id": pair.value["scenario_id"],
                "mutant": pair.value["mutant"],
            })
    report = {
        "definition": "byte-equivalent canonical JSON of the complete seven-field input pair; keep the first occurrence",
        "removed_pairs": len(duplicate_groups),
        "removed_candidate_records": 2 * len(duplicate_groups),
        "duplicates": duplicate_groups,
    }
    return unique, report


def _drop_label_conflicts(
    candidates: list[_Candidate], policy: str,
) -> tuple[list[_Candidate], dict]:
    by_input = defaultdict(list)
    for candidate in candidates:
        by_input[candidate.fingerprint].append(candidate)
    conflicts = []
    dropped_lines = set()
    for fingerprint, occurrences in sorted(by_input.items()):
        if len({item.target for item in occurrences}) < 2:
            continue
        dropped_lines.update(item.pair.line_number for item in occurrences)
        conflicts.append({
            "input_fingerprint": fingerprint,
            "occurrences": [
                {
                    "input_line": item.pair.line_number,
                    "scenario_id": item.pair.value["scenario_id"],
                    "split": item.split,
                    "candidate_role": item.role,
                    "target": list(item.target),
                }
                for item in sorted(occurrences, key=lambda x: (x.pair.line_number, x.role))
            ],
        })
    if conflicts and policy == "error":
        raise DataConflictError(
            f"{len(conflicts)} identical candidate inputs have conflicting labels; "
            f"{len(dropped_lines)} complete pairs are implicated"
        )
    kept = [
        candidate for candidate in candidates
        if candidate.pair.line_number not in dropped_lines
    ]
    report = {
        "policy": policy,
        "definition": "same sanitized state/question/kind/options with different target labels",
        "conflicting_inputs": len(conflicts),
        "removed_pairs": len(dropped_lines),
        "removed_candidate_records": 2 * len(dropped_lines),
        "removed_input_lines": sorted(dropped_lines),
        "conflicts": conflicts,
    }
    return kept, report


def _drop_duplicate_candidate_pairs(
    candidates: list[_Candidate],
) -> tuple[list[_Candidate], dict]:
    by_input = defaultdict(list)
    by_pair = defaultdict(list)
    for candidate in candidates:
        by_input[candidate.fingerprint].append(candidate)
        by_pair[candidate.pair.line_number].append(candidate)
    duplicate_inputs = {
        fingerprint: occurrences
        for fingerprint, occurrences in by_input.items()
        if len({item.pair.line_number for item in occurrences}) > 1
    }
    seen = {}
    removals = []
    removed_lines = set()
    for line_number in sorted(by_pair):
        pair_candidates = by_pair[line_number]
        duplicates = [
            item for item in pair_candidates if item.fingerprint in seen
        ]
        if duplicates:
            removed_lines.add(line_number)
            first = pair_candidates[0].pair.value
            removals.append({
                "removed_input_line": line_number,
                "kept_input_lines": sorted({
                    seen[item.fingerprint] for item in duplicates
                }),
                "scenario_id": first["scenario_id"],
                "mutant": first["mutant"],
                "duplicate_candidates": [
                    {
                        "input_fingerprint": item.fingerprint,
                        "candidate_role": item.role,
                        "kept_input_line": seen[item.fingerprint],
                    }
                    for item in duplicates
                ],
            })
            continue
        for candidate in pair_candidates:
            seen[candidate.fingerprint] = line_number
    kept = [
        candidate for candidate in candidates
        if candidate.pair.line_number not in removed_lines
    ]
    report = {
        "definition": "identical sanitized candidate model input with the same target in a different pair",
        "policy": "retain the earliest input-line pair; drop each later implicated pair as a whole",
        "duplicate_inputs": len(duplicate_inputs),
        "duplicate_candidate_occurrences": sum(
            len(occurrences) for occurrences in duplicate_inputs.values()
        ),
        "removed_pairs": len(removals),
        "removed_candidate_records": 2 * len(removals),
        "removed_input_lines": sorted(removed_lines),
        "removals": removals,
    }
    return kept, report


def _to_record(candidate: _Candidate, input_sha256: str, source_url: str,
               license_name: str, seed: int) -> dict:
    pair = candidate.pair
    raw = pair.value
    original_id = f"{source_url}#L{pair.line_number}"
    return {
        "id": (
            f"import:ora-dpo:{input_sha256[:12]}:"
            f"{pair.line_number}:{candidate.role}"
        ),
        "group_id": raw["scenario_id"],
        "split": candidate.split,
        "source": raw["source"],
        "state": candidate.state,
        "question": QUESTION,
        "kind": KIND,
        "options": list(OPTIONS),
        "target": list(candidate.target),
        "metadata": {
            "target_basis": TARGET_BASIS,
            "historical_development": True,
            "provenance": {
                "type": "import",
                "input_sha256": input_sha256,
                "source_url": source_url,
                "license": license_name,
                "original_id": original_id,
                "original_split": raw["split"],
                "original_mutant": raw["mutant"],
                "split_policy": SPLIT_POLICY,
                "split_seed": seed,
            },
        },
    }


def _model_text(record: dict) -> str:
    return _canonical({field: record[field] for field in MODEL_INPUT_FIELDS})


def _check_output_safety(records: list[dict], all_scenario_ids: set[str],
                         all_sources: set[str]) -> dict:
    prompt_contexts = defaultdict(lambda: {"groups": set(), "splits": set()})
    input_owners = defaultdict(set)
    for record in records:
        model_text = _model_text(record)
        for scenario_id in all_scenario_ids:
            if scenario_id in model_text:
                raise DataLeakageError(
                    f"scenario_id leaked into model input for record {record['id']}"
                )
        for source in all_sources:
            if source in model_text:
                raise DataLeakageError(
                    f"source leaked into model input for record {record['id']}"
                )
        context = prompt_contexts[record["state"]["prompt"]]
        context["groups"].add(record["group_id"])
        context["splits"].add(record["split"])
        input_owners[_fingerprint(record["state"])].add(
            record["metadata"]["provenance"]["original_id"]
        )

    cross_group = [value for value in prompt_contexts.values() if len(value["groups"]) > 1]
    cross_split = [value for value in prompt_contexts.values() if len(value["splits"]) > 1]
    if cross_group or cross_split:
        raise DataLeakageError(
            f"prompt context leakage: {len(cross_group)} cross-scenario contexts, "
            f"{len(cross_split)} cross-split contexts"
        )
    residual_duplicates = sum(len(owners) > 1 for owners in input_owners.values())
    if residual_duplicates:
        raise DataConflictError(
            f"{residual_duplicates} duplicate candidate inputs remain across distinct pairs"
        )
    return {
        "cross_split_groups": 0,
        "cross_split_prompt_contexts": 0,
        "cross_scenario_prompt_contexts": 0,
        "scenario_id_occurrences_in_model_inputs": 0,
        "source_occurrences_in_model_inputs": 0,
        "residual_duplicate_candidate_inputs": 0,
        "residual_conflicting_candidate_inputs": 0,
    }


def validate_output_records(records: Iterable[dict]) -> dict:
    ids = set()
    groups = {}
    contexts = {}
    inputs = {}
    pairs = defaultdict(list)
    counts = Counter()
    for line, record in enumerate(records, 1):
        prefix = f"record {line} ({record.get('id', '?')}): "
        if set(record) != OUTPUT_FIELDS:
            raise DataPreparationError(prefix + "incorrect output schema fields")
        for field in ("id", "group_id", "source", "question"):
            if not isinstance(record[field], str) or not record[field].strip():
                raise DataPreparationError(prefix + f"{field} must be nonempty text")
        if record["id"] in ids:
            raise DataPreparationError(prefix + "duplicate id")
        if record["split"] not in SPLITS:
            raise DataPreparationError(prefix + "unknown split")
        if record["kind"] != KIND or record["options"] != OPTIONS:
            raise DataPreparationError(prefix + "invalid noul contract")
        state = record["state"]
        if (
            not isinstance(state, dict) or set(state) != {"prompt", "candidate_code"}
            or any(not isinstance(value, str) or not value.strip() for value in state.values())
        ):
            raise DataPreparationError(prefix + "state must contain nonempty prompt and candidate_code")
        target = record["target"]
        if (
            not isinstance(target, list) or len(target) != 2
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in target)
            or list(target) not in (list(CHOSEN_TARGET), list(REJECTED_TARGET))
        ):
            raise DataPreparationError(prefix + "target must be [0.0, 1.0] or [1.0, 0.0]")
        metadata = record["metadata"]
        if not isinstance(metadata, dict):
            raise DataPreparationError(prefix + "metadata must be an object")
        if metadata.get("target_basis") != TARGET_BASIS:
            raise DataPreparationError(prefix + "incorrect target_basis")
        if metadata.get("historical_development") is not True:
            raise DataPreparationError(prefix + "historical_development must be true")
        provenance = metadata.get("provenance")
        required_provenance = {
            "input_sha256", "source_url", "license", "original_id", "split_policy",
        }
        if (
            not isinstance(provenance, dict) or provenance.get("type") != "import"
            or any(not provenance.get(field) for field in required_provenance)
        ):
            raise DataPreparationError(prefix + "incomplete import provenance")
        group = record["group_id"]
        split = record["split"]
        if group in groups and groups[group] != split:
            raise DataLeakageError(prefix + "group appears in multiple splits")
        context = _hash({
            "state": state,
            "question": " ".join(record["question"].split()),
            "kind": record["kind"],
        })
        if context in contexts and contexts[context] != split:
            raise DataLeakageError(prefix + "candidate context appears in multiple splits")
        fingerprint = _fingerprint(state)
        target_by_label = dict(zip(record["options"], target))
        if fingerprint in inputs and inputs[fingerprint][1] != target_by_label:
            raise DataConflictError(prefix + "identical input has conflicting targets")
        if record["group_id"] in _model_text(record) or record["source"] in _model_text(record):
            raise DataLeakageError(prefix + "group/source leaked into model input")
        ids.add(record["id"])
        groups[group] = split
        contexts[context] = split
        inputs[fingerprint] = split, target_by_label
        pairs[provenance["original_id"]].append(record)
        counts[split] += 1
    for original_id, pair_records in pairs.items():
        targets = sorted(record["target"] for record in pair_records)
        if len(pair_records) != 2 or targets != [list(CHOSEN_TARGET), list(REJECTED_TARGET)]:
            raise DataPreparationError(f"pair {original_id}: incomplete or inconsistent pair")
        if len({record["group_id"] for record in pair_records}) != 1:
            raise DataPreparationError(f"pair {original_id}: multiple groups")
        if len({record["split"] for record in pair_records}) != 1:
            raise DataPreparationError(f"pair {original_id}: multiple splits")
    return {
        "records": len(ids),
        "pairs": len(pairs),
        "groups": len(groups),
        "unique_inputs": len(inputs),
        "splits": dict(sorted(counts.items())),
    }


def _prepare_numbered(
    pairs: list[NumberedPair], input_sha256: str, *, source_url: str,
    license_name: str, split_seed: int, conflict_policy: str,
) -> PreparedData:
    if conflict_policy not in ("drop", "error"):
        raise ValueError("conflict_policy must be drop or error")
    if not input_sha256 or not source_url.strip() or not license_name.strip():
        raise ValueError("input hash, source_url and license are required")
    for pair in pairs:
        _validate_input(pair)
    scenario_ids = {pair.value["scenario_id"] for pair in pairs}
    sources = {pair.value["source"] for pair in pairs}
    assignment, split_details = _assign_splits(pairs, split_seed)
    unique, duplicate_report = _deduplicate(pairs)
    candidates = []
    for pair in unique:
        for candidate in _expand_pair(
            pair, assignment[pair.value["scenario_id"]], scenario_ids, sources,
        ):
            candidates.append(_with_fingerprint(candidate))
    kept, conflict_report = _drop_label_conflicts(candidates, conflict_policy)
    kept, candidate_duplicate_report = _drop_duplicate_candidate_pairs(kept)
    records = [
        _to_record(candidate, input_sha256, source_url, license_name, split_seed)
        for candidate in kept
    ]
    safety_report = _check_output_safety(records, scenario_ids, sources)
    validation = validate_output_records(records) if records else {
        "records": 0, "pairs": 0, "groups": 0, "unique_inputs": 0, "splits": {},
    }
    report = {
        "input_pairs": len(pairs),
        "unique_pairs_after_exact_deduplication": len(unique),
        "output_pairs": len(records) // 2,
        "output_records": len(records),
        "split_assignment": split_details,
        "exact_duplicates": duplicate_report,
        "candidate_input_duplicates": candidate_duplicate_report,
        "label_conflicts": conflict_report,
        "safety_checks": safety_report,
        "validation": validation,
    }
    return PreparedData(records, report)


def prepare_records(rows: Iterable[dict], input_sha256: str, *,
                    source_url: str = SOURCE_URL, license_name: str = LICENSE_NAME,
                    split_seed: int = 42, conflict_policy: str = "drop") -> PreparedData:
    """Pure in-memory conversion API; input line numbers are one-based row positions."""
    pairs = [NumberedPair(index, row) for index, row in enumerate(rows, 1)]
    return _prepare_numbered(
        pairs, input_sha256, source_url=source_url, license_name=license_name,
        split_seed=split_seed, conflict_policy=conflict_policy,
    )


def _split_details(records: list[dict]) -> dict:
    details = {}
    for split in SPLITS:
        split_records = [record for record in records if record["split"] == split]
        pair_records = [record for record in split_records if record["target"] == [0.0, 1.0]]
        scenarios = sorted({record["group_id"] for record in split_records})
        details[split] = {
            "pairs": len(pair_records),
            "records": len(split_records),
            "scenarios": len(scenarios),
            "scenario_ids": scenarios,
            "pair_mutants": dict(sorted(Counter(
                record["metadata"]["provenance"]["original_mutant"]
                for record in pair_records
            ).items())),
            "pair_sources": dict(sorted(Counter(
                record["source"] for record in pair_records
            ).items())),
            "target_records": {
                "no": sum(record["target"] == [1.0, 0.0] for record in split_records),
                "yes": sum(record["target"] == [0.0, 1.0] for record in split_records),
            },
        }
    return details


def generate_dataset(input_path: str | Path = DEFAULT_INPUT,
                     output_dir: str | Path = DEFAULT_OUTPUT, *,
                     source_url: str = SOURCE_URL, license_name: str = LICENSE_NAME,
                     split_seed: int = 42, conflict_policy: str = "drop") -> dict:
    pairs, input_sha256 = read_input_pairs(input_path)
    prepared = _prepare_numbered(
        pairs, input_sha256, source_url=source_url, license_name=license_name,
        split_seed=split_seed, conflict_policy=conflict_policy,
    )
    if not prepared.records:
        raise DataPreparationError("no records remain after duplicate/conflict handling")
    records = prepared.records
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    files_sha256 = {}
    for split in SPLITS:
        path = output / f"{split}.jsonl"
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                if record["split"] == split:
                    handle.write(_canonical(record) + "\n")
        files_sha256[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    split_details = _split_details(records)
    manifest = {
        "schema_version": 1,
        "dataset_version": DATASET_VERSION,
        "model_input_fields": MODEL_INPUT_FIELDS,
        "input": {
            "source_url": source_url,
            "sha256": input_sha256,
            "pairs": prepared.report["input_pairs"],
        },
        "summary": {
            "pairs": len(records) // 2,
            "records": len(records),
            "scenarios": len({record["group_id"] for record in records}),
            "unique_inputs": prepared.report["validation"]["unique_inputs"],
            "exact_duplicate_pairs_removed": prepared.report["exact_duplicates"]["removed_pairs"],
            "duplicate_candidate_inputs": prepared.report["candidate_input_duplicates"]["duplicate_inputs"],
            "duplicate_candidate_pairs_removed": prepared.report["candidate_input_duplicates"]["removed_pairs"],
            "total_duplicate_pairs_removed": (
                prepared.report["exact_duplicates"]["removed_pairs"]
                + prepared.report["candidate_input_duplicates"]["removed_pairs"]
            ),
            "conflicting_inputs": prepared.report["label_conflicts"]["conflicting_inputs"],
            "conflict_pairs_removed": prepared.report["label_conflicts"]["removed_pairs"],
        },
        "splits": split_details,
        "split_assignment": prepared.report["split_assignment"],
        "duplicate_handling": {
            "exact_pairs": prepared.report["exact_duplicates"],
            "candidate_inputs": prepared.report["candidate_input_duplicates"],
        },
        "conflict_handling": prepared.report["label_conflicts"],
        "group_consistency": {
            "group_id": "scenario_id",
            "pair_integrity": "every retained original_id has exactly one chosen and one rejected candidate in one split",
            **prepared.report["safety_checks"],
            "train_wrong_constant_pairs": split_details["train"]["pair_mutants"].get("wrong_constant", 0),
        },
        "data_limitations": DATA_LIMITATIONS,
        "validation": {
            "local_standard_library_checks": prepared.report["validation"],
            "official_jev_validate_records": "not run locally; remote validation is a separate acceptance step",
        },
        "files_sha256": files_sha256,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--license", dest="license_name", default=LICENSE_NAME)
    parser.add_argument("--split-seed", type=int, default=42)
    parser.add_argument("--conflict-policy", choices=("drop", "error"), default="drop")
    args = parser.parse_args(argv)
    try:
        manifest = generate_dataset(
            args.input, args.output_dir, source_url=args.source_url,
            license_name=args.license_name, split_seed=args.split_seed,
            conflict_policy=args.conflict_policy,
        )
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    result = {
        "output_dir": str(args.output_dir),
        "summary": manifest["summary"],
        "splits": {
            split: {
                key: value
                for key, value in details.items()
                if key in ("pairs", "records", "scenarios")
            }
            for split, details in manifest["splits"].items()
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
