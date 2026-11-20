import sys

import pytest

if sys.version_info < (3, 10):
    pytest.skip("EvalPlus governance requires Python 3.10+", allow_module_level=True)

from scripts.evalplus_governance import build_governor


def manifest():
    problem = {"task_id": "HumanEval/0", "prompt": "def add(a, b):\n",
               "entry_point": "add", "base_input": [[1, 1], [2, 2]],
               "plus_input": [[3, 3]], "atol": 0}
    expected = {"base": [2, 4], "plus": [6], "base_time": [0.001, 0.001], "plus_time": [0.001]}
    cases = []
    for index in range(3):
        cases.append({"case_id": f"clean{index}", "expected": "pass", "mutation": "canonical",
                      "artifact": {"problem": problem, "solution": "def add(a, b):\n    return a + b\n",
                                   "expected_output": expected}})
        cases.append({"case_id": f"wrong{index}", "expected": "fail", "mutation": "return_none",
                      "artifact": {"problem": problem, "solution": "def add(a, b):\n    return None\n",
                                   "expected_output": expected}})
    return {"cases": cases}


def test_evalplus_check_gets_veto_only_after_independent_replay():
    governor = build_governor(manifest(), include_evalplus=True)
    assert governor.checks["L1_execution"].status == "veto_enabled"
    assert governor.checks["L2_evalplus"].status == "veto_enabled"
    assert governor.final_accept({"L1_execution": "pass", "L2_evalplus": "pass"}) == (True, [])
    assert governor.final_accept({"L1_execution": "pass", "L2_evalplus": "fail"}) == (
        False, ["L2_evalplus:fail"])
