"""Chat functions: Diff & Safety Layer -- preview_internal_links / 
apply_internal_links / reject_linking_plan / rollback_linking_run /
get_linking_plan / list_linking_plans / list_linking_runs.

This is the ONLY place a linking plan is decided. It never writes to a real
site's content itself -- it always returns exact find/replace instructions
for Webbee to hand to wordpress-hub.replace_post_content_text (see app.py
docstring for the full "why"). apply_internal_links only records that
Webbee already did the writing; it does not perform it.
"""
from __future__ import annotations

from imperal_sdk import ActionResult

from app import chat
from schemas import (
    PreviewInternalLinksParams, GetLinkingPlanParams, ListLinkingPlansParams,
    ApplyInternalLinksParams, RejectLinkingPlanParams, RollbackLinkingRunParams,
    ListLinkingRunsParams,
    LinkingPlan, LinkingPlanList, LinkingRun, LinkingRunList,
)
import storage


def _count_uniquely(raw_content: str, substring: str) -> int:
    if not substring:
        return 0
    return raw_content.count(substring)


@chat.function(
    "preview_internal_links",
    description=(
        "Build a preview linking+CTA plan for a site -- NEVER writes anything. Takes raw content "
        "Webbee already fetched via wordpress-hub.get_post_content, and (optionally) anchor/CTA "
        "insertions Webbee already drafted via an LLM pass, and validates every proposed insertion's "
        "find_exact_substring occurs EXACTLY ONCE in that post's current raw content -- any insertion "
        "that doesn't is dropped, never guessed. Returns a plan_id; nothing is applied until "
        "apply_internal_links is called after Webbee has actually written each surviving diff via "
        "wordpress-hub.replace_post_content_text."
    ),
    action_type="write",
    data_model=LinkingPlan,
    effects=["ile.plan_previewed"],
    event="internal-linking-engine.preview_internal_links",
)
async def preview_internal_links(ctx, params: PreviewInternalLinksParams) -> ActionResult:
    """Validate proposed insertions against exact-once substring match; never writes anything."""
    settings_doc = await storage.find_settings(ctx, params.site_id)
    if not settings_doc or not settings_doc.data.get("enabled"):
        return ActionResult.error(
            "Internal Linking Engine is not enabled for this site -- call enable_site first.",
            retryable=False, code="SITE_NOT_ENABLED",
        )
    max_links = int(settings_doc.data.get("max_links_per_post", 3))
    max_cta = int(settings_doc.data.get("max_cta_per_post", 1))

    proposals_by_post = {p.get("post_id"): p for p in (params.proposed_insertions or [])}

    entries: list[dict] = []
    links_added = 0
    cta_added = 0
    posts_touched = 0

    for post in params.posts_content:
        post_id = str(post.get("post_id", ""))
        raw = post.get("raw_content", "") or ""
        proposal = proposals_by_post.get(post_id, {})
        link_suggestions_in = proposal.get("link_suggestions", []) or []
        cta_in = proposal.get("cta_suggestion")

        surviving_links: list[dict] = []
        snapshot: dict = {}
        for ls in link_suggestions_in[:max_links]:
            find = ls.get("find_exact_substring", "")
            count = _count_uniquely(raw, find)
            if count != 1:
                continue  # exact-once contract -- drop, never guess
            surviving_links.append(ls | {"match_count": count})
            snapshot[find] = find  # original text IS the find string (pre-insertion)

        surviving_cta = None
        if cta_in and max_cta > 0:
            find = cta_in.get("find_exact_substring", "")
            count = _count_uniquely(raw, find)
            if count == 1:
                surviving_cta = cta_in | {"match_count": count}
                snapshot[find] = find

        if not surviving_links and not surviving_cta:
            continue

        entries.append({
            "post_id": post_id,
            "title": post.get("title", ""),
            "url": post.get("url", ""),
            "lang": post.get("lang", ""),
            "expected_state_token": post.get("expected_state_token", ""),
            "link_suggestions": surviving_links,
            "cta_suggestion": surviving_cta,
            "original_content_snapshot": snapshot,
        })
        links_added += len(surviving_links)
        cta_added += 1 if surviving_cta else 0
        posts_touched += 1

    data = {
        "site_id": params.site_id,
        "domain": settings_doc.data.get("domain", params.site_id),
        "created_at": storage.now_iso(),
        "status": "pending_review",
        "entries": entries,
        "links_added_count": links_added,
        "cta_added_count": cta_added,
        "posts_touched_count": posts_touched,
    }
    plan_doc = await ctx.store.create(storage.PLANS_COLLECTION, data)
    plan_id = plan_doc.id
    await ctx.store.create(storage.RUNS_COLLECTION, {
        "site_id": params.site_id, "domain": data["domain"], "plan_id": plan_id,
        "created_at": data["created_at"], "status": "pending_review",
        "links_added_count": links_added, "cta_added_count": cta_added,
        "posts_touched_count": posts_touched,
    })

    return ActionResult.success(
        LinkingPlan(id=plan_id, **data),
        summary=f"Plan {plan_id}: {posts_touched} post(s), {links_added} link(s) + {cta_added} CTA(s) proposed.",
    )


@chat.function(
    "get_linking_plan",
    description="Read one linking plan in full -- every post's proposed diff, for review before applying.",
    action_type="read",
    data_model=LinkingPlan,
    event="internal-linking-engine.get_linking_plan",
)
async def get_linking_plan(ctx, params: GetLinkingPlanParams) -> ActionResult:
    """Read one linking plan in full, for review before applying."""
    doc = await ctx.store.get(storage.PLANS_COLLECTION, params.plan_id)
    if not doc:
        return ActionResult.error("That linking plan does not exist.", retryable=False, code="PLAN_NOT_FOUND")
    return ActionResult.success(LinkingPlan(id=doc.id, **doc.data), summary=f"Plan {params.plan_id} ({doc.data.get('status')}).")


@chat.function(
    "list_linking_plans",
    description="List linking plans, optionally filtered by site and/or status.",
    action_type="read",
    data_model=LinkingPlanList,
    event="internal-linking-engine.list_linking_plans",
)
async def list_linking_plans(ctx, params: ListLinkingPlansParams) -> ActionResult:
    """List linking plans, optionally filtered by site and/or status."""
    page = await ctx.store.query(storage.PLANS_COLLECTION, order_by="-created_at", limit=200)
    rows = [doc.data | {"id": doc.id} for doc in page.data]
    if params.site_id:
        rows = [r for r in rows if r.get("site_id") == params.site_id]
    if params.status:
        rows = [r for r in rows if r.get("status") == params.status]
    items = [LinkingPlan(**r) for r in rows]
    return ActionResult.success(LinkingPlanList(items=items), summary=f"{len(items)} plan(s).")


@chat.function(
    "apply_internal_links",
    description=(
        "Record that a pending_review plan's diffs were actually written to the site -- call this "
        "ONLY AFTER Webbee has already called wordpress-hub.replace_post_content_text for each "
        "surviving insertion in the plan (using expected_state_token per post for safety). This "
        "function does not write to any site itself; it only transitions the plan's own status and "
        "increments the site's confirmed_applies_count toward its full_auto threshold."
    ),
    action_type="write",
    data_model=LinkingPlan,
    effects=["ile.plan_applied"],
    event="internal-linking-engine.apply_internal_links",
)
async def apply_internal_links(ctx, params: ApplyInternalLinksParams) -> ActionResult:
    """Record that Webbee already wrote a pending plan's diffs to the real site."""
    doc = await ctx.store.get(storage.PLANS_COLLECTION, params.plan_id)
    if not doc:
        return ActionResult.error("That linking plan does not exist.", retryable=False, code="PLAN_NOT_FOUND")
    if doc.data.get("status") != "pending_review":
        return ActionResult.error(
            f"Plan is already '{doc.data.get('status')}', not pending_review.", retryable=False, code="PLAN_NOT_PENDING",
        )
    data = doc.data | {"status": "applied"}
    await ctx.store.update(storage.PLANS_COLLECTION, doc.id, data)

    run = await storage.find_run_by_plan(ctx, params.plan_id)
    if run:
        await ctx.store.update(storage.RUNS_COLLECTION, run.id, run.data | {"status": "applied"})

    settings_doc = await storage.find_settings(ctx, doc.data.get("site_id", ""))
    if settings_doc:
        count = int(settings_doc.data.get("confirmed_applies_count", 0)) + 1
        await ctx.store.update(storage.SETTINGS_COLLECTION, settings_doc.id, settings_doc.data | {
            "confirmed_applies_count": count, "updated_at": storage.now_iso(),
        })

    applied_n = len(params.applied_post_ids) or data.get("posts_touched_count", 0)
    return ActionResult.success(LinkingPlan(id=doc.id, **data), summary=f"Plan {params.plan_id} applied ({applied_n} post(s) written).")


@chat.function(
    "reject_linking_plan",
    description="Reject a pending_review plan without applying it. Nothing was ever written, so this is purely a status change.",
    action_type="write",
    data_model=LinkingPlan,
    effects=["ile.plan_rejected"],
    event="internal-linking-engine.reject_linking_plan",
)
async def reject_linking_plan(ctx, params: RejectLinkingPlanParams) -> ActionResult:
    """Reject a pending plan without applying it -- pure status change, nothing was written."""
    doc = await ctx.store.get(storage.PLANS_COLLECTION, params.plan_id)
    if not doc:
        return ActionResult.error("That linking plan does not exist.", retryable=False, code="PLAN_NOT_FOUND")
    data = doc.data | {"status": "rejected"}
    await ctx.store.update(storage.PLANS_COLLECTION, doc.id, data)
    run = await storage.find_run_by_plan(ctx, params.plan_id)
    if run:
        await ctx.store.update(storage.RUNS_COLLECTION, run.id, run.data | {"status": "rejected"})
    return ActionResult.success(LinkingPlan(id=doc.id, **data), summary=f"Plan {params.plan_id} rejected.")


@chat.function(
    "rollback_linking_run",
    description=(
        "Roll back an already-applied plan: returns the original find/replace pairs (the inserted "
        "anchor/CTA text as 'find', the pre-insertion original snippet as 'replace') for Webbee to "
        "write back via wordpress-hub.replace_post_content_text, restoring each post's content. This "
        "function does not write to any site itself -- it only returns the rollback instructions and "
        "transitions the plan's own status once Webbee confirms."
    ),
    action_type="write",
    data_model=LinkingPlan,
    effects=["ile.run_rolled_back"],
    event="internal-linking-engine.rollback_linking_run",
)
async def rollback_linking_run(ctx, params: RollbackLinkingRunParams) -> ActionResult:
    """Return original find/replace pairs to undo an applied plan; Webbee performs the actual write."""
    doc = await ctx.store.get(storage.PLANS_COLLECTION, params.plan_id)
    if not doc:
        return ActionResult.error("That linking plan does not exist.", retryable=False, code="PLAN_NOT_FOUND")
    if doc.data.get("status") != "applied":
        return ActionResult.error(
            f"Plan is '{doc.data.get('status')}', not applied -- nothing to roll back.", retryable=False, code="PLAN_NOT_APPLIED",
        )
    data = doc.data | {"status": "rolled_back"}
    await ctx.store.update(storage.PLANS_COLLECTION, doc.id, data)
    run = await storage.find_run_by_plan(ctx, params.plan_id)
    if run:
        await ctx.store.update(storage.RUNS_COLLECTION, run.id, run.data | {"status": "rolled_back"})
    return ActionResult.success(LinkingPlan(id=doc.id, **data), summary=f"Plan {params.plan_id} rolled back -- {len(data.get('entries', []))} post(s) to restore via wordpress-hub.")


@chat.function(
    "list_linking_runs",
    description="List the linking runs dashboard -- one row per plan lifecycle event, newest first.",
    action_type="read",
    data_model=LinkingRunList,
    event="internal-linking-engine.list_linking_runs",
)
async def list_linking_runs(ctx, params: ListLinkingRunsParams) -> ActionResult:
    """List the linking runs dashboard, one row per plan lifecycle event, newest first."""
    page = await ctx.store.query(storage.RUNS_COLLECTION, order_by="-created_at", limit=params.limit)
    rows = [doc.data | {"id": doc.id} for doc in page.data]
    if params.site_id:
        rows = [r for r in rows if r.get("site_id") == params.site_id]
    items = [LinkingRun(**r) for r in rows]
    return ActionResult.success(LinkingRunList(items=items), summary=f"{len(items)} run(s).")
