# compresearch/cli.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from compresearch.job_store import create_job
from compresearch.keywords import run_keywords, Provider
from compresearch.models import JobConfig
from compresearch.sitemap import Fetcher, http_fetch, run_sitemap
from compresearch.topical_map import run_topical_map


def run_from_args(argv: list[str], fetch: Fetcher = http_fetch, provider: Provider | None = None, generator=None) -> Path:
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

    raise ValueError(f"Unknown command: {args.command}")  # pragma: no cover


def main() -> None:
    job_dir = run_from_args(sys.argv[1:])
    print(f"Job complete: {job_dir}")


if __name__ == "__main__":
    main()
