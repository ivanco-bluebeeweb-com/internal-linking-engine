"""Extension declaration for Internal Linking Engine.

WHY THIS APP EXISTS: organic internal-linking + one CTA-block insertion is
currently done manually, inside a chat session (pilot: climtec.md). This app
turns it into a platform-native, always-available service: for every
connected site it builds a lightweight content index, proposes 2-5 relevant
internal-link targets per article (language-isolated), drafts anchor
placements + one CTA block via an LLM pass, and produces a strict
preview -> explicit apply -> rollback diff -- never a silent rewrite.

WHY THIS APP DOES NOT CALL wordpress-hub/content-strategy-app ITSELF.
Content Strategy Hub's own main.py states the same boundary explicitly:
"discover_opportunities does not call other extensions itself -- Webbee
fetches query data ... first, then passes it into this tool". Internal
Linking Engine follows the identical contract: it never reads or writes a
site's real content directly. Webbee fetches posts/links from wordpress-hub
first and passes them in as structured data; this app only ever returns
the exact find/replace instructions Webbee should hand to
wordpress-hub.replace_post_content_text -- the actual write always happens
in that other, already-hardened tool, never re-implemented here.

WHY NO EMBEDDINGS. Every app in this portfolio (`Content Strategy Hub`,
`SEO Audit Engine`, `WordPress Hub`) ships with `imperal-sdk` only in
requirements.txt -- no numpy/sklearn/sentence-transformers anywhere. Adding
a real vector-embedding stack here would be the first heavy ML dependency
in the whole codebase for one app. The Relevance Engine instead scores
candidates on metadata (categories/tags/product_type/language as hard
filters) plus deterministic term-overlap on title/excerpt -- explainable,
zero new infrastructure, and already the same spirit as Content Strategy
Hub's own check_keyword_cannibalization. See PREPARATION.md §5 for the
full rationale and the explicit roadmap item to add real embeddings later
if metadata-only scoring proves insufficient on real sites.
"""
from __future__ import annotations

from imperal_sdk import Extension, ChatExtension

ext = Extension(
    "internal-linking-engine",
    version="0.1.0",
    display_name="Internal Linking Engine",
    description=(
        "Automatic organic internal linking + one conversion CTA block per "
        "article, for every connected site. Builds a lightweight content "
        "index, proposes language-isolated relevant link targets, drafts "
        "anchor placements and a CTA with a strict preview -> apply -> "
        "rollback diff -- never a silent content rewrite."
    ),
    icon="icon.svg",
    actions_explicit=True,
    capabilities=["internal_linking:read", "internal_linking:write"],
)

chat = ChatExtension(
    ext,
    tool_name="internal-linking-engine",
    description=(
        "Plans and tracks organic internal linking + CTA insertion for your "
        "sites' articles. Produces exact find/replace instructions for "
        "wordpress-hub to execute -- never writes content itself."
    ),
)


@ext.health_check
async def health_check(ctx) -> bool:
    """Basic liveness check -- confirms the store surface is reachable."""
    await ctx.store.query("ile_site_settings", limit=1)
    return True
