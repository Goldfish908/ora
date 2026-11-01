#!/usr/bin/env python3
"""G1 audit readout: detection rate vs false-alarm rate per arm x thinking.

  detection = mutant artifact (expected FAIL) judged FAIL
  false alarm = correct artifact (expected PASS) judged FAIL
  unparsed = no VERDICT line in the auditor's reply

Usage: python3 scripts/g1_audit_analysis.py [jsonl]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSONL = ROOT / "runs" / "g1_audit" / "g1_audit.jsonl"


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else JSONL
    rows = [json.loads(l) for l in path.read_text().splitlines()
            if l.strip()]
    agg = defaultdict(lambda: defaultdict(int))
    by_mut = defaultdict(lambda: defaultdict(int))
    for r in rows:
        k = (r["arm"], r["thinking"])
        if r["exec_status"] != "ok":
            agg[k]["llm_error"] += 1
            continue
        v = r.get("verdict")
        if v is None:
            agg[k][f"unparsed_{r['expected']}"] += 1
            continue
        if r["expected"] == "FAIL":
            agg[k]["detect" if v == "FAIL" else "miss"] += 1
            mk = (r["arm"], r["thinking"],
                  r["artifact"])
            by_mut[mk]["detect" if v == "FAIL" else "miss"] += 1
        else:
            agg[k]["false_alarm" if v == "FAIL" else "clean_pass"] += 1

    print("== arm x thinking ==")
    for (arm, mode), a in sorted(agg.items()):
        det, miss = a.get("detect", 0), a.get("miss", 0)
        fa, cp = a.get("false_alarm", 0), a.get("clean_pass", 0)
        unp = a.get("unparsed_FAIL", 0) + a.get("unparsed_PASS", 0)
        det_r = det / (det + miss) if det + miss else float("nan")
        fa_r = fa / (fa + cp) if fa + cp else float("nan")
        print(f"  {arm:<7} {mode}: detect {det}/{det+miss} ({det_r:.2f})  "
              f"false-alarm {fa}/{fa+cp} ({fa_r:.2f})  unparsed {unp}")

    print("\n== per mutant type (detection) ==")
    for (arm, mode, aid), a in sorted(by_mut.items()):
        det, miss = a.get("detect", 0), a.get("miss", 0)
        print(f"  {arm:<7} {mode} {aid:<12} {det}/{det+miss}")


if __name__ == "__main__":
    main()
