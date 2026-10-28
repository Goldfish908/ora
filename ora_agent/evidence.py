"""Requirement-traceability evidence schema for ora_agent. Stdlib only.

Five record types (dataclass + to_dict), persisted as one append-only
evidence.jsonl per trial (under <trial>/agent/ora/):

- Requirement: a requirement extracted from the task's public materials.
  hardness: "hard" (must hold, schema/constraint) | "soft" (quality target).
  status: "explicit" | "unresolved_ambiguity".
- ImplementationLink: where a requirement is implemented; artifact_version
  pins the implementing file by sha256 so edits invalidate the link.
- Finding: a suspected/confirmed problem tied to requirements and an
  artifact version. evidence_level: llm_judgment | actual_test |
  deterministic. status: suspected | confirmed | unresolved | refuted.
- CheckResult: one concrete check execution against an artifact version.
- RepairResult: outcome of a patch: resolved / confirmed_regressions /
  newly_discovered / unresolved finding ids.

Discipline encoded here:
- Append-only: nothing is ever rewritten or deleted. When an artifact
  changes, invalidate_links_for(old_hash) appends an invalidation record;
  affected ImplementationLink/CheckResult records are then reported as
  superseded (never removed).
- unknown/unresolved NEVER counts as passed: requirement_status() reports
  passed=True only when there is at least one passing CheckResult on the
  current artifact version AND no open (non-refuted, unresolved-included)
  findings tied to the requirement.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

RECORD_TYPES = frozenset({
    "requirement", "implementation_link", "finding", "check_result",
    "repair_result", "invalidation",
})

REQUIREMENT_STATUS = frozenset({"explicit", "unresolved_ambiguity"})
HARDNESS = frozenset({"hard", "soft"})
PROBLEM_TYPES = frozenset({"implementation", "semantic", "feasibility", "quality"})
EVIDENCE_LEVELS = frozenset({"llm_judgment", "actual_test", "deterministic"})
FINDING_STATUS = frozenset({"suspected", "confirmed", "unresolved", "refuted"})
# Findings in these states still block a "passed" verdict.
_OPEN_FINDING_STATUS = frozenset({"suspected", "confirmed", "unresolved"})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@dataclass
class Requirement:
    req_id: str
    statement: str
    source_refs: list[str] = field(default_factory=list)  # "file:fragment" locators
    scope: str = ""
    units: str = ""
    hardness: str = "hard"          # hard | soft
    status: str = "explicit"        # explicit | unresolved_ambiguity

    def __post_init__(self):
        if self.hardness not in HARDNESS:
            raise ValueError(f"hardness must be one of {sorted(HARDNESS)}")
        if self.status not in REQUIREMENT_STATUS:
            raise ValueError(f"status must be one of {sorted(REQUIREMENT_STATUS)}")

    def to_dict(self) -> dict:
        return {"req_id": self.req_id, "statement": self.statement,
                "source_refs": list(self.source_refs), "scope": self.scope,
                "units": self.units, "hardness": self.hardness,
                "status": self.status}


@dataclass
class ImplementationLink:
    req_id: str
    location: str                 # where implemented (code/model/data path)
    artifact_version: str         # sha256 of the implementing file
    coverage: str = ""            # note on what the link covers
    link_id: str = ""

    def __post_init__(self):
        if not self.link_id:
            self.link_id = _short_id("link")

    def to_dict(self) -> dict:
        return {"link_id": self.link_id, "req_id": self.req_id,
                "location": self.location,
                "artifact_version": self.artifact_version,
                "coverage": self.coverage}


@dataclass
class Finding:
    finding_id: str
    req_ids: list[str]
    artifact_hash: str
    problem_type: str             # implementation|semantic|feasibility|quality
    evidence_level: str           # llm_judgment|actual_test|deterministic
    detail: str = ""
    witness_ref: str = ""         # e.g. outcome file / log line ref
    status: str = "suspected"     # suspected|confirmed|unresolved|refuted

    def __post_init__(self):
        if self.problem_type not in PROBLEM_TYPES:
            raise ValueError(f"problem_type must be one of {sorted(PROBLEM_TYPES)}")
        if self.evidence_level not in EVIDENCE_LEVELS:
            raise ValueError(
                f"evidence_level must be one of {sorted(EVIDENCE_LEVELS)}")
        if self.status not in FINDING_STATUS:
            raise ValueError(f"status must be one of {sorted(FINDING_STATUS)}")

    def to_dict(self) -> dict:
        return {"finding_id": self.finding_id, "req_ids": list(self.req_ids),
                "artifact_hash": self.artifact_hash,
                "problem_type": self.problem_type,
                "evidence_level": self.evidence_level, "detail": self.detail,
                "witness_ref": self.witness_ref, "status": self.status}


@dataclass
class CheckResult:
    check_id: str
    artifact_version: str         # sha256 of the artifact checked
    input_hash: str
    actual_result: str            # e.g. "pass" | "fail" | "unknown" — unknown
                                  # never counts as pass (see module docstring)
    evidence_source: str          # how the check was executed
    ts: str = ""

    def __post_init__(self):
        if not self.ts:
            self.ts = _utc_now_iso()

    def to_dict(self) -> dict:
        return {"check_id": self.check_id,
                "artifact_version": self.artifact_version,
                "input_hash": self.input_hash,
                "actual_result": self.actual_result,
                "evidence_source": self.evidence_source, "ts": self.ts}


@dataclass
class RepairResult:
    patch_hash: str
    target_finding: str
    resolved: list[str] = field(default_factory=list)
    confirmed_regressions: list[str] = field(default_factory=list)
    newly_discovered: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    repair_id: str = ""

    def __post_init__(self):
        if not self.repair_id:
            self.repair_id = _short_id("repair")

    def to_dict(self) -> dict:
        return {"repair_id": self.repair_id, "patch_hash": self.patch_hash,
                "target_finding": self.target_finding,
                "resolved": list(self.resolved),
                "confirmed_regressions": list(self.confirmed_regressions),
                "newly_discovered": list(self.newly_discovered),
                "unresolved": list(self.unresolved)}


class EvidenceStore:
    """Append-only evidence.jsonl store with in-memory index.

    The file is loaded (replayed) on open, so a store survives restarts.
    Every append is flushed + fsync'd.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._records: list[dict] = []
        self._invalidated_hashes: set[str] = set()
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._index(rec)
        self._fp = open(self.path, "a", encoding="utf-8")

    def _index(self, rec: dict) -> None:
        self._records.append(rec)
        if rec.get("record_type") == "invalidation":
            self._invalidated_hashes.add(rec.get("artifact_hash"))

    # -- writing --------------------------------------------------------------

    def append(self, record) -> dict:
        """Append one of the five record dataclasses. Returns the stored row."""
        type_map = {
            Requirement: "requirement",
            ImplementationLink: "implementation_link",
            Finding: "finding",
            CheckResult: "check_result",
            RepairResult: "repair_result",
        }
        rtype = type_map.get(type(record))
        if rtype is None:
            raise TypeError(f"unsupported evidence record: {type(record).__name__}")
        row = {"record_type": rtype, "ts": _utc_now_iso(), **record.to_dict()}
        self._fp.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        self._fp.flush()
        os.fsync(self._fp.fileno())
        self._index(row)
        return row

    def invalidate_links_for(self, old_hash: str) -> int:
        """Mark all ImplementationLink/CheckResult rows pinned to old_hash as
        superseded (append-only: writes an invalidation record, deletes
        nothing). Returns the number of affected rows."""
        affected = sum(
            1 for r in self._records
            if r.get("record_type") in ("implementation_link", "check_result")
            and r.get("artifact_version") == old_hash
            and old_hash not in self._invalidated_hashes)
        row = {"record_type": "invalidation", "ts": _utc_now_iso(),
               "artifact_hash": old_hash, "superseded_count": affected}
        self._fp.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._fp.flush()
        os.fsync(self._fp.fileno())
        self._index(row)
        return affected

    # -- reading ----------------------------------------------------------------

    def is_superseded(self, rec: dict) -> bool:
        return (rec.get("record_type") in ("implementation_link", "check_result")
                and rec.get("artifact_version") in self._invalidated_hashes)

    def records(self, record_type: str | None = None,
                *, include_superseded: bool = True) -> list[dict]:
        out = []
        for r in self._records:
            if record_type and r.get("record_type") != record_type:
                continue
            if r.get("record_type") == "invalidation":
                if record_type is None:
                    continue  # meta-record; not part of domain queries
            row = dict(r)
            if self.is_superseded(r):
                if not include_superseded:
                    continue
                row["superseded"] = True
            out.append(row)
        return out

    def resolved_finding_ids(self) -> set[str]:
        ids: set[str] = set()
        for r in self.records("repair_result"):
            ids.update(r.get("resolved") or [])
        return ids

    def latest_findings(self) -> dict[str, dict]:
        """Latest record per finding_id (findings evolve: a later record with
        the same finding_id supersedes the earlier status, e.g. refuted)."""
        latest: dict[str, dict] = {}
        for f in self.records("finding"):
            latest[f.get("finding_id")] = f
        return latest

    def open_findings(self) -> list[dict]:
        """Findings still open: latest status suspected/confirmed/unresolved,
        not refuted, and not listed as resolved by any RepairResult.
        Unknown / unresolved findings stay open — they never count as
        passed."""
        resolved = self.resolved_finding_ids()
        return [f for f in self.latest_findings().values()
                if f.get("status") in _OPEN_FINDING_STATUS
                and f.get("finding_id") not in resolved]

    def by_req_id(self, req_id: str) -> dict:
        return {
            "requirements": [r for r in self.records("requirement")
                             if r.get("req_id") == req_id],
            "implementation_links": [r for r in self.records("implementation_link")
                                     if r.get("req_id") == req_id],
            "findings": [f for f in self.records("finding")
                         if req_id in (f.get("req_ids") or [])],
        }

    def requirement_status(self, req_id: str) -> dict:
        """Per-requirement rollup. passed=True requires at least one passing,
        non-superseded CheckResult AND zero open findings; unknown/unresolved
        never count as passed."""
        links = self.records("implementation_link", include_superseded=False)
        links = [l for l in links if l.get("req_id") == req_id]
        open_f = [f for f in self.open_findings()
                  if req_id in (f.get("req_ids") or [])]
        # Checks are tied to requirements through their artifact_version via
        # active links (a check on a linked artifact version counts).
        linked_versions = {l.get("artifact_version") for l in links}
        checks = [c for c in self.records("check_result",
                                          include_superseded=False)
                  if c.get("artifact_version") in linked_versions]
        passed_checks = [c for c in checks if c.get("actual_result") == "pass"]
        return {
            "req_id": req_id,
            "n_active_links": len(links),
            "n_checks": len(checks),
            "n_passed_checks": len(passed_checks),
            "n_open_findings": len(open_f),
            "passed": bool(passed_checks) and not open_f,
        }

    def close(self) -> None:
        if not self._fp.closed:
            self._fp.close()

    def __enter__(self) -> "EvidenceStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
