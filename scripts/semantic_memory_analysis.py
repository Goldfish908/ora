#!/usr/bin/env python3
"""Per-family dev/held-out analysis for the gen-2 semantic memory arm (P3).

Holdout protocol: conventions in configs/semantic_priors_v0.1.txt are generic
dataset semantics (no instance values). Families F1-F4 are treated as dev,
F5-F8 as held-out; we report phantom/success rates separately so any
overfitting to dev families would show up as a gap.

Usage:
  python3 scripts/semantic_memory_analysis.py
"""
import json, glob, collections, sys

ROOT = "/home/hewj13/wm/ora"

ARMS = {
    "baseline (无先验)":      f"{ROOT}/runs/m1_pilot/m1_pilot_schema_sol{{v}}.jsonl",
    "P2 (代码惯例)":          f"{ROOT}/runs/m1_pilot_priors2/m1_pilot_schema_sol_p2_{{v}}.jsonl",
    "P3 (代码+语义惯例)":     f"{ROOT}/runs/m1_pilot_priors3/m1_pilot_schema_sol_p3_{{v}}.jsonl",
}
# baseline v0 文件无 _v0 后缀
V_SUFFIX = {"baseline (无先验)": {"v0": "", "v1": "_v1", "v2": "_v2",
                                  "v3": "_v3", "v4": "_v4"}}

def fam_of(sid: str) -> str:
    # retail_f4_demand_surge_v0 -> f4
    return sid.split("_")[1].upper()

def load(arm, pattern):
    cells = {}
    suff = V_SUFFIX.get(arm, {v: v for v in ["v0", "v1", "v2", "v3", "v4"]})
    for v in ["v0", "v1", "v2", "v3", "v4"]:
        for fp in glob.glob(pattern.format(v=suff[v])):
            for line in open(fp):
                r = json.loads(line)
                if r.get("thinking") != "on":
                    continue
                if "true_success" not in r:
                    r["true_success"] = (r.get("witness") == "feasible"
                                         and r.get("grade") == "match")
                cells[r["scenario_id"]] = r   # one record per scenario per arm
    return cells

def stats(cells):
    out = collections.defaultdict(lambda: collections.Counter())
    for sid, r in cells.items():
        fam = fam_of(sid)
        grp = "dev(F1-F4)" if fam in ("F1", "F2", "F3", "F4") else "heldout(F5-F8)"
        for g in (grp, "ALL"):
            st = out[g]
            st["n"] += 1
            if r.get("true_success"):
                st["true_success"] += 1
            elif r.get("exec_status") == "crash":
                st["crash"] += 1
            elif r.get("witness") == "infeasible" and \
                 r.get("grade") == "better_than_reference":
                st["phantom"] += 1
            elif r.get("witness") == "feasible":
                st["feasible_not_match"] += 1
            else:
                st["other_fail"] += 1
    return out

def row(arm, grp, st):
    n = st["n"] or 1
    return (f"{arm:24s} {grp:14s} n={st['n']:3d}  "
            f"成功 {st['true_success']/n:5.1%}  "
            f"幻影 {st['phantom']/n:5.1%}  "
            f"crash {st['crash']/n:5.1%}  "
            f"可行但不对 {st['feasible_not_match']/n:5.1%}  "
            f"其它 {st['other_fail']/n:5.1%}")

print("== pass@1 单发(无环)==")
for arm, pat in ARMS.items():
    try:
        cells = load(arm, pat)
    except Exception as e:
        print(arm, "load error:", e); continue
    if not cells:
        print(arm, ": 无数据"); continue
    st = stats(cells)
    for grp in ("dev(F1-F4)", "heldout(F5-F8)", "ALL"):
        print(row(arm, grp, st[grp]))
    print()

# per-family table for P3 vs P2 phantom rate
print("== 逐族幻影率(P2 vs P3)==")
p2, p3 = load("P2 (代码惯例)", ARMS["P2 (代码惯例)"]), load("P3 (代码+语义惯例)", ARMS["P3 (代码+语义惯例)"])
if p2 and p3:
    fams = sorted({fam_of(s) for s in p2})
    hdr = "family  n   P2幻影   P3幻影   P2成功  P3成功"
    print(hdr)
    for f in fams:
        a = [r for s, r in p2.items() if fam_of(s) == f]
        b = [r for s, r in p3.items() if fam_of(s) == f]
        def ph(rs): return sum(1 for r in rs if r.get("witness")=="infeasible"
                               and r.get("grade")=="better_than_reference")
        def ok(rs): return sum(1 for r in rs if r.get("true_success"))
        print(f"{f}  {len(a):3d}  {ph(a)/len(a):6.1%}  {ph(b)/len(b):6.1%}  "
              f"{ok(a)/len(a):6.1%}  {ok(b)/len(b):6.1%}")
