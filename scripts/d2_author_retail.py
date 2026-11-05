#!/usr/bin/env python3
"""D2-gap: template-slot checker authoring on RetailOpt gapcheck60.

Same protocol as d2_author.py (IndustryOR) but reads the RetailOpt
gapcheck60 slice (data/m1_retailopt/gapcheck60_f1f4.jsonl) and keys outputs
by scenario_id. Purpose: confirm the anchor margin threshold on a dataset
independent from the one where the threshold was selected.

Usage:
    python3 scripts/d2_author_retail.py --limit 2        # smoke
    python3 scripts/d2_author_retail.py --shard 0/4      # batch
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from ora_agent import llm as llm_mod  # noqa: E402
from ora_agent import spec_templates as st  # noqa: E402
from d1_apply import run_rule  # noqa: E402
from d2_author import (PROMPT, REPAIR_PROMPT, _normalize_rule, _sum_usage,  # noqa: E402
                       author_rule, parse_json)

DATA = ROOT / "data" / "m1_retailopt" / "gapcheck60_f1f4.jsonl"
OUT_DIR = ROOT / "runs" / "d2_authoring_gap"
MAX_RULES = 6


def problem_text(d: dict) -> str:
    """The full harness prompt minus the trailing code-generation task block."""
    text = d["prompt_full"]
    i = text.rfind("[TASK]")
    return text[:i].rstrip() if i > 0 else text


def author_problem(d: dict, ask) -> dict:
    t0 = time.time()
    question = problem_text(d)
    resp = ask(PROMPT % question)
    if resp.get("finish_reason") == "length":
        resp = ask((PROMPT % question) +
                   "\nIMPORTANT: reply with COMPACT JSON, at most 4 rules, "
                   "short code snippets.", max_tokens=32768)
    parsed = parse_json(resp["content"])
    rec = {"id": d["scenario_id"]}
    if not parsed or not isinstance(parsed.get("rules"), list):
        rec.update(ok=False, stage1_finish_reason=resp.get("finish_reason"),
                   raw_head=(resp.get("content") or "")[:300])
        return rec
    params = parsed.get("params")
    params = params if isinstance(params, dict) else {}
    rec.update(ok=True, params=params, not_used=parsed.get("not_used"))
    calibrated, discarded = [], []
    for raw in (parsed.get("rules") or [])[:MAX_RULES]:
        rule = _normalize_rule(raw)
        if rule is None:
            continue
        entry, status = author_rule(rule, params, question, ask)
        entry["status"] = status
        (calibrated if status == "calibrated" else discarded).append(entry)
    rec.update(rules=calibrated, discarded=discarded,
               n_calibrated=len(calibrated), n_discarded=len(discarded),
               n_revised=sum(1 for r in calibrated if r["revisions"] > 0),
               latency_s=round(time.time() - t0, 1))
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--skip-fixtures", action="store_true")
    ap.add_argument("--data", default=str(DATA),
                    help="scenario jsonl (default: gapcheck60 slice)")
    ap.add_argument("--out", default=str(OUT_DIR),
                    help="output dir (default: runs/d2_authoring_gap)")
    ap.add_argument("--tag", default="gap",
                    help="output filename tag (default: gap)")
    args = ap.parse_args()
    k, K = (int(x) for x in args.shard.split("/"))
    data_path = Path(args.data)
    out_dir = Path(args.out)

    if not args.skip_fixtures:
        fx = st.run_fixtures()
        if not fx["ok"]:
            print("template fixtures FAILED, aborting:",
                  json.dumps(fx, ensure_ascii=False))
            sys.exit(1)

    data = [json.loads(l) for l in data_path.read_text().splitlines() if l.strip()]
    data = [d for i, d in enumerate(data) if i % K == k]
    if args.limit:
        data = data[: args.limit]
    out_dir.mkdir(parents=True, exist_ok=True)

    for d in data:
        out = out_dir / f"d2rules_{args.tag}_{d['scenario_id']}.json"
        if out.exists():
            print(f"[{d['scenario_id']}] exists, skip", flush=True)
            continue
        calls = []

        def ask(prompt, max_tokens=16384):
            resp = llm_mod.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=max_tokens, temperature=0.3,
                extra={"chat_template_kwargs": {"enable_thinking": False}})
            calls.append({"usage": resp.get("usage"),
                          "latency_s": round(resp.get("latency_s") or 0, 1),
                          "finish_reason": resp.get("finish_reason")})
            return resp

        try:
            rec = author_problem(d, ask)
        except Exception as e:
            rec = {"id": d["scenario_id"], "ok": False,
                   "error": f"{type(e).__name__}: {e}"}
            print(f"[{d['scenario_id']}] LLM error: {type(e).__name__}: {e}",
                  flush=True)
        rec["calls"] = calls
        rec["usage"] = _sum_usage(calls)
        rec["n_llm_calls"] = len(calls)
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
        if rec.get("ok"):
            total = rec["n_calibrated"] + rec["n_discarded"]
            print(f"[{d['scenario_id']}] calibrated={rec['n_calibrated']} "
                  f"(revised={rec['n_revised']}) discarded={rec['n_discarded']} "
                  f"calib_pass={rec['n_calibrated']}/{total} "
                  f"llm_calls={len(calls)} {rec['latency_s']}s", flush=True)
        else:
            print(f"[{d['scenario_id']}] stage1 failed", flush=True)


if __name__ == "__main__":
    main()
