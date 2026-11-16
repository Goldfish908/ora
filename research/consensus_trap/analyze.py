#!/usr/bin/env python3
"""Consensus-trap analysis: is objective-value consensus a reliable label-free reward?

Clusters the K sampled candidates of each problem by objective value (StarOR-style
consensus), then compares consensus-based rewards and majority voting against
semantic labels. No LLM calls.

Labels per candidate:
  correct   objective matches the reference and (when available) the witness re-verifies it
  phantom   objective matches or beats the reference but the witness finds violations
  wrong     objective present but does not match the reference
  fail      no objective (crash, timeout, infeasible, no output)
  unverified objective matches but the solution could not be re-verified (RetailOpt only)

Adapters:
  --k3 PATH          IndustryOR k3 analysis.json (objective labels only, no witness)
  --samples GLOB     jsonl rows with scenario_id, objective, grade, witness
                     (output of sample.py or any m1_pilot-format run; each row = one sample)

Usage:
  python3 research/consensus_trap/analyze.py --k3 work/industryor_k3_dev_v0.1/analysis.json
  python3 research/consensus_trap/analyze.py --samples "runs/consensus_trap/retail_k8/*.jsonl"
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

LABELS = ("correct", "phantom", "unverified", "wrong", "fail")


def label_retail(row: dict) -> str:
    objective = row.get("objective")
    if objective is None or row.get("exec_status") != "ok" or row.get("solver_status") == "infeasible":
        return "fail"
    grade = row.get("grade") or ""
    witness = row.get("witness")
    if grade in ("match", "better_than_reference"):
        if witness == "feasible":
            return "correct"
        if witness == "infeasible":
            return "phantom"
        return "unverified"
    return "wrong"


def load_samples(pattern: str) -> dict[str, list[dict]]:
    problems: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(glob.glob(pattern)):
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("thinking", "on") != "on":
                continue
            problems[row["scenario_id"]].append(
                {"objective": row.get("objective") if row.get("exec_status") == "ok" else None,
                 "label": label_retail(row)})
    return problems


def load_k3(path: str, abs_tol: float) -> dict[str, list[dict]]:
    problems: dict[str, list[dict]] = {}
    for result in json.loads(Path(path).read_text())["results"]:
        if result.get("status") != "completed":
            continue
        reference = result["reference"]
        rows = []
        for candidate in result["candidates"]:
            objective = candidate.get("objective")
            if objective is None:
                rows.append({"objective": None, "label": "fail"})
            else:
                rows.append({"objective": objective,
                             "label": "correct" if abs(objective - reference) <= abs_tol else "wrong"})
        problems[str(result["id"])] = rows
    return problems


def same_value(a: float, b: float, rel_tol: float) -> bool:
    return abs(a - b) <= rel_tol * max(abs(a), abs(b), 1.0)


def cluster(samples: list[dict], rel_tol: float) -> list[list[int]]:
    """Greedy clustering on sorted objectives; returns clusters of sample indices, largest first."""
    indexed = sorted((s["objective"], i) for i, s in enumerate(samples) if s["objective"] is not None)
    clusters: list[list[int]] = []
    anchor = None
    for value, index in indexed:
        if clusters and same_value(value, anchor, rel_tol):
            clusters[-1].append(index)
        else:
            clusters.append([index])
            anchor = value
    return sorted(clusters, key=lambda c: (-len(c), min(c)))


def problem_stats(samples: list[dict], rel_tol: float) -> dict:
    clusters = cluster(samples, rel_tol)
    k = len(samples)
    share = [0.0] * k
    for members in clusters:
        for index in members:
            share[index] = len(members) / k
    majority = clusters[0] if clusters else []
    tied = len(clusters) > 1 and len(clusters[1]) == len(majority)
    majority_labels = Counter(samples[i]["label"] for i in majority)
    majority_label = majority_labels.most_common(1)[0][0] if majority else "fail"
    in_majority = [False] * k
    for index in majority:
        in_majority[index] = len(majority) >= 2
    return {"k": k, "share": share, "in_majority": in_majority,
            "majority_size": len(majority), "majority_tied": tied,
            "majority_label": majority_label, "n_clusters": len(clusters),
            "labels": [s["label"] for s in samples]}


def auc(scores: list[float], positives: list[bool]) -> float | None:
    pos = [s for s, p in zip(scores, positives) if p]
    neg = [s for s, p in zip(scores, positives) if not p]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def summarize(stats: list[dict]) -> dict:
    n = len(stats)
    executed = [(st["share"][i], st["labels"][i], st["in_majority"][i])
                for st in stats for i in range(st["k"]) if st["labels"][i] != "fail"]
    base = Counter(label for _, label, _ in executed)
    in_majority = Counter(label for _, label, maj in executed if maj)
    total_exec = sum(base.values())
    total_maj = sum(in_majority.values())
    single = sum(st["labels"].count("correct") / st["k"] for st in stats) / n
    vote = sum(st["majority_label"] == "correct" for st in stats) / n
    oracle = sum("correct" in st["labels"] for st in stats) / n
    majority_counts = Counter(st["majority_label"] for st in stats)
    strong = [st for st in stats if st["majority_size"] >= max(2, math.ceil(st["k"] / 2))]
    strong_counts = Counter(st["majority_label"] for st in strong)
    return {
        "n_problems": n,
        "single_sample_correct": round(single, 4),
        "majority_vote_correct": round(vote, 4),
        "pass_at_k_correct": round(oracle, 4),
        "majority_cluster_label": {label: majority_counts.get(label, 0) for label in LABELS},
        "strong_majority_n": len(strong),
        "strong_majority_label": {label: strong_counts.get(label, 0) for label in LABELS},
        "executed_samples": total_exec,
        "label_rate_all_executed": {label: round(base.get(label, 0) / total_exec, 4) if total_exec else None
                                    for label in LABELS},
        "label_rate_in_majority": {label: round(in_majority.get(label, 0) / total_maj, 4) if total_maj else None
                                   for label in LABELS},
        "phantom_enrichment_in_majority": (
            round((in_majority.get("phantom", 0) / total_maj) / (base["phantom"] / total_exec), 3)
            if total_maj and base.get("phantom") else None),
        "auc_share_correct_vs_rest": auc([s for s, _, _ in executed], [l == "correct" for _, l, _ in executed]),
        "auc_share_correct_vs_phantom": auc([s for s, l, _ in executed if l in ("correct", "phantom")],
                                            [l == "correct" for _, l, _ in executed if l in ("correct", "phantom")]),
    }


def bootstrap(stats: list[dict], keys: list[str], reps: int, seed: int) -> dict:
    rng = random.Random(seed)
    draws = defaultdict(list)
    for _ in range(reps):
        sample = [rng.choice(stats) for _ in stats]
        summary = summarize(sample)
        for key in keys:
            if summary[key] is not None:
                draws[key].append(summary[key])
    out = {}
    for key, values in draws.items():
        values.sort()
        out[key] = [round(values[int(0.025 * len(values))], 4), round(values[int(0.975 * len(values)) - 1], 4)]
    return out


def k_curve(problems: dict[str, list[dict]], rel_tol: float, reps: int, seed: int) -> dict:
    rng = random.Random(seed)
    k_max = min(len(s) for s in problems.values())
    curve = {}
    for k in sorted({1, 2, 3, 4, 6, 8, 12, 16, k_max}):
        if k > k_max:
            continue
        vote = phantom_vote = 0.0
        for _ in range(reps):
            for samples in problems.values():
                stats = problem_stats(rng.sample(samples, k), rel_tol)
                vote += stats["majority_label"] == "correct"
                phantom_vote += stats["majority_label"] == "phantom"
        denom = reps * len(problems)
        curve[k] = {"majority_vote_correct": round(vote / denom, 4),
                    "majority_vote_phantom": round(phantom_vote / denom, 4)}
    return curve


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--k3")
    source.add_argument("--samples")
    parser.add_argument("--rel-tol", type=float, default=1e-4, help="objective clustering tolerance")
    parser.add_argument("--abs-tol", type=float, default=0.1, help="IndustryOR reference match tolerance")
    parser.add_argument("--min-k", type=int, default=2)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    problems = load_k3(args.k3, args.abs_tol) if args.k3 else load_samples(args.samples)
    problems = {pid: s for pid, s in problems.items() if len(s) >= args.min_k}
    if not problems:
        raise SystemExit("no problems with enough samples")
    k_hist = Counter(len(s) for s in problems.values())
    stats = [problem_stats(s, args.rel_tol) for s in problems.values()]
    report = {
        "source": args.k3 or args.samples,
        "rel_tol": args.rel_tol,
        "k_histogram": dict(sorted(k_hist.items())),
        "summary": summarize(stats),
        "bootstrap_95ci": bootstrap(stats, ["single_sample_correct", "majority_vote_correct",
                                            "phantom_enrichment_in_majority"], args.bootstrap, args.seed),
        "k_curve": k_curve(problems, args.rel_tol, 20, args.seed),
        "wrong_majorities": [
            {"problem": pid, "k": st["k"], "majority_size": st["majority_size"],
             "majority_label": st["majority_label"], "labels": dict(Counter(st["labels"]))}
            for pid, st in zip(problems, stats)
            if st["majority_label"] in ("phantom", "wrong") and st["majority_size"] >= 2],
    }
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
