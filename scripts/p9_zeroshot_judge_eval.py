#!/usr/bin/env python3
"""P9: zero-shot judge baseline over eval cells via the LLM API (no GPU).

Runs a base model (default Qwen3_8-27B, thinking ON) over an eval jsonl of
{key, wrong, system, user} cells — same JUDGE_PROMPT input the trained judge
sees — and parses the VERDICT line. This isolates the effect of training:
same base model, same prompt, same cells; only the LoRA adapter differs.

Usage:
  ORA_LLM_BASE_URL=... ORA_LLM_API_KEY=... ORA_LLM_MODEL=Qwen3_8-27B \
  ORA_LLM_INSECURE=1 python scripts/p9_zeroshot_judge_eval.py \
      --eval work/judge_data/eval_industryor.jsonl \
      --out  work/judge_data/zeroshot_industryor.jsonl --workers 8
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import sys
sys.path.insert(0, str(ROOT))
from scripts.p5_judge_rs import call_llm, parse_verdict  # noqa: E402

import os  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cells = [json.loads(l) for l in open(args.eval)]
    out_path = Path(args.out)
    done = set()
    if out_path.exists():
        for l in out_path.read_text().splitlines():
            done.add(json.loads(l)["key"])
    todo = [c for c in cells if c["key"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"cells {len(cells)}, pending {len(todo)}")

    base_url = os.environ["ORA_LLM_BASE_URL"]
    api_key = os.environ["ORA_LLM_API_KEY"]
    model = os.environ.get("ORA_LLM_MODEL", "Qwen3_8-27B")
    insecure = os.environ.get("ORA_LLM_INSECURE") == "1"

    def one(c):
        msgs = ([{"role": "system", "content": c["system"]}] if c.get("system")
                else [])
        # call_llm takes a single user string; system is empty in our cells
        resp = call_llm(c["user"], model=model, base_url=base_url,
                        api_key=api_key, insecure=insecure, temperature=0.0,
                        max_tokens=args.max_tokens)
        return {"key": c["key"], "wrong": bool(c["wrong"]),
                "verdict": parse_verdict(resp["content"]),
                "latency_s": resp["latency_s"], "error": resp.get("error")}

    n = 0
    t0 = time.time()
    with out_path.open("a") as out, ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(one, c) for c in todo]
        for fut in as_completed(futs):
            r = fut.result()
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
            out.flush()
            n += 1
            if n % 20 == 0 or n == len(todo):
                print(f"[{n}/{len(todo)}] {time.time()-t0:.0f}s", flush=True)

    rows = [json.loads(l) for l in out_path.read_text().splitlines()]
    tp = sum(1 for r in rows if r["wrong"] and r["verdict"] == "INVALID")
    fn = sum(1 for r in rows if r["wrong"] and r["verdict"] != "INVALID")
    fp = sum(1 for r in rows if not r["wrong"] and r["verdict"] == "INVALID")
    tn = sum(1 for r in rows if not r["wrong"] and r["verdict"] != "INVALID")
    unparsed = sum(1 for r in rows if r["verdict"] is None)
    print(json.dumps({"n": len(rows), "tp": tp, "fn": fn, "fp": fp, "tn": tn,
                      "unparsed": unparsed,
                      "detection": round(tp / max(tp + fn, 1), 4),
                      "false_positive": round(fp / max(fp + tn, 1), 4)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
