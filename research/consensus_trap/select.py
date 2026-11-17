#!/usr/bin/env python3
"""Stratified RetailOpt slice for the consensus-trap sampler.

Avoids `--limit N` (name-order bias). Groups by major family (F1–F8) and
subfamily (`retail_f7_transshipment` from `retail_f7_transshipment_v3`), then
allocates slots so every major family is covered. Prefers the `v0` variant when
present (matches prior baselines); otherwise the lowest-numbered variant.

Usage (from repo root):
  python3 research/consensus_trap/select.py --n 48 \\
    --out runs/consensus_trap/slice48.jsonl
  python3 research/consensus_trap/sample.py --k 8 --workers 16 \\
    --scenarios-file runs/consensus_trap/slice48.jsonl \\
    --out runs/consensus_trap/retail_k8_s48
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "data" / "m1_retailopt" / "retailopt_190.jsonl"
SID_RE = re.compile(r"^(?P<sub>retail_(?P<major>f\d+)_.+?)_(?P<var>v\d+)$")


def parse_sid(sid: str) -> tuple[str, str, str]:
    match = SID_RE.match(sid)
    if not match:
        raise ValueError(f"unrecognized scenario_id: {sid}")
    return match.group("major").upper(), match.group("sub"), match.group("var")


def load_rows(path: Path, variant_suffix: str | None) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if variant_suffix:
        rows = [row for row in rows if row["scenario_id"].endswith(f"_{variant_suffix}")]
    return rows


def choose_variant(variants: dict[str, dict]) -> dict:
    if "v0" in variants:
        return variants["v0"]
    return variants[min(variants, key=lambda name: (len(name), name))]


def allocate(n: int, sizes: dict[str, int], cap: dict[str, int] | None = None) -> dict[str, int]:
    """Proportional integer allocation with largest-remainder.

    Every non-empty group gets ≥1 when n ≥ #groups. `cap[key]` (default unlimited)
    bounds how many slots a group may receive — use (#subfamilies × #variants) so
    n can exceed the subfamily count.
    """
    keys = [key for key, size in sizes.items() if size > 0]
    if n <= 0 or not keys:
        return {key: 0 for key in sizes}
    if n < len(keys):
        raise SystemExit(f"--n={n} is smaller than the number of major families ({len(keys)}); "
                         f"raise --n or pass --families to restrict")
    limit = {key: (cap or {}).get(key, 10**9) for key in keys}
    if sum(limit[key] for key in keys) < n:
        raise SystemExit(f"--n={n} exceeds available scenarios ({sum(limit.values())})")
    total = sum(sizes[key] for key in keys)
    raw = {key: n * sizes[key] / total for key in keys}
    base = {key: min(limit[key], max(1, math.floor(raw[key]))) for key in keys}
    while sum(base.values()) > n:
        key = max((k for k in keys if base[k] > 1),
                  key=lambda k: (base[k] - raw[k], sizes[k], k), default=None)
        if key is None:
            break
        base[key] -= 1
    remainders = sorted(keys, key=lambda k: (raw[k] - math.floor(raw[k]), -sizes[k], k), reverse=True)
    while sum(base.values()) < n:
        progressed = False
        for key in remainders:
            if base[key] < limit[key]:
                base[key] += 1
                progressed = True
                if sum(base.values()) >= n:
                    break
        if not progressed:
            break
    return {key: base.get(key, 0) for key in sizes}


def select_rows(rows: list[dict], n: int, seed: int, families: set[str] | None,
                prefer_phantom_heavy: bool) -> list[dict]:
    by_major: dict[str, dict[str, dict[str, dict]]] = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        major, sub, var = parse_sid(row["scenario_id"])
        if families and major not in families:
            continue
        by_major[major][sub][var] = row
    if not by_major:
        raise SystemExit("no scenarios left after filtering")

    sizes = {major: len(subs) for major, subs in by_major.items()}
    caps = {major: sum(len(variants) for variants in subs.values())
            for major, subs in by_major.items()}
    budget = allocate(n, sizes, caps)
    if prefer_phantom_heavy:
        for heavy in ("F3", "F7"):
            if heavy in budget and budget[heavy] < caps.get(heavy, 0):
                donor = max((m for m in budget if m not in ("F3", "F7") and budget[m] > 1),
                            key=lambda m: budget[m], default=None)
                if donor is not None:
                    budget[heavy] += 1
                    budget[donor] -= 1

    rng = random.Random(seed)
    chosen: list[dict] = []
    for major in sorted(by_major):
        need = budget.get(major, 0)
        subs = list(by_major[major].items())
        rng.shuffle(subs)
        # first pass: one preferred variant per subfamily
        picked: list[dict] = []
        for sub, variants in subs:
            if len(picked) >= need:
                break
            picked.append(choose_variant(variants))
        # second pass: extra variants if this major still needs slots
        if len(picked) < need:
            extras = []
            taken_ids = {row["scenario_id"] for row in picked}
            for sub, variants in subs:
                for name in sorted(variants):
                    row = variants[name]
                    if row["scenario_id"] not in taken_ids:
                        extras.append(row)
            rng.shuffle(extras)
            picked.extend(extras[: need - len(picked)])
        chosen.extend(picked[:need])

    chosen.sort(key=lambda row: row["scenario_id"])
    if len(chosen) < n:
        raise SystemExit(f"only {len(chosen)} scenarios available after stratification; lower --n")
    return chosen[:n]


def summarize(rows: list[dict]) -> dict:
    majors = defaultdict(int)
    subs = set()
    for row in rows:
        major, sub, _ = parse_sid(row["scenario_id"])
        majors[major] += 1
        subs.add(sub)
    return {"n": len(rows), "n_major_families": len(majors), "n_subfamilies": len(subs),
            "per_major": dict(sorted(majors.items())),
            "scenario_ids": [row["scenario_id"] for row in rows]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--n", type=int, default=48, help="target number of scenarios")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--families", nargs="*", default=None, help="optional major families, e.g. F1 F3 F7")
    parser.add_argument("--variant", default=None, help="if set, only keep this variant suffix (e.g. v0)")
    parser.add_argument("--prefer-phantom-heavy", action="store_true", default=True,
                        help="nudge +1 slot toward F3/F7 (default on)")
    parser.add_argument("--no-prefer-phantom-heavy", action="store_false", dest="prefer_phantom_heavy")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    path = Path(args.data)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise SystemExit(f"dataset not found: {path}")
    families = None
    if args.families:
        families = set()
        for name in args.families:
            token = name.upper()
            families.add(token if token.startswith("F") else f"F{token}")
    rows = load_rows(path, args.variant)
    selected = select_rows(rows, args.n, args.seed, families, args.prefer_phantom_heavy)
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in selected))
    meta = summarize(selected)
    meta.update(seed=args.seed, data=str(path), prefer_phantom_heavy=args.prefer_phantom_heavy)
    (out.parent / (out.stem + "_manifest.json")).write_text(json.dumps(meta, indent=1) + "\n")
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
