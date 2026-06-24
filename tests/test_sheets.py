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


def test_safe_value_neutralizes_formula_text_but_keeps_hyperlinks():
    from compresearch.sheets import _safe_value
    assert _safe_value("=cmd(1)") == "'=cmd(1)"      # injection text -> apostrophe-prefixed
    assert _safe_value("+1-800") == "'+1-800"
    assert _safe_value("-lead") == "'-lead"
    assert _safe_value("@handle") == "'@handle"
    assert _safe_value('=HYPERLINK("u", "u")') == '=HYPERLINK("u", "u")'  # intended formula kept
    assert _safe_value("free crm") == "free crm"     # ordinary text untouched
    assert _safe_value(800) == 800                   # numbers untouched


def test_build_format_requests_rejects_unknown_color_scale_direction():
    import pytest
    from compresearch.sheets import build_format_requests, SheetTab, ColorScale
    from compresearch.models import Branding
    tab = SheetTab("X", [["h"], ["a"], ["b"]], color_scales=[ColorScale(0, "sideways")])
    with pytest.raises(ValueError):
        build_format_requests(tab, sheet_id=1, branding=Branding())


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

        def update(self, range_name=None, values=None, **kwargs):
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


def test_build_sheet_model_declares_formatting():
    data = _full_jobdata()
    tabs = {t.name: t for t in build_sheet_model(data, run_date="2026-06-23")}

    overview = tabs["Overview"]
    assert overview.tab_color is True
    assert overview.title_block is not None and overview.title_block.span == 2
    assert any(row == ["Generated", "2026-06-23"] for row in overview.rows)

    kg = tabs["Keyword Gaps"]
    assert kg.header is True
    assert kg.basic_filter is True
    assert kg.number_formats == {1: "#,##0", 2: "0", 3: "0", 4: "$#,##0"}
    assert any(cs.col == 2 and cs.direction == "low_good" for cs in kg.color_scales)

    qw = tabs["Quick Wins"]
    assert qw.header is True and qw.basic_filter is True
    assert qw.number_formats == {1: "0", 2: "#,##0", 3: "$#,##0"}
    assert any(cs.col == 1 and cs.direction == "low_good" for cs in qw.color_scales)
    # URL column became a clickable HYPERLINK (row 1 is the single quick-win)
    assert any("HYPERLINK" in str(c) and "acme.com/crm" in str(c) for c in qw.rows[1])

    assert tabs["Sitemap"].header is True
    assert tabs["Sitemap"].number_formats == {1: "#,##0"}
    assert tabs["Topical Map"].header is True
    assert tabs["Topical Map"].number_formats == {5: "#,##0"}


def test_build_sheet_model_no_run_date_omits_generated_row():
    data = _full_jobdata()
    overview = next(t for t in build_sheet_model(data) if t.name == "Overview")
    assert not any(row and row[0] == "Generated" for row in overview.rows)


def test_quick_wins_blank_url_is_not_hyperlink():
    data = JobData(
        config=JobConfig(client_name="X", client_url="https://x.com"),
        keywords=KeywordResult(quick_wins=[QuickWin(keyword="bare", position=5)]),  # url=None
    )
    qw = next(t for t in build_sheet_model(data) if t.name == "Quick Wins")
    assert qw.rows[1][4] == ""          # blank, not =HYPERLINK("")


def test_sheettab_formatting_fields_default_off():
    from compresearch.sheets import SheetTab, ColorScale, TitleBlock
    t = SheetTab("X", [["a"]])
    assert t.header is False
    assert t.number_formats == {}
    assert t.color_scales == []
    assert t.basic_filter is False
    assert t.tab_color is False
    assert t.title_block is None
    # the helper types exist and carry their fields
    assert ColorScale(2, "low_good").direction == "low_good"
    assert TitleBlock(3).span == 3


def test_hex_to_rgb():
    from compresearch.sheets import _hex_to_rgb
    rgb = _hex_to_rgb("#AB1D42")
    assert round(rgb["red"], 3) == round(171 / 255, 3)
    assert round(rgb["green"], 3) == round(29 / 255, 3)
    assert round(rgb["blue"], 3) == round(66 / 255, 3)


def _req_types(requests):
    return [next(iter(r)) for r in requests]


def test_build_format_requests_header_freeze_and_number_formats():
    from compresearch.sheets import build_format_requests, SheetTab, _hex_to_rgb
    from compresearch.models import Branding
    branding = Branding(primary_color="#AB1D42")
    tab = SheetTab("Keyword Gaps",
                   [["Keyword", "Volume"], ["free crm", 800]],
                   header=True, number_formats={1: "#,##0"})
    reqs = build_format_requests(tab, sheet_id=99, branding=branding)
    types = _req_types(reqs)
    assert "repeatCell" in types          # header style + number format both use repeatCell
    assert "updateSheetProperties" in types  # frozen row
    # header repeatCell carries the brand background and targets sheet 99
    header_req = next(r["repeatCell"] for r in reqs
                      if "repeatCell" in r and r["repeatCell"]["range"].get("startRowIndex") == 0
                      and r["repeatCell"]["range"].get("endRowIndex") == 1)
    assert header_req["range"]["sheetId"] == 99
    bg = header_req["cell"]["userEnteredFormat"]["backgroundColor"]
    assert round(bg["red"], 3) == round(171 / 255, 3)
    assert header_req["cell"]["userEnteredFormat"]["textFormat"]["bold"] is True
    # a number-format repeatCell exists for column 1 with the pattern
    num_req = next(r["repeatCell"] for r in reqs
                   if "repeatCell" in r
                   and r["repeatCell"]["cell"]["userEnteredFormat"].get("numberFormat", {}).get("pattern") == "#,##0")
    assert num_req["range"]["startColumnIndex"] == 1
    assert num_req["range"]["startRowIndex"] == 1   # data rows only, below header
    # frozen row
    freeze = next(r["updateSheetProperties"] for r in reqs if "updateSheetProperties" in r
                  and "gridProperties" in r["updateSheetProperties"]["properties"])
    assert freeze["properties"]["gridProperties"]["frozenRowCount"] == 1


def test_build_format_requests_color_scale_filter_tabcolor_title():
    from compresearch.sheets import build_format_requests, SheetTab, ColorScale, TitleBlock
    from compresearch.models import Branding
    branding = Branding(primary_color="#AB1D42")

    kg = SheetTab("Keyword Gaps", [["Keyword", "Difficulty"], ["a", 30]],
                  header=True, basic_filter=True, color_scales=[ColorScale(1, "low_good")])
    reqs = build_format_requests(kg, sheet_id=5, branding=branding)
    types = _req_types(reqs)
    assert "addConditionalFormatRule" in types
    assert "setBasicFilter" in types
    grad = next(r["addConditionalFormatRule"]["rule"]["gradientRule"]
                for r in reqs if "addConditionalFormatRule" in r)
    # low_good: MIN point is green-ish (more green than red), MAX point is red-ish
    assert grad["minpoint"]["color"]["green"] > grad["minpoint"]["color"]["red"]
    assert grad["maxpoint"]["color"]["red"] > grad["maxpoint"]["color"]["green"]

    ov = SheetTab("Overview", [["Competitive Research"], ["Client", "Acme"]],
                  tab_color=True, title_block=TitleBlock(span=2))
    reqs2 = build_format_requests(ov, sheet_id=0, branding=branding)
    types2 = _req_types(reqs2)
    assert "mergeCells" in types2
    assert "updateSheetProperties" in types2   # tab color
    merge = next(r["mergeCells"]["range"] for r in reqs2 if "mergeCells" in r)
    assert merge["startRowIndex"] == 0 and merge["endColumnIndex"] == 2


def test_build_format_requests_empty_for_plain_tab():
    from compresearch.sheets import build_format_requests, SheetTab
    from compresearch.models import Branding
    tab = SheetTab("Draft Post", [["Title", "X"]])   # no formatting flags
    assert build_format_requests(tab, sheet_id=1, branding=Branding()) == []


def test_build_format_requests_skips_numbers_and_scales_when_no_data_rows():
    from compresearch.sheets import build_format_requests, SheetTab, ColorScale
    from compresearch.models import Branding
    # header-only tab (no data rows) must not emit zero-height number-format / color-scale ranges
    tab = SheetTab("Keyword Gaps", [["Keyword", "Difficulty"]],
                   header=True, basic_filter=True,
                   number_formats={1: "#,##0"}, color_scales=[ColorScale(1, "low_good")])
    reqs = build_format_requests(tab, sheet_id=7, branding=Branding())
    kinds = [next(iter(r)) for r in reqs]
    assert "addConditionalFormatRule" not in kinds
    # the only repeatCell is the header style (row 0), not a number format
    assert all(r["repeatCell"]["range"].get("startRowIndex") == 0
               for r in reqs if "repeatCell" in r)
    # header + freeze + filter still emitted
    assert "updateSheetProperties" in kinds and "setBasicFilter" in kinds


def _formatting_fake_spreadsheet():
    """A fake gspread Spreadsheet/Worksheet that records batch_update calls."""
    captured = {"batch": None, "updates": []}

    class _WS:
        _next_id = 0

        def __init__(self):
            _WS._next_id += 1
            self.id = _WS._next_id

        def update_title(self, name):
            pass

        def update(self, range_name=None, values=None, **kwargs):
            captured["updates"].append(values)

    class _SS:
        url = "https://docs.google.com/spreadsheets/d/FAKE"

        def __init__(self):
            self.sheet1 = _WS()

        def add_worksheet(self, title, rows, cols):
            return _WS()

        def share(self, email, perm_type, role):
            pass

        def batch_update(self, body):
            captured["batch"] = body
            return body

    class _Client:
        def create(self, title, folder_id=None):
            return _SS()

    return _Client(), captured


def test_writer_sends_one_batched_format_update():
    from compresearch.sheets import GoogleSheetWriter, build_sheet_model
    from compresearch.models import Branding
    client, captured = _formatting_fake_spreadsheet()
    writer = GoogleSheetWriter(client, "team@example.com", branding=Branding(primary_color="#AB1D42"))
    tabs = build_sheet_model(_full_jobdata(), run_date="2026-06-23")
    url = writer("Acme — Competitive Research", tabs)
    assert url.endswith("FAKE")
    assert captured["batch"] is not None
    reqs = captured["batch"]["requests"]
    # header styling + a basic filter both made it into the single batch
    kinds = {next(iter(r)) for r in reqs}
    assert "repeatCell" in kinds and "setBasicFilter" in kinds and "updateSheetProperties" in kinds


def test_writer_formatting_failure_still_returns_url():
    from compresearch.sheets import GoogleSheetWriter, build_sheet_model
    from compresearch.models import Branding
    client, captured = _formatting_fake_spreadsheet()

    ss = client.create("t")
    def boom(body):
        raise RuntimeError("bad request")
    # Patch the spreadsheet instance the writer will create to raise on batch_update.
    class _Client2:
        def create(self, title, folder_id=None):
            s = ss
            s.batch_update = boom
            return s
    writer = GoogleSheetWriter(_Client2(), "team@example.com", branding=Branding())
    tabs = build_sheet_model(_full_jobdata(), run_date="2026-06-23")
    url = writer("Acme — Competitive Research", tabs)   # must NOT raise
    assert url.endswith("FAKE")


def _keywords_with_lists():
    from compresearch.models import JobConfig, JobData, KeywordResult, DomainKeywords, KeywordEntry
    cfg = JobConfig(
        client_name="ATS Hire",
        client_url="https://atshire.com/",
        competitor_urls=["https://bluesignal.com/"],
    )
    kw = KeywordResult(
        client=DomainKeywords(domain="atshire.com", keywords=[
            KeywordEntry(keyword="rf recruiter", search_volume=200, difficulty=20, position=6,
                         url="https://atshire.com/rf"),
            KeywordEntry(keyword="photonics jobs", search_volume=900, difficulty=30, position=12),
        ]),
        competitors=[DomainKeywords(domain="bluesignal.com", keywords=[
            KeywordEntry(keyword="wireless recruiter", search_volume=400, difficulty=25, position=3),
        ])],
    )
    return JobData(config=cfg, keywords=kw)


def test_build_sheet_model_emits_client_and_competitor_keyword_tabs():
    tabs = build_sheet_model(_keywords_with_lists())
    names = [t.name for t in tabs]
    assert "ATS Hire — Keywords" in names
    assert "bluesignal.com" in names
    # Order: client tab precedes competitor tabs; both precede Topical Map / Draft Post
    assert names.index("ATS Hire — Keywords") < names.index("bluesignal.com")

    by_name = {t.name: t for t in tabs}
    client_tab = by_name["ATS Hire — Keywords"]
    assert client_tab.rows[0] == ["Keyword", "Volume", "Difficulty", "Position", "URL"]
    # Sorted by volume descending: photonics jobs (900) before rf recruiter (200)
    assert [r[0] for r in client_tab.rows[1:]] == ["photonics jobs", "rf recruiter"]


def test_keyword_tabs_skipped_when_lists_empty():
    from compresearch.models import JobConfig, JobData, KeywordResult, DomainKeywords
    cfg = JobConfig(client_name="ATS Hire", client_url="https://atshire.com/")
    data = JobData(config=cfg, keywords=KeywordResult(
        client=DomainKeywords(domain="atshire.com", keywords=[]),
        competitors=[DomainKeywords(domain="bluesignal.com", keywords=[])],
    ))
    names = [t.name for t in build_sheet_model(data)]
    assert "ATS Hire — Keywords" not in names
    assert "bluesignal.com" not in names


def test_build_sheet_model_emits_provided_keywords_tab():
    from compresearch.models import (
        JobConfig, JobData, KeywordResult, DomainKeywords, ProvidedKeyword,
    )
    cfg = JobConfig(client_name="ATS Hire", client_url="https://atshire.com/")
    data = JobData(config=cfg, keywords=KeywordResult(
        client=DomainKeywords(domain="atshire.com", keywords=[]),
        provided=[
            ProvidedKeyword(
                keyword="RF Engineering Recruiter", search_volume=320, difficulty=18,
                client_position=None, competitors_ranking=["bluesignal.com"],
                best_competitor_position=4,
            ),
        ],
    ))
    tabs = build_sheet_model(data)
    by_name = {t.name: t for t in tabs}
    assert "Client-Provided Keywords" in by_name
    tab = by_name["Client-Provided Keywords"]
    assert tab.rows[0] == ["Keyword", "Volume", "Difficulty", "Client rank",
                           "Competitors ranking", "Best competitor rank"]
    assert tab.rows[1] == ["RF Engineering Recruiter", 320, 18, "", "bluesignal.com", 4]


def test_provided_tab_absent_when_no_provided_keywords():
    from compresearch.models import JobConfig, JobData, KeywordResult
    data = JobData(config=JobConfig(client_name="ATS Hire", client_url="https://atshire.com/"),
                   keywords=KeywordResult())
    assert "Client-Provided Keywords" not in [t.name for t in build_sheet_model(data)]
