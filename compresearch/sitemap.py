# compresearch/sitemap.py
from __future__ import annotations

import gzip
import logging
from datetime import date
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx
from lxml import etree

from compresearch.job_store import load_data, save_data
from compresearch.models import (
    DomainSitemap, JobData, SitemapGap, SitemapResult, UrlEntry,
)

Fetcher = Callable[[str], bytes]


def _root_url(url: str) -> str:
    parsed = urlparse(url if "://" in url else "https://" + url)
    return f"{parsed.scheme}://{parsed.netloc}"


def discover_sitemaps(base_url: str, fetch: Fetcher) -> list[str]:
    """Find sitemap URLs via robots.txt; fall back to /sitemap.xml."""
    root = _root_url(base_url)
    sitemaps: list[str] = []
    try:
        robots = fetch(root + "/robots.txt").decode("utf-8", "ignore")
        for line in robots.splitlines():
            if line.lower().startswith("sitemap:"):
                sitemaps.append(line.split(":", 1)[1].strip())
    except Exception:
        pass
    if not sitemaps:
        sitemaps.append(root + "/sitemap.xml")
    return sitemaps


def _maybe_gunzip(url: str, content: bytes) -> bytes:
    if url.endswith(".gz") or content[:2] == b"\x1f\x8b":
        return gzip.decompress(content)
    return content


def _parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text.strip()[:10])
    except ValueError:
        return None


def fetch_sitemap_urls(
    sitemap_url: str, fetch: Fetcher, _seen: set[str] | None = None, _depth: int = 0
) -> list[UrlEntry]:
    """Fetch a sitemap, recursing into sitemap indexes; return all URL entries."""
    MAX_DEPTH = 10
    if _seen is None:
        _seen = set()
    if sitemap_url in _seen or _depth > MAX_DEPTH:
        return []
    _seen.add(sitemap_url)

    content = _maybe_gunzip(sitemap_url, fetch(sitemap_url))
    root = etree.fromstring(content)

    if etree.QName(root).localname == "sitemapindex":
        entries: list[UrlEntry] = []
        for loc in root.xpath(".//*[local-name()='loc']/text()"):
            entries.extend(fetch_sitemap_urls(loc.strip(), fetch, _seen, _depth + 1))
        return entries

    entries = []
    for url_el in root.xpath(".//*[local-name()='url']"):
        loc = url_el.xpath("./*[local-name()='loc']/text()")
        if not loc:
            continue
        lastmod = url_el.xpath("./*[local-name()='lastmod']/text()")
        entries.append(
            UrlEntry(
                loc=loc[0].strip(),
                lastmod=_parse_date(lastmod[0]) if lastmod else None,
            )
        )
    return entries


def categorize_urls(urls: list[UrlEntry]) -> dict[str, int]:
    """Count URLs by their first path segment ('(root)' for the homepage)."""
    counts: dict[str, int] = {}
    for entry in urls:
        path = urlparse(entry.loc).path.strip("/")
        section = path.split("/")[0] if path else "(root)"
        counts[section] = counts.get(section, 0) + 1
    return counts


def infer_cadence(urls: list[UrlEntry]) -> float | None:
    """Estimate posts per month from lastmod dates; None if fewer than 2 dates."""
    dates = sorted(e.lastmod for e in urls if e.lastmod)
    if len(dates) < 2:
        return None
    span_days = (dates[-1] - dates[0]).days
    if span_days <= 0:
        return None
    months = span_days / 30.44
    return round(len(dates) / months, 1)


def analyze_domain(domain_url: str, fetch: Fetcher) -> DomainSitemap:
    """Discover, fetch, parse, and summarize one domain's sitemap content.

    Never raises: discovery failure yields an error result; if some sitemaps
    fetch and others fail, the collected URLs are kept and failures are logged.
    """
    try:
        sitemap_urls = discover_sitemaps(domain_url, fetch)
    except Exception as exc:
        logging.warning("Sitemap discovery failed for %s: %s", domain_url, exc)
        return DomainSitemap(domain=domain_url, error=str(exc))

    seen: set[str] = set()
    urls: list[UrlEntry] = []
    errors: list[str] = []
    for sitemap_url in sitemap_urls:
        try:
            urls.extend(fetch_sitemap_urls(sitemap_url, fetch, seen))
        except Exception as exc:
            logging.warning("Failed to fetch sitemap %s for %s: %s", sitemap_url, domain_url, exc)
            errors.append(f"{sitemap_url}: {exc}")

    deduped = list({e.loc: e for e in urls}.values())
    error = "; ".join(errors) if errors and not deduped else None
    return DomainSitemap(
        domain=domain_url,
        urls=deduped,
        section_counts=categorize_urls(deduped),
        total_urls=len(deduped),
        posts_per_month=infer_cadence(deduped),
        error=error,
    )


def _find_gaps(
    client: DomainSitemap, competitors: list[DomainSitemap]
) -> list[SitemapGap]:
    """Sections one or more competitors have that the client has zero of."""
    if client.error:
        return []
    competitor_sections: dict[str, list[str]] = {}
    for comp in competitors:
        for section in comp.section_counts:
            competitor_sections.setdefault(section, []).append(comp.domain)

    gaps: list[SitemapGap] = []
    for section, domains in competitor_sections.items():
        if client.section_counts.get(section, 0) == 0:
            gaps.append(
                SitemapGap(
                    section=section,
                    competitors_with=sorted(set(domains)),
                    client_count=0,
                )
            )
    gaps.sort(key=lambda g: len(g.competitors_with), reverse=True)
    return gaps


def compare_domains(
    client_url: str, competitor_urls: list[str], fetch: Fetcher
) -> SitemapResult:
    """Analyze the client and each competitor, then compute content gaps."""
    client = analyze_domain(client_url, fetch)
    competitors = [analyze_domain(url, fetch) for url in competitor_urls]
    is_partial = bool(client.error) or any(c.error for c in competitors)
    return SitemapResult(
        client=client,
        competitors=competitors,
        gaps=_find_gaps(client, competitors),
        is_partial=is_partial,
    )


def http_fetch(url: str) -> bytes:
    """Production fetcher: real HTTP GET with redirects and a UA header."""
    resp = httpx.get(
        url,
        follow_redirects=True,
        timeout=30.0,
        headers={"User-Agent": "TAG-CompResearch/1.0"},
    )
    resp.raise_for_status()
    return resp.content


def run_sitemap(job_dir: Path, fetch: Fetcher = http_fetch) -> JobData:
    """Run sitemap comparison for a job and persist the result to data.json."""
    data = load_data(job_dir)
    data.sitemap = compare_domains(
        data.config.client_url, data.config.competitor_urls, fetch
    )
    save_data(job_dir, data)
    return data
