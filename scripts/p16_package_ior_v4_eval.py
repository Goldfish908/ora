#!/usr/bin/env python3
"""P16: package IndustryOR eval bundle for remote v4 generative eval.

Emits work/judge_data/v4_eval_ior/{cells.jsonl, prompts.json} and tars the
instrumented solutions (work/judge_data/ior_sandbox, from p13 stage 0) for
upload. No LLM calls, no judging — pure packaging. IndustryOR stays a
zero-iteration final-validation set.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.p13_active_judge_ior2 import DECIDER_TEMPLATE, PLANNER_PROMPT  # noqa: E402

CELLS = ROOT / "runs" / "industryor" / "industryor_judge_cells.jsonl"
SANDBOX = ROOT / "work" / "judge_data" / "ior_sandbox"
OUT = ROOT / "work" / "judge_data" / "v4_eval_ior"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cells = [json.loads(l) for l in CELLS.read_text().splitlines()]
    n = 0
    with (OUT / "cells.jsonl").open("w") as f:
        for c in cells:
            key = f"industryor_{c['arm']}_{c['id']}"
            if not (SANDBOX / key / "solution.json").exists():
                continue
            f.write(json.dumps({
                "key": key, "wrong": bool(c["wrong"]),
                "prompt": (c.get("prompt") or "")[:6000],
                "code": (c.get("code") or "")[:4000],
                "objective": c.get("objective"),
            }, ensure_ascii=False) + "\n")
            n += 1
    json.dump({"planner": PLANNER_PROMPT, "decider": DECIDER_TEMPLATE},
              (OUT / "prompts.json").open("w"), ensure_ascii=False)
    subprocess.run(["tar", "-czf", str(OUT / "ior_sandbox.tar.gz"),
                    "-C", str(SANDBOX.parent), "ior_sandbox"], check=True)
    print(json.dumps({"cells": n, "out": str(OUT)}))


if __name__ == "__main__":
    main()
