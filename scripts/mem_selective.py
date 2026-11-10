#!/usr/bin/env python3
"""Selective memory injection: only inject clauses whose trigger matches
the instance's data. Prevents cross-context misuse (e.g. a substitution
clause applied to a no-substitution cell) and trims prompt cost.

Clause marking in conventions text: a line starting with
  [TRIGGER: <predicate>]
applies to the FOLLOWING clause block (up to the next [TRIGGER:] or section
header in [BRACKETS] or end of file). Unmarked blocks are ALWAYS kept.

Supported predicates (evaluated against the instance's data dict):
  sub_edges        -> data['sub_edges'] is non-empty
  trans_edges      -> data['trans_edges'] is non-empty
  shelf_life       -> data['shelf_life'] is a non-empty mapping
  moq              -> data['moq'] is non-empty
  return_rate      -> data['return_rate'] is non-empty
  no_substitution  -> data['sub_edges'] is empty
  not:<pred>       -> negation
  <pred>&<pred>    -> conjunction
"""
from __future__ import annotations

import re


def _active(pred: str, data: dict) -> bool:
    pred = pred.strip()
    if pred.startswith("not:"):
        return not _active(pred[4:], data)
    if "&" in pred:
        return all(_active(p, data) for p in pred.split("&"))
    val = data.get(pred)
    return bool(val)


def select_conventions(text: str, data: dict) -> str:
    """Filter conventions text by data-activated clause triggers."""
    lines = text.split("\n")
    out: list[str] = []
    keep = True
    in_trig = False
    for line in lines:
        m = re.match(r"^\[TRIGGER:\s*(.+?)\]\s*$", line.strip())
        if m:
            keep = _active(m.group(1), data)
            in_trig = True
            continue  # the trigger line itself is not injected
        if re.match(r"^\d+\.\s", line.strip()):
            if not in_trig:
                keep = True  # a new numbered clause outside a trigger block
            in_trig = False  # first numbered line after a trigger belongs to it
        if keep:
            out.append(line)
    return "\n".join(out).strip()
