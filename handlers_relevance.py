"""Chat function: Relevance Engine -- top-N candidate link targets for one
source post, language-isolated, from already-indexed metadata."""
from __future__ import annotations

from imperal_sdk import ActionResult

from app import chat
from schemas import GetRelevantTargetsParams, RelevanceMatch, RelevanceMatchList
import storage
import relevance as relevance_lib


@chat.function(
    "get_relevant_targets",
    description=(
        "Find the top-N internal-link targets for one already-indexed source post, using "
        "deterministic metadata + term-overlap scoring (categories/tags/product_type/title). "
        "Language isolation is a hard filter -- a candidate whose lang differs from the source "
        "post's lang is never returned, even if it scores highest (the climtec.md RU/RO lesson). "
        "Excluded URLs from the site's settings are also dropped before scoring."
    ),
    action_type="read",
    data_model=RelevanceMatchList,
    event="internal-linking-engine.get_relevant_targets",
)
async def get_relevant_targets(ctx, params: GetRelevantTargetsParams) -> ActionResult:
    """Score already-indexed candidates for link-worthiness against one source post."""
    source_doc = await storage.find_indexed_post(ctx, params.site_id, params.source_post_id)
    if not source_doc:
        return ActionResult.error(
            "That post is not indexed yet -- call index_posts first.",
            retryable=False, code="POST_NOT_INDEXED",
        )
    source = source_doc.data
    source_lang = (source.get("lang") or "").strip()

    settings_doc = await storage.find_settings(ctx, params.site_id)
    excluded = set((settings_doc.data.get("excluded_urls") if settings_doc else []) or [])

    candidates = await storage.list_indexed_posts(ctx, params.site_id)
    scored: list[RelevanceMatch] = []
    for cand in candidates:
        if cand.get("post_id") == params.source_post_id:
            continue
        if cand.get("url") in excluded:
            continue
        cand_lang = (cand.get("lang") or "").strip()
        if source_lang and cand_lang and source_lang != cand_lang:
            continue  # hard language isolation -- never a scoring factor
        score, reason = relevance_lib.score_candidate(source, cand)
        if score <= 0:
            continue
        scored.append(RelevanceMatch(
            target_post_id=cand.get("post_id", ""),
            target_title=cand.get("title", ""),
            target_url=cand.get("url", ""),
            score=score,
            reason=reason,
        ))

    scored.sort(key=lambda m: m.score, reverse=True)
    top = scored[: params.max_targets]
    result = RelevanceMatchList(items=top)
    return ActionResult.success(result, summary=f"Found {len(top)} relevant target(s) for '{source.get('title', params.source_post_id)}'.")
