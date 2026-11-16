#!/usr/bin/env python3
"""Export reference-derived bindings for executor sanity, not asset learning."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.dvsa_linear import reference_bindings  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    model_path = Path(args.model)
    if not model_path.is_absolute():
        model_path = ROOT / model_path
    model = json.loads(model_path.read_text())
    result = reference_bindings(model)
    result["model_sha256"] = hashlib.sha256(model_path.read_bytes()).hexdigest()
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"problem_id": model["problem_id"], "bindings": len(result["bindings"]),
                      "skipped": result["skipped"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
