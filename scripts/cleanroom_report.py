#!/usr/bin/env python3
"""Align clean-room direct, residual-DAG and memory results without pooling coverage."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ora_agent.oragentbench import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]


def curve_row(curve: dict, arm: str) -> dict:
    return {"arm": arm, "candidate_idx": curve["candidate_idx"], "n": curve["n"],
            "proxy_match": curve["proxy_match"], "true_correct": curve["true_correct"],
            "phantom_proxy": curve["phantom_proxy"], "unknown": curve["unknown"],
            "mean_quality": curve["mean_quality"], "coverage": "complete_validation"}


def repair_row(path: Path) -> dict:
    result = read_json(path)
    before = result.get("before", {})
    after = result.get("after", {})
    record = result.get("record", {})
    re_eval = path.parent / "acceptance_re_eval.json"
    acceptance = read_json(re_eval) if re_eval.exists() else result
    return {"arm": "B2_residual_dag", "task": record.get("task"),
            "candidate_sha256": record.get("candidate_sha256"),
            "before": before, "after": after,
            "true_correct": record.get("true_correct"), "quality": record.get("quality"),
            "objective": record.get("objective"), "status": acceptance.get("status"),
            "edge_accepted": acceptance.get("edge_accepted"),
            "final_accept": acceptance.get("final_accept"),
            "source": str(path)}


def build(gepa_run: Path, repair_paths: list[Path], memory_direct: Path | None, out: Path) -> dict:
    analysis = read_json(gepa_run / "analysis.json")
    curves = analysis["curves"]
    best = max(curves, key=lambda row: row["official_proxy_mean"])
    direct = [curve_row(curves[0], "B0_empty_specification"), curve_row(best, "B1_gepa_specification")]
    repairs = [repair_row(path) for path in repair_paths]
    memory = None
    if memory_direct is not None:
        record = read_json(memory_direct)
        memory = {"arm": "B3_verified_memory", "task": record["task"], "n": 1,
                  "true_correct": record["true_correct"], "quality": record["quality"],
                  "candidate_sha256": record["candidate_sha256"], "source": str(memory_direct)}
    status = {"direct": direct, "residual_dag": repairs,
            "memory": memory if memory is not None else {"arm": "B3_verified_memory", "status": "not_run"}}
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / "summary.json", status)
    lines = ["# Clean-room result alignment", "",
             "Direct specification and residual-DAG results are reported separately. Missing arms are not_run, never zero-filled.", "",
             "| Arm | Candidate | N | Proxy | True | Phantom | UNKNOWN | Mean quality |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in direct:
        lines.append(f"| {row['arm']} | {row['candidate_idx']} | {row['n']} | {row['proxy_match']} | "
                     f"{row['true_correct']} | {row['phantom_proxy']} | {row['unknown']} | {row['mean_quality']:.4f} |")
    lines += ["", "## Residual DAG", "",
              "| Task | Status | Before | After | Official true | Quality |",
              "|---|---|---|---|---:|---:|"]
    for row in repairs:
        lines.append(f"| {row['task']} | {row['status']} | `{row['before']}` | `{row['after']}` | "
                     f"{row['true_correct']} | {row['quality']:.4f} |")
    lines += ["", "## Memory", ""]
    if memory is None:
        lines.append("B3: not_run")
    else:
        lines.append(f"B3: `{memory['task']}` true={memory['true_correct']} quality={memory['quality']:.4f}")
    lines += ["", "B2 rows are per-task outcomes, not full-validation accuracy. B1/B3 reuse requires a separately evaluated subsequent task set.", ""]
    (out / "report.md").write_text("\n".join(lines))
    return status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gepa-run", required=True)
    parser.add_argument("--repair", action="append", default=[])
    parser.add_argument("--memory-direct")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = build((ROOT / args.gepa_run).resolve(),
                   [(ROOT / path).resolve() for path in args.repair],
                   (ROOT / args.memory_direct).resolve() if args.memory_direct else None,
                   (ROOT / args.out).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
