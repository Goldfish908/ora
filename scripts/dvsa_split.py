#!/usr/bin/env python3
"""Create the deterministic DVSA/BWOR split without inspecting problem content."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/external/or_llm_agent/data/datasets/bwor.jsonl"
OUT = ROOT / "data/dvsa"
SEED = "dvsa-bwor-v0.1"
SIZES = {"dev": 16, "validation": 16, "frozen": 41}


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def allocate(ids, seed=SEED, sizes=None):
    sizes = sizes or SIZES
    ordered = sorted(set(ids), key=lambda item: digest(f"{seed}:{item}"))
    if len(ordered) != len(ids) or len(ordered) != sum(sizes.values()):
        raise ValueError("IDs must be unique and match the split sizes")
    dev = sorted(ordered[:sizes["dev"]])
    validation = sorted(ordered[sizes["dev"]:sizes["dev"] + sizes["validation"]])
    frozen = sorted(ordered[sizes["dev"] + sizes["validation"]:])
    return {"dev": dev, "validation": validation, "frozen": frozen}


def build():
    raw = SOURCE.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    selected = [row for row in rows
                if row["solution_status"] == "optimal"
                and row["problem_type"] in {"LP", "IP", "MIP"}]
    ids = [str(row["id"]) for row in selected]
    splits = allocate(ids)
    files = {}
    for name, values in splits.items():
        content = "\n".join(values) + "\n"
        files[name] = {"path": f"data/dvsa/bwor/{name}.txt",
                       "n": len(values), "sha256": digest(content),
                       "content": content}
    manifest = {
        "protocol_version": "dvsa-bwor-v0.1",
        "seed": SEED,
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "license": "CC-BY-4.0",
        "source_release_n": len(rows),
        "selection": {"solution_status": "optimal",
                      "problem_type": ["LP", "IP", "MIP"],
                      "selected_before_problem_content": True},
        "eligible_n": len(selected),
        "selected_domain_counts": dict(sorted(Counter(
            row["domain"] for row in selected).items())),
        "excluded_by_metadata": dict(sorted(Counter(
            f"{row['solution_status']}:{row['problem_type']}" for row in rows
            if row not in selected).items())),
        "exposed_ids_forced_dev": [],
        "exposure": {
            "project_problem_level_runs_before_dvsa": 0,
            "evidence": "No BWOR references in project scripts/work; prior aggregate research only; local legacy file matched release structurally without exposing content.",
        },
        "splits": {name: {k: v for k, v in record.items() if k != "content"}
                   for name, record in files.items()},
        "frozen_policy": "Frozen questions and results must not propose, select, revise or tune assets, prompts, bindings, thresholds or budgets. Blind references are frozen before candidate evaluation.",
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False,
                                indent=2, sort_keys=True) + "\n").encode("utf-8")
    return manifest, files, manifest_bytes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    manifest, files, manifest_bytes = build()
    manifest_path = OUT / "splits_manifest.json"
    if args.check:
        for record in files.values():
            path = ROOT / record["path"]
            assert path.exists(), f"missing split: {path}"
            assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"], path
        assert manifest_path.read_bytes() == manifest_bytes, "manifest is not reproducible"
        print("DVSA split reproducibility: OK")
        return
    for record in files.values():
        path = ROOT / record["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record["content"], encoding="utf-8")
    manifest_path.write_bytes(manifest_bytes)
    print(json.dumps({"source_sha256": manifest["source_sha256"],
                      "splits": manifest["splits"]}, indent=2))
    print(f"manifest sha256: {hashlib.sha256(manifest_bytes).hexdigest()}")


if __name__ == "__main__":
    main()
