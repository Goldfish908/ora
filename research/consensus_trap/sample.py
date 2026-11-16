#!/usr/bin/env python3
"""Draw K independent zero-shot candidates per RetailOpt scenario for the consensus-trap analysis.

Same generation and scoring path as `scripts/m1_pilot.py --prompt-mode schema_sol` (thinking on,
temperature 0.6, no priors, no repair): each sample is executed, graded against the reference
objective, and re-verified by the RetailOpt witness. Samples are independent; nothing is fed back.

Usage (from the repo root on the intranet machine):
    source ~/.leagent_env
    python3 research/consensus_trap/sample.py --k 8 --limit 6 --out runs/consensus_trap/smoke
    python3 research/consensus_trap/sample.py --k 8 --workers 16 --out runs/consensus_trap/retail_k8

Output: <out>/samples.jsonl, one row per (scenario_id, sample_index), m1_pilot-compatible fields
plus sample_index and code_sha256. Re-running with the same --out resumes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from scripts.m1_pilot import (DATA, SCHEMA_PRELUDE, SCIP_OUTPUT_FORMAT_SOL,  # noqa: E402
                              adapt_prompt_schema, extract_code, grade, run_code, run_witness)

_lock = threading.Lock()


def select_rows(args) -> list[dict]:
    source = Path(args.scenarios_file) if args.scenarios_file else DATA
    rows = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    if not args.scenarios_file:
        rows = [row for row in rows if row["scenario_id"].endswith(f"_{args.variant}")]
    if args.families:
        tags = tuple(f"_f{family.lower().lstrip('f')}_" for family in args.families)
        rows = [row for row in rows if any(tag in row["scenario_id"] for tag in tags)]
    rows.sort(key=lambda row: row["scenario_id"])
    return rows[: args.limit] if args.limit else rows


def draw(row: dict, index: int, out_dir: Path, cfg, out_path: Path) -> None:
    sid = row["scenario_id"]
    prompt = adapt_prompt_schema(row["prompt_schema"], SCIP_OUTPUT_FORMAT_SOL)
    rec = {"scenario_id": sid, "sample_index": index, "thinking": "on", "prompt_mode": "schema_sol",
           "reference_objective": row["reference_objective"],
           "reference_status": row["reference_status"]}
    started = time.time()
    try:
        resp = llm_mod.chat([{"role": "user", "content": prompt}], max_tokens=32768, temperature=0.6,
                            extra={"reasoning_effort": "medium"}, config=cfg)
        text = resp.get("content") or ""
        usage = resp.get("usage") or {}
        rec.update(model=resp.get("model"), finish_reason=resp.get("finish_reason"),
                   completion_tokens=usage.get("completion_tokens"),
                   reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens"))
        error = None
    except Exception as exc:
        text, error = "", f"{type(exc).__name__}: {exc}"
    rec["llm_latency_s"] = round(time.time() - started, 1)
    if error:
        rec.update(exec_status="llm_error", error=error)
    else:
        sandbox = out_dir / "sandbox" / f"{sid}__s{index:02d}"
        sandbox.mkdir(parents=True, exist_ok=True)
        (sandbox / "data.json").write_text(row["data"])
        code = SCHEMA_PRELUDE + extract_code(text)
        rec["code_sha256"] = hashlib.sha256(code.encode()).hexdigest()
        rec.update(run_code(code, sandbox))
        rec["grade"] = grade(rec.get("objective"), row["reference_objective"], rec.get("solver_status"))
        rec.update(run_witness(row, sandbox))
    with _lock, out_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[{sid}][s{index:02d}] {rec.get('exec_status')} grade={rec.get('grade')} "
          f"witness={rec.get('witness', '-')} llm={rec['llm_latency_s']}s", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--families", nargs="*", default=None)
    parser.add_argument("--variant", default="v0")
    parser.add_argument("--scenarios-file", default=None)
    parser.add_argument("--retry-errors", action="store_true", help="redo samples that ended in llm_error")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    rows = select_rows(args)
    if not rows:
        raise SystemExit("no scenarios selected")
    out_dir = (ROOT / args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "samples.jsonl"
    done = set()
    if out_path.exists():
        kept = []
        for line in out_path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if args.retry_errors and rec.get("exec_status") == "llm_error":
                continue
            done.add((rec["scenario_id"], rec["sample_index"]))
            kept.append(line)
        if args.retry_errors:
            out_path.write_text("".join(line + "\n" for line in kept))
    cfg = llm_mod.load_config()
    (out_dir / "run_config.json").write_text(json.dumps(
        {"model": cfg.model, "base_url": cfg.base_url, "k": args.k, "temperature": 0.6,
         "reasoning_effort": "medium", "max_tokens": 32768, "prompt_mode": "schema_sol",
         "priors": None, "repair": False, "n_scenarios": len(rows),
         "scenario_ids": [row["scenario_id"] for row in rows],
         "dataset_sha256": hashlib.sha256((Path(args.scenarios_file) if args.scenarios_file else DATA)
                                          .read_bytes()).hexdigest()}, indent=1) + "\n")
    jobs = [(row, index) for row in rows for index in range(args.k) if (row["scenario_id"], index) not in done]
    print(f"{len(rows)} scenarios x k={args.k}: {len(jobs)} samples to draw ({len(done)} already done)", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in [pool.submit(draw, row, index, out_dir, cfg, out_path) for row, index in jobs]:
            future.result()


if __name__ == "__main__":
    main()
