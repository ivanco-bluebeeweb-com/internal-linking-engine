"""Deterministic relevance scoring -- no embeddings, no ML dependency.

WHY THIS SHAPE (see app.py docstring + PREPARATION.md §5 for full rationale):
every app in this portfolio ships imperal-sdk only; adding a vector-embedding
stack here would be the first heavy ML dependency in the whole codebase for
one app. Instead: hard filters (language, excluded URLs, post itself) plus a
weighted score built from metadata overlap (categories/tags/product_type)
and a simple title/excerpt term-overlap -- explainable, auditable, and in
the same spirit as Content Strategy Hub's own keyword-overlap-based
cannibalization check.

LANGUAGE ISOLATION IS A HARD FILTER, NOT A SCORING FACTOR: a source post's
lang must exactly match a candidate's lang (when both are non-empty) or the
candidate is dropped before scoring even starts -- this is the direct lesson
from climtec.md (RU must never link to RO and vice versa).
"""
from __future__ import annotations

import re

_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "are", "was", "how", "what",
    "и", "в", "на", "с", "для", "как", "что", "это", "по", "не", "к", "от", "за", "или",
    "si", "in", "la", "de", "cu", "pentru", "ce", "un", "o", "care", "sau",
}


def _terms(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁăâîșțĂÂÎȘȚ]{3,}", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS}


def score_candidate(source: dict, candidate: dict) -> tuple[float, str]:
    """Score one candidate target post against one source post.
    Returns (score, human-readable reason). Caller is responsible for the
    hard language filter and self-exclusion before calling this."""
    score = 0.0
    reasons: list[str] = []

    src_cats = set(source.get("categories") or [])
    cand_cats = set(candidate.get("categories") or [])
    shared_cats = src_cats & cand_cats
    if shared_cats:
        score += 3.0 * len(shared_cats)
        reasons.append(f"shared categories: {', '.join(sorted(shared_cats))}")

    src_tags = set(source.get("tags") or [])
    cand_tags = set(candidate.get("tags") or [])
    shared_tags = src_tags & cand_tags
    if shared_tags:
        score += 2.0 * len(shared_tags)
        reasons.append(f"shared tags: {', '.join(sorted(shared_tags))}")

    src_pt = (source.get("product_type") or "").strip()
    cand_pt = (candidate.get("product_type") or "").strip()
    if src_pt and cand_pt and src_pt == cand_pt:
        score += 2.5
        reasons.append(f"same product_type: {src_pt}")

    src_terms = _terms(source.get("title", "")) | _terms(source.get("excerpt", ""))
    cand_terms = _terms(candidate.get("title", "")) | _terms(candidate.get("excerpt", ""))
    shared_terms = src_terms & cand_terms
    if shared_terms:
        score += 0.5 * len(shared_terms)
        reasons.append(f"shared terms: {', '.join(sorted(shared_terms)[:5])}")

    return score, "; ".join(reasons) if reasons else "no strong overlap"


def rank_targets(source: dict, candidates: list[dict], *, max_targets: int = 5) -> list[dict]:
    """Rank candidates for one source post. Hard filters applied here:
    - never suggest the post itself
    - never cross languages when both source and candidate have a lang set
    - drop zero-score candidates (no meaningful relevance signal)
    """
    src_id = source.get("post_id")
    src_lang = (source.get("lang") or "").strip()

    scored: list[dict] = []
    for cand in candidates:
        if cand.get("post_id") == src_id:
            continue
        cand_lang = (cand.get("lang") or "").strip()
        if src_lang and cand_lang and src_lang != cand_lang:
            continue  # hard language isolation -- never mix RU/RO etc.
        s, reason = score_candidate(source, cand)
        if s <= 0:
            continue
        scored.append({
            "target_post_id": cand.get("post_id", ""),
            "target_title": cand.get("title", ""),
            "target_url": cand.get("url", ""),
            "score": round(s, 2),
            "reason": reason,
        })

    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:max_targets]
