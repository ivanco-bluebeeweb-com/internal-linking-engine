"""Chat functions: per-site Internal Linking Engine settings."""
from __future__ import annotations

from imperal_sdk import ActionResult

from app import chat
from schemas import (
    EnableSiteParams, UpdateSiteSettingsParams, ListSitesParams, GetSiteSettingsParams,
    SiteSettings, SiteSettingsList, MODE_CHOICES,
)
import storage


@chat.function(
    "enable_site",
    description=(
        "Turn on Internal Linking Engine for one site already known to Sites Registry. "
        "Creates the site's settings row in review_first mode by default -- no content is "
        "touched until a plan is previewed and explicitly applied."
    ),
    action_type="write",
    data_model=SiteSettings,
    effects=["ile.site_enabled"],
    event="internal-linking-engine.enable_site",
)
async def enable_site(ctx, params: EnableSiteParams) -> ActionResult:
    """Turn on the engine for a site (review-first by default); idempotent re-enable."""
    existing = await storage.find_settings(ctx, params.site_id)
    now = storage.now_iso()
    if existing:
        data = existing.data | {
            "enabled": True,
            "max_links_per_post": params.max_links_per_post,
            "languages": params.languages or existing.data.get("languages", []),
            "updated_at": now,
        }
        await ctx.store.update(storage.SETTINGS_COLLECTION, existing.id, data)
        return ActionResult.success(SiteSettings(id=existing.id, title=data.get("domain") or params.site_id, **data), summary=f"Re-enabled Internal Linking Engine for '{params.site_id}'.")

    data = {
        "site_id": params.site_id,
        "domain": params.domain or params.site_id,
        "enabled": True,
        "mode": "review_first",
        "max_links_per_post": params.max_links_per_post,
        "max_cta_per_post": 1,
        "languages": params.languages,
        "cta_targets": [],
        "excluded_urls": [],
        "confirmed_applies_count": 0,
        "full_auto_threshold": 5,
        "last_scanned_at": "",
        "created_at": now,
        "updated_at": now,
    }
    doc = await ctx.store.create(storage.SETTINGS_COLLECTION, data)
    return ActionResult.success(SiteSettings(id=doc.id, title=data["domain"], **data), summary=f"Internal Linking Engine enabled for '{data['domain']}' (review-first mode).")


@chat.function(
    "update_site_settings",
    description="Update an existing site's Internal Linking Engine settings (mode, limits, CTA targets, exclusions, languages). Only given fields change.",
    action_type="write",
    data_model=SiteSettings,
    effects=["ile.settings_updated"],
    event="internal-linking-engine.update_site_settings",
)
async def update_site_settings(ctx, params: UpdateSiteSettingsParams) -> ActionResult:
    """Patch selected settings fields for an already-enabled site."""
    existing = await storage.find_settings(ctx, params.site_id)
    if not existing:
        return ActionResult.error(f"No Internal Linking Engine settings found for site '{params.site_id}'. Call enable_site first.", retryable=False, code="SITE_NOT_ENABLED")

    data = dict(existing.data)
    if params.enabled is not None:
        data["enabled"] = params.enabled
    if params.mode:
        if params.mode not in MODE_CHOICES:
            return ActionResult.error(f"mode must be one of {MODE_CHOICES}.", retryable=False, code="INVALID_MODE")
        data["mode"] = params.mode
    if params.max_links_per_post is not None:
        data["max_links_per_post"] = params.max_links_per_post
    if params.max_cta_per_post is not None:
        data["max_cta_per_post"] = params.max_cta_per_post
    if params.languages is not None:
        data["languages"] = params.languages
    if params.cta_targets is not None:
        data["cta_targets"] = params.cta_targets
    if params.excluded_urls is not None:
        data["excluded_urls"] = params.excluded_urls
    if params.full_auto_threshold is not None:
        data["full_auto_threshold"] = params.full_auto_threshold
    data["updated_at"] = storage.now_iso()

    await ctx.store.update(storage.SETTINGS_COLLECTION, existing.id, data)
    return ActionResult.success(SiteSettings(id=existing.id, title=data.get("domain") or params.site_id, **data), summary=f"Updated settings for '{data.get('domain') or params.site_id}'.")


@chat.function(
    "list_sites",
    description="List every site with Internal Linking Engine settings (enabled or not), across every connected site.",
    action_type="read",
    data_model=SiteSettingsList,
    event="internal-linking-engine.list_sites",
)
async def list_sites(ctx, params: ListSitesParams) -> ActionResult:
    """List every site with Internal Linking Engine settings, enabled or not."""
    rows = await storage.list_settings(ctx)
    items = [SiteSettings(title=r.get("domain") or r.get("site_id", ""), **r) for r in rows]
    return ActionResult.success(SiteSettingsList(items=items), summary=f"{len(items)} site(s) configured.")


@chat.function(
    "get_site_settings",
    description="Read one site's Internal Linking Engine settings in full.",
    action_type="read",
    data_model=SiteSettings,
    event="internal-linking-engine.get_site_settings",
)
async def get_site_settings(ctx, params: GetSiteSettingsParams) -> ActionResult:
    """Read one site's full Internal Linking Engine settings."""
    existing = await storage.find_settings(ctx, params.site_id)
    if not existing:
        return ActionResult.error(f"No Internal Linking Engine settings found for site '{params.site_id}'.", retryable=False, code="SITE_NOT_ENABLED")
    return ActionResult.success(SiteSettings(id=existing.id, title=existing.data.get("domain") or params.site_id, **existing.data), summary=f"Settings for '{existing.data.get('domain') or params.site_id}'.")
