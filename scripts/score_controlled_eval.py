#!/usr/bin/env python3
"""Score controlled-eval results against labels.json (task book 2.5).

Reads work/controlled_eval/*/result.json (produced by
scripts/run_controlled_eval.py) and controlled/<problem>/labels.json
(evaluation side only — never fed to any worker).

Metrics:
- correct/equivalent artifacts: false positives = CONFIRMED
  semantic/implementation findings (expected 0); suspected tracked
  separately.
- mutants: detection = exists a confirmed finding whose text hits
  labels.detection_keywords (keywords are hints; full finding text is
  printed for manual review). Localization correctness is left blank for
  human review.
- repair: success = witness PASS after patch; regression = witness still
  FAIL or verify_fix reports confirmed_regressions.
- full vs blind detection comparison (input control, 2.3): no winner is
  assumed a priori.

Writes runs/controlled_eval/summary.md + summary.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ORA_ROOT = Path(__file__).resolve().parents[1]
CONTROLLED = ORA_ROOT / "controlled"
WORK = ORA_ROOT / "work" / "controlled_eval"
OUT = ORA_ROOT / "runs" / "controlled_eval"

FP_PROBLEM_TYPES = ("semantic", "implementation")


def load_labels(problem: str) -> dict:
    return json.loads((CONTROLLED / problem / "labels.json").read_text())


def confirmed_findings(result: dict) -> list[dict]:
    return [f for f in (result.get("open_findings") or [])
            if f.get("status") == "confirmed"]


def suspected_findings(result: dict) -> list[dict]:
    return [f for f in (result.get("open_findings") or [])
            if f.get("status") == "suspected"]


def keyword_hit(finding: dict, keywords: list[str]) -> bool:
    blob = json.dumps(finding, ensure_ascii=False)
    return any(k in blob for k in keywords)


def score_artifact(result: dict, labels: dict) -> dict:
    aid = result["aid"]
    meta = labels["artifacts"][aid]
    row = {
        "problem": result["problem"], "aid": aid, "kind": meta["kind"],
        "mutation_type": meta.get("mutation_type"),
        "expected_witness": meta.get("expected_witness"),
        "error": result.get("error"),
        "n_confirmed": 0, "n_suspected": 0,
        "false_positive_confirmed": 0, "false_positive_suspected": 0,
        "detected": None, "detected_by": [],
        "confirmed_findings_text": [],
        "localization_correct": None,   # manual review, to be filled
        "usage": result.get("usage"), "wall_time_s": result.get("wall_time_s"),
    }
    conf = confirmed_findings(result)
    susp = suspected_findings(result)
    row["n_confirmed"] = len(conf)
    row["n_suspected"] = len(susp)
    row["confirmed_findings_text"] = [
        {"finding_id": f["finding_id"], "problem_type": f["problem_type"],
         "detail": f["detail"]} for f in conf]

    if meta["kind"] in ("correct", "equivalent"):
        row["false_positive_confirmed"] = sum(
            1 for f in conf if f.get("problem_type") in FP_PROBLEM_TYPES)
        row["false_positive_suspected"] = sum(
            1 for f in susp if f.get("problem_type") in FP_PROBLEM_TYPES)
    elif meta["kind"] == "mutant":
        kws = meta.get("detection_keywords") or []
        hits = [f["finding_id"] for f in conf if keyword_hit(f, kws)]
        row["detected"] = bool(hits)
        row["detected_by"] = hits

    repair = result.get("repair")
    if repair:
        w = repair.get("witness_after_patch") or {}
        vf = repair.get("verify_fix") or {}
        row["repair"] = {
            "finding_id": repair.get("finding_id"),
            "patch_applied": repair.get("patch_applied"),
            "witness_after_patch": w.get("verdict"),
            "repair_success": w.get("verdict") == "PASS",
            "verify_fix_repair_id": vf.get("repair_result_written"),
        }
    return row


def main() -> int:
    rows = []
    blind_rows = []
    for result_path in sorted(WORK.glob("*/result.json")):
        result = json.loads(result_path.read_text())
        labels = load_labels(result["problem"])
        if result.get("mode") == "blind":
            meta = labels["artifacts"][result["aid"]]
            conf = confirmed_findings(result)
            kws = meta.get("detection_keywords") or []
            hits = [f["finding_id"] for f in conf if keyword_hit(f, kws)]
            blind_rows.append({
                "problem": result["problem"], "aid": result["aid"],
                "n_confirmed": len(conf),
                "detected": bool(hits), "detected_by": hits,
                "confirmed_findings_text": [
                    {"finding_id": f["finding_id"],
                     "problem_type": f["problem_type"], "detail": f["detail"]}
                    for f in conf],
            })
            continue
        rows.append(score_artifact(result, labels))

    mutants = [r for r in rows if r["kind"] == "mutant"]
    negatives = [r for r in rows if r["kind"] in ("correct", "equivalent")]
    detected = sum(1 for r in mutants if r["detected"])
    fp_conf = sum(r["false_positive_confirmed"] for r in negatives)
    fp_susp = sum(r["false_positive_suspected"] for r in negatives)
    repairs = [r for r in mutants if r.get("repair")]
    repair_ok = sum(1 for r in repairs
                    if r["repair"].get("repair_success"))
    blind_detected = sum(1 for r in blind_rows if r["detected"])

    summary = {
        "n_artifacts": len(rows),
        "mutants": {"n": len(mutants), "detected_full": detected,
                    "detected_blind": blind_detected,
                    "n_blind": len(blind_rows)},
        "negatives": {"n": len(negatives),
                      "false_positives_confirmed": fp_conf,
                      "false_positives_suspected": fp_susp},
        "repairs": {"attempted": len(repairs), "succeeded": repair_ok},
        "rows": rows, "blind_rows": blind_rows,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n")

    lines = ["# Controlled eval summary (2.5b)", ""]
    lines.append(f"- mutants detected (full): {detected}/{len(mutants)}")
    lines.append(f"- mutants detected (blind): {blind_detected}/{len(blind_rows)}")
    lines.append(f"- false positives on correct/equivalent: "
                 f"confirmed={fp_conf}, suspected={fp_susp} "
                 f"(n={len(negatives)})")
    lines.append(f"- repairs succeeded: {repair_ok}/{len(repairs)}")
    lines.append("")
    lines.append("| artifact | kind | mutation | confirmed | suspected | "
                 "detected | repair witness | wall_s |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        rep = r.get("repair") or {}
        lines.append(
            f"| {r['problem']}/{r['aid']} | {r['kind']} | "
            f"{r.get('mutation_type') or '-'} | {r['n_confirmed']} | "
            f"{r['n_suspected']} | "
            f"{'-' if r['detected'] is None else r['detected']} | "
            f"{rep.get('witness_after_patch', '-')} | {r['wall_time_s']} |")
    lines.append("")
    lines.append("## Blind-mode detection (input control)")
    lines.append("")
    lines.append("| artifact | detected_blind | n_confirmed |")
    lines.append("|---|---|---|")
    for r in blind_rows:
        lines.append(f"| {r['problem']}/{r['aid']} | {r['detected']} | "
                     f"{r['n_confirmed']} |")
    lines.append("")
    lines.append("## Confirmed finding texts (for manual review of detection "
                 "and localization)")
    for r in rows + blind_rows:
        for f in r["confirmed_findings_text"]:
            lines.append(f"- {r['problem']}/{r['aid']} {f['finding_id']} "
                         f"[{f['problem_type']}]: {f['detail']}")
    lines.append("")
    lines.append("localization_correct: 待人工复核填写（summary.json 各行为 "
                 "null）。")
    (OUT / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:8]))
    print(f"\nwrote {OUT}/summary.md and summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
