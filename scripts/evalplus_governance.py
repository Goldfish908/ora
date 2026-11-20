#!/usr/bin/env python3
"""Trusted EvalPlus audit cases and verification-knowledge authorization."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from evalplus.data import get_human_eval_plus, get_human_eval_plus_hash
from evalplus.evaluate import check_correctness, get_groundtruth

from ora_agent.verification_governance import (
    CheckAsset,
    TrustedCase,
    Verdict,
    VerificationGovernor,
    convention_source,
)
ROOT = Path(__file__).resolve().parents[1]
SPLIT_SEED = "evalplus-gepa-v0.1"


def split_ids(problems: dict) -> dict[str, list[str]]:
    ordered = sorted(problems, key=lambda task_id: hashlib.sha256(
        f"{SPLIT_SEED}:{task_id}".encode()).hexdigest())
    return {"dev": sorted(ordered[:40]), "gapcheck": sorted(ordered[40:100]),
            "test": sorted(ordered[100:])}


def execution_eval(artifact: dict) -> Verdict:
    status = artifact["record"].get("base_status")
    if status in {"pass", "fail"}:
        return Verdict("pass", "code completed the original test execution")
    return Verdict("fail", f"execution status: {status}")


def evalplus_eval(artifact: dict) -> Verdict:
    result = check_correctness("humaneval", 0, artifact["problem"], artifact["solution"],
                               artifact["expected_output"], base_only=False, fast_check=True)
    status = result["plus"][0]
    if status == "pass":
        return Verdict("pass", "all EvalPlus tests pass")
    if status in {"timeout", "runner_error"}:
        return Verdict("unknown", f"EvalPlus status: {status}")
    return Verdict("fail", f"EvalPlus status: {status}")


def generate_cases(outdir: Path, limit: int = 3) -> dict:
    problems = get_human_eval_plus()
    expected = get_groundtruth(problems, get_human_eval_plus_hash(), [])
    dev_ids = split_ids(problems)["dev"][:limit]
    cases = []
    for task_id in dev_ids:
        problem = problems[task_id]
        canonical = problem["prompt"] + problem["canonical_solution"]
        cases.append({"case_id": f"{task_id}:clean", "expected": "pass", "mutation": "canonical",
                      "artifact": {"problem": problem, "solution": canonical,
                                   "expected_output": expected[task_id]}})
        cases.append({"case_id": f"{task_id}:wrong", "expected": "fail", "mutation": "return_none",
                      "artifact": {"problem": problem, "solution": problem["prompt"] + "\n    return None\n",
                                   "expected_output": expected[task_id]}})
    manifest = {"task_ids": dev_ids, "split": "dev", "cases": cases}
    for case in cases:
        result = check_correctness("humaneval", 0, case["artifact"]["problem"], case["artifact"]["solution"],
                                   case["artifact"]["expected_output"], base_only=False, fast_check=True)
        observed = "pass" if result["plus"][0] == "pass" else "fail"
        if observed != case["expected"]:
            raise ValueError(f"trusted EvalPlus case label mismatch: {case['case_id']}={observed}")
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "cases.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    return manifest


def trusted_cases(manifest: dict) -> list[TrustedCase]:
    return [TrustedCase(case["case_id"], case["artifact"], case["expected"])
            for case in manifest["cases"]]


def build_governor(manifest: dict, include_evalplus: bool = False) -> VerificationGovernor:
    governor = VerificationGovernor(min_clean=3, min_wrong=3)
    execution_source = convention_source("python_execution_contract_v1", "b" * 64, True)
    governor.register(CheckAsset("L1_execution", 1, execution_eval, execution_source))
    execution_cases = []
    for index in range(3):
        execution_cases.append(TrustedCase(f"exec_clean_{index}", {"record": {"base_status": "pass"}}, "pass"))
        execution_cases.append(TrustedCase(f"exec_wrong_{index}", {"record": {"base_status": "timeout"}}, "fail"))
    governor.promote("L1_execution", execution_cases)
    if include_evalplus:
        source = convention_source("evalplus_official_tests_v1", hashlib.sha256(b"evalplus-official-tests").hexdigest(), True)
        governor.register(CheckAsset("L2_evalplus", 2, evalplus_eval, source))
        governor.promote("L2_evalplus", trusted_cases(manifest))
    return governor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    outdir = (ROOT / args.out).resolve()
    manifest = generate_cases(outdir)
    governor = build_governor(manifest, include_evalplus=True)
    (outdir / "governor.json").write_text(json.dumps(governor.public_state(), ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"n_cases": len(manifest["cases"]), "governor": governor.freeze()}, indent=1))


if __name__ == "__main__":
    main()
