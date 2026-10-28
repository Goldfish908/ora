"""Round-2 worker tests: audit/repair role invocations (task book 2.3/2.4).

Offline only: a dispatching fake llm_fn routes by system-prompt content
(master vs audit worker vs repair worker) and a fake exec_fn serves canned
file reads. No network, no docker, no harbor.
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
from ora_agent.evidence import EvidenceStore, Finding  # noqa: E402
from ora_agent.loop import LoopConfig, run_loop  # noqa: E402
from ora_agent.trajectory import TrajectoryWriter  # noqa: E402
from ora_agent.workers import WorkerManager  # noqa: E402

PROBLEM_MARKER = "PROBLEM TEXT MARKER: gate capacity rule"

# Canned container content served by the fake exec_fn (context reads only).
FILES = {
    "cat /app/PROBLEM_STATEMENT.md": PROBLEM_MARKER,
    "cat /app/submissions/model.md 2>/dev/null || echo MISSING": "# model v1",
    "cat /app/submissions/solve.py 2>/dev/null || echo MISSING": "print('solve')",
}

AUDIT_RESPONSE = json.dumps({
    "requirements_new": [
        {"req_id": "R1", "statement": "every flight assigned to a gate",
         "source_refs": ["/app/PROBLEM_STATEMENT.md:Constraints"], "scope": "all",
         "units": "flights", "hardness": "hard", "status": "explicit"},
    ],
    "findings": [
        {"req_ids": ["R1"], "problem_type": "implementation",
         "detail": "write_csv may drop the last flight",
         "proposed_checks": ["python3 /tmp/witness_R1.py"]},
    ],
})

AUDIT_CONFIRM_RESPONSE = json.dumps({
    "finding_updates": [{"finding_id": "F-001", "status": "confirmed",
                         "witness_ref": "outcomes/0003_x.json",
                         "detail": "witness reproduced"}],
    "check_results": [{"artifact_version": "v1", "input_hash": "in",
                       "actual_result": "fail", "evidence_source": "bash"}],
})

VERIFY_FIX_RESPONSE = json.dumps({
    "repair_result": {"patch_hash": "sha_v2", "target_finding": "F-001",
                      "resolved": ["F-001"], "confirmed_regressions": [],
                      "newly_discovered": [], "unresolved": []},
    "finding_updates": [{"finding_id": "F-001", "status": "refuted",
                         "witness_ref": "outcomes/0005_y.json"}],
})

REPAIR_RESPONSE = json.dumps({
    "patch_commands": ["cp /app/submissions/solve.py /app/submissions/solve_v2.py",
                       "python3 /tmp/patch.py"],
    "regression_plan": ["python3 /tmp/witness_R1.py"],
    "rationale": "off-by-one in row writer",
    "expected_resolved": ["F-001"],
    "risk_notes": "none",
})


def make_dispatch_llm_fn(actor_script, *, audit_reply=AUDIT_RESPONSE,
                         repair_reply=REPAIR_RESPONSE, worker_usage=None):
    """Route by system-prompt content: master / audit worker / repair worker."""
    worker_usage = worker_usage or {"prompt_tokens": 50,
                                    "completion_tokens": 10,
                                    "total_tokens": 60}
    state = {"n": 0, "audit_messages": [], "repair_messages": [],
             "tools_seen": []}

    def llm_fn(messages, **kwargs):
        sys_content = messages[0].get("content") or ""
        if "evidence-based reviewer" in sys_content:
            state["audit_messages"].append(
                json.loads(json.dumps(messages)))
            return {"content": audit_reply, "tool_calls": [],
                    "usage": dict(worker_usage), "model": "m",
                    "latency_s": 0.05, "finish_reason": "stop"}
        if "repair specialist" in sys_content:
            state["repair_messages"].append(
                json.loads(json.dumps(messages)))
            return {"content": repair_reply, "tool_calls": [],
                    "usage": dict(worker_usage), "model": "m",
                    "latency_s": 0.05, "finish_reason": "stop"}
        if "tools" in (kwargs.get("extra") or {}):
            state["tools_seen"] = [t["function"]["name"]
                                   for t in kwargs["extra"]["tools"]]
        item = actor_script[min(state["n"], len(actor_script) - 1)]
        state["n"] += 1
        return {"content": item.get("content", ""),
                "tool_calls": item.get("tool_calls", []),
                "usage": item.get("usage", {"prompt_tokens": 10,
                                            "completion_tokens": 5,
                                            "total_tokens": 15}),
                "model": "m", "latency_s": 0.01,
                "finish_reason": item.get("finish_reason", "stop")}

    llm_fn.state = state
    return llm_fn


def make_tool_call(name, args, call_id="call_1"):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def make_exec_fn():
    """Serves canned file reads; records every command (to prove workers
    never execute the checks they propose)."""
    calls = []

    async def exec_fn(command, timeout_sec):
        calls.append(command)
        for key, content in FILES.items():
            if command == key:
                return {"stdout": content, "stderr": "", "return_code": 0}
        if command.startswith("ls -la /app/data/"):
            return {"stdout": "flights.csv\n=== /app/data/flights.csv ===\nf1,g1\n",
                    "stderr": "", "return_code": 0}
        return {"stdout": "ok", "stderr": "", "return_code": 0}

    exec_fn.calls = calls
    return exec_fn


class WorkerTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.writer = TrajectoryWriter(self.tmp / "trajectory.jsonl",
                                       run_id="rw", task_id="tw", model="m")
        self.store = EvidenceStore(self.tmp / "evidence.jsonl")

    def tearDown(self):
        self.writer.close()
        self.store.close()
        self._tmp.cleanup()

    def events(self):
        return [json.loads(l)
                for l in (self.tmp / "trajectory.jsonl").read_text().splitlines()
                if l.strip()]

    def make_manager(self, llm_fn, exec_fn, tracker=None):
        return WorkerManager(llm_fn=llm_fn, exec_fn=exec_fn,
                             evidence_store=self.store, writer=self.writer,
                             tracker=tracker)


class TestWorkersDisabled(WorkerTestBase):
    def test_b0_tool_list_unchanged_and_audit_rejected(self):
        script = [
            {"tool_calls": [make_tool_call("audit", {
                "focus": "general", "question": "q"})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("finish", {"summary": "s"})],
             "finish_reason": "tool_calls"},
        ]
        llm_fn = make_dispatch_llm_fn(script)
        result = asyncio.run(run_loop(
            system_prompt="s", instruction="i", config=LoopConfig(),
            llm_fn=llm_fn, exec_fn=make_exec_fn(), writer=self.writer,
            worker_manager=None))
        self.assertEqual(result.status, "finished")
        # tools offered to the master are exactly the v1 set
        self.assertEqual(llm_fn.state["tools_seen"], ["bash", "finish"])
        # hallucinated audit call gets an error tool message, not a crash
        tool_msgs = [e["message"]["content"] for e in self.events()
                     if e["event"] == "msg_append"
                     and e["message"].get("role") == "tool"]
        self.assertTrue(any("not enabled" in m for m in tool_msgs))


class TestAuditFlow(WorkerTestBase):
    def _config(self, **kw):
        return LoopConfig(enable_workers=True, **kw)

    def test_first_audit_writes_requirements_and_findings(self):
        script = [
            {"tool_calls": [make_tool_call("audit", {
                "focus": "general", "question": "audit everything"})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("finish", {"summary": "s"})],
             "finish_reason": "tool_calls"},
        ]
        llm_fn = make_dispatch_llm_fn(script)
        manager = self.make_manager(llm_fn, make_exec_fn())
        result = asyncio.run(run_loop(
            system_prompt="s", instruction="i", config=self._config(),
            llm_fn=llm_fn, exec_fn=make_exec_fn(), writer=self.writer,
            worker_manager=manager))
        self.assertEqual(result.status, "finished")
        self.assertEqual(llm_fn.state["tools_seen"],
                         ["bash", "finish", "audit", "repair"])

        reqs = self.store.records("requirement")
        self.assertEqual([r["req_id"] for r in reqs], ["R1"])
        findings = self.store.records("finding")
        self.assertEqual(len(findings), 1)
        # new findings are forced to llm_judgment/suspected
        self.assertEqual(findings[0]["evidence_level"], "llm_judgment")
        self.assertEqual(findings[0]["status"], "suspected")
        self.assertEqual(findings[0]["problem_type"], "implementation")
        # worker trajectory events exist
        kinds = [(e["event"], e.get("worker")) for e in self.events()]
        self.assertIn(("worker_call", "audit"), kinds)
        self.assertIn(("worker_response", "audit"), kinds)

    def test_proposed_checks_not_executed_by_worker(self):
        script = [
            {"tool_calls": [make_tool_call("audit", {
                "focus": "general", "question": "q"})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("finish", {"summary": "s"})],
             "finish_reason": "tool_calls"},
        ]
        llm_fn = make_dispatch_llm_fn(script)
        exec_fn = make_exec_fn()
        manager = self.make_manager(llm_fn, exec_fn)
        asyncio.run(run_loop(
            system_prompt="s", instruction="i", config=self._config(),
            llm_fn=llm_fn, exec_fn=exec_fn, writer=self.writer,
            worker_manager=manager))
        # the proposed check command must NOT appear among executed commands
        self.assertNotIn("python3 /tmp/witness_R1.py", exec_fn.calls)
        # context reads DID happen (they are the only legitimate exec use)
        self.assertTrue(any(c.startswith("cat /app/") or c.startswith("ls -la")
                            for c in exec_fn.calls))

    def test_confirm_upgrades_finding_and_writes_check_result(self):
        # seed one open finding via a first audit
        script = [
            {"tool_calls": [make_tool_call("audit", {
                "focus": "general", "question": "q"})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("audit", {
                "focus": "confirm",
                "question": "ran witness: F-001 reproduced, rc=1"})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("finish", {"summary": "s"})],
             "finish_reason": "tool_calls"},
        ]
        replies = [AUDIT_RESPONSE, AUDIT_CONFIRM_RESPONSE]

        def audit_reply_seq():
            return replies[min(audit_reply_seq.n, len(replies) - 1)]
        audit_reply_seq.n = 0

        base_llm = make_dispatch_llm_fn(script)

        def llm_fn(messages, **kwargs):
            sys_content = messages[0].get("content") or ""
            if "evidence-based reviewer" in sys_content:
                reply = audit_reply_seq()
                audit_reply_seq.n += 1
                base_llm.state["audit_messages"].append(
                    json.loads(json.dumps(messages)))
                return {"content": reply, "tool_calls": [],
                        "usage": {"prompt_tokens": 50, "completion_tokens": 10,
                                  "total_tokens": 60},
                        "model": "m", "latency_s": 0.05, "finish_reason": "stop"}
            return base_llm(messages, **kwargs)

        manager = self.make_manager(llm_fn, make_exec_fn())
        asyncio.run(run_loop(
            system_prompt="s", instruction="i", config=self._config(),
            llm_fn=llm_fn, exec_fn=make_exec_fn(), writer=self.writer,
            worker_manager=manager))
        latest = self.store.latest_findings()["F-001"]
        self.assertEqual(latest["status"], "confirmed")
        self.assertEqual(latest["evidence_level"], "actual_test")
        self.assertEqual(latest["witness_ref"], "outcomes/0003_x.json")
        checks = self.store.records("check_result")
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["actual_result"], "fail")

    def test_verify_fix_writes_repair_result(self):
        # seed finding, then repair, then verify_fix
        script = [
            {"tool_calls": [make_tool_call("audit", {
                "focus": "general", "question": "q"})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("repair", {
                "finding_id": "F-001", "guidance": "fix the row writer"})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("audit", {
                "focus": "verify_fix",
                "question": "patch applied; witness now passes; regressions none"})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("finish", {"summary": "s"})],
             "finish_reason": "tool_calls"},
        ]
        replies = [AUDIT_RESPONSE, VERIFY_FIX_RESPONSE]
        state = {"n": 0}
        base_llm = make_dispatch_llm_fn(script)

        def llm_fn(messages, **kwargs):
            sys_content = messages[0].get("content") or ""
            if "evidence-based reviewer" in sys_content:
                reply = replies[min(state["n"], len(replies) - 1)]
                state["n"] += 1
                return {"content": reply, "tool_calls": [],
                        "usage": {"prompt_tokens": 50, "completion_tokens": 10,
                                  "total_tokens": 60},
                        "model": "m", "latency_s": 0.05, "finish_reason": "stop"}
            return base_llm(messages, **kwargs)

        manager = self.make_manager(llm_fn, make_exec_fn())
        result = asyncio.run(run_loop(
            system_prompt="s", instruction="i", config=self._config(),
            llm_fn=llm_fn, exec_fn=make_exec_fn(), writer=self.writer,
            worker_manager=manager))
        self.assertEqual(result.status, "finished")
        rrs = self.store.records("repair_result")
        self.assertEqual(len(rrs), 1)
        rr = rrs[0]
        self.assertEqual(rr["patch_hash"], "sha_v2")
        self.assertEqual(rr["target_finding"], "F-001")
        self.assertEqual(rr["resolved"], ["F-001"])
        self.assertEqual(rr["confirmed_regressions"], [])
        self.assertEqual(rr["newly_discovered"], [])
        self.assertEqual(rr["unresolved"], [])
        # verify_fix's finding_update refuted F-001 -> no open findings
        self.assertEqual(self.store.open_findings(), [])

    def test_blind_mode_hides_problem_statement(self):
        script = [
            {"tool_calls": [make_tool_call("audit", {
                "focus": "general", "question": "q", "mode": "blind"})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("finish", {"summary": "s"})],
             "finish_reason": "tool_calls"},
        ]
        llm_fn = make_dispatch_llm_fn(script)
        manager = self.make_manager(llm_fn, make_exec_fn())
        asyncio.run(run_loop(
            system_prompt="s", instruction="i", config=self._config(),
            llm_fn=llm_fn, exec_fn=make_exec_fn(), writer=self.writer,
            worker_manager=manager))
        audit_msgs = llm_fn.state["audit_messages"]
        self.assertEqual(len(audit_msgs), 1)
        blob = json.dumps(audit_msgs[0])
        self.assertNotIn(PROBLEM_MARKER, blob)
        # data overview and code are still provided
        self.assertIn("flights.csv", blob)
        self.assertIn("print('solve')", blob)


class TestRepairWorker(WorkerTestBase):
    def test_repair_unknown_finding_returns_error_not_crash(self):
        script = [
            {"tool_calls": [make_tool_call("repair", {
                "finding_id": "F-999", "guidance": "fix it"})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("finish", {"summary": "s"})],
             "finish_reason": "tool_calls"},
        ]
        llm_fn = make_dispatch_llm_fn(script)
        manager = self.make_manager(llm_fn, make_exec_fn())
        result = asyncio.run(run_loop(
            system_prompt="s", instruction="i",
            config=LoopConfig(enable_workers=True),
            llm_fn=llm_fn, exec_fn=make_exec_fn(), writer=self.writer,
            worker_manager=manager))
        self.assertEqual(result.status, "finished")
        tool_msgs = [e["message"]["content"] for e in self.events()
                     if e["event"] == "msg_append"
                     and e["message"].get("role") == "tool"]
        self.assertTrue(any("finding not found" in m and "F-999" in m
                            for m in tool_msgs))
        # no repair LLM call was made for the unknown finding
        self.assertEqual(llm_fn.state["repair_messages"], [])

    def test_repair_returns_patch_plan(self):
        self.store.append(Finding(
            finding_id="F-001", req_ids=["R1"], artifact_hash="v1",
            problem_type="implementation", evidence_level="actual_test",
            detail="off by one", status="confirmed"))
        script = [
            {"tool_calls": [make_tool_call("repair", {
                "finding_id": "F-001", "guidance": "minimal fix"})],
             "finish_reason": "tool_calls"},
            {"tool_calls": [make_tool_call("finish", {"summary": "s"})],
             "finish_reason": "tool_calls"},
        ]
        llm_fn = make_dispatch_llm_fn(script)
        manager = self.make_manager(llm_fn, make_exec_fn())
        asyncio.run(run_loop(
            system_prompt="s", instruction="i",
            config=LoopConfig(enable_workers=True),
            llm_fn=llm_fn, exec_fn=make_exec_fn(), writer=self.writer,
            worker_manager=manager))
        tool_msgs = [e["message"]["content"] for e in self.events()
                     if e["event"] == "msg_append"
                     and e["message"].get("role") == "tool"]
        reply = json.loads([m for m in tool_msgs if "patch_commands" in m][0])
        self.assertIn("cp /app/submissions/solve.py", reply["patch_commands"][0])
        self.assertEqual(reply["regression_plan"], ["python3 /tmp/witness_R1.py"])


class TestWorkerBudgets(WorkerTestBase):
    def test_worker_tokens_trigger_shared_circuit_break(self):
        tracker = BudgetTracker(token_budget=100)
        script = [
            {"tool_calls": [make_tool_call("audit", {
                "focus": "general", "question": "q"})],
             "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                       "total_tokens": 15},
             "finish_reason": "tool_calls"},
        ]
        # worker usage 95 + actor 10 = 105 > 100
        llm_fn = make_dispatch_llm_fn(script, worker_usage={
            "prompt_tokens": 95, "completion_tokens": 10, "total_tokens": 105})
        manager = self.make_manager(llm_fn, make_exec_fn(), tracker=tracker)
        result = asyncio.run(run_loop(
            system_prompt="s", instruction="i",
            config=LoopConfig(enable_workers=True, token_budget=100),
            llm_fn=llm_fn, exec_fn=make_exec_fn(), writer=self.writer,
            worker_manager=manager, budget_tracker=tracker))
        self.assertEqual(result.status, "token_budget_exceeded")
        self.assertEqual(tracker.role_totals()["worker"]["prompt_tokens"], 95)
        events = self.events()
        brk = [e for e in events if e["event"] == "budget"
               and e.get("kind") == "token_budget_exceeded"]
        self.assertTrue(any(e.get("after") == "worker_call" for e in brk))
        # worker usage also lands in run_summary.json
        summary = json.loads((self.tmp / "run_summary.json").read_text())
        self.assertEqual(summary["worker_usage"]["prompt_tokens"], 95)

    def test_worker_calls_budget_enforced(self):
        script = [
            {"tool_calls": [make_tool_call("audit", {
                "focus": "general", "question": f"q{i}"})],
             "finish_reason": "tool_calls"}
            for i in range(3)
        ] + [{"tool_calls": [make_tool_call("finish", {"summary": "s"})],
              "finish_reason": "tool_calls"}]
        llm_fn = make_dispatch_llm_fn(script)
        manager = self.make_manager(llm_fn, make_exec_fn())
        result = asyncio.run(run_loop(
            system_prompt="s", instruction="i",
            config=LoopConfig(enable_workers=True, worker_calls_budget=1),
            llm_fn=llm_fn, exec_fn=make_exec_fn(), writer=self.writer,
            worker_manager=manager))
        self.assertEqual(result.status, "finished")
        # only the first audit reached the worker (one LLM call)
        self.assertEqual(len(llm_fn.state["audit_messages"]), 1)
        tool_msgs = [e["message"]["content"] for e in self.events()
                     if e["event"] == "msg_append"
                     and e["message"].get("role") == "tool"]
        self.assertTrue(any("worker call budget exhausted" in m
                            for m in tool_msgs))
        # worker calls do not consume max_steps actions
        self.assertEqual(result.n_steps, 0)


if __name__ == "__main__":
    unittest.main()
