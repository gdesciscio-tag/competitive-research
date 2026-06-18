# Render Module (Google Sheet) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Google Sheet appendix to `compresearch` that turns a job's finished `data.json` into a shared Google Sheet with tabs (Overview, Sitemap, Keyword Gaps, Quick Wins, Topical Map, Draft Post) — the data companion to the branded PDF.

**Architecture:** Mirrors the render (PDF) module. A pure `build_sheet_model(data)` turns `JobData` into a list of `SheetTab`s (name + rows); a `GoogleSheetWriter` writes them to a new Google Sheet via gspread and shares it with a configured team email. The gspread call is isolated behind an injectable `writer` seam (lazy gspread import), so tab-building and orchestration test fully offline (the test suite needs no gspread auth and no network). Mirrors the prior conventions: a thin `run_sheet(job_dir, ...) -> JobData` orchestrator that captures errors into a result `.error` and persists `data.json`.

**Tech Stack:** Python 3.11+ (running on 3.14), pydantic v2, gspread (+ google-auth, for real runs only), pytest. Builds on Plans 1–5 (merged to `master`). Scope: the **Google Sheet appendix** only.

---

## Context for the implementer

Already present in `compresearch` (do not recreate): full `models.py` schema, `settings.py` (`get_secret`), `job_store.py` (`load_data`, `save_data`, `slugify`, `create_job`), the four analysis modules, `render.py` (exports `_short_domain`), `cli.py` (subcommands `sitemap`/`keywords`/`topical-map`/`draft-post`/`render`; `run_from_args(argv, fetch=http_fetch, provider=None, generator=None, draft_generator=None, html_to_pdf=render_pdf) -> Path`). Shared pytest fixtures in `tests/conftest.py`. 104 tests pass. Run tests with `.venv\Scripts\python -m pytest` (Windows). Work on a feature branch off `master`; commit per task with the messages given.

**Decisions (from brainstorming):**
- **Sheet access:** each created Sheet is shared (editor) with a configured Google account from `GOOGLE_SHARE_EMAIL`, so it appears in that person's "Shared with me."
- **Auth:** service-account JSON path from `GOOGLE_SERVICE_ACCOUNT_JSON`; gspread default scopes (Sheets + Drive) cover create + share.
- The service account is set up; a live end-to-end verification is possible if `.env` has both keys (optional final step).

**Testability seam:** `run_sheet(job_dir, writer=None)`. `GoogleSheetWriter.from_settings()` lazy-imports gspread *after* checking the env vars, so importing `compresearch.sheets` never requires gspread, and tests inject a fake `writer` callable `(title, tabs) -> url`. The real gspread path is the only un-unit-tested boundary (like `render_pdf` / the LLM calls).

---

## File Structure

| File | Responsibility |
|------|----------------|
| `requirements.txt` (modify) | Add `gspread` |
| `.env.example` (modify) | Document `GOOGLE_SERVICE_ACCOUNT_JSON` + `GOOGLE_SHARE_EMAIL` |
| `compresearch/models.py` (modify) | Add `SheetResult`; add `sheet` to `JobData` |
| `compresearch/sheets.py` (create) | `SheetTab`, `build_sheet_model`, `GoogleSheetWriter`, `run_sheet` |
| `compresearch/cli.py` (modify) | Add a `sheet` subcommand |
| `tests/test_sheets.py` (create) | Tab model + orchestration via a fake writer — all offline |
| `tests/test_cli.py` (modify) | End-to-end `sheet` run with a fake writer; missing-credentials clean exit |
| `README.md` (modify) | Document the sheet usage + service-account setup; mark the module complete |

---

## Task 1: Dependency + SheetResult model

**Files:**
- Modify: `requirements.txt`, `.env.example`, `compresearch/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Add the dependency**

Append `gspread` to `requirements.txt`. Install:

Run: `.venv\Scripts\python -m pip install gspread`
Expected: installs cleanly (pulls `google-auth`). Pin the resolved version into `requirements.txt` (from `pip show gspread`); if the latest won't install on the installed Python, pin the newest that does.

- [ ] **Step 2: Document the env keys**

In `.env.example`, ensure these two lines are present (the file already lists `GOOGLE_SERVICE_ACCOUNT_JSON`; add the share email):

```
GOOGLE_SERVICE_ACCOUNT_JSON=
GOOGLE_SHARE_EMAIL=
```

- [ ] **Step 3: Write the failing test**

Append to `tests/test_models.py`:

```python
def test_sheet_result_and_jobdata_sheet():
    from compresearch.models import SheetResult, JobConfig, JobData
    r = SheetResult(sheet_url="https://docs.google.com/spreadsheets/d/abc")
    restored = SheetResult.model_validate_json(r.model_dump_json())
    assert restored.sheet_url.endswith("abc")
    assert restored.error is None
    data = JobData(config=JobConfig(client_name="X", client_url="https://x.com"))
    assert data.sheet is None
```

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_models.py -k sheet_result`
Expected: FAIL — `ImportError: cannot import name 'SheetResult'`.

- [ ] **Step 5: Write the implementation**

Add to `compresearch/models.py` (after `RenderResult`):

```python
class SheetResult(BaseModel):
    sheet_url: str | None = None
    error: str | None = None
```

Extend `JobData`:

```python
class JobData(BaseModel):
    config: JobConfig
    sitemap: SitemapResult | None = None
    keywords: KeywordResult | None = None
    topical_map: TopicalMapResult | None = None
    draft_post: DraftPostResult | None = None
    render: RenderResult | None = None
    sheet: SheetResult | None = None
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_models.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt .env.example compresearch/models.py tests/test_models.py
git commit -m "feat: add sheet result to schema and gspread dependency"
```

---

## Task 2: `build_sheet_model`

**Files:**
- Create: `compresearch/sheets.py`
- Test: `tests/test_sheets.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_sheets.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'compresearch.sheets'`.

- [ ] **Step 3: Write the implementation**

```python
# compresearch/sheets.py
from __future__ import annotations

from dataclasses import dataclass, field

from compresearch.models import JobData
from compresearch.render import _short_domain


@dataclass
class SheetTab:
    name: str
    rows: list[list] = field(default_factory=list)


def _cell(value):
    """Google Sheets cells: render None as an empty string."""
    return "" if value is None else value


def build_sheet_model(data: JobData) -> list[SheetTab]:
    """Turn a finished JobData into a list of sheet tabs (name + rows). Pure; only emits
    a tab for an analysis section that is present."""
    config = data.config
    tabs: list[SheetTab] = []

    # --- Overview (always) ---
    sitemap_gap_count = len(data.sitemap.gaps) if data.sitemap is not None else 0
    keyword_gap_count = len(data.keywords.gaps) if data.keywords is not None else 0
    quick_win_count = len(data.keywords.quick_wins) if data.keywords is not None else 0
    overview = [
        ["Competitive Research"],
        ["Client", config.client_name],
        ["Website", config.client_url],
        ["Competitors", ", ".join(config.competitor_urls)],
        [],
        ["Content gaps", sitemap_gap_count],
        ["Keyword gaps", keyword_gap_count],
        ["Quick wins", quick_win_count],
    ]
    tabs.append(SheetTab("Overview", overview))

    # --- Sitemap ---
    if data.sitemap is not None:
        rows = [["Site", "Total pages", "Posts/month"]]
        if data.sitemap.client is not None:
            c = data.sitemap.client
            rows.append([_short_domain(c.domain), c.total_urls, _cell(c.posts_per_month)])
        for comp in data.sitemap.competitors:
            rows.append([_short_domain(comp.domain), comp.total_urls, _cell(comp.posts_per_month)])
        if data.sitemap.gaps:
            rows += [[], ["Content gaps"], ["Section", "Competitors with it"]]
            for gap in data.sitemap.gaps:
                rows.append([gap.section, ", ".join(_short_domain(d) for d in gap.competitors_with)])
        tabs.append(SheetTab("Sitemap", rows))

    # --- Keywords ---
    if data.keywords is not None:
        gap_rows = [["Keyword", "Volume", "Difficulty", "Best competitor rank",
                     "Est. traffic value", "Competitors"]]
        for g in data.keywords.gaps:
            gap_rows.append([
                g.keyword, _cell(g.search_volume), _cell(g.difficulty),
                _cell(g.best_competitor_position), _cell(g.traffic_value),
                ", ".join(_short_domain(d) for d in g.competitors_ranking),
            ])
        tabs.append(SheetTab("Keyword Gaps", gap_rows))

        win_rows = [["Keyword", "Current position", "Volume", "Est. traffic value", "URL"]]
        for w in data.keywords.quick_wins:
            win_rows.append([w.keyword, w.position, _cell(w.search_volume),
                             _cell(w.traffic_value), _cell(w.url)])
        tabs.append(SheetTab("Quick Wins", win_rows))

    # --- Topical map ---
    if data.topical_map is not None and data.topical_map.map is not None:
        rows = [["Pillar", "Cluster", "Article", "Target keyword", "Intent", "Est. volume"]]
        for pillar in data.topical_map.map.pillars:
            for cluster in pillar.clusters:
                for article in cluster.articles:
                    rows.append([
                        pillar.name, cluster.name, article.title,
                        _cell(article.target_keyword), _cell(article.search_intent),
                        _cell(article.estimated_volume),
                    ])
        tabs.append(SheetTab("Topical Map", rows))

    # --- Draft post ---
    if data.draft_post is not None and data.draft_post.post is not None:
        post = data.draft_post.post
        rows = [
            ["Title", post.title],
            ["Target keyword", _cell(post.target_keyword)],
            ["Title tag", _cell(post.title_tag)],
            ["Meta description", _cell(post.meta_description)],
            [],
        ]
        if post.internal_links:
            rows += [["Internal links"], ["Anchor", "URL"]]
            for link in post.internal_links:
                rows.append([link.anchor, link.url])
            rows.append([])
        rows += [["Body (Markdown)"], [post.body_markdown]]
        tabs.append(SheetTab("Draft Post", rows))

    return tabs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_sheets.py`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/sheets.py tests/test_sheets.py
git commit -m "feat: build Google Sheet tab model from job data"
```

---

## Task 3: `GoogleSheetWriter` + `run_sheet` orchestration

**Files:**
- Modify: `compresearch/sheets.py`
- Test: `tests/test_sheets.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sheets.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_sheets.py -k "run_sheet or from_settings"`
Expected: FAIL — `ImportError: cannot import name 'run_sheet'`.

- [ ] **Step 3: Write the implementation**

Add to the top imports of `compresearch/sheets.py`:

```python
import logging
from pathlib import Path
from typing import Callable

from compresearch.job_store import load_data, save_data
from compresearch.models import SheetResult
from compresearch.settings import get_secret
```

Append:

```python
SheetWriter = Callable[[str, list[SheetTab]], str]


class GoogleSheetWriter:
    """Writes the sheet model to a new Google Sheet via gspread and shares it. gspread is
    imported lazily so importing this module (and the test suite) does not require it."""

    def __init__(self, client, share_email: str) -> None:
        self.client = client
        self.share_email = share_email

    def __call__(self, title: str, tabs: list[SheetTab]) -> str:
        spreadsheet = self.client.create(title)
        for index, tab in enumerate(tabs):
            cols = max((len(row) for row in tab.rows), default=1)
            if index == 0:
                worksheet = spreadsheet.sheet1
                worksheet.update_title(tab.name)
            else:
                worksheet = spreadsheet.add_worksheet(
                    title=tab.name, rows=max(len(tab.rows) + 2, 10), cols=max(cols, 4)
                )
            if tab.rows:
                worksheet.update(range_name="A1", values=tab.rows)
        spreadsheet.share(self.share_email, perm_type="user", role="writer")
        return spreadsheet.url

    @classmethod
    def from_settings(cls) -> "GoogleSheetWriter":
        sa_path = get_secret("GOOGLE_SERVICE_ACCOUNT_JSON")
        share_email = get_secret("GOOGLE_SHARE_EMAIL")
        if not sa_path:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON must be set to create a Google Sheet")
        if not share_email:
            raise RuntimeError("GOOGLE_SHARE_EMAIL must be set to share the created Google Sheet")
        import gspread

        return cls(gspread.service_account(filename=sa_path), share_email)


def run_sheet(job_dir, writer: SheetWriter | None = None) -> JobData:
    """Build the sheet model, write it to a Google Sheet, and record the URL in data.json."""
    data = load_data(job_dir)
    if writer is None:
        writer = GoogleSheetWriter.from_settings()
    title = f"{data.config.client_name} — Competitive Research"
    try:
        tabs = build_sheet_model(data)
        url = writer(title, tabs)
        data.sheet = SheetResult(sheet_url=url)
    except Exception as exc:
        logging.warning("Google Sheet creation failed for %s: %s", data.config.client_url, exc)
        data.sheet = SheetResult(error=str(exc))
    save_data(job_dir, data)
    return data
```

Note: the `JobData` annotation on `run_sheet` needs `JobData` imported — it's already imported at the top of the file (Task 2). The gspread `worksheet.update(range_name="A1", values=tab.rows)` call targets gspread 6.x; if a different gspread major is pinned, adjust the `update` call to that version's signature (this is the live, un-unit-tested boundary).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_sheets.py`
Expected: PASS (all sheet tests green).

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python -m pytest`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add compresearch/sheets.py tests/test_sheets.py
git commit -m "feat: add Google Sheet writer and run_sheet orchestration"
```

---

## Task 4: CLI `sheet` subcommand

**Files:**
- Modify: `compresearch/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_sheet_subcommand(tmp_path):
    from compresearch.models import SitemapResult, DomainSitemap
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = load_data(job_dir)
    data.sitemap = SitemapResult(client=DomainSitemap(domain="https://acme.com",
                                                      section_counts={"blog": 5}, total_urls=5))
    save_data(job_dir, data)

    captured = {}

    def fake_writer(title, tabs):
        captured["title"] = title
        return "https://docs.google.com/spreadsheets/d/FAKE"

    returned = run_from_args(["sheet", "--job-dir", str(job_dir)], sheet_writer=fake_writer)
    assert returned == job_dir
    data = load_data(returned)
    assert data.sheet.sheet_url.endswith("FAKE")
    assert captured["title"].startswith("Acme Co")


def test_sheet_subcommand_missing_credentials_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SHARE_EMAIL", raising=False)
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    with pytest.raises(SystemExit) as exc:
        run_from_args(["sheet", "--job-dir", str(job_dir)])  # no writer -> from_settings
    assert exc.value.code == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py -k sheet`
Expected: FAIL — `run_from_args` has no `sheet_writer` parameter, or argparse rejects `sheet`.

- [ ] **Step 3: Write the implementation**

In `compresearch/cli.py`:

1. Add the import: `from compresearch.sheets import run_sheet`.
2. Add a `sheet_writer=None` parameter to `run_from_args` (after `html_to_pdf`):

```python
def run_from_args(
    argv: list[str],
    fetch: Fetcher = http_fetch,
    provider=None,
    generator: Generator | None = None,
    draft_generator: DraftGenerator | None = None,
    html_to_pdf=render_pdf,
    sheet_writer=None,
) -> Path:
```

3. Add the subparser (after the `render` subparser):

```python
    sh = sub.add_parser("sheet", help="Create the Google Sheet appendix for an existing job")
    sh.add_argument("--job-dir", required=True)
```

4. Add the dispatch branch (after the `render` branch, before the final `raise`):

```python
    if args.command == "sheet":
        job_dir = Path(args.job_dir)
        try:
            run_sheet(job_dir, writer=sheet_writer)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        return job_dir
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py`
Expected: PASS (all existing CLI tests plus the two new sheet tests).

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python -m pytest`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add compresearch/cli.py tests/test_cli.py
git commit -m "feat: add sheet CLI subcommand"
```

---

## Task 5: Docs + optional live verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the README**

Add a section after the render section and flip the status checklist line. Add:

```markdown
## Create the Google Sheet appendix

The sheet module turns a job's finished `data.json` into a shared Google Sheet with tabs
(Overview, Sitemap, Keyword Gaps, Quick Wins, Topical Map, Draft Post).

**One-time setup:**
1. In Google Cloud, create a service account and enable the Google Sheets API and Google Drive API.
2. Download the service-account JSON key.
3. In `.env`, set `GOOGLE_SERVICE_ACCOUNT_JSON` to the JSON file path and `GOOGLE_SHARE_EMAIL`
   to the Google account that should own/see the sheets (each created sheet is shared with it
   as editor and appears under "Shared with me").

**Create the sheet:**

```
.venv\Scripts\python -m compresearch.cli sheet --job-dir jobs\acme-co
```

The shareable URL is recorded in `data.json` under `sheet`.
```

Change the render status line so the Google Sheet is now checked:

```markdown
- [x] Render module (branded PDF + Google Sheet)
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document Google Sheet module and service-account setup"
```

- [ ] **Step 3: (Optional) Live verification**

If `GOOGLE_SERVICE_ACCOUNT_JSON` and `GOOGLE_SHARE_EMAIL` are set in `.env` and point at a real,
ready service account, optionally run a live end-to-end sheet creation to confirm the gspread path:
seed a small job (sitemap + keywords) into a temp dir, call `run_sheet(job_dir)` (no fake writer),
and confirm `data.sheet.sheet_url` is a real `https://docs.google.com/spreadsheets/...` URL with no
error. If the credentials are not present, skip this step — the offline tests are the gate. Report
the outcome (URL or exact error). Do not commit any credentials.

---

## Self-Review Notes

- **Spec coverage:** Google Sheet appendix with the spec's six tabs — Overview, Sitemap, Keyword Gaps, Quick Wins, Topical Map, Draft Post (Task 2). Shared with a configured team email (Task 3) — the brainstorming decision. gspread + service-account auth via `from_settings` (Task 3). Output URL persisted under `sheet` (Tasks 1, 3). This completes the render/deliverables layer (PDF from Plan 5 + Sheet here).
- **Placeholder scan:** No TBDs; every code/test step is complete. The gspread `update` signature note is a real, version-specific caveat on the live boundary, not a placeholder.
- **Type/name consistency:** `SheetResult`, `SheetTab`, `_cell`, `build_sheet_model`, `SheetWriter`, `GoogleSheetWriter`, `run_sheet` used consistently across tasks/tests. `run_from_args` gains `sheet_writer` (default None), used only by the `sheet` branch. `run_sheet(job_dir, ...) -> JobData` matches the other orchestrators for Plan 6.
- **Offline testing:** the gspread path is isolated in `GoogleSheetWriter` (lazy import); all tests inject a fake `writer` and never import gspread or hit Google. Tab building and orchestration are verified offline; `from_settings` credential-guard is tested without gspread.
- **Reuse:** `_short_domain` is reused from `render.py`; no new domain helper.
- **Known follow-ups:** the live gspread path is exercised only against a real service account — verify once via the optional step; the `worksheet.update` signature may need adjusting to the pinned gspread major. **Next: Plan 6 (Orchestrator + Claude Code skill)** — chain `run_sitemap → run_keywords → run_topical_map → run_draft_post → run_render → run_sheet` with per-job cost logging and a one-command operator entry point.
