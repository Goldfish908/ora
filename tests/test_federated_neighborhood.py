from __future__ import annotations

import copy
import hashlib
import json
import time
from pathlib import Path

import pytest

from ora_agent.cleanroom import FAIL, PASS, UNKNOWN
from ora_agent.declarative_neighborhood import DECISION_REPAIR, OBJECTIVE_OPTIMIZATION
from ora_agent.federated_neighborhood import FederatedNeighborhoodRepair, build_dependency_graph
from ora_agent.federated_public_ir import (
    APP_DIR,
    CLIENT_UNIQUE,
    GPU_BUDGET,
    PRIVACY_BUDGET,
    STREAM_CLIENTS,
    STREAM_ENCLAVES,
    STREAM_EXAMPLES,
    UPLOAD_BUDGET,
    FederatedPublicChecker,
    all_variable_names,
    check_decisions,
    check_solution_csv,
    decisions_to_artifact,
    decisions_to_solution_bytes,
    load_public_files,
    load_public_problem,
    pair_key,
    solution_file_to_artifact,
    split_variable_name,
    variable_name,
)

ROOT = Path(__file__).resolve().parents[1]
CLEAN_PATH = ROOT / "tests/fixtures/federated_solution.csv"


@pytest.fixture(scope="module")
def public_files():
    return load_public_files()


@pytest.fixture(scope="module")
def problem(public_files):
    return load_public_problem(public_files)


@pytest.fixture(scope="module")
def clean(public_files):
    return solution_file_to_artifact(CLEAN_PATH, public_files)


def _rule_keys(report, requirement_id):
    return {row["rule_part"] for row in report["violations"]
            if row["requirement_id"] == requirement_id and row["status"] == FAIL}


def _artifact_with_selection(clean, selected, public_files):
    return decisions_to_artifact(
        {"selected": selected, "_mapping_violations": []}, public_files,
    )


def _duplicate_wrong(clean, problem, public_files):
    selected = dict(clean.decisions["selected"])
    chosen_pair = next(pair for pair in problem.pair_order if selected[pair_key(*pair)] == 1)
    alternate = next(
        pair for pair in problem.by_client[chosen_pair[0]]
        if selected[pair_key(*pair)] == 0
    )
    selected[pair_key(*alternate)] = 1
    return _artifact_with_selection(clean, selected, public_files)


def _stream_wrong(clean, problem, public_files):
    selected = dict(clean.decisions["selected"])
    for pair in problem.by_stream["home_energy"]:
        selected[pair_key(*pair)] = 0
    return _artifact_with_selection(clean, selected, public_files)


def _budget_wrong(clean, problem, public_files):
    selected = dict(clean.decisions["selected"])
    clients_used = {pair[0] for pair in problem.pair_order if selected[pair_key(*pair)]}
    counts = {
        stream_id: sum(selected[pair_key(*pair)] for pair in pairs)
        for stream_id, pairs in problem.by_stream.items()
    }
    config = problem.config

    def usage():
        chosen = [pair for pair in problem.pair_order if selected[pair_key(*pair)]]
        return (
            sum(float(problem.clients[pair[0]]["privacy_cost"]) for pair in chosen),
            sum(float(problem.scores[pair]["upload_mb"]) for pair in chosen),
            sum(float(problem.scores[pair]["gpu_minutes"]) for pair in chosen),
        )

    for pair in problem.pair_order:
        privacy, upload, gpu = usage()
        if (privacy > float(config["privacy_budget"])
                and upload > float(config["upload_budget_mb"])
                and gpu > float(config["gpu_minutes_budget"])):
            break
        if selected[pair_key(*pair)] or pair[0] in clients_used:
            continue
        if counts[pair[1]] >= int(problem.streams[pair[1]]["max_clients"]):
            continue
        selected[pair_key(*pair)] = 1
        clients_used.add(pair[0])
        counts[pair[1]] += 1
    return _artifact_with_selection(clean, selected, public_files)


@pytest.fixture(scope="module")
def wrong_artifacts(clean, problem, public_files):
    artifacts = {
        "duplicate_client": _duplicate_wrong(clean, problem, public_files),
        "stream_minimums": _stream_wrong(clean, problem, public_files),
        "all_budgets": _budget_wrong(clean, problem, public_files),
    }
    duplicate = check_decisions(artifacts["duplicate_client"].decisions, public_files)
    assert "capacity" in _rule_keys(duplicate, CLIENT_UNIQUE)

    stream = check_decisions(artifacts["stream_minimums"].decisions, public_files)
    for requirement_id in (STREAM_CLIENTS, STREAM_EXAMPLES, STREAM_ENCLAVES):
        assert "minimum_flow" in _rule_keys(stream, requirement_id)

    budgets = check_decisions(artifacts["all_budgets"].decisions, public_files)
    for requirement_id in (PRIVACY_BUDGET, UPLOAD_BUDGET, GPU_BUDGET):
        assert "capacity" in _rule_keys(budgets, requirement_id)
    return artifacts


def test_real_clean_csv_round_trip_and_public_provenance(public_files, clean):
    canonical = decisions_to_solution_bytes(clean.decisions, public_files)
    assert canonical == clean.raw_bytes
    reparsed = solution_file_to_artifact(CLEAN_PATH, public_files)
    assert reparsed.decisions == clean.decisions
    assert reparsed.sha256 == hashlib.sha256(clean.raw_bytes).hexdigest()

    checker = FederatedPublicChecker(public_files)
    report = checker.check(clean.decisions)
    assert report["business_status"] == PASS
    assert report["violations"] == []
    assert report["objective_sense"] == "maximize"
    assert report["objective"] == pytest.approx(6020.689910000001)
    assert report["metrics"]["selected_pairs"] == 445
    assert not checker.ir.validation_issues(public_files)
    assert report["checker_sha256"] == checker.checker_sha256
    assert report["veto_enabled"] is False
    assert {row["status"] for row in report["uncovered_rules"]} == {UNKNOWN}
    for name, content in public_files.items():
        assert report["public_file_sha256"][name] == hashlib.sha256(
            (APP_DIR / name).read_bytes()
        ).hexdigest()
        assert report["public_file_sha256"][name] == hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest()


def test_uncovered_duplicate_row_semantics_are_unknown(public_files, clean):
    first_decision_row = clean.raw_bytes.splitlines(keepends=True)[1]
    duplicated = clean.raw_bytes + first_decision_row
    report = check_solution_csv(duplicated, public_files)
    assert report["business_status"] == UNKNOWN
    assert any(row["rule_part"] == "duplicate_decision" and row["status"] == UNKNOWN
               for row in report["violations"])
    assert report["veto_enabled"] is False


def test_complete_checks_include_maximum_and_eligibility(public_files, clean, problem):
    selected = dict(clean.decisions["selected"])
    stream_id = "vision_quality"
    maximum = int(problem.streams[stream_id]["max_clients"])
    used_clients = {pair[0] for pair in problem.pair_order if selected[pair_key(*pair)]}
    count = sum(selected[pair_key(*pair)] for pair in problem.by_stream[stream_id])
    for pair in problem.by_stream[stream_id]:
        if count > maximum:
            break
        if pair[0] not in used_clients and not selected[pair_key(*pair)]:
            selected[pair_key(*pair)] = 1
            used_clients.add(pair[0])
            count += 1
    wrong = _artifact_with_selection(clean, selected, public_files)
    report = check_decisions(wrong.decisions, public_files)
    assert "capacity" in _rule_keys(report, STREAM_CLIENTS)

    invalid_csv = b"client_id,stream_id,selected\r\nNOT_A_CLIENT,home_energy,1\r\n"
    invalid = check_solution_csv(invalid_csv, public_files)
    assert invalid["business_status"] == FAIL
    assert any(row["rule_part"] == "ineligible_pair" for row in invalid["violations"])


def test_dependency_graph_releases_violations_and_one_hop_only(
        public_files, clean, wrong_artifacts):
    parent = wrong_artifacts["duplicate_client"]
    repair = FederatedNeighborhoodRepair(public_files)
    spec = repair.build(parent)
    graph = build_dependency_graph(parent.decisions, public_files)
    assert spec.parent_bytes == parent.raw_bytes
    assert spec.parent_sha256 == parent.sha256
    assert spec.dependency_graph_sha256 == graph.sha256
    assert spec.released_variables
    assert spec.fixed_variables
    assert set(spec.released_variables).isdisjoint(spec.fixed_variables)
    assert set(spec.released_variables).union(spec.fixed_variables) == set(all_variable_names(public_files))
    for key in spec.violation_keys:
        seeds = set(graph.violation_variables[key])
        assert seeds <= set(spec.released_variables)
        assert set(graph.direct_neighbors(seeds)) <= set(spec.released_variables)
    for name in spec.fixed_variables:
        client_id, stream_id = split_variable_name(name)
        assert spec.fixed_values[name] == parent.decisions["selected"][pair_key(client_id, stream_id)]


def test_parent_hash_and_fixed_value_guards(public_files, wrong_artifacts):
    parent = wrong_artifacts["duplicate_client"]
    repair = FederatedNeighborhoodRepair(public_files)

    def wrong_parent(spec):
        return {"status": "optimal", "parent_sha256": "0" * 64, "values": {}}

    hashed = repair.repair(parent, solver=wrong_parent)
    assert not hashed.accepted
    assert hashed.reason == "parent_hash_mismatch"
    assert hashed.selected.raw_bytes == parent.raw_bytes

    def change_fixed(spec):
        decisions = copy.deepcopy(parent.decisions)
        name = spec.fixed_variables[0]
        client_id, stream_id = split_variable_name(name)
        key = pair_key(client_id, stream_id)
        decisions["selected"][key] = 1 - decisions["selected"][key]
        return {"status": "optimal", "decisions": decisions, "parent_sha256": spec.parent_sha256}

    fixed = repair.repair(parent, solver=change_fixed)
    assert not fixed.accepted
    assert fixed.reason == "fixed_variable_changed"
    assert fixed.selected.raw_bytes == parent.raw_bytes


def test_new_violation_guard_rolls_back(public_files, wrong_artifacts):
    parent = wrong_artifacts["duplicate_client"]
    repair = FederatedNeighborhoodRepair(public_files)

    def empty_neighborhood_values(spec):
        return {
            "status": "optimal",
            "parent_sha256": spec.parent_sha256,
            "values": {name: 0 for name in spec.released_variables},
        }

    result = repair.repair(parent, solver=empty_neighborhood_values)
    assert not result.accepted
    assert result.reason == "new_violations"
    assert result.introduced_violations
    assert result.selected.raw_bytes == parent.raw_bytes


def test_maximize_objective_regression_guard(public_files, clean, problem):
    repair = FederatedNeighborhoodRepair(public_files)
    chosen = [pair for pair in problem.pair_order
              if clean.decisions["selected"][pair_key(*pair)] == 1]

    def coefficient(pair):
        score = problem.scores[pair]
        return (float(score["expected_model_gain"]) - float(problem.clients[pair[0]]["privacy_cost"])
                - float(score["gpu_minutes"]) * float(problem.config["gpu_minute_cost"])
                - float(score["upload_mb"]) * float(problem.config["upload_mb_cost"]))

    seed_pair = max(chosen, key=coefficient)
    assert coefficient(seed_pair) > 0

    def remove_seeded_client(spec):
        return {
            "status": "optimal",
            "parent_sha256": spec.parent_sha256,
            "values": {name: 0 for name in spec.released_variables},
        }

    result = repair.repair(
        clean, mode=OBJECTIVE_OPTIMIZATION, seed_variables=[variable_name(*seed_pair)],
        solver=remove_seeded_client,
    )
    assert not result.accepted
    assert result.reason == "objective_regression"
    assert result.selected.raw_bytes == clean.raw_bytes
    assert result.candidate_report["objective"] < result.parent_report["objective"]


def test_clean_root_is_not_damaged(public_files, clean):
    result = FederatedNeighborhoodRepair(public_files).repair(clean)
    assert not result.accepted
    assert result.reason == "empty_neighborhood"
    assert result.selected.raw_bytes == clean.raw_bytes
    assert result.selected.decisions == clean.decisions
    assert check_solution_csv(result.selected.raw_bytes, public_files)["business_status"] == PASS


def test_real_pyscipopt_repairs_all_predeclared_scenarios(public_files, clean, wrong_artifacts):
    repair = FederatedNeighborhoodRepair(public_files, time_limit_seconds=60.0, relative_gap=0.0005)
    summaries = []
    raw_outcomes = {}
    accepted_count = 0
    for name, parent in wrong_artifacts.items():
        def solve_and_record(spec, scenario=name):
            outcome = repair.solve(spec)
            raw_outcomes[scenario] = outcome
            return outcome

        started = time.perf_counter()
        result = repair.repair(parent, solver=solve_and_record)
        elapsed = time.perf_counter() - started
        raw_outcome = raw_outcomes[name]
        assert result.spec is not None
        assert result.solve_status is not None
        if result.accepted:
            accepted_count += 1
            assert result.fixed_violations
            assert not result.introduced_violations
            assert result.candidate_report["business_status"] == PASS
            assert result.solve_status in {"optimal", "feasible"}
            assert decisions_to_solution_bytes(
                result.selected.decisions, public_files,
            ) == result.selected.raw_bytes
            assert check_solution_csv(
                result.selected.raw_bytes, public_files,
            )["business_status"] == PASS
            for variable in result.spec.fixed_variables:
                client_id, stream_id = split_variable_name(variable)
                key = pair_key(client_id, stream_id)
                assert (result.selected.decisions["selected"][key]
                        == parent.decisions["selected"][key])
        else:
            assert result.selected.raw_bytes == parent.raw_bytes
            assert check_decisions(result.selected.decisions, public_files) == result.parent_report
        summaries.append({
            "scenario": name,
            "accepted": result.accepted,
            "reason": result.reason,
            "solve_status": result.solve_status,
            "scip_status": raw_outcome["solver_status"],
            "scip_nodes": raw_outcome["node_count"],
            "scip_solve_seconds": round(raw_outcome["solve_seconds"], 6),
            "scip_objective": raw_outcome.get("scip_objective"),
            "scip_dual_bound": raw_outcome.get("dual_bound"),
            "elapsed_seconds": round(elapsed, 6),
            "released_variables": len(result.spec.released_variables),
            "fixed_variables": len(result.spec.fixed_variables),
            "parent_violations": len(result.parent_report["violations"]),
            "fixed_violations": len(result.fixed_violations),
            "introduced_violations": len(result.introduced_violations),
            "remaining_violations": len(result.remaining_violations),
            "parent_objective": result.parent_report["objective"],
            "selected_objective": result.candidate_report["objective"] if result.accepted
                                  else result.parent_report["objective"],
            "selected_pairs": result.candidate_report["metrics"]["selected_pairs"] if result.accepted
                              else result.parent_report["metrics"]["selected_pairs"],
        })
    print("FEDERATED_REPAIR_SUMMARY=" + json.dumps(summaries, sort_keys=True))
    assert accepted_count >= 1
    assert check_solution_csv(clean.raw_bytes, public_files)["business_status"] == PASS
