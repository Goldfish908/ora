"""Offline tests for scripts/analyze_predictions.py and scripts/fork_sample.py.

No network, no docker, no LLM credentials. The real dev_gate_v3 trajectory
is used only when present (read-only).
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ORA_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ORA_ROOT))
sys.path.insert(0, str(ORA_ROOT / "scripts"))

import analyze_predictions as ap  # noqa: E402
import fork_sample as fs  # noqa: E402

REAL_TRAJ = (ORA_ROOT / "runs" / "dev_gate_v3" / "airport_gate_assignment__NvK9ANJ"
             / "agent" / "ora" / "trajectory.jsonl")


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.write_text("".join(json.dumps(e) + "\n" for e in events),
                    encoding="utf-8")


def _make_trial(root: Path, *, with_pairs: bool) -> Path:
    trial = root / "task_x__abc" / "agent" / "ora"
    trial.mkdir(parents=True)
    events = [
        {"event": "run_meta", "task_id": "task_x", "model": "m"},
        {"event": "llm_response", "task_id": "task_x", "model": "m",
         "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
        {"event": "llm_response", "task_id": "task_x", "model": "m",
         "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}},
        {"event": "action", "task_id": "task_x", "model": "m", "seq": 1,
         "action": {"tool": "bash", "command": "python solve.py",
                    "action_kind": "solve"}},
        {"event": "action", "task_id": "task_x", "model": "m", "seq": 2,
         "action": {"tool": "bash", "command": "cat out.csv",
                    "action_kind": "validate"}},
        {"event": "action", "task_id": "task_x", "model": "m", "seq": 3,
         "action": {"tool": "finish"}, "summary": "done"},
        {"event": "budget", "kind": "final", "status": "finished",
         "usage": {"prompt_tokens": 30, "completion_tokens": 10,
                   "total_tokens": 40}},
    ]
    _write_jsonl(trial / "trajectory.jsonl", events)
    if with_pairs:
        (trial / "predictions").mkdir()
        (trial / "outcomes").mkdir()

        def pred(seq, h, kind, prob, modes=None, unknown=False):
            p = {"unknown": True} if unknown else {
                "will_succeed_prob": prob,
                "expected_outcome": "x",
                "likely_failure_modes": modes or [],
                "post_state_guess": "y", "confidence": 0.5}
            return {"seq": seq, "action_hash": h, "predictor_mode": "shadow",
                    "input_hash": "z",
                    "action": {"tool": "bash", "command": "c",
                               "action_kind": kind},
                    "prediction": p}

        def outc(seq, h, kind, classification, rc):
            return {"seq": seq, "action_hash": h,
                    "prediction_file": f"predictions/{seq:04d}_{h}.json",
                    "action": {"tool": "bash", "command": "c",
                               "action_kind": kind},
                    "outcome": {"return_code": rc, "timed_out": False,
                                "error": None, "stdout_tail": "",
                                "stderr_tail": "",
                                "classification": classification}}

        # seq1: optimistic, succeeded -> hit
        # seq2: optimistic, failed -> MISS, optimistic_but_failed
        # seq3: pessimistic, succeeded -> MISS, pessimistic_but_succeeded
        # seq4: unknown, failed -> hit n/a
        pairs = [
            (1, "h1", "solve", 0.9, "ok", 0, False),
            (2, "h2", "solve", 0.8, "nonzero_exit", 1, False),
            (3, "h3", "validate", 0.2, "ok", 0, False),
            (4, "h4", "repair", None, "timeout", None, True),
        ]
        for seq, h, kind, prob, classification, rc, unknown in pairs:
            (trial / "predictions" / f"{seq:04d}_{h}.json").write_text(
                json.dumps(pred(seq, h, kind, prob, unknown=unknown)))
            (trial / "outcomes" / f"{seq:04d}_{h}.json").write_text(
                json.dumps(outc(seq, h, kind, classification, rc)))
        # one unpaired prediction
        (trial / "predictions" / "0005_h5.json").write_text(
            json.dumps(pred(5, "h5", "solve", 0.5)))
    return trial


class TestAnalyzePredictions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_pairing_and_aggregate(self):
        trial = _make_trial(self.root, with_pairs=True)
        result = ap.analyze_trial(trial)
        self.assertEqual(len(result["pairs"]), 4)
        self.assertEqual(result["unpaired"]["predictions_without_outcome"],
                         ["0005_h5.json"])

        agg = ap.aggregate([result])
        self.assertEqual(agg["n_pairs"], 4)
        self.assertEqual(agg["n_unknown"], 1)
        self.assertAlmostEqual(agg["unknown_rate"], 0.25)
        # 3 known: probs 0.9(ok),0.8(fail),0.2(ok) -> hits: T,F,F
        self.assertAlmostEqual(agg["overall"]["hit_rate"], 1 / 3)
        self.assertAlmostEqual(agg["overall"]["actual_success_rate"], 0.5)
        # calibration buckets: 0.67-1.0 has 0.9(ok),0.8(fail) -> actual 0.5
        high = [c for c in agg["calibration"] if c["bucket"] == "0.67-1.00"][0]
        self.assertEqual(high["n"], 2)
        self.assertAlmostEqual(high["actual_success_rate"], 0.5)
        low = [c for c in agg["calibration"] if c["bucket"] == "0.00-0.33"][0]
        self.assertEqual(low["n"], 1)
        self.assertAlmostEqual(low["actual_success_rate"], 1.0)
        # selection-bias lists
        self.assertEqual([p["seq"] for p in agg["optimistic_but_failed"]], [2])
        self.assertEqual([p["seq"] for p in agg["pessimistic_but_succeeded"]], [3])
        # by_action_kind
        kinds = {r["action_kind"]: r for r in agg["by_action_kind"]}
        self.assertEqual(kinds["solve"]["n"], 2)
        self.assertAlmostEqual(kinds["solve"]["actual_success_rate"], 0.5)

        # text report renders and mentions key sections
        text = ap.render_text([result], agg)
        for marker in ("TRIAL SUMMARIES", "PREDICTION PAIRS", "CALIBRATION",
                       "OPTIMISTIC BUT FAILED", "task_x"):
            self.assertIn(marker, text)

    def test_degraded_trial_without_predictions(self):
        trial = _make_trial(self.root, with_pairs=False)
        result = ap.analyze_trial(trial)
        self.assertEqual(result["pairs"], [])
        self.assertIn("no predictions", result["note"])
        s = result["summary"]
        self.assertEqual(s["task_id"], "task_x")
        self.assertEqual(s["status"], "finished")
        self.assertEqual(s["n_llm_calls"], 2)
        self.assertEqual(s["n_actions"], 2)  # finish not counted
        self.assertEqual(s["usage"]["total_tokens"], 40)
        self.assertEqual(s["action_kind_counts"], {"solve": 1, "validate": 1})
        agg = ap.aggregate([result])
        self.assertEqual(agg["n_pairs"], 0)
        self.assertIsNone(agg["unknown_rate"])
        text = ap.render_text([result], agg)
        self.assertIn("no prediction/outcome pairs", text)

    def test_v2_fields_and_legacy_dash(self):
        trial = _make_trial(self.root, with_pairs=True)
        # upgrade one prediction file to the v2 shape (task book 2.7)
        p = trial / "predictions" / "0001_h1.json"
        payload = json.loads(p.read_text())
        payload["prompt_version"] = "v2"
        payload["context_source"] = "evidence_store"
        payload["prediction_target"] = "independent_outcome"
        payload["prediction"]["scope_note"] = "only for tiny instances"
        payload["prediction"]["expected_solution_validity"] = "valid"
        p.write_text(json.dumps(payload))

        result = ap.analyze_trial(trial)
        by_seq = {r["seq"]: r for r in result["pairs"]}
        v2 = by_seq[1]
        self.assertEqual(v2["prompt_version"], "v2")
        self.assertEqual(v2["context_source"], "evidence_store")
        self.assertEqual(v2["prediction_target"], "independent_outcome")
        self.assertEqual(v2["scope_note"], "only for tiny instances")
        self.assertEqual(v2["expected_solution_validity"], "valid")
        # legacy v1 files: new keys are None and render as '-'
        self.assertIsNone(by_seq[2]["prompt_version"])
        self.assertIsNone(by_seq[2]["context_source"])
        text = ap.render_text([result], ap.aggregate([result]))
        self.assertIn("pv=v2", text)
        self.assertIn("ctx=evidence_store", text)
        self.assertIn("pv=-", text)
        self.assertIn("scope: only for tiny instances", text)


class TestForkSampleHelpers(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _traj(self) -> Path:
        events = []
        for seq, (tool, cmd, kind) in enumerate([
                ("bash", "cat /app/PROBLEM_STATEMENT.md", "recon"),
                ("bash", "sleep 1000", "other"),
                ("bash", "echo done", "other"),
                ("finish", "", "")], start=1):
            e = {"event": "action", "seq": seq,
                 "action": {"tool": tool, "command": cmd, "action_kind": kind}}
            events.append(e)
        p = self.root / "trajectory.jsonl"
        _write_jsonl(p, events)
        return p

    def test_extract_prefix_with_skip_pattern(self):
        traj = self._traj()
        prefix = fs.extract_replay_prefix(traj, upto_seq=4,
                                          skip_patterns=[r"sleep"])
        self.assertEqual([a["seq"] for a in prefix], [1, 3])
        self.assertTrue(all(a["command"] for a in prefix))
        prefix2 = fs.extract_replay_prefix(traj, upto_seq=1)
        self.assertEqual(len(prefix2), 1)

    def test_load_candidates_and_hash(self):
        path = self.root / "cands.json"
        path.write_text(json.dumps([
            {"command": "python a.py", "action_kind": "solve",
             "rationale": "r"},
            {"command": "python b.py"},
        ]))
        cands = fs.load_candidates(path)
        self.assertEqual(len(cands), 2)
        self.assertEqual(cands[1]["action_kind"], "other")
        self.assertEqual(cands[0]["timeout_sec"], fs.DEFAULT_EXEC_TIMEOUT_SEC)
        h1 = fs.action_hash("python a.py", "solve")
        self.assertEqual(h1, fs.action_hash("python a.py", "solve"))
        self.assertNotEqual(h1, fs.action_hash("python a.py", "code"))
        with self.assertRaises(ValueError):
            bad = self.root / "bad.json"
            bad.write_text(json.dumps([{"rationale": "no command"}]))
            fs.load_candidates(bad)

    @unittest.skipUnless(REAL_TRAJ.is_file(), "real trajectory not present")
    def test_replay_prefix_from_real_trajectory(self):
        prefix = fs.extract_replay_prefix(REAL_TRAJ, upto_seq=5)
        self.assertEqual(len(prefix), 5)
        self.assertEqual([a["seq"] for a in prefix], [1, 2, 3, 4, 5])
        self.assertEqual(prefix[0]["action_kind"], "recon")


class TestBlindSanitize(unittest.TestCase):
    """E1.4: blind mode must not leak the spec via comments/docstrings."""

    def test_sanitize_strips_comments_and_docstrings(self):
        import ast as _ast
        import run_controlled_eval as rce
        src = ('"""precedence J1 -> J3, minimize makespan."""\n'
               'import json  # stdlib\n'
               'MIN_FROM_P2 = 20  # at least 20 pieces from P2\n'
               'def f(x):\n'
               '    """ Supply-stability rule."""\n'
               '    return x + 1  # inline note\n')
        with tempfile.TemporaryDirectory() as td:
            app = Path(td)
            (app / "submissions").mkdir()
            (app / "submissions" / "solve.py").write_text(src)
            n = rce.sanitize_blind_tree(app)
            out = (app / "submissions" / "solve.py").read_text()
        self.assertEqual(n, 1)
        self.assertNotIn("#", out)
        self.assertNotIn('"""', out)
        self.assertNotIn("precedence", out)
        self.assertNotIn("at least 20 pieces", out)
        # semantics preserved: still parses, constants and code intact
        tree = _ast.parse(out)
        self.assertIn("MIN_FROM_P2 = 20", out)
        self.assertIn("return x + 1", out)
        self.assertTrue(tree)

    def test_sanitize_survives_syntax_error(self):
        import run_controlled_eval as rce
        with tempfile.TemporaryDirectory() as td:
            app = Path(td)
            (app / "broken.py").write_text("def f(:\n")
            self.assertEqual(rce.sanitize_blind_tree(app), 0)
            self.assertEqual((app / "broken.py").read_text(), "def f(:\n")


if __name__ == "__main__":
    unittest.main()
