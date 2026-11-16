#!/usr/bin/env python3
"""Compare an official Open-Jev checkpoint and an adapted checkpoint on fixed pairs."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pair_id(row: dict) -> str:
    suffix = row["id"].rsplit(":", 1)
    if len(suffix) != 2 or suffix[1] not in {"chosen", "rejected"}:
        raise ValueError(f"invalid pair identifier: {row['id']}")
    return suffix[0]


def pairwise_metrics(predictions: list[dict]) -> dict:
    pairs = defaultdict(dict)
    for row in predictions:
        side = row["id"].rsplit(":", 1)[-1]
        if side not in {"chosen", "rejected"}:
            raise ValueError(f"invalid candidate side in {row['id']}")
        key = pair_id(row)
        if side in pairs[key]:
            raise ValueError(f"duplicate {side} for {key}")
        pairs[key][side] = row
    if not pairs:
        raise ValueError("no candidate pairs to evaluate")
    outcomes = []
    for key, pair in pairs.items():
        if set(pair) != {"chosen", "rejected"}:
            raise ValueError(f"incomplete candidate pair: {key}")
        chosen, rejected = pair["chosen"], pair["rejected"]
        margin = chosen["scores"][1] - chosen["scores"][0] - rejected["scores"][1] + rejected["scores"][0]
        outcomes.append({"pair_id": key, "group_id": chosen["group_id"],
                         "margin": margin, "correct": margin > 0})
    scenario_scores = {}
    for outcome in outcomes:
        scenario_scores.setdefault(outcome["group_id"], []).append(outcome["correct"])
    return {
        "pairs": len(outcomes),
        "scenarios": len(scenario_scores),
        "correct": sum(item["correct"] for item in outcomes),
        "pairwise_accuracy": sum(item["correct"] for item in outcomes) / len(outcomes),
        "macro_scenario_accuracy": sum(sum(group) / len(group) for group in scenario_scores.values())
                                    / len(scenario_scores),
        "nonzero_margin_coverage": sum(item["margin"] != 0 for item in outcomes) / len(outcomes),
        "total_input_tokens": sum(row["input_tokens"] for row in predictions),
        "total_latency_seconds": sum(row["latency_seconds"] for row in predictions),
        "outcomes": outcomes,
    }


def evaluate_model(checkpoint: Path, rows: list[dict], device: str, output: Path) -> list[dict]:
    import gc
    import torch

    from jev.model import DecisionModel

    model = DecisionModel.load(checkpoint, device=device)
    output.parent.mkdir(parents=True, exist_ok=True)
    predictions = []
    with output.open("w") as handle, torch.inference_mode():
        for index, row in enumerate(rows, 1):
            torch.cuda.synchronize()
            started = time.perf_counter()
            scores = model([row])[0].float().cpu().tolist()
            torch.cuda.synchronize()
            prediction = {"id": row["id"], "group_id": row["group_id"],
                          "scores": scores, "target": row["target"],
                          "input_tokens": model.last_input_tokens,
                          "latency_seconds": time.perf_counter() - started}
            handle.write(json.dumps(prediction) + "\n")
            handle.flush()
            predictions.append(prediction)
            if index % 10 == 0 or index == len(rows):
                print(json.dumps({"checkpoint": str(checkpoint), "evaluated": index,
                                  "total": len(rows)}), flush=True)
    del model
    gc.collect()
    torch.cuda.empty_cache()
    return predictions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--split", default="test", choices=("test", "ood"))
    parser.add_argument("--device", default="cuda:1")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    data_path = Path(args.data)
    rows = [json.loads(line) for line in data_path.read_text().splitlines() if line.strip()]
    if any(row["split"] != args.split for row in rows):
        raise ValueError("data split does not match requested evaluation split")
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        raise ValueError("no evaluation rows")
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    baseline = evaluate_model(Path(args.baseline), rows, args.device,
                              outdir / "baseline_predictions.jsonl")
    trained = evaluate_model(Path(args.checkpoint), rows, args.device,
                             outdir / "trained_predictions.jsonl")
    result = {
        "scope": "historical development diagnostic, not frozen/sealed evaluation",
        "split": args.split,
        "baseline": pairwise_metrics(baseline),
        "trained": pairwise_metrics(trained),
        "checkpoint": str(args.checkpoint),
        "baseline_checkpoint": str(args.baseline),
        "data_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "device": args.device,
        "limitations": ["Small, previously exposed development cohort",
                        "Pairwise scores do not establish end-to-end repair uplift",
                        "Non-LLM baselines use a different cleaning protocol"],
    }
    (outdir / "metrics.json").write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({"baseline": result["baseline"], "trained": result["trained"]}, indent=1))


if __name__ == "__main__":
    main()
