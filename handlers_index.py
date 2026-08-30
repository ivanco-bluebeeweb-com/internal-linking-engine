"""Chat functions: Content Indexer -- caches per-post metadata for relevance
scoring. This app never fetches posts itself; Webbee fetches via
wordpress-hub (list_posts/get_post_content/get_post_meta/extract_links) and
passes the metadata in (see app.py docstring for why).

Plan §4 step 1 (incremental re-index): every indexed row carries a
content_hash of the post's raw content. Re-indexing an UNCHANGED post is a
cheap no-op that reports skipped, so a scheduled scan only pays for what
actually moved since last time.
"""
from __future__ import annotations

import hashlib

from imperal_sdk import ActionResult

from app import chat
from schemas import (
    IndexPostsParams, GetSiteIndexStatusParams,
    IndexedPost, IndexedPostList,
)
import storage


def _content_hash(post: dict) -> str:
    """Hash of everything the index stores about a post -- if it matches the
    stored row, nothing about this post changed since the last index pass."""
    payload = "|".join([
        str(post.get("title", "")),
        str(post.get("excerpt", "")),
        str(post.get("lang", "")),
        str(post.get("product_type", "")),
        ",".join(post.get("categories", []) or []),
        ",".join(post.get("tags", []) or []),
        ",".join(post.get("outbound_link_urls", []) or []),
        hashlib.sha256((post.get("raw_content_sample", "") or "").encode("utf-8")).hexdigest()[:16],
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@chat.function(
    "index_posts",
    description=(
        "Cache metadata for a batch of posts already fetched via wordpress-hub, so the "
        "Relevance Engine can score them without re-fetching. Call this once per post before "
        "get_relevant_targets/preview_internal_links can use it as a candidate or source."
    ),
    action_type="write",
    data_model=IndexedPostList,
    effects=["ile.posts_indexed"],
    event="internal-linking-engine.index_posts",
)
async def index_posts(ctx, params: IndexPostsParams) -> ActionResult:
    """Cache/refresh metadata for a batch of posts already fetched via wordpress-hub.

    Incremental (plan §4 step 1): a post whose content_hash matches the stored
    row is skipped -- no write, and the summary says so -- so repeated scans
    only pay for posts that actually changed."""
    now = storage.now_iso()
    saved: list[IndexedPost] = []
    skipped_unchanged = 0
    for post in params.posts:
        post_id = str(post.get("post_id", ""))
        if not post_id:
            continue
        new_hash = _content_hash(post)
        existing = await storage.find_indexed_post(ctx, params.site_id, post_id)
        if existing and existing.data.get("content_hash") == new_hash:
            skipped_unchanged += 1
            saved.append(IndexedPost(id=existing.id, **existing.data))
            continue
        data = {
            "site_id": params.site_id,
            "post_id": post_id,
            "title": post.get("title", ""),
            "slug": post.get("slug", ""),
            "url": post.get("url", ""),
            "post_type": post.get("post_type", "post"),
            "categories": post.get("categories", []) or [],
            "tags": post.get("tags", []) or [],
            "product_type": post.get("product_type", ""),
            "lang": post.get("lang", ""),
            "excerpt": post.get("excerpt", ""),
            "outbound_link_urls": post.get("outbound_link_urls", []) or [],
            "content_sample": (post.get("raw_content_sample", "") or "")[:2000],
            "content_hash": new_hash,
            "last_indexed_at": now,
        }
        if existing:
            await ctx.store.update(storage.INDEX_COLLECTION, existing.id, data)
            saved.append(IndexedPost(id=existing.id, **data))
        else:
            doc = await ctx.store.create(storage.INDEX_COLLECTION, data)
            saved.append(IndexedPost(id=doc.id, **data))

    summary = f"Indexed {len(saved)} post(s) for '{params.site_id}'"
    if skipped_unchanged:
        summary += f" ({skipped_unchanged} unchanged, skipped)"
    return ActionResult.success(
        IndexedPostList(items=saved),
        summary=summary + ".",
    )


@chat.function(
    "get_site_index_status",
    description="One-glance index health for a site: how many posts indexed, by language, and when last indexed.",
    action_type="read",
    data_model=IndexedPostList,
    event="internal-linking-engine.get_site_index_status",
)
async def get_site_index_status(ctx, params: GetSiteIndexStatusParams) -> ActionResult:
    """One-glance index health for a site: post count by language and last-indexed time."""
    rows = await storage.list_indexed_posts(ctx, params.site_id)
    by_lang: dict[str, int] = {}
    last_indexed = ""
    for r in rows:
        lang = r.get("lang") or "(unset)"
        by_lang[lang] = by_lang.get(lang, 0) + 1
        if r.get("last_indexed_at", "") > last_indexed:
            last_indexed = r.get("last_indexed_at", "")
    summary_parts = ", ".join(f"{lang}: {count}" for lang, count in sorted(by_lang.items()))
    items = [IndexedPost(**r) for r in rows]
    return ActionResult.success(
        IndexedPostList(items=items),
        summary=f"{len(rows)} post(s) indexed for '{params.site_id}' ({summary_parts or 'none'}). Last indexed: {last_indexed or 'never'}.",
    )
