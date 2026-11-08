#!/usr/bin/env python3
"""P22: constant-audit probe on IndustryOR (240 cells) + multi-channel union.

Extends the p21 union analysis to IndustryOR. The probe's data-constant pool
is regex-extracted from the [PROBLEM] text (IndustryOR ships no data.json —
see report §9.1). Channels unioned:

  D = zero-shot direct judge   (zeroshot_industryor.jsonl)
  R = re-derivation judge      (active_industryor.jsonl)
  I = instrumentation judge    (active_ior2.jsonl)
  B = constant audit           (this script, frozen p17 parameters)

No LLM calls, read-only. Verdict convention: "INVALID" = flagged wrong.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from p17_const_audit import audit, factor_literals  # noqa: E402

JD = ROOT / "work" / "judge_data"
EVAL = JD / "eval_industryor.jsonl"

NUM = re.compile(r"\$?(-?\d[\d,]*(?:\.\d+)?)\s*(?:\\mathrm\{[^}]*\})?")


def section(u: str, tag: str, start: int) -> tuple[str, int]:
    i = u.find(f"[{tag}]", start)
    if i < 0:
        return "", start
    j = len(u)
    for t in ("PROBLEM", "DATA", "MODEL CODE", "SOLUTION"):
        k = u.find(f"[{t}]", i + 1)
        if 0 < k < j:
            j = k
    return u[i + len(tag) + 2:j], j


def problem_numbers(text: str) -> list[float]:
    vals = []
    for m in NUM.finditer(text):
        try:
            vals.append(float(m.group(1).replace(",", "")))
        except ValueError:
            pass
    return vals


def audit_against_vals(code: str, vals: list[float], band=(0.07, 0.31)):
    """near-miss channel against a raw value list (IndustryOR has no data.json)."""
    import bisect
    vals = sorted(v for v in vals if v != 0)
    if not vals:
        return []
    sus = []
    from p17_const_audit import code_literals
    for lit in set(code_literals(code)):
        if lit == 0:
            continue
        i = bisect.bisect_left(vals, lit)
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(vals):
                rel = abs(vals[j] - lit) / max(abs(vals[j]), abs(lit))
                if best is None or rel < best:
                    best = rel
        if best is not None and band[0] <= best <= band[1]:
            sus.append((lit, round(best, 4)))
    return sus


def main() -> None:
    cells = [json.loads(l) for l in EVAL.read_text().splitlines()]

    def verdicts(path):
        out = {}
        if not path.exists():
            return out
        for l in path.read_text().splitlines():
            r = json.loads(l)
            out[r["key"].split("|")[0]] = r.get("verdict")
        return out

    v_direct = verdicts(JD / "zeroshot_industryor.jsonl")
    v_rederive = verdicts(JD / "active_industryor.jsonl")
    v_instr = verdicts(JD / "active_ior2.jsonl")

    rows = []
    for c in cells:
        key, wrong = c["key"], c["wrong"]
        u = c["user"]
        prob, _ = section(u, "PROBLEM", 1000)
        code, _ = section(u, "MODEL CODE", 1000)
        vals = problem_numbers(prob)
        sus_n = audit_against_vals(code, vals)
        sus_f = factor_literals(code)
        k0 = key.split("|")[0]
        rows.append({
            "key": key, "wrong": wrong,
            "B_probe": bool(sus_n) or bool(sus_f),
            "D_direct": v_direct.get(k0) == "INVALID",
            "R_rederive": v_rederive.get(k0) == "INVALID",
            "I_instr": v_instr.get(k0) == "INVALID",
            "n_prob_nums": len(vals),
        })

    def rate(pred, label):
        sub = [r for r in rows if r["wrong"] == label]
        hit = sum(1 for r in sub if pred(r))
        return hit, len(sub), (hit / len(sub) if sub else 0)

    channels = [
        ("B const-probe", lambda r: r["B_probe"]),
        ("D direct", lambda r: r["D_direct"]),
        ("R re-derive", lambda r: r["R_rederive"]),
        ("I instrument", lambda r: r["I_instr"]),
        ("D|R|I (report §6)", lambda r: r["D_direct"] or r["R_rederive"] or r["I_instr"]),
        ("D|R|I|B union", lambda r: r["D_direct"] or r["R_rederive"] or r["I_instr"] or r["B_probe"]),
    ]
    for name, pred in channels:
        wh, wt, wr = rate(pred, True)
        ch, ct, cr = rate(pred, False)
        print(f"{name:20s} detect {wh}/{wt} = {wr:.1%}   FP {ch}/{ct} = {cr:.1%}")

    only_b = [r for r in rows if r["B_probe"] and r["wrong"]
              and not (r["D_direct"] or r["R_rederive"] or r["I_instr"])]
    print(f"\ncells ONLY the probe catches (wrong, missed by all 3 judge channels): {len(only_b)}")
    for r in only_b:
        print("  ", r["key"])
    print("\nmeta:", Counter(r["n_prob_nums"] > 5 for r in rows))
    out = JD / "p22_union_ior.json"
    out.write_text(json.dumps(rows, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
