# Draft-Post Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the draft blog post out of a Google Sheet cell into an editable Google Doc plus a CMS-paste-ready HTML file, via a new dedicated pipeline step.

**Architecture:** A new `draft_export` step (one module, mirroring `sheets.py`) runs after `draft_post` and before `render`/`sheet`. It renders the draft Markdown to HTML once, always writes a local `.html` file, then uploads that HTML to Google Drive converted to a Google Doc inside the configured Shared Drive. The Sheet keeps only the draft's SEO metadata plus a link to the Doc. Every external (Drive) failure degrades gracefully — the local HTML is always produced.

**Tech Stack:** Python 3.14, pydantic, gspread, `google-api-python-client` (new), `markdown`, pytest. Google access uses the existing service-account + `GOOGLE_SHARED_DRIVE_ID` trio.

---

## File Structure

- `compresearch/models.py` — add `DraftExportResult`, add `JobData.draft_export` field.
- `compresearch/render.py` — extract `markdown_to_html()`; `build_report_context` calls it.
- `compresearch/draft_export.py` — **new**: `build_draft_html`, `DocWriter`, `GoogleDocWriter`, `run_draft_export`.
- `compresearch/orchestrator.py` — new `draft_export` step + `doc_writer` param.
- `compresearch/cli.py` — `draft-export` subcommand, `doc_writer` param, summary lines.
- `compresearch/sheets.py` — slim the "Draft Post" tab + Doc-link row.
- `requirements.txt` — add `google-api-python-client`.
- `tests/test_models.py`, `tests/test_render.py`, `tests/test_draft_export.py` (new), `tests/test_orchestrator.py`, `tests/test_cli.py`, `tests/test_sheets.py` — tests.

Run the whole suite at any checkpoint with: `.venv\Scripts\python -m pytest -q`

---

### Task 1: Add the Drive client dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add the dependency line**

Add this line to `requirements.txt` (after `gspread==6.2.1`):

```
google-api-python-client==2.149.0
```

- [ ] **Step 2: Install it**

Run: `.venv\Scripts\python -m pip install google-api-python-client==2.149.0`
Expected: ends with `Successfully installed ... google-api-python-client-2.149.0 ...` (plus its transitive deps). If pip reports that exact version is unavailable, install without the pin (`pip install google-api-python-client`), then run `.venv\Scripts\python -m pip show google-api-python-client` and set the pin in `requirements.txt` to the `Version:` it reports.

- [ ] **Step 3: Verify import works**

Run: `.venv\Scripts\python -c "from googleapiclient.discovery import build; from googleapiclient.http import MediaInMemoryUpload; print('ok')"`
Expected: prints `ok`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "build: add google-api-python-client for Drive Doc upload"
```

---

### Task 2: Add the `DraftExportResult` model

**Files:**
- Modify: `compresearch/models.py` (add class after `SheetResult`; add field to `JobData`)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
def test_draft_export_result_defaults_and_jobdata_field():
    from compresearch.models import DraftExportResult, JobData, JobConfig

    r = DraftExportResult()
    assert r.html_path is None
    assert r.doc_url is None
    assert r.is_partial is False
    assert r.error is None

    data = JobData(config=JobConfig(client_name="X", client_url="https://x.com"))
    assert data.draft_export is None  # field exists, defaults to None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_models.py::test_draft_export_result_defaults_and_jobdata_field -v`
Expected: FAIL with `ImportError: cannot import name 'DraftExportResult'`

- [ ] **Step 3: Add the model and field**

In `compresearch/models.py`, add this class immediately after the `SheetResult` class:

```python
class DraftExportResult(BaseModel):
    html_path: str | None = None    # local outputs/<slug>-draft.html
    doc_url: str | None = None      # Google Doc in the Shared Drive
    is_partial: bool = False        # HTML written but Doc creation failed
    error: str | None = None        # set only when even HTML could not be written
```

In the `JobData` class, add the `draft_export` field between `draft_post` and `render`:

```python
class JobData(BaseModel):
    config: JobConfig
    sitemap: SitemapResult | None = None
    keywords: KeywordResult | None = None
    topical_map: TopicalMapResult | None = None
    draft_post: DraftPostResult | None = None
    draft_export: DraftExportResult | None = None
    render: RenderResult | None = None
    sheet: SheetResult | None = None
    run_report: RunReport | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_models.py::test_draft_export_result_defaults_and_jobdata_field -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add compresearch/models.py tests/test_models.py
git commit -m "feat: add DraftExportResult model and JobData.draft_export field"
```

---

### Task 3: Extract `markdown_to_html` shared helper

**Files:**
- Modify: `compresearch/render.py` (add function; call it in `build_report_context`)
- Test: `tests/test_render.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_render.py`:

```python
def test_markdown_to_html_renders_bold_and_headings():
    from compresearch.render import markdown_to_html
    html = markdown_to_html("# Title\n\nA **bold** word.")
    assert "<h1>Title</h1>" in html
    assert "<strong>bold</strong>" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_render.py::test_markdown_to_html_renders_bold_and_headings -v`
Expected: FAIL with `ImportError: cannot import name 'markdown_to_html'`

- [ ] **Step 3: Add the helper and use it**

In `compresearch/render.py`, add this function just below the `TEMPLATES_DIR = ...` line near the top:

```python
def markdown_to_html(md: str) -> str:
    """Render Markdown to HTML using the project's standard extensions.

    Shared by the PDF report context and the draft-export module so the draft renders
    identically in both. The output is trusted LLM content; see the trust-boundary note
    in build_report_context before serving it to a browser.
    """
    return markdown.markdown(md, extensions=["extra", "sane_lists"])
```

In `build_report_context`, replace the inline call:

```python
            "body_html": markdown.markdown(post.body_markdown, extensions=["extra", "sane_lists"]),
```

with:

```python
            "body_html": markdown_to_html(post.body_markdown),
```

- [ ] **Step 4: Run the render tests to verify parity**

Run: `.venv\Scripts\python -m pytest tests/test_render.py -q`
Expected: PASS (including the existing `test_build_report_context_shape`, which asserts `<strong>helps</strong>` in `ctx["draft"]["body_html"]`)

- [ ] **Step 5: Commit**

```bash
git add compresearch/render.py tests/test_render.py
git commit -m "refactor: extract markdown_to_html shared helper in render"
```

---

### Task 4: `build_draft_html` pure function

**Files:**
- Create: `compresearch/draft_export.py`
- Test: `tests/test_draft_export.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_draft_export.py`:

```python
from compresearch.models import Branding, DraftPost, InternalLink


def _post():
    return DraftPost(
        title="What Is a VSL?",
        target_keyword="video sales letter",
        title_tag="What Is a VSL? A Quick Guide",
        meta_description="A VSL turns visitors into customers.",
        body_markdown="## Intro\n\nA VSL is a **video sales letter**.",
        internal_links=[InternalLink(anchor="our services", url="https://acme.com/services")],
    )


def test_build_draft_html_includes_title_metadata_body_and_links():
    from compresearch.draft_export import build_draft_html

    html = build_draft_html(_post(), Branding())
    assert "<h1>What Is a VSL?</h1>" in html
    assert "video sales letter" in html          # target keyword in metadata header
    assert "What Is a VSL? A Quick Guide" in html  # title tag
    assert "A VSL turns visitors into customers." in html  # meta description
    assert "<strong>video sales letter</strong>" in html   # body rendered via markdown_to_html
    assert "https://acme.com/services" in html   # internal link url
    assert "our services" in html                # internal link anchor


def test_build_draft_html_escapes_metadata():
    from compresearch.draft_export import build_draft_html

    post = _post()
    post.title = "A < B & C"
    html = build_draft_html(post, Branding())
    assert "A &lt; B &amp; C" in html            # title escaped in the <h1>
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_draft_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'compresearch.draft_export'`

- [ ] **Step 3: Create the module with `build_draft_html`**

Create `compresearch/draft_export.py`:

```python
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

    links_html = ""
    if post.internal_links:
        items = "".join(
            f"<li><a href=\"{escape(link.url)}\">{escape(link.anchor)}</a></li>"
            for link in post.internal_links
        )
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_draft_export.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add compresearch/draft_export.py tests/test_draft_export.py
git commit -m "feat: build_draft_html renders a standalone branded draft document"
```

---

### Task 5: `GoogleDocWriter` and `DocWriter` protocol

**Files:**
- Modify: `compresearch/draft_export.py` (append after `build_draft_html`)
- Test: `tests/test_draft_export.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_draft_export.py`:

```python
import pytest


class _FakeExecutable:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeFiles:
    def __init__(self, calls):
        self._calls = calls

    def create(self, body=None, media_body=None, fields=None, supportsAllDrives=None):
        self._calls["create"] = {
            "body": body, "fields": fields, "supportsAllDrives": supportsAllDrives,
        }
        return _FakeExecutable({"id": "DOC123", "webViewLink": "https://docs.google.com/document/d/DOC123/edit"})


class _FakePermissions:
    def __init__(self, calls):
        self._calls = calls

    def create(self, fileId=None, body=None, supportsAllDrives=None, sendNotificationEmail=None):
        self._calls["permission"] = {"fileId": fileId, "body": body}
        return _FakeExecutable({"id": "perm1"})


class _FakeService:
    def __init__(self):
        self.calls = {}

    def files(self):
        return _FakeFiles(self.calls)

    def permissions(self):
        return _FakePermissions(self.calls)


def test_google_doc_writer_uploads_html_into_folder_and_shares():
    from compresearch.draft_export import GoogleDocWriter

    service = _FakeService()
    writer = GoogleDocWriter(service, "team@example.com", folder_id="DRIVE9")
    url = writer("Acme — Draft Post", "<html><body><h1>Hi</h1></body></html>")

    assert url == "https://docs.google.com/document/d/DOC123/edit"
    create = service.calls["create"]
    assert create["body"]["mimeType"] == "application/vnd.google-apps.document"
    assert create["body"]["parents"] == ["DRIVE9"]
    assert create["supportsAllDrives"] is True
    assert service.calls["permission"]["body"]["emailAddress"] == "team@example.com"


def test_google_doc_writer_from_settings_requires_credentials(monkeypatch):
    from compresearch.draft_export import GoogleDocWriter

    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SHARE_EMAIL", raising=False)
    monkeypatch.delenv("GOOGLE_SHARED_DRIVE_ID", raising=False)
    with pytest.raises(RuntimeError):
        GoogleDocWriter.from_settings()
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "sa.json")
    with pytest.raises(RuntimeError):   # share email still missing
        GoogleDocWriter.from_settings()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_draft_export.py::test_google_doc_writer_uploads_html_into_folder_and_shares -v`
Expected: FAIL with `ImportError: cannot import name 'GoogleDocWriter'`

- [ ] **Step 3: Implement `DocWriter` + `GoogleDocWriter`**

Append to `compresearch/draft_export.py` (after `build_draft_html`):

```python
DOC_MIME = "application/vnd.google-apps.document"

DocWriter = Callable[[str, str], str]


class GoogleDocWriter:
    """Uploads draft HTML to Google Drive, converted to a Google Doc, inside a Shared
    Drive folder, and shares it. The googleapiclient import is lazy so importing this
    module (and the test suite) does not require it."""

    def __init__(self, service, share_email: str, folder_id: str | None = None) -> None:
        self.service = service
        self.share_email = share_email
        self.folder_id = folder_id

    def __call__(self, title: str, html: str) -> str:
        from googleapiclient.http import MediaInMemoryUpload

        body = {"name": title, "mimeType": DOC_MIME}
        if self.folder_id:
            body["parents"] = [self.folder_id]
        media = MediaInMemoryUpload(html.encode("utf-8"), mimetype="text/html", resumable=False)
        created = self.service.files().create(
            body=body,
            media_body=media,
            fields="id,webViewLink",
            supportsAllDrives=True,
        ).execute()
        doc_id = created["id"]
        self.service.permissions().create(
            fileId=doc_id,
            body={"type": "user", "role": "writer", "emailAddress": self.share_email},
            supportsAllDrives=True,
            sendNotificationEmail=False,
        ).execute()
        return created.get("webViewLink") or f"https://docs.google.com/document/d/{doc_id}/edit"

    @classmethod
    def from_settings(cls) -> "GoogleDocWriter":
        sa_path = get_secret("GOOGLE_SERVICE_ACCOUNT_JSON")
        share_email = get_secret("GOOGLE_SHARE_EMAIL")
        folder_id = get_secret("GOOGLE_SHARED_DRIVE_ID")
        if not sa_path:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON must be set to create a Google Doc")
        if not share_email:
            raise RuntimeError("GOOGLE_SHARE_EMAIL must be set to share the created Google Doc")
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_service_account_file(
            sa_path, scopes=["https://www.googleapis.com/auth/drive"]
        )
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return cls(service, share_email, folder_id or None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_draft_export.py -v`
Expected: PASS (all four tests in the file so far)

- [ ] **Step 5: Commit**

```bash
git add compresearch/draft_export.py tests/test_draft_export.py
git commit -m "feat: GoogleDocWriter uploads draft HTML to a Shared Drive Doc"
```

---

### Task 6: `run_draft_export` orchestration function

**Files:**
- Modify: `compresearch/draft_export.py` (append `run_draft_export`)
- Test: `tests/test_draft_export.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_draft_export.py`:

```python
from compresearch.job_store import create_job, load_data, save_data
from compresearch.models import JobConfig, JobData, DraftPostResult


def _job_with_draft(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = JobData(config=cfg, draft_post=DraftPostResult(post=_post()))
    save_data(job_dir, data)
    return job_dir


def test_run_draft_export_writes_html_and_records_doc_url(tmp_path):
    from compresearch.draft_export import run_draft_export

    job_dir = _job_with_draft(tmp_path)
    captured = {}

    def fake_doc_writer(title, html):
        captured["title"] = title
        captured["html"] = html
        return "https://docs.google.com/document/d/DOC/edit"

    run_draft_export(job_dir, doc_writer=fake_doc_writer)

    data = load_data(job_dir)
    assert data.draft_export.error is None
    assert data.draft_export.is_partial is False
    assert data.draft_export.doc_url.endswith("/edit")
    assert data.draft_export.html_path.endswith("acme-co-draft.html")
    assert (job_dir / "outputs" / "acme-co-draft.html").read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert captured["title"] == "Acme Co — Draft Post"


def test_run_draft_export_partial_when_doc_writer_fails(tmp_path):
    from compresearch.draft_export import run_draft_export

    job_dir = _job_with_draft(tmp_path)

    def boom(title, html):
        raise RuntimeError("drive unavailable")

    run_draft_export(job_dir, doc_writer=boom)

    data = load_data(job_dir)
    assert data.draft_export.html_path is not None     # HTML still written
    assert (job_dir / "outputs" / "acme-co-draft.html").exists()
    assert data.draft_export.doc_url is None
    assert data.draft_export.is_partial is True
    assert "drive unavailable" in data.draft_export.error


def test_run_draft_export_graceful_when_no_draft(tmp_path):
    from compresearch.draft_export import run_draft_export

    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)  # no draft_post

    run_draft_export(job_dir, doc_writer=lambda t, h: "unused")

    data = load_data(job_dir)
    assert data.draft_export.html_path is None
    assert data.draft_export.doc_url is None
    assert "No draft post" in data.draft_export.error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_draft_export.py::test_run_draft_export_writes_html_and_records_doc_url -v`
Expected: FAIL with `ImportError: cannot import name 'run_draft_export'`

- [ ] **Step 3: Implement `run_draft_export`**

Append to `compresearch/draft_export.py`:

```python
def run_draft_export(job_dir: Path, doc_writer: DocWriter | None = None, branding: Branding | None = None) -> JobData:
    """Render the draft to a local HTML file and a Google Doc; record both in data.json.

    The local HTML is always written first; a Drive/Doc failure leaves the HTML in place
    and marks the result partial. Never raises — failures are captured like the other steps.
    """
    data = load_data(job_dir)
    if data.draft_post is None or data.draft_post.post is None:
        logging.warning(
            "No draft post to export for %s; run the draft-post module first",
            data.config.client_url,
        )
        data.draft_export = DraftExportResult(error="No draft post available to export")
        save_data(job_dir, data)
        return data

    branding = branding or load_branding()
    post = data.draft_post.post
    slug = slugify(data.config.client_name)
    output_path = Path(job_dir) / "outputs" / f"{slug}-draft.html"

    try:
        html = build_draft_html(post, branding)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
    except Exception as exc:
        logging.warning("Draft HTML render failed for %s: %s", data.config.client_url, exc)
        data.draft_export = DraftExportResult(error=str(exc))
        save_data(job_dir, data)
        return data

    result = DraftExportResult(html_path=str(output_path))
    if doc_writer is None:
        try:
            doc_writer = GoogleDocWriter.from_settings()
        except Exception as exc:
            logging.warning("Google Doc writer unavailable for %s: %s", data.config.client_url, exc)
            result.is_partial = True
            result.error = str(exc)
            data.draft_export = result
            save_data(job_dir, data)
            return data

    title = f"{data.config.client_name} — Draft Post"
    try:
        result.doc_url = doc_writer(title, html)
    except Exception as exc:
        logging.warning("Google Doc creation failed for %s: %s", data.config.client_url, exc)
        result.is_partial = True
        result.error = str(exc)
    data.draft_export = result
    save_data(job_dir, data)
    return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_draft_export.py -v`
Expected: PASS (all seven tests in the file)

- [ ] **Step 5: Commit**

```bash
git add compresearch/draft_export.py tests/test_draft_export.py
git commit -m "feat: run_draft_export writes HTML and Google Doc with graceful fallback"
```

---

### Task 7: Wire `draft_export` into the orchestrator

**Files:**
- Modify: `compresearch/orchestrator.py` (import, new step, `doc_writer` param)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Update the orchestrator tests**

In `tests/test_orchestrator.py`, in `_full_run`, add a `doc_writer` fake and pass it. Replace the `sheet_writer` definition and the `run_job(...)` call inside `_full_run` with:

```python
    def sheet_writer(title, tabs):
        captured["sheet_title"] = title
        return "https://docs.google.com/spreadsheets/d/FAKE"

    def doc_writer(title, html):
        captured["doc_title"] = title
        return "https://docs.google.com/document/d/DOCFAKE/edit"

    data = run_job(
        job_dir,
        fetch=_sitemap_fetch(),
        keyword_provider=_keyword_provider(),
        topical_generator=_topical_generator(),
        draft_generator=_draft_generator(),
        html_to_pdf=html_to_pdf,
        sheet_writer=sheet_writer,
        doc_writer=doc_writer,
    )
    return data, captured
```

In `test_run_job_runs_all_six_steps_offline`, update the expected step list and add draft-export assertions:

```python
    report = data.run_report
    assert [s.name for s in report.steps] == [
        "sitemap", "keywords", "topical_map", "draft_post", "draft_export", "render", "sheet",
    ]
    assert all(s.status == "ok" for s in report.steps), [(s.name, s.status, s.error) for s in report.steps]
    # deliverables produced
    assert data.render.pdf_path.endswith(".pdf")
    assert data.sheet.sheet_url.endswith("FAKE")
    assert data.draft_export.html_path.endswith("acme-co-draft.html")
    assert data.draft_export.doc_url.endswith("DOCFAKE/edit")
```

In the three other tests (`test_run_job_is_resilient_to_a_failed_step`, `test_run_job_marks_step_failed_when_generator_errors_and_continues`, `test_run_job_marks_sitemap_partial_when_a_competitor_fetch_fails`), add a `doc_writer` argument to each `run_job(...)` call so they exercise the new step offline. In each of those three tests, add this line just before its `run_job(` call:

```python
    def doc_writer(title, html):
        return "https://docs.google.com/document/d/DOCFAKE/edit"
```

and add `doc_writer=doc_writer,` to that test's `run_job(...)` keyword arguments.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL — `test_run_job_runs_all_six_steps_offline` fails on the step-list assertion (no `draft_export`), and `run_job()` raises `TypeError: run_job() got an unexpected keyword argument 'doc_writer'`.

- [ ] **Step 3: Add the step and parameter to the orchestrator**

In `compresearch/orchestrator.py`, add the import near the other step imports:

```python
from compresearch.draft_export import run_draft_export
```

Add `doc_writer=None` to the `run_job` signature (after `sheet_writer=None`):

```python
def run_job(
    job_dir,
    *,
    fetch=http_fetch,
    keyword_provider=None,
    topical_generator=None,
    draft_generator=None,
    html_to_pdf=render_pdf,
    sheet_writer=None,
    doc_writer=None,
) -> JobData:
```

Insert this new step block between the draft-post step (step 4) and the render step (step 5):

```python
    # 5. Draft export (HTML + Google Doc)
    t = time.monotonic()
    try:
        run_draft_export(job_dir, doc_writer=doc_writer)
        status, err = _section_status(job_dir, "draft_export")
        record("draft_export", status, err, t)
    except Exception as exc:
        record("draft_export", "failed", str(exc), t)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_orchestrator.py -v`
Expected: PASS (all four tests)

- [ ] **Step 5: Commit**

```bash
git add compresearch/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: run draft_export step in the pipeline between draft and render"
```

---

### Task 8: CLI subcommand, run-job wiring, and summary lines

**Files:**
- Modify: `compresearch/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_run_from_args_draft_export_writes_html_and_records_doc(tmp_path):
    from compresearch.cli import run_from_args
    from compresearch.job_store import create_job, load_data, save_data
    from compresearch.models import JobConfig, JobData, DraftPostResult, DraftPost

    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = JobData(config=cfg, draft_post=DraftPostResult(post=DraftPost(
        title="What is a CRM?", body_markdown="# What is a CRM?\n\nBody.")))
    save_data(job_dir, data)

    def doc_writer(title, html):
        return "https://docs.google.com/document/d/DOC/edit"

    returned = run_from_args(["draft-export", "--job-dir", str(job_dir)], doc_writer=doc_writer)

    assert returned == job_dir
    reloaded = load_data(job_dir)
    assert reloaded.draft_export.doc_url.endswith("/edit")
    assert reloaded.draft_export.html_path.endswith("acme-co-draft.html")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py::test_run_from_args_draft_export_writes_html_and_records_doc -v`
Expected: FAIL with `TypeError: run_from_args() got an unexpected keyword argument 'doc_writer'`

- [ ] **Step 3: Wire the CLI**

In `compresearch/cli.py`, add the import:

```python
from compresearch.draft_export import run_draft_export
```

Add `doc_writer=None` to the `run_from_args` signature (after `sheet_writer=None`):

```python
def run_from_args(argv: list[str], fetch: Fetcher = http_fetch, provider=None, generator: Generator | None = None, draft_generator: DraftGenerator | None = None, html_to_pdf=render_pdf, sheet_writer=None, doc_writer=None) -> Path:
```

Register the subcommand — add this just after the `sh = sub.add_parser("sheet", ...)` block:

```python
    de = sub.add_parser("draft-export", help="Export the draft post to HTML + a Google Doc")
    de.add_argument("--job-dir", required=True)
```

Add the command branch — add this just before the `if args.command == "run-job":` block:

```python
    if args.command == "draft-export":
        job_dir = Path(args.job_dir)
        run_draft_export(job_dir, doc_writer=doc_writer)
        return job_dir
```

In the `run-job` branch, pass `doc_writer` into `run_job(...)`:

```python
        data = run_job(
            job_dir,
            fetch=fetch,
            keyword_provider=provider,
            topical_generator=generator,
            draft_generator=draft_generator,
            html_to_pdf=html_to_pdf,
            sheet_writer=sheet_writer,
            doc_writer=doc_writer,
        )
```

In `_print_run_summary`, add the draft-export output lines just after the Sheet block (after the `if data.sheet is not None ...` lines, before the cost print):

```python
    if data.draft_export is not None:
        if data.draft_export.html_path:
            print(f"  Draft HTML: {data.draft_export.html_path}")
        if data.draft_export.doc_url:
            print(f"  Draft Doc:  {data.draft_export.doc_url}")
```

- [ ] **Step 4: Run the CLI tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py -v`
Expected: PASS (the new test and all existing CLI tests)

- [ ] **Step 5: Commit**

```bash
git add compresearch/cli.py tests/test_cli.py
git commit -m "feat: add draft-export CLI command and run-job summary lines"
```

---

### Task 9: Slim the Sheet's "Draft Post" tab

**Files:**
- Modify: `compresearch/sheets.py` (the draft-post tab block in `build_sheet_model`)
- Test: `tests/test_sheets.py`

- [ ] **Step 1: Update and add the failing tests**

In `tests/test_sheets.py`, the existing `test_build_sheet_model_full_job_has_all_tabs` still expects a "Draft Post" tab containing the title "What is a CRM?" — that stays true. Add a new test that asserts the body is gone and the Doc link appears:

```python
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
    assert "A CRM helps teams." not in flat
    assert not any("A CRM helps teams." in cell for cell in flat)
    # a clickable Doc link is present
    assert any("HYPERLINK" in cell and "DOC/edit" in cell for cell in flat)


def test_draft_post_tab_omits_doc_link_when_no_export():
    data = _full_jobdata()  # no draft_export
    draft = next(t for t in build_sheet_model(data) if t.name == "Draft Post")
    assert not any("HYPERLINK" in cell for cell in _flatten(draft))
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `.venv\Scripts\python -m pytest tests/test_sheets.py::test_draft_post_tab_is_metadata_with_doc_link -v`
Expected: FAIL — the body string `A CRM helps teams.` is still present in the tab, and no `HYPERLINK` cell exists yet.

- [ ] **Step 3: Replace the draft-post tab block**

In `compresearch/sheets.py`, replace the entire draft-post block in `build_sheet_model` (currently starting at `# --- Draft post ---` and building `rows` with `body_markdown`) with:

```python
    # --- Draft post (metadata only; the prose lives in the exported Doc/HTML) ---
    if data.draft_post is not None and data.draft_post.post is not None:
        post = data.draft_post.post
        rows = [
            ["Title", post.title],
            ["Target keyword", _cell(post.target_keyword)],
            ["Title tag", _cell(post.title_tag)],
            ["Meta description", _cell(post.meta_description)],
        ]
        doc_url = data.draft_export.doc_url if data.draft_export is not None else None
        if doc_url:
            rows.append(["Document", f'=HYPERLINK("{doc_url}", "Open draft")'])
        tabs.append(SheetTab("Draft Post", rows))
```

- [ ] **Step 4: Run the sheet tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_sheets.py -v`
Expected: PASS (the two new tests plus all existing sheet tests, including `test_build_sheet_model_full_job_has_all_tabs`)

- [ ] **Step 5: Commit**

```bash
git add compresearch/sheets.py tests/test_sheets.py
git commit -m "feat: slim the Sheet draft tab to metadata plus a Doc link"
```

---

### Task 10: Full suite + manual smoke check

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all tests pass, no errors.

- [ ] **Step 2: Re-export the real TAG Online draft against the Shared Drive**

This uses live Google credentials and the existing `jobs/tag-online` job (which already has a `draft_post`):

Run: `.venv\Scripts\python -m compresearch.cli draft-export --job-dir jobs/tag-online`
Expected: exits cleanly (`Job complete: jobs\tag-online`).

- [ ] **Step 3: Verify the artifacts**

Run: `.venv\Scripts\python -c "import json;d=json.load(open('jobs/tag-online/data.json'));print(d['draft_export'])"`
Expected: a dict with a non-null `html_path` and `doc_url`, `is_partial` false, `error` null. Confirm `jobs/tag-online/outputs/tag-online-draft.html` exists and opens in a browser, and that the `doc_url` opens a Google Doc inside the "Comp Research" Shared Drive.

- [ ] **Step 4: Final commit (if any working-tree changes remain)**

```bash
git add -A
git commit -m "test: verify draft-export end to end" --allow-empty
```

---

## Self-Review Notes

- **Spec coverage:** model (Task 2) ✓; shared `markdown_to_html` (Task 3) ✓; `build_draft_html` (Task 4) ✓; `DocWriter`/`GoogleDocWriter` (Task 5) ✓; `run_draft_export` with partial/graceful paths (Task 6) ✓; orchestrator step + order (Task 7) ✓; CLI subcommand + summary (Task 8) ✓; slim Sheet tab + Doc link (Task 9) ✓; `google-api-python-client` dependency (Task 1) ✓; PDF unchanged (no task touches the PDF draft section) ✓.
- **Type consistency:** `DraftExportResult(html_path, doc_url, is_partial, error)` used identically across tasks; `DocWriter = (title, html) -> url` matches `GoogleDocWriter.__call__`, the orchestrator/CLI fakes, and `run_draft_export`'s `doc_writer(title, html)` call; `run_job`/`run_from_args` both gain `doc_writer=None`.
- **Section ordering:** `draft_export` is inserted between `draft_post` and `render` everywhere (model field, orchestrator step, expected test list).
