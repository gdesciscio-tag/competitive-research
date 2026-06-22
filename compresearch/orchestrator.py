# compresearch/orchestrator.py
from __future__ import annotations

import logging
import time
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
    if usage is None or not model:
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
