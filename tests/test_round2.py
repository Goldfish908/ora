"""Round-2 tests: run_summary crash safety, message reconstruction,
predictor cost accounting, active-mode warning, timeout_layer,
BudgetTracker, EvidenceStore. Offline only (fake llm_fn/exec_fn).
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ora_agent.budget import BudgetTracker  # noqa: E402
from ora_agent.evidence import (  # noqa: E402
    CheckResult, EvidenceStore, Finding, ImplementationLink, RepairResult,
    Requirement,
)
from ora_agent.loop import (  # noqa: E402
    LoopConfig, messages_sha256, run_loop,
)
from ora_agent.predict import PredictionRecorder, make_predictor  # noqa: E402
from ora_agent.trajectory import TrajectoryWriter  # noqa: E402


def make_tool_call(name, args, call_id="call_1"):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def make_capturing_llm_fn(script):
    """Fake llm_fn that deep-copies the messages it actually sees per call."""
    captured = []
    calls = {"n": 0}

    def llm_fn(messages, **kwargs):
        captured.append(json.loads(json.dumps(messages)))  # deep copy as-sent
        item = script[min(calls["n"], len(script) - 1)]
        calls["n"] += 1
        return {
            "content": item.get("content", ""),
            "tool_calls": item.get("tool_calls", []),
            "usage": item.get("usage", {"prompt_tokens": 10,
                                        "completion_tokens": 5,
                                        "total_tokens": 15}),
            "model": "qwen3.8-27b", "latency_s": 0.01,
            "finish_reason": item.get("finish_reason", "stop"),
        }

    llm_fn.captured = captured
    llm_fn.calls = calls
    return llm_fn


def make_exec_fn(result=None):
    result = result or {"stdout": "ok", "stderr": "", "return_code": 0}

    async def exec_fn(command, timeout_sec):
        return dict(result)

    return exec_fn


def read_events(path: Path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


THREE_STEP_SCRIPT = [
    {"tool_calls": [make_tool_call("bash", {
        "command": "ls /app", "action_kind": "recon", "rationale": "look"})],
     "finish_reason": "tool_calls"},
    {"tool_calls": [make_tool_call("bash", {
        "command": "python /app/submissions/solve.py", "action_kind": "solve",
        "rationale": "run"})], "finish_reason": "tool_calls"},
    {"tool_calls": [make_tool_call("finish", {"summary": "done"})],
     "finish_reason": "tool_calls"},
]


class Round2Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.writer = TrajectoryWriter(self.tmp / "trajectory.jsonl",
                                       run_id="r2", task_id="t2", model="m")

    def tearDown(self):
        self.writer.close()
        self._tmp.cleanup()

    def events(self):
        return read_events(self.tmp / "trajectory.jsonl")

    def summary(self):
        return json.loads((self.tmp / "run_summary.json").read_text())


class TestMessageReconstruction(Round2Base):
    def test_byte_exact_rebuild_and_hash_match(self):
        llm_fn = make_capturing_llm_fn(THREE_STEP_SCRIPT)
        result = asyncio.run(run_loop(
            system_prompt="SYS-PROMPT", instruction="TASK-INSTRUCTION",
            config=LoopConfig(), llm_fn=llm_fn, exec_fn=make_exec_fn(),
            writer=self.writer))
        self.assertEqual(result.status, "finished")

        events = self.events()
        init = [e for e in events if e["event"] == "context_init"]
        self.assertEqual(len(init), 1)
        self.assertEqual(init[0]["system_prompt"], "SYS-PROMPT")
        self.assertEqual(init[0]["instruction"], "TASK-INSTRUCTION")

        # Rebuild: context_init gives messages[0:2]; msg_append appends rest.
        rebuilt = [
            {"role": "system", "content": init[0]["system_prompt"]},
            {"role": "user", "content": init[0]["instruction"]},
        ]
        appends = [e for e in events if e["event"] == "msg_append"]
        for e in sorted(appends, key=lambda x: x["index"]):
            rebuilt.append(e["message"])
            self.assertEqual(e["index"], len(rebuilt) - 1)

        # Byte-exact equality with what the fake llm actually saw at call 2.
        seen_call2 = llm_fn.captured[1]
        prefix = rebuilt[:len(seen_call2)]
        self.assertEqual(json.dumps(prefix, sort_keys=True, ensure_ascii=False),
                         json.dumps(seen_call2, sort_keys=True, ensure_ascii=False))

        # messages_sha256 on every llm_request matches reconstruction prefix.
        requests = [e for e in events if e["event"] == "llm_request"]
        for i, req in enumerate(requests):
            seen = llm_fn.captured[i]
            self.assertEqual(req["n_messages"], len(seen))
            self.assertEqual(req["messages_sha256"], messages_sha256(seen))


class TestRunSummaryCrashSafety(Round2Base):
    def test_summary_incremental_without_final(self):
        # Simulate a kill: emit usage-bearing events, never emit a final
        # budget event, and check run_summary.json already has the usage.
        self.writer.emit("llm_request", n_messages=2, messages_sha256="x")
        self.writer.emit("llm_response", content="c", tool_calls=[],
                         usage={"prompt_tokens": 111, "completion_tokens": 7,
                                "total_tokens": 118},
                         finish_reason="stop", latency_s=0.5)
        self.writer.emit("action", seq=1, action={"tool": "bash"},
                         action_hash="h")
        s = self.summary()
        self.assertEqual(s["status"], "running")  # never finalized
        self.assertEqual(s["actor_usage"]["prompt_tokens"], 111)
        self.assertEqual(s["actor_usage"]["calls"], 1)
        self.assertEqual(s["n_steps"], 1)
        self.assertEqual(s["last_state_id"], 3)

    def test_keyboard_interrupt_still_writes_final_and_keeps_usage(self):
        calls = {"n": 0}

        def llm_fn(messages, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"content": "", "tool_calls": [make_tool_call(
                    "bash", {"command": "ls", "action_kind": "recon",
                             "rationale": "r"})],
                    "usage": {"prompt_tokens": 42, "completion_tokens": 3,
                              "total_tokens": 45},
                    "model": "m", "latency_s": 0.1,
                    "finish_reason": "tool_calls"}
            raise KeyboardInterrupt()  # simulated kill mid-run

        with self.assertRaises(KeyboardInterrupt):
            asyncio.run(run_loop(
                system_prompt="s", instruction="i", config=LoopConfig(),
                llm_fn=llm_fn, exec_fn=make_exec_fn(), writer=self.writer))
        events = self.events()
        finals = [e for e in events
                  if e["event"] == "budget" and e.get("kind") == "final"]
        self.assertEqual(len(finals), 1)
        s = self.summary()
        self.assertEqual(s["actor_usage"]["prompt_tokens"], 42)
        self.assertEqual(s["status"], "error")

    def test_final_budget_on_llm_error(self):
        def llm_fn(messages, **kwargs):
            raise RuntimeError("down")
        result = asyncio.run(run_loop(
            system_prompt="s", instruction="i", config=LoopConfig(),
            llm_fn=llm_fn, exec_fn=make_exec_fn(), writer=self.writer))
        self.assertEqual(result.status, "llm_error")
        finals = [e for e in self.events()
                  if e["event"] == "budget" and e.get("kind") == "final"]
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["status"], "llm_error")


class TestPredictorAccounting(Round2Base):
    def test_predictor_usage_tracked_once(self):
        pred_llm = make_capturing_llm_fn([{
            "content": '{"will_succeed_prob": 0.7}',
            "usage": {"prompt_tokens": 55, "completion_tokens": 11,
                      "total_tokens": 66}}])
        predictor = make_predictor("shadow", pred_llm)
        tracker = BudgetTracker(token_budget=10**9)
        recorder = PredictionRecorder(self.tmp, writer=self.writer,
                                      predictor=predictor, tracker=tracker)
        result = asyncio.run(run_loop(
            system_prompt="s", instruction="i", config=LoopConfig(),
            llm_fn=make_capturing_llm_fn(THREE_STEP_SCRIPT),
            exec_fn=make_exec_fn(), writer=self.writer, recorder=recorder,
            budget_tracker=tracker))
        self.assertEqual(result.status, "finished")

        totals = tracker.role_totals()
        # exactly one predicted action (the solve at seq 2), recorded once
        self.assertEqual(totals["predictor"]["calls"], 1)
        self.assertEqual(totals["predictor"]["prompt_tokens"], 55)
        self.assertEqual(totals["actor"]["calls"], 3)
        # recorder.usage delegates to the tracker (single aggregation point)
        self.assertEqual(recorder.usage["prompt_tokens"], 55)

        finals = [e for e in self.events()
                  if e["event"] == "budget" and e.get("kind") == "final"]
        self.assertEqual(finals[0]["predictor_usage"]["prompt_tokens"], 55)
        self.assertEqual(finals[0]["actor_usage"]["prompt_tokens"], 30)
        self.assertIn("worker_usage", finals[0])
        s = self.summary()
        self.assertEqual(s["predictor_usage"]["prompt_tokens"], 55)
        self.assertEqual(s["status"], "finished")

    def test_active_mode_warns_and_marks_no_decision_integration(self):
        pred_llm = make_capturing_llm_fn([{"content": '{"unknown": true}'}])
        recorder = PredictionRecorder(
            self.tmp, writer=self.writer,
            predictor=make_predictor("active", pred_llm))
        asyncio.run(run_loop(
            system_prompt="s", instruction="i", config=LoopConfig(),
            llm_fn=make_capturing_llm_fn(THREE_STEP_SCRIPT),
            exec_fn=make_exec_fn(), writer=self.writer, recorder=recorder))
        events = self.events()
        run_meta = [e for e in events if e["event"] == "run_meta"][0]
        self.assertFalse(run_meta["config"]["decision_integration"])
        warnings = [e for e in events if e["event"] == "warning"]
        self.assertTrue(any(w.get("kind") == "active_not_integrated"
                            and "NOT wired into decisions" in w.get("message", "")
                            for w in warnings))
        self.assertFalse(self.summary()["decision_integration"])


class TestTimeoutLayer(Round2Base):
    def _run_once_with(self, exec_result):
        script = [
            {"tool_calls": [make_tool_call("bash", {
                "command": "python solve.py", "action_kind": "solve",
                "rationale": "r"})], "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("finish", {"summary": "s"})],
             "finish_reason": "tool_calls"},
        ]
        asyncio.run(run_loop(
            system_prompt="s", instruction="i", config=LoopConfig(),
            llm_fn=make_capturing_llm_fn(script),
            exec_fn=make_exec_fn(exec_result), writer=self.writer))
        return [e for e in self.events() if e["event"] == "outcome"][0]

    def test_exec_level_timeout(self):
        outcome = self._run_once_with(
            {"stdout": "", "stderr": "", "return_code": -1, "timed_out": True})
        self.assertEqual(outcome["timeout_layer"], "exec")

    def test_solver_reported_timeout(self):
        outcome = self._run_once_with({
            "stdout": "SCIP Status        : TIME LIMIT\nSolving Time (sec) : 300.00",
            "stderr": "", "return_code": 0})
        self.assertEqual(outcome["timeout_layer"], "solver_reported")

    def test_no_timeout(self):
        outcome = self._run_once_with(
            {"stdout": "optimal solution found", "stderr": "", "return_code": 0})
        self.assertIsNone(outcome["timeout_layer"])


class TestArtifactsProbe(Round2Base):
    def test_probe_after_submissions_touching_action(self):
        probes = {"n": 0}

        async def probe():
            probes["n"] += 1
            return "-rw-r--r-- 1 root root 123 solve.py"

        asyncio.run(run_loop(
            system_prompt="s", instruction="i", config=LoopConfig(),
            llm_fn=make_capturing_llm_fn(THREE_STEP_SCRIPT),
            exec_fn=make_exec_fn(), writer=self.writer,
            artifacts_probe=probe))
        self.assertEqual(probes["n"], 1)  # only seq2 command mentions /app/submissions
        obs = self.summary()["artifacts_last_observed"]
        self.assertEqual(obs["after_seq"], 2)
        self.assertIn("solve.py", obs["listing"])


class TestBudgetTracker(unittest.TestCase):
    def test_record_and_budget(self):
        t = BudgetTracker(token_budget=100)
        t.record("actor", {"prompt_tokens": 60, "completion_tokens": 10}, 0.5)
        t.record("predictor", {"prompt_tokens": 30}, 0.2)
        t.record("worker", None)  # call with no usage still counts
        self.assertEqual(t.combined()["prompt_tokens"], 90)
        self.assertEqual(t.combined()["calls"], 3)
        self.assertFalse(t.over_budget())
        t.record("actor", {"prompt_tokens": 20}, None)
        self.assertTrue(t.over_budget())
        totals = t.role_totals()
        self.assertEqual(totals["actor"]["calls"], 2)
        self.assertAlmostEqual(totals["actor"]["latency_s"], 0.5)


class TestEvidenceStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_roundtrip_invalidation_and_queries(self):
        store = EvidenceStore(self.tmp / "evidence.jsonl")
        store.append(Requirement(
            req_id="R1", statement="solution.csv must list every flight",
            source_refs=["/app/PROBLEM_STATEMENT.md:Output Format"],
            scope="output schema", units="flights", hardness="hard"))
        store.append(ImplementationLink(
            req_id="R1", location="/app/submissions/solve.py:write_csv",
            artifact_version="sha_v1", coverage="writes all rows"))
        store.append(Finding(
            finding_id="F1", req_ids=["R1"], artifact_hash="sha_v1",
            problem_type="implementation", evidence_level="actual_test",
            detail="missing last flight", witness_ref="outcomes/0002_h.json",
            status="confirmed"))
        store.append(Finding(
            finding_id="F2", req_ids=["R1"], artifact_hash="sha_v1",
            problem_type="quality", evidence_level="llm_judgment",
            detail="maybe slow", status="unresolved"))
        store.append(CheckResult(
            check_id="C1", artifact_version="sha_v1", input_hash="in1",
            actual_result="fail", evidence_source="python check_schema.py"))

        # one open finding blocks "passed"; unresolved also blocks
        st = store.requirement_status("R1")
        self.assertFalse(st["passed"])
        self.assertEqual(st["n_open_findings"], 2)

        # repair resolves F1; F2 stays open -> still not passed
        store.append(RepairResult(
            patch_hash="sha_v2", target_finding="F1", resolved=["F1"],
            unresolved=["F2"]))
        open_ids = [f["finding_id"] for f in store.open_findings()]
        self.assertEqual(open_ids, ["F2"])
        self.assertFalse(store.requirement_status("R1")["passed"])

        # artifact changed: old links/checks superseded, not deleted
        n = store.invalidate_links_for("sha_v1")
        self.assertEqual(n, 2)  # one link + one check
        all_links = store.records("implementation_link")
        self.assertEqual(len(all_links), 1)
        self.assertTrue(all_links[0]["superseded"])
        active = store.records("implementation_link", include_superseded=False)
        self.assertEqual(active, [])

        # new artifact version with a passing check and F2 refuted -> passed
        store.append(ImplementationLink(
            req_id="R1", location="/app/submissions/solve.py:write_csv",
            artifact_version="sha_v2"))
        store.append(CheckResult(
            check_id="C2", artifact_version="sha_v2", input_hash="in1",
            actual_result="pass", evidence_source="python check_schema.py"))
        store.append(Finding(
            finding_id="F2", req_ids=["R1"], artifact_hash="sha_v2",
            problem_type="quality", evidence_level="deterministic",
            detail="timed: 12s", status="refuted"))
        st = store.requirement_status("R1")
        self.assertTrue(st["passed"])

        # unknown check result never counts as pass
        store.append(CheckResult(
            check_id="C3", artifact_version="sha_v3", input_hash="in1",
            actual_result="unknown", evidence_source="flaky"))
        store.append(ImplementationLink(
            req_id="R9", location="nowhere", artifact_version="sha_v3"))
        st9 = store.requirement_status("R9")
        self.assertFalse(st9["passed"])
        store.close()

        # persistence: reload replays the file, invalidation still applies
        store2 = EvidenceStore(self.tmp / "evidence.jsonl")
        links = store2.records("implementation_link")
        self.assertTrue(any(l.get("superseded") for l in links))
        # F1 resolved by repair, F2's latest record is refuted -> nothing open
        self.assertEqual(store2.open_findings(), [])
        by_req = store2.by_req_id("R1")
        self.assertEqual(len(by_req["requirements"]), 1)
        self.assertEqual(len(by_req["findings"]), 3)
        store2.close()

    def test_invalid_enum_rejected(self):
        with self.assertRaises(ValueError):
            Finding(finding_id="F", req_ids=[], artifact_hash="x",
                    problem_type="typo", evidence_level="actual_test")
        with self.assertRaises(ValueError):
            Requirement(req_id="R", statement="s", hardness="medium")


if __name__ == "__main__":
    unittest.main()
