#!/usr/bin/env python3
"""Analyze the feedback-enrichment ablation (A3).

Input: runs/m1_feedback_ablation/ablation.jsonl
  one record per (scenario_id, arm); arms: plain | enriched
  fields used: true_success, witness, grade, llm_s, llm_error

Reports, per arm:
  - repair rate (true_success) over the shared cell set
  - witness/grade outcome distribution
  - mean LLM seconds
and a paired McNemar-style breakdown (both / only-plain / only-enriched /
neither) over cells present in BOTH arms. Prints JSON to stdout.
"""
import json, sys
from collections import Counter, defaultdict
from pathlib import Path

ABL = Path(__file__).resolve().parent.parent / \
    "runs/m1_feedback_ablation/ablation.jsonl"


def main() -> None:
    recs = defaultdict(dict)  # sid -> arm -> record (first record wins)
    for line in ABL.open():
        r = json.loads(line)
        recs[r["scenario_id"]].setdefault(r["arm"], r)
    paired = {s: a for s, a in recs.items()
              if "plain" in a and "enriched" in a}
    out = {"cells_total": len(recs), "cells_paired": len(paired), "arms": {}}
    for arm in ("plain", "enriched"):
        sub = [a[arm] for a in paired.values()]
        n = len(sub)
        fixed = sum(1 for r in sub if r.get("true_success"))
        err = sum(1 for r in sub if r.get("llm_error"))
        wit = Counter(r.get("witness") for r in sub)
        grd = Counter(r.get("grade") for r in sub)
        lat = [r["llm_s"] for r in sub if r.get("llm_s")]
        fam = defaultdict(lambda: [0, 0])
        for r in sub:
            f = r["scenario_id"].split("_")[1]
            fam[f][1] += 1
            fam[f][0] += bool(r.get("true_success"))
        out["arms"][arm] = {
            "n": n, "fixed": fixed,
            "repair_rate": round(fixed / n, 4) if n else None,
            "llm_error": err,
            "witness": dict(wit), "grade": dict(grd),
            "mean_llm_s": round(sum(lat) / len(lat), 1) if lat else None,
            "per_family_fixed": {k: f"{a}/{b}" for k, (a, b)
                                 in sorted(fam.items())},
        }
    both = only_p = only_e = neither = 0
    for a in paired.values():
        p = bool(a["plain"].get("true_success"))
        e = bool(a["enriched"].get("true_success"))
        if p and e:
            both += 1
        elif p:
            only_p += 1
        elif e:
            only_e += 1
        else:
            neither += 1
    out["paired"] = {"both_fixed": both, "only_plain": only_p,
                     "only_enriched": only_e, "neither": neither}
    json.dump(out, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
