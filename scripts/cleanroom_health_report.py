#!/usr/bin/env python3
"""Bind frozen task roles to their original oracle/official health evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ora_agent.oragentbench import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]


def collect_health(roles_path: Path, sources: dict[str, Path]) -> dict:
    roles = read_json(roles_path)
    tasks = roles["tasks"]
    names = [item["name"] for item in tasks]
    if len(names) != len(set(names)):
        raise ValueError("frozen roles contain duplicate tasks")
    rows = []
    for item in tasks:
        name = item["name"]
        if name not in sources:
            raise ValueError(f"missing oracle evidence: {name}")
        path = sources[name].resolve()
        document = read_json(path)
        result = document.get(name, document)
        metrics = result.get("metrics") or {}
        if not metrics.get("true_correct"):
            raise ValueError(f"oracle/official health did not pass: {name}")
        implementation_path = path.parent / "implementation.json"
        rows.append({
            "task": name,
            "domain": item["domain"],
            "split": item["split"],
            "role": item.get("role"),
            "feasible": metrics["feasible"],
            "quality": metrics["quality"],
            "objective": metrics.get("objective"),
            "source": str(path),
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "implementation_sha256": hashlib.sha256(implementation_path.read_bytes()).hexdigest()
            if implementation_path.exists() else None,
        })
    return {
        "version": roles["version"],
        "n_tasks": len(rows),
        "n_healthy": sum(row["feasible"] and row["quality"] > 0.4 for row in rows),
        "all_true_correct": all(row["feasible"] and row["quality"] > 0.4 for row in rows),
        "roles_sha256": hashlib.sha256(roles_path.read_bytes()).hexdigest(),
        "tasks": rows,
        "evidence_note": "Original oracle/official health only; Qwen outcomes were not used to select these tasks.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roles", required=True)
    parser.add_argument("--source", action="append", required=True,
                        help="task_name=oracle_results.json or task/oracle/result.json")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    sources = {}
    for item in args.source:
        name, separator, value = item.partition("=")
        if not separator or not name or not value or name in sources:
            parser.error("each --source must be a unique task_name=path mapping")
        sources[name] = (ROOT / value).resolve()
    roles_path = (ROOT / args.roles).resolve()
    summary = collect_health(roles_path, sources)
    out = (ROOT / args.out).resolve()
    write_json(out, summary)
    print(json.dumps({"n_tasks": summary["n_tasks"], "n_healthy": summary["n_healthy"],
                      "out": str(out)}, indent=1))


if __name__ == "__main__":
    main()
