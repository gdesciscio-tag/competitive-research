# compresearch/cli.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from compresearch.draft_export import run_draft_export
from compresearch.draft_post import run_draft_post, DraftGenerator
from compresearch.job_store import create_job, load_data
from compresearch.keywords import run_keywords, Provider
from compresearch.models import JobConfig
from compresearch.orchestrator import run_job
from compresearch.render import run_render, render_pdf
from compresearch.runlog import job_log, remediation_hint
from compresearch.sheets import run_sheet
from compresearch.sitemap import Fetcher, http_fetch, run_sitemap
from compresearch.topical_map import run_topical_map, Generator


def _print_run_summary(data) -> None:
    report = data.run_report
    print("\nCompetitive research job complete:")
    for step in report.steps:
        mark = {"ok": "OK ", "partial": "~~ ", "skipped": "-- "}.get(step.status, "XX ")
        line = f"  [{mark}] {step.name}"
        if step.error:
            line += f" — {step.error}"
        print(line)
        hint = remediation_hint(step.error)
        if hint:
            print(f"         fix: {hint}")
    if data.render is not None and data.render.pdf_path:
        print(f"  PDF:   {data.render.pdf_path}")
    if data.sheet is not None and data.sheet.sheet_url:
        print(f"  Sheet: {data.sheet.sheet_url}")
    _print_draft_exports(data)
    _print_draft_warnings(data)
    print(f"  Estimated LLM cost: ${report.total_cost_usd:.4f}\n")


def _print_draft_warnings(data) -> None:
    """Surface internal SEO/quality flags for each draft (never shown to the client)."""
    drafts = [d for d in data.draft_posts if d.post is not None and d.warnings]
    if not drafts:
        return
    multiple = len([d for d in data.draft_posts if d.post is not None]) > 1
    for index, draft in enumerate(drafts, 1):
        label = f"Draft {index} ({draft.selected_keyword})" if multiple else "Draft"
        print(f"  {label} quality notes:")
        for warning in draft.warnings:
            print(f"    - {warning}")


def _print_draft_exports(data) -> None:
    """List every exported draft (HTML path + Google Doc URL), one block per draft."""
    if data.draft_export is None:
        return
    items = data.draft_export.items or []
    if not items:  # legacy single-draft export with only top-level fields
        if data.draft_export.html_path:
            print(f"  Draft HTML: {data.draft_export.html_path}")
        if data.draft_export.doc_url:
            print(f"  Draft Doc:  {data.draft_export.doc_url}")
        return
    multiple = len(items) > 1
    for index, item in enumerate(items, 1):
        label = f"Draft {index}" if multiple else "Draft"
        if item.html_path:
            print(f"  {label} HTML: {item.html_path}")
        if item.doc_url:
            print(f"  {label} Doc:  {item.doc_url}")


def _print_outputs_summary(data) -> None:
    """Print the regenerated outputs after a refresh-outputs run."""
    print("\nOutputs refreshed:")
    if data.render is not None and data.render.pdf_path:
        print(f"  PDF:   {data.render.pdf_path}")
    if data.sheet is not None and data.sheet.sheet_url:
        print(f"  Sheet: {data.sheet.sheet_url}")
    _print_draft_exports(data)
    print()


def run_from_args(argv: list[str], fetch: Fetcher = http_fetch, provider=None, generator: Generator | None = None, draft_generator: DraftGenerator | None = None, html_to_pdf=render_pdf, sheet_writer=None, doc_writer=None) -> Path:
    """Parse args, create the job, run the requested module. Returns the job dir."""
    parser = argparse.ArgumentParser(prog="compresearch")
    sub = parser.add_subparsers(dest="command", required=True)

    sm = sub.add_parser("sitemap", help="Create a job and run sitemap comparison")
    sm.add_argument("--client-name", required=True)
    sm.add_argument("--client-url", required=True)
    sm.add_argument("--competitors", default="", help="Comma-separated competitor URLs")
    sm.add_argument("--jobs-dir", default="jobs")
    sm.add_argument("--force", action="store_true", help="Re-run even if a cached result exists")

    kw = sub.add_parser("keywords", help="Run keyword analysis on an existing job")
    kw.add_argument("--job-dir", required=True)
    kw.add_argument("--force", action="store_true", help="Re-run even if a cached result exists")

    tm = sub.add_parser("topical-map", help="Generate a topical map for an existing job")
    tm.add_argument("--job-dir", required=True)
    tm.add_argument("--force", action="store_true", help="Re-run even if a cached result exists")

    dp = sub.add_parser("draft-post", help="Generate a draft blog post for an existing job")
    dp.add_argument("--job-dir", required=True)
    dp.add_argument("--keyword", default=None, help="Preferred keyword to draft (optional)")
    dp.add_argument("--force", action="store_true",
                    help="Re-draft even if this topic was already drafted")

    rn = sub.add_parser("render", help="Render the branded PDF report for an existing job")
    rn.add_argument("--job-dir", required=True)

    sh = sub.add_parser("sheet", help="Create the Google Sheet appendix for an existing job")
    sh.add_argument("--job-dir", required=True)

    de = sub.add_parser("draft-export", help="Export the draft post to HTML + a Google Doc")
    de.add_argument("--job-dir", required=True)

    ro = sub.add_parser(
        "refresh-outputs",
        help="Re-export drafts and rebuild the PDF + Google Sheet for an existing job "
        "(run after drafting another post so the outputs include it)",
    )
    ro.add_argument("--job-dir", required=True)

    rj = sub.add_parser("run-job", help="Run the full competitive-research pipeline for a client")
    rj.add_argument("--client-name", help="Client name (required for a new job)")
    rj.add_argument("--client-url", help="Client URL (required for a new job)")
    rj.add_argument("--competitors", default="", help="Comma-separated competitor URLs")
    rj.add_argument("--business-description", default=None)
    rj.add_argument("--keyword-source", default="api", choices=["api", "manual"])
    rj.add_argument("--jobs-dir", default="jobs")
    rj.add_argument("--job-dir", default=None,
                    help="Resume an existing job, skipping already-completed steps")
    rj.add_argument("--force", action="store_true",
                    help="Recompute every step, ignoring cached results")

    args = parser.parse_args(argv)

    if args.command == "sitemap":
        competitors = [c.strip() for c in args.competitors.split(",") if c.strip()]
        config = JobConfig(
            client_name=args.client_name,
            client_url=args.client_url,
            competitor_urls=competitors,
        )
        job_dir = create_job(config, jobs_dir=Path(args.jobs_dir))
        with job_log(job_dir):
            run_sitemap(job_dir, fetch=fetch, force=args.force)
        return job_dir

    if args.command == "keywords":
        job_dir = Path(args.job_dir)
        try:
            with job_log(job_dir):
                run_keywords(job_dir, provider=provider, force=args.force)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        return job_dir

    if args.command == "topical-map":
        job_dir = Path(args.job_dir)
        try:
            with job_log(job_dir):
                run_topical_map(job_dir, generator=generator, force=args.force)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        return job_dir

    if args.command == "draft-post":
        job_dir = Path(args.job_dir)
        try:
            with job_log(job_dir):
                run_draft_post(job_dir, generator=draft_generator, fetch=fetch,
                               preferred_keyword=args.keyword, force=args.force)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        _print_draft_warnings(load_data(job_dir))
        return job_dir

    if args.command == "render":
        job_dir = Path(args.job_dir)
        try:
            with job_log(job_dir):
                run_render(job_dir, html_to_pdf=html_to_pdf)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        return job_dir

    if args.command == "sheet":
        job_dir = Path(args.job_dir)
        try:
            with job_log(job_dir):
                run_sheet(job_dir, writer=sheet_writer)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        return job_dir

    if args.command == "draft-export":
        job_dir = Path(args.job_dir)
        with job_log(job_dir):
            run_draft_export(job_dir, doc_writer=doc_writer)
        return job_dir

    if args.command == "refresh-outputs":
        job_dir = Path(args.job_dir)
        with job_log(job_dir):
            run_draft_export(job_dir, doc_writer=doc_writer)
            run_render(job_dir, html_to_pdf=html_to_pdf)
            run_sheet(job_dir, writer=sheet_writer)
        _print_outputs_summary(load_data(job_dir))
        return job_dir

    if args.command == "run-job":
        if args.job_dir:
            job_dir = Path(args.job_dir)
        else:
            if not args.client_name or not args.client_url:
                parser.error(
                    "run-job requires --client-name and --client-url "
                    "(or --job-dir to resume an existing job)"
                )
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
            force=args.force,
            fetch=fetch,
            keyword_provider=provider,
            topical_generator=generator,
            draft_generator=draft_generator,
            html_to_pdf=html_to_pdf,
            sheet_writer=sheet_writer,
            doc_writer=doc_writer,
        )
        _print_run_summary(data)
        return job_dir

    raise ValueError(f"Unknown command: {args.command}")  # pragma: no cover


def main() -> None:
    job_dir = run_from_args(sys.argv[1:])
    print(f"Job complete: {job_dir}")


if __name__ == "__main__":
    main()
