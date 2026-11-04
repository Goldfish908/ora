#!/usr/bin/env python3
"""P2 retrieval-conditioned repair baseline (non-parametric arm).

Motivation (runs/p1_factory final, 2026-11-04): phantom_inventory repairs
succeed only 17.5% — 32/40 failures burn all 3 rounds emitting
near-identical code. Hypothesis: generic "fix the model" feedback is too
weak for structural semantic errors; a *repair playbook* distilled from
VERIFIED successful repairs of the same mutant class (dev40 only — the
exact data budget a LoRA repair SFT would get) should rescue part of the
failures without any weight update.

Method:
  1. card authoring: for a mutant type, take up to --n-card-examples
     successful (broken -> repaired) factory pairs, show the LLM the
     violation text + unified diff, and distill a compact playbook:
     how to recognize the error, its semantic root cause, the canonical
     fix pattern. Cached at runs/p2_hints/card_<mutant>.json.
  2. rescue: for every factory sample of that mutant type that was NOT
     verified-fixed, re-run the SAME repair loop (<=3 rounds, same
     witness+gold verification) with the playbook prepended to the
     initial repair prompt. One output file per sample =>
     resumable + shardable.

Metric: rescue rate on previously-failed samples (baseline for these
samples is 0% by construction), and implied new total fix rate.

Usage (from /home/hewj13/wm/ora):
    source ~/.leagent_env
    export ORA_LLM_BASE_URL=$QWEN27B_BASE_URL ORA_LLM_API_KEY=$QWEN27B_API_KEY \
        ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
    PY=/home/hewj13/planbb/miniforge3/envs/rl/bin/python
    $PY scripts/p2_repair_hints.py --mutant phantom_inventory --shard 0/2
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from scripts.p1_inject_factory import (  # noqa: E402
    MAX_TOKENS, REPAIR_TASK, TEMPERATURE, THINKING_OFF, extract_code,
    grade, repair_feedback, run_code, run_witness_local,
    violation_text_of)

FACTORY = ROOT / "runs" / "p1_factory"
OUT_DIR = ROOT / "runs" / "p2_hints"
DEV40 = ROOT / "data" / "m1_retailopt" / "dev40_f1f4.jsonl"

CARD_TASK = (
    "You are distilling a REPAIR PLAYBOOK for a class of semantic modeling "
    "bugs in PySCIPOpt scripts. Below are {n} VERIFIED examples. Each shows "
    "the constraint violations an independent checker reported for the "
    "buggy code, and the diff that fixed it.\n\n"
    "{examples}\n\n"
    "Write a compact playbook (max 220 words) with exactly these sections:"
    "\nRECOGNIZE: which violation messages / code patterns indicate this "
    "bug class."
    "\nROOT CAUSE: the single most common semantic misunderstanding."
    "\nCANONICAL FIX: the concrete code-level repair pattern (what to "
    "delete / add / re-derive), stated generally enough to transfer to a "
    "different scenario of the same bug class."
    "\nPITFALLS: what a naive patch gets wrong (e.g. patching the reported "
    "objective instead of the model)."
    "\nOutput plain text only.")

PLAYBOOK_HEADER = (
    "[REPAIR PLAYBOOK — distilled from verified fixes of this exact bug "
    "class on OTHER problems]\n")


def load_samples(mutant: str) -> list[dict]:
    out = []
    for p in sorted(FACTORY.glob(f"samples_*__{mutant}.json")):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            continue
    return out


def is_fixed(s: dict) -> bool:
    wv = s.get("witness_verdict") or {}
    return bool(s.get("mutant_valid") and s.get("repaired_code")
                and wv.get("verdict") == "pass" and wv.get("grade") == "match")


def make_examples(successes: list[dict], n: int) -> str:
    blocks = []
    for s in successes[:n]:
        diff = "\n".join(difflib.unified_diff(
            (s.get("broken_code") or "").splitlines(),
            (s.get("repaired_code") or "").splitlines(),
            lineterm="", n=2))
        blocks.append(
            f"=== example ({s['scenario_id']}) ===\n"
            f"[VIOLATIONS]\n{(s.get('violation_text') or '')[:900]}\n"
            f"[FIX DIFF]\n{diff[:2600]}")
    return "\n\n".join(blocks)


def author_card(cfg, mutant: str, successes: list[dict], n_ex: int) -> dict:
    prompt = CARD_TASK.format(n=min(n_ex, len(successes)),
                              examples=make_examples(successes, n_ex))
    t0 = time.time()
    resp = llm_mod.chat([{"role": "user", "content": prompt}],
                        max_tokens=2048, temperature=0.2,
                        extra=THINKING_OFF, config=cfg)
    card = (resp.get("content") or "").strip()
    return {"mutant_type": mutant, "n_examples": min(n_ex, len(successes)),
            "example_ids": [s["scenario_id"] for s in successes[:n_ex]],
            "card": card, "latency_s": round(time.time() - t0, 1)}


def rescue_sample(cfg, row: dict, sample: dict, card: str,
                  max_rounds: int) -> dict:
    sid = sample["scenario_id"]
    problem = sample["problem_text"]
    sb_root = OUT_DIR / "sandbox" / f"{sid}__{sample['mutant_type']}"
    sb_root.mkdir(parents=True, exist_ok=True)
    data = json.loads(row["data"])

    prompt = (PLAYBOOK_HEADER + "```\n" + card + "\n```\n\n"
              + REPAIR_TASK.format(problem=problem,
                                   broken=sample["broken_code"],
                                   violations=sample["violation_text"]))
    rec = {"scenario_id": sid, "mutant_type": sample["mutant_type"],
           "gold_objective": sample["gold_objective"],
           "rescue_rounds": 0, "rescued": False, "history": []}
    messages = [{"role": "user", "content": prompt}]
    for rnd in range(1, max_rounds + 1):
        t0 = time.time()
        try:
            resp = llm_mod.chat(messages, max_tokens=MAX_TOKENS,
                                temperature=TEMPERATURE, extra=THINKING_OFF,
                                config=cfg)
            text = resp.get("content") or ""
            meta = {"llm_latency_s": round(time.time() - t0, 1),
                    "finish_reason": resp.get("finish_reason")}
        except Exception as e:
            rec["history"].append({"round": rnd,
                                   "llm_error": f"{type(e).__name__}: {e}"})
            break
        hrec = {"round": rnd, **meta}
        code = extract_code(text)
        sb = sb_root / f"rescue_r{rnd}"
        sb.mkdir(parents=True, exist_ok=True)
        (sb / "data.json").write_text(row["data"])
        exec_rec = run_code(code, sb)
        exec_rec.update(run_witness_local(data, sb))
        g = grade(exec_rec.get("objective"), sample["gold_objective"],
                  exec_rec.get("solver_status"))
        hrec.update({k: exec_rec.get(k) for k in
                     ("exec_status", "solver_status", "objective",
                      "witness", "witness_rules", "wall_s")})
        hrec["grade"] = g
        rec["history"].append(hrec)
        rec["rescue_rounds"] = rnd
        if exec_rec.get("witness") == "feasible" and g == "match":
            rec["rescued"] = True
            rec["rescued_code"] = code
            break
        if rnd < max_rounds:
            messages.append({"role": "assistant", "content": code})
            messages.append({"role": "user",
                             "content": repair_feedback(exec_rec)})
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutant", default="phantom_inventory")
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--n-card-examples", type=int, default=4)
    args = ap.parse_args()

    rows = [json.loads(l) for l in DEV40.read_text().splitlines()
            if l.strip()]
    by_sid = {r["scenario_id"]: r for r in rows}

    samples = [s for s in load_samples(args.mutant)
               if s.get("mutant_valid")]
    successes = [s for s in samples if is_fixed(s)]
    failures = [s for s in samples if not is_fixed(s)]
    print(f"mutant={args.mutant} valid={len(samples)} "
          f"fixed={len(successes)} failed={len(failures)}", flush=True)

    cfg = llm_mod.load_config()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    card_path = OUT_DIR / f"card_{args.mutant}.json"
    if card_path.exists():
        card = json.loads(card_path.read_text())
        print(f"[card] reuse {card_path.name}", flush=True)
    else:
        if not successes:
            sys.exit("no verified successes to distill a card from")
        card = author_card(cfg, args.mutant, successes, args.n_card_examples)
        card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2))
        print(f"[card] authored from {card['n_examples']} examples",
              flush=True)

    k, kk = (int(x) for x in args.shard.split("/"))
    todo = [s for i, s in enumerate(failures) if i % kk == k]
    if args.limit:
        todo = todo[: args.limit]

    n_rescued = 0
    for s in todo:
        sid = s["scenario_id"]
        out = OUT_DIR / f"rescue_{sid}__{args.mutant}.json"
        if out.exists():
            print(f"[skip] {sid}", flush=True)
            continue
        rec = rescue_sample(cfg, by_sid[sid], s, card["card"],
                            args.max_rounds)
        rec["card_file"] = card_path.name
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=2))
        n_rescued += rec["rescued"]
        print(f"[{sid}] rescued={rec['rescued']} "
              f"rounds={rec['rescue_rounds']}", flush=True)
    print(f"DONE rescued {n_rescued}/{len(todo)} in this shard", flush=True)


if __name__ == "__main__":
    main()
