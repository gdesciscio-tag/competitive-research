# compresearch/cli.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from compresearch.draft_post import run_draft_post, DraftGenerator
from compresearch.job_store import create_job
from compresearch.keywords import run_keywords, Provider
from compresearch.models import JobConfig
from compresearch.orchestrator import run_job
from compresearch.render import run_render, render_pdf
from compresearch.sheets import run_sheet
from compresearch.sitemap import Fetcher, http_fetch, run_sitemap
from compresearch.topical_map import run_topical_map, Generator


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


def run_from_args(argv: list[str], fetch: Fetcher = http_fetch, provider=None, generator: Generator | None = None, draft_generator: DraftGenerator | None = None, html_to_pdf=render_pdf, sheet_writer=None) -> Path:
    """Parse args, create the job, run the requested module. Returns the job dir."""
    parser = argparse.ArgumentParser(prog="compresearch")
    sub = parser.add_subparsers(dest="command", required=True)

    sm = sub.add_parser("sitemap", help="Create a job and run sitemap comparison")
    sm.add_argument("--client-name", required=True)
    sm.add_argument("--client-url", required=True)
    sm.add_argument("--competitors", default="", help="Comma-separated competitor URLs")
    sm.add_argument("--jobs-dir", default="jobs")

    kw = sub.add_parser("keywords", help="Run keyword analysis on an existing job")
    kw.add_argument("--job-dir", required=True)

    tm = sub.add_parser("topical-map", help="Generate a topical map for an existing job")
    tm.add_argument("--job-dir", required=True)

    dp = sub.add_parser("draft-post", help="Generate a draft blog post for an existing job")
    dp.add_argument("--job-dir", required=True)
    dp.add_argument("--keyword", default=None, help="Preferred keyword to draft (optional)")

    rn = sub.add_parser("render", help="Render the branded PDF report for an existing job")
    rn.add_argument("--job-dir", required=True)

    sh = sub.add_parser("sheet", help="Create the Google Sheet appendix for an existing job")
    sh.add_argument("--job-dir", required=True)

    rj = sub.add_parser("run-job", help="Run the full competitive-research pipeline for a client")
    rj.add_argument("--client-name", required=True)
    rj.add_argument("--client-url", required=True)
    rj.add_argument("--competitors", default="", help="Comma-separated competitor URLs")
    rj.add_argument("--business-description", default=None)
    rj.add_argument("--keyword-source", default="api", choices=["api", "manual"])
    rj.add_argument("--jobs-dir", default="jobs")

    args = parser.parse_args(argv)

    if args.command == "sitemap":
        competitors = [c.strip() for c in args.competitors.split(",") if c.strip()]
        config = JobConfig(
            client_name=args.client_name,
            client_url=args.client_url,
            competitor_urls=competitors,
        )
        job_dir = create_job(config, jobs_dir=Path(args.jobs_dir))
        run_sitemap(job_dir, fetch=fetch)
        return job_dir

    if args.command == "keywords":
        job_dir = Path(args.job_dir)
        try:
            run_keywords(job_dir, provider=provider)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        return job_dir

    if args.command == "topical-map":
        job_dir = Path(args.job_dir)
        try:
            run_topical_map(job_dir, generator=generator)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        return job_dir

    if args.command == "draft-post":
        job_dir = Path(args.job_dir)
        try:
            run_draft_post(job_dir, generator=draft_generator, fetch=fetch, preferred_keyword=args.keyword)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        return job_dir

    if args.command == "render":
        job_dir = Path(args.job_dir)
        try:
            run_render(job_dir, html_to_pdf=html_to_pdf)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        return job_dir

    if args.command == "sheet":
        job_dir = Path(args.job_dir)
        try:
            run_sheet(job_dir, writer=sheet_writer)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        return job_dir

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

    raise ValueError(f"Unknown command: {args.command}")  # pragma: no cover


def main() -> None:
    job_dir = run_from_args(sys.argv[1:])
    print(f"Job complete: {job_dir}")


if __name__ == "__main__":
    main()
