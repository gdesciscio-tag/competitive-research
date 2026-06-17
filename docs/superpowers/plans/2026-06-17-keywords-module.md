# Keywords Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a data-only Keywords module to `compresearch` that collects each domain's ranking keywords (via the DataForSEO API, or a manual CSV fallback), then computes keyword gaps, quick-wins, and traffic-value estimates into a job's `data.json`.

**Architecture:** Mirrors the sitemap module's pattern. A `Provider` is an injectable callable `(domain) -> list[KeywordEntry]`, so the comparison logic is provider-agnostic and fully offline-testable. Two providers: `DataForSEOProvider` (real API, raw-fetch isolated behind an injectable boundary) and a manual CSV provider. `analyze_keywords` composes per-domain lookups and computes gaps/quick-wins locally (same "fetch per domain, compare locally" shape as sitemap). Results are written to `data.json` under a new `keywords` section. No LLM in this module — semantic topic synthesis is the Topical Map module's job (Plan 3).

**Tech Stack:** Python 3.11+ (running on 3.14), pydantic v2, httpx, Python stdlib `csv`/`logging`, pytest. Builds on the Plan 1 foundation already merged to `master`.

---

## Context for the implementer

Already present in `compresearch` (do not recreate): `models.py` (pydantic schema + `JobData`), `settings.py` (`get_secret`), `job_store.py` (`slugify`, `create_job`, `load_data`, `save_data`), `sitemap.py`, `cli.py` (argparse with a `sitemap` subcommand and `run_from_args(argv, fetch=http_fetch) -> Path`). 29 tests pass. `JobConfig.keyword_source` is already `Literal["api", "manual"]`.

The module under construction is `compresearch/keywords.py` with tests in `tests/test_keywords.py`. Run tests with `.venv\Scripts\python -m pytest` (Windows venv). Work on a feature branch off `master`. Commit per task with the messages given.

**Manual CSV template** (the agreed format — one file per domain): columns `keyword, search_volume, difficulty, position, url`. Files live in `jobs/<slug>/keywords_input/<domain-slug>.csv`, where `<domain-slug>` is `slugify(domain_key)` and `domain_key` is the netloc without scheme or leading `www.` (e.g. `https://acme.com` → `acme-com.csv`).

**DataForSEO note (Task 4/5):** the parser targets the DataForSEO Labs `ranked_keywords/live` response shape (`tasks[].result[].items[]`, each item with `keyword_data.keyword`, `keyword_data.keyword_info.search_volume`, `keyword_data.keyword_properties.keyword_difficulty`, and `ranked_serp_element.serp_item.rank_absolute` / `.url`). This is implemented defensively (`.get` chains, no hard failures on missing keys) and tested against a representative fixture. If the live API shape differs slightly, it's a fixture-driven adjustment isolated to the parser.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `compresearch/models.py` (modify) | Add `KeywordEntry`, `DomainKeywords`, `KeywordGap`, `QuickWin`, `KeywordResult`; add `keywords` field to `JobData` |
| `compresearch/keywords.py` (create) | Providers (DataForSEO + manual CSV), traffic-value estimate, gap/quick-win analysis, `run_keywords` |
| `compresearch/cli.py` (modify) | Add a `keywords` subcommand |
| `tests/test_keywords.py` (create) | All keywords logic via fake providers + temp CSVs (offline) |
| `tests/test_cli.py` (modify) | End-to-end `keywords` CLI run in manual mode (offline) |
| `README.md` (modify) | Document the keywords usage + manual CSV template; update status checklist |

---

## Task 1: Keyword data models

**Files:**
- Modify: `compresearch/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
from compresearch.models import (
    KeywordEntry, DomainKeywords, KeywordGap, QuickWin, KeywordResult,
)


def test_keyword_models_round_trip():
    result = KeywordResult(
        client=DomainKeywords(
            domain="https://acme.com",
            keywords=[KeywordEntry(keyword="crm software", search_volume=1000,
                                   difficulty=40.0, position=8, url="https://acme.com/crm")],
            total_keywords=1,
        ),
        competitors=[DomainKeywords(domain="https://rival.com")],
        gaps=[KeywordGap(keyword="free crm", search_volume=500,
                         competitors_ranking=["https://rival.com"],
                         best_competitor_position=3, traffic_value=55.0)],
        quick_wins=[QuickWin(keyword="crm software", position=8,
                             search_volume=1000, traffic_value=30.0)],
        is_partial=False,
    )
    restored = KeywordResult.model_validate_json(result.model_dump_json())
    assert restored.client.keywords[0].keyword == "crm software"
    assert restored.gaps[0].best_competitor_position == 3
    assert restored.quick_wins[0].position == 8
    assert restored.is_partial is False


def test_jobdata_has_optional_keywords():
    from compresearch.models import JobConfig, JobData
    data = JobData(config=JobConfig(client_name="X", client_url="https://x.com"))
    assert data.keywords is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_models.py -k keyword`
Expected: FAIL — `ImportError: cannot import name 'KeywordEntry'`.

- [ ] **Step 3: Write the implementation**

Add to `compresearch/models.py` (after the sitemap models, before `JobConfig`):

```python
class KeywordEntry(BaseModel):
    keyword: str
    search_volume: int | None = None
    difficulty: float | None = None
    position: int | None = None
    url: str | None = None


class DomainKeywords(BaseModel):
    domain: str
    keywords: list[KeywordEntry] = Field(default_factory=list)
    total_keywords: int = 0
    error: str | None = None


class KeywordGap(BaseModel):
    keyword: str
    search_volume: int | None = None
    difficulty: float | None = None
    competitors_ranking: list[str] = Field(default_factory=list)
    best_competitor_position: int | None = None
    traffic_value: float | None = None


class QuickWin(BaseModel):
    keyword: str
    position: int
    search_volume: int | None = None
    url: str | None = None
    traffic_value: float | None = None


class KeywordResult(BaseModel):
    client: DomainKeywords | None = None
    competitors: list[DomainKeywords] = Field(default_factory=list)
    gaps: list[KeywordGap] = Field(default_factory=list)
    quick_wins: list[QuickWin] = Field(default_factory=list)
    is_partial: bool = False
```

And extend `JobData`:

```python
class JobData(BaseModel):
    config: JobConfig
    sitemap: SitemapResult | None = None
    keywords: KeywordResult | None = None
    # Future sections (topical_map, draft_post) added in later plans.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_models.py`
Expected: PASS (all model tests green).

- [ ] **Step 5: Commit**

```bash
git add compresearch/models.py tests/test_models.py
git commit -m "feat: add keyword data models to schema"
```

---

## Task 2: Traffic-value estimate

**Files:**
- Create: `compresearch/keywords.py`
- Test: `tests/test_keywords.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_keywords.py
from compresearch.keywords import estimate_traffic_value


def test_traffic_value_uses_position_ctr():
    # position 1 ~ 0.28 CTR
    assert estimate_traffic_value(1000, 1) == 280.0
    # position 8 ~ 0.03 CTR
    assert estimate_traffic_value(1000, 8) == 30.0
    # positions 11-20 ~ 0.01
    assert estimate_traffic_value(1000, 15) == 10.0
    # beyond 20 ~ 0.005
    assert estimate_traffic_value(1000, 50) == 5.0


def test_traffic_value_none_when_inputs_missing():
    assert estimate_traffic_value(None, 5) is None
    assert estimate_traffic_value(1000, None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_keywords.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'compresearch.keywords'`.

- [ ] **Step 3: Write the implementation**

```python
# compresearch/keywords.py
from __future__ import annotations

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
    if position <= 10:
        ctr = _CTR_BY_POSITION.get(position, 0.02)
    elif position <= 20:
        ctr = 0.01
    else:
        ctr = 0.005
    return round(volume * ctr, 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_keywords.py`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/keywords.py tests/test_keywords.py
git commit -m "feat: add keyword traffic-value estimate"
```

---

## Task 3: Manual CSV provider

**Files:**
- Modify: `compresearch/keywords.py`
- Test: `tests/test_keywords.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_keywords.py`:

```python
from compresearch.keywords import parse_keyword_csv, make_manual_provider, _domain_key

CSV_CONTENT = """keyword,search_volume,difficulty,position,url
crm software,1000,40,8,https://acme.com/crm
free crm,,,,
sales tools,500,25,3,https://acme.com/sales
"""


def test_domain_key_strips_scheme_and_www():
    assert _domain_key("https://www.acme.com/path") == "acme.com"
    assert _domain_key("acme.com") == "acme.com"


def test_parse_keyword_csv(tmp_path):
    csv_path = tmp_path / "acme-com.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    entries = parse_keyword_csv(str(csv_path))
    assert len(entries) == 3
    assert entries[0].keyword == "crm software"
    assert entries[0].search_volume == 1000
    assert entries[0].position == 8
    # blank numeric fields become None
    assert entries[1].keyword == "free crm"
    assert entries[1].search_volume is None
    assert entries[1].url is None


def test_make_manual_provider_maps_by_domain(tmp_path):
    csv_path = tmp_path / "acme-com.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    provider = make_manual_provider({"acme.com": str(csv_path)})
    entries = provider("https://www.acme.com")
    assert len(entries) == 3


def test_make_manual_provider_raises_for_missing_domain():
    provider = make_manual_provider({})
    import pytest
    with pytest.raises(FileNotFoundError):
        provider("https://acme.com")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_keywords.py -k "csv or domain_key or manual_provider"`
Expected: FAIL — `ImportError: cannot import name 'parse_keyword_csv'`.

- [ ] **Step 3: Write the implementation**

Append to `compresearch/keywords.py` (add the imports at the top with the existing ones):

```python
import csv
from typing import Callable
from urllib.parse import urlparse

from compresearch.models import KeywordEntry

Provider = Callable[[str], list[KeywordEntry]]


def _domain_key(url: str) -> str:
    """Netloc without scheme or leading 'www.' — used for matching and filenames."""
    netloc = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_keywords.py -k "csv or domain_key or manual_provider"`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/keywords.py tests/test_keywords.py
git commit -m "feat: add manual CSV keyword provider"
```

---

## Task 4: DataForSEO response parser

**Files:**
- Modify: `compresearch/keywords.py`
- Test: `tests/test_keywords.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_keywords.py`:

```python
from compresearch.keywords import parse_ranked_keywords

DATAFORSEO_PAYLOAD = {
    "tasks": [
        {
            "result": [
                {
                    "items": [
                        {
                            "keyword_data": {
                                "keyword": "crm software",
                                "keyword_info": {"search_volume": 1000},
                                "keyword_properties": {"keyword_difficulty": 40},
                            },
                            "ranked_serp_element": {
                                "serp_item": {"rank_absolute": 8, "url": "https://acme.com/crm"}
                            },
                        },
                        {
                            "keyword_data": {
                                "keyword": "free crm",
                                "keyword_info": {"search_volume": 500},
                                "keyword_properties": {"keyword_difficulty": 25},
                            },
                            "ranked_serp_element": {
                                "serp_item": {"rank_absolute": 3, "url": "https://acme.com/free"}
                            },
                        },
                    ]
                }
            ]
        }
    ]
}


def test_parse_ranked_keywords():
    entries = parse_ranked_keywords(DATAFORSEO_PAYLOAD)
    assert len(entries) == 2
    assert entries[0].keyword == "crm software"
    assert entries[0].search_volume == 1000
    assert entries[0].difficulty == 40
    assert entries[0].position == 8
    assert entries[0].url == "https://acme.com/crm"


def test_parse_ranked_keywords_tolerates_missing_fields():
    payload = {"tasks": [{"result": [{"items": [
        {"keyword_data": {"keyword": "bare term"}},
        {"keyword_data": {}},  # no keyword -> skipped
    ]}]}]}
    entries = parse_ranked_keywords(payload)
    assert len(entries) == 1
    assert entries[0].keyword == "bare term"
    assert entries[0].search_volume is None
    assert entries[0].position is None


def test_parse_ranked_keywords_empty_payload():
    assert parse_ranked_keywords({}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_keywords.py -k ranked_keywords`
Expected: FAIL — `ImportError: cannot import name 'parse_ranked_keywords'`.

- [ ] **Step 3: Write the implementation**

Append to `compresearch/keywords.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_keywords.py -k ranked_keywords`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/keywords.py tests/test_keywords.py
git commit -m "feat: parse DataForSEO ranked-keywords responses"
```

---

## Task 5: DataForSEO provider

**Files:**
- Modify: `compresearch/keywords.py`
- Test: `tests/test_keywords.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_keywords.py`:

```python
from compresearch.keywords import DataForSEOProvider


def test_dataforseo_provider_uses_injected_raw_fetch():
    calls = []

    def fake_raw_fetch(domain_key: str) -> dict:
        calls.append(domain_key)
        return DATAFORSEO_PAYLOAD

    provider = DataForSEOProvider(login="x", password="y", raw_fetch=fake_raw_fetch)
    entries = provider("https://www.acme.com")
    assert calls == ["acme.com"]            # scheme/www stripped before the API call
    assert len(entries) == 2
    assert entries[0].keyword == "crm software"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_keywords.py -k dataforseo_provider`
Expected: FAIL — `ImportError: cannot import name 'DataForSEOProvider'`.

- [ ] **Step 3: Write the implementation**

Add `import httpx` and `from compresearch.settings import get_secret` to the top of `compresearch/keywords.py`, then append:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_keywords.py -k dataforseo_provider`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/keywords.py tests/test_keywords.py
git commit -m "feat: add DataForSEO keyword provider with injectable fetch"
```

---

## Task 6: Domain analysis, gaps, and quick-wins

**Files:**
- Modify: `compresearch/keywords.py`
- Test: `tests/test_keywords.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_keywords.py`:

```python
from compresearch.keywords import analyze_keywords
from compresearch.models import KeywordEntry


def make_provider(domain_to_entries):
    """Fake Provider: dict of domain_key -> list[KeywordEntry]; raises for unknowns."""
    def provider(domain):
        key = _domain_key(domain)
        if key not in domain_to_entries:
            raise RuntimeError(f"no data for {key}")
        return domain_to_entries[key]
    return provider


def test_analyze_keywords_gaps_and_quick_wins():
    provider = make_provider({
        "acme.com": [
            KeywordEntry(keyword="crm software", search_volume=1000, position=8, url="https://acme.com/crm"),
            KeywordEntry(keyword="sales tools", search_volume=500, position=3),
        ],
        "rival.com": [
            KeywordEntry(keyword="crm software", search_volume=1000, position=2),
            KeywordEntry(keyword="free crm", search_volume=800, position=4),
        ],
    })
    result = analyze_keywords("https://acme.com", ["https://rival.com"], provider)

    # gap = keyword a competitor ranks for that the client does not
    assert [g.keyword for g in result.gaps] == ["free crm"]
    assert result.gaps[0].competitors_ranking == ["https://rival.com"]
    assert result.gaps[0].best_competitor_position == 4
    assert result.gaps[0].traffic_value is not None

    # quick win = client ranks position 5-20 ("crm software" at 8; "sales tools" at 3 excluded)
    assert [w.keyword for w in result.quick_wins] == ["crm software"]
    assert result.quick_wins[0].position == 8
    assert result.is_partial is False


def test_analyze_keywords_marks_partial_and_skips_gaps_on_client_failure():
    provider = make_provider({
        "rival.com": [KeywordEntry(keyword="free crm", search_volume=800, position=4)],
    })  # acme.com missing -> client lookup fails
    result = analyze_keywords("https://acme.com", ["https://rival.com"], provider)
    assert result.client.error is not None
    assert result.gaps == []
    assert result.quick_wins == []
    assert result.is_partial is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_keywords.py -k analyze_keywords`
Expected: FAIL — `ImportError: cannot import name 'analyze_keywords'`.

- [ ] **Step 3: Write the implementation**

Add `import logging` to the top of `compresearch/keywords.py`, import the additional models (`from compresearch.models import KeywordEntry, DomainKeywords, KeywordGap, QuickWin, KeywordResult` — replace the earlier single-model import), then append:

```python
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
            if gap.search_volume is None:
                gap.search_volume = entry.search_volume
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
    wins.sort(key=lambda w: w.search_volume or 0, reverse=True)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_keywords.py -k analyze_keywords`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/keywords.py tests/test_keywords.py
git commit -m "feat: compute keyword gaps and quick-wins"
```

---

## Task 7: `run_keywords` orchestration + provider selection

**Files:**
- Modify: `compresearch/keywords.py`
- Test: `tests/test_keywords.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_keywords.py`:

```python
from compresearch.keywords import run_keywords
from compresearch.job_store import create_job, load_data
from compresearch.models import JobConfig


def test_run_keywords_with_injected_provider(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    competitor_urls=["https://rival.com"])
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    provider = make_provider({
        "acme.com": [KeywordEntry(keyword="crm software", search_volume=1000, position=8)],
        "rival.com": [KeywordEntry(keyword="free crm", search_volume=800, position=4)],
    })
    run_keywords(job_dir, provider=provider)

    data = load_data(job_dir)
    assert data.keywords is not None
    assert [g.keyword for g in data.keywords.gaps] == ["free crm"]
    assert [w.keyword for w in data.keywords.quick_wins] == ["crm software"]


def test_run_keywords_manual_source_reads_input_dir(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    competitor_urls=["https://rival.com"], keyword_source="manual")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    input_dir = job_dir / "keywords_input"
    input_dir.mkdir()
    (input_dir / "acme-com.csv").write_text(
        "keyword,search_volume,difficulty,position,url\ncrm software,1000,40,8,\n",
        encoding="utf-8",
    )
    (input_dir / "rival-com.csv").write_text(
        "keyword,search_volume,difficulty,position,url\nfree crm,800,30,4,\n",
        encoding="utf-8",
    )
    run_keywords(job_dir)  # no provider -> manual provider built from input dir

    data = load_data(job_dir)
    assert [g.keyword for g in data.keywords.gaps] == ["free crm"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_keywords.py -k run_keywords`
Expected: FAIL — `ImportError: cannot import name 'run_keywords'`.

- [ ] **Step 3: Write the implementation**

Add `from pathlib import Path` and `from compresearch.job_store import load_data, save_data, slugify` and `from compresearch.models import JobConfig, JobData` to the top imports of `compresearch/keywords.py` (merge with existing model import line), then append:

```python
def _provider_for_job(job_dir: Path, config: JobConfig) -> Provider:
    """Select a Provider from the job config: manual CSVs or the DataForSEO API."""
    if config.keyword_source == "manual":
        input_dir = Path(job_dir) / "keywords_input"
        mapping: dict[str, str] = {}
        for url in [config.client_url, *config.competitor_urls]:
            key = _domain_key(url)
            csv_path = input_dir / f"{slugify(key)}.csv"
            if csv_path.exists():
                mapping[key] = str(csv_path)
        return make_manual_provider(mapping)
    return DataForSEOProvider.from_settings()


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_keywords.py -k run_keywords`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python -m pytest`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add compresearch/keywords.py tests/test_keywords.py
git commit -m "feat: add run_keywords orchestration with provider selection"
```

---

## Task 8: CLI `keywords` subcommand

**Files:**
- Modify: `compresearch/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
from compresearch.job_store import create_job
from compresearch.models import JobConfig


def test_keywords_subcommand_manual_mode(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    competitor_urls=["https://rival.com"], keyword_source="manual")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    input_dir = job_dir / "keywords_input"
    input_dir.mkdir()
    (input_dir / "acme-com.csv").write_text(
        "keyword,search_volume,difficulty,position,url\ncrm software,1000,40,8,\n", encoding="utf-8")
    (input_dir / "rival-com.csv").write_text(
        "keyword,search_volume,difficulty,position,url\nfree crm,800,30,4,\n", encoding="utf-8")

    returned = run_from_args(["keywords", "--job-dir", str(job_dir)])
    assert returned == job_dir
    data = load_data(returned)
    assert [g.keyword for g in data.keywords.gaps] == ["free crm"]
```

(`run_from_args` and `load_data` are already imported at the top of `tests/test_cli.py` from Task 12 of Plan 1.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py -k keywords`
Expected: FAIL — argparse exits with an error on the unknown `keywords` subcommand (or `SystemExit`).

- [ ] **Step 3: Write the implementation**

In `compresearch/cli.py`, import `run_keywords` (`from compresearch.keywords import run_keywords`) at the top, then add the subparser and dispatch. After the existing `sitemap` subparser block, add:

```python
    kw = sub.add_parser("keywords", help="Run keyword analysis on an existing job")
    kw.add_argument("--job-dir", required=True)
```

Refactor the dispatch in `run_from_args` so it branches on `args.command`. Replace the existing post-parse body with:

```python
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
        run_keywords(job_dir, provider=provider)
        return job_dir

    raise ValueError(f"Unknown command: {args.command}")  # pragma: no cover
```

Update the `run_from_args` signature to accept an injectable provider for testing/orchestration:

```python
def run_from_args(argv: list[str], fetch: Fetcher = http_fetch, provider=None) -> Path:
```

(The manual-mode test passes no provider and relies on `run_keywords` building the manual provider from the job's `keywords_input/` directory — fully offline.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py`
Expected: PASS (both the existing sitemap CLI test and the new keywords test).

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python -m pytest`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add compresearch/cli.py tests/test_cli.py
git commit -m "feat: add keywords CLI subcommand"
```

---

## Task 9: Docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the README**

In `README.md`, add a Keywords section after the sitemap usage and update the status checklist. Add:

```markdown
## Run the keywords module

Keyword analysis runs on a job that already exists (create it first via the sitemap
run, or any job folder).

**API mode (default):** set `DATAFORSEO_LOGIN` and `DATAFORSEO_PASSWORD` in `.env`, then:

```
.venv\Scripts\python -m compresearch.cli keywords --job-dir jobs\acme-co
```

**Manual mode (KeySearch fallback):** set `keyword_source: manual` in the job's `job.yaml`,
then drop one CSV per domain into `jobs\<slug>\keywords_input\`, named by the domain
(scheme and `www.` removed, dots → hyphens). Example: `acme-com.csv`, `rival-com.csv`.

CSV columns (header row required):

```
keyword,search_volume,difficulty,position,url
crm software,1000,40,8,https://acme.com/crm
free crm,800,30,,
```

Leave a numeric cell blank if unknown. Then run the same command above.
```

And change the status checklist line for keywords from `- [ ]` to `- [x]`:

```markdown
- [x] Keywords module
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document keywords module usage and manual CSV template"
```

---

## Self-Review Notes

- **Spec coverage:** DataForSEO API as primary source (Tasks 4–5) with manual KeySearch CSV fallback (Task 3) → satisfies the spec's "API primary, manual fallback" decision. Keyword-gap analysis (Task 6), quick-wins at positions 5–20 (Task 6), and estimated traffic value (Task 2) → the spec's quality upgrades. Data-only scope honored: no LLM in this module; semantic clustering deferred to the Topical Map module (Plan 3). Results persist to `data.json` under `keywords` (Tasks 1, 7), consistent with the single-source-of-truth design. Error isolation + `is_partial` + logged warnings mirror the sitemap module's hardened behavior.
- **Placeholder scan:** No TBDs; every code and test step is complete.
- **Type/name consistency:** `Provider`, `KeywordEntry`, `DomainKeywords`, `KeywordGap`, `QuickWin`, `KeywordResult`, `_domain_key`, `estimate_traffic_value`, `parse_keyword_csv`, `make_manual_provider`, `parse_ranked_keywords`, `DataForSEOProvider`, `analyze_domain_keywords`, `_find_keyword_gaps`, `_find_quick_wins`, `analyze_keywords`, `run_keywords`, `_provider_for_job` are used consistently across tasks and tests. `run_from_args` gains a `provider` param used by the `keywords` branch.
- **Known follow-ups for later plans:** location/language are fixed to US/English defaults in `DataForSEOProvider` (expose as job config if international clients arise); the DataForSEO response-shape assumption (Task 4) should be confirmed against a live call when an account is available — it's isolated to `parse_ranked_keywords` and fixture-driven. The deferred `tests/conftest.py` dedup of test fakes (from Plan 1) still stands.
