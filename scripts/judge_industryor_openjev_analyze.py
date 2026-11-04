#!/usr/bin/env python3
"""Analyze Open-Jev judge on IndustryOR cells (oracle = en_answer tolerance)."""
import json
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "runs" / "industryor" / "industryor_judge_openjev.jsonl"


def auc(pos, neg):
    w = t = 0
    for a in pos:
        for b in neg:
            t += 1
            w += 1 if a > b else (0.5 if a == b else 0)
    return w / t if t else float("nan")


rows = [json.loads(l) for l in P.open() if l.strip()]
rows = [r for r in rows if r["p_violation"] is not None]
pos = [r["p_violation"] for r in rows if r["wrong"]]      # 出解但目标值错 = 幻影
neg = [r["p_violation"] for r in rows if not r["wrong"]]  # 正确
print(f"n={len(rows)}  phantom(wrong)={len(pos)}  correct={len(neg)}")
print(f"mean p_viol: phantom={sum(pos)/len(pos):.4f}  correct={sum(neg)/len(neg):.4f}")
print(f"AUC = {auc(pos, neg):.3f}")
print("\nthreshold sweep (false-clear on phantoms / false-positive on correct):")
for t in (0.1, 0.2, 0.3, 0.5, 0.7, 0.9):
    fc = sum(1 for p in pos if p < t) / len(pos)
    fp = sum(1 for p in neg if p >= t) / len(neg)
    print(f"  t={t:.1f}: false-clear {fc:.1%} | false-positive {fp:.1%}")
print("\n按臂拆分 (t=0.5 误放行率):")
for arm in ("z0", "z1", "z2"):
    sub = [r for r in rows if r["arm"] == arm and r["wrong"]]
    if sub:
        fc = sum(1 for r in sub if r["p_violation"] < 0.5) / len(sub)
        print(f"  {arm}: phantom n={len(sub)}, false-clear {fc:.1%}")
lat = sorted(r["latency_s"] for r in rows)
print(f"\nlatency median {lat[len(lat)//2]}s p90 {lat[int(len(lat)*0.9)]}s")
