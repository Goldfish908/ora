"""Analyze P0 judge calibration output (runs/judge_calib_p0/judge_p0.jsonl).

Reports, against witness labels (the calibration oracle):
- overall confusion matrix (judge VIOLATION vs witness infeasible)
- phantom subset false-clear rate (grade looks fine, witness=infeasible,
  judge says NO violation) — the headline number
- true-success subset false-alarm rate (feasible & match, judge says YES)
- per-family breakdown
- confidence calibration buckets (does 0.9 confidence mean ~90% accuracy?)

Usage: python scripts/judge_calibration_p0_analyze.py [--file PATH]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "runs" / "judge_calib_p0" / "judge_p0.jsonl"


def family(sid: str) -> str:
    m = re.match(r"retail_(f\d+)", sid)
    return m.group(1) if m else "?"


def bucket(conf: float | None) -> str:
    if conf is None:
        return "n/a"
    if conf < 0.6:
        return "<0.6"
    if conf < 0.8:
        return "0.6-0.8"
    if conf < 0.9:
        return "0.8-0.9"
    return ">=0.9"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(DEFAULT))
    args = ap.parse_args()
    rows = [json.loads(l) for l in Path(args.file).open()]
    rows = [r for r in rows if r.get("judge_violation") in ("YES", "NO")]
    print(f"judged cells: {len(rows)}")

    tp = fp = tn = fn = 0  # positive = judge says VIOLATION: YES
    for r in rows:
        js = r["judge_violation"] == "YES"
        wt = r["witness"] == "infeasible"
        if js and wt:
            tp += 1
        elif js and not wt:
            fp += 1
        elif not js and wt:
            fn += 1
        else:
            tn += 1
    print(f"\n== overall confusion (positive = judge flags violation) ==")
    print(f"witness infeasible: caught {tp}, missed {fn}  (recall {tp/(tp+fn):.1%})"
          if tp + fn else "")
    print(f"witness feasible:   cleared {tn}, false-alarm {fp}  "
          f"(false-alarm rate {fp/(fp+tn):.1%})" if fp + tn else "")

    ph = [r for r in rows if r["witness"] == "infeasible"
          and r.get("grade") in ("match", "better_than_reference")]
    ph_cleared = sum(1 for r in ph if r["judge_violation"] == "NO")
    print(f"\n== phantom subset (looks-fine but infeasible): {len(ph)} ==")
    print(f"judge false-clear (said NO violation): {ph_cleared}/{len(ph)}"
          + (f" = {ph_cleared/len(ph):.1%}" if ph else ""))

    ts = [r for r in rows if r["witness"] == "feasible" and r.get("grade") == "match"]
    ts_alarm = sum(1 for r in ts if r["judge_violation"] == "YES")
    print(f"\n== true-success subset (feasible & match): {len(ts)} ==")
    print(f"judge false-alarm (said YES): {ts_alarm}/{len(ts)}"
          + (f" = {ts_alarm/len(ts):.1%}" if ts else ""))

    print("\n== per-family recall on witness-infeasible ==")
    fam: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        if r["witness"] == "infeasible":
            fam[family(r["scenario_id"])][0] += r["judge_violation"] == "YES"
            fam[family(r["scenario_id"])][1] += 1
    for f in sorted(fam):
        c, n = fam[f]
        print(f"  {f}: caught {c}/{n} = {c/n:.0%}")

    print("\n== confidence calibration (judge says NO violation = 'cleared') ==")
    cal: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        if r["judge_violation"] == "NO":
            ok = r["witness"] == "feasible"
            cal[bucket(r.get("judge_confidence"))][0] += ok
            cal[bucket(r.get("judge_confidence"))][1] += 1
    for b in ("<0.6", "0.6-0.8", "0.8-0.9", ">=0.9", "n/a"):
        if b in cal:
            ok, n = cal[b]
            print(f"  conf {b}: actually clean {ok}/{n} = {ok/n:.0%}")


if __name__ == "__main__":
    main()
