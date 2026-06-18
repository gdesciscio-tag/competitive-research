# tests/test_sheets.py
from compresearch.sheets import build_sheet_model, SheetTab
from compresearch.models import (
    JobConfig, JobData,
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
            quick_wins=[QuickWin(keyword="crm software", position=8, search_volume=1000, traffic_value=30.0,
                                 url="https://acme.com/crm")],
        ),
        topical_map=TopicalMapResult(map=TopicalMap(pillars=[PillarTopic(
            name="CRM Basics", clusters=[TopicCluster(name="Intro", articles=[
                ArticleIdea(title="What is a CRM?", target_keyword="what is a crm",
                            search_intent="informational", estimated_volume=2000)])])])),
        draft_post=DraftPostResult(post=DraftPost(
            title="What is a CRM?", meta_description="A guide.",
            body_markdown="# What is a CRM?\n\nA CRM helps teams.",
            internal_links=[InternalLink(anchor="pricing", url="https://acme.com/pricing")])),
    )


def _flatten(tab: SheetTab):
    return [str(cell) for row in tab.rows for cell in row]


def test_build_sheet_model_full_job_has_all_tabs():
    tabs = build_sheet_model(_full_jobdata())
    assert [t.name for t in tabs] == [
        "Overview", "Sitemap", "Keyword Gaps", "Quick Wins", "Topical Map", "Draft Post",
    ]
    by_name = {t.name: t for t in tabs}
    assert "free crm" in _flatten(by_name["Keyword Gaps"])
    assert "crm software" in _flatten(by_name["Quick Wins"])
    assert "case-studies" in _flatten(by_name["Sitemap"])
    assert "What is a CRM?" in _flatten(by_name["Topical Map"])
    assert "What is a CRM?" in _flatten(by_name["Draft Post"])
    # domains are shortened, totals present
    assert "acme.com" in _flatten(by_name["Sitemap"])
    assert "120" in _flatten(by_name["Sitemap"])


def test_build_sheet_model_minimal_job_is_overview_only():
    data = JobData(config=JobConfig(client_name="X", client_url="https://x.com"))
    assert [t.name for t in build_sheet_model(data)] == ["Overview"]


def test_build_sheet_model_converts_none_to_blank():
    data = JobData(
        config=JobConfig(client_name="X", client_url="https://x.com"),
        keywords=KeywordResult(gaps=[KeywordGap(keyword="bare")]),  # volume/difficulty/etc None
    )
    kg = next(t for t in build_sheet_model(data) if t.name == "Keyword Gaps")
    # the 'bare' data row has no None cells (None -> "")
    data_row = kg.rows[1]
    assert None not in data_row
    assert data_row[0] == "bare"
