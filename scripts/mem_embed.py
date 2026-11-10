#!/usr/bin/env python3
"""Embedding-ranked memory injection (for the data-predicate vs embedding
ablation). Selects the top-k semantically similar OPTIONAL clauses per
problem and always keeps the universal clauses.

Optional clauses = numbered clauses in SEMANTIC CONVENTIONS (item 3) and
appended candidate units (# candidate ...). Universal = everything else.
"""
from __future__ import annotations

import re
from functools import lru_cache

import numpy as np


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-MiniLM-L6-v2", device="cpu")


def _split_clauses(text: str):
    """Return (universal_text, [(title, body)]) for optional selection."""
    lines = text.split("\n")
    universal, optional = [], []
    cur_title, cur_body = None, []
    opt_mode = False
    for line in lines:
        if line.strip().startswith("[TRIGGER:"):
            continue  # embedding arm ignores data-predicate markers
        m = re.match(r"^(\d+\.\s.+|# candidate.+)$", line.strip())
        if m:
            if cur_title is not None:
                optional.append((cur_title, "\n".join(cur_body)))
            cur_title, cur_body = line, []
            opt_mode = True
        else:
            if opt_mode and cur_title is not None:
                cur_body.append(line)
            else:
                universal.append(line)
    if cur_title is not None:
        optional.append((cur_title, "\n".join(cur_body)))
    return "\n".join(universal).strip(), optional


def select_by_embedding(text: str, prompt: str, top_k: int = 2) -> str:
    universal, optional = _split_clauses(text)
    if not optional:
        return universal
    model = _model()
    titles = [t for t, _ in optional]
    embs = model.encode([prompt[:600]] + titles,
                        normalize_embeddings=True)
    sims = embs[1:] @ embs[0]
    keep = set(np.argsort(-sims)[:top_k].tolist())
    parts = [universal]
    for i, (title, body) in enumerate(optional):
        if i in keep:
            parts.append(title + "\n" + body)
    return "\n\n".join(p for p in parts if p.strip()).strip()


def select_trigger_then_embedding(text: str, data: dict, prompt: str,
                                  top_k: int = 2) -> str:
    """Arm 4: deterministic trigger filter first, embedding rank second."""
    from scripts.mem_selective import select_conventions
    filtered = select_conventions(text, data)
    return select_by_embedding(filtered, prompt, top_k)
