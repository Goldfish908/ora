#!/usr/bin/env python3
"""Author evidence-scoped invariants instead of free-form checker code."""
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

from ora_agent import llm as llm_mod
from ora_agent.scoped_ir import empty_records, evaluate_spec, extract_spec
from scripts.memory_witness_cegis import load_cells, schema

PROMPT = """You are constructing a deterministic, evidence-scoped semantic audit for an optimization solution.
Return ONLY one JSON object with an "invariants" list. Do not return Python code or markdown.

[PROBLEM]
{question}

[SOLUTION SCHEMA]
{solution_schema}

Each invariant must have this form:
{{
  "invariant_id": "short_rule_id",
  "kind": "constraint" | "objective" | "makespan" | "domain_integer" | "domain_nonnegative",
  "relation": "eq" | "le" | "ge" | "lt" | "gt",
  "lhs": <numeric expression>,
  "rhs": <numeric expression>,
  "source_span": "a short VERBATIM quote copied exactly from the problem"
}}

Numeric expressions may only be finite numbers or objects with one of these forms:
- {{"path": "solution.variables.<actual variable name>"}}
- {{"path": "solution.objective"}}
- {{"add": [expr, ...]}}
- {{"mul": [expr, ...]}}
- {{"max": [expr, ...]}}
- {{"min": [expr, ...]}}
- {{"sub": [left, right]}}
- {{"div": [left, right]}}
- {{"neg": expr}}
- {{"abs": expr}}
- {{"round": expr}}

Rules:
1. Use only actual variable names in the supplied solution schema. For an objective check, use {{"path": "solution.objective"}} on one side and the independently recomputed expression on the other.
2. Every source_span must be copied exactly from the problem and support that specific invariant. Do not fabricate a citation for background knowledge.
3. Add domain_integer only if the source_span explicitly contains integer, whole number, integral, indivisible, whole/discrete units, or equivalent explicit wording. "How many" and a countable noun alone are not enough.
4. Do not infer integer domains from object type. Do not add non-negativity without textual support.
5. Do not add optimality bounds, purchase-sales conservation, repair-inspection relations, or any other requirement absent from the problem.
6. Include only requirements supported by the text. Fewer valid invariants are better than unsupported ones.
7. If a requirement cannot be represented using actual solution variables and constants, omit it rather than inventing a field.
8. For concurrent tasks, parallel completion, or a makespan, set kind="makespan" and use max/min, not add. When several required activities have independent completion times and all must finish, total completion time is max(times), not their sum. Use add only for genuinely sequential additive work.
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_one(pid: str, cells: list[dict], question: str, outdir: Path,
            temperature: float, cfg) -> dict:
    pdir = outdir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    final_path = pdir / "final.json"
    if final_path.exists():
        return json.loads(final_path.read_text())
    prompt = PROMPT.format(question=question, solution_schema=schema(cells))
    t0 = time.time()
    try:
        resp = llm_mod.chat([{"role": "user", "content": prompt}],
                            max_tokens=32768, temperature=temperature,
                            extra={"reasoning_effort": "medium"}, config=cfg)
        text = resp.get("content") or ""
        error = None
    except Exception as exc:
        resp = {"usage": {}}
        text = ""
        error = f"{type(exc).__name__}: {exc}"
    try:
        spec = extract_spec(text) if text else None
        evaluation = evaluate_spec(spec, question, cells, pid) if spec else empty_records(
            cells, [], "no_json_spec")
    except Exception as exc:
        spec = None
        evaluation = empty_records(cells, [], f"{type(exc).__name__}: {exc}")
    usage = resp.get("usage") or {}
    final = {"id": pid, "arm": "scoped_ir", "status": "historical-validation",
             "prompt": prompt, "response_text": text, "error": error,
             "spec": spec, "evaluation": evaluation,
             "finish_reason": resp.get("finish_reason"), "usage": usage,
             "latency_s": round(time.time() - t0, 1)}
    final_path.write_text(json.dumps(final, ensure_ascii=False, indent=1) + "\n")
    (pdir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n")
    print(f"[{pid}][scoped_ir] det={evaluation['detection']:.1%} "
          f"fp={evaluation['false_positive']:.1%} unknown={evaluation['unknown']} "
          f"rejected={evaluation['rejected_count']}", flush=True)
    return final


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", default="work/memory_witness/nlp4lp_artifacts_v2/validation")
    ap.add_argument("--out", default="work/procedural_memory/validation_v0.2/scoped_ir")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--prepare-only", action="store_true")
    args = ap.parse_args()
    artifact_dir = ROOT / args.artifacts
    grouped = load_cells(artifact_dir / "cells.jsonl", args.ids)
    ids = sorted(grouped)[:args.limit] if args.limit else sorted(grouped)
    outdir = ROOT / args.out
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = {"arm": "scoped_ir", "ids": ids, "temperature": args.temperature,
                "model": llm_mod.DEFAULT_MODEL, "artifacts": args.artifacts,
                "artifacts_sha256": sha256(artifact_dir / "cells.jsonl"),
                "script_sha256": sha256(Path(__file__).resolve()),
                "protocol_sha256": sha256(
                    ROOT / "docs/paper/scoped_ir_validation_protocol_v0.2.md")}
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    if args.prepare_only:
        print(json.dumps(manifest, indent=1))
        return
    cfg = llm_mod.load_config()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one, pid, grouped[pid],
                               (artifact_dir / f"{pid}__question.txt").read_text(),
                               outdir, args.temperature, cfg)
                   for pid in ids]
        for future in futures:
            future.result()


if __name__ == "__main__":
    main()
