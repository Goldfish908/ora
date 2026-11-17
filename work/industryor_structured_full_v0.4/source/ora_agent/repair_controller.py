"""Deterministic repair-action selection based on candidate and evidence progress."""
from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import asdict, dataclass, field

from ora_agent.acceptance import can_accept

ACTIONS = (
    "local_patch", "regenerate", "acquire_evidence", "repair_checker",
    "specialized_api_repair", "stop",
)


def code_sha256(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def scip_sense_error(record: dict) -> str | None:
    error = (record.get("stderr_tail") or "").lower()
    match = re.search(r"unrecognized optimization sense:\s*(max|min)\b", error)
    return match.group(1) if match else None


def failure_signature(record: dict, audit: dict) -> str:
    if audit.get("fired"):
        rules = sorted({str(item.get("rule")) for item in audit.get("violations", [])})
        return "semantic:" + ",".join(rules)
    sense = scip_sense_error(record)
    if sense:
        return f"execution:optimization_sense:{sense}"
    if audit.get("status") == "unknown":
        error = (record.get("stderr_tail") or "").strip().splitlines()
        if error:
            detail = re.sub(r"line \d+", "line <n>", error[-1].strip())
            return f"execution:{record.get('exec_status', 'unknown')}:{detail}"
        return "unknown:" + str(audit.get("reason") or "insufficient_evidence")
    return str(audit.get("status") or "unknown")


class FailureKind:
    API = "api"
    EXECUTION = "execution"
    CONTRACT = "contract"
    SEMANTIC_LOCAL = "semantic_local"
    SEMANTIC_COMPLEX = "semantic_complex"
    CONSTRAINT_EXPLOSION = "constraint_explosion"
    UNKNOWN = "unknown"
    CHECKER = "checker"


@dataclass(frozen=True)
class BudgetPolicy:
    api: int = 1
    execution: int = 2
    contract: int = 2
    semantic_local: int = 2
    semantic_complex: int = 3
    constraint_explosion: int = 1
    unknown: int = 0
    checker: int = 0
    violation_explosion_threshold: int = 8


def violation_magnitudes(audit: dict) -> dict[str, float]:
    values = {}
    for item in audit.get("violations", []):
        delta = item.get("delta")
        if isinstance(delta, (int, float)) and not isinstance(delta, bool):
            values[str(item.get("rule"))] = abs(float(delta))
    return values


def evidence_improved(previous: dict[str, float], current: dict[str, float]) -> bool:
    if not previous or set(previous) != set(current):
        return False
    return (any(current[rule] < previous[rule] - 1e-9 for rule in previous)
            and all(current[rule] <= previous[rule] + 1e-9 for rule in previous))


def classify_failure(record: dict, audit: dict, checker_status: str,
                     explosion_threshold: int) -> str:
    if checker_status == "rejected":
        return FailureKind.CHECKER
    if scip_sense_error(record):
        return FailureKind.API
    if audit.get("status") == "unknown" and audit.get("reason") != "no_solution":
        return FailureKind.UNKNOWN
    reason = str(audit.get("reason") or record.get("status") or "")
    if (audit.get("reason") == "no_solution" or record.get("exec_status") not in (None, "ok")
            or reason in {"contract_invalid", "invalid_shared_schema", "problem_id_mismatch",
                          "no_complete_json", "invalid_candidate"}):
        return FailureKind.CONTRACT
    violations = audit.get("violations", [])
    rules = {str(item.get("rule")) for item in violations}
    repeated_time_semantics = bool(rules) and all(rule.startswith(
        ("job_precedence", "job_completion", "job_machine_sequence")) for rule in rules)
    if len(violations) >= explosion_threshold and not repeated_time_semantics:
        return FailureKind.CONSTRAINT_EXPLOSION
    if len(violations) > 1:
        return FailureKind.SEMANTIC_COMPLEX
    if audit.get("status") == "unknown":
        return FailureKind.UNKNOWN
    return FailureKind.SEMANTIC_LOCAL


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    code_sha256: str
    failure_signature: str
    failure_kind: str = FailureKind.SEMANTIC_LOCAL
    evidence: dict[str, float] = field(default_factory=dict)
    new_error_introduced: bool = False


@dataclass
class Attempt:
    action: str
    code_sha256: str
    failure_signature: str
    result_code_sha256: str
    no_progress: bool | None = None
    failure_kind: str = FailureKind.SEMANTIC_LOCAL
    evidence: dict[str, float] = field(default_factory=dict)
    evidence_improved: bool = False
    new_error_introduced: bool = False


class ProgressController:
    def __init__(self, budget: BudgetPolicy | None = None):
        self.budget = budget or BudgetPolicy()
        self.attempts: list[Attempt] = []

    def decide(self, code: str, record: dict, audit: dict, remaining: int,
               checker_status: str = "accepted") -> Decision:
        digest = code_sha256(code)
        signature = failure_signature(record, audit)
        evidence = violation_magnitudes(audit)
        kind = classify_failure(record, audit, checker_status,
                                self.budget.violation_explosion_threshold)
        self._current_kind = kind
        self._current_evidence = evidence
        if self.attempts and self.attempts[-1].no_progress is None:
            previous = self.attempts[-1]
            previous.new_error_introduced = (previous.new_error_introduced
                                             or bool(set(evidence) - set(previous.evidence)))
            previous.evidence_improved = evidence_improved(previous.evidence, evidence)
            previous.no_progress = (previous.code_sha256 == previous.result_code_sha256
                                    or (previous.failure_signature == signature
                                        and not previous.evidence_improved))
        self._new_error = self.attempts[-1].new_error_introduced if self.attempts else False
        if can_accept(audit, checker_status):
            return self._decision("stop", "accepted", digest, signature)
        if remaining <= 0:
            return self._decision("stop", "budget_exhausted", digest, signature)
        if checker_status == "rejected":
            return self._decision("repair_checker", "independent_gate_rejected",
                                  digest, signature)
        if scip_sense_error(record):
            if any(item.action == "specialized_api_repair"
                   and item.failure_signature == signature for item in self.attempts):
                return self._decision("stop", "specialized_api_repair_did_not_change_failure",
                                      digest, signature)
            return self._action("specialized_api_repair", "known_pyscipopt_sense_api",
                                digest, signature)
        if audit.get("status") == "not_applicable":
            return self._decision("stop", "not_applicable", digest, signature)
        if kind == FailureKind.UNKNOWN and audit.get("reason") != "no_solution":
            details = " ".join(str(item.get("detail", ""))
                               for item in audit.get("unknown_evidence", []))
            reason = ("needs_clarification" if "missing path" in details
                      else "unknown_is_not_acceptance")
            return self._decision("acquire_evidence", reason, digest, signature)
        if checker_status != "accepted" and audit.get("reason") != "no_solution":
            return self._decision("acquire_evidence", "checker_validation_required",
                                  digest, signature)
        same_failure = [item for item in self.attempts
                        if item.failure_signature == signature]
        budget = getattr(self.budget, kind)
        if len(same_failure) >= budget and kind == FailureKind.SEMANTIC_COMPLEX:
            return self._decision("stop", f"budget_exhausted_for_{kind}", digest, signature)
        if kind == FailureKind.CONSTRAINT_EXPLOSION:
            if same_failure:
                return self._decision("stop", "constraint_complexity_exceeded", digest, signature)
            return self._action("regenerate", "constraint_complexity_requires_new_candidate",
                                digest, signature)
        if any(item.action == "regenerate" and item.new_error_introduced
               for item in self.attempts):
            return self._decision("stop", "new_error_after_regenerate", digest, signature)
        if any(item.action == "local_patch" and item.new_error_introduced
               for item in self.attempts):
            return self._action("regenerate", "new_error_after_local_patch", digest, signature)
        if same_failure and not same_failure[-1].no_progress:
            return self._action("local_patch", "evidence_improved", digest, signature)
        if kind == FailureKind.SEMANTIC_COMPLEX:
            if same_failure:
                return self._action("regenerate", "same_failure_after_local_patch",
                                    digest, signature)
            return self._action("local_patch", "first_action_for_failure", digest, signature)
        if any(item.action == "local_patch" and item.failure_signature == signature
               for item in same_failure):
            if any(item.action == "regenerate" and item.failure_signature == signature
                   for item in same_failure):
                return self._decision("stop", "no_progress_after_local_patch_and_regenerate",
                                      digest, signature)
            return self._action("regenerate", "same_failure_after_local_patch",
                                digest, signature)
        return self._action("local_patch", "first_action_for_failure", digest, signature)

    def _action(self, action: str, reason: str, digest: str, signature: str) -> Decision:
        duplicate = any(item.action == action and item.code_sha256 == digest
                        and item.failure_signature == signature for item in self.attempts)
        if duplicate:
            return self._decision("stop", "duplicate_action", digest, signature)
        return self._decision(action, reason, digest, signature)

    def _decision(self, action: str, reason: str, digest: str, signature: str) -> Decision:
        if action not in ACTIONS:
            raise ValueError(f"unsupported repair action: {action}")
        return Decision(action, reason, digest, signature,
                        failure_kind=self._current_kind, evidence=self._current_evidence,
                        new_error_introduced=self._new_error)

    @property
    def _current_kind(self) -> str:
        return getattr(self, "_kind", FailureKind.SEMANTIC_LOCAL)

    @_current_kind.setter
    def _current_kind(self, value: str) -> None:
        self._kind = value

    @property
    def _current_evidence(self) -> dict[str, float]:
        return getattr(self, "_evidence", {})

    @_current_evidence.setter
    def _current_evidence(self, value: dict[str, float]) -> None:
        self._evidence = value

    def record(self, decision: Decision, result_code: str) -> None:
        if decision.action == "stop":
            return
        self.attempts.append(Attempt(decision.action, decision.code_sha256,
                                     decision.failure_signature, code_sha256(result_code),
                                     failure_kind=decision.failure_kind,
                                     evidence=decision.evidence,
                                     new_error_introduced=decision.new_error_introduced))

    @property
    def no_progress_count(self) -> int:
        return sum(item.no_progress is True for item in self.attempts)

    @property
    def new_error_count(self) -> int:
        return sum(item.new_error_introduced for item in self.attempts)

    @property
    def evidence_improved_count(self) -> int:
        return sum(item.evidence_improved for item in self.attempts)

    def trace(self) -> list[dict]:
        return [asdict(item) for item in self.attempts]


def repair_scip_sense(code: str, sense: str) -> str:
    replacement = {"max": "maximize", "min": "minimize"}.get(sense)
    if replacement is None:
        raise ValueError(f"unsupported SCIP sense repair: {sense}")
    tree = ast.parse(code)
    lines = code.splitlines(keepends=True)
    edits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setObjective"):
            continue
        for keyword in node.keywords:
            if (keyword.arg == "sense" and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value == sense):
                start = keyword.value
                edits.append((start.col_offset, start.end_col_offset,
                              start.lineno, start.end_lineno, replacement))
    if not edits:
        raise ValueError(f"no literal setObjective sense={sense!r} found")
    if any(line != end_line for _, _, line, end_line, _ in edits):
        raise ValueError("multiline optimization-sense literals require LLM repair")
    for start, end, line, _, value in sorted(edits, reverse=True):
        index = line - 1
        lines[index] = lines[index][:start] + repr(value) + lines[index][end:]
    return "".join(lines)
