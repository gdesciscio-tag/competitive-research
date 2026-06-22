# compresearch/draft_export.py
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape

from compresearch.branding import load_branding
from compresearch.job_store import load_data, save_data, slugify
from compresearch.models import Branding, DraftExportResult, DraftPost, JobData
from compresearch.render import markdown_to_html
from compresearch.settings import get_secret


def build_draft_html(post: DraftPost, branding: Branding) -> str:
    """Render a DraftPost into a complete, standalone, lightly-branded HTML document.

    Browser-viewable and clean enough to paste into a CMS or convert to a Google Doc.
    Pure and deterministic. Title and SEO metadata are LLM output and are escaped; the
    body HTML is the already-rendered Markdown (trusted; see render.markdown_to_html).
    """
    meta_rows = []
    for label, value in (
        ("Target keyword", post.target_keyword),
        ("Title tag", post.title_tag),
        ("Meta description", post.meta_description),
    ):
        if value:
            meta_rows.append(
                f"<tr><th align='left'>{escape(label)}</th><td>{escape(value)}</td></tr>"
            )
    meta_table = f"<table>{''.join(meta_rows)}</table>" if meta_rows else ""

    def _link_item(link) -> str:
        # The url field is LLM-sourced; only emit a real href for http(s) schemes so a
        # javascript:/data: URL cannot become a live link in the browser-viewable output.
        if link.url.lower().startswith(("http://", "https://")):
            return f"<li><a href=\"{escape(link.url)}\">{escape(link.anchor)}</a></li>"
        return f"<li>{escape(link.anchor)}</li>"

    links_html = ""
    if post.internal_links:
        items = "".join(_link_item(link) for link in post.internal_links)
        links_html = f"<h2>Internal links</h2><ul>{items}</ul>"

    body_html = markdown_to_html(post.body_markdown)

    # branding.* come from the trusted branding config (not user/LLM input).
    return (
        "<!DOCTYPE html>"
        "<html><head><meta charset=\"utf-8\">"
        f"<title>{escape(post.title)}</title>"
        f"<style>body{{font-family:{branding.font_family};color:{branding.text_color};}}"
        f"h1,h2{{color:{branding.primary_color};}}"
        "table{border-collapse:collapse;margin:0 0 1em;}"
        "th,td{padding:2px 8px;}</style></head><body>"
        f"<h1>{escape(post.title)}</h1>"
        f"{meta_table}"
        f"{body_html}"
        f"{links_html}"
        "</body></html>"
    )
