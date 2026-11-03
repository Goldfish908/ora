#!/usr/bin/env python3
"""Freeze the evolution inner-loop slices (see docs/paper/self_evolution_design_v0.1.md).

dev40   = F1-F4 archetypes, variants v0+v4  (fitness set, every genome every gen)
gapcheck60 = F1-F4 variants v1,v2,v3        (champion-only overfitting check)
F5-F8 are physically excluded from both files.

Split by variant (not archetype) because per-variant difficulty differs
(v3 hardest); v0+v4 balances the P3 pass@1 baseline (25.0% vs 21.7%).

Regenerate:  python3 scripts/freeze_slices.py
Verify:      sha256sum -c via data/m1_retailopt/slices_manifest.json
"""
import json, collections, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/m1_retailopt/retailopt_190.jsonl"
DEV_VARS = {"v0", "v4"}

dev, gap = [], []
for line in SRC.open():
    r = json.loads(line)
    sid = r["scenario_id"]
    fam, var = sid.split("_")[1], sid.rsplit("_", 1)[1]
    if fam not in ("f1", "f2", "f3", "f4"):
        continue
    (dev if var in DEV_VARS else gap).append(r)

out_dev = ROOT / "data/m1_retailopt/dev40_f1f4.jsonl"
out_gap = ROOT / "data/m1_retailopt/gapcheck60_f1f4.jsonl"
out_dev.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in dev))
out_gap.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in gap))

leak = [r["scenario_id"] for r in dev + gap if re.search(r"_f[5-8]_", r["scenario_id"])]
assert not leak, f"F5-F8 leakage: {leak}"
print(f"dev={len(dev)} gap={len(gap)} leak=0 "
      f"dev_families={dict(collections.Counter(r['scenario_id'].split('_')[1] for r in dev))}")
