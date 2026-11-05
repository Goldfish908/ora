#!/usr/bin/env python3
"""P3: build SFT / DPO datasets from factory + rescue traces.

Sources (all card-free prompts — the response must come from the model,
not from retrieval):
- runs/p1_factory/samples_*.json   injection + baseline repair traces
- runs/p2_hints/rescue_*.json      playbook rescue traces (card stripped)

Outputs (work/sft_data/):
- sft.jsonl   {"scenario_id", "mutant", "prompt", "response", "source",
               "rounds_used", "split"}
- dpo.jsonl   {"scenario_id", "mutant", "prompt", "chosen", "rejected",
               "source", "split"}
- stats.json  counts + split assignment

Split: deterministic 90/10 by scenario_id (every 10th sorted id -> dev).
F5-F8 remain untouched (not in the factory input at all).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTORY = ROOT / "runs" / "p1_factory"
RESCUE = ROOT / "runs" / "p2_hints"
OUT = ROOT / "work" / "sft_data"

REPAIR_PROMPT = (
    "{problem}\n\n"
    "[BUGGY CODE]\n```python\n{broken}\n```\n\n"
    "[CONSTRAINT VIOLATIONS — an independent witness checker re-verified "
    "the solution produced by the code above and found hard violations]\n"
    "```\n{violations}\n```\n"
    "The code contains a semantic modeling error (for example phantom "
    "resources that the problem never provides, a wrong parameter value, "
    "or a missing required constraint). Diagnose the root cause from the "
    "violations and the problem statement, fix the MODEL, and rewrite the "
    "COMPLETE corrected PySCIPOpt script. Output ONLY executable Python "
    "code.")


def split_of(sid: str, all_sids: list[str]) -> str:
    return "dev" if all_sids.index(sid) % 10 == 0 else "train"


def factory_prompt(s: dict) -> str:
    return REPAIR_PROMPT.format(problem=s["problem_text"],
                                broken=s["broken_code"],
                                violations=s["violation_text"])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sft: list[dict] = []
    dpo: list[dict] = []

    factory_samples = []
    for p in sorted(FACTORY.glob("samples_*.json")):
        try:
            s = json.loads(p.read_text())
        except Exception:
            continue
        if s.get("mutant_valid") and s.get("broken_code"):
            factory_samples.append(s)

    all_sids = sorted({s["scenario_id"] for s in factory_samples})

    def emit(sid, mutant, prompt, chosen, rejected, source):
        sp = split_of(sid, all_sids)
        if chosen:
            sft.append({"scenario_id": sid, "mutant": mutant,
                        "prompt": prompt, "response": chosen,
                        "source": source, "split": sp})
        if chosen and rejected and chosen.strip() != rejected.strip():
            dpo.append({"scenario_id": sid, "mutant": mutant,
                        "prompt": prompt, "chosen": chosen,
                        "rejected": rejected, "source": source, "split": sp})

    n_pass = n_fail = 0
    for s in factory_samples:
        sid, mut = s["scenario_id"], s["mutant_type"]
        prompt = factory_prompt(s)
        ga, oa = s.get("gold_objective"), s.get("objective_after")
        passed = bool(s.get("repaired_code")) and ga is not None \
            and oa is not None and abs(oa - ga) <= 1e-4 * max(1, abs(ga))
        wv = s.get("witness_verdict") or {}
        passed = passed and wv.get("verdict") == "pass"
        if passed:
            n_pass += 1
            # rejected: the broken code itself is the cleanest negative —
            # it is what the model must learn to move away from
            emit(sid, mut, prompt, s["repaired_code"], s["broken_code"],
                 "factory_pass")
        else:
            n_fail += 1

    # rescue traces: chosen from the rescue, rejected from the factory
    # baseline's failed repaired code (or broken code if no repair)
    base_by_key = {}
    for s in factory_samples:
        base_by_key[(s["scenario_id"], s["mutant_type"])] = s
    n_rescue = 0
    for p in sorted(RESCUE.glob("rescue_*.json")):
        try:
            r = json.loads(p.read_text())
        except Exception:
            continue
        if not r.get("rescued") or not r.get("rescued_code"):
            continue
        sid, mut = r["scenario_id"], r["mutant_type"]
        base = base_by_key.get((sid, mut))
        if base is None:
            continue
        prompt = factory_prompt(base)
        emit(sid, mut, prompt, r["rescued_code"],
             base.get("repaired_code") or base["broken_code"],
             "rescue_pass")
        n_rescue += 1

    with open(OUT / "sft.jsonl", "w") as f:
        for r in sft:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(OUT / "dpo.jsonl", "w") as f:
        for r in dpo:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    stats = {
        "factory_valid": len(factory_samples),
        "factory_pass": n_pass,
        "factory_fail": n_fail,
        "rescue_pass_used": n_rescue,
        "sft": len(sft),
        "dpo": len(dpo),
        "by_mutant_sft": Counter(r["mutant"] for r in sft),
        "by_split_sft": Counter(r["split"] for r in sft),
        "by_split_dpo": Counter(r["split"] for r in dpo),
    }
    (OUT / "stats.json").write_text(json.dumps(
        stats, ensure_ascii=False, indent=1, default=dict))
    print(json.dumps(stats, ensure_ascii=False, default=dict))


if __name__ == "__main__":
    main()
