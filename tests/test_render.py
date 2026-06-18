# tests/test_render.py
import json

from compresearch.branding import load_branding


def test_load_branding_defaults_when_no_override(tmp_path):
    b = load_branding(tmp_path / "missing.json")
    assert b.agency_name == "TAG Online"


def test_load_branding_merges_override(tmp_path):
    path = tmp_path / "branding.json"
    path.write_text(json.dumps({"agency_name": "Acme Agency", "accent_color": "#00FF00"}),
                    encoding="utf-8")
    b = load_branding(path)
    assert b.agency_name == "Acme Agency"        # overridden
    assert b.accent_color == "#00FF00"           # overridden
    assert b.primary_color.startswith("#")       # default preserved


from compresearch.render import _bar_chart_svg, _short_domain


def test_short_domain():
    assert _short_domain("https://www.acme.com/blog") == "acme.com"
    assert _short_domain("rival.com") == "rival.com"


def test_bar_chart_svg_renders_values_and_labels():
    svg = _bar_chart_svg(["acme.com", "rival.com"], [10, 30])
    assert svg.startswith("<svg")
    assert "rival.com" in svg
    assert ">30<" in svg   # value label present
    assert "<rect" in svg  # bars present


def test_bar_chart_svg_empty_returns_empty():
    assert _bar_chart_svg([], []) == ""


def test_bar_chart_svg_escapes_labels():
    svg = _bar_chart_svg(["a&b.com"], [5])
    assert "a&amp;b.com" in svg
    assert "a&b.com" not in svg


from compresearch.render import build_report_context
from compresearch.models import (
    JobConfig, JobData, Branding,
    SitemapResult, DomainSitemap, SitemapGap,
    KeywordResult, KeywordGap, QuickWin,
    TopicalMapResult, TopicalMap, PillarTopic, TopicCluster, ArticleIdea,
    DraftPostResult, DraftPost, InternalLink,
)


def _full_jobdata():
    return JobData(
        config=JobConfig(client_name="Acme Co", client_url="https://acme.com",
                         competitor_urls=["https://rival.com"]),
        sitemap=SitemapResult(
            client=DomainSitemap(domain="https://acme.com", section_counts={"blog": 30}, total_urls=30),
            competitors=[DomainSitemap(domain="https://rival.com", section_counts={"blog": 120}, total_urls=120)],
            gaps=[SitemapGap(section="case-studies", competitors_with=["https://rival.com"])],
        ),
        keywords=KeywordResult(
            gaps=[KeywordGap(keyword="free crm", search_volume=800, difficulty=30.0,
                             best_competitor_position=4, traffic_value=80.0,
                             competitors_ranking=["https://rival.com"])],
            quick_wins=[QuickWin(keyword="crm software", position=8, search_volume=1000, traffic_value=30.0)],
        ),
        topical_map=TopicalMapResult(map=TopicalMap(pillars=[PillarTopic(
            name="CRM Basics", clusters=[TopicCluster(name="Intro", articles=[
                ArticleIdea(title="What is a CRM?", target_keyword="what is a crm")])])])),
        draft_post=DraftPostResult(post=DraftPost(
            title="What is a CRM?", meta_description="A guide.",
            body_markdown="# What is a CRM?\n\nA CRM **helps** teams.",
            internal_links=[InternalLink(anchor="pricing", url="https://acme.com/pricing")])),
    )


def test_build_report_context_shape():
    ctx = build_report_context(_full_jobdata(), Branding(), report_date="June 17, 2026")
    assert ctx["client_name"] == "Acme Co"
    assert ctx["report_date"] == "June 17, 2026"
    assert ctx["summary"]["competitor_count"] == 1
    assert ctx["summary"]["content_gap_count"] == 1
    assert ctx["summary"]["keyword_gap_count"] == 1
    assert ctx["summary"]["quick_win_count"] == 1
    # sitemap domains include client + competitor totals
    assert {d["domain"]: d["total"] for d in ctx["sitemap"]["domains"]} == {"acme.com": 30, "rival.com": 120}
    assert ctx["keywords"]["gaps"][0]["keyword"] == "free crm"
    assert ctx["topical_map"]["pillars"][0].name == "CRM Basics"
    # draft body markdown is rendered to HTML
    assert "<strong>helps</strong>" in ctx["draft"]["body_html"]
    # charts are SVG strings
    assert ctx["charts"]["content_volume_svg"].startswith("<svg")


def test_build_report_context_handles_missing_sections():
    data = JobData(config=JobConfig(client_name="X", client_url="https://x.com"))
    ctx = build_report_context(data, Branding(), report_date=None)
    assert ctx["summary"]["competitor_count"] == 0
    assert ctx["draft"] is None
    assert ctx["topical_map"]["pillars"] == []
    assert ctx["charts"]["content_volume_svg"] == ""   # nothing to chart
