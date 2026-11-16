#!/usr/bin/env python3
"""Promote a countable witness only after an independent integer re-solve counterexample."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod
from scripts.m1_pilot import run_code
from scripts.m3_industryor import countable_witness_feedback, force_integer_variables
from scripts.mamo_witness_author import evidence_matches, parse_json

PROMPT = """An independent development counterexample has established that this model's continuous relaxation is wrong while the integer re-solve is correct.

[PROBLEM]
{question}

[CONTINUOUS OBJECTIVE]
{continuous}

[INTEGER RE-SOLVE OBJECTIVE]
{integer}

[INDEPENDENT REFERENCE]
{reference}

[VERIFIED MEMORY]
{memory}

Propose the variable-type witness ONLY if all main decision variables are indivisible.
Return JSON: {{"all_main_countable": true or false, "entity": "...", "evidence": "...", "reason": "..."}}.
Evidence must be ONE short, contiguous, verbatim span copied exactly from the problem. Never use ellipses or combine disjoint spans. Use the independent result as a counterexample to overly conservative textual intuition, not as a reason to hardcode the objective.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--baseline-tag", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--memory-file", required=True)
    ap.add_argument("--out-log", required=True)
    args = ap.parse_args()
    rows = {r["id"]: r for r in json.loads(Path(args.data).read_text())}
    baseline = [json.loads(l) for l in Path(args.baseline).read_text().splitlines() if l.strip()]
    prev = max((r for r in baseline if r["id"] == args.id), key=lambda r: r["round"])
    code = (ROOT / "runs/industryor/sandbox"
            / f"{args.baseline_tag}__{args.id}__r{prev['round']}" / "gen.py").read_text()
    reference = float(prev["reference"])
    continuous_correct = (prev.get("objective") is not None
                          and abs(prev["objective"] - reference) <= 0.1)
    integer_code = force_integer_variables(code)
    sandbox = (ROOT / "work/memory_witness/counterexample" / str(args.id)).resolve()
    result = run_code(integer_code, sandbox)
    integer = result.get("objective")
    integer_correct = integer is not None and abs(integer - reference) <= 0.1
    config_path = Path(args.config)
    config = json.loads(config_path.read_text())
    rec = {"id": args.id, "continuous": prev.get("objective"),
           "integer": integer, "reference": reference,
           "continuous_correct": continuous_correct, "integer_correct": integer_correct}
    if continuous_correct or not integer_correct:
        rec["status"] = "rejected_counterexample_not_supportive"
    else:
        question = rows[args.id]["en_question"]
        memory = Path(args.memory_file).read_text()
        resp = llm_mod.chat([{"role": "user", "content": PROMPT.format(
            question=question, continuous=prev.get("objective"), integer=integer,
            reference=reference, memory=memory)}], max_tokens=4096, temperature=0.0,
            extra={"chat_template_kwargs": {"enable_thinking": False}}, config=llm_mod.load_config())
        proposal = parse_json(resp.get("content") or "")
        rec["proposal"] = proposal
        evidence = str((proposal or {}).get("evidence") or "")
        if not isinstance(proposal, dict) or proposal.get("all_main_countable") is not True:
            rec["status"] = "rejected_text_or_type_not_supported"
        elif not evidence_matches(evidence, question):
            rec["status"] = "rejected_evidence_not_verbatim"
        else:
            rule = {"rule": "COUNTABLE_INTEGER", "scope": "all_main_decision_variables",
                    "entity": proposal.get("entity") or "indivisible entities",
                    "evidence": evidence}
            rec["must_fire"] = bool(countable_witness_feedback({str(args.id): rule}, args.id, code))
            rec["must_pass"] = countable_witness_feedback({str(args.id): rule}, args.id, integer_code) is None
            if rec["must_fire"] and rec["must_pass"]:
                config[str(args.id)] = rule
                config_path.write_text(json.dumps(config, ensure_ascii=False, indent=1) + "\n")
                rec["status"] = "dev-passed"
            else:
                rec["status"] = "rejected_self_test"
    Path(args.out_log).write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(rec, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
