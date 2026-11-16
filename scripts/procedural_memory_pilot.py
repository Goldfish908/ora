#!/usr/bin/env python3
"""Paired dev-only comparison of declarative and procedural audit memory."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.memory_witness_cegis import REVISION, evaluate, load_cells, schema
from scripts.m1_pilot import extract_code
from ora_agent import llm as llm_mod

ARMS = ("zero", "text", "procedure", "combined", "procedure_cegis")

TEXT_GUIDANCE = """General declarative audit lessons:
- Recompute the objective from decision variables and problem constants.
- Check explicit resource bounds, minimum/maximum requirements, conservation relations, and variable domains.
- A better objective is not evidence of feasibility.
- Do not invent requirements absent from the problem.
- A script error is not a violation."""

PROCEDURE_GUIDANCE = """General diagnostic and validation procedure:
1. Inventory every decision variable, its unit, domain, and complete index/quantifier scope.
2. Make a requirement ledger from the text: objective terms, explicit bounds, conservation relations, and variable domains. Preserve each requirement's subject and scope.
3. For every ledger entry, choose an independent numeric recomputation using returned variables and problem constants. Do not merely restate solver status.
4. Recompute the objective separately from the constraints, then check variable domains, including integrality only when justified by the problem.
5. Mentally construct a clean case that must pass and a targeted counterexample that must fire. Check that your implementation distinguishes them rather than rejecting everything.
6. If a requirement cannot be evaluated from the supplied solution schema, do not fabricate a violation. Emit an object with "kind": "unknown" and a concrete explanation. Missing data or script failure is not semantic proof.
7. Review the finished script for aggregation scope, units, time/index boundaries, and accidental rejection of valid solutions."""

BASE = """You are constructing a deterministic semantic witness for an optimization solution.
Independently check returned variable values and the objective against the natural-language problem, rather than trusting that the solver ran.

[PROBLEM]
{question}

[SOLUTION SCHEMA]
{schema}

Write one complete Python program. It must:
1. Read solution.json in the current directory.
2. Check applicable requirements using numeric values in the problem above.
3. Set violations to a list of objects {{"rule": short_rule_id, "detail": concrete_numeric_explanation}}.
4. Print exactly json.dumps(violations), with an empty list when the solution is valid.
Use only the Python standard library. Output ONLY executable Python code, without markdown fences.
"""


def build_prompt(arm: str, question: str, solution_schema: str) -> str:
    if arm not in ARMS:
        raise ValueError(f"unknown arm: {arm}")
    guidance = []
    if arm in ("text", "combined"):
        guidance.append(TEXT_GUIDANCE)
    if arm in ("procedure", "combined", "procedure_cegis"):
        guidance.append(PROCEDURE_GUIDANCE)
    prefix = "\n\n".join(guidance)
    return (prefix + "\n\n" if prefix else "") + BASE.format(
        question=question, schema=solution_schema)


def empty_evaluation(n: int) -> dict:
    return {"records": [], "tp": 0, "fn": 0, "fp": 0, "tn": 0,
            "unknown": n, "detection": 0.0, "false_positive": 0.0,
            "dev_passed": False}


def usage_totals(attempts: list[dict]) -> dict:
    prompt = sum((a.get("usage") or {}).get("prompt_tokens", 0) or 0 for a in attempts)
    completion = sum((a.get("usage") or {}).get("completion_tokens", 0) or 0 for a in attempts)
    return {"prompt_tokens": prompt, "completion_tokens": completion,
            "total_tokens": prompt + completion}


def run_one(pid: str, arm: str, cells: list[dict], question: str,
            outdir: Path, max_repairs: int, temperature: float, cfg,
            init_from: Path = None) -> dict:
    pdir = outdir / arm / pid
    pdir.mkdir(parents=True, exist_ok=True)
    final_path = pdir / "final.json"
    if final_path.exists():
        return json.loads(final_path.read_text())
    by_key = {c["key"]: c for c in cells}
    prompt = build_prompt(arm, question, schema(cells))
    attempts = []
    best = None
    start_rnd = 0
    if init_from is not None:
        source = init_from / pid / "witness.py"
        script = source.read_text() if source.exists() else ""
        evaluation = evaluate(script, cells) if script else empty_evaluation(len(cells))
        key = (evaluation["fp"] == 0, evaluation["detection"], -evaluation["unknown"])
        best = {"round": 0, "arm": arm, "prompt": None, "response_text": None,
                "error": None, "script": script, "evaluation": evaluation,
                "finish_reason": "reused", "usage": {}, "key": key,
                "reused_from": str(source)}
        attempts.append({k: v for k, v in best.items() if k != "key"})
        (pdir / "attempt_0.json").write_text(
            json.dumps(attempts[0], ensure_ascii=False, indent=1) + "\n")
        (pdir / "attempt_0.py").write_text(script)
        start_rnd = 1
    t0 = time.time()
    for rnd in range(start_rnd, max_repairs + 1):
        if rnd == 0:
            current_prompt = prompt
        else:
            cases = []
            for r in best["evaluation"]["records"]:
                failed = ((r["wrong"] and not r["fired"])
                          or (not r["wrong"] and r["fired"])
                          or r["status"] != "ok")
                if not failed:
                    continue
                item = {k: r.get(k) for k in
                        ("key", "wrong", "mutation", "reference_violations",
                         "status", "fired", "error", "violations")}
                item["solution"] = by_key[r["key"]]["solution"]
                cases.append(item)
            current_prompt = REVISION.format(
                question=question, script=best["script"],
                cases=json.dumps(cases[:4], ensure_ascii=False, indent=1))
        try:
            resp = llm_mod.chat([{"role": "user", "content": current_prompt}],
                                max_tokens=32768, temperature=temperature,
                                extra={"reasoning_effort": "medium"}, config=cfg)
            text = resp.get("content") or ""
            error = None
        except Exception as exc:
            resp = {"usage": {}}
            text = ""
            error = f"{type(exc).__name__}: {exc}"
        script = extract_code(text)
        evaluation = evaluate(script, cells) if script else empty_evaluation(len(cells))
        attempt = {"round": rnd, "arm": arm, "prompt": current_prompt,
                   "response_text": text, "error": error, "script": script,
                   "evaluation": evaluation,
                   "finish_reason": resp.get("finish_reason"),
                   "usage": resp.get("usage")}
        attempts.append(attempt)
        (pdir / f"attempt_{rnd}.json").write_text(
            json.dumps(attempt, ensure_ascii=False, indent=1) + "\n")
        (pdir / f"attempt_{rnd}.py").write_text(script or "")
        key = (evaluation["fp"] == 0, evaluation["detection"], -evaluation["unknown"])
        if best is None or key > best["key"]:
            best = {**attempt, "key": key}
        print(f"[{pid}][{arm}] r{rnd} det={evaluation['detection']:.1%} "
              f"fp={evaluation['false_positive']:.1%} unknown={evaluation['unknown']}",
              flush=True)
        if evaluation["dev_passed"]:
            best = {**attempt, "key": key}
            break
    final = {"id": pid, "arm": arm, "status": "dev-pilot",
             "best_round": best["round"], "evaluation": best["evaluation"],
             "attempts": len(attempts), "latency_s": round(time.time() - t0, 1),
             "usage": usage_totals(attempts), "script": best["script"]}
    final_path.write_text(json.dumps(final, ensure_ascii=False, indent=1) + "\n")
    (pdir / "witness.py").write_text(best["script"] or "")
    return final


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", default="work/memory_witness/nlp4lp_artifacts_v2/dev")
    ap.add_argument("--out", default="work/procedural_memory/pilot_v0.1")
    ap.add_argument("--arms", nargs="+", choices=ARMS,
                    default=["zero", "text", "procedure", "combined"])
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-repairs", type=int, default=0)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--init-from")
    ap.add_argument("--prepare-only", action="store_true")
    args = ap.parse_args()
    artifact_dir = ROOT / args.artifacts
    grouped = load_cells(artifact_dir / "cells.jsonl", args.ids)
    ids = sorted(grouped)[:args.limit] if args.limit else sorted(grouped)
    outdir = ROOT / args.out
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = {"arms": args.arms, "ids": ids, "max_repairs": args.max_repairs,
                "temperature": args.temperature,
                "model": llm_mod.DEFAULT_MODEL,
                "artifacts": args.artifacts,
                "artifacts_sha256": sha256(artifact_dir / "cells.jsonl"),
                "script_sha256": sha256(Path(__file__).resolve()),
                "protocol_sha256": sha256(
                    ROOT / "docs/paper/procedural_memory_pilot_protocol_v0.1.md"),
                "init_from": args.init_from}
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    if args.prepare_only:
        print(json.dumps(manifest, indent=1))
        return
    cfg = llm_mod.load_config()
    init_from = ROOT / args.init_from if args.init_from else None
    tasks = [(pid, arm, grouped[pid],
              (artifact_dir / f"{pid}__question.txt").read_text())
             for pid in ids for arm in args.arms]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one, pid, arm, cells, question, outdir,
                               args.max_repairs, args.temperature, cfg, init_from)
                   for pid, arm, cells, question in tasks]
        for future in futures:
            future.result()


if __name__ == "__main__":
    main()
