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


def test_run_job_runs_all_six_steps_offline(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    competitor_urls=["https://rival.com"],
                    business_description="Acme sells CRM software")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data, captured = _full_run(job_dir)

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

    def doc_writer(title, html):
        return "https://docs.google.com/document/d/DOCFAKE/edit"

    data = run_job(
        job_dir,
        fetch=_sitemap_fetch(),
        keyword_provider=_keyword_provider(),
        topical_generator=_topical_generator(),
        draft_generator=_draft_generator(),
        html_to_pdf=html_to_pdf,
        sheet_writer=boom_sheet_writer,
        doc_writer=doc_writer,
    )
    statuses = {s.name: s.status for s in data.run_report.steps}
    assert statuses["render"] == "ok"        # earlier steps still succeeded
    assert statuses["sheet"] == "failed"     # the failing step is recorded, not raised
    sheet_step = next(s for s in data.run_report.steps if s.name == "sheet")
    assert "quota" in sheet_step.error


def test_run_job_marks_step_failed_when_generator_errors_and_continues(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    competitor_urls=["https://rival.com"])
    job_dir = create_job(cfg, jobs_dir=tmp_path)

    class RaisingTopicalGen:
        model = "claude-sonnet-4-6"
        last_usage = None  # no usage captured on failure

        def __call__(self, prompt):
            raise RuntimeError("model unavailable")

    from pathlib import Path

    def html_to_pdf(html, output_path):
        Path(output_path).write_text("PDF", encoding="utf-8")

    def sheet_writer(title, tabs):
        return "https://docs.google.com/spreadsheets/d/FAKE"

    def doc_writer(title, html):
        return "https://docs.google.com/document/d/DOCFAKE/edit"

    data = run_job(
        job_dir,
        fetch=_sitemap_fetch(),
        keyword_provider=_keyword_provider(),
        topical_generator=RaisingTopicalGen(),
        draft_generator=_draft_generator(),
        html_to_pdf=html_to_pdf,
        sheet_writer=sheet_writer,
        doc_writer=doc_writer,
    )
    steps = {s.name: s for s in data.run_report.steps}
    # run_topical_map captures the generator error into topical_map.error WITHOUT raising,
    # so the orchestrator records the step as "failed" (not via an exception) and continues.
    assert steps["topical_map"].status == "failed"
    assert "model unavailable" in steps["topical_map"].error
    assert steps["topical_map"].cost_usd is None        # last_usage=None -> no cost, no crash
    # draft_post also fails (no topical-map article available to select a topic from),
    # but the pipeline still continues to render and sheet.
    assert steps["draft_post"].status == "failed"
    assert steps["render"].status == "ok"
    assert steps["sheet"].status == "ok"
    # total cost still sums cleanly (topical_map has None cost, draft generator
    # was never invoked so its stale last_usage drives the cost tally)
    assert data.run_report.total_cost_usd == round(
        sum(s.cost_usd or 0.0 for s in steps.values()), 4
    )


def test_run_job_marks_sitemap_partial_when_a_competitor_fetch_fails(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    competitor_urls=["https://rival.com"])
    job_dir = create_job(cfg, jobs_dir=tmp_path)

    # fetch knows the client but NOT the competitor -> the rival crawl fails ->
    # SitemapResult.is_partial is True (client still succeeds).
    acme_urlset = (
        b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://acme.com/blog/a</loc></url></urlset>"
    )
    pages = {
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": acme_urlset,
    }

    def fetch(url):
        if url not in pages:
            raise FileNotFoundError(url)
        return pages[url]

    from pathlib import Path

    def html_to_pdf(html, output_path):
        Path(output_path).write_text("PDF", encoding="utf-8")

    def sheet_writer(title, tabs):
        return "https://docs.google.com/spreadsheets/d/FAKE"

    def doc_writer(title, html):
        return "https://docs.google.com/document/d/DOCFAKE/edit"

    data = run_job(
        job_dir,
        fetch=fetch,
        keyword_provider=_keyword_provider(),
        topical_generator=_topical_generator(),
        draft_generator=_draft_generator(),
        html_to_pdf=html_to_pdf,
        sheet_writer=sheet_writer,
        doc_writer=doc_writer,
    )
    steps = {s.name: s for s in data.run_report.steps}
    assert steps["sitemap"].status == "partial"
    assert steps["sitemap"].error is not None       # the explanatory note
    assert steps["render"].status == "ok"           # pipeline completed regardless


def test_run_job_marks_draft_export_partial_when_doc_upload_fails(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    competitor_urls=["https://rival.com"])
    job_dir = create_job(cfg, jobs_dir=tmp_path)

    from pathlib import Path

    def html_to_pdf(html, output_path):
        Path(output_path).write_text("PDF", encoding="utf-8")

    def sheet_writer(title, tabs):
        return "https://docs.google.com/spreadsheets/d/FAKE"

    def boom_doc_writer(title, html):
        raise RuntimeError("drive unavailable")

    data = run_job(
        job_dir,
        fetch=_sitemap_fetch(),
        keyword_provider=_keyword_provider(),
        topical_generator=_topical_generator(),
        draft_generator=_draft_generator(),
        html_to_pdf=html_to_pdf,
        sheet_writer=sheet_writer,
        doc_writer=boom_doc_writer,
    )
    steps = {s.name: s for s in data.run_report.steps}
    # HTML was written but the Doc upload failed -> partial (not failed), and the note
    # carries the underlying error.
    assert steps["draft_export"].status == "partial"
    assert "drive unavailable" in steps["draft_export"].error
    # the local HTML artifact is still recorded, and later steps still ran
    assert data.draft_export.html_path is not None
    assert data.draft_export.doc_url is None
    assert steps["render"].status == "ok"
    assert steps["sheet"].status == "ok"
