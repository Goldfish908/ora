#!/usr/bin/env python3
"""Report accepted GEPA candidates on both development and transfer selection sets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ora_agent.cleanroom_analysis import summarize_records
from ora_agent.oragentbench import read_json, write_json
from scripts.cleanroom_batch_report import add_cost, empty_cost
from scripts.cleanroom_experiment import digest

ROOT = Path(__file__).resolve().parents[1]


def proposal_history(run: Path) -> list[dict]:
    history = []
    for iteration in (run / "iterations").iterdir():
        meta_path = iteration / "meta.json"
        if not meta_path.exists():
            continue
        meta = read_json(meta_path)
        component = iteration / "components/conventions.txt"
        history.append({"iteration_id": meta.get("iteration_id", iteration.name),
                        "trace_i": meta.get("trace_i"), "accepted": meta.get("accepted"),
                        "candidate_idx": meta.get("candidate_idx"),
                        "parent_iteration_ids": meta.get("parent_iteration_ids", []),
                        "subsample_ids": meta.get("subsample_ids", []),
                        "subsample_scores_before": meta.get("subsample_scores_before", []),
                        "subsample_scores_after": meta.get("subsample_scores_after", []),
                        "avg_val_score": meta.get("avg_val_score"),
                        "metric_calls_to_discover": meta.get("metric_calls_to_discover"),
                        "candidate_sha256": digest(component.read_text()) if component.exists() else None,
                        "candidate_text_saved": component.exists()})
    return sorted(history, key=lambda row: row["trace_i"] if row["trace_i"] is not None else -1)


def evaluation_for_hash(run: Path, candidate_hash: str, task_ids: list[str]) -> dict:
    records, missing = [], []
    for task in task_ids:
        path = run / "rollouts" / candidate_hash / task / "attempt_0/record.json"
        if path.exists():
            records.append(read_json(path))
        else:
            missing.append(task)
    summary = summarize_records(records, expected_tasks=len(task_ids))
    summary["status"] = "complete" if not missing else "partial" if records else "not_run"
    summary["not_run_tasks"] = missing
    return summary


def build_analysis(run: Path) -> dict:
    result = read_json(run / "gepa_result.json")
    original = read_json(run / "analysis.json")
    dev_ids, transfer_ids = original["train_ids"], original["val_ids"]
    candidates = []
    for index, candidate in enumerate(result["candidates"]):
        candidate_hash = digest(candidate["conventions"])
        records = {}
        for split, task_ids in (("dev", dev_ids), ("transfer", transfer_ids)):
            split_records = [read_json(run / "rollouts" / candidate_hash / task / "attempt_0/record.json")
                             for task in task_ids]
            records[split] = summarize_records(split_records, expected_tasks=len(task_ids))
        cost = empty_cost()
        add_cost(cost, records["dev"]["cost"])
        add_cost(cost, records["transfer"]["cost"])
        meta = None
        for iteration in (run / "iterations").iterdir():
            component = iteration / "components/conventions.txt"
            if component.exists() and digest(component.read_text()) == candidate_hash:
                meta = read_json(iteration / "meta.json")
                break
        candidates.append({"candidate_idx": index, "candidate_sha256": candidate_hash,
                           "parents": result["parents"][index], "accepted_meta": meta,
                           "dev": records["dev"], "transfer": records["transfer"], "cost": cost})
    history = proposal_history(run)
    for row in history:
        if row["candidate_sha256"]:
            row["dev_evaluation"] = evaluation_for_hash(run, row["candidate_sha256"], dev_ids)
            row["transfer_evaluation"] = evaluation_for_hash(run, row["candidate_sha256"], transfer_ids)
    return {"candidates": candidates, "dev_ids": dev_ids, "transfer_ids": transfer_ids,
            "proposal_history": history,
            "n_rejected_proposals": sum(row["accepted"] is False for row in history),
            "total_metric_calls": original["total_metric_calls"],
            "wall_seconds": original["wall_seconds"],
            "implementation_sha256": hashlib.sha256(
                (run / "implementation.json").read_bytes()).hexdigest(),
            "evaluation_boundary": "Both sets participated in GEPA train/validation. Neither is a final held-out set."}


def write_figure(analysis: dict, out: Path) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    plt.rcParams.update({"font.family": "serif", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.2})
    candidates = analysis["candidates"]
    labels = ["Seed" if row["candidate_idx"] == 0 else f"C{row['candidate_idx']}" for row in candidates]
    x = np.arange(len(candidates))
    width = 0.2
    colors = ("#3569a8", "#4b9b74", "#d28b36", "#8b8f98")
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.1))
    for axis, split, title in zip(axes, ("dev", "transfer"), ("Development", "Transfer")):
        for index, metric in enumerate(("proxy_match", "true_correct", "phantom_proxy", "unknown")):
            values = [row[split][metric] for row in candidates]
            bars = axis.bar(x + (index - 1.5) * width, values, width, label=metric.replace("_", " "),
                            color=colors[index])
            axis.bar_label(bars, padding=2, fontsize=8)
        axis.set_title(f"{title} (n={len(analysis[split + '_ids'])})")
        axis.set_xticks(x, labels)
        axis.set_ylabel("Tasks")
        axis.set_ylim(bottom=0)
        axis.grid(axis="x", visible=False)
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    fig.suptitle("GEPA candidates: proxy and independent official outcomes")
    fig.text(0.5, 0.01, f"Selection sets; {analysis['n_rejected_proposals']} rejected proposals; not held-out",
             ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(out / "gepa_candidates.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    run = (ROOT / args.run_dir).resolve()
    out = (ROOT / args.out).resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError("report output directory must be new")
    out.mkdir(parents=True)
    analysis = build_analysis(run)
    write_json(out / "candidate_analysis.json", analysis)
    write_figure(analysis, out)
    lines = ["# GEPA candidate report", "", analysis["evaluation_boundary"], "",
             "| Candidate | Accepted | Dev proxy | Dev true | Transfer proxy | Transfer true | Phantom | UNKNOWN | Tokens |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in analysis["candidates"]:
        dev, transfer = row["dev"], row["transfer"]
        accepted = row["accepted_meta"].get("accepted") if row["accepted_meta"] else None
        lines.append(f"| {row['candidate_idx']} | {accepted} | {dev['proxy_match']} | {dev['true_correct']} | "
                     f"{transfer['proxy_match']} | {transfer['true_correct']} | {transfer['phantom_proxy']} | "
                     f"{transfer['unknown']} | {row['cost']['total_tokens']} |")
    lines += ["", "## Proposal history", "",
              "| Iteration | Accepted | Proxy after | Dev true | Dev failures | Transfer |",
              "|---|---|---|---:|---|---|"]
    for row in analysis["proposal_history"]:
        dev = row.get("dev_evaluation")
        transfer = row.get("transfer_evaluation")
        failures = dev.get("failure_counts", {}) if dev else {}
        transfer_text = transfer["status"] if transfer else "not_recorded"
        lines.append(f"| {row['iteration_id']} | {row['accepted']} | {row['subsample_scores_after']} | "
                     f"{dev['true_correct'] if dev else 'not_recorded'} | {failures} | {transfer_text} |")
    lines += ["", f"Rejected proposals: {analysis['n_rejected_proposals']}. "
              "Rejected specifications are excluded from the accepted-candidate registry even when iteration text is saved."]
    if len(analysis["candidates"]) == 1:
        lines += ["", "Negative review: no non-seed candidate was accepted. Do not claim a GEPA gain or promote memory as a positive result; inspect proposal history and seed failure classes."]
    lines += ["", f"Total GEPA metric calls: {analysis['total_metric_calls']}. "
              "Candidate costs are token sums across the two selection sets; implementation and per-task records are retained."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(analysis, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
