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


def test_draft_post_tab_is_metadata_with_doc_link():
    from compresearch.models import DraftExportResult
    data = _full_jobdata()
    data.config = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    data.draft_export = DraftExportResult(doc_url="https://docs.google.com/document/d/DOC/edit")

    tabs = build_sheet_model(data)
    draft = next(t for t in tabs if t.name == "Draft Post")
    flat = _flatten(draft)
    # metadata present
    assert "What is a CRM?" in flat                 # the Title row
    # the prose body is NOT dumped into the sheet anymore
    assert not any("A CRM helps teams." in cell for cell in flat)
    # a clickable Doc link is present
    assert any("HYPERLINK" in cell and "DOC/edit" in cell for cell in flat)


def test_draft_post_tab_omits_doc_link_when_no_export():
    data = _full_jobdata()  # no draft_export
    draft = next(t for t in build_sheet_model(data) if t.name == "Draft Post")
    assert not any("HYPERLINK" in cell for cell in _flatten(draft))


from compresearch.sheets import run_sheet, GoogleSheetWriter
from compresearch.job_store import create_job, load_data, save_data
import pytest


def make_fake_writer(captured, url="https://docs.google.com/spreadsheets/d/FAKE", raises=None):
    def writer(title, tabs):
        captured["title"] = title
        captured["tabs"] = tabs
        if raises is not None:
            raise raises
        return url
    return writer


def test_run_sheet_persists_url_and_passes_model(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = _full_jobdata()
    data.config = cfg
    save_data(job_dir, data)

    captured = {}
    run_sheet(job_dir, writer=make_fake_writer(captured))

    reloaded = load_data(job_dir)
    assert reloaded.sheet is not None
    assert reloaded.sheet.error is None
    assert reloaded.sheet.sheet_url.endswith("FAKE")
    assert captured["title"].startswith("Acme Co")
    assert any(t.name == "Keyword Gaps" for t in captured["tabs"])


def test_run_sheet_captures_writer_error(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    run_sheet(job_dir, writer=make_fake_writer({}, raises=RuntimeError("quota exceeded")))
    data = load_data(job_dir)
    assert data.sheet.sheet_url is None
    assert "quota exceeded" in data.sheet.error


def test_google_sheet_writer_from_settings_requires_credentials(monkeypatch):
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SHARE_EMAIL", raising=False)
    with pytest.raises(RuntimeError):
        GoogleSheetWriter.from_settings()
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "sa.json")
    with pytest.raises(RuntimeError):   # share email still missing
        GoogleSheetWriter.from_settings()


def test_google_sheet_writer_sanitizes_empty_rows():
    """The real __call__ must never send an empty row ([]) to the Sheets API."""
    updates = []

    class _WS:
        def update_title(self, name):
            pass

        def update(self, range_name=None, values=None):
            updates.append(values)

    class _SS:
        url = "https://docs.google.com/spreadsheets/d/FAKE"

        def __init__(self):
            self.sheet1 = _WS()

        def add_worksheet(self, title, rows, cols):
            return _WS()

        def share(self, email, perm_type, role):
            pass

    class _Client:
        def create(self, title, folder_id=None):
            return _SS()

    writer = GoogleSheetWriter(_Client(), "team@example.com")
    url = writer("Acme — Competitive Research", [SheetTab("Overview", [["a"], [], ["b", "c"]])])
    assert url.endswith("FAKE")
    sent_rows = [row for values in updates for row in values]
    assert [] not in sent_rows        # no empty row reached the API
    assert [""] in sent_rows          # the [] spacer became [""]


def test_run_sheet_warns_when_no_analysis_sections(tmp_path, caplog):
    import logging
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    with caplog.at_level(logging.WARNING):
        run_sheet(job_dir, writer=make_fake_writer({}))
    assert "no analysis sections" in caplog.text
