#!/usr/bin/env python3
"""CEGIS pilot: crystallize NLP4LP solution checks into deterministic witnesses."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod
from scripts.m1_pilot import extract_code

GENERATOR = """You are constructing a deterministic semantic witness for an optimization solution.
The witness must independently check the returned variable values and objective against the natural-language problem, not merely trust that the solver ran.

General lessons from previous optimization-modeling audits:
- Recompute the objective from the decision variables and problem constants.
- Check every explicit resource bound, minimum/maximum requirement, conservation relation, and variable domain.
- A better objective is not evidence of feasibility.
- Do not invent requirements that are absent from the problem.
- A script error is not a violation.

[PROBLEM]
{question}

[SOLUTION SCHEMA]
{schema}

Write one complete Python program. It must:
1. Read solution.json in the current directory.
2. Check all applicable requirements using the numeric values in the problem above.
3. Set violations to a list of objects {{"rule": short_rule_id, "detail": concrete_numeric_explanation}}.
4. Print exactly json.dumps(violations), with an empty list when the solution is valid.
Use only the Python standard library. Output ONLY executable Python code, without markdown fences.
"""

REVISION = """You are revising a deterministic semantic witness using counterexamples from a development-only independent reference audit.

[PROBLEM]
{question}

[CURRENT CHECKER]
{script}

[FAILING CASES]
{cases}

The independent labels are available only for development. Revise the checker so that clean cases produce no violations and the supplied invalid cases are caught with concrete numeric evidence. Keep checks for all problem requirements, not only the displayed cases. Do not hardcode a case's expected output; recompute from problem constants and solution values.

The program must read solution.json and print exactly json.dumps(violations), using only the Python standard library. Output ONLY executable Python code, without markdown fences.
"""


def load_cells(path: Path, ids: list[str] | None) -> dict[str, list[dict]]:
    grouped = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        cell = json.loads(line)
        if ids and cell["id"] not in ids:
            continue
        grouped.setdefault(cell["id"], []).append(cell)
    return grouped


def schema(cells: list[dict]) -> str:
    variables = cells[0]["solution"]["variables"]
    return json.dumps({"variables": {k: "number" for k in variables},
                       "objective": "number"})


def run_check(script: str, solution: dict, timeout: int = 10) -> dict:
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        (work / "solution.json").write_text(json.dumps(solution))
        (work / "check.py").write_text(script)
        try:
            p = subprocess.run([sys.executable, "check.py"], cwd=work,
                               capture_output=True, text=True, timeout=timeout)
            text = p.stdout.strip()
            if p.returncode:
                return {"status": "error", "fired": False,
                        "error": (p.stderr or text)[-1000:]}
            match = re.search(r"(\[.*\])", text, re.S)
            if not match:
                return {"status": "error", "fired": False,
                        "error": f"no JSON list in stdout: {text[-500:]}"}
            violations = json.loads(match.group(0))
            if not isinstance(violations, list):
                raise TypeError("output is not a list")
            genuine, unknown_evidence = [], []
            for item in violations:
                kind = str(item.get("kind", "")).lower() if isinstance(item, dict) else ""
                rule = str(item.get("rule", "")).lower() if isinstance(item, dict) else ""
                is_unknown = (kind == "unknown" or rule.startswith("valid_")
                              or rule.startswith("missing_") or rule.startswith("type_")
                              or any(marker in rule for marker in
                                     ("missing", "not_found", "non_numeric",
                                      "schema", "parse_error", "read_error"))
                              or rule in {"type_check", "parse_error", "invalid_solution"})
                (unknown_evidence if is_unknown else genuine).append(item)
            return {"status": "unknown" if unknown_evidence else "ok",
                    "fired": bool(genuine), "violations": genuine[:10],
                    "unknown_evidence": unknown_evidence[:10]}
        except Exception as e:
            return {"status": "error", "fired": False,
                    "error": f"{type(e).__name__}: {e}"}


def evaluate(script: str, cells: list[dict]) -> dict:
    records = []
    for cell in cells:
        result = run_check(script, cell["solution"])
        records.append({"key": cell["key"], "wrong": cell["wrong"],
                        "mutation": cell["mutation"],
                        "reference_violations": cell["reference_violations"],
                        **result})
    wrong = [r for r in records if r["wrong"]]
    clean = [r for r in records if not r["wrong"]]
    tp = sum(r["fired"] for r in wrong)
    fn = len(wrong) - tp
    fp = sum(r["fired"] for r in clean)
    tn = len(clean) - fp
    unknown = sum(r["status"] != "ok" for r in records)
    detection = tp / max(tp + fn, 1)
    fpr = fp / max(fp + tn, 1)
    return {"records": records, "tp": tp, "fn": fn, "fp": fp, "tn": tn,
            "unknown": unknown, "detection": detection, "false_positive": fpr,
            "dev_passed": unknown == 0 and fp == 0 and detection >= 0.6}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", default="work/memory_witness/nlp4lp_artifacts/dev")
    ap.add_argument("--out", default="work/memory_witness/cegis_dev")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-repairs", type=int, default=2)
    ap.add_argument("--memory-from")
    ap.add_argument("--freeze-memory", action="store_true")
    ap.add_argument("--temperature", type=float, default=0.2)
    args = ap.parse_args()
    artifact_dir = ROOT / args.artifacts
    grouped = load_cells(artifact_dir / "cells.jsonl", args.ids)
    ids = sorted(grouped)[:args.limit] if args.limit else sorted(grouped)
    outdir = ROOT / args.out
    outdir.mkdir(parents=True, exist_ok=True)
    cfg = llm_mod.load_config()
    successful_memory = []
    if args.memory_from:
        for path in sorted((ROOT / args.memory_from).glob("*/final.json")):
            final = json.loads(path.read_text())
            if final.get("status") == "dev-passed" and final.get("script"):
                successful_memory.append(final["script"][:4000])

    def ask(prompt: str):
        return llm_mod.chat([{"role": "user", "content": prompt}],
                            max_tokens=32768, temperature=args.temperature,
                            extra={"reasoning_effort": "medium"}, config=cfg)

    for pid in ids:
        cells = grouped[pid]
        by_key = {c["key"]: c for c in cells}
        question = (artifact_dir / f"{pid}__question.txt").read_text()
        pdir = outdir / pid
        pdir.mkdir(parents=True, exist_ok=True)
        if (pdir / "final.json").exists():
            print(f"[{pid}] exists, skip", flush=True)
            continue
        memory_text = ""
        if successful_memory:
            memory_text = ("\n\nVerified checker examples from earlier development problems "
                           "(adapt the mechanism, not their constants):\n"
                           + "\n\n".join(successful_memory[-2:]))
        prompt = GENERATOR.format(question=question, schema=schema(cells)) + memory_text
        attempts = []
        best = None
        t0 = time.time()
        for rnd in range(args.max_repairs + 1):
            if rnd == 0:
                resp = ask(prompt)
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
                revision = REVISION.format(
                    question=question, script=best["script"],
                    cases=json.dumps(cases[:4], ensure_ascii=False, indent=1))
                resp = ask(revision)
            script = extract_code(resp.get("content") or "")
            if not script:
                evaluation = {"records": [], "tp": 0, "fn": 0, "fp": 0, "tn": 0,
                              "unknown": len(cells), "detection": 0.0,
                              "false_positive": 0.0, "dev_passed": False}
            else:
                evaluation = evaluate(script, cells)
            attempt = {"round": rnd, "script": script, "evaluation": evaluation,
                       "finish_reason": resp.get("finish_reason"),
                       "usage": resp.get("usage")}
            attempts.append(attempt)
            (pdir / f"attempt_{rnd}.json").write_text(
                json.dumps(attempt, ensure_ascii=False, indent=1) + "\n")
            (pdir / f"attempt_{rnd}.py").write_text(script or "")
            key = (evaluation["fp"] == 0, evaluation["detection"], -evaluation["unknown"])
            if best is None or key > best["key"]:
                best = {**attempt, "key": key}
            print(f"[{pid}] r{rnd} det={evaluation['detection']:.1%} "
                  f"fp={evaluation['false_positive']:.1%} unknown={evaluation['unknown']} "
                  f"dev_pass={evaluation['dev_passed']}", flush=True)
            if evaluation["dev_passed"]:
                best = {**attempt, "key": key}
                break
        status = "dev-passed" if best["evaluation"]["dev_passed"] else "candidate"
        if args.freeze_memory:
            status = "frozen-evaluation"
        final = {"id": pid, "status": status,
                 "best_round": best["round"], "evaluation": best["evaluation"],
                 "attempts": len(attempts), "latency_s": round(time.time() - t0, 1),
                 "script": best["script"]}
        (pdir / "final.json").write_text(json.dumps(final, ensure_ascii=False, indent=1) + "\n")
        (pdir / "witness.py").write_text(best["script"] or "")
        if status == "dev-passed" and not args.freeze_memory:
            successful_memory.append(best["script"][:4000])


if __name__ == "__main__":
    main()
