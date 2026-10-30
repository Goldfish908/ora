"""m2gen CLI: generate validated controlled-M2 instances.

Usage:
  python3 -m m2gen.emit --structure inv_cap --n 2 --seed 0 \
      --out controlled_m2/gen
  python3 -m m2gen.emit --all --n 2 --seed 0 --out controlled_m2/gen
  python3 -m m2gen.emit --structure inv_cap --n 1 --params FILE \
      --out /tmp/m2reg   (fixed params; no discriminability resampling)
"""

import argparse
import json
from pathlib import Path

from .core import SPEC, generate


def main() -> int:
    ap = argparse.ArgumentParser(prog="m2gen.emit")
    ap.add_argument("--structure", choices=list(_structures()))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--n", type=int, default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--params", type=Path, default=None,
                    help="fixed params.json; skips sampling/resampling")
    args = ap.parse_args()

    struct_ids = list(_structures()) if args.all else [args.structure]
    if not args.structure and not args.all:
        ap.error("give --structure or --all")
    fixed = json.loads(args.params.read_text()) if args.params else None

    n_bad = 0
    for sid in struct_ids:
        n = args.n or SPEC["structures"][sid]["n_instances_default"]
        made = generate(sid, n, args.seed, args.out, fixed_params=fixed)
        for inst, ok, report in made:
            line = " ".join(
                f"{a}={e['verdict']}({e['objective']})"
                for a, e in report.items())
            print(f"{inst.name}: {'OK ' if ok else 'BAD'} {line}")
            n_bad += 0 if ok else 1
        if len(made) < n:
            print(f"{sid}: only {len(made)}/{n} valid instances "
                  f"within draw budget")
            n_bad += 1
    return 1 if n_bad else 0


def _structures():
    return SPEC["structures"].keys()


if __name__ == "__main__":
    raise SystemExit(main())
