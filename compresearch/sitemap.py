# compresearch/sitemap.py
from __future__ import annotations

import gzip
import logging
import re
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
    # Some servers emit stray leading whitespace (a blank line from PHP output, etc.)
    # before the XML declaration, which lxml rejects. Strip it so an otherwise-valid
    # sitemap still parses.
    content = content.lstrip()
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


# A shared hyphen-prefix across this many root-level standalone slugs reads as a
# deliberate template (e.g. local-SEO location pages) rather than coincidence.
_SLUG_PATTERN_MIN_GROUP = 3


def _group_slug_patterns(
    slugs: list[str], min_group: int = _SLUG_PATTERN_MIN_GROUP
) -> tuple[dict[str, int], list[str]]:
    """Group root-level standalone slugs that share a hyphenated prefix into pattern
    sections, so local-SEO templates aren't lost in '(individual pages)'. E.g.
    'digital-marketing-passaic-nj' + '...-clifton-nj' + '...-newark-nj' -> 'digital-marketing-*'.

    Greedy: repeatedly take the longest prefix (most specific) shared by >= min_group
    slugs, preferring more members then alphabetical on ties. Returns (pattern_counts,
    leftover_slugs).
    """
    remaining = list(slugs)
    patterns: dict[str, int] = {}
    while True:
        members_by_prefix: dict[str, list[str]] = {}
        for slug in remaining:
            tokens = slug.split("-")
            for length in range(1, len(tokens)):   # leave >=1 token as the variable tail
                prefix = "-".join(tokens[:length])
                if len(prefix) >= 3:               # skip trivial prefixes ("a-", "to-")
                    members_by_prefix.setdefault(prefix, []).append(slug)
        best = None  # (token_len, member_count, -alpha) — maximize specificity, then size
        for prefix, members in members_by_prefix.items():
            if len(members) < min_group:
                continue
            key = (prefix.count("-") + 1, len(members), tuple(-ord(c) for c in prefix))
            if best is None or key > best[0]:
                best = (key, prefix, members)
        if best is None:
            break
        _, prefix, members = best
        patterns[f"{prefix}-*"] = len(members)
        chosen = set(members)
        remaining = [s for s in remaining if s not in chosen]
    return patterns, remaining


def categorize_urls(urls: list[UrlEntry]) -> dict[str, int]:
    """Count URLs by content section.

    A first path segment is a real *section* if it groups 2+ URLs or has any deeper path
    under it (e.g. '/blog/post' -> 'blog', '/services/seo' -> 'services'). Root-level
    standalone pages with no children (e.g. '/my-post', '/about') normally fold into a
    single '(individual pages)' bucket — but when several share a hyphen prefix (a local-SEO
    template like '/digital-marketing-<city>-<state>') they're surfaced as a '<prefix>-*'
    section so the signal isn't lost. The homepage is counted as '(root)'.
    """
    root_count = 0
    seg_count: dict[str, int] = {}
    seg_has_child: dict[str, bool] = {}
    for entry in urls:
        path = urlparse(entry.loc).path.strip("/")
        if not path:
            root_count += 1
            continue
        parts = path.split("/")
        segment = parts[0]
        seg_count[segment] = seg_count.get(segment, 0) + 1
        if len(parts) >= 2:
            seg_has_child[segment] = True

    counts: dict[str, int] = {}
    if root_count:
        counts["(root)"] = root_count
    individual_slugs: list[str] = []
    for segment, count in seg_count.items():
        if count >= 2 or seg_has_child.get(segment, False):
            counts[segment] = count
        else:
            individual_slugs.append(segment)

    pattern_counts, leftover = _group_slug_patterns(individual_slugs)
    counts.update(pattern_counts)
    if leftover:
        counts["(individual pages)"] = len(leftover)
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


# A real site's content history fits comfortably inside this window; a longer
# implied span means a garbage lastmod (e.g. 0001-01-01) is distorting the estimate.
_MAX_PLAUSIBLE_SPAN_YEARS = 25


def _cadence_is_reliable(urls: list[UrlEntry]) -> bool:
    """Whether posts_per_month can be trusted: enough dated pages, and a plausible
    span (an outlier date like year 1 inflates the span and collapses the rate)."""
    dates = sorted(e.lastmod for e in urls if e.lastmod)
    if len(dates) < 3:
        return False
    span_years = (dates[-1] - dates[0]).days / 365.25
    return span_years <= _MAX_PLAUSIBLE_SPAN_YEARS


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
        dated_urls=sum(1 for e in deduped if e.lastmod),
        posts_per_month_reliable=_cadence_is_reliable(deduped),
        error=error,
    )


# CMS/theme taxonomy and system path segments that aren't real content sections.
_NON_CONTENT_SECTIONS = {
    "author", "authors", "category", "categories", "tag", "tags", "type", "types",
    "feed", "page", "comment-page", "attachment", "embed", "amp", "search", "login",
    "cart", "checkout", "account", "wp-json", "wp-admin", "wp-content", "wp-includes",
    "portfolio_category", "portfolio-items", "casestudies-categories", "(root)",
    "(individual pages)",
}
_NON_CONTENT_PREFIXES = ("colio", "elementor", "wp-")
_NON_CONTENT_SUFFIXES = ("-categories", "-category", "_category", "_categories",
                         "_tag", "_group", "_item")

# Bare language roots (/en/, /fr/) — kept as an allowlist so genuine 2-letter
# content sections like /ai/ or /rf/ are NOT mistaken for locales.
_LANG_CODES = {
    "en", "fr", "de", "es", "it", "pt", "nl", "ja", "zh", "ko", "ru", "ar",
    "sv", "da", "no", "fi", "pl", "tr", "hi", "cs", "el", "he", "th", "vi", "id",
}
_LOCALE_HYPHEN = re.compile(r"^[a-z]{2}-[a-z]{2,3}$")   # en-gb, fr-ca, en-in, zh-cn
_NUMERIC = re.compile(r"^\d+$")                          # /2024/ date archives, numeric IDs

# Structurally-different sections that mean the same thing. Folding them lets a
# client's /all-jobs/ cover a competitor's /job/ instead of reading as a gap.
_SECTION_SYNONYMS = {
    "job": "jobs", "jobs": "jobs", "all-jobs": "jobs", "job_type": "jobs",
    "career": "jobs", "careers": "jobs", "opening": "jobs", "openings": "jobs",
    "position": "jobs", "positions": "jobs", "open-roles": "jobs", "roles": "jobs",
    "service": "services", "services": "services",
    "about": "about", "about-us": "about", "who-we-are": "about",
    "contact": "contact", "contact-us": "contact",
    "blog": "blog", "news": "blog", "insights": "blog", "articles": "blog",
}


def _is_content_section(name: str) -> bool:
    """True if a section name looks like real content (not a CMS taxonomy/system path,
    a date archive, or an i18n locale subpath)."""
    lowered = name.lower()
    if lowered in _NON_CONTENT_SECTIONS:
        return False
    if lowered.startswith(_NON_CONTENT_PREFIXES):
        return False
    if lowered.endswith(_NON_CONTENT_SUFFIXES):
        return False
    if _NUMERIC.match(lowered):           # date archives (/2024/) and numeric IDs
        return False
    if _LOCALE_HYPHEN.match(lowered):     # locale subpaths (/en-gb/, /fr-ca/)
        return False
    if lowered in _LANG_CODES:            # bare language roots (/en/, /fr/)
        return False
    return True


def _canonical_section(name: str) -> str:
    """Map a section name to its semantic label so synonymous sections compare equal."""
    return _SECTION_SYNONYMS.get(name.lower(), name.lower())


def _find_gaps(
    client: DomainSitemap, competitors: list[DomainSitemap]
) -> list[SitemapGap]:
    """Content sections one or more competitors have that the client has zero of.

    CMS taxonomy / system paths (categories, tags, author archives, theme artifacts) are
    excluded — they aren't content-strategy gaps.
    """
    if client.error:
        return []
    client_canon = {
        _canonical_section(s) for s in client.section_counts if _is_content_section(s)
    }
    aggregated: dict[str, SitemapGap] = {}
    for comp in competitors:
        for section in comp.section_counts:
            if not _is_content_section(section):
                continue
            canon = _canonical_section(section)
            if canon in client_canon:
                continue
            gap = aggregated.get(canon)
            if gap is None:
                gap = SitemapGap(section=canon, competitors_with=[], client_count=0)
                aggregated[canon] = gap
            if comp.domain not in gap.competitors_with:
                gap.competitors_with.append(comp.domain)

    gaps = list(aggregated.values())
    for gap in gaps:
        gap.competitors_with.sort()
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


def run_sitemap(job_dir: Path, fetch: Fetcher = http_fetch, force: bool = False) -> JobData:
    """Run sitemap comparison for a job and persist the result to data.json.

    Skips the crawl when a complete result is already cached, unless force=True."""
    data = load_data(job_dir)
    if not force and data.sitemap is not None and not data.sitemap.is_partial:
        logging.info("Skipping sitemap for %s: cached result present (use --force to re-run)",
                     data.config.client_url)
        return data
    data.sitemap = compare_domains(
        data.config.client_url, data.config.competitor_urls, fetch
    )
    save_data(job_dir, data)
    return data
