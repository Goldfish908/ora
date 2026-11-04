#!/usr/bin/env python3
"""D1: checker-authoring — LLM drafts executable semantic check rules for
IndustryOR problems, seeing ONLY the problem text (no answers, no failing code).

Per problem, the agent returns JSON:
  {"params": {...},                      # extracted problem data
   "rules": [{"name": str, "why": str,   # error class this guards
              "code": "def check(code, objective, params): ..."}]}

Usage:
    python3 scripts/d1_author.py --limit 5        # smoke
    python3 scripts/d1_author.py --shard 0/4      # batch
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402

DATA = ROOT / "data" / "industryor" / "IndustryOR.json"
OUT_DIR = ROOT / "runs" / "d1_authoring"

PROMPT = """You are auditing AI-generated optimization code BEFORE trusting its answer.
Below is an optimization problem. An LLM (not you) wrote PySCIPOpt code to solve
it. Such code often runs fine yet models the problem WRONG (silent failures).

Your job: draft up to 5 executable audit rules that catch likely modeling errors
WITHOUT knowing the true answer.

Step 1 — extract the problem's data as JSON ("params"): all numeric quantities
with short names (demands, costs, capacities, limits, horizons...).

Step 2 — write audit rules. Each rule is a Python function:
    def check(code, objective, params):
        # code: str, the audited script's full text
        # objective: float or None, the printed optimal objective
        # params: dict, your extracted data from step 1
        # return a string describing the violation, or None if it passes
        import re  # allowed; stdlib only

Target error classes (examples, not exhaustive):
- a constraint present in the text but missing in code (e.g. text says
  "at most 3 lines", code has no such constraint — detectable via keyword
  or coefficient patterns);
- wrong constant: code uses a number that differs from the text;
- fabricated resource: code assumes initial inventory / free capacity the
  text never grants;
- wrong direction: maximize vs minimize, <= vs >=;
- sanity bounds on the objective (e.g. total cost cannot exceed buying
  everything new at max price; revenue cannot exceed total possible sales).

Be CONSERVATIVE: flag only when the violation is clear from the text.
A false alarm on a correct model is much worse than a missed error.
Rules must be robust: wrap risky parsing in try/except and return None on
any doubt. Never compare against the unknown true optimum.

Reply with EXACTLY one JSON object, no markdown fences:
{"params": {...}, "rules": [{"name": "...", "why": "...", "code": "def check(...): ..."}]}

[PROBLEM]
%s
"""


def parse_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1:]
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(text[i:j + 1], strict=False)
    except json.JSONDecodeError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--shard", default="0/1")
    args = ap.parse_args()
    k, K = (int(x) for x in args.shard.split("/"))

    data = json.loads(DATA.read_text())
    data = [d for i, d in enumerate(data) if i % K == k]
    if args.limit:
        data = data[: args.limit]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for d in data:
        out = OUT_DIR / f"rules_{d['id']}.json"
        if out.exists():
            continue
        t0 = time.time()
        try:
            resp = llm_mod.chat(
                [{"role": "user", "content": PROMPT % d["en_question"]}],
                max_tokens=16384, temperature=0.3,
                extra={"chat_template_kwargs": {"enable_thinking": False}})
            if resp.get("finish_reason") == "length":
                resp = llm_mod.chat(
                    [{"role": "user", "content":
                      (PROMPT % d["en_question"]) +
                      "\nIMPORTANT: reply with COMPACT single-line JSON, "
                      "at most 3 rules, short code bodies."}],
                    max_tokens=32768, temperature=0.3,
                    extra={"chat_template_kwargs": {"enable_thinking": False}})
            parsed = parse_json(resp["content"])
        except Exception as e:
            parsed = None
            resp = {"content": "", "usage": {}}
            print(f"[{d['id']}] LLM error: {type(e).__name__}: {e}", flush=True)
        rec = {"id": d["id"], "difficulty": d["difficulty"],
               "ok": bool(parsed and parsed.get("rules")),
               "n_rules": len(parsed.get("rules", [])) if parsed else 0,
               "finish_reason": resp.get("finish_reason"),
               "usage": resp.get("usage"),
               "latency_s": round(time.time() - t0, 1)}
        if parsed:
            rec["params"] = parsed.get("params")
            rec["rules"] = parsed.get("rules")
        else:
            rec["raw_head"] = (resp.get("content") or "")[:300]
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
        print(f"[{d['id']}] ok={rec['ok']} n_rules={rec['n_rules']} "
              f"{rec['latency_s']}s", flush=True)


if __name__ == "__main__":
    main()
