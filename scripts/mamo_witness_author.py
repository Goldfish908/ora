#!/usr/bin/env python3
"""Author conservative per-instance countable-variable witnesses from MAMO text/code."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod
from scripts.m3_industryor import countable_witness_feedback

PROMPT = """You are proposing ONE deterministic variable-type witness for an optimization model.
Your only decision is whether EVERY main decision quantity is clearly indivisible.

Return all_main_countable=true ONLY when every main quantity counts discrete entities
(such as individual brownies, bottles, chairs, or packages). Return false for:
- any divisible quantity (money, liquids, pounds, hours, geometric dimensions, bulk material);
- mixed models with both integer and continuous main quantities;
- network flows or any case where integer-only modeling would be too strong.

Do not infer integrality merely from words like food, product, units, or optimization.
Use the problem text, not the reference objective.

{memory}

[PROBLEM]
{question}

[GENERATED CODE]
{code}

Reply with exactly one JSON object:
{{"all_main_countable": true or false,
 "entity": "the discrete entities, or the reason the model is continuous/mixed",
 "evidence": "an exact verbatim span from the problem supporting your decision",
 "reason": "one sentence"}}
"""


def parse_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def evidence_matches(evidence: str, question: str) -> bool:
    normalize = lambda s: " ".join(s.split()).casefold()
    return bool(evidence.strip()) and normalize(evidence) in normalize(question)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--baseline-tag", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out-config", required=True)
    ap.add_argument("--out-log", required=True)
    ap.add_argument("--memory-file")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    rows = {r["id"]: r for r in json.loads(Path(args.data).read_text())}
    baseline = [json.loads(l) for l in Path(args.baseline).read_text().splitlines() if l.strip()]
    last = {}
    for r in baseline:
        if r["id"] not in last or r["round"] > last[r["id"]]["round"]:
            last[r["id"]] = r
    cfg = llm_mod.load_config()
    memory = Path(args.memory_file).read_text() if args.memory_file else ""
    config, log = {}, []
    done = set()
    if args.resume and Path(args.out_config).exists() and Path(args.out_log).exists():
        config = json.loads(Path(args.out_config).read_text())
        log = [json.loads(l) for l in Path(args.out_log).read_text().splitlines() if l.strip()]
        done = {r["id"] for r in log}
    for pid, prev in sorted(last.items()):
        if pid in done:
            print(pid, "resume_skip", flush=True)
            continue
        question = rows[pid]["en_question"]
        sandbox = (ROOT / "runs/industryor/sandbox"
                   / f"{args.baseline_tag}__{pid}__r{prev['round']}")
        code = (sandbox / "gen.py").read_text()
        resp = llm_mod.chat([{"role": "user", "content": PROMPT.format(
            question=question, code=code, memory=memory)}], max_tokens=4096, temperature=0.0,
            extra={"chat_template_kwargs": {"enable_thinking": False}}, config=cfg)
        proposal = parse_json(resp.get("content") or "")
        rec = {"id": pid, "proposal": proposal, "usage": resp.get("usage")}
        if not isinstance(proposal, dict):
            rec["status"] = "rejected_unparseable"
        else:
            evidence = str(proposal.get("evidence") or "")
            if not evidence_matches(evidence, question):
                rec["status"] = "rejected_evidence_not_verbatim"
            elif proposal.get("all_main_countable") is True:
                rule = {"rule": "COUNTABLE_INTEGER", "scope": "all_main_decision_variables",
                        "entity": proposal.get("entity") or "indivisible entities",
                        "evidence": evidence}
                config[str(pid)] = rule
                guard = countable_witness_feedback({str(pid): rule}, pid, code)
                rec.update(status="candidate", must_fire=bool(guard),
                           must_pass=guard is None)
            else:
                rec.update(status="disabled_continuous_or_mixed", must_pass=True)
        log.append(rec)
        print(pid, rec["status"], "must_fire", rec.get("must_fire"),
              "must_pass", rec.get("must_pass"), flush=True)
    out_config = Path(args.out_config)
    out_config.parent.mkdir(parents=True, exist_ok=True)
    out_config.write_text(json.dumps(config, ensure_ascii=False, indent=1) + "\n")
    Path(args.out_log).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in log))


if __name__ == "__main__":
    main()
