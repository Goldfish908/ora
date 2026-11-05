#!/usr/bin/env python3
"""P4: build judge-training dataset v2 from the P1 factory.

Each record pairs a code text with the NUMERIC DIGEST of the solution it
produced — the judge learns from the channel where witness actually works
(solution values vs problem data), not just from reading code text.

Records:
  - "wrong"  : the injected mutant (witness-confirmed infeasible) + its
               solution from the inject sandbox
  - "correct": the verified repaired code (witness pass + gold match) + its
               solution from the passing repair round

Output: work/judge_data/judge_v2.jsonl + stats.json
Split: deterministic 90/10 by scenario_id (every 10th sorted -> dev).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTORY = ROOT / "runs" / "p1_factory"
OUT = ROOT / "work" / "judge_data"


def data_digest(d: dict) -> dict:
    c = d.get("constraints") or {}
    costs = d.get("costs") or {}
    return {
        "periods": d.get("periods"),
        "n_products": len(d.get("products") or []),
        "n_locations": len(d.get("locations") or []),
        "shelf_life": d.get("shelf_life"),
        "lead_time": d.get("lead_time"),
        "moq": c.get("moq"), "pack_size": c.get("pack_size"),
        "budget_per_period": c.get("budget_per_period"),
        "waste_limit_pct": c.get("waste_limit_pct"),
        "fixed_order_cost": costs.get("fixed_order"),
        "n_trans_edges": len((d.get("network") or {}).get("trans_edges") or []),
    }


def solution_digest(sol: dict, d: dict) -> dict:
    sl = d.get("shelf_life") or {}
    moq = (d.get("constraints") or {}).get("moq") or 0

    def entries(field):
        out = []
        for k, v in (sol.get(field) or {}).items():
            if isinstance(v, (int, float)) and abs(v) > 1e-6:
                out.append((k.split("|"), float(v)))
        return out

    # phantom signal: inventory at t=1 that cannot be explained by t=1 orders.
    # Non-fresh buckets (r<SL) are impossible under any convention; fresh
    # bucket (r==SL) is explainable only if lead_time==0 AND Q[p,.,1] covers it
    # (gold convention: zero initial inventory).
    lt = d.get("lead_time") or {}
    init_by_p, q1_by_p = {}, {}
    init_nonfresh, init_cnt = 0.0, 0
    init_fresh, init_fresh_cnt = 0.0, 0
    for parts, v in entries("I"):
        if len(parts) == 4:
            p, l, t, r = parts[0], parts[1], int(parts[2]), int(parts[3])
            if t == 1:
                init_by_p[p] = init_by_p.get(p, 0.0) + v
                if r < int(sl.get(p, 1)):
                    init_nonfresh += v
                    init_cnt += 1
                else:
                    init_fresh += v
                    init_fresh_cnt += 1
    for parts, v in entries("Q"):
        if len(parts) == 3 and int(parts[2]) == 1:
            q1_by_p[parts[0]] = q1_by_p.get(parts[0], 0.0) + v
    unexplained = 0.0
    for p, v in init_by_p.items():
        cover = q1_by_p.get(p, 0.0) if int(lt.get(p, 1) or 0) == 0 else 0.0
        unexplained += max(0.0, v - cover)
    q_vals = [v for _, v in entries("Q")]
    moq_viol = sum(1 for v in q_vals if moq and 1e-6 < v < moq - 1e-6)
    return {
        "objective": sol.get("objective"),
        "init_nonfresh_inv_total": round(init_nonfresh, 4),
        "init_nonfresh_inv_count": init_cnt,
        "init_fresh_inv_total": round(init_fresh, 4),
        "init_fresh_inv_count": init_fresh_cnt,
        "unexplained_init_inv_total": round(unexplained, 4),
        "n_positive_Q": len(q_vals),
        "moq_violations": moq_viol,
        "waste_total": round(sum(v for _, v in entries("W")), 4),
        "lost_total": round(sum(v for _, v in entries("lost")), 4),
        "sub_total": round(sum(v for _, v in entries("sub")), 4),
        "trans_total": round(sum(v for _, v in entries("X")), 4),
    }


def find_inject_solution(sb_root: Path, obj_before):
    for d in sorted(sb_root.glob("inject_a*")):
        sp = d / "solution.json"
        if not sp.exists():
            continue
        try:
            sol = json.loads(sp.read_text())
        except Exception:
            continue
        if obj_before is not None and sol.get("objective") is not None and \
                abs(sol["objective"] - obj_before) <= 1e-6 * max(1, abs(obj_before)):
            return sol
        return sol  # single attempt: accept without objective match
    return None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = {r["scenario_id"]: r for r in
            (json.loads(l) for l in
             (ROOT / "data/m1_retailopt/f1f4_all100.jsonl").read_text().splitlines()
             if l.strip())}

    records = []
    skipped = Counter()
    for p in sorted(FACTORY.glob("samples_*.json")):
        try:
            s = json.loads(p.read_text())
        except Exception:
            continue
        if not s.get("mutant_valid") or not s.get("broken_code"):
            continue
        sid = s["scenario_id"]
        row = rows.get(sid)
        if row is None:
            skipped["no_row"] += 1
            continue
        d = json.loads(row["data"])
        seed_tag = p.stem.split(f"__{s['mutant_type']}", 1)[1]
        sb_root = FACTORY / "sandbox" / f"{sid}__{s['mutant_type']}{seed_tag}"
        dd = data_digest(d)

        base = {"scenario_id": sid, "mutant": s["mutant_type"],
                "seed_tag": seed_tag, "gold_objective": s["gold_objective"],
                "data_digest": dd}

        sol_bad = find_inject_solution(sb_root, s.get("objective_before"))
        if sol_bad is not None:
            records.append({**base, "source": "inject", "label": "wrong",
                            "code": s["broken_code"],
                            "objective": sol_bad.get("objective"),
                            "solution_digest": solution_digest(sol_bad, d)})
        else:
            skipped["no_inject_solution"] += 1

        wv = s.get("witness_verdict") or {}
        ga, oa = s.get("gold_objective"), s.get("objective_after")
        passed = bool(s.get("repaired_code")) and wv.get("verdict") == "pass" \
            and ga is not None and oa is not None \
            and abs(oa - ga) <= 1e-4 * max(1, abs(ga))
        if passed:
            rnd = s.get("repair_rounds") or 1
            sp = sb_root / f"repair_r{rnd}" / "solution.json"
            if sp.exists():
                try:
                    sol_ok = json.loads(sp.read_text())
                    records.append({**base, "source": "repair_pass",
                                    "label": "correct",
                                    "code": s["repaired_code"],
                                    "objective": sol_ok.get("objective"),
                                    "solution_digest": solution_digest(sol_ok, d)})
                except Exception:
                    skipped["bad_repair_solution"] += 1
            else:
                skipped["no_repair_solution"] += 1

    all_sids = sorted({r["scenario_id"] for r in records})
    for r in records:
        r["split"] = "dev" if all_sids.index(r["scenario_id"]) % 10 == 0 else "train"

    with open(OUT / "judge_v2.jsonl", "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def _has_init_inv(r):
        d = r["solution_digest"]
        return (d["init_nonfresh_inv_count"] > 0
                or d["unexplained_init_inv_total"] > 1e-3)

    stats = {
        "records": len(records),
        "by_label": Counter(r["label"] for r in records),
        "by_source": Counter(r["source"] for r in records),
        "by_split": Counter(r["split"] for r in records),
        "skipped": dict(skipped),
        "phantom_signal_check": {
            "wrong_with_init_inv": sum(1 for r in records
                                       if r["label"] == "wrong" and _has_init_inv(r)),
            "correct_with_init_inv": sum(1 for r in records
                                         if r["label"] == "correct" and _has_init_inv(r)),
        },
    }
    (OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False,
                                               indent=1, default=dict))
    print(json.dumps(stats, ensure_ascii=False, default=dict))


if __name__ == "__main__":
    main()
