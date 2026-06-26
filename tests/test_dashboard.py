from compresearch.models import DashboardResult, JobData, JobConfig


def test_dashboard_result_defaults():
    r = DashboardResult()
    assert r.html_path is None
    assert r.error is None


def test_jobdata_has_dashboard_field_defaulting_none():
    data = JobData(config=JobConfig(client_name="Acme Co", client_url="https://acme.com"))
    assert data.dashboard is None


from compresearch.models import (
    Branding, SitemapResult, DomainSitemap, SitemapGap,
    KeywordResult, DomainKeywords, KeywordEntry, KeywordGap, QuickWin, ProvidedKeyword,
    TopicalMapResult, TopicalMap, PillarTopic, TopicCluster, ArticleIdea,
    DraftPostResult, DraftPost, InternalLink,
)


def _full_jobdata():
    return JobData(
        config=JobConfig(client_name="Acme Co", client_url="https://acme.com",
                         competitor_urls=["https://rival.com"]),
        sitemap=SitemapResult(
            client=DomainSitemap(domain="https://acme.com", total_urls=30),
            competitors=[DomainSitemap(domain="https://rival.com", total_urls=120)],
            gaps=[SitemapGap(section="case-studies", competitors_with=["https://rival.com"])],
        ),
        keywords=KeywordResult(
            client=DomainKeywords(domain="https://acme.com",
                                  keywords=[KeywordEntry(keyword="crm", search_volume=1000, position=8)],
                                  total_keywords=1),
            competitors=[DomainKeywords(domain="https://rival.com",
                                        keywords=[KeywordEntry(keyword="free crm", search_volume=800, position=4)],
                                        total_keywords=1)],
            gaps=[KeywordGap(keyword="free crm", search_volume=800, difficulty=30.0,
                             best_competitor_position=4, traffic_value=80.0,
                             competitors_ranking=["https://rival.com"])],
            quick_wins=[QuickWin(keyword="crm software", position=8, search_volume=1000,
                                 traffic_value=30.0, url="https://acme.com/crm")],
            provided=[ProvidedKeyword(keyword="best crm", search_volume=500, difficulty=20.0,
                                      client_position=12, best_competitor_position=3,
                                      competitors_ranking=["https://rival.com"])],
        ),
        topical_map=TopicalMapResult(map=TopicalMap(summary="A map.", pillars=[PillarTopic(
            name="CRM Basics", clusters=[TopicCluster(name="Intro", articles=[
                ArticleIdea(title="What is a CRM?", target_keyword="what is a crm")])])])),
        draft_posts=[DraftPostResult(post=DraftPost(
            title="What is a CRM?", target_keyword="what is a crm", word_count=1200,
            meta_description="A guide.", body_markdown="# What is a CRM?\n\nA CRM **helps** teams.",
            internal_links=[InternalLink(anchor="pricing", url="https://acme.com/pricing")]))],
    )


def test_build_dashboard_context_shape_and_completeness():
    from compresearch.dashboard import build_dashboard_context
    ctx = build_dashboard_context(_full_jobdata(), Branding(), report_date="June 2026")
    assert ctx["client_name"] == "Acme Co"
    assert ctx["report_date"] == "June 2026"
    assert ctx["summary"] == {"competitor_count": 1, "content_gap_count": 1,
                              "keyword_gap_count": 1, "quick_win_count": 1, "is_partial": False}
    assert ctx["keyword_gaps"][0]["keyword"] == "free crm"
    assert ctx["quick_wins"][0]["url"] == "https://acme.com/crm"
    # per-domain keyword tables: client + 1 competitor
    assert [d["domain"] for d in ctx["domain_keywords"]] == ["acme.com", "rival.com"]
    assert ctx["provided"][0]["keyword"] == "best crm"
    assert ctx["topical_map"]["pillars"][0].name == "CRM Basics"
    # draft body markdown rendered to HTML
    assert "<strong>helps</strong>" in ctx["drafts"][0]["body_html"]
    assert ctx["content_volume_svg"].startswith("<svg")


def test_build_dashboard_context_tolerates_missing_sections():
    from compresearch.dashboard import build_dashboard_context
    data = JobData(config=JobConfig(client_name="X", client_url="https://x.com"))
    ctx = build_dashboard_context(data, Branding())
    assert ctx["keyword_gaps"] == []
    assert ctx["drafts"] == []
    assert ctx["domain_keywords"] == []
    assert ctx["topical_map"]["pillars"] == []
    assert ctx["content_volume_svg"] == ""


def test_render_dashboard_html_contains_sections_and_is_self_contained():
    from compresearch.dashboard import build_dashboard_context, render_dashboard_html
    html = render_dashboard_html(build_dashboard_context(_full_jobdata(), Branding()))
    # key content present
    assert "Acme Co" in html
    assert "free crm" in html                      # keyword gap
    assert "What is a CRM?" in html                # topical map + draft
    assert "<strong>helps</strong>" in html        # rendered draft body
    assert "<svg" in html                          # inline chart
    # tabs rendered
    assert 'data-tab="keywords"' in html
    assert 'data-tab="domains"' in html
    # self-contained: no external CSS/JS/asset references
    assert "<link" not in html
    assert "src=\"http" not in html
    assert "src='http" not in html
    assert "cdn" not in html.lower()


def test_render_dashboard_html_handles_empty_job():
    from compresearch.dashboard import build_dashboard_context, render_dashboard_html
    data = JobData(config=JobConfig(client_name="X", client_url="https://x.com"))
    html = render_dashboard_html(build_dashboard_context(data, Branding()))
    assert "X" in html                              # renders without error
    assert 'data-tab="keywords"' not in html        # absent sections produce no tab


from compresearch.job_store import create_job, load_data, save_data


def test_run_dashboard_writes_html_and_records_path(tmp_path):
    from compresearch.dashboard import run_dashboard
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = _full_jobdata()
    data.config = cfg
    save_data(job_dir, data)

    run_dashboard(job_dir)

    reloaded = load_data(job_dir)
    assert reloaded.dashboard.error is None
    assert reloaded.dashboard.html_path.endswith("acme-co-dashboard.html")
    written = (job_dir / "outputs" / "acme-co-dashboard.html").read_text(encoding="utf-8")
    assert written.startswith("<!DOCTYPE html>")
    assert "free crm" in written


def test_run_dashboard_captures_render_error(tmp_path, monkeypatch):
    from compresearch import dashboard
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)

    def boom(context, templates_dir=dashboard.TEMPLATES_DIR):
        raise RuntimeError("template broke")

    monkeypatch.setattr(dashboard, "render_dashboard_html", boom)
    dashboard.run_dashboard(job_dir)

    data = load_data(job_dir)
    assert data.dashboard.html_path is None
    assert "template broke" in data.dashboard.error
