from scripts.memory_witness_cegis import evaluate


UNKNOWN_SCRIPT = """import json
s = json.load(open('solution.json'))
v = s['variables']
print(json.dumps([{'rule': 'type_check', 'detail': 'checker looked in the wrong place'}]))
"""

VIOLATION_SCRIPT = """import json
s = json.load(open('solution.json'))
x = s['variables']['x']
out = []
if x > 4:
    out.append({'rule': 'bound', 'detail': f'{x} > 4'})
print(json.dumps(out))
"""


def test_checker_malfunction_is_unknown_not_detection():
    cells = [
        {"key": "clean", "wrong": False, "mutation": "clean",
         "reference_violations": [], "solution": {"variables": {"x": 1}, "objective": 1}},
        {"key": "wrong", "wrong": True, "mutation": "bound",
         "reference_violations": ["C01"], "solution": {"variables": {"x": 5}, "objective": 5}},
    ]
    result = evaluate(UNKNOWN_SCRIPT, cells)
    assert result["unknown"] == 2
    assert result["tp"] == 0
    assert result["fp"] == 0
    assert result["detection"] == 0


def test_numeric_violation_still_counts_as_detection():
    cells = [
        {"key": "clean", "wrong": False, "mutation": "clean",
         "reference_violations": [], "solution": {"variables": {"x": 1}, "objective": 1}},
        {"key": "wrong", "wrong": True, "mutation": "bound",
         "reference_violations": ["C01"], "solution": {"variables": {"x": 5}, "objective": 5}},
    ]
    result = evaluate(VIOLATION_SCRIPT, cells)
    assert result["unknown"] == 0
    assert result["tp"] == 1
    assert result["fp"] == 0
    assert result["dev_passed"] is True


def test_variable_missing_suffix_is_unknown_not_false_positive():
    cells = [
        {"key": "clean", "wrong": False, "mutation": "clean",
         "reference_violations": [], "solution": {"variables": {}, "objective": 1}},
    ]
    script = """import json
print(json.dumps([{'rule': 'var_V_missing', 'detail': 'VegetableServings is missing or not a number'}]))
"""
    result = evaluate(script, cells)
    assert result["unknown"] == 1
    assert result["fp"] == 0
    assert result["records"][0]["fired"] is False


def test_optimality_rule_remains_semantic_evidence():
    cells = [
        {"key": "clean", "wrong": False, "mutation": "clean",
         "reference_violations": [], "solution": {"variables": {}, "objective": 1}},
    ]
    script = """import json
print(json.dumps([{'rule': 'optimality', 'detail': 'objective is below proven minimum'}]))
"""
    result = evaluate(script, cells)
    assert result["unknown"] == 0
    assert result["fp"] == 1
