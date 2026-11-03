#!/usr/bin/env python3
"""B8 analysis: champion full-190 results vs the hand-distilled P3 baseline,
per business family, with the F5-F8 held-out aggregate the life/death
criterion needs.

Usage:
  python3 scripts/evo_full190_analyze.py --gen 3 --gid g3_x_...

Reads:
  runs/evo/gen{G}_full190/m1_pilot_schema_sol_full190_{GID}_v*.jsonl
  runs/m1_pilot_priors3/m1_pilot_schema_sol_p3_v*.jsonl   (P3 baseline)

Scoring: first complete trajectory per scenario (dedup), thinking==on only,
true_success = witness=="feasible" and grade=="match" (derived when absent).
"""
from __future__ import annotations

import argparse, glob, json, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAMS = [f"f{i}" for i in range(1, 9)]


def load(pattern: str) -> dict:
    recs: dict[str, dict] = {}
    for fp in sorted(glob.glob(str(ROOT / pattern))):
        for line in open(fp):
            r = json.loads(line)
            if r.get("thinking") != "on":
                continue
            recs.setdefault(r["scenario_id"], r)
    return recs


def stats(recs: dict) -> dict:
    fam = defaultdict(lambda: {"n": 0, "succ": 0, "ph": 0})
    for sid, r in recs.items():
        f = sid.split("_")[1]
        st = fam[f]
        st["n"] += 1
        ts = r.get("true_success")
        if ts is None:
            ts = (r.get("witness") == "feasible"
                  and r.get("grade") == "match")
        st["succ"] += bool(ts)
        st["ph"] += (r.get("witness") == "infeasible"
                     and r.get("grade") == "better_than_reference")
    return fam


def agg(fam: dict, keys: list[str]) -> tuple[int, int]:
    n = sum(fam[k]["n"] for k in keys)
    s = sum(fam[k]["succ"] for k in keys)
    return s, n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True)
    ap.add_argument("--gid", required=True)
    args = ap.parse_args()

    champ = load(f"runs/evo/gen{args.gen}_full190/"
                 f"m1_pilot_schema_sol_full190_{args.gid}_v*.jsonl")
    base = load("runs/m1_pilot_priors3/m1_pilot_schema_sol_p3_v*.jsonl")
    assert len(champ) == 190, f"champion coverage {len(champ)} != 190"
    assert len(base) == 190, f"P3 coverage {len(base)} != 190"

    cf, bf = stats(champ), stats(base)
    print(f"## 全量 190 题:{args.gid} (gen{args.gen}) vs P3 基线\n")
    print("| 族 | n | 冠军 | P3 | Δ |")
    print("|---|---|---|---|---|")
    for f in FAMS:
        c, b = cf[f], bf[f]
        cr = c["succ"] / c["n"] if c["n"] else 0
        br = b["succ"] / b["n"] if b["n"] else 0
        print(f"| {f} | {c['n']} | {c['succ']}/{c['n']} ({cr:.1%}) "
              f"| {b['succ']}/{b['n']} ({br:.1%}) | {cr-br:+.1%} |")
    for label, keys in (("F1-F4(进化可见)", FAMS[:4]),
                        ("F5-F8(留出)", FAMS[4:]),
                        ("总计", FAMS)):
        cs, cn = agg(cf, keys)
        bs, bn = agg(bf, keys)
        print(f"| **{label}** | {cn} | **{cs}/{cn} ({cs/cn:.1%})** "
              f"| **{bs}/{bn} ({bs/bn:.1%})** | **{cs/cn-bs/bn:+.1%}** |")
    held_cs, held_cn = agg(cf, FAMS[4:])
    held_bs, _ = agg(bf, FAMS[4:])
    print(f"\n留出族判据:冠军 F5-F8 {held_cs/held_cn:.1%} vs "
          f"P3 {held_bs/held_cn:.1%},阈值 ≥ "
          f"{held_bs/held_cn - 0.05:.1%} → "
          f"{'PASS' if held_cs/held_cn >= held_bs/held_cn - 0.05 else 'FAIL'}")


if __name__ == "__main__":
    main()
