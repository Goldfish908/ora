"""Regression: m2gen-generated inv_cap with the handmade instance's params
must reproduce the handmade vertical slice (controlled_m2/inv_cap)
semantically: same objectives (50.0 / 48.0 / 48.0), correct PASSes,
both mutants FAIL on W3.

Usage: python3 m2gen/run_regression.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from m2gen.core import generate  # noqa: E402

EXPECTED = {
    "correct": {"verdict": "PASS", "objective": 50.0, "rules": []},
    "c1_bind": {"verdict": "FAIL", "objective": 48.0, "rules": ["W3"]},
    "c4_time": {"verdict": "FAIL", "objective": 48.0, "rules": ["W3"]},
}


def main() -> int:
    handmade = (Path(__file__).resolve().parents[1]
                / "controlled_m2" / "inv_cap" / "data" / "params.json")
    params = json.loads(handmade.read_text())
    tmp = Path(tempfile.mkdtemp(prefix="m2gen_regression_"))
    try:
        made = generate("inv_cap", 1, seed=0, out_dir=tmp,
                        fixed_params=params)
        assert len(made) == 1, "expected exactly 1 instance"
        inst, ok, report = made[0]
        failures = []
        if not ok:
            failures.append("instance rejected by validation")
        for aid, exp in EXPECTED.items():
            got = report.get(aid)
            if got is None:
                failures.append(f"{aid}: missing")
                continue
            if got["verdict"] != exp["verdict"]:
                failures.append(
                    f"{aid}: verdict {got['verdict']} != {exp['verdict']}")
            if got["objective"] is None or \
                    abs(got["objective"] - exp["objective"]) > 1e-6:
                failures.append(
                    f"{aid}: objective {got['objective']} != "
                    f"{exp['objective']}")
            if [r for r in exp["rules"] if r not in got["rules"]]:
                failures.append(
                    f"{aid}: rules {got['rules']} missing {exp['rules']}")
        # flip pair must exist for storage_time and compile into a solve.py
        flip = inst / "flip_storage_time" / "correct" / "solve.py"
        if not flip.exists():
            failures.append("flip_storage_time reference missing")
        if failures:
            print("REGRESSION FAIL")
            for f_ in failures:
                print("  -", f_)
            return 1
        print("REGRESSION OK: generated inv_cap reproduces handmade slice "
              "(50.0/48.0/48.0, PASS/FAIL:W3/FAIL:W3, flip pair emitted)")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
