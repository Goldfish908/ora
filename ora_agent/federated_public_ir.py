"""Public-source decisions and checks for federated learning cohort selection."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .cleanroom import FAIL, PASS, UNKNOWN
from .declarative_neighborhood import DecisionArtifact, NeighborhoodError
from .requirement_ir import PublicDecisionChecker, Requirement, RequirementIR, SourceRef

PROBLEM_ID = "federated_learning_cohort_selection"
APP_DIR = (Path(__file__).resolve().parents[1] / "ORAgentBench" / "harbor_tasks" /
           PROBLEM_ID / "environment" / "app")
PUBLIC_FILENAMES = (
    "PROBLEM_STATEMENT.md",
    "data/config.json",
    "data/clients.csv",
    "data/training_streams.csv",
    "data/client_stream_scores.csv",
    "submissions/solution_template.csv",
)
EXPECTED_COLUMNS = ["client_id", "stream_id", "selected"]
ADAPTER_VERSION = "federated_public_checker_v0.1"
OBJECTIVE_SENSE = "maximize"

OUTPUT_SCHEMA = "output_schema"
ELIGIBLE_PAIRS = "eligible_pairs_only"
CLIENT_UNIQUE = "client_unique_stream"
STREAM_CLIENTS = "stream_client_bounds"
STREAM_EXAMPLES = "stream_local_examples"
STREAM_ENCLAVES = "stream_secure_enclave_clients"
PRIVACY_BUDGET = "privacy_budget"
UPLOAD_BUDGET = "upload_budget"
GPU_BUDGET = "gpu_minute_budget"
OBJECTIVE_RECOMPUTE = "objective_recompute"

_RULES_QUOTE = (
    "Select only rows listed in `client_stream_scores.csv`. Each client may be assigned to "
    "at most one stream. Each stream must satisfy its client-count, local-example, and "
    "secure-enclave requirements, and cannot exceed its listed maximum client count. The "
    "selected cohort must stay within the total privacy, upload, and GPU-minute budgets."
)
_ELIGIBILITY_QUOTE = "Select only rows listed in `client_stream_scores.csv`."
_UNIQUE_QUOTE = "Each client may be assigned to at most one stream."
_STREAM_QUOTE = (
    "Each stream must satisfy its client-count, local-example, and secure-enclave "
    "requirements, and cannot exceed its listed maximum client count."
)
_BUDGET_QUOTE = (
    "The selected cohort must stay within the total privacy, upload, and GPU-minute budgets."
)
_OBJECTIVE_QUOTE = (
    "The team wants to maximize expected model gain after accounting for privacy, GPU, and "
    "upload costs."
)
_SCHEMA_QUOTE = "Include selected pairs with `selected` equal to `1`."


@dataclass(frozen=True)
class PublicProblem:
    config: dict
    clients: dict[str, dict[str, str]]
    streams: dict[str, dict[str, str]]
    scores: dict[tuple[str, str], dict[str, str]]
    pair_order: tuple[tuple[str, str], ...]
    by_client: dict[str, tuple[tuple[str, str], ...]]
    by_stream: dict[str, tuple[tuple[str, str], ...]]

    @property
    def tolerance(self) -> float:
        return float(self.config["feasibility_tolerance"])


def load_public_files(app_dir: str | Path = APP_DIR) -> dict[str, str]:
    root = Path(app_dir)
    files = {}
    for name in PUBLIC_FILENAMES:
        with (root / name).open("r", encoding="utf-8", newline="") as handle:
            files[name] = handle.read()
    return files


def _csv_rows(content: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content)))


def load_public_problem(public_files: dict[str, str] | None = None) -> PublicProblem:
    files = load_public_files() if public_files is None else public_files
    config = json.loads(files["data/config.json"])
    client_rows = _csv_rows(files["data/clients.csv"])
    stream_rows = _csv_rows(files["data/training_streams.csv"])
    score_rows = _csv_rows(files["data/client_stream_scores.csv"])
    clients = {row["client_id"]: row for row in client_rows}
    streams = {row["stream_id"]: row for row in stream_rows}
    if len(clients) != len(client_rows) or len(streams) != len(stream_rows):
        raise ValueError("public client and stream identifiers must be unique")
    scores = {}
    pair_order = []
    for row in score_rows:
        pair = (row["client_id"], row["stream_id"])
        if pair[0] not in clients or pair[1] not in streams or pair in scores:
            raise ValueError("public scores must contain unique eligible client-stream pairs")
        scores[pair] = row
        pair_order.append(pair)
    by_client = {client_id: [] for client_id in clients}
    by_stream = {stream_id: [] for stream_id in streams}
    for pair in pair_order:
        by_client[pair[0]].append(pair)
        by_stream[pair[1]].append(pair)
    return PublicProblem(
        config=config,
        clients=clients,
        streams=streams,
        scores=scores,
        pair_order=tuple(pair_order),
        by_client={key: tuple(value) for key, value in by_client.items()},
        by_stream={key: tuple(value) for key, value in by_stream.items()},
    )


def pair_key(client_id: str, stream_id: str) -> str:
    return f"{client_id}|{stream_id}"


def split_pair_key(value: str) -> tuple[str, str]:
    parts = value.split("|")
    if len(parts) != 2 or not all(parts):
        raise NeighborhoodError("invalid federated client-stream key")
    return parts[0], parts[1]


def variable_name(client_id: str, stream_id: str) -> str:
    return f"selected.{pair_key(client_id, stream_id)}"


def split_variable_name(name: str) -> tuple[str, str]:
    if not name.startswith("selected."):
        raise NeighborhoodError("invalid federated decision variable")
    return split_pair_key(name[len("selected."):])


def all_variable_names(public_files: dict[str, str] | None = None) -> tuple[str, ...]:
    problem = load_public_problem(public_files)
    return tuple(variable_name(client_id, stream_id) for client_id, stream_id in problem.pair_order)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _source(public_files: dict[str, str], quote: str) -> SourceRef:
    content = public_files["PROBLEM_STATEMENT.md"]
    return SourceRef("PROBLEM_STATEMENT.md", quote, _sha256(content))


def _data_source(public_files: dict[str, str], name: str) -> dict:
    content = public_files[name]
    return {"source_file": name, "quote": content.splitlines()[0], "sha256": _sha256(content)}


def _data_sources(public_files: dict[str, str], *names: str) -> list[dict]:
    return [_data_source(public_files, name) for name in names]


def build_requirement_ir(public_files: dict[str, str] | None = None) -> RequirementIR:
    files = load_public_files() if public_files is None else public_files
    tolerance = float(json.loads(files["data/config.json"])["feasibility_tolerance"])
    common = {"tolerance": tolerance}

    def output(decision_key: str, row_index: list[str]) -> dict:
        return {"decision_key": decision_key, "row_index": row_index,
                "fields": ["use", "flow", "minimum_flow", "capacity"]}

    requirements = (
        Requirement(
            OUTPUT_SCHEMA, "conditional_bounds", _source(files, _SCHEMA_QUOTE),
            output("output_schema", ["row"]), {"tolerance": tolerance},
        ),
        Requirement(
            ELIGIBLE_PAIRS, "conditional_bounds", _source(files, _ELIGIBILITY_QUOTE),
            output("eligibility", ["client_id", "stream_id"]),
            {**common, "data_sources": _data_sources(files, "data/client_stream_scores.csv")},
        ),
        Requirement(
            CLIENT_UNIQUE, "conditional_bounds", _source(files, _UNIQUE_QUOTE),
            output("client_unique", ["client_id"]),
            {**common, "data_sources": _data_sources(files, "data/clients.csv",
                                                       "data/client_stream_scores.csv")},
            unit="streams",
        ),
        Requirement(
            STREAM_CLIENTS, "conditional_bounds", _source(files, _STREAM_QUOTE),
            output("stream_clients", ["stream_id"]),
            {**common, "data_sources": _data_sources(files, "data/training_streams.csv",
                                                       "data/client_stream_scores.csv")},
            unit="clients",
        ),
        Requirement(
            STREAM_EXAMPLES, "conditional_bounds", _source(files, _STREAM_QUOTE),
            output("stream_examples", ["stream_id"]),
            {**common, "data_sources": _data_sources(files, "data/training_streams.csv",
                                                       "data/client_stream_scores.csv")},
            unit="local_examples",
        ),
        Requirement(
            STREAM_ENCLAVES, "conditional_bounds", _source(files, _STREAM_QUOTE),
            output("stream_enclaves", ["stream_id"]),
            {**common, "data_sources": _data_sources(files, "data/training_streams.csv",
                                                       "data/clients.csv",
                                                       "data/client_stream_scores.csv")},
            unit="secure_enclave_clients",
        ),
        Requirement(
            PRIVACY_BUDGET, "conditional_bounds", _source(files, _BUDGET_QUOTE),
            output("privacy", ["sprint"]),
            {**common, "data_sources": _data_sources(files, "data/config.json", "data/clients.csv")},
            unit="privacy_cost",
        ),
        Requirement(
            UPLOAD_BUDGET, "conditional_bounds", _source(files, _BUDGET_QUOTE),
            output("upload", ["sprint"]),
            {**common, "data_sources": _data_sources(files, "data/config.json",
                                                       "data/client_stream_scores.csv")},
            unit="MB",
        ),
        Requirement(
            GPU_BUDGET, "conditional_bounds", _source(files, _BUDGET_QUOTE),
            output("gpu", ["sprint"]),
            {**common, "data_sources": _data_sources(files, "data/config.json",
                                                       "data/client_stream_scores.csv")},
            unit="GPU_minutes",
        ),
        Requirement(
            OBJECTIVE_RECOMPUTE, "objective_recompute", _source(files, _OBJECTIVE_QUOTE),
            {"decision_key": "objective_terms", "reported_key": "reported_objective",
             "row_index": ["client_id", "stream_id"], "fields": ["value", "coefficient"]},
            {**common,
             "equation": "expected_model_gain - privacy_cost - gpu_minutes * gpu_minute_cost "
                         "- upload_mb * upload_mb_cost",
             "data_sources": _data_sources(files, "data/config.json", "data/clients.csv",
                                             "data/client_stream_scores.csv")},
            hard=False,
        ),
    )
    return RequirementIR(
        problem_id=PROBLEM_ID,
        objective_sense=OBJECTIVE_SENSE,
        requirements=requirements,
        omission_defaults={"selected": "0"},
    )


def uncovered_rules() -> list[dict]:
    return [
        {"rule": "duplicate_csv_row_aggregation", "status": UNKNOWN,
         "detail": "The public schema does not define aggregation of repeated copies of one pair."},
        {"rule": "objective_optimality", "status": UNKNOWN,
         "detail": "A feasible CSV and an independently recomputed objective do not prove global optimality."},
        {"rule": "official_business_truth_equivalence", "status": UNKNOWN,
         "detail": "Offline public-rule checks are not an independent statement of official business truth."},
    ]


def _violation(requirement_id: str, index, rule_part: str, status: str, detail: str) -> dict:
    indices = [str(value) for value in (index if isinstance(index, (list, tuple)) else (index,))]
    key = json.dumps([requirement_id, indices, rule_part], ensure_ascii=False)
    return {"key": key, "requirement_id": requirement_id, "index": indices,
            "rule_part": rule_part, "status": status, "detail": detail}


def _zero_selection(problem: PublicProblem) -> dict[str, int]:
    return {pair_key(client_id, stream_id): 0 for client_id, stream_id in problem.pair_order}


def solution_to_decisions(csv_data: str | bytes, public_files: dict[str, str] | None = None) -> dict:
    files = load_public_files() if public_files is None else public_files
    problem = load_public_problem(files)
    if isinstance(csv_data, bytes):
        csv_text = csv_data.decode("utf-8")
    elif isinstance(csv_data, str):
        csv_text = csv_data
    else:
        raise NeighborhoodError("solution CSV must be text or bytes")
    selected = _zero_selection(problem)
    issues = []
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames != EXPECTED_COLUMNS:
        issues.append(_violation(
            OUTPUT_SCHEMA, ("header",), "solution_schema", FAIL,
            "solution.csv must use client_id,stream_id,selected in the published order",
        ))
    seen = set()
    for row_number, row in enumerate(reader, 2):
        client_id = (row.get("client_id") or "").strip()
        stream_id = (row.get("stream_id") or "").strip()
        pair = (client_id, stream_id)
        row_index = ("csv_row", row_number)
        raw_value = (row.get("selected") or "").strip()
        try:
            value = float(raw_value)
            if not math.isfinite(value):
                raise ValueError
        except (TypeError, ValueError):
            issues.append(_violation(
                OUTPUT_SCHEMA, row_index, "selected_not_one", FAIL,
                "every emitted row must have finite numeric selected equal to 1",
            ))
            continue
        if value != 1.0:
            issues.append(_violation(
                OUTPUT_SCHEMA, row_index, "selected_not_one", FAIL,
                "the public output schema permits selected rows only with selected=1",
            ))
        if pair not in problem.scores:
            issues.append(_violation(
                ELIGIBLE_PAIRS, row_index, "ineligible_pair", FAIL,
                "the emitted pair is not listed in client_stream_scores.csv",
            ))
            continue
        key = pair_key(*pair)
        if pair in seen:
            issues.append(_violation(
                OUTPUT_SCHEMA, row_index, "duplicate_decision", UNKNOWN,
                "repeated-pair aggregation is not publicly defined; a set projection is used for diagnostics",
            ))
        seen.add(pair)
        if value == 1.0:
            selected[key] = 1
    return {"selected": selected, "_mapping_violations": issues}


def solution_to_artifact(csv_data: str | bytes, public_files: dict[str, str] | None = None) -> DecisionArtifact:
    if isinstance(csv_data, str):
        raw_bytes = csv_data.encode("utf-8")
    elif isinstance(csv_data, bytes):
        raw_bytes = csv_data
    else:
        raise NeighborhoodError("solution CSV must be text or bytes")
    return DecisionArtifact(solution_to_decisions(raw_bytes, public_files), raw_bytes)


def solution_file_to_artifact(path: str | Path, public_files: dict[str, str] | None = None) -> DecisionArtifact:
    return solution_to_artifact(Path(path).read_bytes(), public_files)


def decisions_to_solution_bytes(decisions: Mapping, public_files: dict[str, str] | None = None) -> bytes:
    files = load_public_files() if public_files is None else public_files
    problem = load_public_problem(files)
    if not isinstance(decisions, Mapping) or not isinstance(decisions.get("selected"), Mapping):
        raise NeighborhoodError("structured decisions must contain a selected object")
    supplied = decisions["selected"]
    expected = {pair_key(client_id, stream_id) for client_id, stream_id in problem.pair_order}
    if set(supplied) != expected:
        raise NeighborhoodError("structured decisions must contain every eligible pair exactly once")
    values = {}
    for key in expected:
        value = supplied[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value) or value not in {0, 1}:
            raise NeighborhoodError("structured selection values must be finite binary numbers")
        values[key] = int(value)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=EXPECTED_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    for client_id, stream_id in problem.pair_order:
        if values[pair_key(client_id, stream_id)]:
            writer.writerow({"client_id": client_id, "stream_id": stream_id, "selected": 1})
    return output.getvalue().encode("utf-8")


def decisions_to_solution_csv(decisions: Mapping, public_files: dict[str, str] | None = None) -> str:
    return decisions_to_solution_bytes(decisions, public_files).decode("utf-8")


def decisions_to_artifact(decisions: Mapping, public_files: dict[str, str] | None = None) -> DecisionArtifact:
    files = load_public_files() if public_files is None else public_files
    return DecisionArtifact(dict(decisions), decisions_to_solution_bytes(decisions, files))


def _objective_coefficient(pair: tuple[str, str], problem: PublicProblem) -> float:
    client = problem.clients[pair[0]]
    score = problem.scores[pair]
    return (float(score["expected_model_gain"]) - float(client["privacy_cost"])
            - float(score["gpu_minutes"]) * float(problem.config["gpu_minute_cost"])
            - float(score["upload_mb"]) * float(problem.config["upload_mb_cost"]))


def _derive_decisions(decisions: Mapping, problem: PublicProblem) -> tuple[dict, list[dict], dict]:
    extra = []
    supplied = decisions.get("selected") if isinstance(decisions, Mapping) else None
    selected = _zero_selection(problem)
    eligibility_rows = []
    if not isinstance(supplied, Mapping):
        extra.append(_violation(
            OUTPUT_SCHEMA, ("selected",), "structured_decisions", UNKNOWN,
            "the complete structured selected object is missing",
        ))
        supplied = {}
    expected = {pair_key(*pair) for pair in problem.pair_order}
    missing = sorted(expected.difference(supplied))
    if missing:
        extra.append(_violation(
            OUTPUT_SCHEMA, ("selected",), "incomplete_decision_vector", UNKNOWN,
            f"the structured decision vector is missing {len(missing)} eligible pairs",
        ))
    for pair in problem.pair_order:
        key = pair_key(*pair)
        value = supplied.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value) or value not in {0, 1}:
            extra.append(_violation(
                OUTPUT_SCHEMA, pair, "selection_binary", FAIL,
                "structured selection values must be binary; unselected values project to zero for diagnostics",
            ))
            value = 1 if value == 1 and not isinstance(value, bool) else 0
        selected[key] = int(value)
    for key in sorted(set(supplied).difference(expected)):
        extra.append(_violation(
            ELIGIBLE_PAIRS, (key,), "unknown_decision", FAIL,
            "structured decisions contain a pair absent from public eligible scores",
        ))
        eligibility_rows.append({"index": (key,), "use": 1.0, "flow": 1.0,
                                 "minimum_flow": 0.0, "capacity": 0.0})

    client_unique_rows = []
    for client_id in problem.clients:
        count = sum(selected[pair_key(*pair)] for pair in problem.by_client[client_id])
        client_unique_rows.append({"index": (client_id,), "use": 1.0, "flow": float(count),
                                   "minimum_flow": 0.0, "capacity": 1.0})

    stream_client_rows = []
    stream_example_rows = []
    stream_enclave_rows = []
    stream_metrics = {}
    for stream_id, stream in problem.streams.items():
        pairs = problem.by_stream[stream_id]
        chosen = [pair for pair in pairs if selected[pair_key(*pair)]]
        count = len(chosen)
        examples = sum(float(problem.scores[pair]["examples"]) for pair in chosen)
        enclaves = sum(int(problem.clients[pair[0]]["secure_enclave"]) for pair in chosen)
        stream_metrics[stream_id] = {"clients": count, "examples": examples,
                                     "secure_enclave_clients": enclaves}
        stream_client_rows.append({
            "index": (stream_id,), "use": 1.0, "flow": float(count),
            "minimum_flow": float(stream["min_clients"]), "capacity": float(stream["max_clients"]),
        })
        stream_example_rows.append({
            "index": (stream_id,), "use": 1.0, "flow": examples,
            "minimum_flow": float(stream["min_examples"]),
            "capacity": sum(float(problem.scores[pair]["examples"]) for pair in pairs),
        })
        stream_enclave_rows.append({
            "index": (stream_id,), "use": 1.0, "flow": float(enclaves),
            "minimum_flow": float(stream["min_secure_enclave_clients"]),
            "capacity": float(sum(int(problem.clients[pair[0]]["secure_enclave"]) for pair in pairs)),
        })

    chosen = [pair for pair in problem.pair_order if selected[pair_key(*pair)]]
    privacy = sum(float(problem.clients[pair[0]]["privacy_cost"]) for pair in chosen)
    upload = sum(float(problem.scores[pair]["upload_mb"]) for pair in chosen)
    gpu = sum(float(problem.scores[pair]["gpu_minutes"]) for pair in chosen)
    gain = sum(float(problem.scores[pair]["expected_model_gain"]) for pair in chosen)
    gpu_operating_cost = gpu * float(problem.config["gpu_minute_cost"])
    upload_operating_cost = upload * float(problem.config["upload_mb_cost"])
    objective = gain - privacy - gpu_operating_cost - upload_operating_cost
    metrics = {
        "selected_pairs": len(chosen),
        "unique_clients": len({pair[0] for pair in chosen}),
        "streams": stream_metrics,
        "privacy_used": privacy,
        "upload_mb_used": upload,
        "gpu_minutes_used": gpu,
        "expected_model_gain": gain,
        "privacy_cost": privacy,
        "gpu_operating_cost": gpu_operating_cost,
        "upload_operating_cost": upload_operating_cost,
        "net_objective": objective,
    }
    objective_terms = [
        {"index": pair, "value": float(selected[pair_key(*pair)]),
         "coefficient": _objective_coefficient(pair, problem)}
        for pair in problem.pair_order
    ]
    derived = {
        "output_schema": [],
        "eligibility": eligibility_rows,
        "client_unique": client_unique_rows,
        "stream_clients": stream_client_rows,
        "stream_examples": stream_example_rows,
        "stream_enclaves": stream_enclave_rows,
        "privacy": [{"index": ("sprint",), "use": 1.0, "flow": privacy,
                     "minimum_flow": 0.0, "capacity": float(problem.config["privacy_budget"])}],
        "upload": [{"index": ("sprint",), "use": 1.0, "flow": upload,
                    "minimum_flow": 0.0, "capacity": float(problem.config["upload_budget_mb"])}],
        "gpu": [{"index": ("sprint",), "use": 1.0, "flow": gpu,
                 "minimum_flow": 0.0, "capacity": float(problem.config["gpu_minutes_budget"])}],
        "objective_terms": objective_terms,
        "reported_objective": objective,
        "omitted_fields": [],
    }
    return derived, extra, metrics


class FederatedPublicChecker:
    def __init__(self, public_files: dict[str, str] | None = None,
                 ir: RequirementIR | None = None) -> None:
        self.public_files = load_public_files() if public_files is None else public_files
        self.ir = build_requirement_ir(self.public_files) if ir is None else ir
        self.problem = load_public_problem(self.public_files)
        self._delegate = PublicDecisionChecker(self.ir, self.public_files)
        payload = {
            "adapter_version": ADAPTER_VERSION,
            "ir": self.ir.to_dict(),
            "public_files": {name: _sha256(content) for name, content in self.public_files.items()},
        }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False,
                               separators=(",", ":")).encode("utf-8")
        self.checker_sha256 = hashlib.sha256(canonical).hexdigest()

    def check(self, decisions: dict) -> dict:
        derived, derived_issues, metrics = _derive_decisions(decisions, self.problem)
        result = self._delegate.check(derived)
        result["requirement_checker_sha256"] = result["checker_sha256"]
        result["checker_sha256"] = self.checker_sha256
        mapping_issues = decisions.get("_mapping_violations", []) if isinstance(decisions, Mapping) else []
        if not isinstance(mapping_issues, list) or not all(isinstance(row, dict) for row in mapping_issues):
            mapping_issues = [_violation(
                OUTPUT_SCHEMA, ("mapping",), "mapping_issues", UNKNOWN,
                "mapping issues are missing or malformed",
            )]
        extras = list(mapping_issues) + derived_issues
        result["violations"].extend(extras)
        result["violations"].sort(key=lambda row: row["key"])
        for requirement_id in {row.get("requirement_id") for row in extras}:
            statuses = {row.get("status") for row in extras
                        if row.get("requirement_id") == requirement_id}
            result["verdicts"][requirement_id] = (
                UNKNOWN if UNKNOWN in statuses else FAIL if FAIL in statuses else PASS)
        statuses = set(result["verdicts"].values())
        result["business_status"] = UNKNOWN if UNKNOWN in statuses else FAIL if FAIL in statuses else PASS
        result["objective"] = metrics["net_objective"]
        result["objective_sense"] = OBJECTIVE_SENSE
        result["metrics"] = metrics
        result["public_file_sha256"] = {
            name: _sha256(content) for name, content in sorted(self.public_files.items())
        }
        result["requirement_ir"] = self.ir.to_dict()
        result["veto_enabled"] = False
        result["uncovered_rules"] = uncovered_rules()
        result["coverage_note"] = (
            "PASS covers the encoded public feasibility constraints only; uncovered semantics remain UNKNOWN "
            "and offline results do not establish independent official business truth."
        )
        return result


def check_decisions(decisions: dict, public_files: dict[str, str] | None = None,
                    ir: RequirementIR | None = None) -> dict:
    return FederatedPublicChecker(public_files, ir).check(decisions)


def check_solution_csv(csv_data: str | bytes, public_files: dict[str, str] | None = None) -> dict:
    files = load_public_files() if public_files is None else public_files
    return FederatedPublicChecker(files).check(solution_to_decisions(csv_data, files))


def check_solution_file(path: str | Path, public_files: dict[str, str] | None = None) -> dict:
    return check_solution_csv(Path(path).read_bytes(), public_files)
