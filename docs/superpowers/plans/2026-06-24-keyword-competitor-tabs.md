# Richer Keyword Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-competitor and client ranked-keyword tabs to the Google Sheet, plus a Client-Provided Keywords tab that ingests a wishlist file, enriches it via DataForSEO `keyword_overview`, and cross-references it against the ranked data already pulled.

**Architecture:** All work happens inside the existing **keywords step** (`compresearch/keywords.py`) and the pure sheet model (`compresearch/sheets.py`). A new `ProvidedKeyword` model carries the enriched + cross-referenced wishlist. Enrichment and cross-reference are split into pure, individually testable functions with the network call injected. No orchestrator, CLI, or PDF changes.

**Tech Stack:** Python, Pydantic v2, httpx (DataForSEO Labs API), pytest, gspread (Sheets writer — untouched here).

**Spec:** `docs/superpowers/specs/2026-06-24-keyword-competitor-tabs-design.md`

---

## File Structure

- `compresearch/models.py` — add `ProvidedKeyword`; add `provided` field to `KeywordResult`.
- `compresearch/keywords.py` — add `parse_keyword_overview`, `DataForSEOProvider.enrich_keywords`, `read_provided_keywords`, `analyze_provided_keywords`, an `Enricher` type alias, and wire them into `run_keywords`.
- `compresearch/sheets.py` — add `_sheet_tab_name` + `_keyword_list_rows` helpers; emit competitor tabs, the client tab, and the provided-keywords tab inside `build_sheet_model`.
- `tests/test_keywords.py` — tests for the new parser, file reader, and cross-reference/enrichment logic.
- `tests/test_sheets.py` — tests for the new tabs in `build_sheet_model`.

Run the whole suite with: `.venv/Scripts/python -m pytest -q`

---

## Task 1: `ProvidedKeyword` model + `KeywordResult.provided`

**Files:**
- Modify: `compresearch/models.py` (the `KeywordResult` block, ~lines 57–79)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
def test_provided_keyword_and_result_field_defaults():
    from compresearch.models import ProvidedKeyword, KeywordResult
    pk = ProvidedKeyword(keyword="rf engineering recruiter")
    assert pk.search_volume is None
    assert pk.difficulty is None
    assert pk.client_position is None
    assert pk.competitors_ranking == []
    assert pk.best_competitor_position is None
    # KeywordResult gains a `provided` list that defaults to empty
    assert KeywordResult().provided == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_models.py::test_provided_keyword_and_result_field_defaults -v`
Expected: FAIL — `ImportError: cannot import name 'ProvidedKeyword'`.

- [ ] **Step 3: Add the model and field**

In `compresearch/models.py`, immediately after the `QuickWin` class (before `class KeywordResult`):

```python
class ProvidedKeyword(BaseModel):
    keyword: str
    search_volume: int | None = None
    difficulty: float | None = None
    client_position: int | None = None
    competitors_ranking: list[str] = Field(default_factory=list)
    best_competitor_position: int | None = None
```

Then add this line inside `class KeywordResult` (after the `quick_wins` field):

```python
    provided: list[ProvidedKeyword] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_models.py::test_provided_keyword_and_result_field_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add compresearch/models.py tests/test_models.py
git commit -m "feat: add ProvidedKeyword model and KeywordResult.provided field"
```

---

## Task 2: `parse_keyword_overview` (enrichment response parser)

**Files:**
- Modify: `compresearch/keywords.py` (add after `parse_ranked_keywords`, ~line 124)
- Test: `tests/test_keywords.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_keywords.py`:

```python
from compresearch.keywords import parse_keyword_overview


def test_parse_keyword_overview_reads_volume_and_difficulty():
    payload = {
        "tasks": [{
            "result": [{
                "items": [
                    {
                        "keyword": "rf engineering recruiter",
                        "keyword_info": {"search_volume": 320},
                        "keyword_properties": {"keyword_difficulty": 18},
                    },
                    {
                        "keyword": "photonics recruiter",
                        "keyword_info": {"search_volume": 90},
                        "keyword_properties": {"keyword_difficulty": 12},
                    },
                    {"keyword": None},  # skipped — no keyword
                ]
            }]
        }]
    }
    entries = parse_keyword_overview(payload)
    assert [e.keyword for e in entries] == ["rf engineering recruiter", "photonics recruiter"]
    assert entries[0].search_volume == 320
    assert entries[0].difficulty == 18
    assert entries[1].search_volume == 90
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_keywords.py::test_parse_keyword_overview_reads_volume_and_difficulty -v`
Expected: FAIL — `ImportError: cannot import name 'parse_keyword_overview'`.

- [ ] **Step 3: Implement the parser**

In `compresearch/keywords.py`, after `parse_ranked_keywords` (before the `DATAFORSEO_RANKED_KEYWORDS_URL` constant):

```python
def parse_keyword_overview(payload: dict) -> list[KeywordEntry]:
    """Parse a DataForSEO Labs keyword_overview/live response into KeywordEntry list.

    keyword_overview items are flatter than ranked_keywords (no `keyword_data`
    wrapper): the keyword, keyword_info, and keyword_properties sit at the item
    top level. Items without a keyword are skipped.
    """
    entries: list[KeywordEntry] = []
    for task in payload.get("tasks") or []:
        for result in task.get("result") or []:
            for item in result.get("items") or []:
                keyword = item.get("keyword")
                if not keyword:
                    continue
                info = item.get("keyword_info") or {}
                props = item.get("keyword_properties") or {}
                entries.append(
                    KeywordEntry(
                        keyword=keyword,
                        search_volume=info.get("search_volume"),
                        difficulty=props.get("keyword_difficulty"),
                    )
                )
    return entries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_keywords.py::test_parse_keyword_overview_reads_volume_and_difficulty -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add compresearch/keywords.py tests/test_keywords.py
git commit -m "feat: parse DataForSEO keyword_overview responses"
```

---

## Task 3: `read_provided_keywords` (file reader)

**Files:**
- Modify: `compresearch/keywords.py` (add near `_provider_for_job`, ~line 267)
- Test: `tests/test_keywords.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_keywords.py`:

```python
from compresearch.keywords import read_provided_keywords


def test_read_provided_keywords_skips_blanks_comments_and_dedupes(tmp_path):
    input_dir = tmp_path / "keywords_input"
    input_dir.mkdir()
    (input_dir / "client_provided.txt").write_text(
        "# client wishlist\n"
        "RF Engineering Recruiter\n"
        "\n"
        "Photonics Recruiter\n"
        "rf engineering recruiter\n",  # duplicate (case-insensitive) — dropped
        encoding="utf-8",
    )
    assert read_provided_keywords(tmp_path) == [
        "RF Engineering Recruiter",
        "Photonics Recruiter",
    ]


def test_read_provided_keywords_missing_file_returns_empty(tmp_path):
    assert read_provided_keywords(tmp_path) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_keywords.py -k read_provided_keywords -v`
Expected: FAIL — `ImportError: cannot import name 'read_provided_keywords'`.

- [ ] **Step 3: Implement the reader**

In `compresearch/keywords.py`, just above `_provider_for_job`:

```python
def read_provided_keywords(job_dir: Path) -> list[str]:
    """Read the operator-supplied client keyword wishlist.

    Source: ``<job_dir>/keywords_input/client_provided.txt`` — one keyword per
    line. Blank lines and lines starting with '#' are ignored; duplicates are
    dropped case-insensitively while preserving first-seen order. Returns [] when
    the file is absent.
    """
    path = Path(job_dir) / "keywords_input" / "client_provided.txt"
    if not path.exists():
        return []
    terms: list[str] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8-sig") as handle:
        for line in handle:
            term = line.strip()
            if not term or term.startswith("#"):
                continue
            if term.lower() not in seen:
                seen.add(term.lower())
                terms.append(term)
    return terms
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_keywords.py -k read_provided_keywords -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add compresearch/keywords.py tests/test_keywords.py
git commit -m "feat: read client-provided keyword wishlist file"
```

---

## Task 4: `analyze_provided_keywords` (cross-reference + enrichment merge)

**Files:**
- Modify: `compresearch/keywords.py` (add `Enricher` alias near the `Provider` alias ~line 41; add the function near `analyze_keywords` ~line 249); import `ProvidedKeyword`.
- Test: `tests/test_keywords.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_keywords.py`:

```python
from compresearch.keywords import analyze_provided_keywords
from compresearch.models import KeywordEntry, DomainKeywords


def _dk(domain, entries):
    return DomainKeywords(domain=domain, keywords=entries, total_keywords=len(entries))


def test_analyze_provided_keywords_cross_references_and_enriches():
    client = _dk("atshire.com", [
        KeywordEntry(keyword="photonics recruiter", search_volume=50, position=7),
    ])
    competitors = [
        _dk("bluesignal.com", [
            KeywordEntry(keyword="rf engineering recruiter", search_volume=300, position=4),
        ]),
        _dk("broadstaffglobal.com", [
            KeywordEntry(keyword="rf engineering recruiter", search_volume=300, position=9),
        ]),
    ]

    def enricher(terms):
        # Authoritative volume/difficulty for every term, even ones nobody ranks for
        return [
            KeywordEntry(keyword="rf engineering recruiter", search_volume=320, difficulty=18),
            KeywordEntry(keyword="photonics recruiter", search_volume=90, difficulty=12),
            KeywordEntry(keyword="semiconductor recruiter", search_volume=140, difficulty=22),
        ]

    result = analyze_provided_keywords(
        ["RF Engineering Recruiter", "Photonics Recruiter", "Semiconductor Recruiter"],
        client, competitors, enricher,
    )
    by_kw = {p.keyword: p for p in result}

    rf = by_kw["RF Engineering Recruiter"]
    assert rf.search_volume == 320 and rf.difficulty == 18      # from enrichment
    assert rf.client_position is None                            # client doesn't rank
    assert sorted(rf.competitors_ranking) == ["bluesignal.com", "broadstaffglobal.com"]
    assert rf.best_competitor_position == 4                      # best (lowest) of 4 and 9

    ph = by_kw["Photonics Recruiter"]
    assert ph.client_position == 7                               # client ranks
    assert ph.competitors_ranking == []

    semi = by_kw["Semiconductor Recruiter"]
    assert semi.search_volume == 140                             # enrichment only
    assert semi.client_position is None and semi.competitors_ranking == []


def test_analyze_provided_keywords_without_enricher_falls_back_to_ranked_volume():
    client = _dk("atshire.com", [])
    competitors = [_dk("bluesignal.com", [
        KeywordEntry(keyword="rf engineering recruiter", search_volume=300, position=4),
    ])]
    # enricher=None (manual mode / no creds): volume falls back to matched ranked data
    result = analyze_provided_keywords(["RF Engineering Recruiter"], client, competitors, None)
    assert result[0].search_volume == 300
    assert result[0].best_competitor_position == 4


def test_analyze_provided_keywords_survives_enricher_error():
    client = _dk("atshire.com", [])
    def boom(terms):
        raise RuntimeError("dataforseo down")
    result = analyze_provided_keywords(["RF Engineering Recruiter"], client, [], boom)
    assert len(result) == 1
    assert result[0].search_volume is None       # enrichment failed, no ranked match
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_keywords.py -k analyze_provided_keywords -v`
Expected: FAIL — `ImportError: cannot import name 'analyze_provided_keywords'`.

- [ ] **Step 3: Implement the function**

In `compresearch/keywords.py`, update the model import to include `ProvidedKeyword`:

```python
from compresearch.models import (
    KeywordEntry, DomainKeywords, KeywordGap, QuickWin, KeywordResult,
    ProvidedKeyword, JobConfig, JobData,
)
```

Add the type alias next to the existing `Provider` alias (~line 41):

```python
Enricher = Callable[[list[str]], list[KeywordEntry]]
```

Add the function just above `_provider_for_job`:

```python
def analyze_provided_keywords(
    terms: list[str],
    client: DomainKeywords | None,
    competitors: list[DomainKeywords],
    enricher: Enricher | None = None,
) -> list[ProvidedKeyword]:
    """Build ProvidedKeyword rows for the client's wishlist.

    Volume/difficulty come from the enricher (authoritative, covers every term);
    when the enricher is absent or fails, they fall back to any matching ranked
    entry. Client/competitor ranks are always cross-referenced from the ranked
    data already pulled. Enrichment failure is logged, never fatal.
    """
    if not terms:
        return []

    enriched: dict[str, KeywordEntry] = {}
    if enricher is not None:
        try:
            for entry in enricher(terms):
                enriched[entry.keyword.lower()] = entry
        except Exception as exc:
            logging.warning("Provided-keyword enrichment failed: %s", exc)

    client_kw = {e.keyword.lower(): e for e in (client.keywords if client else [])}

    results: list[ProvidedKeyword] = []
    for term in terms:
        key = term.lower()
        comp_domains: list[str] = []
        best: int | None = None
        ranked_match: KeywordEntry | None = client_kw.get(key)
        for comp in competitors:
            for entry in comp.keywords:
                if entry.keyword.lower() != key:
                    continue
                if comp.domain not in comp_domains:
                    comp_domains.append(comp.domain)
                if entry.position is not None and (best is None or entry.position < best):
                    best = entry.position
                ranked_match = ranked_match or entry
                break
        source = enriched.get(key) or ranked_match
        client_entry = client_kw.get(key)
        results.append(
            ProvidedKeyword(
                keyword=term,
                search_volume=(source.search_volume if source else None),
                difficulty=(source.difficulty if source else None),
                client_position=(client_entry.position if client_entry else None),
                competitors_ranking=comp_domains,
                best_competitor_position=best,
            )
        )
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_keywords.py -k analyze_provided_keywords -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add compresearch/keywords.py tests/test_keywords.py
git commit -m "feat: cross-reference and enrich client-provided keywords"
```

---

## Task 5: `DataForSEOProvider.enrich_keywords` (network call)

**Files:**
- Modify: `compresearch/keywords.py` (add the URL constant near `DATAFORSEO_RANKED_KEYWORDS_URL` ~line 127; extend `DataForSEOProvider`)
- Test: `tests/test_keywords.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_keywords.py`:

```python
from compresearch.keywords import DataForSEOProvider


def test_enrich_keywords_uses_injected_fetch_and_parses():
    captured = {}

    def raw_enrich(keywords):
        captured["keywords"] = keywords
        return {
            "tasks": [{
                "result": [{
                    "items": [
                        {"keyword": "rf engineering recruiter",
                         "keyword_info": {"search_volume": 320},
                         "keyword_properties": {"keyword_difficulty": 18}},
                    ]
                }]
            }]
        }

    provider = DataForSEOProvider("login", "pw", raw_enrich=raw_enrich)
    entries = provider.enrich_keywords(["rf engineering recruiter"])
    assert captured["keywords"] == ["rf engineering recruiter"]
    assert entries[0].search_volume == 320
    assert entries[0].difficulty == 18


def test_enrich_keywords_empty_input_makes_no_call():
    def raw_enrich(keywords):
        raise AssertionError("should not be called for empty input")
    provider = DataForSEOProvider("login", "pw", raw_enrich=raw_enrich)
    assert provider.enrich_keywords([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_keywords.py -k enrich_keywords -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'raw_enrich'`.

- [ ] **Step 3: Implement the method**

In `compresearch/keywords.py`, add the URL constant beneath `DATAFORSEO_RANKED_KEYWORDS_URL`:

```python
DATAFORSEO_KEYWORD_OVERVIEW_URL = (
    "https://api.dataforseo.com/v3/dataforseo_labs/google/keyword_overview/live"
)
```

In `DataForSEOProvider.__init__`, add a `raw_enrich` parameter mirroring `raw_fetch`. Change the signature line and add the assignment:

```python
        raw_fetch: Callable[[str], dict] | None = None,
        raw_enrich: Callable[[list[str]], dict] | None = None,
    ) -> None:
        self._login = login
        self._password = password
        self._location_code = location_code
        self._language_name = language_name
        self._limit = limit
        self._raw_fetch = raw_fetch or self._http_fetch
        self._raw_enrich = raw_enrich or self._http_enrich
```

Add these two methods to `DataForSEOProvider` (after `_http_fetch`):

```python
    def _http_enrich(self, keywords: list[str]) -> dict:
        resp = httpx.post(
            DATAFORSEO_KEYWORD_OVERVIEW_URL,
            auth=(self._login, self._password),
            json=[{
                "keywords": keywords,
                "location_code": self._location_code,
                "language_name": self._language_name,
            }],
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()

    def enrich_keywords(self, keywords: list[str]) -> list[KeywordEntry]:
        """Look up volume + difficulty for arbitrary keywords (one batched call)."""
        if not keywords:
            return []
        return parse_keyword_overview(self._raw_enrich(keywords))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_keywords.py -k enrich_keywords -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add compresearch/keywords.py tests/test_keywords.py
git commit -m "feat: DataForSEOProvider.enrich_keywords via keyword_overview"
```

---

## Task 6: Wire provided keywords into `run_keywords`

**Files:**
- Modify: `compresearch/keywords.py` (`run_keywords`, ~lines 285–293)
- Test: `tests/test_keywords.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_keywords.py` (uses the existing `make_provider` fixture and `create_job`):

```python
from compresearch.keywords import run_keywords
from compresearch.job_store import create_job, load_data
from compresearch.models import JobConfig, KeywordEntry


def test_run_keywords_populates_provided_from_file(tmp_path, make_provider):
    cfg = JobConfig(
        client_name="ATS Hire",
        client_url="https://atshire.com/",
        competitor_urls=["https://bluesignal.com/"],
    )
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    input_dir = job_dir / "keywords_input"
    input_dir.mkdir(exist_ok=True)
    (input_dir / "client_provided.txt").write_text("RF Engineering Recruiter\n", encoding="utf-8")

    provider = make_provider({
        "atshire.com": [],
        "bluesignal.com": [KeywordEntry(keyword="rf engineering recruiter",
                                        search_volume=300, position=4)],
    })

    def enricher(terms):
        return [KeywordEntry(keyword="rf engineering recruiter",
                             search_volume=320, difficulty=18)]

    run_keywords(job_dir, provider=provider, enricher=enricher)
    data = load_data(job_dir)
    assert len(data.keywords.provided) == 1
    pk = data.keywords.provided[0]
    assert pk.keyword == "RF Engineering Recruiter"
    assert pk.search_volume == 320
    assert pk.competitors_ranking == ["bluesignal.com"]


def test_run_keywords_no_provided_file_leaves_provided_empty(tmp_path, make_provider):
    cfg = JobConfig(client_name="ATS Hire", client_url="https://atshire.com/")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    provider = make_provider({"atshire.com": []})
    run_keywords(job_dir, provider=provider, enricher=lambda terms: [])
    assert load_data(job_dir).keywords.provided == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_keywords.py -k "run_keywords_populates_provided or run_keywords_no_provided" -v`
Expected: FAIL — `run_keywords()` rejects the `enricher=` kwarg (`TypeError`).

- [ ] **Step 3: Update `run_keywords`**

Replace the body of `run_keywords` in `compresearch/keywords.py` with:

```python
def run_keywords(
    job_dir: Path,
    provider: Provider | None = None,
    enricher: Enricher | None = None,
) -> JobData:
    """Run keyword analysis for a job and persist the result to data.json."""
    data = load_data(job_dir)
    if provider is None:
        provider = _provider_for_job(Path(job_dir), data.config)
    data.keywords = analyze_keywords(
        data.config.client_url, data.config.competitor_urls, provider
    )

    terms = read_provided_keywords(Path(job_dir))
    if terms:
        if enricher is None and data.config.keyword_source == "api":
            try:
                enricher = DataForSEOProvider.from_settings().enrich_keywords
            except Exception as exc:
                logging.warning("No enricher available for provided keywords: %s", exc)
        data.keywords.provided = analyze_provided_keywords(
            terms, data.keywords.client, data.keywords.competitors, enricher
        )

    save_data(job_dir, data)
    return data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_keywords.py -v`
Expected: PASS (all keyword tests, including the two new ones)

- [ ] **Step 5: Commit**

```bash
git add compresearch/keywords.py tests/test_keywords.py
git commit -m "feat: ingest and enrich provided keywords in the keywords step"
```

---

## Task 7: Competitor + client keyword tabs in `build_sheet_model`

**Files:**
- Modify: `compresearch/sheets.py` (add helpers above `build_sheet_model` ~line 154; emit tabs inside the `if data.keywords is not None:` block after Quick Wins, ~line 221)
- Test: `tests/test_sheets.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_sheets.py` (mirror the existing `_full_jobdata` / `by_name` style):

```python
def _keywords_with_lists():
    from compresearch.models import JobConfig, JobData, KeywordResult, DomainKeywords, KeywordEntry
    cfg = JobConfig(
        client_name="ATS Hire",
        client_url="https://atshire.com/",
        competitor_urls=["https://bluesignal.com/"],
    )
    kw = KeywordResult(
        client=DomainKeywords(domain="atshire.com", keywords=[
            KeywordEntry(keyword="rf recruiter", search_volume=200, difficulty=20, position=6,
                         url="https://atshire.com/rf"),
            KeywordEntry(keyword="photonics jobs", search_volume=900, difficulty=30, position=12),
        ]),
        competitors=[DomainKeywords(domain="bluesignal.com", keywords=[
            KeywordEntry(keyword="wireless recruiter", search_volume=400, difficulty=25, position=3),
        ])],
    )
    return JobData(config=cfg, keywords=kw)


def test_build_sheet_model_emits_client_and_competitor_keyword_tabs():
    tabs = build_sheet_model(_keywords_with_lists())
    names = [t.name for t in tabs]
    assert "ATS Hire — Keywords" in names
    assert "bluesignal.com" in names
    # Order: client tab precedes competitor tabs; both precede Topical Map / Draft Post
    assert names.index("ATS Hire — Keywords") < names.index("bluesignal.com")

    by_name = {t.name: t for t in tabs}
    client_tab = by_name["ATS Hire — Keywords"]
    assert client_tab.rows[0] == ["Keyword", "Volume", "Difficulty", "Position", "URL"]
    # Sorted by volume descending: photonics jobs (900) before rf recruiter (200)
    assert [r[0] for r in client_tab.rows[1:]] == ["photonics jobs", "rf recruiter"]


def test_keyword_tabs_skipped_when_lists_empty():
    from compresearch.models import JobConfig, JobData, KeywordResult, DomainKeywords
    cfg = JobConfig(client_name="ATS Hire", client_url="https://atshire.com/")
    data = JobData(config=cfg, keywords=KeywordResult(
        client=DomainKeywords(domain="atshire.com", keywords=[]),
        competitors=[DomainKeywords(domain="bluesignal.com", keywords=[])],
    ))
    names = [t.name for t in build_sheet_model(data)]
    assert "ATS Hire — Keywords" not in names
    assert "bluesignal.com" not in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_sheets.py -k "keyword_tabs or client_and_competitor" -v`
Expected: FAIL — the new tab names are absent from `build_sheet_model` output.

- [ ] **Step 3: Add helpers and emit tabs**

In `compresearch/sheets.py`, add these helpers just above `def build_sheet_model` (~line 154):

```python
# Google Sheets tab names cannot contain these characters and cap at 100 chars.
_INVALID_TAB_CHARS = str.maketrans({c: " " for c in ":\\/?*[]"})


def _sheet_tab_name(name: str) -> str:
    return name.translate(_INVALID_TAB_CHARS).strip()[:100] or "Sheet"


def _keyword_list_rows(dk) -> list[list]:
    """Rows for a single domain's ranked keyword list, sorted by volume desc."""
    rows = [["Keyword", "Volume", "Difficulty", "Position", "URL"]]
    for e in sorted(dk.keywords, key=lambda k: k.search_volume or 0, reverse=True):
        if e.url:
            safe_url = e.url.replace('"', "%22")
            url_cell = f'=HYPERLINK("{safe_url}", "{safe_url}")'
        else:
            url_cell = ""
        rows.append([e.keyword, _cell(e.search_volume), _cell(e.difficulty),
                     _cell(e.position), url_cell])
    return rows
```

Then, inside `build_sheet_model`'s `if data.keywords is not None:` block, immediately **after** the Quick Wins `tabs.append(...)` and **before** the `# --- Topical map ---` block, insert:

```python
        # --- Client's own ranked keywords ---
        if data.keywords.client is not None and data.keywords.client.keywords:
            tabs.append(SheetTab(
                _sheet_tab_name(f"{config.client_name} — Keywords"),
                _keyword_list_rows(data.keywords.client),
                header=True, basic_filter=True,
                number_formats={1: "#,##0", 2: "0", 3: "0"},
            ))

        # --- One tab per competitor ---
        for comp in data.keywords.competitors:
            if not comp.keywords:
                continue
            tabs.append(SheetTab(
                _sheet_tab_name(short_domain(comp.domain)),
                _keyword_list_rows(comp),
                header=True, basic_filter=True,
                number_formats={1: "#,##0", 2: "0", 3: "0"},
            ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_sheets.py -k "keyword_tabs or client_and_competitor" -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Update the full-job tab-order assertion**

The existing `test_build_sheet_model_full_job_has_all_tabs` pins the exact tab-name list. If `_full_jobdata()` includes client/competitor keyword lists, that assertion now sees the new tabs. Run it:

Run: `.venv/Scripts/python -m pytest tests/test_sheets.py::test_build_sheet_model_full_job_has_all_tabs -v`

If it FAILS, update the expected list in that test to include the new tabs in their emitted position (client tab + competitor tabs, after "Quick Wins", before "Topical Map"). If it PASSES (because `_full_jobdata()`'s competitors/client have empty keyword lists), leave it unchanged.

- [ ] **Step 6: Commit**

```bash
git add compresearch/sheets.py tests/test_sheets.py
git commit -m "feat: per-competitor and client ranked-keyword tabs"
```

---

## Task 8: Client-Provided Keywords tab in `build_sheet_model`

**Files:**
- Modify: `compresearch/sheets.py` (emit the tab inside the keywords block, **before** the client tab from Task 7)
- Test: `tests/test_sheets.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_sheets.py`:

```python
def test_build_sheet_model_emits_provided_keywords_tab():
    from compresearch.models import (
        JobConfig, JobData, KeywordResult, DomainKeywords, ProvidedKeyword,
    )
    cfg = JobConfig(client_name="ATS Hire", client_url="https://atshire.com/")
    data = JobData(config=cfg, keywords=KeywordResult(
        client=DomainKeywords(domain="atshire.com", keywords=[]),
        provided=[
            ProvidedKeyword(
                keyword="RF Engineering Recruiter", search_volume=320, difficulty=18,
                client_position=None, competitors_ranking=["bluesignal.com"],
                best_competitor_position=4,
            ),
        ],
    ))
    tabs = build_sheet_model(data)
    by_name = {t.name: t for t in tabs}
    assert "Client-Provided Keywords" in by_name
    tab = by_name["Client-Provided Keywords"]
    assert tab.rows[0] == ["Keyword", "Volume", "Difficulty", "Client rank",
                           "Competitors ranking", "Best competitor rank"]
    assert tab.rows[1] == ["RF Engineering Recruiter", 320, 18, "", "bluesignal.com", 4]


def test_provided_tab_absent_when_no_provided_keywords():
    from compresearch.models import JobConfig, JobData, KeywordResult
    data = JobData(config=JobConfig(client_name="ATS Hire", client_url="https://atshire.com/"),
                   keywords=KeywordResult())
    assert "Client-Provided Keywords" not in [t.name for t in build_sheet_model(data)]
```

Note: `_cell(None)` renders as `""` and `_cell(320)` returns `320` (int passthrough) — that is why the expected row mixes `""` and bare ints.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_sheets.py -k provided -v`
Expected: FAIL — "Client-Provided Keywords" tab is absent.

- [ ] **Step 3: Emit the tab**

In `compresearch/sheets.py`, inside the `if data.keywords is not None:` block, insert this **before** the `# --- Client's own ranked keywords ---` block added in Task 7 (so the provided tab comes first):

```python
        # --- Client-provided keyword wishlist (only when supplied) ---
        if data.keywords.provided:
            prov_rows = [["Keyword", "Volume", "Difficulty", "Client rank",
                          "Competitors ranking", "Best competitor rank"]]
            for p in data.keywords.provided:
                prov_rows.append([
                    p.keyword, _cell(p.search_volume), _cell(p.difficulty),
                    _cell(p.client_position),
                    ", ".join(short_domain(d) for d in p.competitors_ranking),
                    _cell(p.best_competitor_position),
                ])
            tabs.append(SheetTab(
                "Client-Provided Keywords", prov_rows, header=True, basic_filter=True,
                number_formats={1: "#,##0", 2: "0", 3: "0", 5: "0"},
            ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_sheets.py -k provided -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add compresearch/sheets.py tests/test_sheets.py
git commit -m "feat: Client-Provided Keywords tab in the Sheet"
```

---

## Task 9: Full suite + README note

**Files:**
- Modify: `README.md` (document the optional `client_provided.txt` input)

- [ ] **Step 1: Run the entire test suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: PASS (all tests green). If `test_build_sheet_model_full_job_has_all_tabs` fails, finish the Task 7 Step 5 fix.

- [ ] **Step 2: Document the input file**

In `README.md`, under the keyword/usage section, add a short note:

```markdown
### Client-provided keywords (optional)

To include a "Client-Provided Keywords" tab in the Sheet, drop a plain-text file
at `jobs/<slug>/keywords_input/client_provided.txt` before running — one keyword
per line (blank lines and lines starting with `#` are ignored). In `api` keyword
mode each phrase is enriched with search volume and difficulty via DataForSEO and
cross-referenced against the client's and competitors' rankings. In `manual` mode
the tab still renders, with volume/difficulty filled in only where a phrase
matches the supplied ranking data.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document optional client-provided keywords input"
```

---

## Self-Review Notes

- **Spec coverage:** per-competitor tabs (Task 7), client tab (Task 7), provided tab (Task 8), file ingestion (Task 3), enrichment via keyword_overview (Tasks 2 & 5), cross-reference (Task 4), resilience/manual-mode fallback (Tasks 4 & 6), data model (Task 1). All spec sections map to a task.
- **Type consistency:** `Enricher = Callable[[list[str]], list[KeywordEntry]]` used consistently in Tasks 4–6; `enrich_keywords` returns `list[KeywordEntry]` matching the `Enricher` shape; `ProvidedKeyword` fields match between Task 1, Task 4, and Task 8.
- **Ordering:** within the keywords block the emit order is Quick Wins → Client-Provided Keywords → client tab → competitor tabs → (Topical Map / Draft Post follow in later blocks), matching the spec layout.
