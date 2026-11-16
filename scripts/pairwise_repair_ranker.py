#!/usr/bin/env python3
"""Falsifiable pairwise repair-ranker pilot; no controller or solver replacement."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Optional

import joblib
import numpy as np
import sklearn
from scipy import sparse
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.repair_features import feature_difference, style_features  # noqa: E402


MODEL_NAMES = ("length_only", "style_logreg", "ast_logreg", "tfidf_logreg")
MODEL_KIND = {
    "length_only": "length",
    "style_logreg": "style",
    "ast_logreg": "ast",
    "tfidf_logreg": "tfidf",
}
MODEL_PRIORITY = {name: index for index, name in enumerate(MODEL_NAMES)}
REQUIRED_FIELDS = {
    "scenario_id", "mutant", "prompt", "chosen", "rejected", "source", "split"
}
ALLOWED_SOURCES = {"factory_pass", "rescue_pass"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def pair_identifier(row: dict) -> str:
    return sha256_text("\0".join((row["prompt"], row["chosen"], row["rejected"])))[:20]


def json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1,
                               default=json_default) + "\n")


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=json_default) + "\n")


def load_pairs(path: Path) -> tuple:
    """Load, validate orientation collisions, and remove exact duplicate pairs."""
    raw_rows = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        missing = REQUIRED_FIELDS - set(row)
        if missing:
            raise ValueError(f"line {line_number}: missing fields {sorted(missing)}")
        if row["split"] not in ("train", "dev"):
            raise ValueError(f"line {line_number}: invalid split {row['split']!r}")
        if row["source"] not in ALLOWED_SOURCES:
            raise ValueError(f"line {line_number}: invalid source {row['source']!r}")
        if not row["chosen"].strip() or not row["rejected"].strip():
            raise ValueError(f"line {line_number}: empty candidate")
        if row["chosen"].strip() == row["rejected"].strip():
            raise ValueError(f"line {line_number}: chosen and rejected are identical")
        row = dict(row)
        row["source_line"] = line_number
        row["pair_id"] = pair_identifier(row)
        raw_rows.append(row)

    scenario_splits = defaultdict(set)
    for row in raw_rows:
        scenario_splits[row["scenario_id"]].add(row["split"])
    mixed = {sid: sorted(splits) for sid, splits in scenario_splits.items()
             if len(splits) != 1}
    if mixed:
        raise ValueError(f"scenario appears on multiple split sides: {mixed}")

    seen = {}
    rows = []
    duplicates = []
    for row in raw_rows:
        key = (row["prompt"], row["chosen"], row["rejected"])
        reverse_key = (row["prompt"], row["rejected"], row["chosen"])
        if reverse_key in seen:
            other = seen[reverse_key]
            raise ValueError(
                f"reversed pair direction collision between lines {other['source_line']} "
                f"and {row['source_line']}")
        if key in seen:
            duplicates.append(row)
            continue
        seen[key] = row
        rows.append(row)

    audit = {
        "path": str(path),
        "sha256": sha256_bytes(path.read_bytes()),
        "bytes": path.stat().st_size,
        "raw_pairs": len(raw_rows),
        "deduplicated_pairs": len(rows),
        "exact_duplicates_removed": len(duplicates),
        "duplicates_by_split": dict(Counter(row["split"] for row in duplicates)),
        "pairs_by_split": dict(Counter(row["split"] for row in rows)),
        "scenarios_by_split": {
            split: len({row["scenario_id"] for row in rows if row["split"] == split})
            for split in ("train", "dev")
        },
        "sources_by_split": {
            split: dict(Counter(row["source"] for row in rows if row["split"] == split))
            for split in ("train", "dev")
        },
        "mutants_by_split": {
            split: dict(Counter(row["mutant"] for row in rows if row["split"] == split))
            for split in ("train", "dev")
        },
        "scenario_mixed_split_count": 0,
        "reversed_direction_collisions": 0,
        "identical_candidate_pairs": 0,
        "canonical_deduplicated_sha256": sha256_text("\n".join(
            json.dumps({key: row[key] for key in (
                "pair_id", "scenario_id", "mutant", "prompt", "chosen", "rejected",
                "source", "split")}, sort_keys=True, ensure_ascii=False)
            for row in rows)),
    }
    return raw_rows, rows, audit


def _objective_close(objective, reference, tolerance: float) -> bool:
    try:
        objective = float(objective)
        reference = float(reference)
    except (TypeError, ValueError):
        return False
    return (math.isfinite(objective) and math.isfinite(reference)
            and abs(objective - reference) <= tolerance * max(1.0, abs(reference)))


def audit_trace_directions(raw_rows: list, factory_dir: Path, rescue_dir: Path) -> dict:
    """Verify both directions and quarantine pairs whose negative also passed."""
    from scripts.p3_build_sft import factory_prompt

    factory_by_key = defaultdict(list)
    for path in sorted(factory_dir.glob("samples_*.json")):
        try:
            sample = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if sample.get("mutant_valid") and sample.get("broken_code"):
            sample["_audit_prompt"] = factory_prompt(sample)
            factory_by_key[(sample["scenario_id"], sample["mutant_type"])].append(sample)

    rescue_by_key = defaultdict(list)
    for path in sorted(rescue_dir.glob("rescue_*.json")):
        try:
            rescue = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if rescue.get("rescued") and rescue.get("rescued_code"):
            rescue_by_key[(rescue["scenario_id"], rescue["mutant_type"])].append(rescue)

    matched = Counter()
    verified_pair_ids = []
    failures = []
    for row in raw_rows:
        key = (row["scenario_id"], row["mutant"])
        matches = 0
        rejected_verified_pass = False
        if row["source"] == "factory_pass":
            for sample in factory_by_key[key]:
                verdict = sample.get("witness_verdict") or {}
                before = sample.get("exec_before") or {}
                positive = (
                    sample.get("repaired_code") == row["chosen"]
                    and verdict.get("verdict") == "pass"
                    and _objective_close(sample.get("objective_after"),
                                         sample.get("gold_objective"), 1e-4))
                negative = (sample.get("broken_code") == row["rejected"]
                            and before.get("witness") == "infeasible")
                if positive and negative and sample["_audit_prompt"] == row["prompt"]:
                    matches += 1
        else:
            for rescue in rescue_by_key[key]:
                if rescue.get("rescued_code") != row["chosen"]:
                    continue
                history = rescue.get("history") or []
                final = history[-1] if history else {}
                positive = (final.get("witness") == "feasible"
                            and final.get("grade") == "match"
                            and _objective_close(final.get("objective"),
                                                 rescue.get("gold_objective"), 1e-3))
                if not positive:
                    continue
                for base in factory_by_key[key]:
                    rejected = base.get("repaired_code") or base.get("broken_code")
                    if rejected != row["rejected"] or base["_audit_prompt"] != row["prompt"]:
                        continue
                    verdict = base.get("witness_verdict") or {}
                    if base.get("repaired_code"):
                        negative = verdict.get("verdict") == "fail"
                        rejected_verified_pass |= (
                            verdict.get("verdict") == "pass" and verdict.get("grade") == "match")
                    else:
                        negative = (base.get("exec_before") or {}).get("witness") == "infeasible"
                    if negative:
                        matches += 1
        if matches and not rejected_verified_pass:
            matched[row["source"]] += 1
            verified_pair_ids.append(row["pair_id"])
        else:
            reason = ("rejected_was_verified_pass" if rejected_verified_pass
                      else "no_exact_verified_direction_match")
            failures.append({"source_line": row["source_line"], "pair_id": row["pair_id"],
                             "scenario_id": row["scenario_id"], "mutant": row["mutant"],
                             "source": row["source"], "reason": reason})
    return {
        "factory_trace_count": sum(map(len, factory_by_key.values())),
        "rescue_trace_count": sum(map(len, rescue_by_key.values())),
        "matched_raw_pairs": dict(matched),
        "verified_pair_ids": verified_pair_ids,
        "direction_excluded_raw_pairs": len(failures),
        "excluded_pairs": failures,
        "exclusion_reasons": dict(Counter(row["reason"] for row in failures)),
        "positive_criterion": (
            "factory: witness pass and |objective-gold|<=1e-4*max(1,|gold|); "
            "rescue: final witness feasible and grade=match"),
        "negative_criterion": (
            "factory broken code has recorded witness=infeasible; rescue negative is "
            "the recorded failed factory repair, or broken code when no repair exists; "
            "a rejected candidate with any matching pass/match trace is quarantined"),
        "builder_prompt_exact_match_required": True,
    }


def fit_model(model_name: str, rows: list, seed: int) -> dict:
    """Fit a position-symmetric model using only prompt/candidate/execution inputs."""
    kind = MODEL_KIND[model_name]
    model = {"model_name": model_name, "kind": kind, "seed": seed}
    if kind == "length":
        return model

    classifier = LogisticRegression(
        C=1.0, fit_intercept=False, max_iter=2000, solver="liblinear",
        dual=(kind == "tfidf"), random_state=seed)
    if kind == "tfidf":
        vectorizer = TfidfVectorizer(
            lowercase=False, analyzer="word", token_pattern=r"(?u)\b\w+\b",
            ngram_range=(1, 2), min_df=2, max_features=20000,
            sublinear_tf=True, norm="l2", dtype=np.float64)
        corpus = [candidate for row in rows for candidate in (row["chosen"], row["rejected"])]
        vectorizer.fit(corpus)
        chosen = vectorizer.transform(row["chosen"] for row in rows)
        rejected = vectorizer.transform(row["rejected"] for row in rows)
        difference = chosen - rejected
        model.update(vectorizer=vectorizer, scaler=None)
    else:
        vectorizer = DictVectorizer(sparse=True)
        differences = [feature_difference(
            kind, row["prompt"], row["chosen"], row["rejected"],
            row.get("chosen_execution"), row.get("rejected_execution")) for row in rows]
        difference = vectorizer.fit_transform(differences)
        scaler = StandardScaler(with_mean=False)
        difference = scaler.fit_transform(sparse.vstack((difference, -difference)))
        model.update(vectorizer=vectorizer, scaler=scaler)
        augmented = difference
        labels = np.concatenate((np.ones(len(rows)), np.zeros(len(rows))))
        classifier.fit(augmented, labels)
        model["classifier"] = classifier
        return model

    augmented = sparse.vstack((difference, -difference), format="csr")
    labels = np.concatenate((np.ones(len(rows)), np.zeros(len(rows))))
    classifier.fit(augmented, labels)
    model["classifier"] = classifier
    return model


def score_model(model: dict, rows: list) -> np.ndarray:
    """Positive means chosen is preferred; zero is an abstention."""
    if not rows:
        return np.zeros(0, dtype=float)
    kind = model["kind"]
    if kind == "length":
        return np.asarray([
            math.log1p(len(row["chosen"])) - math.log1p(len(row["rejected"]))
            for row in rows])
    if kind == "tfidf":
        chosen = model["vectorizer"].transform(row["chosen"] for row in rows)
        rejected = model["vectorizer"].transform(row["rejected"] for row in rows)
        difference = chosen - rejected
    else:
        differences = [feature_difference(
            kind, row["prompt"], row["chosen"], row["rejected"],
            row.get("chosen_execution"), row.get("rejected_execution")) for row in rows]
        difference = model["vectorizer"].transform(differences)
        difference = model["scaler"].transform(difference)
    return np.asarray(model["classifier"].decision_function(difference)).reshape(-1)


def reverse_rows(rows: list) -> list:
    reversed_rows = []
    for row in rows:
        item = dict(row)
        item["chosen"], item["rejected"] = row["rejected"], row["chosen"]
        item["chosen_execution"], item["rejected_execution"] = (
            row.get("rejected_execution"), row.get("chosen_execution"))
        reversed_rows.append(item)
    return reversed_rows


def grouped_oof(model_name: str, rows: list, seed: int, folds: int) -> tuple:
    groups = np.asarray([row["scenario_id"] for row in rows])
    unique_groups = len(set(groups))
    n_splits = min(folds, unique_groups)
    if n_splits < 2:
        raise ValueError("grouped validation requires at least two scenarios")
    rng = np.random.default_rng(seed)
    scenario_names = np.asarray(sorted(set(groups)))
    shuffled_names = rng.permutation(scenario_names)
    relabel = {scenario: index for index, scenario in enumerate(shuffled_names)}
    shuffled_groups = np.asarray([relabel[scenario] for scenario in groups])
    splitter = GroupKFold(n_splits=n_splits)
    margins = np.zeros(len(rows), dtype=float)
    fold_ids = np.full(len(rows), -1, dtype=int)
    fold_rows = []
    indices = np.arange(len(rows))
    for fold, (train_indices, valid_indices) in enumerate(
            splitter.split(indices, groups=shuffled_groups)):
        model = fit_model(model_name, [rows[index] for index in train_indices], seed + fold)
        margins[valid_indices] = score_model(model, [rows[index] for index in valid_indices])
        fold_ids[valid_indices] = fold
        fold_rows.append({
            "fold": fold,
            "train_pairs": int(len(train_indices)),
            "validation_pairs": int(len(valid_indices)),
            "train_scenarios": int(len(set(groups[train_indices]))),
            "validation_scenarios": int(len(set(groups[valid_indices]))),
            "validation_indices": valid_indices.tolist(),
        })
    if np.any(fold_ids < 0):
        raise AssertionError("incomplete grouped OOF predictions")
    return margins, fold_ids, fold_rows


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> Optional[list]:
    if total == 0:
        return None
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    radius = z * math.sqrt(
        proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)
    ) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def scenario_bootstrap_interval(correct: np.ndarray, covered: np.ndarray,
                                scenarios: np.ndarray, seed: int,
                                replicates: int) -> Optional[list]:
    unique = np.unique(scenarios)
    if not len(unique) or replicates <= 0:
        return None
    per_scenario = {}
    for scenario in unique:
        mask = scenarios == scenario
        denominator = int(covered[mask].sum())
        per_scenario[scenario] = (float(correct[mask].sum() / denominator)
                                  if denominator else None)
    rng = np.random.default_rng(seed)
    estimates = []
    for _ in range(replicates):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        values = [per_scenario[scenario] for scenario in sampled
                  if per_scenario[scenario] is not None]
        if values:
            estimates.append(float(np.mean(values)))
    if not estimates:
        return None
    return np.percentile(estimates, [2.5, 97.5]).tolist()


def summarize_predictions(rows: list, margins: np.ndarray, seed: int,
                          bootstrap: int = 2000, include_scenarios: bool = True) -> dict:
    margins = np.asarray(margins, dtype=float)
    covered = margins != 0.0
    correct = (margins > 0.0) & covered
    n_covered = int(covered.sum())
    n_correct = int(correct.sum())
    scenarios = np.asarray([row["scenario_id"] for row in rows])
    scenario_rows = []
    macro_values = []
    for scenario in sorted(set(scenarios)):
        mask = scenarios == scenario
        scenario_covered = int(covered[mask].sum())
        scenario_correct = int(correct[mask].sum())
        accuracy = scenario_correct / scenario_covered if scenario_covered else None
        if accuracy is not None:
            macro_values.append(accuracy)
        scenario_rows.append({
            "scenario_id": scenario,
            "pairs": int(mask.sum()),
            "covered": scenario_covered,
            "coverage": scenario_covered / int(mask.sum()),
            "correct": scenario_correct,
            "pairwise_accuracy": accuracy,
        })
    result = {
        "pairs": len(rows),
        "scenarios": len(set(scenarios)),
        "covered": n_covered,
        "coverage": n_covered / len(rows) if rows else 0.0,
        "coverage_wilson_ci95": wilson_interval(n_covered, len(rows)),
        "correct": n_correct,
        "abstentions": len(rows) - n_covered,
        "pairwise_accuracy": n_correct / n_covered if n_covered else None,
        "pairwise_accuracy_wilson_ci95": wilson_interval(n_correct, n_covered),
        "unconditional_accuracy_abstain_wrong": n_correct / len(rows) if rows else None,
        "macro_scenario_accuracy": float(np.mean(macro_values)) if macro_values else None,
        "macro_scenario_bootstrap_ci95": scenario_bootstrap_interval(
            correct, covered, scenarios, seed, bootstrap),
        "accuracy_note": (
            "pairwise_accuracy is conditional on non-abstention; macro_scenario_accuracy "
            "weights each covered scenario equally; CI resamples scenario IDs"),
    }
    if include_scenarios:
        result["by_scenario"] = scenario_rows
    return result


def length_matched_mask(rows: list, threshold: float) -> np.ndarray:
    return np.asarray([
        abs(len(row["chosen"]) - len(row["rejected"]))
        / max(1, len(row["chosen"]), len(row["rejected"])) <= threshold
        for row in rows])


def evaluate_predictions(rows: list, margins: np.ndarray, seed: int,
                         length_threshold: float, bootstrap: int = 2000,
                         strata: bool = True) -> dict:
    result = summarize_predictions(rows, margins, seed, bootstrap)
    mask = length_matched_mask(rows, length_threshold)
    selected_rows = [row for row, keep in zip(rows, mask) if keep]
    result["length_matched"] = summarize_predictions(
        selected_rows, margins[mask], seed + 1, bootstrap, include_scenarios=False)
    result["length_matched"]["relative_char_difference_threshold"] = length_threshold
    if strata:
        for field in ("source", "mutant"):
            values = sorted({row[field] for row in rows})
            result[f"by_{field}"] = {}
            for value in values:
                selected = [index for index, row in enumerate(rows) if row[field] == value]
                result[f"by_{field}"][value] = summarize_predictions(
                    [rows[index] for index in selected], margins[selected], seed + 2,
                    bootstrap=0, include_scenarios=False)
    return result


def prediction_rows(rows: list, margins_by_model: dict, fold_ids=None) -> list:
    output = []
    for index, row in enumerate(rows):
        item = {
            "pair_id": row["pair_id"], "source_line": row["source_line"],
            "scenario_id": row["scenario_id"], "split": row["split"],
            "mutant": row["mutant"], "source": row["source"],
            "chosen_sha256": sha256_text(row["chosen"]),
            "rejected_sha256": sha256_text(row["rejected"]),
            "relative_char_difference": abs(len(row["chosen"]) - len(row["rejected"]))
            / max(1, len(row["chosen"]), len(row["rejected"])),
            "models": {},
        }
        for model_name, margins in margins_by_model.items():
            margin = float(margins[index])
            prediction = "chosen" if margin > 0 else "rejected" if margin < 0 else "abstain"
            fold = None
            if fold_ids is not None:
                model_folds = fold_ids[model_name] if isinstance(fold_ids, dict) else fold_ids
                fold = int(model_folds[index])
            item["models"][model_name] = {
                "margin_chosen_minus_rejected": margin,
                "top_choice": prediction,
                "covered": prediction != "abstain",
                "correct": prediction == "chosen",
                "fold": fold,
            }
        output.append(item)
    return output


def permute_orientations_by_scenario(rows: list, seed: int) -> tuple:
    rng = np.random.default_rng(seed)
    scenarios = sorted({row["scenario_id"] for row in rows})
    flips = {scenario: bool(rng.integers(0, 2)) for scenario in scenarios}
    output = []
    for row in rows:
        if flips[row["scenario_id"]]:
            output.append(reverse_rows([row])[0])
        else:
            output.append(dict(row))
    return output, flips


def candidate_overlap(train_rows: list, dev_rows: list) -> dict:
    roles = defaultdict(set)
    for row in train_rows:
        roles[sha256_text(row["chosen"])].add("chosen")
        roles[sha256_text(row["rejected"])].add("rejected")
    any_overlap = np.zeros(len(dev_rows), dtype=bool)
    same_role = 0
    opposite_role = 0
    for index, row in enumerate(dev_rows):
        for role in ("chosen", "rejected"):
            train_roles = roles.get(sha256_text(row[role]), set())
            if train_roles:
                any_overlap[index] = True
            same_role += int(role in train_roles)
            opposite_role += int(("rejected" if role == "chosen" else "chosen") in train_roles)
    return {
        "train_unique_candidates": len(roles),
        "dev_pairs_with_any_exact_train_candidate": int(any_overlap.sum()),
        "dev_candidate_same_role_overlaps": same_role,
        "dev_candidate_opposite_role_overlaps": opposite_role,
        "novel_candidate_mask": any_overlap.tolist(),
    }


def model_diagnostics(model: dict, limit: int = 15) -> dict:
    if model["kind"] == "length":
        return {"rule": "prefer log character length; exact ties abstain"}
    names = model["vectorizer"].get_feature_names_out()
    coefficients = np.asarray(model["classifier"].coef_).reshape(-1)
    positive = np.argsort(coefficients)[-limit:][::-1]
    negative = np.argsort(coefficients)[:limit]
    return {
        "feature_count": int(len(names)),
        "top_positive": [{"feature": str(names[index]), "coefficient": coefficients[index]}
                         for index in positive],
        "top_negative": [{"feature": str(names[index]), "coefficient": coefficients[index]}
                         for index in negative],
        "coefficient_note": "positive increases chosen-minus-rejected margin",
    }


def _solver_grade(objective, reference, solver_status) -> str:
    if solver_status is None:
        return "no_output"
    if solver_status == "infeasible":
        return "declared_infeasible"
    if objective is None:
        return "no_objective"
    gap = (objective - reference) / max(abs(reference), 1e-9)
    if gap < -1e-3:
        return "better_than_reference"
    if gap <= 1e-3:
        return "match"
    return "suboptimal"


def validate_top_choice(model_name: str, rows: list, margins: np.ndarray,
                        reference_rows: list, outdir: Path, timeout: int,
                        limit: int = 0) -> dict:
    """Actually rerun dev top choices with the existing independent witness."""
    from m1_witness import retailopt as witness

    references = {row["scenario_id"]: row for row in reference_rows}
    selected = list(zip(rows, margins))
    if limit:
        selected = selected[:limit]
    records = []
    for row, margin in selected:
        if margin == 0:
            records.append({"pair_id": row["pair_id"], "top_choice": "abstain",
                            "attempted": False, "independent_pass": None})
            continue
        top = "chosen" if margin > 0 else "rejected"
        code = row[top]
        reference = references[row["scenario_id"]]
        sandbox = outdir / row["pair_id"]
        sandbox.mkdir(parents=True, exist_ok=True)
        script = sandbox / "gen.py"
        script.write_text(code)
        (sandbox / "data.json").write_text(reference["data"])
        solution_path = sandbox / "solution.json"
        if solution_path.exists():
            solution_path.unlink()
        start = time.time()
        try:
            process = subprocess.run(
                [sys.executable, str(script)], cwd=sandbox, capture_output=True,
                text=True, timeout=timeout)
            record = {
                "exec_status": "ok" if process.returncode == 0 else "crash",
                "return_code": process.returncode,
                "stderr_tail": process.stderr[-400:] if process.returncode else "",
            }
            status_match = re.search(r"^status:\s*(\S+)", process.stdout, re.MULTILINE)
            objective_match = re.search(
                r"^objective:\s*([-+0-9.eE]+)", process.stdout, re.MULTILINE)
            record["solver_status"] = status_match.group(1) if status_match else None
            record["objective"] = float(objective_match.group(1)) if objective_match else None
        except subprocess.TimeoutExpired:
            record = {"exec_status": "timeout", "solver_status": None, "objective": None}
        record["wall_s"] = round(time.time() - start, 3)
        record.update({
            "pair_id": row["pair_id"], "scenario_id": row["scenario_id"],
            "mutant": row["mutant"], "source": row["source"], "model": model_name,
            "margin": float(margin), "top_choice": top, "attempted": True,
            "code_sha256": sha256_text(code),
        })
        solution = None
        try:
            solution = json.loads(solution_path.read_text())
        except (OSError, json.JSONDecodeError):
            pass
        if solution is None:
            record["witness"] = "no_solution"
            record["witness_rules"] = []
        else:
            try:
                checked = witness.check(json.loads(reference["data"]), solution)
                record["witness"] = "feasible" if not checked["violations"] else "infeasible"
                record["witness_rules"] = sorted({rule for rule, _ in checked["violations"]})
                record["witness_details"] = [f"{rule}: {detail}" for rule, detail
                                              in checked["violations"][:10]]
                record["solution_objective"] = solution.get("objective")
            except Exception as error:
                record["witness"] = "checker_error"
                record["witness_error"] = f"{type(error).__name__}: {error}"[:400]
        gold = float(reference["reference_objective"])
        record["reference_objective"] = gold
        record["grade"] = _solver_grade(record.get("objective"), gold,
                                        record.get("solver_status"))
        record["builder_tolerance_objective_match"] = _objective_close(
            record.get("objective"), gold, 1e-4)
        record["independent_pass"] = bool(
            record["exec_status"] == "ok" and record.get("solver_status") == "optimal"
            and record.get("witness") == "feasible" and record["grade"] == "match")
        write_json(sandbox / "record.json", record)
        records.append(record)

    attempted = [record for record in records if record["attempted"]]
    passed = [record for record in attempted if record["independent_pass"]]
    by_top_label = {}
    for label in ("chosen", "rejected"):
        subset = [record for record in attempted if record["top_choice"] == label]
        by_top_label[label] = {
            "attempted": len(subset),
            "independent_pass": sum(record["independent_pass"] for record in subset),
            "pass_rate": (sum(record["independent_pass"] for record in subset) / len(subset)
                          if subset else None),
            "pass_rate_wilson_ci95": wilson_interval(
                sum(record["independent_pass"] for record in subset), len(subset)),
        }
    result = {
        "model_selected_by_train_grouped_validation_only": model_name,
        "selection_used_dev_metrics": False,
        "requested_pairs": len(selected),
        "attempted": len(attempted),
        "abstained": len(selected) - len(attempted),
        "independent_pass": len(passed),
        "pass_rate": len(passed) / len(attempted) if attempted else None,
        "pass_rate_wilson_ci95": wilson_interval(len(passed), len(attempted)),
        "by_top_label": by_top_label,
        "witness_outcomes": dict(Counter(record.get("witness") for record in attempted)),
        "solver_statuses": dict(Counter(record.get("solver_status") for record in attempted)),
        "grades": dict(Counter(record.get("grade") for record in attempted)),
        "total_wall_s": sum(record.get("wall_s", 0.0) for record in attempted),
        "pass_criterion": (
            "fresh subprocess exit 0 + solver status optimal + existing retailopt witness "
            "feasible + existing grade match (relative objective tolerance 1e-3)"),
        "scope": (
            "Re-execution of existing dev candidates only. This validates ranking labels and "
            "top-choice correctness, not improvement over candidate generation or pipeline uplift."),
        "records": records,
    }
    write_json(outdir.parent / "top_choice_validation.json", result)
    return result


def negative_findings(metrics: dict, overlap: dict, selected_model: str,
                      data_audit: dict) -> dict:
    findings = []
    excluded = data_audit["direction_excluded_deduplicated_pairs"]
    if excluded:
        findings.append(
            f"{excluded} deduplicated pairs ({data_audit['direction_excluded_raw_pairs']} raw) "
            "were quarantined because the rejected candidate also had a pass/match trace")
    style_dev = metrics["style_logreg"]["dev"]["macro_scenario_accuracy"]
    length_dev = metrics["length_only"]["dev"]["macro_scenario_accuracy"]
    for name in MODEL_NAMES:
        current = metrics[name]
        train_score = current["train_grouped"]["macro_scenario_accuracy"]
        dev_score = current["dev"]["macro_scenario_accuracy"]
        if name != "style_logreg" and dev_score <= style_dev:
            findings.append(f"{name}: dev macro accuracy does not beat style_logreg")
        if name != "length_only" and dev_score <= length_dev:
            findings.append(f"{name}: dev macro accuracy does not beat length_only")
        gap = train_score - dev_score
        if gap > 0.05:
            findings.append(f"{name}: train-grouped-to-dev macro gap is {gap:.3f} (>0.05)")
        matched = current["dev"]["length_matched"]
        style_matched = metrics["style_logreg"]["dev"]["length_matched"]
        if (matched["pairs"] and name != "style_logreg"
                and matched["macro_scenario_accuracy"] is not None
                and style_matched["macro_scenario_accuracy"] is not None
                and matched["macro_scenario_accuracy"] <= style_matched["macro_scenario_accuracy"]):
            findings.append(f"{name}: no style-baseline gain on the length-matched dev subset")
        permuted = current["permutation_train_grouped"].get("macro_scenario_accuracy")
        if permuted is not None and permuted > 0.60:
            findings.append(f"{name}: orientation-permutation control macro accuracy is {permuted:.3f}")
        by_source = current["dev"].get("by_source", {})
        source_scores = [value["pairwise_accuracy"] for value in by_source.values()
                         if value["pairwise_accuracy"] is not None]
        if source_scores and max(source_scores) - min(source_scores) > 0.20:
            findings.append(f"{name}: source-stratified dev accuracy differs by more than 0.20")
    if overlap["dev_pairs_with_any_exact_train_candidate"]:
        findings.append("exact candidate code overlap remains between train and dev")
    ast = metrics["ast_logreg"]
    ast_matched = ast["dev"]["length_matched"]
    style_matched = metrics["style_logreg"]["dev"]["length_matched"]
    graph_gate = (
        ast["train_grouped"]["macro_scenario_accuracy"]
        > metrics["style_logreg"]["train_grouped"]["macro_scenario_accuracy"] + 0.02
        and ast["dev"]["macro_scenario_accuracy"] > style_dev + 0.02
        and ast_matched["pairs"] >= 10
        and ast_matched["macro_scenario_accuracy"]
        > style_matched["macro_scenario_accuracy"] + 0.02)
    dev_saturated = ast["dev"]["pairwise_accuracy"] == 1.0
    if dev_saturated:
        findings.append(
            "ast_logreg dev is saturated; the current dev cannot establish headroom for a "
            "graph model, and its [1,1] scenario-bootstrap interval is not population certainty")
    return {
        "findings": findings,
        "graph_pilot_gate_passed": bool(graph_gate),
        "graph_pilot_requires_fresh_harder_evaluation": bool(dev_saturated),
        "graph_pilot_gate": (
            "AST must beat style macro accuracy by >0.02 on both train-grouped and dev, "
            "and by >0.02 on a length-matched dev subset with at least 10 pairs"),
        "selected_model_for_independent_validation": selected_model,
        "fixed_limitations": [
            "Factory/rescue development trajectories are not a natural held-out test set.",
            "All positives and negatives came from the same repair factory; candidate-generation "
            "ranking and new-business uplift were not evaluated.",
            "Dev contains few scenarios; scenario-bootstrap intervals remain more informative "
            "than a single pair-level point estimate.",
            "AST counts can still proxy code length; style and length-matched comparisons are "
            "shortcut diagnostics, not proof of semantic learning.",
        ],
    }


def _fmt(value) -> str:
    return "NA" if value is None else f"{value:.3f}"


def _fmt_ci(value) -> str:
    return "NA" if value is None else f"[{value[0]:.3f}, {value[1]:.3f}]"


def render_report(data_audit: dict, metrics: dict, selected_model: str,
                  negative: dict, validation: Optional[dict]) -> str:
    lines = [
        "# Pairwise repair ranker v0.1", "",
        "本 pilot 只验证既有 factory/rescue 候选的 pairwise 排序；dev 不是自然 heldout。",
        "未来位置为候选生成后、确定性审计前，不训练 controller 动作，也不替代 SCIP/witness。", "",
        f"数据：原始 {data_audit['raw_pairs']} 对，去除 {data_audit['exact_duplicates_removed']} "
        f"个精确重复，并隔离 {data_audit['direction_excluded_deduplicated_pairs']} 个方向不可靠对后，"
        f"剩余 {data_audit['deduplicated_pairs']} 对；train "
        f"{data_audit['pairs_by_split'].get('train', 0)} 对 / "
        f"{data_audit['scenarios_by_split'].get('train', 0)} scenarios，dev "
        f"{data_audit['pairs_by_split'].get('dev', 0)} 对 / "
        f"{data_audit['scenarios_by_split'].get('dev', 0)} scenarios。", "",
        "所有模型使用相同 5-fold scenario-grouped train OOF 和固定 seed。pairwise accuracy "
        "以非弃权 pair 为分母；macro 为 scenario 等权；括号为 macro 的 scenario-bootstrap 95% CI。", "",
        "| model | train macro (CI) | dev micro | dev macro (CI) | dev coverage | length-matched dev micro | permutation train macro |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in MODEL_NAMES:
        result = metrics[name]
        train = result["train_grouped"]
        dev = result["dev"]
        lines.append(
            f"| {name} | {_fmt(train['macro_scenario_accuracy'])} "
            f"{_fmt_ci(train['macro_scenario_bootstrap_ci95'])} | "
            f"{_fmt(dev['pairwise_accuracy'])} | {_fmt(dev['macro_scenario_accuracy'])} "
            f"{_fmt_ci(dev['macro_scenario_bootstrap_ci95'])} | {_fmt(dev['coverage'])} | "
            f"{_fmt(dev['length_matched']['pairwise_accuracy'])} "
            f"(n={dev['length_matched']['pairs']}) | "
            f"{_fmt(result['permutation_train_grouped']['macro_scenario_accuracy'])} |")
    lines.extend(["", f"独立重跑模型（仅由 train 分组验证选择）：`{selected_model}`。", ""])
    if validation is None:
        lines.append("未进行独立 SCIP 重跑；本制品只验证 pairwise ranking，不宣称业务提升。")
    else:
        lines.extend([
            f"实际重跑 dev top-choice {validation['attempted']} 个，独立通过 "
            f"{validation['independent_pass']} 个，通过率 {_fmt(validation['pass_rate'])}，"
            f"Wilson 95% CI {_fmt_ci(validation['pass_rate_wilson_ci95'])}。",
            "通过要求新子进程 solver=optimal、既有 retailopt witness=feasible、参考目标 grade=match。",
            "这只是既有候选排序的独立正确性核验，不是新生成候选或端到端业务提升。", "",
        ])
    lines.extend(["## 负结果与风险", ""])
    if negative["findings"]:
        lines.extend(f"- {finding}" for finding in negative["findings"])
    else:
        lines.append("- 未触发预声明的基线/间隔/置换警戒规则；这不构成语义学习证明。")
    lines.extend(f"- {limitation}" for limitation in negative["fixed_limitations"])
    lines.extend(["", f"图模型预声明门槛：{'通过' if negative['graph_pilot_gate_passed'] else '未通过'}。",
                  negative["graph_pilot_gate"]])
    if negative.get("graph_pilot_requires_fresh_harder_evaluation"):
        lines.append("但当前 AST dev 已饱和：只允许在新增更难的独立评估集上开展小型图 pilot，"
                     "不把现有 100% 解释为图模型收益空间。")
    lines.extend(["", "逐 pair 预测、完整 micro/macro/CI、source/mutant 分层、特征系数、模型和数据 hash "
                  "见同目录 JSON/JSONL/JOBLIB 制品。"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "work/sft_data/dpo.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "work/repair_ranker_v0.1")
    parser.add_argument("--factory-dir", type=Path, default=ROOT / "runs/p1_factory")
    parser.add_argument("--rescue-dir", type=Path, default=ROOT / "runs/p2_hints")
    parser.add_argument("--reference-data", type=Path,
                        default=ROOT / "data/m1_retailopt/f1f4_all100.jsonl")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--length-matched-threshold", type=float, default=0.05)
    parser.add_argument("--skip-permutation-control", action="store_true")
    parser.add_argument("--validate-top-choice", action="store_true")
    parser.add_argument("--validation-timeout", type=int, default=60)
    parser.add_argument("--validation-limit", type=int, default=0)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    raw_rows, rows, data_audit = load_pairs(args.data)
    all_scenarios = sorted({row["scenario_id"] for row in raw_rows})
    expected_split = {scenario: ("dev" if index % 10 == 0 else "train")
                      for index, scenario in enumerate(all_scenarios)}
    mismatches = [row["source_line"] for row in raw_rows
                  if row["split"] != expected_split[row["scenario_id"]]]
    data_audit["original_every_tenth_scenario_split_mismatches"] = len(mismatches)
    if mismatches:
        raise ValueError(f"original scenario split assignment mismatch at lines {mismatches[:20]}")

    direction_audit = audit_trace_directions(raw_rows, args.factory_dir, args.rescue_dir)
    data_audit["trace_direction_audit"] = direction_audit
    verified_pair_ids = set(direction_audit["verified_pair_ids"])
    excluded_rows = [row for row in rows if row["pair_id"] not in verified_pair_ids]
    data_audit["pre_direction_filter"] = {
        key: data_audit[key] for key in (
            "deduplicated_pairs", "pairs_by_split", "scenarios_by_split",
            "sources_by_split", "mutants_by_split", "canonical_deduplicated_sha256")}
    rows = [row for row in rows if row["pair_id"] in verified_pair_ids]
    data_audit["direction_excluded_raw_pairs"] = direction_audit["direction_excluded_raw_pairs"]
    data_audit["direction_excluded_deduplicated_pairs"] = len(excluded_rows)
    data_audit["direction_excluded_by_split"] = dict(Counter(
        row["split"] for row in excluded_rows))
    data_audit["deduplicated_pairs"] = len(rows)
    data_audit["pairs_by_split"] = dict(Counter(row["split"] for row in rows))
    data_audit["scenarios_by_split"] = {
        split: len({row["scenario_id"] for row in rows if row["split"] == split})
        for split in ("train", "dev")}
    data_audit["sources_by_split"] = {
        split: dict(Counter(row["source"] for row in rows if row["split"] == split))
        for split in ("train", "dev")}
    data_audit["mutants_by_split"] = {
        split: dict(Counter(row["mutant"] for row in rows if row["split"] == split))
        for split in ("train", "dev")}
    data_audit["canonical_deduplicated_sha256"] = sha256_text("\n".join(
        json.dumps({key: row[key] for key in (
            "pair_id", "scenario_id", "mutant", "prompt", "chosen", "rejected",
            "source", "split")}, sort_keys=True, ensure_ascii=False) for row in rows))
    train_rows = [row for row in rows if row["split"] == "train"]
    dev_rows = [row for row in rows if row["split"] == "dev"]
    overlap = candidate_overlap(train_rows, dev_rows)
    overlap["novel_candidate_mask"] = [not value for value in overlap.pop("novel_candidate_mask")]
    data_audit["train_dev_exact_candidate_overlap"] = {
        key: value for key, value in overlap.items() if key != "novel_candidate_mask"}
    write_json(args.out / "data_audit.json", data_audit)

    train_margins = {}
    train_fold_ids = {}
    dev_margins = {}
    permutation_margins = {}
    metrics = {}
    final_models = {}
    for model_name in MODEL_NAMES:
        margins, fold_ids, fold_rows = grouped_oof(
            model_name, train_rows, args.seed, args.folds)
        train_margins[model_name] = margins
        train_fold_ids[model_name] = fold_ids
        train_metrics = evaluate_predictions(
            train_rows, margins, args.seed, args.length_matched_threshold, args.bootstrap)
        fold_metrics = []
        for fold in fold_rows:
            indices = np.asarray(fold.pop("validation_indices"), dtype=int)
            fold_summary = summarize_predictions(
                [train_rows[index] for index in indices], margins[indices],
                args.seed + fold["fold"], bootstrap=0, include_scenarios=False)
            fold_metrics.append({**fold, "metrics": fold_summary})
        train_metrics["folds"] = fold_metrics

        final_model = fit_model(model_name, train_rows, args.seed)
        final_models[model_name] = final_model
        dev_margins[model_name] = score_model(final_model, dev_rows)
        dev_metrics = evaluate_predictions(
            dev_rows, dev_margins[model_name], args.seed,
            args.length_matched_threshold, args.bootstrap)
        novel_mask = np.asarray(overlap["novel_candidate_mask"], dtype=bool)
        dev_metrics["novel_candidate_subset"] = summarize_predictions(
            [row for row, keep in zip(dev_rows, novel_mask) if keep],
            dev_margins[model_name][novel_mask], args.seed + 3, args.bootstrap,
            include_scenarios=False)

        if args.skip_permutation_control:
            permuted_metrics = {"skipped": True}
        else:
            permuted_rows, flips = permute_orientations_by_scenario(train_rows, args.seed + 1000)
            permuted_margin, _, _ = grouped_oof(
                model_name, permuted_rows, args.seed + 2000, args.folds)
            permutation_margins[model_name] = permuted_margin
            permuted_metrics = summarize_predictions(
                permuted_rows, permuted_margin, args.seed + 3000, args.bootstrap)
            permuted_metrics["flipped_scenarios"] = sorted(
                scenario for scenario, flip in flips.items() if flip)
        metrics[model_name] = {
            "train_grouped": train_metrics,
            "dev": dev_metrics,
            "permutation_train_grouped": permuted_metrics,
        }

        model_path = args.out / f"{model_name}.joblib"
        joblib.dump(final_model, model_path)
        write_json(args.out / f"{model_name}_diagnostics.json",
                   model_diagnostics(final_model))

    selected_model = min(MODEL_NAMES, key=lambda name: (
        -metrics[name]["train_grouped"]["macro_scenario_accuracy"],
        -metrics[name]["train_grouped"]["pairwise_accuracy"],
        -metrics[name]["train_grouped"]["coverage"],
        MODEL_PRIORITY[name]))

    write_jsonl(args.out / "train_grouped_predictions.jsonl", prediction_rows(
        train_rows, train_margins, train_fold_ids))
    write_jsonl(args.out / "dev_predictions.jsonl", prediction_rows(dev_rows, dev_margins))
    if not args.skip_permutation_control:
        permuted_rows, _ = permute_orientations_by_scenario(train_rows, args.seed + 1000)
        write_jsonl(args.out / "permutation_train_grouped_predictions.jsonl",
                    prediction_rows(permuted_rows, permutation_margins))
    metrics["model_selection"] = {
        "selected_model": selected_model,
        "criterion": "highest train-grouped macro scenario accuracy, then micro, coverage, simplicity",
        "dev_used_for_selection": False,
    }
    write_json(args.out / "metrics.json", metrics)

    validation = None
    if args.validate_top_choice:
        reference_rows = [json.loads(line) for line in
                          args.reference_data.read_text().splitlines() if line.strip()]
        validation = validate_top_choice(
            selected_model, dev_rows, dev_margins[selected_model], reference_rows,
            args.out / "scip_top_choice", args.validation_timeout, args.validation_limit)
    negative = negative_findings(metrics, overlap, selected_model, data_audit)
    negative["independent_validation_run"] = validation is not None
    if validation is not None:
        negative["top_choice_independent_pass_rate"] = validation["pass_rate"]
    write_json(args.out / "negative_results.json", negative)

    config = {
        "pilot": "pairwise_repair_ranker_v0.1",
        "seed": args.seed,
        "folds": args.folds,
        "bootstrap_replicates": args.bootstrap,
        "length_matched_relative_char_threshold": args.length_matched_threshold,
        "data": str(args.data),
        "data_sha256": data_audit["sha256"],
        "deduplicated_data_sha256": data_audit["canonical_deduplicated_sha256"],
        "reference_data_for_evaluation_only": str(args.reference_data),
        "reference_data_sha256": sha256_bytes(args.reference_data.read_bytes()),
        "allowed_inputs": ["prompt", "chosen/rejected code",
                           "optional allowlisted structured execution fields"],
        "forbidden_features": ["source", "public answer/reference objective", "scenario_id",
                               "chosen/rejected label", "mutant", "split", "pair_id"],
        "metadata_use": "scenario_id only for grouping/aggregation; source/mutant only for post-hoc strata",
        "tfidf": {"candidate_code_only": True, "analyzer": "word", "ngram_range": [1, 2],
                  "min_df": 2, "max_features": 20000, "sublinear_tf": True, "norm": "l2"},
        "classifier": {"type": "LogisticRegression", "C": 1.0, "solver": "liblinear",
                       "dual": "tfidf only", "fit_intercept": False, "max_iter": 2000},
        "pairwise_symmetry": "chosen-minus-rejected features with both orientations; no intercept",
        "coverage": "nonzero margin / all pairs; zero margin abstains",
        "permutation_control": not args.skip_permutation_control,
        "top_choice_validation_requested": args.validate_top_choice,
        "validation_timeout_s": args.validation_timeout,
        "validation_limit": args.validation_limit,
        "selected_model": selected_model,
        "python": sys.version,
        "numpy": np.__version__,
        "sklearn": sklearn.__version__,
        "implementation_sha256": {
            "ora_agent/repair_features.py": sha256_bytes(
                (ROOT / "ora_agent/repair_features.py").read_bytes()),
            "scripts/pairwise_repair_ranker.py": sha256_bytes(Path(__file__).read_bytes()),
        },
        "no_external_api_or_llm": True,
        "natural_heldout": False,
        "pipeline_files_modified": False,
        "intended_future_position": "after candidate generation, before deterministic audit",
        "controller_actions_trained": False,
        "scip_or_witness_replaced": False,
        "manifest_excludes": ["run.log (tee is still being written)"],
    }
    write_json(args.out / "config.json", config)
    report = render_report(data_audit, metrics, selected_model, negative, validation)
    (args.out / "report.md").write_text(report)

    manifest = {}
    for path in sorted(args.out.iterdir()):
        if path.is_file() and path.name not in ("manifest.json", "run.log"):
            manifest[path.name] = {"sha256": sha256_bytes(path.read_bytes()),
                                   "bytes": path.stat().st_size}
    write_json(args.out / "manifest.json", manifest)
    print(json.dumps({
        "raw_pairs": data_audit["raw_pairs"],
        "deduplicated_pairs": data_audit["deduplicated_pairs"],
        "train_pairs": len(train_rows), "dev_pairs": len(dev_rows),
        "selected_model": selected_model,
        "models": {name: {
            "train_macro": metrics[name]["train_grouped"]["macro_scenario_accuracy"],
            "dev_micro": metrics[name]["dev"]["pairwise_accuracy"],
            "dev_macro": metrics[name]["dev"]["macro_scenario_accuracy"],
            "dev_coverage": metrics[name]["dev"]["coverage"],
        } for name in MODEL_NAMES},
        "top_choice_validation": None if validation is None else {
            "attempted": validation["attempted"],
            "independent_pass": validation["independent_pass"],
            "pass_rate": validation["pass_rate"],
        },
        "graph_pilot_gate_passed": negative["graph_pilot_gate_passed"],
        "out": str(args.out),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
