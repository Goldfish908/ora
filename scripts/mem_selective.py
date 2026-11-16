#!/usr/bin/env python3
"""Select memory clauses by deterministic, data-activated predicates.

A [TRIGGER: <predicate>] marker applies to the following numbered clause.
Unmarked blocks are retained. Supported predicates use each dataset's nested
schema, with a top-level fallback for older exports:
  sub_edges / trans_edges -> data['network'][name]
  moq                     -> data['constraints']['moq']
  shelf_life/return_rate  -> top-level fields
  no_substitution         -> negation of sub_edges
  not:<pred>, <a>&<b>     -> negation and conjunction
"""
from __future__ import annotations

import re

_PATHS = {
    "sub_edges": ("network", "sub_edges"),
    "trans_edges": ("network", "trans_edges"),
    "moq": ("constraints", "moq"),
}


def _value(pred: str, data: dict):
    if pred == "no_substitution":
        return not _value("sub_edges", data)
    path = _PATHS.get(pred)
    if path:
        value = data
        for key in path:
            value = value.get(key, {}) if isinstance(value, dict) else {}
        if value:
            return value
    return data.get(pred)


def _active(pred: str, data: dict) -> bool:
    pred = pred.strip()
    if pred.startswith("not:"):
        return not _active(pred[4:], data)
    if "&" in pred:
        return all(_active(p, data) for p in pred.split("&"))
    return bool(_value(pred, data))


def select_conventions_with_trace(text: str, data: dict) -> tuple[str, list[dict]]:
    lines = text.split("\n")
    out: list[str] = []
    trace: list[dict] = []
    keep = True
    in_trig = False
    current = None
    for line in lines:
        m = re.match(r"^\[TRIGGER:\s*(.+?)\]\s*$", line.strip())
        if m:
            predicate = m.group(1)
            keep = _active(predicate, data)
            in_trig = True
            current = {"predicate": predicate, "active": keep, "clause": None}
            trace.append(current)
            continue
        if re.match(r"^\d+\.\s", line.strip()):
            if current is not None and current["clause"] is None:
                current["clause"] = line.strip()
            if not in_trig:
                keep = True
            in_trig = False
        if keep:
            out.append(line)
    return "\n".join(out).strip(), trace


def select_conventions(text: str, data: dict) -> str:
    return select_conventions_with_trace(text, data)[0]
