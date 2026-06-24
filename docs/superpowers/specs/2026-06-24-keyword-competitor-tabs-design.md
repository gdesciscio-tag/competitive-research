# Richer keyword tabs in the Sheets deliverable

**Date:** 2026-06-24
**Status:** Approved (brainstorming), pending implementation plan

## Problem

The Google Sheet deliverable surfaces keyword work through only two analysis
tabs — **Keyword Gaps** and **Quick Wins**. Two things are missing:

1. **Competitor keyword visibility.** The pipeline pulls up to 200 ranked
   keywords per competitor from DataForSEO and stores them in
   `KeywordResult.competitors[]`, but nothing renders them. The client's own
   full ranked list (`KeywordResult.client`) is likewise hidden — only Quick
   Wins (page 1–2 rankings) leak through.
2. **Client-provided keywords are never ingested.** The discovery process
   produces a client wishlist of target phrases (e.g. "RF Engineering
   Recruiter"), but the job only accepts `--business-description`. Those phrases
   have no input path, so they never appear and are never validated against real
   search data.

## Goals

- One tab **per competitor** showing that competitor's full ranked-keyword list.
- One tab for the **client's own** ranked keywords (symmetry with competitors).
- One **Client-Provided Keywords** tab: the wishlist phrases, enriched with
  volume + difficulty from DataForSEO, and cross-referenced against the ranked
  data we already pulled (who already ranks, and where).

## Non-goals

- No orchestrator, CLI, or PDF changes. All additions live inside the existing
  **keywords step**, so they appear under the existing `keywords` line in the
  run summary.
- No new keyword *analysis* (gaps/quick-wins logic is unchanged).
- No UI for editing the provided-keyword list — it's a file the operator drops
  in before the run.

## Design

### Tab layout and order

```
Overview · Sitemap · Keyword Gaps · Quick Wins
  → Client-Provided Keywords        (new — only if the input file exists)
  → ATS Hire — Keywords             (new — client's own ranked list)
  → bluesignal.com                  (new — one tab per competitor)
  → broadstaffglobal.com            (new)
  → actalentservices.com            (new)
Topical Map · Draft Post
```

- **Competitor tabs** (one each) and the **client tab** share columns:
  `Keyword · Volume · Difficulty · Position · URL`, sorted by **volume
  descending**. Pure presentation of data already in
  `KeywordResult.competitors[]` / `.client`. No model change.
  - Competitor tab name = `short_domain(domain)` (e.g. `bluesignal.com`).
  - Client tab name = `"<client_name> — Keywords"` (e.g. `ATS Hire — Keywords`).
  - Tab names are sanitized for Google Sheets (no `: \ / ? * [ ]`); names are
    already domains/plain text, so this is a guard, not a transform.
- **Client-Provided Keywords** columns:
  `Keyword · Volume · Difficulty · Client rank · Competitors ranking · Best competitor rank`.
  - Volume / Difficulty come from enrichment.
  - Client rank, Competitors ranking, Best competitor rank are cross-referenced
    from the ranked data already in memory — no extra API cost.

### Ingestion + enrichment (inside the keywords step)

1. **Read the input file.** `jobs/<slug>/keywords_input/client_provided.txt`,
   one keyword per line. Blank lines and lines beginning with `#` are ignored.
   File absent → the Client-Provided Keywords tab is skipped entirely (the rest
   of the job is unaffected).
2. **Enrich in one call.** A new `enrich_keywords(keywords: list[str])` method on
   `DataForSEOProvider` POSTs to
   `dataforseo_labs/google/keyword_overview/live` (up to 700 keywords/request;
   all ~20 provided phrases fit in one call), reusing the existing
   login/password auth. Response parsing mirrors `parse_ranked_keywords`:
   `keyword_info.search_volume` → `search_volume`,
   `keyword_properties.keyword_difficulty` → `difficulty`.
3. **Resilience.** If DataForSEO credentials/provider are unavailable (e.g.
   `keyword_source: manual`) or the enrichment call fails, skip enrichment and
   still render the tab with cross-reference columns only (volume/difficulty
   blank). Enrichment failure is logged, never fatal — consistent with the
   pipeline's partial-failure philosophy.
4. **Cross-reference.** For each provided phrase (case-insensitive match against
   `KeywordResult.client.keywords` and each competitor's keywords):
   - `client_position` = the client's rank for that phrase, if any.
   - `competitors_ranking` = competitor domains that rank for it.
   - `best_competitor_position` = the best (lowest) competitor rank.

### Data model

New model in `models.py`:

```python
class ProvidedKeyword(BaseModel):
    keyword: str
    search_volume: int | None = None
    difficulty: float | None = None
    client_position: int | None = None
    competitors_ranking: list[str] = Field(default_factory=list)
    best_competitor_position: int | None = None
```

Add to `KeywordResult`:

```python
    provided: list[ProvidedKeyword] = Field(default_factory=list)
```

No model change is needed for the competitor/client tabs — that data already
exists on `KeywordResult`.

### Touched files

- `compresearch/models.py` — add `ProvidedKeyword`; add `provided` to
  `KeywordResult`.
- `compresearch/keywords.py` — read provided-keyword file; add
  `DataForSEOProvider.enrich_keywords` + a `parse_keyword_overview` helper;
  cross-reference logic; wire `provided` into `analyze_keywords` /
  `run_keywords`.
- `compresearch/sheets.py` — in `build_sheet_model`, emit the per-competitor
  tabs, the client tab, and the provided-keywords tab in the order above.

## Testing

- `parse_keyword_overview` parses volume + difficulty from a representative
  response.
- Provided-keyword file parsing ignores blank and `#` lines.
- Cross-reference fills `client_position`, `competitors_ranking`,
  `best_competitor_position` correctly from a known ranked dataset.
- `build_sheet_model` emits one tab per competitor, the client tab, and the
  provided tab, in the specified order with the specified columns.
- Resilience: no input file → no provided tab; enrichment error →
  cross-reference-only provided tab still renders; competitor/client tabs render
  from existing data with no provider call.

## Sequencing note

The competitor + client tabs are a small, self-contained presentation change and
could ship independently. The Client-Provided Keywords tab is the larger piece
(file ingestion, new endpoint, new model). Both fit one coherent change set
across `keywords.py` / `models.py` / `sheets.py`.

## References

- DataForSEO Labs keyword_overview/live:
  https://docs.dataforseo.com/v3/dataforseo_labs-google-keyword_overview-live/
