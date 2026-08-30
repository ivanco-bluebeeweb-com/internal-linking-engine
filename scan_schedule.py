"""Per-site scan-schedule settings -- plan §7 (Scheduler).

WHY TICK + STORED TIME, NOT A CRON STRING PER SITE: the platform reads
@ext.schedule(cron=...) at app REGISTRATION time, so the cron line is frozen
at deploy. Putting the chosen hour/days in the store lets the user move the
scan to any night without a redeploy -- same lesson SEO Audit Engine's
schedule_settings.py documents in detail (this module mirrors its shape on
purpose: one settings row per site, due() asks "is it time yet", mark_ran()
is stamped BEFORE the work so a failed scan never re-fires every tick).

WHAT THE TICK ACTUALLY DOES. ILE's architecture rule (app.py docstring) is
that this app never fetches a site's content itself -- Webbee does that via
wordpress-hub and hands the data in. So the scheduler cannot crawl; instead,
when a site's scan is due it delivers a chat message to Webbee with the
exact pipeline to run (index -> preview -> review/apply), then marks the
day as done. A missed platform wake-up fires once (catching_up), never in a
retry storm.
"""
from __future__ import annotations

import time
from typing import Any

SCHEDULE_COLLECTION = "ile_scan_schedules"

#: Hourly alarm -- accuracy to the hour is all a nightly content scan needs.
TICK_CRON = "7 * * * *"

DEFAULT_HOUR = 4        # night: nobody is editing articles at 4am
DEFAULT_DAYS = ""       # empty = every day

DEFAULTS: dict[str, Any] = {
    "enabled": False,   # off by default: autonomous runs are opt-in per site
    "hour": DEFAULT_HOUR,
    "days": DEFAULT_DAYS,
    "last_date": "",    # UTC date of the last fired scan (dedup guard)
    "updated_at": "",
}


def _now_parts(ts: float | None = None) -> tuple[str, int, int]:
    """(date YYYY-MM-DD, hour 0-23, weekday 0-6) in UTC -- the platform has
    no user timezone, and silently picking one would mean '4am' lands at noon
    for half the portfolio."""
    t = time.gmtime(ts if ts is not None else time.time())
    return (time.strftime("%Y-%m-%d", t), t.tm_hour, t.tm_wday)


def parse_days(raw: str) -> list[int]:
    """'1,4' -> [0, 3]; empty/'*'/'daily' -> every day. Humans count Monday=1,
    Python counts Monday=0 -- the off-by-one here is a scan on the wrong day,
    noticed a week later."""
    raw = (raw or "").strip().lower()
    if not raw or raw in ("*", "all", "every", "daily", "все", "ежедневно"):
        return list(range(7))
    out: list[int] = []
    for part in raw.replace(" ", "").split(","):
        if part.isdigit() and 1 <= int(part) <= 7:
            out.append(int(part) - 1)
    return sorted(set(out)) or list(range(7))


async def _find(ctx, site_id: str):
    try:
        page = await ctx.store.query(SCHEDULE_COLLECTION, where={"key": site_id}, limit=1)
    except Exception:
        return None
    return page.data[0] if page.data else None


async def get_settings(ctx, site_id: str) -> dict[str, Any]:
    doc = await _find(ctx, site_id)
    d = dict(DEFAULTS)
    if doc is not None:
        raw = getattr(doc, "data", None) or {}
        if isinstance(raw, dict):
            d.update({k: v for k, v in raw.items() if k in DEFAULTS})
    d["site_id"] = site_id
    d["days_list"] = parse_days(str(d.get("days", "")))
    return d


async def set_settings(ctx, site_id: str, *, enabled: bool | None = None,
                       hour: int | None = None, days: str | None = None) -> dict[str, Any]:
    """Partial update: 'move to 5am' must not silently wipe the day list."""
    d = await get_settings(ctx, site_id)
    if enabled is not None:
        d["enabled"] = bool(enabled)
    if hour is not None:
        d["hour"] = max(0, min(23, int(hour)))
    if days is not None:
        d["days"] = (days or "").strip()
    payload = {k: d.get(k, DEFAULTS[k]) for k in DEFAULTS}
    payload["key"] = site_id
    payload["title"] = f"Scan schedule for {site_id}"
    payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    existing = await _find(ctx, site_id)
    if existing is not None:
        await ctx.store.update(SCHEDULE_COLLECTION, existing.id, payload)
    else:
        await ctx.store.create(SCHEDULE_COLLECTION, payload)
    d["updated_at"] = payload["updated_at"]
    return d


async def due(ctx, site_id: str, *, ts: float | None = None) -> tuple[bool, str]:
    """Is this site's scan due right now? Always returns the reason too --
    without it 'why didn't it fire last night' is unanswerable without
    reading code."""
    d = await get_settings(ctx, site_id)
    if not d.get("enabled"):
        return False, "disabled"
    today, hour, wday = _now_parts(ts)
    if wday not in parse_days(str(d.get("days", ""))):
        return False, "other_day"
    want = int(d.get("hour", DEFAULT_HOUR))
    if hour < want:
        return False, "too_early"
    # Dedup by DATE, not by elapsed time: a scan that ran long must not push
    # tomorrow's run an hour later every day until it drifts into daytime.
    if str(d.get("last_date") or "") == today:
        return False, "already_today"
    return True, ("on_time" if hour == want else "catching_up")


async def mark_ran(ctx, site_id: str, *, ts: float | None = None) -> None:
    """Stamp today's date BEFORE the work starts: a failed scan must not
    re-fire on every tick -- a network hiccup would otherwise become the
    most frequent scan in the app's history."""
    d = await get_settings(ctx, site_id)
    today, _h, _w = _now_parts(ts)
    await set_settings(ctx, site_id)  # ensures the row exists
    payload = {k: d.get(k, DEFAULTS[k]) for k in DEFAULTS}
    payload["last_date"] = today
    payload["key"] = site_id
    payload["title"] = f"Scan schedule for {site_id}"
    existing = await _find(ctx, site_id)
    if existing is not None:
        await ctx.store.update(SCHEDULE_COLLECTION, existing.id, payload)


def describe(d: dict[str, Any]) -> str:
    if not d.get("enabled"):
        return f"Scheduled linking scans are OFF for {d.get('site_id', 'this site')}."
    days = d.get("days") or "every day"
    return (f"Scheduled linking scans for {d.get('site_id', '')}: "
            f"days {days}, at {int(d.get('hour', DEFAULT_HOUR)):02d}:00 UTC.")
