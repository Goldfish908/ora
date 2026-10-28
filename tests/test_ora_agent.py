"""Offline unit tests for ora_agent: no network, no docker, no harbor import.

Run: python3 -m unittest discover -s tests -v   (from /home/hewj13/wm/ora)
or:  python3 -m pytest tests/
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ora_agent import llm as llm_mod          # noqa: E402
from ora_agent.loop import LoopConfig, run_loop  # noqa: E402
from ora_agent.predict import (               # noqa: E402
    PredictionRecorder, QwenShadowPredictor, make_predictor,
)
from ora_agent.trajectory import TrajectoryWriter  # noqa: E402


def make_tool_call(name, args, call_id="call_1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def make_llm_fn(script):
    """script: list of dicts returned in order (content/tool_calls/usage/...)."""
    calls = {"n": 0, "requests": []}

    def llm_fn(messages, **kwargs):
        calls["requests"].append({"messages": list(messages), **kwargs})
        item = script[min(calls["n"], len(script) - 1)]
        calls["n"] += 1
        return {
            "content": item.get("content", ""),
            "tool_calls": item.get("tool_calls", []),
            "usage": item.get("usage", {"prompt_tokens": 10,
                                        "completion_tokens": 5,
                                        "total_tokens": 15}),
            "model": item.get("model", "qwen3.8-27b"),
            "latency_s": 0.01,
            "finish_reason": item.get("finish_reason", "stop"),
        }

    llm_fn.calls = calls
    return llm_fn


def make_exec_fn(results=None):
    """results: list of exec result dicts (cycled). Records all invocations."""
    calls = []
    results = results or [{"stdout": "ok", "stderr": "", "return_code": 0}]

    async def exec_fn(command, timeout_sec):
        calls.append({"command": command, "timeout_sec": timeout_sec})
        return dict(results[min(len(calls) - 1, len(results) - 1)])

    exec_fn.calls = calls
    return exec_fn


class LoopTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.writer = TrajectoryWriter(self.tmp / "trajectory.jsonl",
                                       run_id="run-test", task_id="task-test",
                                       model="qwen3.8-27b")

    def tearDown(self):
        self.writer.close()
        self._tmp.cleanup()

    def run_async(self, coro):
        return asyncio.run(coro)

    def read_events(self):
        self.writer._fp.flush()
        return [json.loads(line)
                for line in (self.tmp / "trajectory.jsonl").read_text().splitlines()
                if line.strip()]


class TestLoop(LoopTestBase):
    def test_finish_flow(self):
        script = [
            {"tool_calls": [make_tool_call("bash", {
                "command": "ls /app", "action_kind": "recon",
                "rationale": "see what is there"})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("finish", {"summary": "done"})],
             "finish_reason": "tool_calls"},
        ]
        llm_fn = make_llm_fn(script)
        exec_fn = make_exec_fn()
        result = self.run_async(run_loop(
            system_prompt="sys", instruction="task", config=LoopConfig(),
            llm_fn=llm_fn, exec_fn=exec_fn, writer=self.writer))
        self.assertEqual(result.status, "finished")
        self.assertEqual(result.finish_summary, "done")
        self.assertEqual(result.n_steps, 1)
        self.assertEqual(len(exec_fn.calls), 1)
        self.assertEqual(exec_fn.calls[0]["command"], "ls /app")
        # default exec timeout applied
        self.assertEqual(exec_fn.calls[0]["timeout_sec"], 360)

        events = self.read_events()
        types = [e["event"] for e in events]
        for t in ("run_meta", "llm_request", "llm_response", "action",
                  "outcome", "finish", "budget"):
            self.assertIn(t, types)
        # state_id chain integrity + required fields on every event
        for i, e in enumerate(events):
            for key in ("ts", "run_id", "task_id", "model", "state_id",
                        "parent_state", "event"):
                self.assertIn(key, e)
            self.assertEqual(e["state_id"], i + 1)
            self.assertEqual(e["parent_state"], i or None)
            self.assertEqual(e["run_id"], "run-test")

    def test_token_budget_circuit_breaker(self):
        script = [{
            "tool_calls": [make_tool_call("bash", {
                "command": "echo hi", "action_kind": "other",
                "rationale": "x"})],
            "usage": {"prompt_tokens": 5000, "completion_tokens": 5,
                      "total_tokens": 5005},
            "finish_reason": "tool_calls",
        }]
        exec_fn = make_exec_fn()
        result = self.run_async(run_loop(
            system_prompt="sys", instruction="task",
            config=LoopConfig(token_budget=1000),
            llm_fn=make_llm_fn(script), exec_fn=exec_fn, writer=self.writer))
        self.assertEqual(result.status, "token_budget_exceeded")
        self.assertEqual(len(exec_fn.calls), 0)  # action NOT executed
        types = [e["event"] for e in self.read_events()]
        self.assertIn("budget", types)
        self.assertNotIn("outcome", types)

    def test_max_steps(self):
        script = [{
            "tool_calls": [make_tool_call("bash", {
                "command": "echo hi", "action_kind": "other",
                "rationale": "x"})],
            "finish_reason": "tool_calls",
        }]
        exec_fn = make_exec_fn()
        result = self.run_async(run_loop(
            system_prompt="sys", instruction="task",
            config=LoopConfig(max_steps=3),
            llm_fn=make_llm_fn(script), exec_fn=exec_fn, writer=self.writer))
        self.assertEqual(result.status, "max_steps")
        self.assertEqual(result.n_steps, 3)
        self.assertEqual(len(exec_fn.calls), 3)

    def test_model_stopped(self):
        script = [{"content": "I give up.", "tool_calls": []}]
        result = self.run_async(run_loop(
            system_prompt="sys", instruction="task", config=LoopConfig(),
            llm_fn=make_llm_fn(script), exec_fn=make_exec_fn(),
            writer=self.writer))
        self.assertEqual(result.status, "model_stopped")

    def test_bad_tool_arguments_recover(self):
        bad = {"id": "c1", "type": "function",
               "function": {"name": "bash", "arguments": "{not json"}}
        script = [
            {"tool_calls": [bad], "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("finish", {"summary": "ok"}, "c2")],
             "finish_reason": "tool_calls"},
        ]
        exec_fn = make_exec_fn()
        result = self.run_async(run_loop(
            system_prompt="sys", instruction="task", config=LoopConfig(),
            llm_fn=make_llm_fn(script), exec_fn=exec_fn, writer=self.writer))
        self.assertEqual(result.status, "finished")
        self.assertEqual(len(exec_fn.calls), 0)
        bad_events = [e for e in self.read_events()
                      if e.get("error") == "bad_arguments"]
        self.assertEqual(len(bad_events), 1)

    def test_exec_timeout_clamped_and_classified(self):
        script = [
            {"tool_calls": [make_tool_call("bash", {
                "command": "sleep 999", "action_kind": "solve",
                "rationale": "x", "timeout_sec": 99999})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("finish", {"summary": "s"})],
             "finish_reason": "tool_calls"},
        ]
        exec_fn = make_exec_fn(results=[
            {"stdout": "", "stderr": "", "return_code": -1,
             "error": "RuntimeError: Command timed out after 600 seconds"},
        ])
        result = self.run_async(run_loop(
            system_prompt="sys", instruction="task", config=LoopConfig(),
            llm_fn=make_llm_fn(script), exec_fn=exec_fn, writer=self.writer))
        self.assertEqual(exec_fn.calls[0]["timeout_sec"], 600)  # clamped
        outcome = [e for e in self.read_events() if e["event"] == "outcome"][0]
        self.assertEqual(outcome["classification"], "timeout")
        self.assertEqual(result.status, "finished")

    def test_llm_error_aborts(self):
        def llm_fn(messages, **kwargs):
            raise llm_mod.LLMRequestError("boom")
        result = self.run_async(run_loop(
            system_prompt="sys", instruction="task", config=LoopConfig(),
            llm_fn=llm_fn, exec_fn=make_exec_fn(), writer=self.writer))
        self.assertEqual(result.status, "llm_error")
        events = self.read_events()
        err = [e for e in events if e.get("error") == "llm_request_failed"]
        self.assertEqual(len(err), 1)


class TestPrediction(LoopTestBase):
    def _shadow_recorder(self, predictor_response='{"will_succeed_prob": 0.5, '
                                               '"expected_outcome": "ok", '
                                               '"likely_failure_modes": [], '
                                               '"post_state_guess": "x", '
                                               '"confidence": 0.4}'):
        pred_llm = make_llm_fn([{"content": predictor_response}])
        predictor = QwenShadowPredictor(pred_llm)
        return PredictionRecorder(self.tmp, writer=self.writer,
                                  predictor=predictor), pred_llm

    def test_prediction_file_written_before_exec(self):
        recorder, pred_llm = self._shadow_recorder()
        pred_file_at_exec_time = []

        async def exec_fn(command, timeout_sec):
            # At exec time the prediction file must already exist on disk
            # (fsync'd before execution).
            pred_dir = self.tmp / "predictions"
            existing = list(pred_dir.glob("*.json"))
            pred_file_at_exec_time.append(existing)
            self.assertTrue(existing, "prediction file must exist before exec")
            return {"stdout": "optimal", "stderr": "", "return_code": 0}

        script = [
            {"tool_calls": [make_tool_call("bash", {
                "command": "python /app/submissions/solve.py",
                "action_kind": "solve", "rationale": "run solver"})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("finish", {"summary": "s"})],
             "finish_reason": "tool_calls"},
        ]
        result = self.run_async(run_loop(
            system_prompt="sys", instruction="task", config=LoopConfig(),
            llm_fn=make_llm_fn(script), exec_fn=exec_fn, writer=self.writer,
            recorder=recorder))
        self.assertEqual(result.status, "finished")
        self.assertEqual(pred_llm.calls["n"], 1)  # predictor called once

        preds = list((self.tmp / "predictions").glob("*.json"))
        outs = list((self.tmp / "outcomes").glob("*.json"))
        self.assertEqual(len(preds), 1)
        self.assertEqual(len(outs), 1)
        pred = json.loads(preds[0].read_text())
        outc = json.loads(outs[0].read_text())
        self.assertIn("input_hash", pred)
        self.assertEqual(pred["prediction"]["will_succeed_prob"], 0.5)
        self.assertEqual(outc["prediction_file"], f"predictions/{preds[0].name}")
        self.assertEqual(outc["outcome"]["return_code"], 0)
        self.assertEqual(outc["action_hash"], pred["action_hash"])

    def test_non_predicted_kinds_get_no_files(self):
        recorder, pred_llm = self._shadow_recorder()
        script = [
            {"tool_calls": [make_tool_call("bash", {
                "command": "ls /app", "action_kind": "recon",
                "rationale": "look"})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("finish", {"summary": "s"})],
             "finish_reason": "tool_calls"},
        ]
        self.run_async(run_loop(
            system_prompt="sys", instruction="task", config=LoopConfig(),
            llm_fn=make_llm_fn(script), exec_fn=make_exec_fn(),
            writer=self.writer, recorder=recorder))
        self.assertEqual(pred_llm.calls["n"], 0)
        self.assertEqual(list((self.tmp / "predictions").glob("*.json")), [])
        self.assertEqual(list((self.tmp / "outcomes").glob("*.json")), [])
        # but the trajectory still records the outcome event
        self.assertIn("outcome", [e["event"] for e in self.read_events()])

    def test_off_mode_never_calls_llm(self):
        predictor = make_predictor("off", None)
        recorder = PredictionRecorder(self.tmp, writer=self.writer,
                                      predictor=predictor)
        script = [
            {"tool_calls": [make_tool_call("bash", {
                "command": "python solve.py", "action_kind": "solve",
                "rationale": "x"})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("finish", {"summary": "s"})],
             "finish_reason": "tool_calls"},
        ]
        self.run_async(run_loop(
            system_prompt="sys", instruction="task", config=LoopConfig(),
            llm_fn=make_llm_fn(script), exec_fn=make_exec_fn(),
            writer=self.writer, recorder=recorder))
        self.assertEqual(list((self.tmp / "predictions").glob("*.json")), [])

    def test_unparseable_prediction_becomes_unknown(self):
        recorder, _ = self._shadow_recorder(
            predictor_response="I have no idea, honestly.")
        fname = recorder.before_exec(
            seq=1,
            action={"tool": "bash", "command": "x", "action_kind": "solve",
                    "rationale": "r", "timeout_sec": 360},
            action_hash="abc123", history_summary="", budget_state={})
        self.assertIsNotNone(fname)
        payload = json.loads((self.tmp / fname).read_text())
        self.assertTrue(payload["prediction"]["unknown"])


class _FakeHTTPResponse:
    def __init__(self, body: str):
        self._body = body.encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    def __init__(self, behaviors):
        self.behaviors = list(behaviors)
        self.n_calls = 0

    def open(self, request, timeout=None):
        self.n_calls += 1
        behavior = self.behaviors.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return _FakeHTTPResponse(behavior)


class TestLLMClient(unittest.TestCase):
    def setUp(self):
        self.config = llm_mod.LLMConfig(base_url="http://llm.local/v1",
                                        api_key="test-key", model="m")

    def test_missing_env_raises_clear_error(self):
        with self.assertRaises(llm_mod.LLMConfigError) as cm:
            llm_mod.load_config({})
        msg = str(cm.exception)
        self.assertIn("ORA_LLM_BASE_URL", msg)
        self.assertIn("ORA_LLM_API_KEY", msg)

    def test_chat_parses_tool_calls(self):
        body = json.dumps({
            "model": "m",
            "choices": [{
                "finish_reason": "tool_calls",
                "message": {"content": "", "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {"name": "bash", "arguments": "{\"command\": \"ls\"}"},
                }]},
            }],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2,
                      "total_tokens": 5},
        })
        opener = _FakeOpener([body])
        out = llm_mod.chat([{"role": "user", "content": "hi"}],
                           config=self.config, opener=opener, sleep_fn=lambda s: None)
        self.assertEqual(out["finish_reason"], "tool_calls")
        self.assertEqual(out["tool_calls"][0]["function"]["name"], "bash")
        self.assertEqual(out["usage"]["prompt_tokens"], 3)
        self.assertEqual(out["model"], "m")
        self.assertGreaterEqual(out["latency_s"], 0)

    def test_retries_network_errors_then_succeeds(self):
        opener = _FakeOpener([
            urllib.error.URLError("conn reset"),
            urllib.error.URLError("conn reset"),
            json.dumps({"model": "m", "choices": [{
                "finish_reason": "stop", "message": {"content": "OK"}}],
                "usage": {}}),
        ])
        out = llm_mod.chat([{"role": "user", "content": "hi"}],
                           config=self.config, opener=opener,
                           sleep_fn=lambda s: None)
        self.assertEqual(out["content"], "OK")
        self.assertEqual(opener.n_calls, 3)  # 1 initial + 2 retries

    def test_retry_exhaustion_raises(self):
        opener = _FakeOpener([urllib.error.URLError("down")] * 3)
        with self.assertRaises(llm_mod.LLMRequestError):
            llm_mod.chat([{"role": "user", "content": "hi"}],
                         config=self.config, opener=opener,
                         sleep_fn=lambda s: None)
        self.assertEqual(opener.n_calls, 3)

    def test_http_400_not_retried(self):
        err = urllib.error.HTTPError("http://x", 400, "Bad Request", {},
                                     io.BytesIO(b'{"error": "bad"}'))
        opener = _FakeOpener([err])
        with self.assertRaises(llm_mod.LLMRequestError) as cm:
            llm_mod.chat([{"role": "user", "content": "hi"}],
                         config=self.config, opener=opener,
                         sleep_fn=lambda s: None)
        self.assertEqual(cm.exception.status, 400)
        self.assertEqual(opener.n_calls, 1)

    def test_empty_content_with_length_reported_truthfully(self):
        body = json.dumps({"model": "m", "choices": [{
            "finish_reason": "length", "message": {"content": ""}}],
            "usage": {}})
        out = llm_mod.chat([{"role": "user", "content": "hi"}],
                           config=self.config, opener=_FakeOpener([body]),
                           sleep_fn=lambda s: None)
        self.assertEqual(out["content"], "")
        self.assertEqual(out["finish_reason"], "length")


if __name__ == "__main__":
    unittest.main()
