"""Store access helpers for Internal Linking Engine's 4 collections.

Kept thin and boring, same shape as Sites Registry's storage.py: no business
logic here, just find/save primitives.
"""
from __future__ import annotations

import time
import uuid

SETTINGS_COLLECTION = "ile_site_settings"
INDEX_COLLECTION = "ile_content_index"
PLANS_COLLECTION = "ile_linking_plans"
RUNS_COLLECTION = "ile_linking_runs"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_id() -> str:
    return uuid.uuid4().hex[:16]


# ---------------------------------------------------------------------------
# Site settings
# ---------------------------------------------------------------------------

async def find_settings(ctx, site_id: str):
    page = await ctx.store.query(SETTINGS_COLLECTION, limit=200)
    for doc in page.data:
        if doc.data.get("site_id") == site_id:
            return doc
    return None


async def list_settings(ctx, *, limit: int = 100):
    page = await ctx.store.query(SETTINGS_COLLECTION, order_by="-updated_at", limit=limit)
    return [doc.data | {"id": doc.id} for doc in page.data]


# ---------------------------------------------------------------------------
# Content index (one row per indexed post)
# ---------------------------------------------------------------------------

async def list_indexed_posts(ctx, site_id: str, *, lang: str = "", limit: int = 500):
    page = await ctx.store.query(INDEX_COLLECTION, limit=limit)
    rows = [doc.data | {"id": doc.id} for doc in page.data if doc.data.get("site_id") == site_id]
    if lang:
        rows = [r for r in rows if r.get("lang") == lang]
    return rows


async def find_indexed_post(ctx, site_id: str, post_id: str):
    page = await ctx.store.query(INDEX_COLLECTION, limit=500)
    for doc in page.data:
        if doc.data.get("site_id") == site_id and doc.data.get("post_id") == post_id:
            return doc
    return None


# ---------------------------------------------------------------------------
# Linking plans
# ---------------------------------------------------------------------------

async def find_plan(ctx, plan_id: str):
    return await ctx.store.get(PLANS_COLLECTION, plan_id)


async def list_plans(ctx, *, site_id: str = "", status: str = "", limit: int = 100):
    page = await ctx.store.query(PLANS_COLLECTION, order_by="-created_at", limit=limit)
    rows = [doc.data | {"id": doc.id} for doc in page.data]
    if site_id:
        rows = [r for r in rows if r.get("site_id") == site_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return rows


# ---------------------------------------------------------------------------
# Runs dashboard
# ---------------------------------------------------------------------------

async def list_runs(ctx, *, site_id: str = "", limit: int = 50):
    page = await ctx.store.query(RUNS_COLLECTION, order_by="-created_at", limit=limit)
    rows = [doc.data | {"id": doc.id} for doc in page.data]
    if site_id:
        rows = [r for r in rows if r.get("site_id") == site_id]
    return rows


async def find_run_by_plan(ctx, plan_id: str):
    page = await ctx.store.query(RUNS_COLLECTION, limit=500)
    for doc in page.data:
        if doc.data.get("plan_id") == plan_id:
            return doc
    return None
