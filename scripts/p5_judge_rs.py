"""P5 rejection sampling: reasoning-judge SFT traces from the intranet Qwen.

For each judge_v2 train record we sample k reasoning trajectories from
Qwen3.8-27B with thinking ON, keep only those whose final verdict matches the
witness-derived label, and emit them as SFT traces. Side product: the per-sample
verdict match rate is a zero-shot judge accuracy measurement on the new
solution-digest channel (idea 2) before any training.

Usage:
  source ~/.leagent_env && export ORA_LLM_BASE_URL=$QWEN27B_BASE_URL \
      ORA_LLM_API_KEY=$QWEN27B_API_KEY ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
  python scripts/p5_judge_rs.py --dry-run
  python scripts/p5_judge_rs.py --limit 8 --workers 4        # smoke
  python scripts/p5_judge_rs.py --workers 16                 # full
"""
from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

JUDGE_DATA = ROOT / "work" / "judge_data" / "judge_v2.jsonl"
SCENARIOS = ROOT / "data" / "m1_retailopt" / "f1f4_all100.jsonl"
OUT = ROOT / "work" / "judge_data" / "rs_traces.jsonl"
STATS = ROOT / "work" / "judge_data" / "rs_stats.json"

JUDGE_PROMPT = """You are a meticulous semantics auditor for operations-research optimization models.

You are given:
1. [PROBLEM] the natural-language problem statement
2. [DATA] a digest of the instance data (ground-truth parameters)
3. [MODEL CODE] Python/SCIP modeling code written by an AI agent
4. [SOLUTION] a numeric digest of the solution the solver returned for that model

Decide whether the returned solution is SEMANTICALLY VALID with respect to the
problem statement and the data. Known violation patterns in this domain:
- inventory appearing from nowhere: positive stock at period 1 that first-period
  orders cannot explain, or any stock in non-fresh buckets at period 1
  (convention: zero initial inventory; with lead_time 0 an order placed at t=1
  arrives as FRESH stock at t=1 and is legitimate)
- a constraint silently dropped or relaxed (balance, capacity, availability, labor)
- wrong constants hardcoded in the model versus the data digest (MOQ, pack size,
  costs, capacities, shelf life)
- objective assembled from wrong quantity definitions

Field notes for [SOLUTION]:
- init_nonfresh_inv_total/count: stock at t=1 in buckets with remaining life < shelf_life
- init_fresh_inv_total/count: stock at t=1 in the fresh bucket
- unexplained_init_inv_total: t=1 stock beyond what t=1 orders can cover
- moq_violations: positive order quantities below the data MOQ

Reason concretely, citing numbers from [DATA] and [SOLUTION]. Then end with
exactly one final line:
VERDICT: VALID
or
VERDICT: INVALID

[PROBLEM]
{prompt}

[DATA]
{data_digest}

[MODEL CODE] (truncated)
{code}

[SOLUTION]
{solution_digest}"""


def load_prompts() -> dict[str, str]:
    out = {}
    for line in SCENARIOS.read_text().splitlines():
        r = json.loads(line)
        out[r["scenario_id"]] = r.get("prompt_full") or ""
    return out


def parse_verdict(text: str) -> str | None:
    hits = re.findall(r"VERDICT:\s*(VALID|INVALID)", text or "")
    return hits[-1] if hits else None


def call_llm(msg: str, *, model: str, base_url: str, api_key: str,
             insecure: bool, temperature: float, max_tokens: int,
             timeout: int = 300, retries: int = 2) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": msg}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "chat_template_kwargs": {"enable_thinking": True},
    }
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"},
            method="POST")
        try:
            t0 = time.monotonic()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
            msg_out = (payload.get("choices") or [{}])[0].get("message") or {}
            return {
                "content": msg_out.get("content") or "",
                "reasoning": msg_out.get("reasoning_content") or "",
                "usage": payload.get("usage") or {},
                "latency_s": round(time.monotonic() - t0, 2),
                "finish_reason": (payload.get("choices") or [{}])[0].get("finish_reason"),
            }
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(min(2.0 * (2 ** attempt), 20.0))
    return {"content": "", "reasoning": "", "usage": {},
            "latency_s": -1, "error": str(last), "finish_reason": None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    records = [json.loads(l) for l in JUDGE_DATA.read_text().splitlines()]
    train = [r for r in records if r["split"] == "train"]
    prompts = load_prompts()
    print(f"train records: {len(train)}; scenarios with prompt: {len(prompts)}")

    done = set()
    if OUT.exists():
        for l in OUT.read_text().splitlines():
            r = json.loads(l)
            done.add((r["scenario_id"], r.get("mutant"), r.get("seed_tag"),
                      r["sample_idx"]))
    todo = []
    for r in train:
        for i in range(args.k):
            if (r["scenario_id"], r.get("mutant"), r.get("seed_tag"), i) not in done:
                todo.append((r, i))
    if args.limit:
        todo = todo[:args.limit]
    print(f"pending samples: {len(todo)} (done {len(done)})")
    if args.dry_run:
        from collections import Counter
        print("by mutant/label:", Counter(
            (r.get("mutant"), r["label"]) for r, _ in todo))
        return

    base_url = os.environ["ORA_LLM_BASE_URL"]
    api_key = os.environ["ORA_LLM_API_KEY"]
    model = os.environ.get("ORA_LLM_MODEL", "Qwen3_8-27B")
    insecure = os.environ.get("ORA_LLM_INSECURE") == "1"

    def one(rec, idx):
        msg = JUDGE_PROMPT.format(
            prompt=prompts.get(rec["scenario_id"], "")[:4000],
            data_digest=json.dumps(rec["data_digest"], ensure_ascii=False),
            code=rec["code"][:4000],
            solution_digest=json.dumps(rec["solution_digest"], ensure_ascii=False))
        resp = call_llm(msg, model=model, base_url=base_url, api_key=api_key,
                        insecure=insecure, temperature=args.temperature,
                        max_tokens=args.max_tokens)
        verdict = parse_verdict(resp["content"])
        gold_verdict = "INVALID" if rec["label"] == "wrong" else "VALID"
        return {
            "scenario_id": rec["scenario_id"], "mutant": rec.get("mutant"),
            "seed_tag": rec.get("seed_tag"), "split": rec["split"],
            "label": rec["label"], "sample_idx": idx,
            "verdict": verdict, "verdict_match": verdict == gold_verdict,
            "content": resp["content"], "reasoning": resp["reasoning"],
            "usage": resp["usage"], "latency_s": resp["latency_s"],
            "finish_reason": resp.get("finish_reason"),
            "error": resp.get("error"),
        }

    n_done = 0
    t0 = time.time()
    with OUT.open("a") as out, ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(one, r, i) for r, i in todo]
        for fut in as_completed(futs):
            rec = fut.result()
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            n_done += 1
            if n_done % 20 == 0 or n_done == len(todo):
                el = time.time() - t0
                print(f"[{n_done}/{len(todo)}] {el:.0f}s "
                      f"({el / max(n_done, 1):.1f}s/sample)", flush=True)

    # stats over everything in OUT (this run + earlier)
    from collections import Counter, defaultdict
    rows = [json.loads(l) for l in OUT.read_text().splitlines()]
    per_class = defaultdict(Counter)
    for r in rows:
        key = (r.get("mutant") or "correct", r["label"])
        per_class[key]["n"] += 1
        if r.get("error"):
            per_class[key]["error"] += 1
        elif r["verdict_match"]:
            per_class[key]["match"] += 1
        elif r["verdict"] is None:
            per_class[key]["no_verdict"] += 1
    rec_any = defaultdict(bool)
    rec_tot = defaultdict(int)
    for r in rows:
        k = (r["scenario_id"], r.get("mutant"), r.get("seed_tag"))
        rec_tot[k] += 1
        rec_any[k] = rec_any[k] or r["verdict_match"]
    stats = {
        "samples": len(rows),
        "per_class": {str(k): dict(v) for k, v in sorted(per_class.items())},
        "records_with_any_match": sum(rec_any.values()),
        "records_total": len(rec_tot),
        "overall_sample_match": sum(1 for r in rows if r["verdict_match"]) / max(len(rows), 1),
    }
    STATS.write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
