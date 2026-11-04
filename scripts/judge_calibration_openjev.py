#!/usr/bin/env python3
"""P1': Open-Jev judge calibration on the P0 cell set (witness-as-oracle).

Same 316 witness-labeled cells, same killer metric (phantom false-clear rate),
same analyzer as P0 — only the judge backend changes: instead of generative
Qwen chat completions, we POST {state, questions} to a self-hosted Open-Jev
server (Noul primitive returns a calibrated probability in one forward pass).

Controlled comparison: Open-Jev-27B is LoRA + scalar decision head on the
SAME base weights as our solving model (Qwen3.8-27B, pinned revision), so a
performance delta vs P0 attributes to the decision-model form, not capacity.

Requires a running Open-Jev server (see docs/paper/jev_integration_exploration
§10):  python -m jev.server --checkpoint models/Open-Jev-27B-v1.1/package/...

Usage:
  python scripts/judge_calibration_openjev.py --dry-run     # no server needed
  python scripts/judge_calibration_openjev.py --limit 3     # smoke
  python scripts/judge_calibration_openjev.py               # all cells
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from judge_calibration_p0 import load_cells, load_prompts, sol_head  # noqa: E402

SERVER = "http://127.0.0.1:8791/v1/inference"

NOUL_INSTRUCTIONS = (
    "Decide whether the returned solution violates the problem's stated or "
    "clearly implied semantics (e.g. inventory appearing from nowhere, demand "
    "balance broken, capacity exceeded, lead time ignored, min-order "
    "violated). Do NOT re-solve the problem; judge semantic consistency "
    "between the statement and the returned solution.")


def build_request(prompt: str, code: str, objective, sol: dict) -> dict:
    state = (
        "[PROBLEM]\n" + prompt[:8000] +
        "\n\n[MODEL CODE] (truncated)\n" + code[:4000] +
        "\n\n[RETURNED SOLUTION SUMMARY]\n"
        f"objective = {objective}\n"
        f"first decision entries = {sol_head(sol)}")
    return {"state": state,
            "questions": {"violation": {"type": "noul",
                                        "instructions": NOUL_INSTRUCTIONS}}}


def post(request: dict, server: str, timeout: float = 120.0) -> dict:
    req = urllib.request.Request(
        server, data=json.dumps(request).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def extract_noul(resp: dict) -> tuple[float | None, float | None]:
    """Return (p_yes, confidence) from a server response, tolerant to key
    naming; None when absent."""
    q = resp.get("questions") or resp.get("answers") or resp
    v = q.get("violation") if isinstance(q, dict) else None
    if not isinstance(v, dict):
        return None, None
    p = v.get("noul", v.get("probability", v.get("p_yes")))
    conf = v.get("confidence")
    return (float(p) if p is not None else None,
            float(conf) if conf is not None else None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="no server calls")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--server", default=SERVER)
    ap.add_argument("--out", default=str(ROOT / "runs" / "judge_calib_openjev"
                                              / "judge_openjev.jsonl"))
    args = ap.parse_args()

    cells = load_cells()
    prompts = load_prompts()
    if args.limit:
        cells = cells[: args.limit]
    print(f"cells: {len(cells)}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.exists():
        for l in out_path.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                done.add((r["scenario_id"], r["thinking"], r["round"]))

    n_written = 0
    with out_path.open("a", encoding="utf-8") as fp:
        for c in cells:
            key = (c["scenario_id"], c["thinking"], c["round"])
            if key in done:
                continue
            sol = json.loads((c["_sandbox"] / "solution.json").read_text())
            code = (c["_sandbox"] / "gen.py").read_text()[:4000]
            request = build_request(prompts[c["scenario_id"]], code,
                                    c.get("objective"), sol)
            if args.dry_run:
                if n_written == 0:
                    print("sample request state head:",
                          request["state"][:300].replace("\n", " "))
                n_written += 1
                continue
            t0 = time.time()
            try:
                resp = post(request, args.server)
                p_yes, conf = extract_noul(resp)
                err = None
            except Exception as e:
                p_yes, conf, err = None, None, f"{type(e).__name__}: {e}"
            rec = {"scenario_id": c["scenario_id"], "thinking": c["thinking"],
                   "round": c["round"], "witness": c["witness"],
                   "grade": c.get("grade"), "p_violation": p_yes,
                   "confidence": conf, "latency_s": round(time.time() - t0, 2)}
            if err:
                rec["error"] = err
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fp.flush()
            n_written += 1
            print(f"[{c['scenario_id']} r{c['round']}] p_viol={p_yes} "
                  f"conf={conf} witness={c['witness']}", flush=True)
    print(("dry-run validated" if args.dry_run else "wrote"),
          n_written, "cells ->", out_path)


if __name__ == "__main__":
    main()
