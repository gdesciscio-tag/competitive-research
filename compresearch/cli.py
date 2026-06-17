# compresearch/cli.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from compresearch.job_store import create_job
from compresearch.models import JobConfig
from compresearch.sitemap import Fetcher, http_fetch, run_sitemap


def run_from_args(argv: list[str], fetch: Fetcher = http_fetch) -> Path:
    """Parse args, create the job, run the requested module. Returns the job dir."""
    parser = argparse.ArgumentParser(prog="compresearch")
    sub = parser.add_subparsers(dest="command", required=True)

    sm = sub.add_parser("sitemap", help="Create a job and run sitemap comparison")
    sm.add_argument("--client-name", required=True)
    sm.add_argument("--client-url", required=True)
    sm.add_argument("--competitors", default="", help="Comma-separated competitor URLs")
    sm.add_argument("--jobs-dir", default="jobs")

    args = parser.parse_args(argv)

    competitors = [c.strip() for c in args.competitors.split(",") if c.strip()]
    config = JobConfig(
        client_name=args.client_name,
        client_url=args.client_url,
        competitor_urls=competitors,
    )
    job_dir = create_job(config, jobs_dir=Path(args.jobs_dir))
    run_sitemap(job_dir, fetch=fetch)
    return job_dir


def main() -> None:
    job_dir = run_from_args(sys.argv[1:])
    print(f"Job complete: {job_dir}")


if __name__ == "__main__":
    main()
