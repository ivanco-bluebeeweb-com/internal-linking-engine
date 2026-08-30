"""Data models for Internal Linking Engine.

Collections (via ctx.store, same pattern as Sites Registry/SEO Audit Engine):
- ile_site_settings: per-site config (enabled, mode, limits, CTA targets, exclusions)
- ile_content_index: per-article metadata cache (title, categories, lang, links)
- ile_linking_plans: one scan/preview = one plan (per-post diffs, status)
- ile_linking_runs: dashboard row per apply/rollback event

See PREPARATION.md for full rationale.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from imperal_sdk import sdl

MODE_CHOICES = ("review_first", "full_auto")
PLAN_STATUS_CHOICES = ("pending_review", "applied", "rolled_back", "rejected")


# ---------------------------------------------------------------------------
# Site settings
# ---------------------------------------------------------------------------

class SiteSettings(sdl.Entity):
    """One site's Internal Linking Engine configuration. site_id matches the
    Sites Registry id/domain so both apps agree on identity without a
    translation table."""
    site_id: str = ""
    domain: str = ""
    enabled: bool = False
    mode: str = "review_first"  # review_first | full_auto
    max_links_per_post: int = 3
    max_cta_per_post: int = 1
    languages: list[str] = Field(default_factory=list)  # empty = auto-detect from content
    cta_targets: list[dict] = Field(default_factory=list)  # [{"url","label","tone"}]
    excluded_urls: list[str] = Field(default_factory=list)
    confirmed_applies_count: int = 0  # trust counter toward full_auto eligibility
    full_auto_threshold: int = 5
    last_scanned_at: str = ""
    created_at: str = ""
    updated_at: str = ""


class SiteSettingsList(sdl.EntityList[SiteSettings]):
    pass


class EnableSiteParams(BaseModel):
    site_id: str = Field(..., description="Site id/domain from Sites Registry to enable Internal Linking Engine for.")
    domain: str = Field(default="", description="Site domain, for display; defaults to site_id if left blank.")
    max_links_per_post: int = Field(default=3, description="Max internal links this engine may add per article (2-5 recommended).")
    languages: list[str] = Field(default_factory=list, description="Explicit language codes to isolate (e.g. ['ru','ro']). Leave empty to auto-detect per article.")


class UpdateSiteSettingsParams(BaseModel):
    site_id: str = Field(..., description="Site id to update settings for.")
    enabled: bool | None = Field(default=None, description="Turn the engine on/off for this site.")
    mode: str = Field(default="", description="review_first or full_auto. Blank keeps current value.")
    max_links_per_post: int | None = Field(default=None, description="Max internal links per article.")
    max_cta_per_post: int | None = Field(default=None, description="Max CTA blocks per article (usually 1).")
    languages: list[str] | None = Field(default=None, description="Explicit language codes to isolate.")
    cta_targets: list[dict] | None = Field(default=None, description="CTA target definitions: [{'url','label','tone'}].")
    excluded_urls: list[str] | None = Field(default=None, description="URLs to never modify.")
    full_auto_threshold: int | None = Field(default=None, description="Confirmed applies required before full_auto becomes eligible.")


class ListSitesParams(BaseModel):
    pass


class GetSiteSettingsParams(BaseModel):
    site_id: str = Field(..., description="Site id to read settings for.")


# ---------------------------------------------------------------------------
# Content index
# ---------------------------------------------------------------------------

class IndexedPost(sdl.Entity):
    """One article/page's cached metadata for relevance scoring. Populated
    from data Webbee already fetched via wordpress-hub (list_posts/
    get_post_content/get_post_meta/extract_links) and passed in -- this app
    never fetches it itself (see app.py docstring)."""
    site_id: str = ""
    post_id: str = ""
    title: str = ""
    slug: str = ""
    url: str = ""
    post_type: str = "post"
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    product_type: str = ""
    lang: str = ""
    excerpt: str = ""
    outbound_link_urls: list[str] = Field(default_factory=list)
    content_sample: str = ""  # bounded excerpt of raw content, for href-dedup checks
    content_hash: str = ""    # plan §4 step 1: unchanged hash => re-index is a no-op
    last_indexed_at: str = ""


class IndexedPostList(sdl.EntityList[IndexedPost]):
    pass


class IndexPostsParams(BaseModel):
    site_id: str = Field(..., description="Site id these posts belong to.")
    posts: list[dict] = Field(
        ...,
        description=(
            "Post metadata already fetched via wordpress-hub, one dict per post: "
            "post_id, title, slug, url, post_type, categories, tags, product_type, "
            "lang, excerpt, outbound_link_urls."
        ),
    )


class ListIndexedPostsParams(BaseModel):
    site_id: str = Field(..., description="Site id to list indexed posts for.")
    lang: str = Field(default="", description="Optional language filter, e.g. 'ru'.")


class GetSiteIndexStatusParams(BaseModel):
    site_id: str = Field(..., description="Site id to read index status for.")


# ---------------------------------------------------------------------------
# Relevance matching
# ---------------------------------------------------------------------------

class RelevanceMatch(BaseModel):
    """One scored candidate link target for a source post."""
    target_post_id: str = ""
    target_title: str = ""
    target_url: str = ""
    score: float = 0.0
    reason: str = ""  # e.g. "shared category: рекуператоры; same product_type; same lang"


class RelevanceMatchList(sdl.EntityList):
    items: list[RelevanceMatch] = []


class GetRelevantTargetsParams(BaseModel):
    site_id: str = Field(..., description="Site id.")
    source_post_id: str = Field(..., description="Post id (must already be indexed) to find relevant link targets for.")
    max_targets: int = Field(default=5, ge=1, le=10, description="Max candidate targets to return.")


# ---------------------------------------------------------------------------
# Linking plans (preview / apply / rollback / reject)
# ---------------------------------------------------------------------------

class LinkSuggestion(BaseModel):
    """One proposed internal-link anchor insertion inside a source article.
    find_exact_substring must match exactly once in the post's raw content --
    the same contract wordpress-hub.replace_post_content_text enforces, so
    Webbee can hand this straight to that tool without re-checking."""
    target_post_id: str = ""
    target_url: str = ""
    target_title: str = ""
    relevance_score: float = 0.0
    find_exact_substring: str = ""
    replacement_with_anchor: str = ""
    match_count: int = 0  # must be exactly 1 to be safely appliable; this app verifies and drops otherwise


class CtaSuggestion(BaseModel):
    """One proposed CTA block insertion (at most one per post per plan)."""
    target_url: str = ""
    cta_label: str = ""
    find_exact_substring: str = ""
    replacement_with_cta: str = ""
    match_count: int = 0


class PostPlanEntry(BaseModel):
    """One source article's full proposed diff within a linking plan."""
    post_id: str = ""
    title: str = ""
    url: str = ""
    lang: str = ""
    expected_state_token: str = ""
    link_suggestions: list[dict] = Field(default_factory=list)  # serialized LinkSuggestion
    cta_suggestion: dict | None = None  # serialized CtaSuggestion
    original_content_snapshot: dict = Field(default_factory=dict)  # {find_exact: original_full_text} for rollback


class LinkingPlan(sdl.Entity):
    """One scan/preview run for a site -- the unit preview_internal_links
    creates and apply_internal_links/reject_linking_plan/rollback_linking_run
    transition through PLAN_STATUS_CHOICES."""
    site_id: str = ""
    domain: str = ""
    created_at: str = ""
    status: str = "pending_review"
    entries: list[dict] = Field(default_factory=list)  # serialized PostPlanEntry
    links_added_count: int = 0
    cta_added_count: int = 0
    posts_touched_count: int = 0


class LinkingPlanList(sdl.EntityList[LinkingPlan]):
    pass


class PreviewInternalLinksParams(BaseModel):
    site_id: str = Field(..., description="Site id to build a linking+CTA plan for.")
    post_ids: list[str] = Field(
        default_factory=list,
        description="Optional explicit post ids to limit the plan to; empty scans every indexed post for this site.",
    )
    posts_content: list[dict] = Field(
        ...,
        description=(
            "Raw content + state tokens Webbee already fetched via wordpress-hub.get_post_content, one dict per "
            "post: {post_id, title, url, lang, raw_content, expected_state_token}. This app never fetches content "
            "itself (see app.py docstring)."
        ),
    )
    proposed_insertions: list[dict] = Field(
        default_factory=list,
        description=(
            "Optional: anchor/CTA insertions Webbee already drafted via an LLM pass per post, keyed by post_id: "
            "[{post_id, link_suggestions: [...], cta_suggestion: {...}}]. If omitted, this app only returns "
            "relevance-scored candidate targets per post without drafted anchor text (a lighter, metadata-only "
            "preview) -- Webbee can then draft insertions and call preview again to attach them."
        ),
    )


class GetLinkingPlanParams(BaseModel):
    plan_id: str = Field(..., description="Linking plan id from preview_internal_links.")


class ListLinkingPlansParams(BaseModel):
    site_id: str = Field(default="", description="Optional site id filter.")
    status: str = Field(default="", description="Optional status filter: pending_review, applied, rolled_back, rejected.")


class ApplyInternalLinksParams(BaseModel):
    plan_id: str = Field(..., description="Linking plan id to mark as applied, AFTER Webbee has actually written each diff via wordpress-hub.replace_post_content_text.")
    applied_post_ids: list[str] = Field(
        default_factory=list,
        description="Which post ids from the plan were actually written successfully; partial application is recorded honestly (not all-or-nothing).",
    )


class BatchApplyPlanItem(BaseModel):
    """One reviewed plan included in a single explicit batch confirmation."""
    plan_id: str = Field(..., description="Pending-review linking plan id to record as applied.")
    applied_post_ids: list[str] = Field(
        default_factory=list,
        description="Post ids from this plan whose diffs Webbee actually wrote successfully.",
    )


class ApplyInternalLinksBatchParams(BaseModel):
    """Explicit batch confirmation. No pending plan is selected implicitly."""
    plans: list[BatchApplyPlanItem] = Field(
        ...,
        min_length=1,
        max_length=50,
        description=(
            "Explicit reviewed plans to mark as applied after their exact WordPress diffs were written. "
            "Every id must still be pending_review; the operation is all-or-nothing for audit safety."
        ),
    )


class RejectLinkingPlanParams(BaseModel):
    plan_id: str = Field(..., description="Linking plan id to reject without applying.")


class RollbackLinkingRunParams(BaseModel):
    plan_id: str = Field(..., description="Applied plan id to roll back -- returns the original find/replace pairs for Webbee to write back via wordpress-hub.replace_post_content_text.")


# ---------------------------------------------------------------------------
# Runs dashboard
# ---------------------------------------------------------------------------

class LinkingRun(sdl.Entity):
    """One dashboard row: mirrors a LinkingPlan's lifecycle transitions for
    the at-a-glance runs table (§10 of the plan)."""
    site_id: str = ""
    domain: str = ""
    plan_id: str = ""
    created_at: str = ""
    status: str = "pending_review"
    links_added_count: int = 0
    cta_added_count: int = 0
    posts_touched_count: int = 0


class LinkingRunList(sdl.EntityList[LinkingRun]):
    pass


class ListLinkingRunsParams(BaseModel):
    site_id: str = Field(default="", description="Optional site id filter; empty lists across all sites.")
    limit: int = Field(default=50, ge=1, le=200, description="Max rows to return.")


# ---------------------------------------------------------------------------
# Scan schedule (plan §7 -- autonomous nightly scans)
# ---------------------------------------------------------------------------

class LinkingSchedule(sdl.Entity):
    """One site's autonomous linking-scan schedule (plan §7). The platform
    cron line is frozen at registration; the chosen hour/days live in the
    store so they can move without a redeploy (see scan_schedule.py)."""
    site_id: str = ""
    enabled: bool = False
    hour: int = 4           # UTC hour the scan fires at
    days: str = ""          # '1,3,5' style list; empty = every day
    last_date: str = ""     # UTC date the scan last fired (dedup guard)


class GetLinkingScheduleParams(BaseModel):
    site_id: str = Field(..., description="Site id to read the linking-scan schedule for.")


class SetLinkingScheduleParams(BaseModel):
    site_id: str = Field(..., description="Site id whose linking-scan schedule to change.")
    enabled: bool | None = Field(default=None, description="Turn the autonomous scan on (true) or off (false).")
    hour: int | None = Field(default=None, ge=0, le=23, description="UTC hour to fire at (default 4 -- nobody edits articles at night).")
    days: str | None = Field(default=None, description="Weekday list like '1,3,5' (1=Monday); empty string = every day.")
