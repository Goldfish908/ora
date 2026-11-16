#!/usr/bin/env python3
"""Build deterministic, exposure-aware ID splits for memory→witness experiments."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "memory_witness"
SEED = "memory-witness-cross-domain-v0.1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def allocate(ids: list[str], exposed: set[str], n_dev: int, n_val: int,
             dataset: str) -> dict[str, list[str]]:
    ids = set(ids)
    dev = sorted(ids & exposed)
    remaining = sorted(ids - exposed,
                       key=lambda x: sha256_text(f"{SEED}:{dataset}:{x}"))
    need = n_dev - len(dev)
    dev += sorted(remaining[:need])
    val = sorted(remaining[need:need + n_val])
    sealed = sorted(remaining[need + n_val:])
    assert len(dev) == n_dev, (dataset, len(dev), n_dev)
    assert len(val) == n_val, (dataset, len(val), n_val)
    assert set(dev) & set(exposed) == exposed & ids
    assert not (set(dev) & set(val) or set(dev) & set(sealed) or set(val) & set(sealed))
    assert set(dev) | set(val) | set(sealed) == ids
    return {"dev": dev, "validation": val, "sealed": sealed}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def mamo() -> tuple[Path, list[str], set[str], int, int]:
    path = ROOT / "data/external/mamo/data/optimization/Complex_LP/mamo_complex_lp.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    ids = [str(r["id"]) for r in rows if r.get("Answer") is not None]
    return path, ids, {"1", "2"}, 60, 50


def nlp4lp() -> tuple[Path, list[str], set[str], int, int]:
    path = ROOT / "data/external/ORThought/datasets/processed/NLP4LP/nlp4lp.csv"
    ids = []
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                sol = json.loads(r["solution"])
                info = json.loads(r["problem_info"])
                json.loads(r["parameters"])
            except Exception:
                continue
            if r["problem_type"] not in ("LP", "IP"):
                continue
            if not isinstance(sol, dict) or sol.get("objective") is None:
                continue
            if not info.get("constraints") or not info.get("objective"):
                continue
            ids.append(r["id"])
    exposed = {"prob_000", "prob_001"} | {f"prob_{i:03d}" for i in range(3, 16)}
    return path, ids, exposed, 60, 57


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"version": "v0.1", "seed": SEED,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "datasets": {}}
    for name, loader in (("mamo_complex", mamo), ("nlp4lp", nlp4lp)):
        source, ids, exposed, n_dev, n_val = loader()
        splits = allocate(ids, exposed, n_dev, n_val, name)
        d = OUT / name
        d.mkdir(parents=True, exist_ok=True)
        files = {}
        for split, values in splits.items():
            p = d / f"{split}.txt"
            p.write_text("\n".join(values) + "\n")
            files[split] = {"path": str(p.relative_to(ROOT)), "n": len(values),
                            "sha256": sha256(p)}
        manifest["datasets"][name] = {
            "source": str(source.relative_to(ROOT)), "source_sha256": sha256(source),
            "eligible_n": len(ids), "exposed_ids_forced_dev": sorted(exposed & set(ids)),
            "splits": files,
        }
        print(name, {k: len(v) for k, v in splits.items()})
    p = OUT / "slices_manifest.json"
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    print("manifest", p, "sha256", sha256(p))


if __name__ == "__main__":
    main()
