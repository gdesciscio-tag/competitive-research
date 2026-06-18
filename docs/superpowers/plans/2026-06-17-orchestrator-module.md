# Orchestrator + Claude Code Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-command orchestrator that chains all six modules (sitemap → keywords → topical map → draft post → branded PDF → Google Sheet) for a single client, with per-step pass/fail status, duration, and real per-job Claude API cost logging — plus a `run-job` CLI subcommand and a Claude Code project skill so a non-technical operator runs a full competitive-research job in one command.

**Architecture:** A resilient `run_job(job_dir, ...) -> JobData` runs each module's existing `run_*` in order. Each step is isolated: a credential error or a captured section error is recorded as a failed `StepResult` and the pipeline continues, so the job produces whatever deliverables it can. Claude token usage is captured on the two LLM generators (`last_usage`) and converted to USD via a price table; the per-step report (status/error/duration/cost) is persisted under `data.run_report`. All module seams remain injectable, so the whole pipeline tests offline. This is the last plan; it also folds in two deferred review findings: a clear per-step summary, and relocating `short_domain` to a shared util.

**Tech Stack:** Python 3.11+ (running on 3.14), pydantic v2, pytest. Builds on Plans 1–5b (merged to `master`). No new dependencies.

---

## Context for the implementer

Already present in `compresearch` (merged to master): full `models.py` schema; the six modules with their orchestrators — `sitemap.run_sitemap(job_dir, fetch=http_fetch)`, `keywords.run_keywords(job_dir, provider=None)`, `topical_map.run_topical_map(job_dir, generator=None)` + `ClaudeTopicalMapGenerator`, `draft_post.run_draft_post(job_dir, generator=None, fetch=http_fetch, preferred_keyword=None)` + `ClaudeDraftPostGenerator`, `render.run_render(job_dir, html_to_pdf=render_pdf, ...)` + `render._short_domain`, `sheets.run_sheet(job_dir, writer=None)`; `job_store` (`create_job`, `load_data`, `save_data`, `slugify`); `cli.run_from_args(argv, fetch=http_fetch, provider=None, generator=None, draft_generator=None, html_to_pdf=render_pdf, sheet_writer=None) -> Path`. Shared pytest fixtures in `tests/conftest.py`. 115 tests pass. Run tests with `.venv\Scripts\python -m pytest` (Windows). Work on a feature branch off `master`; commit per task with the messages given.

**Design decisions:**
- **Resilient:** a failed step (missing credentials, captured section error, or unexpected exception) is recorded and the pipeline continues. Partial deliverables are fine.
- **Cost:** real Claude token usage (input/output) × a per-model price table; DataForSEO/keyword cost is not tracked in v1 (documented follow-up). `total_cost_usd` reflects LLM spend.
- **Operator entry:** a `run-job` CLI subcommand and a `.claude/skills/competitive-research/SKILL.md` project skill.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `compresearch/utils.py` (create) | `short_domain` (moved from `render._short_domain`, made public) |
| `compresearch/render.py` (modify) | Import `short_domain` from utils (drop the local `_short_domain`) |
| `compresearch/sheets.py` (modify) | Import `short_domain` from utils |
| `compresearch/costs.py` (create) | Price table + `estimate_cost(model, input_tokens, output_tokens)` |
| `compresearch/topical_map.py` (modify) | Capture `last_usage` on `ClaudeTopicalMapGenerator` |
| `compresearch/draft_post.py` (modify) | Capture `last_usage` on `ClaudeDraftPostGenerator` |
| `compresearch/models.py` (modify) | Add `StepResult`, `RunReport`; add `run_report` to `JobData` |
| `compresearch/orchestrator.py` (create) | `run_job` |
| `compresearch/cli.py` (modify) | Add a `run-job` subcommand + summary printout |
| `.claude/skills/competitive-research/SKILL.md` (create) | Operator-facing project skill |
| `tests/test_utils.py`, `tests/test_costs.py`, `tests/test_orchestrator.py` (create); `tests/test_topical_map.py`, `tests/test_draft_post.py`, `tests/test_models.py`, `tests/test_cli.py`, `tests/test_render.py` (modify) | Tests |
| `README.md` (modify) | Document the full-job command + the skill; mark the project complete |

---

## Task 1: Relocate `short_domain` to a shared util

**Files:**
- Create: `compresearch/utils.py`
- Modify: `compresearch/render.py`, `compresearch/sheets.py`, `tests/test_render.py`
- Test: `tests/test_utils.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_utils.py`:

```python
# tests/test_utils.py
from compresearch.utils import short_domain


def test_short_domain_strips_scheme_and_www():
    assert short_domain("https://www.acme.com/blog") == "acme.com"
    assert short_domain("rival.com") == "rival.com"
    assert short_domain("http://sub.acme.co.uk/x") == "sub.acme.co.uk"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_utils.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'compresearch.utils'`.

- [ ] **Step 3: Write the implementation and rewire imports**

Create `compresearch/utils.py` (move the body of `render._short_domain` here, public name):

```python
# compresearch/utils.py
from __future__ import annotations

from urllib.parse import urlparse


def short_domain(url: str) -> str:
    """Netloc without scheme or leading 'www.', for labels and tables."""
    netloc = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    netloc = netloc[4:] if netloc.startswith("www.") else netloc
    return netloc or url
```

In `compresearch/render.py`: delete the local `_short_domain` definition; add `from compresearch.utils import short_domain` to the imports; replace every `_short_domain(` call with `short_domain(`.

In `compresearch/sheets.py`: change `from compresearch.render import _short_domain` to `from compresearch.utils import short_domain`; replace every `_short_domain(` call with `short_domain(`.

In `tests/test_render.py`: the `test_short_domain` test and the `_short_domain` import reference the old name. Change the import from `from compresearch.render import _bar_chart_svg, _short_domain` to `from compresearch.render import _bar_chart_svg` plus `from compresearch.utils import short_domain`, and update the `test_short_domain` body to call `short_domain`. (If `_short_domain` is referenced elsewhere in `test_render.py`, update those too.)

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `.venv\Scripts\python -m pytest`
Expected: all green (the move is behavior-preserving).

- [ ] **Step 5: Commit**

```bash
git add compresearch/utils.py compresearch/render.py compresearch/sheets.py tests/test_utils.py tests/test_render.py
git commit -m "refactor: move short_domain to shared utils module"
```

---

## Task 2: Cost estimation

**Files:**
- Create: `compresearch/costs.py`
- Test: `tests/test_costs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_costs.py`:

```python
# tests/test_costs.py
from compresearch.costs import estimate_cost


def test_estimate_cost_opus():
    # opus 4.8: $5 / 1M input, $25 / 1M output
    # 1,000,000 input + 1,000,000 output = 5 + 25 = 30.0
    assert estimate_cost("claude-opus-4-8", 1_000_000, 1_000_000) == 30.0


def test_estimate_cost_sonnet_partial():
    # sonnet 4.6: $3 / 1M input, $15 / 1M output
    # 200k input + 100k output = 0.6 + 1.5 = 2.1
    assert estimate_cost("claude-sonnet-4-6", 200_000, 100_000) == 2.1


def test_estimate_cost_unknown_model_is_none():
    assert estimate_cost("some-other-model", 1000, 1000) is None


def test_estimate_cost_zero_tokens():
    assert estimate_cost("claude-opus-4-8", 0, 0) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_costs.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'compresearch.costs'`.

- [ ] **Step 3: Write the implementation**

```python
# compresearch/costs.py
from __future__ import annotations

# USD per 1,000,000 tokens: (input, output). Source: Claude API pricing.
PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5": (10.0, 50.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimate the USD cost of a Claude call. None for an unknown model."""
    rates = PRICE_PER_MTOK.get(model)
    if rates is None:
        return None
    input_rate, output_rate = rates
    cost = (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate
    return round(cost, 4)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_costs.py`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/costs.py tests/test_costs.py
git commit -m "feat: add Claude API cost estimation"
```

---

## Task 3: Capture token usage on the Claude generators

**Files:**
- Modify: `compresearch/topical_map.py`, `compresearch/draft_post.py`
- Test: `tests/test_topical_map.py`, `tests/test_draft_post.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_topical_map.py`:

```python
def test_generator_records_last_usage():
    from compresearch.topical_map import ClaudeTopicalMapGenerator
    from compresearch.models import TopicalMap

    class _Usage:
        input_tokens = 1200
        output_tokens = 800

    class _Resp:
        parsed_output = TopicalMap(pillars=[])
        usage = _Usage()

    class _Messages:
        def parse(self, **kwargs):
            return _Resp()

    class _Client:
        messages = _Messages()

    gen = ClaudeTopicalMapGenerator(client=_Client())
    assert gen.last_usage is None          # nothing recorded before the first call
    gen("prompt")
    assert gen.last_usage == {"input_tokens": 1200, "output_tokens": 800}
```

Append to `tests/test_draft_post.py`:

```python
def test_draft_generator_records_last_usage():
    from compresearch.draft_post import ClaudeDraftPostGenerator
    from compresearch.models import DraftPost

    class _Usage:
        input_tokens = 500
        output_tokens = 2500

    class _Resp:
        parsed_output = DraftPost(title="t", body_markdown="b")
        usage = _Usage()

    class _Messages:
        def parse(self, **kwargs):
            return _Resp()

    class _Client:
        messages = _Messages()

    gen = ClaudeDraftPostGenerator(client=_Client())
    assert gen.last_usage is None
    gen("prompt")
    assert gen.last_usage == {"input_tokens": 500, "output_tokens": 2500}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_topical_map.py tests/test_draft_post.py -k last_usage`
Expected: FAIL — `AttributeError: 'ClaudeTopicalMapGenerator' object has no attribute 'last_usage'`.

- [ ] **Step 3: Write the implementation**

In `compresearch/topical_map.py`, `ClaudeTopicalMapGenerator.__init__`, add at the end:

```python
        self.last_usage: dict | None = None
```

In `ClaudeTopicalMapGenerator.__call__`, after getting `response` and before/around the `parsed_output` handling, record usage:

```python
    def __call__(self, prompt: str) -> TopicalMap:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
            output_format=TopicalMap,
        )
        usage = getattr(response, "usage", None)
        self.last_usage = (
            {
                "input_tokens": getattr(usage, "input_tokens", 0) or 0,
                "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            }
            if usage is not None
            else None
        )
        topical_map = response.parsed_output
        if topical_map is None:
            raise RuntimeError(
                f"Claude returned no structured output (stop_reason="
                f"{getattr(response, 'stop_reason', None)!r})"
            )
        return topical_map
```

Apply the identical pattern to `compresearch/draft_post.py` `ClaudeDraftPostGenerator`: add `self.last_usage: dict | None = None` at the end of `__init__`, and record `self.last_usage` from `response.usage` in `__call__` (using `output_format=DraftPost` and the existing `parsed_output` None-guard).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_topical_map.py tests/test_draft_post.py -k last_usage`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full suite + commit**

Run: `.venv\Scripts\python -m pytest`
Expected: all green.

```bash
git add compresearch/topical_map.py compresearch/draft_post.py tests/test_topical_map.py tests/test_draft_post.py
git commit -m "feat: capture Claude token usage on the generators"
```

---

## Task 4: StepResult + RunReport models

**Files:**
- Modify: `compresearch/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
def test_run_report_and_jobdata_run_report():
    from compresearch.models import StepResult, RunReport, JobConfig, JobData
    report = RunReport(
        steps=[
            StepResult(name="sitemap", status="ok", duration_seconds=1.2),
            StepResult(name="topical_map", status="ok", duration_seconds=8.0, cost_usd=0.03),
            StepResult(name="sheet", status="failed", error="quota", duration_seconds=0.5),
        ],
        total_cost_usd=0.03,
    )
    restored = RunReport.model_validate_json(report.model_dump_json())
    assert restored.steps[1].cost_usd == 0.03
    assert restored.steps[2].status == "failed"
    assert restored.total_cost_usd == 0.03
    data = JobData(config=JobConfig(client_name="X", client_url="https://x.com"))
    assert data.run_report is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_models.py -k run_report`
Expected: FAIL — `ImportError: cannot import name 'StepResult'`.

- [ ] **Step 3: Write the implementation**

Add to `compresearch/models.py` (after `SheetResult`):

```python
class StepResult(BaseModel):
    name: str
    status: str  # "ok" | "failed" | "skipped"
    error: str | None = None
    duration_seconds: float | None = None
    cost_usd: float | None = None


class RunReport(BaseModel):
    steps: list[StepResult] = Field(default_factory=list)
    total_cost_usd: float = 0.0
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
    run_report: RunReport | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_models.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add compresearch/models.py tests/test_models.py
git commit -m "feat: add run report to schema"
```

---

## Task 5: The orchestrator (`run_job`)

**Files:**
- Create: `compresearch/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_orchestrator.py`:

```python
# tests/test_orchestrator.py
from compresearch.orchestrator import run_job
from compresearch.job_store import create_job, load_data
from compresearch.models import (
    JobConfig, TopicalMap, PillarTopic, TopicCluster, ArticleIdea,
    DraftPost, KeywordEntry,
)


def _sitemap_fetch():
    """Fake fetcher for client + one competitor."""
    urlset = (
        b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://acme.com/blog/a</loc></url></urlset>"
    )
    rival = (
        b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://rival.com/blog/a</loc></url>"
        b"<url><loc>https://rival.com/case-studies/x</loc></url></urlset>"
    )
    pages = {
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": urlset,
        "https://rival.com/robots.txt": b"Sitemap: https://rival.com/sitemap.xml\n",
        "https://rival.com/sitemap.xml": rival,
    }

    def fetch(url):
        if url not in pages:
            raise FileNotFoundError(url)
        return pages[url]
    return fetch


def _keyword_provider():
    data = {
        "acme.com": [KeywordEntry(keyword="crm", search_volume=1000, position=8)],
        "rival.com": [KeywordEntry(keyword="free crm", search_volume=800, position=4)],
    }

    def provider(domain):
        from compresearch.keywords import _domain_key
        key = _domain_key(domain)
        if key not in data:
            raise RuntimeError(f"no data for {key}")
        return data[key]
    return provider


def _topical_generator():
    class Gen:
        model = "claude-sonnet-4-6"
        last_usage = {"input_tokens": 1000, "output_tokens": 1000}

        def __call__(self, prompt):
            return TopicalMap(pillars=[PillarTopic(name="P", clusters=[TopicCluster(
                name="C", articles=[ArticleIdea(title="What is a CRM?", target_keyword="free crm",
                                                estimated_volume=800)])])])
    return Gen()


def _draft_generator():
    class Gen:
        model = "claude-opus-4-8"
        last_usage = {"input_tokens": 500, "output_tokens": 2000}

        def __call__(self, prompt):
            return DraftPost(title="What is a CRM?", body_markdown="# Hi\n\nBody.")
    return Gen()


def _full_run(job_dir):
    captured = {}

    def html_to_pdf(html, output_path):
        captured["html"] = html
        from pathlib import Path
        Path(output_path).write_text("PDF", encoding="utf-8")

    def sheet_writer(title, tabs):
        captured["sheet_title"] = title
        return "https://docs.google.com/spreadsheets/d/FAKE"

    data = run_job(
        job_dir,
        fetch=_sitemap_fetch(),
        keyword_provider=_keyword_provider(),
        topical_generator=_topical_generator(),
        draft_generator=_draft_generator(),
        html_to_pdf=html_to_pdf,
        sheet_writer=sheet_writer,
    )
    return data, captured


def test_run_job_runs_all_six_steps_offline(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    competitor_urls=["https://rival.com"],
                    business_description="Acme sells CRM software")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data, captured = _full_run(job_dir)

    report = data.run_report
    assert [s.name for s in report.steps] == [
        "sitemap", "keywords", "topical_map", "draft_post", "render", "sheet",
    ]
    assert all(s.status == "ok" for s in report.steps), [(s.name, s.status, s.error) for s in report.steps]
    # deliverables produced
    assert data.render.pdf_path.endswith(".pdf")
    assert data.sheet.sheet_url.endswith("FAKE")
    # the report HTML and sheet flowed through with real data
    assert "Acme Co" in captured["html"]
    # LLM cost captured: sonnet (1M+1M -> wait, 1000+1000) opus (500+2000)
    # sonnet 1000 in/1000 out = 0.003 + 0.015 = 0.018; opus 500 in/2000 out = 0.0025 + 0.05 = 0.0525
    topical_cost = next(s.cost_usd for s in report.steps if s.name == "topical_map")
    draft_cost = next(s.cost_usd for s in report.steps if s.name == "draft_post")
    assert topical_cost == 0.018
    assert draft_cost == 0.0525
    assert report.total_cost_usd == round(0.018 + 0.0525, 4)


def test_run_job_is_resilient_to_a_failed_step(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    competitor_urls=["https://rival.com"])
    job_dir = create_job(cfg, jobs_dir=tmp_path)

    def boom_sheet_writer(title, tabs):
        raise RuntimeError("sheet quota exceeded")

    from pathlib import Path

    def html_to_pdf(html, output_path):
        Path(output_path).write_text("PDF", encoding="utf-8")

    data = run_job(
        job_dir,
        fetch=_sitemap_fetch(),
        keyword_provider=_keyword_provider(),
        topical_generator=_topical_generator(),
        draft_generator=_draft_generator(),
        html_to_pdf=html_to_pdf,
        sheet_writer=boom_sheet_writer,
    )
    statuses = {s.name: s.status for s in data.run_report.steps}
    assert statuses["render"] == "ok"        # earlier steps still succeeded
    assert statuses["sheet"] == "failed"     # the failing step is recorded, not raised
    sheet_step = next(s for s in data.run_report.steps if s.name == "sheet")
    assert "quota" in sheet_step.error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_orchestrator.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'compresearch.orchestrator'`.

- [ ] **Step 3: Write the implementation**

```python
# compresearch/orchestrator.py
from __future__ import annotations

import logging
import time
from pathlib import Path

from compresearch.costs import estimate_cost
from compresearch.draft_post import ClaudeDraftPostGenerator, run_draft_post
from compresearch.job_store import load_data, save_data
from compresearch.keywords import run_keywords
from compresearch.models import JobData, RunReport, StepResult
from compresearch.render import render_pdf, run_render
from compresearch.sheets import run_sheet
from compresearch.sitemap import http_fetch, run_sitemap
from compresearch.topical_map import ClaudeTopicalMapGenerator, run_topical_map


def _section_error(job_dir, attr: str) -> str | None:
    """Return a section's captured error (None if the section ran cleanly)."""
    section = getattr(load_data(job_dir), attr, None)
    if section is None:
        return "no result produced"
    return getattr(section, "error", None)


def _llm_cost(generator) -> float | None:
    usage = getattr(generator, "last_usage", None)
    model = getattr(generator, "model", None)
    if not usage or not model:
        return None
    return estimate_cost(model, usage.get("input_tokens", 0), usage.get("output_tokens", 0))


def run_job(
    job_dir,
    *,
    fetch=http_fetch,
    keyword_provider=None,
    topical_generator=None,
    draft_generator=None,
    html_to_pdf=render_pdf,
    sheet_writer=None,
) -> JobData:
    """Run the full pipeline for one job: sitemap -> keywords -> topical map -> draft
    -> PDF -> Sheet. Resilient: a failed step is recorded and the pipeline continues."""
    steps: list[StepResult] = []

    def record(name, status, error, started, cost=None):
        steps.append(StepResult(
            name=name, status=status, error=error,
            duration_seconds=round(time.monotonic() - started, 2), cost_usd=cost,
        ))

    # 1. Sitemap
    t = time.monotonic()
    try:
        run_sitemap(job_dir, fetch=fetch)
        err = _section_error(job_dir, "sitemap")
        record("sitemap", "ok" if err is None else "failed", err, t)
    except Exception as exc:
        record("sitemap", "failed", str(exc), t)

    # 2. Keywords
    t = time.monotonic()
    try:
        run_keywords(job_dir, provider=keyword_provider)
        err = _section_error(job_dir, "keywords")
        record("keywords", "ok" if err is None else "failed", err, t)
    except Exception as exc:
        record("keywords", "failed", str(exc), t)

    # 3. Topical map (LLM)
    t = time.monotonic()
    try:
        gen = topical_generator or ClaudeTopicalMapGenerator.from_settings()
        run_topical_map(job_dir, generator=gen)
        err = _section_error(job_dir, "topical_map")
        record("topical_map", "ok" if err is None else "failed", err, t, _llm_cost(gen))
    except Exception as exc:
        record("topical_map", "failed", str(exc), t)

    # 4. Draft post (LLM)
    t = time.monotonic()
    try:
        gen = draft_generator or ClaudeDraftPostGenerator.from_settings()
        run_draft_post(job_dir, generator=gen, fetch=fetch)
        err = _section_error(job_dir, "draft_post")
        record("draft_post", "ok" if err is None else "failed", err, t, _llm_cost(gen))
    except Exception as exc:
        record("draft_post", "failed", str(exc), t)

    # 5. Render PDF
    t = time.monotonic()
    try:
        run_render(job_dir, html_to_pdf=html_to_pdf)
        err = _section_error(job_dir, "render")
        record("render", "ok" if err is None else "failed", err, t)
    except Exception as exc:
        record("render", "failed", str(exc), t)

    # 6. Google Sheet
    t = time.monotonic()
    try:
        run_sheet(job_dir, writer=sheet_writer)
        err = _section_error(job_dir, "sheet")
        record("sheet", "ok" if err is None else "failed", err, t)
    except Exception as exc:
        record("sheet", "failed", str(exc), t)

    total = round(sum(s.cost_usd or 0.0 for s in steps), 4)
    data = load_data(job_dir)
    data.run_report = RunReport(steps=steps, total_cost_usd=total)
    save_data(job_dir, data)
    logging.info(
        "Job %s finished: %s steps ok, total LLM cost $%.4f",
        job_dir, sum(1 for s in steps if s.status == "ok"), total,
    )
    return data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_orchestrator.py`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full suite + commit**

Run: `.venv\Scripts\python -m pytest`
Expected: all green.

```bash
git add compresearch/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add run_job orchestrator chaining all six modules"
```

---

## Task 6: CLI `run-job` subcommand + summary

**Files:**
- Modify: `compresearch/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_run_job_subcommand_end_to_end(tmp_path):
    from tests.test_orchestrator import (
        _sitemap_fetch, _keyword_provider, _topical_generator, _draft_generator,
    )

    captured = {}

    def html_to_pdf(html, output_path):
        captured["html"] = html
        from pathlib import Path as _P
        _P(output_path).write_text("PDF", encoding="utf-8")

    def sheet_writer(title, tabs):
        return "https://docs.google.com/spreadsheets/d/FAKE"

    returned = run_from_args(
        [
            "run-job",
            "--client-name", "Acme Co",
            "--client-url", "https://acme.com",
            "--competitors", "https://rival.com",
            "--business-description", "Acme sells CRM software",
            "--jobs-dir", str(tmp_path),
        ],
        fetch=_sitemap_fetch(),
        provider=_keyword_provider(),
        generator=_topical_generator(),
        draft_generator=_draft_generator(),
        html_to_pdf=html_to_pdf,
        sheet_writer=sheet_writer,
    )
    assert returned == tmp_path / "acme-co"
    data = load_data(returned)
    assert [s.name for s in data.run_report.steps] == [
        "sitemap", "keywords", "topical_map", "draft_post", "render", "sheet",
    ]
    assert all(s.status == "ok" for s in data.run_report.steps)
    assert data.sheet.sheet_url.endswith("FAKE")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py -k run_job`
Expected: FAIL — argparse rejects `run-job`.

- [ ] **Step 3: Write the implementation**

In `compresearch/cli.py`:

1. Add the import: `from compresearch.orchestrator import run_job`.
2. Add the subparser (after the `sheet` subparser):

```python
    rj = sub.add_parser("run-job", help="Run the full competitive-research pipeline for a client")
    rj.add_argument("--client-name", required=True)
    rj.add_argument("--client-url", required=True)
    rj.add_argument("--competitors", default="", help="Comma-separated competitor URLs")
    rj.add_argument("--business-description", default=None)
    rj.add_argument("--keyword-source", default="api", choices=["api", "manual"])
    rj.add_argument("--jobs-dir", default="jobs")
```

3. Add the dispatch branch (after the `sheet` branch, before the final `raise`):

```python
    if args.command == "run-job":
        competitors = [c.strip() for c in args.competitors.split(",") if c.strip()]
        config = JobConfig(
            client_name=args.client_name,
            client_url=args.client_url,
            competitor_urls=competitors,
            business_description=args.business_description,
            keyword_source=args.keyword_source,
        )
        job_dir = create_job(config, jobs_dir=Path(args.jobs_dir))
        data = run_job(
            job_dir,
            fetch=fetch,
            keyword_provider=provider,
            topical_generator=generator,
            draft_generator=draft_generator,
            html_to_pdf=html_to_pdf,
            sheet_writer=sheet_writer,
        )
        _print_run_summary(data)
        return job_dir
```

4. Add the summary printer near the top of `cli.py` (module-level function):

```python
def _print_run_summary(data) -> None:
    report = data.run_report
    print("\nCompetitive research job complete:")
    for step in report.steps:
        mark = "OK " if step.status == "ok" else "XX "
        line = f"  [{mark}] {step.name}"
        if step.error:
            line += f" — {step.error}"
        print(line)
    if data.render is not None and data.render.pdf_path:
        print(f"  PDF:   {data.render.pdf_path}")
    if data.sheet is not None and data.sheet.sheet_url:
        print(f"  Sheet: {data.sheet.sheet_url}")
    print(f"  Estimated LLM cost: ${report.total_cost_usd:.4f}\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py -k run_job`
Expected: PASS.

- [ ] **Step 5: Run the full suite + commit**

Run: `.venv\Scripts\python -m pytest`
Expected: all green.

```bash
git add compresearch/cli.py tests/test_cli.py
git commit -m "feat: add run-job CLI subcommand with run summary"
```

---

## Task 7: Claude Code skill + docs

**Files:**
- Create: `.claude/skills/competitive-research/SKILL.md`
- Modify: `README.md`

- [ ] **Step 1: Write the Claude Code project skill**

Create `.claude/skills/competitive-research/SKILL.md`:

```markdown
---
name: competitive-research
description: Run a full competitive research & analysis job for a client — crawls the client and competitors, finds keyword gaps and quick wins, builds a data-driven topical map, drafts a sample blog post, and produces a branded PDF report plus a Google Sheet. Use when someone asks for a competitive research report or analysis for a client.
---

# Competitive Research

Run a complete competitive-research job for a client with one command.

## Gather inputs (ask the operator)

- **Client name** (e.g. "Acme Co")
- **Client website URL** (e.g. https://acme.com)
- **Competitor URLs** (comma-separated)
- **Business description** (one line — what the client does/sells; improves the topical map)
- **Keyword source**: `api` (DataForSEO, default) or `manual` (operator pastes KeySearch CSVs into `jobs/<slug>/keywords_input/` first)

## Prerequisites (one-time)

Confirm `.env` has the needed keys before running:
- `ANTHROPIC_API_KEY` (topical map + draft post)
- `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` (keyword API mode)
- `GOOGLE_SERVICE_ACCOUNT_JSON` + `GOOGLE_SHARE_EMAIL` (Google Sheet)
- For real PDF output: `python -m playwright install chromium` has been run once

## Run the job

```
python -m compresearch.cli run-job \
  --client-name "<name>" \
  --client-url "<url>" \
  --competitors "<comma-separated urls>" \
  --business-description "<one line>"
```

Add `--keyword-source manual` for the manual KeySearch path.

## Report back

The command prints a per-step summary (which steps succeeded/failed), the branded PDF path,
the shared Google Sheet URL, and the estimated Claude cost for the job. Relay those to the
operator. The pipeline is resilient — if one step fails (e.g. a missing credential), the others
still run and the summary shows exactly what was produced.
```

- [ ] **Step 2: Update the README**

Add a section near the top (after the setup, before the per-module sections) and flip the final checklist line. Add:

```markdown
## Run a full job (one command)

Run the entire pipeline — sitemap, keywords, topical map, draft post, branded PDF, and Google
Sheet — for one client:

```
.venv\Scripts\python -m compresearch.cli run-job \
  --client-name "Acme Co" \
  --client-url "https://acme.com" \
  --competitors "https://rival-a.com,https://rival-b.com" \
  --business-description "Acme sells CRM software"
```

It prints a per-step pass/fail summary, the PDF path, the Google Sheet URL, and the estimated
Claude cost for the job. The pipeline is resilient: a failed step is recorded and the rest still
run. Inside Claude Code, the `competitive-research` skill walks an operator through the same flow.
```

Change the status checklist so the orchestrator is checked:

```markdown
- [x] Orchestrator + Claude Code skill
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/competitive-research/SKILL.md README.md
git commit -m "docs: add competitive-research Claude Code skill and full-job docs"
```

---

## Self-Review Notes

- **Spec coverage:** A one-command orchestrator chaining all six modules in order (Task 5); resilient per-step status + duration recorded to `data.run_report` (Tasks 4, 5) — addresses the deferred "clear pass/fail summary" finding; real Claude token-based cost logging (Tasks 2, 3, 5); a `run-job` CLI with a printed summary (Task 6); a Claude Code project skill for non-technical operators (Task 7). The `short_domain` relocation (Task 1) addresses the second deferred finding.
- **Placeholder scan:** No TBDs. DataForSEO/keyword cost is intentionally untracked in v1 (documented), not a placeholder.
- **Type/name consistency:** `short_domain`, `estimate_cost`, `PRICE_PER_MTOK`, `last_usage`, `StepResult`, `RunReport`, `run_job`, `_section_error`, `_llm_cost`, `_print_run_summary` used consistently. `run_job` matches the `(job_dir, ...) -> JobData` family; the CLI threads the same six seams (`fetch`/`provider`/`generator`/`draft_generator`/`html_to_pdf`/`sheet_writer`) into it.
- **Offline testing:** the whole pipeline tests offline — `run_job` accepts injected fakes for every seam; no test hits the network, an LLM, Chromium, or Google. Token-usage capture is tested with stub clients; cost math is unit-tested.
- **Project completion:** with this plan the build sequence is done — all six modules, both deliverables, and the operator entry point. Remaining real-world steps are operator config (DataForSEO + Google service account + real branding) and the first live end-to-end run. Documented follow-up: track DataForSEO per-call cost (its API response includes a `cost` field) to fold into `total_cost_usd`.
