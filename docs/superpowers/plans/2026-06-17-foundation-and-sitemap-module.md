# Foundation + Sitemap Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Python project foundation (data model, job folders, config) and a working Sitemap module that fetches and parses competitor sitemaps, categorizes URLs by section, infers publishing cadence, and computes content gaps — all written to a job's `data.json`.

**Architecture:** A `compresearch` Python package. Each job lives in `jobs/<slug>/` with a `job.yaml` (inputs) and `data.json` (single source of truth). Pydantic models define the schema. The sitemap module is pure logic that takes an injectable `fetch` function (real HTTP in production, an in-memory fake in tests) so the whole pipeline is testable offline with zero network calls.

**Tech Stack:** Python 3.11+, pydantic v2, httpx, lxml, PyYAML, python-dotenv, pytest.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `requirements.txt` | Pinned dependencies |
| `pyproject.toml` | Package metadata + pytest config |
| `compresearch/__init__.py` | Package marker |
| `compresearch/models.py` | Pydantic schema: `UrlEntry`, `DomainSitemap`, `SitemapGap`, `SitemapResult`, `JobConfig`, `JobData` |
| `compresearch/settings.py` | Load `.env`, expose `get_secret` |
| `compresearch/job_store.py` | Create/load/save job folders and `data.json` |
| `compresearch/sitemap.py` | Sitemap discovery, fetch/parse, categorize, cadence, gap analysis, `run_sitemap` |
| `compresearch/cli.py` | `python -m compresearch.cli` entry to create a job and run the sitemap module |
| `tests/test_models.py` | Schema round-trip + defaults |
| `tests/test_settings.py` | `.env` loading |
| `tests/test_job_store.py` | Job folder lifecycle |
| `tests/test_sitemap.py` | All sitemap logic with a fake fetcher |
| `tests/test_cli.py` | End-to-end job run with a fake fetcher |

---

## Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `pyproject.toml`
- Create: `compresearch/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `requirements.txt`**

```
httpx==0.27.2
lxml==5.3.0
pydantic==2.9.2
PyYAML==6.0.2
python-dotenv==1.0.1
pytest==8.3.3
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "compresearch"
version = "0.1.0"
description = "TAG Online competitive research automation"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v"

[tool.setuptools.packages.find]
include = ["compresearch*"]
```

- [ ] **Step 3: Create empty package markers**

Create `compresearch/__init__.py` containing:

```python
"""TAG Online competitive research automation."""
```

Create `tests/__init__.py` as an empty file.

- [ ] **Step 4: Create and populate a virtual environment**

Run (Windows PowerShell):
```
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```
Expected: all packages install without error.

- [ ] **Step 5: Verify pytest runs (collects zero tests)**

Run: `.venv\Scripts\python -m pytest`
Expected: "no tests ran" — exit code 5, no errors.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt pyproject.toml compresearch/__init__.py tests/__init__.py
git commit -m "chore: scaffold compresearch package and tooling"
```

---

## Task 2: Data models

**Files:**
- Create: `compresearch/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from datetime import date
from compresearch.models import (
    UrlEntry, DomainSitemap, SitemapGap, SitemapResult, JobConfig, JobData,
)


def test_jobconfig_defaults():
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    assert cfg.competitor_urls == []
    assert cfg.keyword_source == "api"


def test_jobdata_round_trip_through_json():
    cfg = JobConfig(
        client_name="Acme Co",
        client_url="https://acme.com",
        competitor_urls=["https://rival.com"],
    )
    sitemap = SitemapResult(
        client=DomainSitemap(
            domain="https://acme.com",
            urls=[UrlEntry(loc="https://acme.com/blog/x", lastmod=date(2026, 1, 1))],
            section_counts={"blog": 1},
            total_urls=1,
            posts_per_month=2.5,
        ),
        competitors=[DomainSitemap(domain="https://rival.com")],
        gaps=[SitemapGap(section="services", competitors_with=["https://rival.com"], client_count=0)],
    )
    data = JobData(config=cfg, sitemap=sitemap)

    restored = JobData.model_validate_json(data.model_dump_json())
    assert restored.config.client_name == "Acme Co"
    assert restored.sitemap.client.urls[0].lastmod == date(2026, 1, 1)
    assert restored.sitemap.gaps[0].section == "services"


def test_jobdata_sitemap_optional():
    data = JobData(config=JobConfig(client_name="X", client_url="https://x.com"))
    assert data.sitemap is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_models.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'compresearch.models'`.

- [ ] **Step 3: Write the implementation**

```python
# compresearch/models.py
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class UrlEntry(BaseModel):
    loc: str
    lastmod: date | None = None


class DomainSitemap(BaseModel):
    domain: str
    urls: list[UrlEntry] = Field(default_factory=list)
    section_counts: dict[str, int] = Field(default_factory=dict)
    total_urls: int = 0
    posts_per_month: float | None = None
    error: str | None = None


class SitemapGap(BaseModel):
    section: str
    competitors_with: list[str] = Field(default_factory=list)
    client_count: int = 0


class SitemapResult(BaseModel):
    client: DomainSitemap | None = None
    competitors: list[DomainSitemap] = Field(default_factory=list)
    gaps: list[SitemapGap] = Field(default_factory=list)


class JobConfig(BaseModel):
    client_name: str
    client_url: str
    competitor_urls: list[str] = Field(default_factory=list)
    keyword_source: str = "api"  # "api" | "manual"


class JobData(BaseModel):
    config: JobConfig
    sitemap: SitemapResult | None = None
    # Future sections (keywords, topical_map, draft_post) added in later plans.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_models.py`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/models.py tests/test_models.py
git commit -m "feat: add job data schema with pydantic models"
```

---

## Task 3: Settings loader

**Files:**
- Create: `compresearch/settings.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings.py
from compresearch.settings import get_secret


def test_get_secret_reads_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    assert get_secret("ANTHROPIC_API_KEY") == "sk-test-123"


def test_get_secret_missing_returns_none(monkeypatch):
    monkeypatch.delenv("DEFINITELY_MISSING_KEY", raising=False)
    assert get_secret("DEFINITELY_MISSING_KEY") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_settings.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'compresearch.settings'`.

- [ ] **Step 3: Write the implementation**

```python
# compresearch/settings.py
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()  # loads .env from the working directory if present


def get_secret(key: str) -> str | None:
    """Return a secret/config value from the environment, or None if unset."""
    return os.environ.get(key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_settings.py`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/settings.py tests/test_settings.py
git commit -m "feat: add .env-backed settings loader"
```

---

## Task 4: Job store

**Files:**
- Create: `compresearch/job_store.py`
- Test: `tests/test_job_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_job_store.py
from compresearch.job_store import slugify, create_job, load_config, load_data, save_data
from compresearch.models import JobConfig


def test_slugify():
    assert slugify("Acme Co. Ltd!") == "acme-co-ltd"
    assert slugify("  Multiple   Spaces ") == "multiple-spaces"


def test_create_job_writes_files(tmp_path):
    cfg = JobConfig(
        client_name="Acme Co",
        client_url="https://acme.com",
        competitor_urls=["https://rival.com"],
    )
    job_dir = create_job(cfg, jobs_dir=tmp_path)

    assert job_dir == tmp_path / "acme-co"
    assert (job_dir / "job.yaml").exists()
    assert (job_dir / "data.json").exists()
    assert (job_dir / "outputs").is_dir()


def test_load_config_and_data_round_trip(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)

    loaded_cfg = load_config(job_dir)
    assert loaded_cfg.client_name == "Acme Co"

    data = load_data(job_dir)
    assert data.config.client_url == "https://acme.com"
    assert data.sitemap is None


def test_save_data_persists_changes(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)

    data = load_data(job_dir)
    data.config.keyword_source = "manual"
    save_data(job_dir, data)

    assert load_data(job_dir).config.keyword_source == "manual"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_job_store.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'compresearch.job_store'`.

- [ ] **Step 3: Write the implementation**

```python
# compresearch/job_store.py
from __future__ import annotations

import re
from pathlib import Path

import yaml

from compresearch.models import JobConfig, JobData

DEFAULT_JOBS_DIR = Path("jobs")


def slugify(name: str) -> str:
    """Turn a client name into a filesystem-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug


def create_job(config: JobConfig, jobs_dir: Path = DEFAULT_JOBS_DIR) -> Path:
    """Create jobs/<slug>/ with job.yaml, data.json, and outputs/. Returns the job dir."""
    job_dir = Path(jobs_dir) / slugify(config.client_name)
    (job_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (job_dir / "job.yaml").write_text(
        yaml.safe_dump(config.model_dump(), sort_keys=False), encoding="utf-8"
    )
    save_data(job_dir, JobData(config=config))
    return job_dir


def load_config(job_dir: Path) -> JobConfig:
    raw = yaml.safe_load((Path(job_dir) / "job.yaml").read_text(encoding="utf-8"))
    return JobConfig.model_validate(raw)


def load_data(job_dir: Path) -> JobData:
    text = (Path(job_dir) / "data.json").read_text(encoding="utf-8")
    return JobData.model_validate_json(text)


def save_data(job_dir: Path, data: JobData) -> None:
    (Path(job_dir) / "data.json").write_text(
        data.model_dump_json(indent=2), encoding="utf-8"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_job_store.py`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/job_store.py tests/test_job_store.py
git commit -m "feat: add job folder store (create/load/save)"
```

---

## Task 5: Sitemap discovery

**Files:**
- Create: `compresearch/sitemap.py`
- Test: `tests/test_sitemap.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sitemap.py
from compresearch.sitemap import discover_sitemaps


def make_fetch(pages: dict[str, bytes]):
    """Build a fake fetcher backed by a dict; raises for unknown URLs."""
    def fetch(url: str) -> bytes:
        if url not in pages:
            raise FileNotFoundError(url)
        return pages[url]
    return fetch


def test_discover_reads_sitemaps_from_robots():
    fetch = make_fetch({
        "https://acme.com/robots.txt": b"User-agent: *\nSitemap: https://acme.com/sitemap_index.xml\n",
    })
    assert discover_sitemaps("https://acme.com", fetch) == ["https://acme.com/sitemap_index.xml"]


def test_discover_falls_back_to_default_when_no_robots():
    fetch = make_fetch({})  # robots.txt fetch raises -> fallback
    assert discover_sitemaps("https://acme.com", fetch) == ["https://acme.com/sitemap.xml"]


def test_discover_normalizes_bare_domain():
    fetch = make_fetch({})
    assert discover_sitemaps("acme.com", fetch) == ["https://acme.com/sitemap.xml"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_sitemap.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'compresearch.sitemap'`.

- [ ] **Step 3: Write the implementation**

```python
# compresearch/sitemap.py
from __future__ import annotations

import gzip
from datetime import date
from typing import Callable
from urllib.parse import urlparse

from lxml import etree

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_sitemap.py`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/sitemap.py tests/test_sitemap.py
git commit -m "feat: add sitemap discovery via robots.txt"
```

---

## Task 6: Sitemap fetch + parse (index recursion + gzip)

**Files:**
- Modify: `compresearch/sitemap.py`
- Test: `tests/test_sitemap.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sitemap.py`:

```python
import gzip as _gzip
from datetime import date
from compresearch.sitemap import fetch_sitemap_urls

URLSET = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://acme.com/blog/post-1</loc><lastmod>2026-01-10</lastmod></url>
  <url><loc>https://acme.com/blog/post-2</loc><lastmod>2026-02-10T08:00:00+00:00</lastmod></url>
  <url><loc>https://acme.com/about</loc></url>
</urlset>"""

INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://acme.com/sitemap-posts.xml</loc></sitemap>
</sitemapindex>"""


def test_fetch_parses_urlset_with_lastmod():
    fetch = make_fetch({"https://acme.com/sitemap.xml": URLSET})
    entries = fetch_sitemap_urls("https://acme.com/sitemap.xml", fetch)
    locs = [e.loc for e in entries]
    assert locs == [
        "https://acme.com/blog/post-1",
        "https://acme.com/blog/post-2",
        "https://acme.com/about",
    ]
    assert entries[0].lastmod == date(2026, 1, 10)
    assert entries[1].lastmod == date(2026, 2, 10)
    assert entries[2].lastmod is None


def test_fetch_recurses_into_sitemap_index():
    fetch = make_fetch({
        "https://acme.com/sitemap_index.xml": INDEX,
        "https://acme.com/sitemap-posts.xml": URLSET,
    })
    entries = fetch_sitemap_urls("https://acme.com/sitemap_index.xml", fetch)
    assert len(entries) == 3


def test_fetch_handles_gzip():
    fetch = make_fetch({"https://acme.com/sitemap.xml.gz": _gzip.compress(URLSET)})
    entries = fetch_sitemap_urls("https://acme.com/sitemap.xml.gz", fetch)
    assert len(entries) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_sitemap.py -k fetch`
Expected: FAIL — `ImportError: cannot import name 'fetch_sitemap_urls'`.

- [ ] **Step 3: Write the implementation**

Append to `compresearch/sitemap.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_sitemap.py -k fetch`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/sitemap.py tests/test_sitemap.py
git commit -m "feat: parse sitemaps with index recursion and gzip support"
```

---

## Task 7: Categorize URLs by section

**Files:**
- Modify: `compresearch/sitemap.py`
- Test: `tests/test_sitemap.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sitemap.py`:

```python
from compresearch.sitemap import categorize_urls
from compresearch.models import UrlEntry


def test_categorize_counts_first_path_segment():
    urls = [
        UrlEntry(loc="https://acme.com/blog/a"),
        UrlEntry(loc="https://acme.com/blog/b"),
        UrlEntry(loc="https://acme.com/services/x"),
        UrlEntry(loc="https://acme.com/"),
    ]
    counts = categorize_urls(urls)
    assert counts == {"blog": 2, "services": 1, "(root)": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_sitemap.py -k categorize`
Expected: FAIL — `ImportError: cannot import name 'categorize_urls'`.

- [ ] **Step 3: Write the implementation**

Append to `compresearch/sitemap.py`:

```python
def categorize_urls(urls: list[UrlEntry]) -> dict[str, int]:
    """Count URLs by their first path segment ('(root)' for the homepage)."""
    counts: dict[str, int] = {}
    for entry in urls:
        path = urlparse(entry.loc).path.strip("/")
        section = path.split("/")[0] if path else "(root)"
        counts[section] = counts.get(section, 0) + 1
    return counts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_sitemap.py -k categorize`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/sitemap.py tests/test_sitemap.py
git commit -m "feat: categorize sitemap URLs by section"
```

---

## Task 8: Infer publishing cadence

**Files:**
- Modify: `compresearch/sitemap.py`
- Test: `tests/test_sitemap.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sitemap.py`:

```python
from compresearch.sitemap import infer_cadence


def test_infer_cadence_posts_per_month():
    # 4 posts spanning ~2 months (60.88 days) -> ~2.0/month
    urls = [
        UrlEntry(loc="a", lastmod=date(2026, 1, 1)),
        UrlEntry(loc="b", lastmod=date(2026, 1, 20)),
        UrlEntry(loc="c", lastmod=date(2026, 2, 15)),
        UrlEntry(loc="d", lastmod=date(2026, 3, 1)),
    ]
    assert infer_cadence(urls) == 2.0


def test_infer_cadence_needs_two_dates():
    assert infer_cadence([UrlEntry(loc="a", lastmod=date(2026, 1, 1))]) is None
    assert infer_cadence([UrlEntry(loc="a")]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_sitemap.py -k cadence`
Expected: FAIL — `ImportError: cannot import name 'infer_cadence'`.

- [ ] **Step 3: Write the implementation**

Append to `compresearch/sitemap.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_sitemap.py -k cadence`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/sitemap.py tests/test_sitemap.py
git commit -m "feat: infer publishing cadence from lastmod dates"
```

---

## Task 9: Analyze a single domain (composition)

**Files:**
- Modify: `compresearch/sitemap.py`
- Test: `tests/test_sitemap.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sitemap.py`:

```python
from compresearch.sitemap import analyze_domain


def test_analyze_domain_happy_path():
    fetch = make_fetch({
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": URLSET,
    })
    result = analyze_domain("https://acme.com", fetch)
    assert result.error is None
    assert result.total_urls == 3
    assert result.section_counts == {"blog": 2, "about": 1}
    assert result.posts_per_month is not None


def test_analyze_domain_captures_errors():
    fetch = make_fetch({})  # every fetch raises
    result = analyze_domain("https://broken.com", fetch)
    assert result.error is not None
    assert result.total_urls == 0
```

Note: the second test exercises the case where `discover_sitemaps` falls back to `/sitemap.xml`, which then also fails to fetch — the error is captured rather than raised.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_sitemap.py -k analyze_domain`
Expected: FAIL — `ImportError: cannot import name 'analyze_domain'`.

- [ ] **Step 3: Write the implementation**

Append to `compresearch/sitemap.py`:

```python
def analyze_domain(domain_url: str, fetch: Fetcher) -> DomainSitemap:
    """Discover, fetch, parse, and summarize one domain's sitemap content."""
    try:
        seen: set[str] = set()
        urls: list[UrlEntry] = []
        for sitemap_url in discover_sitemaps(domain_url, fetch):
            urls.extend(fetch_sitemap_urls(sitemap_url, fetch, seen))
        deduped = list({e.loc: e for e in urls}.values())
        return DomainSitemap(
            domain=domain_url,
            urls=deduped,
            section_counts=categorize_urls(deduped),
            total_urls=len(deduped),
            posts_per_month=infer_cadence(deduped),
        )
    except Exception as exc:  # capture, never crash the whole job
        return DomainSitemap(domain=domain_url, error=str(exc))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_sitemap.py -k analyze_domain`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/sitemap.py tests/test_sitemap.py
git commit -m "feat: compose single-domain sitemap analysis with error capture"
```

---

## Task 10: Compare domains + gap analysis

**Files:**
- Modify: `compresearch/sitemap.py`
- Test: `tests/test_sitemap.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sitemap.py`:

```python
from compresearch.sitemap import compare_domains

CLIENT_MAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://acme.com/blog/a</loc></url>
</urlset>"""

RIVAL_MAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://rival.com/blog/a</loc></url>
  <url><loc>https://rival.com/case-studies/x</loc></url>
  <url><loc>https://rival.com/case-studies/y</loc></url>
</urlset>"""


def test_compare_domains_finds_gaps():
    fetch = make_fetch({
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": CLIENT_MAP,
        "https://rival.com/robots.txt": b"Sitemap: https://rival.com/sitemap.xml\n",
        "https://rival.com/sitemap.xml": RIVAL_MAP,
    })
    result = compare_domains("https://acme.com", ["https://rival.com"], fetch)

    assert result.client.total_urls == 1
    assert result.competitors[0].total_urls == 3
    # 'case-studies' is a section the competitor has and the client lacks
    assert [g.section for g in result.gaps] == ["case-studies"]
    assert result.gaps[0].client_count == 0
    assert result.gaps[0].competitors_with == ["https://rival.com"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_sitemap.py -k compare_domains`
Expected: FAIL — `ImportError: cannot import name 'compare_domains'`.

- [ ] **Step 3: Write the implementation**

Append to `compresearch/sitemap.py`:

```python
def _find_gaps(
    client: DomainSitemap, competitors: list[DomainSitemap]
) -> list[SitemapGap]:
    """Sections one or more competitors have that the client has zero of."""
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
    return SitemapResult(
        client=client,
        competitors=competitors,
        gaps=_find_gaps(client, competitors),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_sitemap.py -k compare_domains`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/sitemap.py tests/test_sitemap.py
git commit -m "feat: compare domains and compute content gaps"
```

---

## Task 11: HTTP fetcher + `run_sitemap` orchestration

**Files:**
- Modify: `compresearch/sitemap.py`
- Test: `tests/test_sitemap.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sitemap.py`:

```python
from compresearch.sitemap import run_sitemap
from compresearch.job_store import create_job, load_data
from compresearch.models import JobConfig


def test_run_sitemap_writes_results_to_data_json(tmp_path):
    cfg = JobConfig(
        client_name="Acme Co",
        client_url="https://acme.com",
        competitor_urls=["https://rival.com"],
    )
    job_dir = create_job(cfg, jobs_dir=tmp_path)

    fetch = make_fetch({
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": CLIENT_MAP,
        "https://rival.com/robots.txt": b"Sitemap: https://rival.com/sitemap.xml\n",
        "https://rival.com/sitemap.xml": RIVAL_MAP,
    })
    run_sitemap(job_dir, fetch=fetch)

    data = load_data(job_dir)
    assert data.sitemap is not None
    assert data.sitemap.client.total_urls == 1
    assert [g.section for g in data.sitemap.gaps] == ["case-studies"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_sitemap.py -k run_sitemap`
Expected: FAIL — `ImportError: cannot import name 'run_sitemap'`.

- [ ] **Step 3: Write the implementation**

Append to `compresearch/sitemap.py`:

```python
import httpx

from pathlib import Path

from compresearch.job_store import load_data, save_data
from compresearch.models import JobData


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
```

Note: place the `import httpx` / `from pathlib import Path` / job_store imports at the top of the file with the other imports when implementing — they are shown here inline only to keep the diff readable.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_sitemap.py -k run_sitemap`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python -m pytest`
Expected: PASS — all tests across all files green.

- [ ] **Step 6: Commit**

```bash
git add compresearch/sitemap.py tests/test_sitemap.py
git commit -m "feat: add HTTP fetcher and run_sitemap job orchestration"
```

---

## Task 12: CLI entry point

**Files:**
- Create: `compresearch/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
from compresearch.cli import run_from_args
from compresearch.job_store import load_data

CLIENT_MAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://acme.com/blog/a</loc></url>
</urlset>"""


def make_fetch(pages):
    def fetch(url):
        if url not in pages:
            raise FileNotFoundError(url)
        return pages[url]
    return fetch


def test_run_from_args_creates_job_and_runs_sitemap(tmp_path):
    fetch = make_fetch({
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": CLIENT_MAP,
    })
    job_dir = run_from_args(
        [
            "sitemap",
            "--client-name", "Acme Co",
            "--client-url", "https://acme.com",
            "--competitors", "",
            "--jobs-dir", str(tmp_path),
        ],
        fetch=fetch,
    )
    assert job_dir == tmp_path / "acme-co"
    data = load_data(job_dir)
    assert data.sitemap.client.total_urls == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'compresearch.cli'`.

- [ ] **Step 3: Write the implementation**

```python
# compresearch/cli.py
from __future__ import annotations

import argparse
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
    job_dir = run_from_args(__import__("sys").argv[1:])
    print(f"Job complete: {job_dir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py`
Expected: PASS (1 passed).

- [ ] **Step 5: Manual smoke test against a real site (optional, requires network)**

Run:
```
.venv\Scripts\python -m compresearch.cli sitemap --client-name "Test" --client-url "https://www.python.org" --competitors ""
```
Expected: prints `Job complete: jobs\test`, and `jobs/test/data.json` contains a populated `sitemap` section.

- [ ] **Step 6: Run the full suite + commit**

Run: `.venv\Scripts\python -m pytest`
Expected: all green.

```bash
git add compresearch/cli.py tests/test_cli.py
git commit -m "feat: add CLI to create a job and run the sitemap module"
```

---

## Task 13: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

```markdown
# Competitive Research Automation

TAG Online's competitive research & analysis engine. See the design at
`docs/superpowers/specs/2026-06-17-competitive-research-automation-design.md`.

## Setup

```
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in API keys as modules are added.

## Run the sitemap module

```
.venv\Scripts\python -m compresearch.cli sitemap \
  --client-name "Acme Co" \
  --client-url "https://acme.com" \
  --competitors "https://rival-a.com,https://rival-b.com"
```

Results land in `jobs/<slug>/data.json`.

## Test

```
.venv\Scripts\python -m pytest
```

## Status

- [x] Foundation (job store, schema, settings)
- [x] Sitemap module
- [ ] Keywords module
- [ ] Topical map module
- [ ] Draft post module
- [ ] Render module (Google Sheet + PDF)
- [ ] Orchestrator + Claude Code skill
```

- [ ] **Step 2: Create `.env.example`**

```
# Filled in as later modules are built
ANTHROPIC_API_KEY=
DATAFORSEO_LOGIN=
DATAFORSEO_PASSWORD=
GOOGLE_SERVICE_ACCOUNT_JSON=
```

- [ ] **Step 3: Commit**

```bash
git add README.md .env.example
git commit -m "docs: add README and .env example"
```

---

## Self-Review Notes

- **Spec coverage (Plan 1 scope):** Foundation (job folders, `data.json` source of truth, settings) → Tasks 1–4. Sitemap automation (discovery, parse, gzip, index recursion) → Tasks 5–6. Quality upgrades from the spec — section categorization (Task 7), publishing cadence (Task 8), content-gap analysis (Task 10) — all covered. Error isolation per the spec's error-handling requirement → Task 9. Offline/no-spend testing via injectable fetcher → throughout. Later-plan sections (keywords, topical map, draft post, render, orchestrator) are intentionally out of this plan.
- **Placeholder scan:** No TBDs; every code and test step is complete.
- **Type consistency:** `Fetcher`, `UrlEntry`, `DomainSitemap`, `SitemapGap`, `SitemapResult`, `JobConfig`, `JobData`, and function names (`discover_sitemaps`, `fetch_sitemap_urls`, `categorize_urls`, `infer_cadence`, `analyze_domain`, `compare_domains`, `run_sitemap`, `http_fetch`, `run_from_args`) are used consistently across tasks and tests.
- **Known follow-ups for later plans:** extend `JobData` with `keywords`, `topical_map`, `draft_post` sections; add the orchestrator that chains modules; the CLI gains subcommands per module.
