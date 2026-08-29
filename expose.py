"""Inter-extension IPC surfaces (ctx.extensions.call) for Internal Linking
Engine -- so another app (Content Strategy Hub's project tab today) can show
this engine's status/plans/runs as a section of ITS OWN UI, without the user
ever installing a second, separate app. Same @ext.expose pattern Sites
Registry already uses for WordPress Hub/Page Speed Insights.

Every surface here returns plain dicts (never Pydantic models, never
surfaced to the LLM directly) -- that is the IPC contract other apps in
this portfolio already rely on (see Sites Registry's handlers.py).
"""
from __future__ import annotations

from app import ext
import storage


@ext.expose("ping", action_type="read")
async def expose_ping(ctx, **kwargs) -> dict:
    """Cheap installed/reachable check, no store access -- mirrors Sites
    Registry's own expose_ping for the identical reason (see its docstring)."""
    return {"ok": True}


@ext.expose("get_status", action_type="read")
async def expose_get_status(ctx, *, site_id: str = "", **kwargs) -> dict:
    """One-glance status for a site: settings + index health + latest plan.
    Returns a plain dict:
    {"enabled", "mode", "max_links_per_post", "confirmed_applies_count",
     "full_auto_threshold", "indexed_post_count", "indexed_by_lang",
     "last_scanned_at", "latest_plan": {...} | None}
    """
    if not site_id:
        return {"enabled": False, "error": "site_id is required"}

    settings_doc = await storage.find_settings(ctx, site_id)
    settings = settings_doc.data if settings_doc else {}

    indexed = await storage.list_indexed_posts(ctx, site_id)
    by_lang: dict[str, int] = {}
    last_indexed = ""
    for r in indexed:
        lang = r.get("lang") or "(unset)"
        by_lang[lang] = by_lang.get(lang, 0) + 1
        if r.get("last_indexed_at", "") > last_indexed:
            last_indexed = r.get("last_indexed_at", "")

    plans = await storage.list_plans(ctx, site_id=site_id, limit=1)
    latest_plan = plans[0] if plans else None

    return {
        "enabled": bool(settings.get("enabled", False)),
        "mode": settings.get("mode", "review_first"),
        "max_links_per_post": settings.get("max_links_per_post", 3),
        "confirmed_applies_count": settings.get("confirmed_applies_count", 0),
        "full_auto_threshold": settings.get("full_auto_threshold", 5),
        "indexed_post_count": len(indexed),
        "indexed_by_lang": by_lang,
        "last_scanned_at": last_indexed,
        "latest_plan": latest_plan,
    }


@ext.expose("list_plans", action_type="read")
async def expose_list_plans(ctx, *, site_id: str = "", limit: int = 10, **kwargs) -> list[dict]:
    """Recent linking plans for a site, newest first."""
    if not site_id:
        return []
    return await storage.list_plans(ctx, site_id=site_id, limit=limit)


@ext.expose("list_runs", action_type="read")
async def expose_list_runs(ctx, *, site_id: str = "", limit: int = 10, **kwargs) -> list[dict]:
    """Recent apply/rollback run-dashboard rows for a site, newest first."""
    if not site_id:
        return []
    return await storage.list_runs(ctx, site_id=site_id, limit=limit)


@ext.expose("enable_site", action_type="write")
async def expose_enable_site(ctx, *, site_id: str = "", domain: str = "", **kwargs) -> dict:
    """Turn the engine on for a site from another app's UI (e.g. Content
    Strategy Hub's project tab 'Enable' button) without the user having to
    open this app directly. Idempotent -- re-enabling an existing site just
    flips enabled=True again."""
    if not site_id:
        return {"ok": False, "error": "site_id is required"}

    existing = await storage.find_settings(ctx, site_id)
    now = storage.now_iso()
    if existing:
        data = existing.data | {"enabled": True, "updated_at": now}
        await ctx.store.update(storage.SETTINGS_COLLECTION, existing.id, data)
        return {"ok": True, "site_id": site_id, "created": False}

    data = {
        "site_id": site_id,
        "domain": domain or site_id,
        "enabled": True,
        "mode": "review_first",
        "max_links_per_post": 3,
        "max_cta_per_post": 1,
        "languages": [],
        "cta_targets": [],
        "excluded_urls": [],
        "confirmed_applies_count": 0,
        "full_auto_threshold": 5,
        "last_scanned_at": "",
        "created_at": now,
        "updated_at": now,
    }
    await ctx.store.create(storage.SETTINGS_COLLECTION, data)
    return {"ok": True, "site_id": site_id, "created": True}
