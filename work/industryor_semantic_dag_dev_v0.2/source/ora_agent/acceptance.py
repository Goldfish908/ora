"""Fail-closed acceptance of candidates from deterministic checker evidence."""
from __future__ import annotations


def _has_evidence(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    try:
        return len(value) > 0
    except TypeError:
        return True


def _checker_accepted(checker_status) -> bool:
    if isinstance(checker_status, dict):
        return (checker_status.get("accepted") is True
                and checker_status.get("status", "accepted") == "accepted")
    return checker_status == "accepted"


def can_accept(record: dict, checker_status) -> bool:
    """Accept only a known, unfired candidate with a fully accepted checker."""
    if not isinstance(record, dict) or not _checker_accepted(checker_status):
        return False
    if record.get("status") != "ok" or record.get("fired") is not False:
        return False
    blocked_evidence = ("rejected", "rejected_count", "unknown", "unknown_count",
                        "unknown_evidence", "violations", "not_applicable", "error")
    if any(_has_evidence(record.get(key)) for key in blocked_evidence):
        return False
    return record.get("asset_status") in (None, "SATISFIED")
