"""Chat functions + scheduler tick -- plan §7 (Scheduler).

The ONLY place this app acts without a human present, so it lives apart from
the read/write tooling on purpose (same separation principle as SEO Audit
Engine's handlers_schedule.py).

WHAT A TICK CAN AND CANNOT DO. ILE never fetches a site's content itself --
Webbee reads posts via wordpress-hub and hands the data in (app.py
docstring). A cron therefore cannot crawl or write links autonomously. What
it CAN do is the honest, useful thing: at the configured hour, for every
enabled site whose scan is due, deliver Webbee one chat message naming the
exact pipeline to run next (index_posts -> preview_internal_links -> review,
or apply when the site is already full_auto), then stamp the day so a failed
scan never re-fires on every tick.

The schedule itself is user-controlled: get_linking_schedule /
set_linking_schedule let the user turn it on, pick the UTC hour and the
weekdays per site -- without a redeploy (the cron line is frozen at app
registration; the chosen time lives in the store, see scan_schedule.py).
"""
from __future__ import annotations

from imperal_sdk import ActionResult

from app import chat, ext
from schemas import (
    GetLinkingScheduleParams, SetLinkingScheduleParams, LinkingSchedule,
)
import scan_schedule as sched
import storage


def _entity(site_id: str, d: dict) -> LinkingSchedule:
    return LinkingSchedule(
        id=f"linking-schedule-{site_id}",
        title=sched.describe(d),
        kind="ile_scan_schedule",
        site_id=site_id,
        enabled=bool(d.get("enabled")),
        hour=int(d.get("hour", sched.DEFAULT_HOUR)),
        days=str(d.get("days", "")),
        last_date=str(d.get("last_date", "")),
    )


@chat.function(
    "get_linking_schedule",
    description=(
        "Show the autonomous linking-scan schedule for one site: enabled or not, "
        "which UTC hour it fires at, which weekdays it runs on, and when it last fired. "
        "Use for: when does the linking engine scan my site?"
    ),
    action_type="read",
    data_model=LinkingSchedule,
    event="internal-linking-engine.get_linking_schedule",
)
async def get_linking_schedule(ctx, params: GetLinkingScheduleParams) -> ActionResult:
    """Read one site's autonomous linking-scan schedule from the store."""
    d = await sched.get_settings(ctx, params.site_id)
    hint = ""
    if not d.get("enabled"):
        hint = " Say 'scan climtec.md every night at 4am' to turn it on."
    return ActionResult.success(_entity(params.site_id, d), summary=sched.describe(d) + hint)


@chat.function(
    "set_linking_schedule",
    description=(
        "Turn a site's autonomous linking scan on/off and set its UTC hour and weekdays "
        "(days: '1-5'-style list like '1,3,5', empty = every day). Partial update -- "
        "fields not passed stay untouched. Use for: schedule the linking scan, "
        "run linking checks every night."
    ),
    action_type="write",
    data_model=LinkingSchedule,
    event="internal-linking-engine.set_linking_schedule",
    effects=["ile.schedule_updated"],
)
async def set_linking_schedule(ctx, params: SetLinkingScheduleParams) -> ActionResult:
    """Partial-update the schedule: fields not passed stay untouched."""
    if params.enabled is None and params.hour is None and params.days is None:
        return ActionResult.error(
            "Say what to change: enable/disable, the hour, or the days.",
            retryable=False, code="BAD_INPUT",
        )
    settings_doc = await storage.find_settings(ctx, params.site_id)
    if not settings_doc:
        return ActionResult.error(
            "Internal Linking Engine is not enabled for this site -- call enable_site first.",
            retryable=False, code="SITE_NOT_ENABLED",
        )
    d = await sched.set_settings(
        ctx, params.site_id,
        enabled=params.enabled, hour=params.hour, days=params.days,
    )
    return ActionResult.success(_entity(params.site_id, d), summary=sched.describe(d))


@ext.schedule("ile_scan_tick", sched.TICK_CRON)
async def ile_scan_tick(ctx) -> None:
    """Hourly alarm: asks scan_schedule.due() for every enabled site, and for
    each due site delivers Webbee the exact pipeline to run. A skipped tick
    costs one settings read per site and nothing else -- cheap by design."""
    sites = await storage.list_settings(ctx)
    for s in sites:
        site_id = s.get("site_id", "")
        if not site_id or not s.get("enabled"):
            continue
        ok, reason = await sched.due(ctx, site_id)
        if not ok:
            continue
        # Stamp BEFORE delivering: a lost message must not re-fire the scan on
        # the next tick (SEO Audit Engine's mark_ran lesson).
        await sched.mark_ran(ctx, site_id)
        mode = s.get("mode", "review_first")
        if mode == "full_auto":
            pipeline = ("run its nightly scan now: re-index changed posts "
                        "(index_posts), build a preview (preview_internal_links), "
                        "then apply the surviving diffs and confirm via apply_internal_links.")
        else:
            pipeline = ("run its scheduled scan now: re-index changed posts "
                        "(index_posts) and build a preview plan (preview_internal_links) "
                        "for the user to review.")
        try:
            await ctx.deliver_chat_message(
                f"Scheduled linking scan for **{s.get('domain', site_id)}** "
                f"(site_id `{site_id}`, mode `{mode}`): {pipeline}",
                msg_type="system",
            )
        except Exception as exc:
            await ctx.log(f"scheduled scan message for {site_id} not delivered: {exc}", "error")
