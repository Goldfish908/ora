#!/usr/bin/env python3
"""Adapt batch oracle artifacts to the read-only Witness cache layout."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ora_agent.oragentbench import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]


def materialize_oracle_cache(source: Path, out: Path, task_names: list[str]) -> dict:
    results_path = source / "oracle_results.json"
    results = read_json(results_path)
    if out.exists() and any(out.iterdir()):
        raise ValueError("oracle cache directory must be new")
    out.mkdir(parents=True, exist_ok=True)
    for name in task_names:
        if name not in results:
            raise ValueError(f"oracle result is missing: {name}")
        app_source = (source / name / "oracle/app").resolve()
        if not app_source.is_dir():
            raise ValueError(f"oracle workspace is missing: {name}")
        oracle_dir = out / name / "oracle"
        oracle_dir.mkdir(parents=True)
        (oracle_dir / "app").symlink_to(app_source, target_is_directory=True)
        write_json(oracle_dir / "result.json", results[name])
    manifest = {
        "source": str(source.resolve()),
        "oracle_results_sha256": hashlib.sha256(results_path.read_bytes()).hexdigest(),
        "task_names": task_names,
        "layout": "task/oracle/{result.json,app -> immutable batch oracle workspace}",
    }
    write_json(out / "cache_manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle-run", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    source = (ROOT / args.oracle_run).resolve()
    out = (ROOT / args.out).resolve()
    config = read_json((ROOT / args.tasks).resolve())
    names = [item["name"] for item in config["tasks"]]
    manifest = materialize_oracle_cache(source, out, names)
    manifest["tasks_sha256"] = hashlib.sha256((ROOT / args.tasks).read_bytes()).hexdigest()
    write_json(out / "cache_manifest.json", manifest)
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
