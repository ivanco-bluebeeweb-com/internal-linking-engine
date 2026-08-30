"""Link-graph edge helpers -- plan §4 (link_graph_edges) + §5 filter 3.

One row per live internal link the engine has inserted:
    {site_id, from_post_id, to_post_id, anchor_text, target_url,
     inserted_at, source ("auto"|"manual"), status ("live"|"reverted")}

Two guardrails this powers, straight from the development plan:
- "не является уже существующей ссылкой" -- a candidate the source post
  already links to is dropped BEFORE scoring (get_relevant_targets), so the
  engine never stacks a second link onto the same target;
- "не более 1 ссылки от A на B" -- preview_internal_links rejects a proposed
  insertion whose (from, to) pair is already live in the graph.

Edges are recorded when Webbee confirms a plan was actually written
(apply_internal_links / apply_internal_links_batch), and flipped to
"reverted" by rollback_linking_run, so history is kept for audit instead of
deleted.
"""
from __future__ import annotations

import re

import storage

EDGE_COLLECTION = "ile_link_graph_edges"

_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


def urls_in_html(html: str) -> set[str]:
    """Every href URL appearing in one article's raw content."""
    return set(_HREF_RE.findall(html or ""))


async def record_edge(ctx, *, site_id: str, from_post_id: str, to_post_id: str,
                      target_url: str, anchor_text: str, source: str = "auto") -> None:
    """Upsert one live edge (from -> to). Re-inserting an existing pair just
    refreshes its timestamp/status rather than duplicating rows."""
    page = await ctx.store.query(EDGE_COLLECTION, limit=500)
    for doc in page.data:
        d = doc.data
        if d.get("site_id") == site_id and d.get("from_post_id") == from_post_id \
                and d.get("to_post_id") == to_post_id:
            await ctx.store.update(EDGE_COLLECTION, doc.id, d | {
                "status": "live",
                "target_url": target_url or d.get("target_url", ""),
                "anchor_text": anchor_text or d.get("anchor_text", ""),
                "inserted_at": storage.now_iso(),
            })
            return
    await ctx.store.create(EDGE_COLLECTION, {
        "title": f"{from_post_id} -> {to_post_id or target_url}",
        "site_id": site_id,
        "from_post_id": from_post_id,
        "to_post_id": to_post_id,
        "target_url": target_url,
        "anchor_text": anchor_text,
        "source": source,
        "status": "live",
        "inserted_at": storage.now_iso(),
    })


async def revert_edge(ctx, *, site_id: str, from_post_id: str, to_post_id: str,
                      target_url: str = "") -> None:
    """Flip a matching live edge to reverted (rollback). Falls back to matching
    by target_url when the pair was recorded without a post id (CTA pages)."""
    page = await ctx.store.query(EDGE_COLLECTION, limit=500)
    for doc in page.data:
        d = doc.data
        if d.get("site_id") != site_id or d.get("from_post_id") != from_post_id:
            continue
        same_id = to_post_id and d.get("to_post_id") == to_post_id
        same_url = target_url and (d.get("target_url") or "").rstrip("/") == target_url.rstrip("/")
        if (same_id or same_url) and d.get("status") == "live":
            await ctx.store.update(EDGE_COLLECTION, doc.id, d | {"status": "reverted"})


async def edges_from(ctx, site_id: str, from_post_id: str) -> list[dict]:
    """All live edges leaving one post."""
    page = await ctx.store.query(EDGE_COLLECTION, limit=500)
    return [doc.data for doc in page.data
            if doc.data.get("site_id") == site_id
            and doc.data.get("from_post_id") == from_post_id
            and doc.data.get("status") == "live"]


async def linked_target_ids(ctx, site_id: str, from_post_id: str) -> set[str]:
    """Post ids this source already links to (live edges only)."""
    return {e.get("to_post_id") for e in await edges_from(ctx, site_id, from_post_id)
            if e.get("to_post_id")}
