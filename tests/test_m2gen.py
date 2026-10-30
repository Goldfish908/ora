import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RL_PY = Path("/home/hewj13/planbb/miniforge3/envs/rl/bin/python")


@unittest.skipUnless(RL_PY.exists(), "pyscipopt env python not available")
class TestM2GenRegression(unittest.TestCase):
    def test_inv_cap_reproduces_handmade_slice(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "m2gen" / "run_regression.py")],
            cwd=ROOT, capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)


if __name__ == "__main__":
    unittest.main()
