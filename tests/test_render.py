# tests/test_render.py
import json
from pathlib import Path

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


from compresearch.render import _bar_chart_svg
from compresearch.utils import short_domain


def test_short_domain():
    assert short_domain("https://www.acme.com/blog") == "acme.com"
    assert short_domain("rival.com") == "rival.com"


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


def test_bar_chart_svg_angles_labels_to_avoid_overlap():
    svg = _bar_chart_svg(["adedgemarketing.com", "socialjackmedia.com"], [2559, 1475])
    assert 'transform="rotate(' in svg          # labels are angled, not overlapping
    assert "adedgemarketing.com" in svg


def test_logo_html_inlines_as_base64_data_uri(tmp_path):
    from compresearch.render import _logo_html
    from compresearch.models import Branding
    logo = tmp_path / "logo.svg"
    logo.write_text("<svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>", encoding="utf-8")
    html = _logo_html(Branding(logo_path=str(logo)))
    assert html.startswith("<img")
    assert "data:image/svg+xml;base64," in html
    assert "file://" not in html                # no blocked external reference


def test_logo_html_none_when_unset_or_missing(tmp_path):
    from compresearch.render import _logo_html
    from compresearch.models import Branding
    assert _logo_html(Branding()) is None
    assert _logo_html(Branding(logo_path=str(tmp_path / "does-not-exist.svg"))) is None


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
    assert "<strong>helps</strong>" in ctx["drafts"][0]["body_html"]
    # charts are SVG strings
    assert ctx["charts"]["content_volume_svg"].startswith("<svg")


def test_build_report_context_handles_missing_sections():
    data = JobData(config=JobConfig(client_name="X", client_url="https://x.com"))
    ctx = build_report_context(data, Branding(), report_date=None)
    assert ctx["summary"]["competitor_count"] == 0
    assert ctx["drafts"] == []
    assert ctx["topical_map"]["pillars"] == []
    assert ctx["charts"]["content_volume_svg"] == ""   # nothing to chart


from compresearch.render import render_report_html


def test_render_report_html_contains_key_sections():
    ctx = build_report_context(_full_jobdata(), Branding(), report_date="June 17, 2026")
    html = render_report_html(ctx)
    assert "Acme Co" in html                       # client name on the cover
    assert "TAG Online" in html                    # agency branding
    assert "Executive Summary" in html
    assert "case-studies" in html                  # a content gap
    assert "free crm" in html                      # a keyword gap
    assert "What is a CRM?" in html                # topical map + draft title
    assert "<strong>helps</strong>" in html        # rendered draft body
    assert "<svg" in html                          # an embedded chart
    assert "#16314F" in html or "#E2703A" in html  # branding colors applied


def _jobdata_with_n_gaps(n):
    from compresearch.models import (
        JobConfig, JobData, SitemapResult, DomainSitemap, SitemapGap,
    )
    gaps = [SitemapGap(section=f"sec-{i}", competitors_with=["https://rival.com"]) for i in range(n)]
    return JobData(
        config=JobConfig(client_name="Acme Co", client_url="https://acme.com"),
        sitemap=SitemapResult(client=DomainSitemap(domain="https://acme.com"), gaps=gaps),
    )


def test_build_report_context_caps_gaps_but_counts_all():
    ctx = build_report_context(_jobdata_with_n_gaps(20), Branding())
    assert ctx["summary"]["content_gap_count"] == 20   # full count in the exec summary
    assert len(ctx["sitemap"]["gaps"]) == 12           # capped for the PDF
    assert ctx["sitemap"]["gap_overflow"] == 8


def test_render_report_html_renders_gaps_as_table_with_overflow():
    html = render_report_html(build_report_context(_jobdata_with_n_gaps(20), Branding()))
    assert "Published by" in html        # rendered as a table, not a pill cloud
    assert "and 8 more" in html          # overflow pointer to the Sheet


def test_render_report_html_embeds_logo_inline(tmp_path):
    logo = tmp_path / "logo.svg"
    logo.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    ctx = build_report_context(_full_jobdata(), Branding(logo_path=str(logo)))
    assert "data:image/svg+xml;base64," in ctx["logo_html"]
    html = render_report_html(ctx)
    assert "data:image/svg+xml;base64," in html    # logo reaches the cover, no file:// ref
    assert "file:///" not in html


from compresearch.render import run_render
from compresearch.job_store import create_job, load_data, save_data


def test_run_render_writes_pdf_and_records_path(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    competitor_urls=["https://rival.com"])
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = _full_jobdata()
    data.config = cfg
    save_data(job_dir, data)

    captured = {}

    def fake_html_to_pdf(html, output_path):
        captured["html"] = html
        captured["path"] = output_path
        Path(output_path).write_text("PDF-STUB", encoding="utf-8")

    run_render(job_dir, html_to_pdf=fake_html_to_pdf, report_date="June 17, 2026")

    reloaded = load_data(job_dir)
    assert reloaded.render is not None
    assert reloaded.render.error is None
    assert reloaded.render.pdf_path.endswith("acme-co-competitive-research.pdf")
    assert Path(reloaded.render.pdf_path).exists()
    assert "Acme Co" in captured["html"]      # the real report HTML was passed through
    assert "free crm" in captured["html"]


def test_run_render_captures_renderer_error(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)

    def boom(html, output_path):
        raise RuntimeError("chromium missing")

    run_render(job_dir, html_to_pdf=boom)
    data = load_data(job_dir)
    assert data.render.pdf_path is None
    assert "chromium missing" in data.render.error


def test_build_report_context_marks_partial():
    data = _full_jobdata()
    data.sitemap.is_partial = True
    ctx = build_report_context(data, Branding())
    assert ctx["summary"]["is_partial"] is True


def test_render_report_html_shows_partial_note():
    data = _full_jobdata()
    data.keywords.is_partial = True
    html = render_report_html(build_report_context(data, Branding()))
    assert "partial-note" in html


def test_render_report_html_shows_draft_title():
    # the draft title renders as a heading even if the body has no H1
    html = render_report_html(build_report_context(_full_jobdata(), Branding()))
    assert "<h3>What is a CRM?</h3>" in html


def test_render_report_html_renders_every_draft():
    data = _full_jobdata()
    data.draft_posts = [
        DraftPostResult(post=DraftPost(title="What is a CRM?", body_markdown="# A\n\nFirst body.")),
        DraftPostResult(post=DraftPost(title="CRM Pricing", body_markdown="# B\n\nSecond body.")),
    ]
    html = render_report_html(build_report_context(data, Branding()))
    assert "<h3>What is a CRM?</h3>" in html
    assert "<h3>CRM Pricing</h3>" in html
    assert "First body." in html and "Second body." in html
    # sections are numbered when there is more than one draft
    assert "Sample Blog Post 1" in html and "Sample Blog Post 2" in html


def test_markdown_to_html_renders_bold_and_headings():
    from compresearch.render import markdown_to_html
    html = markdown_to_html("# Title\n\nA **bold** word.")
    assert "<h1>Title</h1>" in html
    assert "<strong>bold</strong>" in html
