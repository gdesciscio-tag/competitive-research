# Draft-Post Export — Design

**Date:** 2026-06-22
**Status:** Approved (pending spec review)

## Problem

The competitive-research draft blog post is currently emitted only as a row inside the Google
Sheet — the entire ~6,400-character Markdown body is jammed into a single cell
(`sheets.py`, the "Draft Post" tab). A spreadsheet cell is the wrong container for prose: the
display truncates, there is no heading hierarchy, line breaks mangle, and copying it out is
painful.

The draft already appears, formatted, inside the client-facing PDF report
(`render.py` `build_report_context`, the `draft` section). So this work is **not** about the
client deliverable — it is about giving the *operator* a usable, editable working copy.

## Goals

- Produce the draft in formats people actually use: an editable **Google Doc** and a
  CMS-paste-ready **HTML file**.
- Stop dumping prose into the Sheet; keep only the genuinely tabular SEO metadata there, plus a
  link to the Doc.
- Fail gracefully — no new external dependency (Google Drive) may break the existing pipeline.

## Non-Goals

- No change to the PDF report; it keeps embedding the formatted draft as the client sample.
- No Sheet *formatting* work (bold headers, color scales, etc.) — that is a separate, deferred
  effort.
- No change to draft-post generation (the LLM step) itself.

## Decisions (from brainstorming)

- **Output formats:** Google Doc **and** HTML file.
- **Sheet's draft tab:** slim it to metadata (target keyword, title tag, meta description) plus a
  `=HYPERLINK()` to the Doc. Not removed entirely.
- **Architecture:** a new dedicated `draft_export` pipeline step (one-module-per-step pattern),
  not folded into `render`/`sheet` and not bolted onto the `draft_post` LLM step.
- **Drive upload mechanism:** add `google-api-python-client` (official lib) for the HTML→Doc
  media upload, isolated inside `GoogleDocWriter`.

## Architecture

Pipeline order becomes:

```
sitemap -> keywords -> topical_map -> draft_post -> draft_export -> render -> sheet
```

`draft_export` runs **before `sheet`** so the Sheet can link to the created Doc.

### 1. Data model (`models.py`)

```python
class DraftExportResult(BaseModel):
    html_path: str | None = None    # local outputs/<slug>-draft.html
    doc_url: str | None = None      # Google Doc in the Shared Drive
    is_partial: bool = False        # HTML written but Doc creation failed
    error: str | None = None        # set only when even HTML couldn't be written
```

Add `draft_export: DraftExportResult | None = None` to `JobData`, positioned between
`draft_post` and `render`.

### 2. Shared render helper (`render.py`)

Extract the inline `markdown.markdown(post.body_markdown, extensions=["extra", "sane_lists"])`
(currently in `build_report_context`) into:

```python
def markdown_to_html(md: str) -> str: ...
```

Both `build_report_context` and the new `draft_export` module call it, so the PDF and the
exported Doc/HTML render identically.

### 3. New module `draft_export.py`

- `build_draft_html(post: DraftPost, branding: Branding) -> str` — **pure** function returning a
  complete, standalone, lightly-branded HTML document:
  - `<h1>` title
  - a compact metadata header (target keyword / title tag / meta description)
  - the rendered body (via `markdown_to_html`)
  - an "Internal links" list
  - Browser-viewable and clean enough to paste into a CMS or convert to a Google Doc.
  - Fully testable offline.

- `DocWriter = Callable[[str, str], str]` protocol — `(title, html) -> doc_url`. The target
  folder is held by the writer instance (mirroring how `GoogleSheetWriter` holds `folder_id`),
  not passed per call.
- `GoogleDocWriter` implementation (mirrors `GoogleSheetWriter`):
  - Holds `folder_id` (from `GOOGLE_SHARED_DRIVE_ID`) and `share_email` as instance attributes.
  - Uploads the HTML to Drive with `mimeType: application/vnd.google-apps.document` and
    `supportsAllDrives=True`, into the `folder_id` (Shared Drive) folder.
  - Shares the Doc with `GOOGLE_SHARE_EMAIL` (best-effort, mirroring the Sheet writer).
  - Returns the Doc URL.
  - `from_settings()` reads `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHARE_EMAIL`,
    `GOOGLE_SHARED_DRIVE_ID` (same trio as the Sheet writer).

- `run_draft_export(job_dir, doc_writer=None) -> JobData`:
  1. Load data; if no `draft_post.post`, record `error` and return (graceful, like the other
     steps).
  2. Render HTML and **always** write `outputs/<slug>-draft.html`.
  3. Try to create the Doc:
     - Success → record `html_path` + `doc_url`.
     - Doc failure → keep `html_path`, set `is_partial=True` + `error` → step reports
       **partial**.
     - HTML write failure → `error`, no paths → step reports **failed**.

### 4. Orchestrator + CLI

- `orchestrator.run_job`: insert a `draft_export` step after `draft_post`, before `render`. It
  is wrapped in its own try/except and recorded in the `RunReport`, like every other step. The
  run summary gains a `draft_export` line.
- `cli.py`: new `draft-export --job-dir` subcommand, re-runnable standalone (like `sheet`).

### 5. Sheet change (`sheets.py`)

In `build_sheet_model`, replace the body-dumping "Draft Post" tab with a slim metadata tab:

- Target keyword
- Title tag
- Meta description
- `=HYPERLINK(doc_url, "Open draft")` row — only when `data.draft_export` and its `doc_url`
  exist; omit the row otherwise.

The body Markdown no longer appears in the Sheet.

## Error handling

Every external failure degrades gracefully:

- Doc creation or sharing fails → the local HTML file is still written; the step is `partial`;
  the Sheet simply omits the Doc-link row.
- The Sheet and PDF steps are unaffected by any `draft_export` failure.
- Nothing the new step does can break the existing pipeline.

## Testing

- `markdown_to_html`: assert the PDF context and the export use the same helper (parity).
- `build_draft_html`: pure-function tests — title `<h1>`, metadata header, body headings, and
  internal-link list all present; runs offline.
- `run_draft_export` with a **fake DocWriter** + a tmp job dir:
  - happy path → `.html` written + `doc_url` recorded;
  - Doc-failure path → `is_partial=True`, HTML kept, `error` set;
  - no-draft path → graceful `error`, no crash.
- `build_sheet_model`: updated test for the slimmed metadata tab + conditional Doc-link row.

## Dependencies

- Add `google-api-python-client` to `requirements.txt` (used only inside `GoogleDocWriter`).

## Affected files

- `compresearch/models.py` — new `DraftExportResult`, new `JobData.draft_export` field.
- `compresearch/render.py` — extract `markdown_to_html`.
- `compresearch/draft_export.py` — **new** module.
- `compresearch/orchestrator.py` — new pipeline step.
- `compresearch/cli.py` — new `draft-export` subcommand.
- `compresearch/sheets.py` — slim the draft tab + Doc link.
- `requirements.txt` — add `google-api-python-client`.
- `tests/` — new and updated tests as above.
