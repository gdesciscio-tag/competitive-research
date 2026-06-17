# compresearch/sitemap.py
from __future__ import annotations

import gzip
from datetime import date
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx
from lxml import etree

from compresearch.job_store import load_data, save_data
from compresearch.models import (
    DomainSitemap, SitemapGap, SitemapResult, UrlEntry,
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
    sitemap_url: str, fetch: Fetcher, _seen: set[str] | None = None
) -> list[UrlEntry]:
    """Fetch a sitemap, recursing into sitemap indexes; return all URL entries."""
    if _seen is None:
        _seen = set()
    if sitemap_url in _seen:
        return []
    _seen.add(sitemap_url)

    content = _maybe_gunzip(sitemap_url, fetch(sitemap_url))
    root = etree.fromstring(content)

    if etree.QName(root).localname == "sitemapindex":
        entries: list[UrlEntry] = []
        for loc in root.xpath(".//*[local-name()='loc']/text()"):
            entries.extend(fetch_sitemap_urls(loc.strip(), fetch, _seen))
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
