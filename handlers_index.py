"""Chat functions: Content Indexer -- caches per-post metadata for relevance
scoring. This app never fetches posts itself; Webbee fetches via
wordpress-hub (list_posts/get_post_content/get_post_meta/extract_links) and
passes the metadata in (see app.py docstring for why)."""
from __future__ import annotations

from imperal_sdk import ActionResult

from app import chat
from schemas import (
    IndexPostsParams, GetSiteIndexStatusParams,
    IndexedPost, IndexedPostList,
)
import storage


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
    """Cache/refresh metadata for a batch of posts already fetched via wordpress-hub."""
    now = storage.now_iso()
    saved: list[IndexedPost] = []
    for post in params.posts:
        post_id = str(post.get("post_id", ""))
        if not post_id:
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
            "last_indexed_at": now,
        }
        existing = await storage.find_indexed_post(ctx, params.site_id, post_id)
        if existing:
            await ctx.store.update(storage.INDEX_COLLECTION, existing.id, data)
            saved.append(IndexedPost(id=existing.id, **data))
        else:
            doc = await ctx.store.create(storage.INDEX_COLLECTION, data)
            saved.append(IndexedPost(id=doc.id, **data))

    return ActionResult.success(
        IndexedPostList(items=saved),
        summary=f"Indexed {len(saved)} post(s) for '{params.site_id}'.",
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
