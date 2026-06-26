# compresearch/dashboard.py
from __future__ import annotations

from compresearch.models import Branding, JobData
from compresearch.render import _bar_chart_svg, _logo_html, markdown_to_html
from compresearch.utils import short_domain


def build_dashboard_context(data: JobData, branding: Branding, report_date: str | None = None) -> dict:
    """Turn a finished JobData + branding into the dashboard view-model. Pure; tolerates any
    missing analysis section. Mirrors render.build_report_context but keeps the FULL dataset
    (uncapped lists, per-domain keyword tables, every draft) and typed values for client-side
    sorting."""
    config = data.config

    sitemap_domains: list[dict] = []
    sitemap_gaps: list[dict] = []
    if data.sitemap is not None:
        if data.sitemap.client is not None:
            sitemap_domains.append({"domain": short_domain(data.sitemap.client.domain),
                                    "total": data.sitemap.client.total_urls,
                                    "posts_per_month": data.sitemap.client.posts_per_month})
        for comp in data.sitemap.competitors:
            sitemap_domains.append({"domain": short_domain(comp.domain),
                                    "total": comp.total_urls,
                                    "posts_per_month": comp.posts_per_month})
        sitemap_gaps = [{"section": g.section,
                         "competitors": [short_domain(d) for d in g.competitors_with]}
                        for g in data.sitemap.gaps]

    keyword_gaps: list[dict] = []
    quick_wins: list[dict] = []
    domain_keywords: list[dict] = []
    provided: list[dict] = []
    if data.keywords is not None:
        keyword_gaps = [{"keyword": g.keyword, "volume": g.search_volume, "difficulty": g.difficulty,
                         "traffic_value": g.traffic_value, "best_position": g.best_competitor_position,
                         "competitors": [short_domain(d) for d in g.competitors_ranking]}
                        for g in data.keywords.gaps]
        quick_wins = [{"keyword": w.keyword, "position": w.position, "volume": w.search_volume,
                       "traffic_value": w.traffic_value, "url": w.url}
                      for w in data.keywords.quick_wins]
        domains = ([data.keywords.client] if data.keywords.client else []) + list(data.keywords.competitors)
        for dk in domains:
            domain_keywords.append({"domain": short_domain(dk.domain),
                                    "keywords": [{"keyword": e.keyword, "volume": e.search_volume,
                                                  "difficulty": e.difficulty, "position": e.position,
                                                  "url": e.url} for e in dk.keywords]})
        provided = [{"keyword": p.keyword, "volume": p.search_volume, "difficulty": p.difficulty,
                     "client_position": p.client_position, "best_position": p.best_competitor_position,
                     "competitors": [short_domain(d) for d in p.competitors_ranking]}
                    for p in data.keywords.provided]

    pillars = []
    topical_summary = None
    if data.topical_map is not None and data.topical_map.map is not None:
        pillars = data.topical_map.map.pillars
        topical_summary = data.topical_map.map.summary

    # body_html is trusted LLM output rendered with |safe in the template (same boundary as
    # the PDF). The dashboard is a static file handed to the client, not served to untrusted
    # visitors; if that ever changes, sanitize before rendering.
    drafts = [{"title": d.post.title, "target_keyword": d.post.target_keyword,
               "title_tag": d.post.title_tag, "meta_description": d.post.meta_description,
               "word_count": d.post.word_count, "body_html": markdown_to_html(d.post.body_markdown),
               "internal_links": [{"anchor": l.anchor, "url": l.url} for l in d.post.internal_links]}
              for d in data.draft_posts if d.post is not None]

    content_volume_svg = _bar_chart_svg(
        [d["domain"] for d in sitemap_domains], [d["total"] for d in sitemap_domains],
        bar_color=branding.accent_color, text_color=branding.text_color,
    )
    keyword_counts = [{"domain": dk["domain"], "total": len(dk["keywords"])} for dk in domain_keywords]
    keyword_counts_svg = _bar_chart_svg(
        [d["domain"] for d in keyword_counts], [d["total"] for d in keyword_counts],
        bar_color=branding.primary_color, text_color=branding.text_color,
    )

    is_partial = bool(
        (data.sitemap and data.sitemap.is_partial) or (data.keywords and data.keywords.is_partial)
    )

    return {
        "branding": branding,
        "logo_html": _logo_html(branding),
        "client_name": config.client_name,
        "client_url": config.client_url,
        "report_date": report_date or "",
        "summary": {
            "competitor_count": len(config.competitor_urls),
            "content_gap_count": len(sitemap_gaps),
            "keyword_gap_count": len(keyword_gaps),
            "quick_win_count": len(quick_wins),
            "is_partial": is_partial,
        },
        "content_volume_svg": content_volume_svg,
        "keyword_counts_svg": keyword_counts_svg,
        "sitemap": {"domains": sitemap_domains, "gaps": sitemap_gaps},
        "keyword_gaps": keyword_gaps,
        "quick_wins": quick_wins,
        "domain_keywords": domain_keywords,
        "provided": provided,
        "topical_map": {"summary": topical_summary, "pillars": pillars},
        "drafts": drafts,
    }
