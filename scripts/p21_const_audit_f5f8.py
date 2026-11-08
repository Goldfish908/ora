#!/usr/bin/env python3
"""P21: constant-audit probe on F5-F8 holdout + union with the active judge.

Question: on the 48 F5-F8 cells, does the deterministic code-vs-data
constant audit (p17) add detection power on top of the v4 zero-shot
active judge, or is the judge already covering the same cells?

Channels:
  A = active judge v4 zero-shot verdict (active_f5f8_v4.jsonl, INVALID)
  B = constant audit: near-miss literal (band 0.07-0.31) OR factor literal

Code is recovered from the eval prompt ([MODEL CODE] section); data comes
from the frozen eval artifacts (v4_eval_artifacts/f5f8/<key>/data.json).
No LLM calls, read-only.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from p17_const_audit import audit, factor_literals  # noqa: E402

EVAL = ROOT / "work" / "judge_data" / "eval_f5f8.jsonl"
V4 = ROOT / "work" / "judge_data" / "active_f5f8_v4.jsonl"
ART = ROOT / "work" / "judge_data" / "v4_eval_artifacts" / "f5f8"


def extract_code(user: str) -> str:
    i = user.find("[MODEL CODE]", user.find("[PROBLEM]\n", 1000))
    if i < 0:
        i = user.rfind("[MODEL CODE]")
    j = user.find("[SOLUTION]", i)
    return user[i + len("[MODEL CODE]"):j].strip()


def main() -> None:
    cells = [json.loads(l) for l in EVAL.read_text().splitlines()]
    verdicts = {json.loads(l)["key"]: json.loads(l)["verdict"]
                for l in V4.read_text().splitlines()}

    rows = []
    for c in cells:
        key, wrong = c["key"], c["wrong"]
        code = extract_code(c["user"])
        dpath = ART / key.replace("|", "__") / "data.json"
        data = json.loads(dpath.read_text()) if dpath.exists() else {}
        sus_n = audit(code, data, band=(0.07, 0.31)) if data else []
        sus_f = factor_literals(code)
        rows.append({
            "key": key, "wrong": wrong,
            "judge_flag": verdicts.get(key) == "INVALID",
            "audit_flag": bool(sus_n) or bool(sus_f),
            "near_miss": sus_n, "factors": sus_f,
            "code_chars": len(code), "has_data": bool(data),
        })

    def rate(rs, pred, label):
        sub = [r for r in rs if r["wrong"] == label]
        hit = sum(1 for r in sub if pred(r))
        return hit, len(sub)

    for name, pred in [
        ("A active-judge v4", lambda r: r["judge_flag"]),
        ("B const-audit", lambda r: r["audit_flag"]),
        ("A|B union", lambda r: r["judge_flag"] or r["audit_flag"]),
        ("A&B intersect", lambda r: r["judge_flag"] and r["audit_flag"]),
    ]:
        w_hit, w_tot = rate(rows, pred, True)
        c_hit, c_tot = rate(rows, pred, False)
        print(f"{name:16s}  detect {w_hit}/{w_tot} = {w_hit/w_tot:.1%}"
              f"   FP {c_hit}/{c_tot} = {c_hit/c_tot:.1%}")

    print("\nmeta:", Counter((r["has_data"], r["code_chars"] > 100) for r in rows))
    print("\naudit-flagged cells:")
    for r in rows:
        if r["audit_flag"]:
            print(f"  {'WRONG' if r['wrong'] else 'clean'}  {r['key']}"
                  f"  near_miss={r['near_miss'][:3]} factors={r['factors'][:3]}"
                  f"  judge={'INVALID' if r['judge_flag'] else 'VALID'}")
    out = ROOT / "work" / "judge_data" / "p21_union_f5f8.json"
    out.write_text(json.dumps(rows, indent=1))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
