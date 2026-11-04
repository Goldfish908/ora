#!/usr/bin/env python3
"""P1' comparison: Open-Jev judge vs P0 Qwen-judge, witness-as-oracle.

Inputs:
  runs/judge_calib_p0/judge_p0.jsonl         (Qwen27B judge, VIOLATION YES/NO)
  runs/judge_calib_openjev/judge_openjev.jsonl (Open-Jev p_violation in [0,1])

Killer metric: phantom false-clear rate = P(judge says NO | witness=infeasible).
Also: false-positive on witness=feasible, AUC (Open-Jev probabilities),
threshold sweep for Open-Jev.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P0 = ROOT / "runs" / "judge_calib_p0" / "judge_p0.jsonl"
OJ = ROOT / "runs" / "judge_calib_openjev" / "judge_openjev.jsonl"


def load(p):
    out = {}
    for line in p.open():
        if line.strip():
            r = json.loads(line)
            out[(r["scenario_id"], r["thinking"], r["round"])] = r
    return out


def auc(pos, neg):
    # rank-based AUC: P(x_pos > x_neg)
    wins = tot = 0
    for a in pos:
        for b in neg:
            tot += 1
            wins += 1 if a > b else (0.5 if a == b else 0)
    return wins / tot if tot else float("nan")


def main():
    p0 = load(P0)
    oj = load(OJ)
    common = sorted(set(p0) & set(oj))
    print(f"P0 cells: {len(p0)}, Open-Jev cells: {len(oj)}, joined: {len(common)}")

    for name, get in [("P0 Qwen-judge", lambda k: p0[k]["judge_violation"] == "YES"),
                      ("Open-Jev@0.5", lambda k: (oj[k]["p_violation"] or 0) >= 0.5)]:
        tp = fn = fp = tn = 0
        for k in common:
            w = p0[k]["witness"]
            v = get(k)
            if w == "infeasible":
                tp, fn = tp + v, fn + (not v)
            else:
                fp += v
                tn += (not v)
        fc = fn / (tp + fn) if tp + fn else float("nan")  # phantom false-clear
        fpr = fp / (fp + tn) if fp + tn else float("nan")
        print(f"{name:14s}  phantom false-clear {fn}/{tp+fn} = {fc:.1%} | "
              f"false-positive {fp}/{fp+tn} = {fpr:.1%}")

    pos = [oj[k]["p_violation"] for k in common
           if p0[k]["witness"] == "infeasible" and oj[k]["p_violation"] is not None]
    neg = [oj[k]["p_violation"] for k in common
           if p0[k]["witness"] == "feasible" and oj[k]["p_violation"] is not None]
    print(f"Open-Jev AUC: {auc(pos, neg):.3f}  (n_pos={len(pos)}, n_neg={len(neg)})")

    print("\nOpen-Jev threshold sweep (phantom false-clear / false-positive):")
    for t in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        fn = fp = 0
        np_ = nn_ = 0
        for k in common:
            p = oj[k]["p_violation"]
            if p is None:
                continue
            if p0[k]["witness"] == "infeasible":
                np_ += 1
                fn += p < t
            else:
                nn_ += 1
                fp_ = p >= t
                fp += fp_
        print(f"  t={t:.1f}: false-clear {fn}/{np_} = {fn/np_:.1%} | "
              f"false-positive {fp}/{nn_} = {fp/nn_:.1%}")

    # latency
    lat = [oj[k]["latency_s"] for k in common if oj[k].get("latency_s")]
    if lat:
        lat.sort()
        print(f"\nOpen-Jev latency: median {lat[len(lat)//2]}s, "
              f"p90 {lat[int(len(lat)*0.9)]}s, n={len(lat)}")


if __name__ == "__main__":
    main()
