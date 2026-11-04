"""Offline tests for ora_agent/spec_templates.py (D2 template skeletons).

No network, no LLM. Covers safe_eval whitelisting, render-time slot
validation, the built-in must-fire/must-pass fixtures (in-process and via
the d1_apply subprocess sandbox), and a few adversarial semantics beyond
the fixtures.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ORA_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ORA_ROOT))
sys.path.insert(0, str(ORA_ROOT / "scripts"))

from ora_agent import spec_templates as st  # noqa: E402
from d1_apply import run_rule  # noqa: E402


def run_local(template, slots, params, case):
    code = st.render(template, slots, params)
    return st._exec_local(code, case, params)


class TestSafeEval(unittest.TestCase):
    def test_basic_arithmetic(self):
        p = {"a1": 10, "a2": 15, "rate": 5, "demand": [3, 4, 5]}
        self.assertEqual(st.safe_eval("(a1+a2)*rate", p), 125.0)
        self.assertEqual(st.safe_eval("sum(demand)", p), 12.0)
        self.assertEqual(st.safe_eval("max(demand) * 2 - 1", p), 9.0)
        self.assertEqual(st.safe_eval("params['a1'] / 4", p), 2.5)

    def test_rejects_nasty_stuff(self):
        for bad in ("__import__('os')", "open('x')", "params.clear()",
                    "x if y else z", "lambda: 1", "10**10**10", "'abc'"):
            with self.assertRaises(st.TemplateError, msg=bad):
                st.safe_eval(bad, {})

    def test_unknown_name_lists_params_keys(self):
        with self.assertRaises(st.TemplateError) as ctx:
            st.safe_eval("a3 * 2", {"a1": 1})
        self.assertIn("a1", str(ctx.exception))

    def test_division_by_zero(self):
        with self.assertRaises(st.TemplateError):
            st.safe_eval("1/0", {})


class TestRenderValidation(unittest.TestCase):
    def test_unknown_template(self):
        with self.assertRaises(st.TemplateError):
            st.render("grep_the_code", {}, {})

    def test_objective_range_needs_a_bound(self):
        with self.assertRaises(st.TemplateError):
            st.render("objective_range", {"lower": None, "upper": None}, {})

    def test_objective_range_inverted(self):
        with self.assertRaises(st.TemplateError):
            st.render("objective_range", {"lower": 10, "upper": 5}, {})

    def test_sense_expected_enum(self):
        with self.assertRaises(st.TemplateError):
            st.render("sense_direction", {"expected": "max"}, {})

    def test_phantom_needs_keywords(self):
        with self.assertRaises(st.TemplateError):
            st.render("phantom_resource",
                      {"keywords": ["x"], "granted": 0}, {})  # too short
        with self.assertRaises(st.TemplateError):
            st.render("phantom_resource", {"keywords": []}, {})

    def test_moq_nothing_to_check(self):
        with self.assertRaises(st.TemplateError):
            st.render("conditional_moq",
                      {"m": None, "require_binary": False}, {})

    def test_rendered_code_has_no_eval_of_params(self):
        code = st.render("objective_range",
                         {"lower": 0, "upper": "(a1+a2)*rate"},
                         {"a1": 10, "a2": 15, "rate": 5})
        self.assertIn("upper = 125.0", code)
        self.assertNotIn("safe_eval", code)


class TestFixtures(unittest.TestCase):
    def test_all_fixtures_pass_in_process(self):
        rep = st.run_fixtures()
        self.assertTrue(rep["ok"], msg=json.dumps(rep, indent=1))

    def test_all_fixtures_pass_in_subprocess_sandbox(self):
        for fx in st.FIXTURES:
            code = st.render(fx["template"], fx["slots"], fx.get("params"))
            params = fx.get("params") or {}
            fire = run_rule(code, fx["must_fire"].get("code") or "",
                            fx["must_fire"].get("objective"), params)
            pas = run_rule(code, fx["must_pass"].get("code") or "",
                           fx["must_pass"].get("objective"), params)
            self.assertEqual(fire.get("status"), "ok", msg=str(fire))
            self.assertEqual(pas.get("status"), "ok", msg=str(pas))
            self.assertTrue(fire.get("violation"),
                            msg=f"must_fire silent: {fx['template']}")
            self.assertIsNone(pas.get("violation"),
                              msg=f"must_pass fired: {fx['template']}")


class TestSemantics(unittest.TestCase):
    def test_objective_none_never_fires(self):
        v = run_local("objective_range", {"lower": 0, "upper": 10}, {},
                      {"code": "anything", "objective": None})
        self.assertIsNone(v)

    def test_sense_both_senses_present_passes(self):
        # e.g. code minimizes a negated profit but mentions maximize in a
        # comment: ambiguous -> stay silent (conservative).
        v = run_local("sense_direction", {"expected": "maximize"}, {},
                      {"code": "# maximize profit\nmodel.setObjective(obj, 'minimize')",
                       "objective": None})
        self.assertIsNone(v)

    def test_sense_pulp(self):
        v = run_local("sense_direction", {"expected": "minimize"}, {},
                      {"code": "prob = LpProblem('p', LpMaximize)",
                       "objective": None})
        self.assertIsNotNone(v)

    def test_phantom_granted_positive(self):
        slots = {"resource": "initial inventory",
                 "keywords": ["initial_inventory"], "granted": 15000}
        self.assertIsNone(run_local("phantom_resource", slots, {},
                                    {"code": "initial_inventory = 15000",
                                     "objective": None}))
        v = run_local("phantom_resource", slots, {},
                      {"code": "initial_inventory = 20000", "objective": None})
        self.assertIsNotNone(v)

    def test_phantom_case_insensitive_and_subscript(self):
        slots = {"resource": "initial inventory",
                 "keywords": ["init_inv"], "granted": 0}
        v = run_local("phantom_resource", slots, {},
                      {"code": "INIT_INV[0] = 30", "objective": None})
        self.assertIsNotNone(v)

    def test_constant_substring_does_not_match(self):
        # expected 5 must not be satisfied by literals 50 or 1.5
        v = run_local("constant_fidelity", {"name": "rate", "expected": 5}, {},
                      {"code": "cap = 50; price = 1.5", "objective": None})
        self.assertIsNotNone(v)

    def test_constant_float_and_fractional(self):
        self.assertIsNone(run_local(
            "constant_fidelity", {"name": "wage", "expected": 0.5}, {},
            {"code": "penalty = .5 * delay", "objective": None}))

    def test_moq_threshold_missing(self):
        v = run_local("conditional_moq", {"m": 100, "require_binary": True}, {},
                      {"code": "y = model.addVar(vtype='B')\n"
                               "model.addConstr(q >= 50 * y)",
                       "objective": None})
        self.assertIsNotNone(v)

    def test_rules_never_crash_on_garbage(self):
        # garbage inputs must raise nothing; constant_fidelity / moq may
        # legitimately fire on literal-free code (that is their design).
        for fx in st.FIXTURES:
            code = st.render(fx["template"], fx["slots"], fx.get("params"))
            st._exec_local(code, {"code": "\x00\xff garbage",
                                  "objective": "nan"}, {})
            st._exec_local(code, {"code": None, "objective": object()}, {})
        v = run_local("objective_range", {"lower": 0, "upper": 10}, {},
                      {"code": "\x00\xff", "objective": "nan"})
        self.assertIsNone(v)


if __name__ == "__main__":
    unittest.main()
