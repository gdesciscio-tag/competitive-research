from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from compresearch.models import (
    KeywordEntry, DomainKeywords, KeywordGap, QuickWin, KeywordResult,
    JobConfig, JobData,
)
from compresearch.settings import get_secret
from compresearch.job_store import load_data, save_data

# Approximate average organic click-through rate by SERP position.
# Used only to rank opportunities relative to each other, not as a traffic promise.
_CTR_BY_POSITION = {
    1: 0.28, 2: 0.15, 3: 0.11, 4: 0.08, 5: 0.06,
    6: 0.05, 7: 0.04, 8: 0.03, 9: 0.025, 10: 0.022,
}


def estimate_traffic_value(volume: int | None, position: int | None) -> float | None:
    """Estimate monthly clicks a keyword could yield at a given SERP position."""
    if volume is None or position is None:
        return None
    if position <= 0:
        return None
    if position <= 10:
        ctr = _CTR_BY_POSITION.get(position, 0.02)
    elif position <= 20:
        ctr = 0.01
    else:
        ctr = 0.005
    return round(volume * ctr, 1)


Provider = Callable[[str], list[KeywordEntry]]


def _domain_key(url: str) -> str:
    """Netloc without scheme or leading 'www.' — used for matching and filenames."""
    netloc = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    if not netloc:
        raise ValueError(f"Cannot extract a domain from URL: {url!r}")
    return netloc[4:] if netloc.startswith("www.") else netloc


def _domain_to_filename(domain_key: str) -> str:
    """Map a domain key to its manual-CSV filename stem (dots -> hyphens)."""
    return domain_key.replace(".", "-")


def _to_int(value: str | None) -> int | None:
    value = (value or "").strip()
    return int(float(value)) if value else None


def _to_float(value: str | None) -> float | None:
    value = (value or "").strip()
    return float(value) if value else None


def parse_keyword_csv(path: str) -> list[KeywordEntry]:
    """Parse a manual keyword CSV (keyword, search_volume, difficulty, position, url)."""
    entries: list[KeywordEntry] = []
    # utf-8-sig tolerates the BOM that Excel/KeySearch exports often include.
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            keyword = (row.get("keyword") or "").strip()
            if not keyword:
                continue
            entries.append(
                KeywordEntry(
                    keyword=keyword,
                    search_volume=_to_int(row.get("search_volume")),
                    difficulty=_to_float(row.get("difficulty")),
                    position=_to_int(row.get("position")),
                    url=(row.get("url") or "").strip() or None,
                )
            )
    return entries


def make_manual_provider(domain_to_path: dict[str, str]) -> Provider:
    """Build a Provider that reads each domain's keywords from a mapped CSV file."""
    def provider(domain: str) -> list[KeywordEntry]:
        key = _domain_key(domain)
        path = domain_to_path.get(key)
        if path is None:
            raise FileNotFoundError(f"No keyword CSV provided for {key}")
        return parse_keyword_csv(path)
    return provider


def parse_ranked_keywords(payload: dict) -> list[KeywordEntry]:
    """Parse a DataForSEO Labs ranked_keywords/live response into KeywordEntry list.

    Defensive against missing keys; items without a keyword are skipped.
    """
    entries: list[KeywordEntry] = []
    for task in payload.get("tasks") or []:
        for result in task.get("result") or []:
            for item in result.get("items") or []:
                kd = item.get("keyword_data") or {}
                keyword = kd.get("keyword")
                if not keyword:
                    continue
                info = kd.get("keyword_info") or {}
                props = kd.get("keyword_properties") or {}
                serp = (item.get("ranked_serp_element") or {}).get("serp_item") or {}
                entries.append(
                    KeywordEntry(
                        keyword=keyword,
                        search_volume=info.get("search_volume"),
                        difficulty=props.get("keyword_difficulty"),
                        position=serp.get("rank_absolute"),
                        url=serp.get("url"),
                    )
                )
    return entries


DATAFORSEO_RANKED_KEYWORDS_URL = (
    "https://api.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live"
)


class DataForSEOProvider:
    """Provider backed by the DataForSEO Labs ranked_keywords endpoint.

    The network call is isolated in `_http_fetch`; tests inject `raw_fetch`
    to exercise parsing/composition offline.
    """

    def __init__(
        self,
        login: str,
        password: str,
        location_code: int = 2840,   # United States
        language_name: str = "English",
        limit: int = 1000,
        raw_fetch: Callable[[str], dict] | None = None,
    ) -> None:
        self._login = login
        self._password = password
        self._location_code = location_code
        self._language_name = language_name
        self._limit = limit
        self._raw_fetch = raw_fetch or self._http_fetch

    def _http_fetch(self, domain_key: str) -> dict:
        resp = httpx.post(
            DATAFORSEO_RANKED_KEYWORDS_URL,
            auth=(self._login, self._password),
            json=[{
                "target": domain_key,
                "location_code": self._location_code,
                "language_name": self._language_name,
                "limit": self._limit,
            }],
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()

    def __call__(self, domain: str) -> list[KeywordEntry]:
        return parse_ranked_keywords(self._raw_fetch(_domain_key(domain)))

    @classmethod
    def from_settings(cls) -> "DataForSEOProvider":
        login = get_secret("DATAFORSEO_LOGIN")
        password = get_secret("DATAFORSEO_PASSWORD")
        if not login or not password:
            raise RuntimeError(
                "DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD must be set for api keyword source"
            )
        return cls(login, password)


def analyze_domain_keywords(domain: str, provider: Provider) -> DomainKeywords:
    """Fetch one domain's ranking keywords; never raises (errors are captured)."""
    try:
        keywords = provider(domain)
        return DomainKeywords(domain=domain, keywords=keywords, total_keywords=len(keywords))
    except Exception as exc:
        logging.warning("Keyword lookup failed for %s: %s", domain, exc)
        return DomainKeywords(domain=domain, error=str(exc))


def _find_keyword_gaps(
    client: DomainKeywords, competitors: list[DomainKeywords]
) -> list[KeywordGap]:
    """Keywords one or more competitors rank for that the client does not."""
    client_keywords = {e.keyword.lower() for e in client.keywords}
    aggregated: dict[str, KeywordGap] = {}
    for comp in competitors:
        for entry in comp.keywords:
            key = entry.keyword.lower()
            if key in client_keywords:
                continue
            gap = aggregated.get(key)
            if gap is None:
                gap = KeywordGap(
                    keyword=entry.keyword,
                    search_volume=entry.search_volume,
                    difficulty=entry.difficulty,
                )
                aggregated[key] = gap
            if comp.domain not in gap.competitors_ranking:
                gap.competitors_ranking.append(comp.domain)
            if entry.position is not None and (
                gap.best_competitor_position is None
                or entry.position < gap.best_competitor_position
            ):
                gap.best_competitor_position = entry.position
            if entry.search_volume is not None:
                gap.search_volume = max(gap.search_volume or 0, entry.search_volume)
            if gap.difficulty is None:
                gap.difficulty = entry.difficulty

    gaps = list(aggregated.values())
    for gap in gaps:
        gap.traffic_value = estimate_traffic_value(gap.search_volume, gap.best_competitor_position)
    gaps.sort(key=lambda g: g.traffic_value or 0, reverse=True)
    return gaps


def _find_quick_wins(client: DomainKeywords) -> list[QuickWin]:
    """Client keywords sitting at positions 5-20 (page 1-2 nudge opportunities)."""
    wins = [
        QuickWin(
            keyword=entry.keyword,
            position=entry.position,
            search_volume=entry.search_volume,
            url=entry.url,
            traffic_value=estimate_traffic_value(entry.search_volume, entry.position),
        )
        for entry in client.keywords
        if entry.position is not None and 5 <= entry.position <= 20
    ]
    wins.sort(key=lambda w: w.traffic_value or 0, reverse=True)
    return wins


def analyze_keywords(
    client_url: str, competitor_urls: list[str], provider: Provider
) -> KeywordResult:
    """Collect keywords for client + competitors and compute gaps/quick-wins."""
    client = analyze_domain_keywords(client_url, provider)
    competitors = [analyze_domain_keywords(url, provider) for url in competitor_urls]
    is_partial = bool(client.error) or any(c.error for c in competitors)
    gaps = [] if client.error else _find_keyword_gaps(client, competitors)
    quick_wins = [] if client.error else _find_quick_wins(client)
    return KeywordResult(
        client=client,
        competitors=competitors,
        gaps=gaps,
        quick_wins=quick_wins,
        is_partial=is_partial,
    )


def _provider_for_job(job_dir: Path, config: JobConfig) -> Provider:
    """Select a Provider from the job config: manual CSVs or the DataForSEO API."""
    if config.keyword_source == "manual":
        input_dir = Path(job_dir) / "keywords_input"
        mapping: dict[str, str] = {}
        for url in [config.client_url, *config.competitor_urls]:
            key = _domain_key(url)
            csv_path = input_dir / f"{_domain_to_filename(key)}.csv"
            if csv_path.exists():
                mapping[key] = str(csv_path)
            else:
                logging.warning("No keyword CSV found for %s at %s", key, csv_path)
        return make_manual_provider(mapping)
    if config.keyword_source == "api":
        return DataForSEOProvider.from_settings()
    raise ValueError(f"Unknown keyword_source: {config.keyword_source}")  # pragma: no cover


def run_keywords(job_dir: Path, provider: Provider | None = None) -> JobData:
    """Run keyword analysis for a job and persist the result to data.json."""
    data = load_data(job_dir)
    if provider is None:
        provider = _provider_for_job(Path(job_dir), data.config)
    data.keywords = analyze_keywords(
        data.config.client_url, data.config.competitor_urls, provider
    )
    save_data(job_dir, data)
    return data
