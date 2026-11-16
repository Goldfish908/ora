import ast
import copy
import hashlib
import json
import math
from pathlib import Path

import pytest

from scripts import industryor_next_stage as ns


ROOT = Path(__file__).resolve().parents[1]


def _manifest():
    return json.loads(ns.MANIFEST.read_text(encoding="utf-8"))


def _entry(problem_id):
    return next(entry for entry in _manifest()["problems"] if entry["id"] == problem_id)


def _keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _keys(child)


def test_requested_cohorts_and_audit_qualification():
    manifest = _manifest()
    assert tuple(manifest["problem_ids"]) == (19, 20, 21, 25, 48, 4, 8, 9)
    assert manifest["qualification"]["count"] >= 6
    assert manifest["qualification"]["qualified_ids"] == [19, 20, 21, 25, 4, 8, 9]
    assert manifest["qualification"]["blocked_ids"] == [48]
    for entry in manifest["problems"]:
        expected_cohort = "natural_objective_error" if entry["id"] in ns.ERROR_IDS else "known_correct_control"
        assert entry["cohort"] == expected_cohort
        assert entry["question"]
        assert "en_answer" not in entry


def test_initial_hashes_and_append_only_deterministic_instrumentation():
    for problem_id in ns.SUPPORTED_IDS:
        entry = _entry(problem_id)
        original = (ROOT / entry["initial"]["source_path"]).read_bytes()
        initial = (ROOT / entry["artifacts"]["initial.py"]).read_bytes()
        assert initial == original
        assert hashlib.sha256(initial).hexdigest() == entry["initial"]["sha256"]
        source = initial.decode("utf-8")
        code = (ROOT / entry["artifacts"]["instrumented.py"]).read_text(encoding="utf-8")
        assert code == ns.instrument_code(source)
        assert code.startswith(source.rstrip())
        assert hashlib.sha256(code.encode()).hexdigest() == entry["instrumented"]["sha256"]
        ast.parse(code)
        assert entry["instrumented"]["business_statements_rewritten"] is False
        assert entry["instrumented"]["public_answer_injected"] is False


def test_instrumenter_rejects_unsupported_or_colliding_modules():
    with pytest.raises(ValueError, match="optimize"):
        ns.instrument_code("from pyscipopt import Model\nm = Model()\n")
    with pytest.raises(ValueError, match="exactly one"):
        ns.instrument_code(
            "from pyscipopt import Model\n"
            "m = Model()\n"
            "m.optimize()\n"
            "m.optimize()\n"
        )
    with pytest.raises(ValueError, match="reserved"):
        ns.instrument_code(
            "from pyscipopt import Model\n"
            "_ior_next_collision = 1\n"
            "m = Model()\n"
            "m.optimize()\n"
        )


def test_real_scip_execution_and_complete_exports():
    for problem_id in ns.SUPPORTED_IDS:
        entry = _entry(problem_id)
        execution = json.loads((ROOT / entry["artifacts"]["execution.json"]).read_text())
        solution = json.loads((ROOT / entry["artifacts"]["solution.json"]).read_text())
        stdout = (ROOT / entry["artifacts"]["stdout.txt"]).read_text()
        assert execution["exec_status"] == "ok"
        assert execution["solver_status"] == "optimal"
        assert execution["export_complete"] is True
        assert solution["schema_version"] == ns.SOLUTION_SCHEMA
        assert solution["solver_status"] == "optimal"
        assert solution["solution_count"] >= 1
        assert solution["export"] == {"complete": True, "error": None}
        assert math.isfinite(solution["objective"])
        assert solution["variables"]
        assert set(solution["variables"]) == set(solution["variable_types"])
        assert all(math.isfinite(value) for value in solution["variables"].values())
        assert "solution_export: complete" in stdout


def test_initial_business_verdicts():
    for problem_id in ns.CONTROL_IDS:
        audit = ns.load_problem(problem_id).scorer()
        assert audit["audit_status"] == "complete"
        assert audit["business_correct"] is True
        assert audit["optimality"] == "proven_optimal"
        assert audit["violations"] == []
    for problem_id in (19, 20, 21, 25):
        audit = ns.load_problem(problem_id).scorer()
        assert audit["audit_status"] == "complete"
        assert audit["business_correct"] is False
        assert audit["violations"]
    audit_48 = ns.load_problem(48).scorer()
    assert audit_48["audit_status"] == "blocked"
    assert audit_48["business_correct"] is False
    assert audit_48["optimality"] == "not_assessed"
    assert audit_48["blocking_reasons"]


def test_natural_error_audit_reasons_are_variable_level():
    for problem_id in (19, 21):
        audit = ns.load_problem(problem_id).scorer()
        assert audit["model_objective_consistent"] is False
        assert audit["optimality"] == "suboptimal"
        assert all(check["passed"] for check in audit["constraint_checks"])
    audit_20 = ns.load_problem(20).scorer()
    failed_20 = {check["rule"] for check in audit_20["constraint_checks"] if not check["passed"]}
    assert "cars_imply_blocks" in failed_20
    assert "link_x3_y3" in failed_20
    audit_25 = ns.load_problem(25).scorer()
    assert audit_25["optimality"] == "suboptimal"
    assert audit_25["model_objective_consistent"] is False
    assert all(check["passed"] for check in audit_25["constraint_checks"])


def test_feasible_suboptimal_variables_fail_even_with_spoofed_objective():
    problem = ns.load_problem(4)
    candidate = copy.deepcopy(problem.solution)
    candidate["variables"].update(x_cows=10.0, x_sheep=20.0, x_chickens=50.0)
    candidate["objective"] = problem.solution["objective"]
    audit = problem.scorer(candidate)
    assert all(check["passed"] for check in audit["constraint_checks"])
    assert audit["optimality"] == "suboptimal"
    assert audit["model_objective_consistent"] is False
    assert audit["business_correct"] is False

    candidate["objective"] = audit["business_objective"]
    audit = problem.scorer(candidate)
    assert audit["model_objective_consistent"] is True
    assert audit["optimality"] == "suboptimal"
    assert audit["business_correct"] is False


def test_boats_require_airplanes_not_the_reverse():
    candidate = copy.deepcopy(ns.load_problem(9).solution)
    candidate["variables"].update(x1=0.0, x2=0.0, x3=1.0, x4=10.0, y1=0.0, y2=1.0)
    candidate["objective"] = 8 * 1 + 7 * 10
    audit = ns.score_solution(9, candidate)
    implication = next(check for check in audit["constraint_checks"] if check["rule"] == "boats_imply_airplanes")
    assert implication["passed"] is False
    assert audit["business_correct"] is False


def test_independently_constructed_repair_witnesses_can_pass():
    for problem_id, orders, units_per_order, unit_cost in (
        (19, "x_C", 10, 40),
        (21, "x_C", 15, 100),
    ):
        candidate = copy.deepcopy(ns.load_problem(problem_id).solution)
        candidate["variables"].update(x_A=0.0, x_B=0.0, x_C=0.0, y_A=0.0, y_B=0.0)
        required_orders = math.ceil((100 if problem_id == 19 else 150) / units_per_order)
        candidate["variables"][orders] = float(required_orders)
        candidate["objective"] = required_orders * units_per_order * unit_cost
        audit = ns.score_solution(problem_id, candidate)
        assert audit["optimality"] == "proven_optimal"
        assert audit["model_objective_consistent"] is True
        assert audit["business_correct"] is True

    candidate = copy.deepcopy(ns.load_problem(25).solution)
    candidate["variables"].update(x1=0.0, x2=100000.0, x3=0.0, x4=0.0)
    candidate["variables"]["x5"] = 3 * candidate["variables"]["x2"]
    candidate["objective"] = 1.7 * candidate["variables"]["x5"]
    audit = ns.score_solution(25, candidate)
    assert audit["optimality"] == "proven_optimal"
    assert audit["business_correct"] is True


def test_48_becomes_auditable_only_with_overtime_quantity_variables():
    candidate = copy.deepcopy(ns.load_problem(48).solution)
    candidate["variables"]["x_A"] = 10.0
    candidate["variables"]["x_B"] = (150 - 4 * 10) / 6
    candidate["variables"]["x_A_OT"] = 0.0
    candidate["variables"]["x_B_OT"] = 0.0
    candidate["objective"] = 300 * 10 + 450 * candidate["variables"]["x_B"]
    audit = ns.score_solution(48, candidate)
    assert audit["audit_status"] == "complete"
    assert audit["optimality"] == "proven_optimal"
    assert audit["business_correct"] is True


def test_malformed_exports_fail_closed_without_crashing():
    candidate = copy.deepcopy(ns.load_problem(4).solution)
    candidate["export"] = None
    audit = ns.score_solution(4, candidate)
    assert audit["execution_checks"]["export_complete"] is False
    assert audit["business_correct"] is False

    candidate = copy.deepcopy(ns.load_problem(4).solution)
    del candidate["variables"]["x_cows"]
    audit = ns.score_solution(4, candidate)
    assert audit["audit_status"] == "invalid_solution"
    assert audit["business_correct"] is False


def test_variable_mapping_covers_every_required_audit_variable():
    for entry in _manifest()["problems"]:
        score = json.loads((ROOT / entry["artifacts"]["score.json"]).read_text())
        required = {
            name
            for name, spec in entry["variable_mapping"].items()
            if spec["required_for_audit"]
        }
        if entry["audit"]["qualified"]:
            assert set(score["variable_audit"]) == required
            assert all(entry["variable_mapping"][name]["observed_in_initial_export"] for name in required)
        else:
            assert entry["id"] == 48
            assert not entry["variable_mapping"]["x_A_OT"]["observed_in_initial_export"]
            assert not entry["variable_mapping"]["x_B_OT"]["observed_in_initial_export"]


def test_questions_and_sources_are_traceable():
    rows = {row["id"]: row for row in json.loads(ns.DATASET.read_text(encoding="utf-8"))}
    for entry in _manifest()["problems"]:
        problem_id = entry["id"]
        assert entry["question"] == rows[problem_id]["en_question"]
        assert hashlib.sha256(entry["question"].encode()).hexdigest() == entry["question_sha256"]
        for source in entry["sources"]["orthought"].values():
            path = ROOT / source["path"]
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]


def test_narrow_api_and_results_do_not_expose_reference_targets():
    problem = ns.load_problem(4)
    assert set(problem.__dataclass_fields__) == {"problem_id", "initial", "code", "solution", "scorer"}
    assert problem.initial == (ns.WORK_ROOT / "prob_004" / "initial.py").read_text()
    assert problem.code == ns.instrument_code(problem.initial)
    assert problem.scorer()["business_correct"] is True
    with pytest.raises(KeyError):
        ns.load_problem(1)
    with pytest.raises(KeyError):
        ns.score_solution(1, {})

    forbidden = {
        "en_answer",
        "reference_objective",
        "independent_optimum",
        "optimal_objective",
        "target_objective",
        "optimum",
    }
    payloads = [_manifest()]
    payloads.extend(ns.load_problem(problem_id).scorer() for problem_id in ns.SUPPORTED_IDS)
    for payload in payloads:
        assert forbidden.isdisjoint(set(_keys(payload)))


def test_builder_does_not_read_or_inject_public_answers():
    source = ns.__file__
    tree = ast.parse(Path(source).read_text(encoding="utf-8"))
    answer_accesses = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == "en_answer"
    ]
    assert answer_accesses == []
