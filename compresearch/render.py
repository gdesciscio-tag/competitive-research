# compresearch/render.py
from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from xml.sax.saxutils import escape

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

from compresearch.branding import load_branding
from compresearch.job_store import load_data, save_data, slugify
from compresearch.models import Branding, JobData, RenderResult
from compresearch.utils import short_domain

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _bar_chart_svg(
    labels: list[str],
    values: list[int],
    width: int = 600,
    height: int = 300,
    bar_color: str = "#6C757D",
    text_color: str = "#1F2933",
) -> str:
    """Render a simple vertical bar chart as a standalone, deterministic SVG string.

    Labels are angled (-30 degrees) below the bars so long domain names don't overlap.
    """
    if not values:
        return ""
    max_val = max(values) or 1
    count = len(values)
    pad_x, pad_top, pad_bottom = 44, 28, 96
    chart_h = height - pad_top - pad_bottom
    chart_w = width - 2 * pad_x
    gap = 18
    bar_w = (chart_w - gap * (count - 1)) / count if count else 0
    baseline = pad_top + chart_h
    # bar_color/text_color come from the trusted branding config (not user/LLM input),
    # so they are interpolated into SVG attributes without escaping; labels ARE escaped.
    parts: list[str] = []
    for index, (label, value) in enumerate(zip(labels, values)):
        bar_h = (value / max_val) * chart_h
        x = pad_x + index * (bar_w + gap)
        cx = x + bar_w / 2
        y = pad_top + (chart_h - bar_h)
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
            f'fill="{bar_color}" rx="3"/>'
        )
        parts.append(
            f'<text x="{cx:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
            f'font-size="12" fill="{text_color}">{value}</text>'
        )
        label_y = baseline + 14
        parts.append(
            f'<text x="{cx:.1f}" y="{label_y:.1f}" text-anchor="end" font-size="11" '
            f'fill="{text_color}" transform="rotate(-30 {cx:.1f} {label_y:.1f})">'
            f'{escape(label)}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'width="100%" role="img">{"".join(parts)}</svg>'
    )


def _logo_html(branding: Branding) -> str | None:
    """Inline the configured logo as a base64 data URI.

    The PDF renderer sets the page HTML directly, which makes the browser block
    `file://` subresource loads — so an external logo silently fails to appear. Embedding
    the bytes inline avoids that entirely. Returns None when no logo file is configured.
    """
    if not branding.logo_path:
        return None
    path = Path(branding.logo_path)
    if not path.exists():
        return None
    mime, _ = mimetypes.guess_type(path.name)
    if mime is None:
        mime = "image/svg+xml" if path.suffix.lower() == ".svg" else "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return (
        f'<img class="logo-img" src="data:{mime};base64,{encoded}" '
        f'alt="{escape(branding.agency_name)}" style="max-height:64px;">'
    )


def build_report_context(data: JobData, branding: Branding, report_date: str | None = None) -> dict:
    """Turn a finished JobData + branding into a template view-model. Pure; tolerates
    any missing analysis section."""
    config = data.config

    # --- sitemap ---
    sitemap_domains: list[dict] = []
    client_total = 0
    sitemap_gaps: list[dict] = []
    if data.sitemap is not None:
        if data.sitemap.client is not None:
            client_total = data.sitemap.client.total_urls
            sitemap_domains.append({
                "domain": short_domain(data.sitemap.client.domain),
                "total": data.sitemap.client.total_urls,
                "posts_per_month": data.sitemap.client.posts_per_month,
            })
        for comp in data.sitemap.competitors:
            sitemap_domains.append({
                "domain": short_domain(comp.domain),
                "total": comp.total_urls,
                "posts_per_month": comp.posts_per_month,
            })
        sitemap_gaps = [
            {"section": g.section, "competitors": [short_domain(d) for d in g.competitors_with]}
            for g in data.sitemap.gaps
        ]
    # Show the most widely-shared gaps in the PDF; the Sheet has the full list.
    GAP_DISPLAY_LIMIT = 12
    sitemap_gap_total = len(sitemap_gaps)
    sitemap_gap_overflow = max(0, sitemap_gap_total - GAP_DISPLAY_LIMIT)
    sitemap_gaps_display = sitemap_gaps[:GAP_DISPLAY_LIMIT]

    # --- keywords ---
    keyword_gaps: list[dict] = []
    quick_wins: list[dict] = []
    keyword_domains: list[dict] = []
    if data.keywords is not None:
        keyword_gaps = [
            {"keyword": g.keyword, "volume": g.search_volume, "difficulty": g.difficulty,
             "traffic_value": g.traffic_value, "best_position": g.best_competitor_position,
             "competitors": [short_domain(d) for d in g.competitors_ranking]}
            for g in data.keywords.gaps[:15]
        ]
        quick_wins = [
            {"keyword": w.keyword, "position": w.position, "volume": w.search_volume,
             "traffic_value": w.traffic_value, "url": w.url}
            for w in data.keywords.quick_wins[:10]
        ]
        if data.keywords.client is not None:
            keyword_domains.append({"domain": short_domain(data.keywords.client.domain),
                                    "total": data.keywords.client.total_keywords})
        for comp in data.keywords.competitors:
            keyword_domains.append({"domain": short_domain(comp.domain),
                                    "total": comp.total_keywords})

    # --- topical map ---
    pillars = []
    topical_summary = None
    if data.topical_map is not None and data.topical_map.map is not None:
        pillars = data.topical_map.map.pillars
        topical_summary = data.topical_map.map.summary

    # --- draft ---
    draft = None
    if data.draft_post is not None and data.draft_post.post is not None:
        post = data.draft_post.post
        draft = {
            "title": post.title,
            "title_tag": post.title_tag,
            "meta_description": post.meta_description,
            # body_html is trusted LLM output, rendered with |safe in the template without
            # sanitization. Trust boundary: LLM -> agency -> static client PDF. If this HTML
            # is ever served to a browser or sourced from untrusted models, sanitize first.
            "body_html": markdown.markdown(post.body_markdown, extensions=["extra", "sane_lists"]),
            "internal_links": [{"anchor": l.anchor, "url": l.url} for l in post.internal_links],
        }

    # --- charts ---
    content_volume_svg = _bar_chart_svg(
        [d["domain"] for d in sitemap_domains], [d["total"] for d in sitemap_domains],
        bar_color=branding.accent_color, text_color=branding.text_color,
    )
    keyword_counts_svg = _bar_chart_svg(
        [d["domain"] for d in keyword_domains], [d["total"] for d in keyword_domains],
        bar_color=branding.primary_color, text_color=branding.text_color,
    )

    is_partial = bool(
        (data.sitemap and data.sitemap.is_partial)
        or (data.keywords and data.keywords.is_partial)
    )

    return {
        "branding": branding,
        "logo_html": _logo_html(branding),
        "client_name": config.client_name,
        "client_url": config.client_url,
        "report_date": report_date or "",
        "summary": {
            "competitor_count": len(config.competitor_urls),
            "content_gap_count": sitemap_gap_total,
            "keyword_gap_count": len(keyword_gaps),
            "quick_win_count": len(quick_wins),
            "is_partial": is_partial,
        },
        "sitemap": {
            "client_total": client_total,
            "domains": sitemap_domains,
            "gaps": sitemap_gaps_display,
            "gap_overflow": sitemap_gap_overflow,
        },
        "keywords": {"gaps": keyword_gaps, "quick_wins": quick_wins},
        "topical_map": {"pillars": pillars, "summary": topical_summary},
        "draft": draft,
        "charts": {"content_volume_svg": content_volume_svg, "keyword_counts_svg": keyword_counts_svg},
    }


def render_report_html(context: dict, templates_dir: Path = TEMPLATES_DIR) -> str:
    """Render the branded report HTML from the context view-model."""
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    return env.get_template("report.html.j2").render(**context)


def render_pdf(html: str, output_path: Path) -> None:
    """Render HTML to a PDF file via headless Chromium. Playwright is imported lazily so
    the module (and the test suite) does not require it to be installed."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(
                path=str(output_path),
                format="A4",
                print_background=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )
        finally:
            browser.close()


def run_render(job_dir, html_to_pdf=render_pdf, branding=None, report_date: str | None = None) -> JobData:
    """Render a job's branded PDF report and record the output path in data.json."""
    data = load_data(job_dir)
    branding = branding or load_branding()
    slug = slugify(data.config.client_name)
    output_path = Path(job_dir) / "outputs" / f"{slug}-competitive-research.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        context = build_report_context(data, branding, report_date=report_date)
        html = render_report_html(context)
        html_to_pdf(html, output_path)
        data.render = RenderResult(pdf_path=str(output_path))
    except Exception as exc:
        logging.warning("PDF render failed for %s: %s", data.config.client_url, exc)
        data.render = RenderResult(error=str(exc))
    save_data(job_dir, data)
    return data
