# Render Module (Branded PDF) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Render module to `compresearch` that turns a job's finished `data.json` into a branded TAG Online PDF report — cover, executive summary, competitive landscape (charts), content/sitemap findings, keyword findings & gaps, recommended topical map, the sample blog post, and prioritized next steps.

**Architecture:** A pure context builder turns `JobData` + a `Branding` config into a template view-model; a Jinja2 HTML/CSS template renders it; bar charts are generated as **inline SVG in Python** (deterministic, no JS/no async); Playwright (headless Chromium) renders the HTML to PDF. The Playwright call is isolated behind an injectable `html_to_pdf` seam, so context building, chart generation, and HTML rendering all test fully offline (the test suite needs no Chromium and no Playwright import). Mirrors the prior modules' conventions: a thin `run_render(job_dir, ...) -> JobData` orchestrator that loads the job, does the work, captures errors into a result `.error`, and persists `data.json`.

**Tech Stack:** Python 3.11+ (running on 3.14), pydantic v2, Jinja2, Python-Markdown, Playwright (headless Chromium, for real runs only), pytest. Builds on Plans 1–4 (merged to `master`). **Scope: PDF only** — the Google Sheet appendix is a separate follow-up plan.

---

## Context for the implementer

Already present in `compresearch` (do not recreate): `models.py` (full schema incl. `JobConfig`, `JobData`, and the `SitemapResult`/`KeywordResult`/`TopicalMapResult`/`DraftPostResult` sections), `settings.py`, `job_store.py` (`load_data`, `save_data`, `slugify`, `create_job`), `sitemap.py`, `keywords.py`, `topical_map.py`, `draft_post.py`, `cli.py` (subcommands `sitemap`, `keywords`, `topical-map`, `draft-post`; `run_from_args(argv, fetch=http_fetch, provider=None, generator=None, draft_generator=None) -> Path`). Shared pytest fixtures live in `tests/conftest.py`. 87 tests pass. Run tests with `.venv\Scripts\python -m pytest` (Windows). Work on a feature branch off `master`; commit per task with the messages given.

**Decisions (from brainstorming):**
- **Scope:** branded **PDF only** this plan; Google Sheet is a later plan.
- **Branding:** a swappable `Branding` config with clean professional defaults + a placeholder (text) logo; operators override later by editing `compresearch/branding.json`.
- **Charts:** inline SVG generated in Python (engineering refinement over a JS chart lib — deterministic, offline, no async render wait). Playwright is used only for HTML→PDF.

**Testability seam:** `run_render(job_dir, html_to_pdf=render_pdf, ...)`. `render_pdf` lazy-imports Playwright inside the function body, so importing `compresearch.render` never requires Playwright, and tests inject a fake `html_to_pdf` (captures the HTML, writes a stub file). The real Playwright path is the only un-unit-tested boundary (like `http_fetch` / the live LLM calls).

---

## File Structure

| File | Responsibility |
|------|----------------|
| `requirements.txt` (modify) | Add `jinja2`, `markdown`, `playwright` |
| `compresearch/models.py` (modify) | Add `Branding` and `RenderResult`; add `render` to `JobData` |
| `compresearch/branding.py` (create) | `load_branding()` — defaults + optional `branding.json` override |
| `compresearch/render.py` (create) | `_bar_chart_svg`, `_short_domain`, `build_report_context`, `render_report_html`, `render_pdf`, `run_render` |
| `compresearch/templates/report.html.j2` (create) | The branded Jinja2 report template |
| `compresearch/branding.example.json` (create) | Documented branding override example |
| `compresearch/cli.py` (modify) | Add a `render` subcommand |
| `tests/test_render.py` (create) | Chart SVG, context builder, HTML render, orchestration — all offline |
| `tests/test_cli.py` (modify) | End-to-end `render` run with a fake `html_to_pdf` |
| `README.md` (modify) | Document the render usage + branding override; mark the module complete |

---

## Task 1: Dependencies + Branding config

**Files:**
- Modify: `requirements.txt`
- Modify: `compresearch/models.py`
- Create: `compresearch/branding.py`
- Create: `compresearch/branding.example.json`
- Test: `tests/test_models.py`, `tests/test_render.py`

- [ ] **Step 1: Add dependencies**

Append `jinja2`, `markdown`, and `playwright` to `requirements.txt` (each on its own line). Install:

Run: `.venv\Scripts\python -m pip install jinja2 markdown playwright`
Expected: installs cleanly. Pin the resolved versions into `requirements.txt` (from `pip show`). If a latest release won't install on the installed Python, pin the newest that does (the lxml/pydantic adjustment from Plan 1).

Then attempt the Chromium download (needed only for real PDF runs, NOT for the test suite):

Run: `.venv\Scripts\python -m playwright install chromium`
This may be large/slow or blocked in some environments. If it fails, that's acceptable — note it in your report; the test suite injects a fake renderer and does not need Chromium.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_models.py`:

```python
def test_branding_defaults():
    from compresearch.models import Branding
    b = Branding()
    assert b.agency_name == "TAG Online"
    assert b.primary_color.startswith("#")
    assert b.logo_path is None
```

Create `tests/test_render.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_render.py tests/test_models.py -k "branding"`
Expected: FAIL — `ImportError` for `Branding` / `compresearch.branding`.

- [ ] **Step 4: Write the implementation**

Add to `compresearch/models.py` (near the other config models):

```python
class Branding(BaseModel):
    agency_name: str = "TAG Online"
    primary_color: str = "#16314F"   # deep navy (placeholder — override in branding.json)
    accent_color: str = "#E2703A"    # warm accent (placeholder)
    text_color: str = "#1F2933"
    muted_color: str = "#52606D"
    font_family: str = "Georgia, 'Times New Roman', serif"
    logo_path: str | None = None     # None -> the agency name is rendered as a text logo
```

Create `compresearch/branding.py`:

```python
# compresearch/branding.py
from __future__ import annotations

import json
from pathlib import Path

from compresearch.models import Branding

DEFAULT_BRANDING_PATH = Path(__file__).parent / "branding.json"


def load_branding(path: Path | None = None) -> Branding:
    """Load the branding config, merging an optional JSON override over the defaults.

    If `path` is None, looks for compresearch/branding.json; if that's absent, returns
    the built-in defaults. Unknown keys in the override are ignored by pydantic.
    """
    path = Path(path) if path is not None else DEFAULT_BRANDING_PATH
    if not path.exists():
        return Branding()
    override = json.loads(path.read_text(encoding="utf-8"))
    return Branding(**{**Branding().model_dump(), **override})
```

Create `compresearch/branding.example.json` (documented example operators copy to `branding.json`):

```json
{
  "agency_name": "TAG Online",
  "primary_color": "#16314F",
  "accent_color": "#E2703A",
  "text_color": "#1F2933",
  "muted_color": "#52606D",
  "font_family": "Georgia, 'Times New Roman', serif",
  "logo_path": "C:/path/to/tag-logo.png"
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_render.py tests/test_models.py -k branding`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt compresearch/models.py compresearch/branding.py compresearch/branding.example.json tests/test_models.py tests/test_render.py
git commit -m "feat: add branding config and render dependencies"
```

---

## Task 2: RenderResult model

**Files:**
- Modify: `compresearch/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
def test_render_result_and_jobdata_render():
    from compresearch.models import RenderResult, JobConfig, JobData
    r = RenderResult(pdf_path="jobs/acme-co/outputs/acme-co-competitive-research.pdf")
    restored = RenderResult.model_validate_json(r.model_dump_json())
    assert restored.pdf_path.endswith(".pdf")
    assert restored.error is None
    data = JobData(config=JobConfig(client_name="X", client_url="https://x.com"))
    assert data.render is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_models.py -k render_result`
Expected: FAIL — `ImportError: cannot import name 'RenderResult'`.

- [ ] **Step 3: Write the implementation**

Add to `compresearch/models.py` (after `DraftPostResult`):

```python
class RenderResult(BaseModel):
    pdf_path: str | None = None
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_models.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add compresearch/models.py tests/test_models.py
git commit -m "feat: add render result to schema"
```

---

## Task 3: Inline SVG bar chart helper

**Files:**
- Create: `compresearch/render.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_render.py -k "bar_chart or short_domain"`
Expected: FAIL — `ModuleNotFoundError: No module named 'compresearch.render'`.

- [ ] **Step 3: Write the implementation**

```python
# compresearch/render.py
from __future__ import annotations

from urllib.parse import urlparse
from xml.sax.saxutils import escape


def _short_domain(url: str) -> str:
    """Netloc without scheme or leading 'www.', for chart/table labels."""
    netloc = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    netloc = netloc[4:] if netloc.startswith("www.") else netloc
    return netloc or url


def _bar_chart_svg(
    labels: list[str],
    values: list[int],
    width: int = 560,
    height: int = 240,
    bar_color: str = "#E2703A",
    text_color: str = "#1F2933",
) -> str:
    """Render a simple vertical bar chart as a standalone, deterministic SVG string."""
    if not values:
        return ""
    max_val = max(values) or 1
    count = len(values)
    pad = 40
    chart_h = height - 2 * pad
    chart_w = width - 2 * pad
    gap = 16
    bar_w = (chart_w - gap * (count - 1)) / count if count else 0
    parts: list[str] = []
    for index, (label, value) in enumerate(zip(labels, values)):
        bar_h = (value / max_val) * chart_h
        x = pad + index * (bar_w + gap)
        y = pad + (chart_h - bar_h)
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
            f'fill="{bar_color}" rx="3"/>'
        )
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
            f'font-size="12" fill="{text_color}">{value}</text>'
        )
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{height - pad + 16:.1f}" text-anchor="middle" '
            f'font-size="11" fill="{text_color}">{escape(label)}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'width="100%" role="img">{"".join(parts)}</svg>'
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_render.py -k "bar_chart or short_domain"`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/render.py tests/test_render.py
git commit -m "feat: add inline SVG bar chart helper for reports"
```

---

## Task 4: Report context builder

**Files:**
- Modify: `compresearch/render.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_render.py -k build_report_context`
Expected: FAIL — `ImportError: cannot import name 'build_report_context'`.

- [ ] **Step 3: Write the implementation**

Add the imports to the top of `compresearch/render.py`:

```python
import markdown

from compresearch.models import Branding, JobData
```

Append:

```python
def build_report_context(data: JobData, branding: Branding, report_date: str | None = None) -> dict:
    """Turn a finished JobData + branding into a template view-model. Pure; tolerates
    any missing analysis section."""
    config = data.config

    # --- sitemap ---
    sitemap_domains: list[dict] = []
    client_total = 0
    sitemap_gaps: list[dict] = []
    if data.sitemap is not None:
        if data.sitemap.client is not None:
            client_total = data.sitemap.client.total_urls
            sitemap_domains.append({
                "domain": _short_domain(data.sitemap.client.domain),
                "total": data.sitemap.client.total_urls,
                "posts_per_month": data.sitemap.client.posts_per_month,
            })
        for comp in data.sitemap.competitors:
            sitemap_domains.append({
                "domain": _short_domain(comp.domain),
                "total": comp.total_urls,
                "posts_per_month": comp.posts_per_month,
            })
        sitemap_gaps = [
            {"section": g.section, "competitors": [_short_domain(d) for d in g.competitors_with]}
            for g in data.sitemap.gaps
        ]

    # --- keywords ---
    keyword_gaps: list[dict] = []
    quick_wins: list[dict] = []
    keyword_domains: list[dict] = []
    if data.keywords is not None:
        keyword_gaps = [
            {"keyword": g.keyword, "volume": g.search_volume, "difficulty": g.difficulty,
             "traffic_value": g.traffic_value, "best_position": g.best_competitor_position,
             "competitors": [_short_domain(d) for d in g.competitors_ranking]}
            for g in data.keywords.gaps[:15]
        ]
        quick_wins = [
            {"keyword": w.keyword, "position": w.position, "volume": w.search_volume,
             "traffic_value": w.traffic_value, "url": w.url}
            for w in data.keywords.quick_wins[:10]
        ]
        if data.keywords.client is not None:
            keyword_domains.append({"domain": _short_domain(data.keywords.client.domain),
                                    "total": data.keywords.client.total_keywords})
        for comp in data.keywords.competitors:
            keyword_domains.append({"domain": _short_domain(comp.domain),
                                    "total": comp.total_keywords})

    # --- topical map ---
    pillars = []
    topical_summary = None
    if data.topical_map is not None and data.topical_map.map is not None:
        pillars = data.topical_map.map.pillars
        topical_summary = data.topical_map.map.summary

    # --- draft ---
    draft = None
    if data.draft_post is not None and data.draft_post.post is not None:
        post = data.draft_post.post
        draft = {
            "title": post.title,
            "title_tag": post.title_tag,
            "meta_description": post.meta_description,
            "body_html": markdown.markdown(post.body_markdown, extensions=["extra", "sane_lists"]),
            "internal_links": [{"anchor": l.anchor, "url": l.url} for l in post.internal_links],
        }

    # --- charts ---
    content_volume_svg = _bar_chart_svg(
        [d["domain"] for d in sitemap_domains], [d["total"] for d in sitemap_domains],
        bar_color=branding.accent_color, text_color=branding.text_color,
    )
    keyword_counts_svg = _bar_chart_svg(
        [d["domain"] for d in keyword_domains], [d["total"] for d in keyword_domains],
        bar_color=branding.primary_color, text_color=branding.text_color,
    )

    is_partial = bool(
        (data.sitemap and data.sitemap.is_partial)
        or (data.keywords and data.keywords.is_partial)
    )

    return {
        "branding": branding,
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
        "sitemap": {"client_total": client_total, "domains": sitemap_domains, "gaps": sitemap_gaps},
        "keywords": {"gaps": keyword_gaps, "quick_wins": quick_wins},
        "topical_map": {"pillars": pillars, "summary": topical_summary},
        "draft": draft,
        "charts": {"content_volume_svg": content_volume_svg, "keyword_counts_svg": keyword_counts_svg},
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_render.py -k build_report_context`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/render.py tests/test_render.py
git commit -m "feat: build report context from job data"
```

---

## Task 5: Jinja2 template + HTML rendering

**Files:**
- Create: `compresearch/templates/report.html.j2`
- Modify: `compresearch/render.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_render.py -k render_report_html`
Expected: FAIL — `ImportError: cannot import name 'render_report_html'`.

- [ ] **Step 3: Write the template**

Create `compresearch/templates/report.html.j2`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  :root {
    --primary: {{ branding.primary_color }};
    --accent: {{ branding.accent_color }};
    --text: {{ branding.text_color }};
    --muted: {{ branding.muted_color }};
  }
  * { box-sizing: border-box; }
  body { font-family: {{ branding.font_family }}; color: var(--text); margin: 0; font-size: 12pt; line-height: 1.5; }
  .page { padding: 48px 56px; page-break-after: always; }
  .page:last-child { page-break-after: auto; }
  h1, h2, h3 { color: var(--primary); margin: 0 0 12px; }
  h1 { font-size: 30pt; }
  h2 { font-size: 19pt; border-bottom: 3px solid var(--accent); padding-bottom: 6px; margin-top: 4px; }
  h3 { font-size: 14pt; color: var(--accent); }
  .cover { display: flex; flex-direction: column; justify-content: center; min-height: 80vh; }
  .logo { font-size: 16pt; font-weight: bold; color: var(--accent); letter-spacing: 1px; text-transform: uppercase; }
  .cover h1 { margin-top: 24px; }
  .cover .sub { color: var(--muted); font-size: 14pt; }
  .stat-grid { display: flex; gap: 16px; flex-wrap: wrap; margin: 16px 0; }
  .stat { flex: 1; min-width: 130px; border: 1px solid #E4E7EB; border-top: 4px solid var(--accent); border-radius: 6px; padding: 14px 16px; }
  .stat .n { font-size: 26pt; color: var(--primary); font-weight: bold; }
  .stat .l { color: var(--muted); font-size: 10.5pt; }
  table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 10.5pt; }
  th { background: var(--primary); color: #fff; text-align: left; padding: 8px 10px; }
  td { padding: 7px 10px; border-bottom: 1px solid #E4E7EB; }
  tr:nth-child(even) td { background: #F5F7FA; }
  .chart { margin: 16px 0; }
  .muted { color: var(--muted); }
  .pill { display: inline-block; background: #F0F2F5; border-radius: 12px; padding: 2px 10px; margin: 2px; font-size: 9.5pt; }
  .draft { border: 1px solid #E4E7EB; border-radius: 8px; padding: 20px 24px; background: #FCFCFD; }
  .draft .meta { color: var(--muted); font-size: 10pt; margin-bottom: 12px; }
  .partial-note { background: #FFF4E5; border-left: 4px solid var(--accent); padding: 10px 14px; font-size: 10pt; margin: 12px 0; }
  ul.links { padding-left: 18px; }
</style>
</head>
<body>

<section class="page cover">
  {% if branding.logo_path %}<img class="logo-img" src="file:///{{ branding.logo_path }}" alt="{{ branding.agency_name }}" style="max-height:64px;">{% else %}<div class="logo">{{ branding.agency_name }}</div>{% endif %}
  <h1>Competitive Research &amp; Analysis</h1>
  <div class="sub">Prepared for <strong>{{ client_name }}</strong> &middot; {{ client_url }}</div>
  {% if report_date %}<div class="sub">{{ report_date }}</div>{% endif %}
</section>

<section class="page">
  <h2>Executive Summary</h2>
  {% if summary.is_partial %}<div class="partial-note">Some data could not be fully retrieved; figures below reflect the data we were able to collect.</div>{% endif %}
  <div class="stat-grid">
    <div class="stat"><div class="n">{{ summary.competitor_count }}</div><div class="l">Competitors analyzed</div></div>
    <div class="stat"><div class="n">{{ summary.content_gap_count }}</div><div class="l">Content gaps found</div></div>
    <div class="stat"><div class="n">{{ summary.keyword_gap_count }}</div><div class="l">Keyword gaps</div></div>
    <div class="stat"><div class="n">{{ summary.quick_win_count }}</div><div class="l">Quick wins</div></div>
  </div>
  <p>This report compares <strong>{{ client_name }}</strong> against {{ summary.competitor_count }} competitor(s) across site content, keyword rankings, and content-strategy opportunities, and includes a sample blog post demonstrating recommended content quality.</p>
</section>

<section class="page">
  <h2>Competitive Landscape</h2>
  {% if charts.content_volume_svg %}<h3>Total indexed pages by site</h3><div class="chart">{{ charts.content_volume_svg | safe }}</div>{% endif %}
  {% if charts.keyword_counts_svg %}<h3>Ranking keywords by site</h3><div class="chart">{{ charts.keyword_counts_svg | safe }}</div>{% endif %}
</section>

<section class="page">
  <h2>Content &amp; Sitemap Findings</h2>
  {% if sitemap.domains %}
  <table>
    <tr><th>Site</th><th>Total pages</th><th>Est. posts / month</th></tr>
    {% for d in sitemap.domains %}<tr><td>{{ d.domain }}</td><td>{{ d.total }}</td><td>{% if d.posts_per_month is not none %}{{ d.posts_per_month }}{% else %}&mdash;{% endif %}</td></tr>{% endfor %}
  </table>
  {% endif %}
  {% if sitemap.gaps %}
  <h3>Content-type gaps</h3>
  <p class="muted">Sections competitors publish that {{ client_name }} does not:</p>
  {% for g in sitemap.gaps %}<span class="pill">{{ g.section }} &middot; {{ g.competitors | join(', ') }}</span>{% endfor %}
  {% else %}<p class="muted">No major content-type gaps detected.</p>{% endif %}
</section>

<section class="page">
  <h2>Keyword Findings &amp; Gaps</h2>
  {% if keywords.gaps %}
  <h3>Top keyword gaps</h3>
  <table>
    <tr><th>Keyword</th><th>Volume</th><th>Difficulty</th><th>Best competitor rank</th><th>Est. value</th></tr>
    {% for k in keywords.gaps %}<tr><td>{{ k.keyword }}</td><td>{% if k.volume is not none %}{{ k.volume }}{% else %}&mdash;{% endif %}</td><td>{% if k.difficulty is not none %}{{ k.difficulty }}{% else %}&mdash;{% endif %}</td><td>{% if k.best_position is not none %}#{{ k.best_position }}{% else %}&mdash;{% endif %}</td><td>{% if k.traffic_value is not none %}{{ k.traffic_value }}{% else %}&mdash;{% endif %}</td></tr>{% endfor %}
  </table>
  {% else %}<p class="muted">No keyword gap data available.</p>{% endif %}
  {% if keywords.quick_wins %}
  <h3>Quick wins (already ranking, positions 5&ndash;20)</h3>
  <table>
    <tr><th>Keyword</th><th>Current rank</th><th>Volume</th></tr>
    {% for w in keywords.quick_wins %}<tr><td>{{ w.keyword }}</td><td>#{{ w.position }}</td><td>{% if w.volume is not none %}{{ w.volume }}{% else %}&mdash;{% endif %}</td></tr>{% endfor %}
  </table>
  {% endif %}
</section>

<section class="page">
  <h2>Recommended Topical Map</h2>
  {% if topical_map.summary %}<p>{{ topical_map.summary }}</p>{% endif %}
  {% for pillar in topical_map.pillars %}
  <h3>{{ pillar.name }}</h3>
  {% if pillar.description %}<p class="muted">{{ pillar.description }}</p>{% endif %}
  {% for cluster in pillar.clusters %}
  <p><strong>{{ cluster.name }}</strong></p>
  <ul>{% for a in cluster.articles %}<li>{{ a.title }}{% if a.target_keyword %} <span class="muted">&mdash; target: {{ a.target_keyword }}{% if a.estimated_volume is not none %}, ~{{ a.estimated_volume }}/mo{% endif %}</span>{% endif %}</li>{% endfor %}</ul>
  {% endfor %}
  {% else %}<p class="muted">No topical map was generated.</p>{% endfor %}
</section>

{% if draft %}
<section class="page">
  <h2>Sample Blog Post</h2>
  <div class="draft">
    {% if draft.meta_description %}<div class="meta"><strong>Meta description:</strong> {{ draft.meta_description }}</div>{% endif %}
    {{ draft.body_html | safe }}
    {% if draft.internal_links %}
    <h3>Suggested internal links</h3>
    <ul class="links">{% for l in draft.internal_links %}<li>{{ l.anchor }} &rarr; {{ l.url }}</li>{% endfor %}</ul>
    {% endif %}
  </div>
</section>
{% endif %}

<section class="page">
  <h2>Recommended Next Steps</h2>
  <ol>
    <li>Close the highest-value keyword gaps with new, targeted content.</li>
    <li>Prioritize the quick-win keywords already ranking on pages 1&ndash;2.</li>
    <li>Build out the recommended topical map, starting with the highest-opportunity pillars.</li>
    <li>Match the voice and quality of the sample blog post across the content program.</li>
  </ol>
  <p class="muted">Prepared by {{ branding.agency_name }}.</p>
</section>

</body>
</html>
```

- [ ] **Step 4: Write the `render_report_html` implementation**

Add to the top imports of `compresearch/render.py`:

```python
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).parent / "templates"
```

Append:

```python
def render_report_html(context: dict, templates_dir: Path = TEMPLATES_DIR) -> str:
    """Render the branded report HTML from the context view-model."""
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    return env.get_template("report.html.j2").render(**context)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_render.py -k render_report_html`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add compresearch/templates/report.html.j2 compresearch/render.py tests/test_render.py
git commit -m "feat: add branded report template and HTML rendering"
```

---

## Task 6: `render_pdf` (Playwright) + `run_render` orchestration

**Files:**
- Modify: `compresearch/render.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_render.py -k run_render`
Expected: FAIL — `ImportError: cannot import name 'run_render'`.

- [ ] **Step 3: Write the implementation**

Add to the top imports of `compresearch/render.py`:

```python
import logging

from compresearch.job_store import load_data, save_data, slugify
from compresearch.models import JobData, RenderResult
from compresearch.branding import load_branding
```

Append:

```python
def render_pdf(html: str, output_path: Path) -> None:
    """Render HTML to a PDF file via headless Chromium. Playwright is imported lazily so
    the module (and the test suite) does not require it to be installed."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(
                path=str(output_path),
                format="A4",
                print_background=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )
        finally:
            browser.close()


def run_render(job_dir, html_to_pdf=render_pdf, branding=None, report_date: str | None = None) -> JobData:
    """Render a job's branded PDF report and record the output path in data.json."""
    data = load_data(job_dir)
    branding = branding or load_branding()
    slug = slugify(data.config.client_name)
    output_path = Path(job_dir) / "outputs" / f"{slug}-competitive-research.pdf"
    try:
        context = build_report_context(data, branding, report_date=report_date)
        html = render_report_html(context)
        html_to_pdf(html, output_path)
        data.render = RenderResult(pdf_path=str(output_path))
    except Exception as exc:
        logging.warning("PDF render failed for %s: %s", data.config.client_url, exc)
        data.render = RenderResult(error=str(exc))
    save_data(job_dir, data)
    return data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_render.py -k run_render`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python -m pytest`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add compresearch/render.py tests/test_render.py
git commit -m "feat: add Playwright PDF renderer and run_render orchestration"
```

---

## Task 7: CLI `render` subcommand

**Files:**
- Modify: `compresearch/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py` (imports at the top of the file already cover most of this; add `from compresearch.render` import as needed):

```python
def test_render_subcommand(tmp_path):
    from compresearch.models import SitemapResult, DomainSitemap
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = load_data(job_dir)
    data.sitemap = SitemapResult(client=DomainSitemap(domain="https://acme.com",
                                                      section_counts={"blog": 5}, total_urls=5))
    save_data(job_dir, data)

    captured = {}

    def fake_html_to_pdf(html, output_path):
        captured["html"] = html
        from pathlib import Path as _P
        _P(output_path).write_text("PDF", encoding="utf-8")

    returned = run_from_args(["render", "--job-dir", str(job_dir)], html_to_pdf=fake_html_to_pdf)
    assert returned == job_dir
    data = load_data(returned)
    assert data.render.pdf_path.endswith(".pdf")
    assert "Acme Co" in captured["html"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py -k render`
Expected: FAIL — `run_from_args` has no `html_to_pdf` parameter, or argparse rejects `render`.

- [ ] **Step 3: Write the implementation**

In `compresearch/cli.py`:

1. Add the import: `from compresearch.render import run_render, render_pdf`.
2. Add an `html_to_pdf=render_pdf` parameter to `run_from_args` (after `draft_generator`):

```python
def run_from_args(
    argv: list[str],
    fetch: Fetcher = http_fetch,
    provider=None,
    generator: Generator | None = None,
    draft_generator: DraftGenerator | None = None,
    html_to_pdf=render_pdf,
) -> Path:
```

3. Add the subparser (after the `draft-post` subparser):

```python
    rn = sub.add_parser("render", help="Render the branded PDF report for an existing job")
    rn.add_argument("--job-dir", required=True)
```

4. Add the dispatch branch (after the `draft-post` branch, before the final `raise`):

```python
    if args.command == "render":
        job_dir = Path(args.job_dir)
        try:
            run_render(job_dir, html_to_pdf=html_to_pdf)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        return job_dir
```

(Note: `run_render` already captures rendering errors into `RenderResult.error` and does not raise for them; the try/except here is for consistency with the other branches and to catch unexpected load/IO errors.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py`
Expected: PASS (all existing CLI tests plus the new render test).

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python -m pytest`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add compresearch/cli.py tests/test_cli.py
git commit -m "feat: add render CLI subcommand"
```

---

## Task 8: Docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the README**

Add a section after the draft-post section and flip the status checklist line. Add:

```markdown
## Render the branded PDF report

The render module turns a job's finished `data.json` into a branded TAG Online PDF report.
It works with whatever analysis sections are present (run sitemap/keywords/topical-map/draft-post first for a complete report).

**One-time setup for real PDF output** (the test suite does not need this):

```
.venv\Scripts\python -m playwright install chromium
```

**Generate the report:**

```
.venv\Scripts\python -m compresearch.cli render --job-dir jobs\acme-co
```

The PDF is written to `jobs\<slug>\outputs\<slug>-competitive-research.pdf` and its path is
recorded in `data.json` under `render`.

**Branding:** copy `compresearch\branding.example.json` to `compresearch\branding.json` and
edit the colors, fonts, and `logo_path` to your real TAG Online assets. Without it, the report
uses clean built-in defaults and a text logo.
```

Change the render status line:

```markdown
- [x] Render module (branded PDF) — Google Sheet appendix pending
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document render module usage and branding override"
```

---

## Self-Review Notes

- **Spec coverage:** Branded PDF report with all the spec's sections — cover, executive summary, competitive landscape (charts), content/sitemap findings, keyword findings & gaps, recommended topical map, sample blog post, next steps (Task 5). Auto-generated charts (Task 3) — implemented as deterministic inline SVG rather than a JS lib (a documented refinement; Playwright still does HTML→PDF). Branding lives in a versioned, swappable config with defaults (Task 1). Output persisted under `render` (Tasks 2, 6). The Google Sheet appendix is intentionally deferred to a follow-up plan (the brainstorming scope decision).
- **Placeholder scan:** No TBDs; every code/test step is complete. `branding.example.json` is an example, not a placeholder in the code sense.
- **Type/name consistency:** `Branding`, `RenderResult`, `load_branding`, `_short_domain`, `_bar_chart_svg`, `build_report_context`, `render_report_html`, `render_pdf`, `run_render`, `TEMPLATES_DIR` used consistently across tasks/tests. `run_from_args` gains `html_to_pdf` (default `render_pdf`), used only by the `render` branch. `run_render` signature matches the other `run_*(job_dir, ...) -> JobData` orchestrators for the Plan 6 orchestrator.
- **Offline testing:** the Playwright path is isolated in `render_pdf` (lazy import); all tests inject a fake `html_to_pdf` and never import Playwright or launch Chromium. Context building, chart SVG, markdown rendering, and HTML templating are all verified offline.
- **Known follow-ups:** the live Playwright `render_pdf` is exercised only against a real Chromium (offline tests inject a fake) — verify a real PDF renders once Chromium is installed; visual/branding polish (real logo + brand hex) is an operator config edit, not code. **Next plan: Render (Google Sheet)** — `gspread`/Google service-account `Sheets` tabs (Overview / Sitemap / Keyword gaps / Quick wins / Topical map / Draft post) from the same `data.json`. **Then Plan 6: Orchestrator + Claude Code skill** chaining `run_sitemap → run_keywords → run_topical_map → run_draft_post → run_render` with per-job cost logging.
```
