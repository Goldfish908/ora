#!/usr/bin/env python3
"""Validate scoped semantic assets on independent clean and wrong cases."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.scoped_assets import load_asset, validate_asset


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="assets/scoped_ir/registry_v0.1.json")
    ap.add_argument("--out", default="work/scoped_assets/validation_v0.1.json")
    args = ap.parse_args()
    registry_path = ROOT / args.registry
    registry = json.loads(registry_path.read_text())
    results = []
    for name in registry["assets"]:
        asset = load_asset(registry_path.parent / name)
        result = validate_asset(asset)
        results.append(result)
        print(f"{result['mechanism_id']}: {result['status']} "
              f"det={result['evaluation']['detection']:.1%} "
              f"fp={result['evaluation']['false_positive']:.1%} "
              f"unknown={result['evaluation']['unknown']}", flush=True)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"schema_version": registry["schema_version"],
                               "assets": results}, ensure_ascii=False, indent=1) + "\n")
    if any(result["status"] != "validated" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
