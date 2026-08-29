"""Panel UI for Internal Linking Engine.

ONE PANEL PER SLOT -- learned the hard way in other apps (see SEO Audit
Engine's panels.py docstring): the host takes all slots as one bundle at
session init and a slot only ever mounts ONE panel with replace semantics,
no stacking. Declaring two `slot="center"` panels means one silently loses
and its buttons look broken with no error. So there is exactly one center
panel (`ile`) here, and `view` is a plain kwarg that switches the screen
inside it -- exactly the same shape as SEO Audit Engine's `seo` panel.

    ui.Call("__panel__ile")                              -> site list (default)
    ui.Call("__panel__ile", view="enable_site")           -> enable-site form
    ui.Call("__panel__ile", view="site_settings", site_id=...) -> settings form
    ui.Call("__panel__ile", view="plan", plan_id=...)     -> plan preview/diff
    ui.Call("__panel__ile", view="runs")                  -> run dashboard
    ui.Call("__panel__ile", view="app_settings")           -> app-wide settings

See UI_COMPONENT_PLAN.md for the full mapping and UI_COMPONENT_VOCABULARY.md
for which ui.* primitives actually exist (no RadioGroup/Textarea -- those
were plan mistakes already fixed).
"""
from __future__ import annotations

from imperal_sdk import ui

from app import ext
import storage

_STATUS_BADGE = {True: ("green", "Enabled"), False: ("gray", "Disabled")}
_PLAN_STATUS_COLOR = {
    "pending_review": "yellow", "applied": "green",
    "rolled_back": "gray", "rejected": "gray",
}


@ext.panel("ile_nav", slot="left", title="Internal Linking Engine", icon="Link", refresh="manual")
async def ile_nav(ctx, **kwargs):
    """Sidebar: no instructions duplicated here (they live in the button's
    own Dialog per the no-duplication rule) -- just navigation."""
    return ui.Stack(direction="v", align="stretch", children=[
        ui.Text("Internal Linking Engine", variant="header"),
        ui.Divider(),
        ui.ListItem(label="Sites", icon="Link", on_click=ui.Call("__panel__ile")),
        ui.ListItem(label="Runs", icon="History", on_click=ui.Call("__panel__ile", view="runs")),
        ui.Divider(),
        ui.Button("App settings", variant="secondary", full_width=True,
                   on_click=ui.Call("__panel__ile", view="app_settings")),
    ])


@ext.panel("ile", slot="center", title="Internal Linking Engine", icon="Link",
           center_overlay=True, refresh="manual")
async def ile_center(ctx, **kwargs):
    """THE ONLY center panel. `view` picks the screen inside it."""
    view = str(kwargs.get("view") or "").strip().lower()
    if view == "enable_site":
        return await _enable_site_view(ctx, kwargs)
    if view == "site_settings":
        return await _site_settings_view(ctx, kwargs)
    if view == "plan":
        return await _plan_view(ctx, kwargs)
    if view == "runs":
        return await _runs_view(ctx, kwargs)
    if view == "app_settings":
        return await _app_settings_view(ctx, kwargs)
    return await _site_list_view(ctx, kwargs)


async def _site_list_view(ctx, kwargs) -> ui.UINode:
    settings_rows = await storage.list_settings(ctx)
    if not settings_rows:
        return ui.Empty(
            message="No sites enabled yet for Internal Linking Engine. Connect a site in WordPress Hub first, then enable it here.",
            icon="Link",
            action=ui.Button("+ Enable a site", on_click=ui.Call("__panel__ile", view="enable_site")),
        )

    rows = []
    for s in settings_rows:
        color, label = _STATUS_BADGE[bool(s.get("enabled"))]
        rows.append({
            "domain": s.get("domain", s.get("site_id", "")),
            "status": ui.Badge(label, color=color),
            "mode": s.get("mode", "review_first"),
            "last_scanned_at": s.get("last_scanned_at") or "—",
            "actions": ui.Row(children=[
                ui.Button("Settings", size="sm", variant="secondary",
                           on_click=ui.Call("__panel__ile", view="site_settings", site_id=s.get("site_id", ""))),
            ]),
        })

    return ui.Stack(direction="v", align="stretch", children=[
        ui.Row(children=[
            ui.Text("Sites", variant="header"),
            ui.Button("+ Enable a site", size="sm", on_click=ui.Call("__panel__ile", view="enable_site")),
        ]),
        ui.DataTable(columns=["domain", "status", "mode", "last_scanned_at", "actions"], rows=rows),
    ])


async def _enable_site_view(ctx, kwargs) -> ui.UINode:
    """Form container stretched full-width, every field with a label via
    Stack+caption Text, contextual placeholders -- per the standing UI rule.
    No how-it-works copy here: that lives only in this button's own Dialog
    (avoids duplicating instructions between sidebar and modal)."""
    return ui.Stack(direction="v", align="stretch", children=[
        ui.Text("Enable a site", variant="header"),
        ui.Form(
            action="enable_site",
            full_width=True,
            children=[
                ui.Stack(direction="v", gap=1, align="stretch", children=[
                    ui.Text("Site id", variant="caption"),
                    ui.Input(param_name="site_id", placeholder="Site id or domain from Sites Registry, e.g. climtec.md", full_width=True),
                ]),
                ui.Stack(direction="v", gap=1, align="stretch", children=[
                    ui.Text("Display name", variant="caption"),
                    ui.Input(param_name="domain", placeholder="Leave blank to use the site id as display name", full_width=True),
                ]),
                ui.Stack(direction="v", gap=1, align="stretch", children=[
                    ui.Text("Max internal links per article", variant="caption"),
                    ui.Input(param_name="max_links_per_post", placeholder="e.g. 3 (recommended range: 2-5)", full_width=True),
                ]),
                ui.Stack(direction="v", gap=1, align="stretch", children=[
                    ui.Text("Languages to isolate", variant="caption"),
                    ui.Input(param_name="languages", placeholder="e.g. ru, ro -- leave blank to auto-detect per article", full_width=True),
                ]),
                ui.Button("Enable Internal Linking Engine", full_width=True, variant="primary",
                           loading_label="Enabling…", on_click=ui.Call("__panel__ile")),
            ],
        ),
    ])


async def _site_settings_view(ctx, kwargs) -> ui.UINode:
    site_id = str(kwargs.get("site_id") or "")
    doc = await storage.find_settings(ctx, site_id)
    if not doc:
        return ui.Empty(message=f"No settings found for '{site_id}'.", icon="AlertCircle",
                          action=ui.Button("Back to sites", on_click=ui.Call("__panel__ile")))
    d = doc.data
    return ui.Stack(direction="v", align="stretch", children=[
        ui.Row(children=[
            ui.Text(f"Settings — {d.get('domain', site_id)}", variant="header"),
            ui.Button("Back", size="sm", variant="secondary", on_click=ui.Call("__panel__ile")),
        ]),
        ui.Stat(label="Confirmed applies toward Full-auto",
                 value=f"{d.get('confirmed_applies_count', 0)}/{d.get('full_auto_threshold', 5)}"),
        ui.Form(
            action="update_site_settings",
            full_width=True,
            children=[
                ui.Input(param_name="site_id", value=site_id, hidden=True),
                ui.Stack(direction="v", gap=1, align="stretch", children=[
                    ui.Text("Working mode", variant="caption"),
                    ui.Select(param_name="mode", value=d.get("mode", "review_first"), full_width=True, options=[
                        {"value": "review_first", "label": "Review-first (preview before applying)"},
                        {"value": "full_auto", "label": "Full-auto (apply automatically)"},
                    ]),
                ]),
                ui.Stack(direction="v", gap=1, align="stretch", children=[
                    ui.Text("Max internal links per article", variant="caption"),
                    ui.Input(param_name="max_links_per_post", value=str(d.get("max_links_per_post", 3)),
                               placeholder="e.g. 3", full_width=True),
                ]),
                ui.Stack(direction="v", gap=1, align="stretch", children=[
                    ui.Text("Excluded URLs (this engine will never touch these)", variant="caption"),
                    ui.Input(param_name="excluded_urls", placeholder="e.g. https://example.com/contacts", full_width=True),
                ]),
                ui.Button("Save settings", full_width=True, variant="primary",
                           loading_label="Saving…", on_click=ui.Call("__panel__ile", view="site_settings", site_id=site_id)),
            ],
        ),
    ])


async def _plan_view(ctx, kwargs) -> ui.UINode:
    plan_id = str(kwargs.get("plan_id") or "")
    doc = await ctx.store.get(storage.PLANS_COLLECTION, plan_id)
    if not doc:
        return ui.Empty(message="That linking plan was not found.", icon="AlertCircle",
                          action=ui.Button("Back to sites", on_click=ui.Call("__panel__ile")))
    d = doc.data
    rows = []
    for entry in d.get("entries", []):
        for link in entry.get("link_suggestions", []):
            rows.append({
                "article": entry.get("title", ""),
                "found_text": link.get("find_exact_substring", "")[:60],
                "proposed_anchor": f"→ {link.get('target_title', '')}",
                "kind": "link",
            })
        cta = entry.get("cta_suggestion")
        if cta:
            rows.append({
                "article": entry.get("title", ""),
                "found_text": cta.get("find_exact_substring", "")[:60],
                "proposed_anchor": f"CTA → {cta.get('cta_label', '')}",
                "kind": "cta",
            })
    color = _PLAN_STATUS_COLOR.get(d.get("status", ""), "gray")
    return ui.Stack(direction="v", align="stretch", children=[
        ui.Row(children=[
            ui.Text(f"Plan {plan_id}", variant="header"),
            ui.Badge(d.get("status", ""), color=color),
        ]),
        ui.Stat(label="Posts touched", value=str(d.get("posts_touched_count", 0))),
        ui.DataTable(columns=["article", "found_text", "proposed_anchor", "kind"], rows=rows) if rows else
        ui.Empty(message="This plan has no surviving insertions to show."),
        ui.Row(children=[
            ui.Button("Reject plan", variant="secondary",
                       on_click=ui.Call("__panel__ile")) if d.get("status") == "pending_review" else ui.Text(""),
        ]),
    ])


async def _runs_view(ctx, kwargs) -> ui.UINode:
    runs = await storage.list_runs(ctx)
    if not runs:
        return ui.Empty(message="No linking runs yet. Enable a site and preview a plan to get started.", icon="History")
    rows = []
    for r in runs:
        color = _PLAN_STATUS_COLOR.get(r.get("status", ""), "gray")
        rows.append({
            "site": r.get("domain", r.get("site_id", "")),
            "created_at": r.get("created_at", ""),
            "links_added": r.get("links_added_count", 0),
            "cta_added": r.get("cta_added_count", 0),
            "status": ui.Badge(r.get("status", ""), color=color),
            "actions": ui.Button("View plan", size="sm", on_click=ui.Call("__panel__ile", view="plan", plan_id=r.get("plan_id", ""))),
        })
    return ui.Stack(direction="v", align="stretch", children=[
        ui.Text("Runs", variant="header"),
        ui.DataTable(columns=["site", "created_at", "links_added", "cta_added", "status", "actions"], rows=rows),
    ])


async def _app_settings_view(ctx, kwargs) -> ui.UINode:
    return ui.Stack(direction="v", align="stretch", children=[
        ui.Text("App settings", variant="header"),
        ui.Text("Internal Linking Engine has no global secrets to configure -- every setting is per-site (see Sites)."),
        ui.Button("Back to sites", on_click=ui.Call("__panel__ile")),
    ])
