#!/usr/bin/env python3
"""Analyze the four-arm MAMO cold-start ablation."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.memory_witness_analyze import exact_p


def load(path: str) -> tuple[list[dict], dict]:
    records = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    last = {}
    for r in records:
        if r["id"] not in last or r["round"] > last[r["id"]]["round"]:
            last[r["id"]] = r
    return records, last


def correct(r: dict, audit: dict | None = None) -> bool:
    reference = (audit or {}).get(r["id"], r["reference"])
    return r.get("objective") is not None and abs(r["objective"] - reference) <= 0.1


def summarize(records: list[dict], last: dict, audit: dict | None = None) -> dict:
    return {"n": len(last), "correct": sum(correct(r, audit) for r in last.values()),
            "accuracy": sum(correct(r, audit) for r in last.values()) / len(last),
            "exec_ok": sum(r.get("exec_status") == "ok" for r in last.values()),
            "llm_calls": len(records),
            "llm_latency_s": round(sum(r.get("llm_latency_s", 0) for r in records), 1),
            "guard_blocks": sum(r.get("exec_status") == "witness_block" for r in records),
            "witness_status": dict(Counter(r.get("witness", "not_used") for r in last.values()))}


def compare(base: dict, other: dict, audit: dict | None = None) -> dict:
    other_only = sum(correct(other[k], audit) and not correct(base[k], audit) for k in base)
    base_only = sum(correct(base[k], audit) and not correct(other[k], audit) for k in base)
    return {"other_only": other_only, "base_only": base_only,
            "mcnemar_p": exact_p(other_only, base_only)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a0", required=True)
    ap.add_argument("--a1", required=True)
    ap.add_argument("--a2", required=True)
    ap.add_argument("--a4", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--figure")
    ap.add_argument("--tsp-audit")
    ap.add_argument("--a4-baseline")
    ap.add_argument("--a4-calls")
    ap.add_argument("--title")
    ap.add_argument("--note")
    args = ap.parse_args()
    audit = None
    if args.tsp_audit:
        audit = {r["id"]: r["independent_optimum"]
                 for r in json.loads(Path(args.tsp_audit).read_text())}
    arms = {}
    for name, path in (("A0_no_prior", args.a0), ("A1_soft_memory", args.a1),
                       ("A2_direct_old_witness", args.a2), ("A4_cold_start", args.a4)):
        records, last = load(path)
        arms[name] = {"records": records, "last": last, "metrics": summarize(records, last)}
    if args.a4_baseline and args.a4_calls:
        baseline_records = [json.loads(l) for l in Path(args.a4_baseline).read_text().splitlines() if l.strip()]
        call_records = [json.loads(l) for l in Path(args.a4_calls).read_text().splitlines() if l.strip()]
        initial_calls = len(baseline_records)
        repair_calls = len(call_records)
        initial_latency = sum(r.get("llm_latency_s", 0) for r in baseline_records)
        repair_latency = sum(r.get("llm_latency_s", 0) for r in call_records)
        arms["A4_cold_start"]["metrics"].update({
            "llm_calls": initial_calls + repair_calls,
            "llm_latency_s": round(initial_latency + repair_latency, 1),
            "initial_llm_calls": initial_calls,
            "repair_llm_calls": repair_calls,
            "initial_llm_latency_s": round(initial_latency, 1),
            "repair_llm_latency_s": round(repair_latency, 1),
            "repair_usage": {k: sum((r.get("usage") or {}).get(k, 0) for r in call_records)
                             for k in ("prompt_tokens", "completion_tokens", "total_tokens")}})
    result = {"arms": {k: v["metrics"] for k, v in arms.items()}, "paired_vs_a4": {}}
    for name in ("A0_no_prior", "A1_soft_memory", "A2_direct_old_witness"):
        result["paired_vs_a4"][name] = compare(arms[name]["last"], arms["A4_cold_start"]["last"])
    if audit:
        result["independent_tsp_audit"] = {
            "arms": {k: summarize(v["records"], v["last"], audit) for k, v in arms.items()},
            "paired_vs_a4": {name: compare(arms[name]["last"], arms["A4_cold_start"]["last"], audit)
                             for name in ("A0_no_prior", "A1_soft_memory", "A2_direct_old_witness")}}
        if args.a4_baseline and args.a4_calls:
            result["independent_tsp_audit"]["arms"]["A4_cold_start"].update({
                k: arms["A4_cold_start"]["metrics"][k] for k in
                ("llm_calls", "llm_latency_s", "initial_llm_calls", "repair_llm_calls",
                 "initial_llm_latency_s", "repair_llm_latency_s", "repair_usage")})
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if args.figure:
        import matplotlib.pyplot as plt
        labels = ["No prior", "Soft memory", "Direct old\nwitness", "Cold start"]
        values = [100 * arms[k]["metrics"]["accuracy"] for k in arms]
        fig, ax = plt.subplots(figsize=(7.5, 4))
        bars = ax.bar(labels, values, color=["#8c9bab", "#5b8e7d", "#c47f5a", "#2374ab"])
        ax.set_ylim(0, 112)
        ax.set_ylabel("Objective accuracy (%)")
        ax.set_title(args.title or "MAMO validation: four-arm cold-start ablation (seed 42)")
        ax.grid(axis="y", alpha=0.2)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, val + 2, f"{val:.1f}%",
                    ha="center", fontsize=10)
        blocks = arms["A4_cold_start"]["metrics"]["guard_blocks"]
        note = args.note or (f"A4 online guard activations: {blocks}. Small n; "
                             "use fixed-code replays for guard attribution.")
        fig.text(0.5, 0.005, note, ha="center", fontsize=8)
        fig.tight_layout(rect=[0, 0.04, 1, 1])
        fig.savefig(args.figure, dpi=180, bbox_inches="tight")
        plt.close(fig)


if __name__ == "__main__":
    main()
