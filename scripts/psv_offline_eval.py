#!/usr/bin/env python3
"""Pre-solve verifier offline evaluation.

Phase A (this script, --phase probes): deterministic AST data-key probes over
the 380 round-1 gen.py artifacts, scored against the program-verified witness
ground truth (m1_pilot_schema_sol_v*.jsonl). No LLM calls.

Outputs:
  runs/presolve/phase_a_rows.jsonl   per-cell probe results + ground truth
  runs/presolve/phase_a_summary.md   recall / pass-through tables
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from presolve import code_probes  # noqa: E402

DATA = ROOT / "data" / "m1_retailopt" / "retailopt_190.jsonl"
PILOT = ROOT / "runs" / "m1_pilot"
OUT = ROOT / "runs" / "presolve"


def load_ground_truth() -> dict:
    rows = {}
    files = ["m1_pilot_schema_sol"] + [f"m1_pilot_schema_sol_v{v}" for v in range(1, 5)]
    for f in files:
        for line in open(PILOT / f"{f}.jsonl"):
            r = json.loads(line)
            rows[(r["scenario_id"], r["thinking"])] = r
    return rows


def classify(r: dict) -> str:
    if r["exec_status"] != "ok":
        return "crash"
    if r["witness"] != "feasible":
        return "phantom"
    return "win" if r["grade"] == "match" else "other"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data_by_scen = {}
    for line in open(DATA):
        row = json.loads(line)
        data_by_scen[row["scenario_id"]] = json.loads(row["data"])

    gt = load_ground_truth()
    assert len(gt) == 380, f"expected 380 ground-truth rows, got {len(gt)}"

    out_rows = []
    missing_code = []
    for (scen, mode), r in sorted(gt.items()):
        code = r.get("gen_code")
        if not code:
            code = None
            for cand in (PILOT / "sandbox" / f"schema_sol__{scen}__{mode}" / "gen.py",
                         PILOT / "sandbox" / f"{scen}__{mode}" / "gen.py"):
                if cand.exists():
                    code = cand.read_text()
                    break
            if code is None:
                missing_code.append(f"{scen}__{mode}")
                continue
        sig = code_probes.extract_signals(code)
        probes = code_probes.eval_probes(sig, data_by_scen[scen])
        init_ev = code_probes.init_pin_evidence(sig)
        fails = [k for k, v in probes.items() if v["status"] == "fail"]
        out_rows.append({
            "scenario_id": scen, "thinking": mode,
            "gt_class": classify(r),
            "witness_rules": r.get("witness_rules", []),
            "parse_ok": sig["parse_ok"],
            "n_addcons": sig["n_addcons"],
            "n_data_keys": len(sig["data_keys"]),
            "probe_fails": fails,
            "init_heuristic_pass": init_ev["heuristic_pass"],
            "probes": {k: v["status"] for k, v in probes.items()},
        })

    with open(OUT / "phase_a_rows.jsonl", "w") as f:
        for r in out_rows:
            f.write(json.dumps(r) + "\n")

    # ---- scoring ----
    # BLOCK rule for Phase A: any active probe fails.
    def block(r):
        return bool(r["probe_fails"])

    conf = Counter()
    for r in out_rows:
        gt_bad = r["gt_class"] in ("phantom", "crash")
        conf[(block(r), gt_bad, r["gt_class"], r["thinking"])] += 1

    def summarize(mode):
        sel = [r for r in out_rows if r["thinking"] == mode]
        phan = [r for r in sel if r["gt_class"] == "phantom"]
        wins = [r for r in sel if r["gt_class"] == "win"]
        crash = [r for r in sel if r["gt_class"] == "crash"]
        return {
            "n": len(sel),
            "phantom": len(phan), "phantom_blocked": sum(block(r) for r in phan),
            "win": len(wins), "win_passed": sum(not block(r) for r in wins),
            "crash": len(crash), "crash_blocked": sum(block(r) for r in crash),
        }

    # per-probe fail stats on phantoms vs wins
    probe_stats = defaultdict(Counter)
    for r in out_rows:
        for p in r["probe_fails"]:
            probe_stats[p][r["gt_class"]] += 1

    lines = ["# Phase A: deterministic data-key probes (pre-solve, zero cost)", ""]
    for mode in ("on", "off"):
        s = summarize(mode)
        pr = s["phantom_blocked"] / s["phantom"] if s["phantom"] else 0.0
        pt = s["win_passed"] / s["win"] if s["win"] else 1.0
        lines.append(
            f"- **{mode}**: n={s['n']}; phantom recall {s['phantom_blocked']}/{s['phantom']} "
            f"({pr:.1%}); win pass-through {s['win_passed']}/{s['win']} ({pt:.1%}); "
            f"crash flagged {s['crash_blocked']}/{s['crash']}")
    lines.append("")
    lines.append("## Per-probe fail counts by ground-truth class")
    lines.append("")
    lines.append("| probe | phantom | win | crash | other |")
    lines.append("|---|---|---|---|---|")
    for p, c in sorted(probe_stats.items()):
        lines.append(f"| {p} | {c.get('phantom',0)} | {c.get('win',0)} | "
                     f"{c.get('crash',0)} | {c.get('other',0)} |")
    if missing_code:
        lines.append("")
        lines.append(f"WARNING missing gen.py for {len(missing_code)} cells: "
                     + ", ".join(missing_code[:10]))
    (OUT / "phase_a_summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
