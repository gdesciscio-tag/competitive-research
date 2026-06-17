# Competitive Research Automation — Design

**Date:** 2026-06-17
**Owner:** TAG Online
**Status:** Approved design, ready for implementation planning

## Goal & Priorities

Automate TAG Online's competitive research & analysis service to make it faster to
produce, more impressive as a deliverable, and consistent across operators.

Priorities, ranked:

1. **Efficiency** — produce the same work in a fraction of the time (enables selling
   the service more without the work ballooning).
2. **Quality / differentiation** — output should feel more insightful and premium than
   raw spreadsheets.
3. **Consistency** — same quality regardless of who runs the job.

Scale is not a near-term priority; current volume is ~2 reports/month, expected to grow.

## Operating Context

- **Built & maintained by** a technical person (with Claude Code).
- **Run day-to-day by** non-technical operators — so the long-term interface must be
  button-pushing simple.
- **Paid APIs are acceptable** when per-report cost is small (a few dollars to ~$15).
- Environment: Windows, Python.

## Chosen Approach

A **modular Python toolkit** orchestrated by Claude Code today, with a thin operator-facing
web form added in Phase 2. Rejected alternatives: a full custom web app (too much
infra/maintenance for current volume) and no-code orchestration (brittle for the LLM-heavy
analysis and branded report rendering, hard to test/version).

## Architecture

Every job is a self-contained folder whose single source of truth is one JSON data file.
Each of the four part-modules reads the job inputs, does its work, and writes its results
back into that JSON. A separate render module reads the finished JSON and produces both
deliverables. Nothing renders until data is complete, so the Sheet and PDF are always two
views of the same data.

```
Job config
   │  (client URL · competitors · brand style)
   ▼
┌──────────┬──────────┬─────────────┬──────────────┐
│ Sitemap  │ Keywords │ Topical map │  Draft post  │   ← four part-modules
│ parse XML│ SEO API  │ Claude API  │  Claude API  │
└──────────┴──────────┴─────────────┴──────────────┘
   │           │            │              │
   └───────────┴────► data.json ◄──────────┘         ← single source of truth
                         │
                         ▼
                   Render module
                    │         │
                    ▼         ▼
            Google Sheet   Branded PDF report
            (appendix)     (headline deliverable)

Orchestration: Claude Code (now) → one-click web form (later)
```

Design properties this buys us:

- **Efficiency:** one command runs the whole chain; a single module can be re-run without
  redoing the rest.
- **Quality/consistency:** analysis logic and presentation are fully separated — improving a
  prompt or restyling the report never risks breaking data collection; templates enforce a
  consistent structure every time.
- **Swappability:** each module has a clean input/output contract (swap keyword providers or
  the LLM without touching the rest).
- **Upgrade path:** "orchestration" is just the trigger; swapping Claude Code for a web form
  requires no change to the modules.

## Job Structure

```
jobs/<client-slug>/
  job.yaml        # inputs: client name, URL, competitor URLs, keyword source (api|manual), options
  data.json       # source of truth — all four modules write here
  outputs/        # generated Google Sheet link + branded PDF
```

Self-contained, reproducible, re-runnable, easy to find later.

## The Four Modules

### 1. Sitemap

- **Automated:** given client + competitor domains, auto-discover sitemaps
  (robots.txt → `/sitemap.xml` → recurse sitemap indexes, handle gzipped), fetch and parse
  every URL.
- **Quality upgrades:**
  - Categorize URLs by site section (`/blog`, `/services`, `/products`, …) so findings read
    as "Competitor A has 120 blog posts vs your 30," not raw totals.
  - Infer publishing cadence from `lastmod` dates where present.
  - Surface content gaps — sections competitors have that the client does not.
- **Output (to data.json):** per-domain URL lists, categorized counts, cadence, gap summary.
- **Reuse:** provides the client's existing page list/content used by the draft-post module
  for style-matching and internal-link suggestions.

### 2. Keywords

- **Automated (primary):** DataForSEO REST API — ranking keywords for client and each
  competitor with position, search volume, and difficulty.
- **Fallback:** manual KeySearch import adapter — operator pastes/imports a KeySearch export,
  normalized into the same schema. The module's contract is "produce keyword data in this
  schema," satisfied by either source.
- **Quality upgrades:** keyword-gap analysis (terms competitors rank for that client does not),
  quick wins (client at positions 5–20), topic clustering, estimated traffic value.
- **Output:** normalized keyword table + gap list + quick-wins list + clusters.

### 3. Topical Map

- **Automated:** Claude API with a structured prompt producing pillar topics → clusters →
  article ideas.
- **Quality upgrade (key):** the prompt is fed the real sitemap gaps + keyword gaps from
  modules 1–2, not just a business description. Every suggested topic is tied to a target
  keyword, search intent, and estimated volume — data-driven and defensible.
- **Output:** structured pillar → cluster → article-idea hierarchy with target keyword/intent/
  volume per idea, plus a ranked opportunity score used to pick the default draft topic.

### 4. Draft Post

- **Automated:** pick the highest-opportunity topic by default (no human checkpoint — re-run
  the module to draft additional articles). Claude generates an SEO-optimized outline, then the
  full draft.
- **Quality upgrades:** style-matching uses the client's own existing writing auto-pulled via
  the sitemap module (no manual example-gathering); output includes target keyword, suggested
  title tag + meta description, and internal-link suggestions pointing at the client's existing
  relevant pages.
- **Output:** draft article (outline + body), SEO metadata, internal-link suggestions.

## Deliverables (Render Module)

The render module reads the finished `data.json` and produces both outputs from one template set.

### A. Google Sheet (data appendix)

- Built via the Google Sheets API (service account).
- Tabs: **Overview**, **Sitemap comparison** (categorized counts + gaps), **Keyword gaps**,
  **Quick wins**, **Topical map**, **Draft post**.
- Formatted/branded: frozen headers, conditional formatting highlighting gaps/opportunities.

### B. Branded PDF report (headline deliverable)

- Narrative document: **cover → executive summary → competitive landscape → content/sitemap
  findings → keyword findings & gaps → recommended topical map → sample blog post →
  prioritized next steps.**
- Auto-generated charts (content volume by competitor, keyword counts, gap sizes) so it reads
  as a strategy document, not a data dump.
- Built as a **Jinja2 HTML/CSS template rendered to PDF via Playwright (headless Chrome)**, so
  charts (lightweight JS chart library) and precise branded layout render reliably. Template is
  versioned in the repo.

### Branding

- **TAG Online–branded** (the agency's report about the client). Fixed branding config (logo,
  colors, fonts). White-label/per-client branding is a possible future option, out of scope now.

## Orchestration & Human-in-the-Loop

- **Now:** a Claude Code project skill defines the workflow. Operator says "run a competitive
  research job for *client* at *url* vs *competitors*"; the orchestrator runs modules 1–4 in
  order, then renders. Any single module can be re-run independently.
- **Human-in-the-loop:** none — fully automatic, default to the top-opportunity draft topic.
  Generate additional articles by re-running the draft module.
- **Phase 2:** the same job fields become a simple web form (fill → click run → links to Sheet
  and PDF). Same modules underneath; only the trigger changes.

## Engineering

- **Language:** Python (Windows-compatible).
- **Libraries:** `httpx` + `lxml` (sitemaps); `anthropic` SDK (Claude); DataForSEO REST client
  + manual-import adapter (keywords); `gspread`/Google Sheets API (Sheet); `Jinja2` + Playwright
  (PDF).
- **Config & secrets:** `.env` for API keys (Anthropic, DataForSEO, Google service-account JSON).
  Branding config and prompt templates are versioned in the repo.
- **Error handling:** modules are isolated and write their own status into `data.json`. A missing
  competitor sitemap or failed lookup logs a warning and continues, marking that section partial
  rather than crashing. Re-runs are idempotent.
- **Testing (TDD):** per-module unit tests against saved fixtures (sample sitemaps, recorded API
  responses) so the full pipeline runs offline with no API spend; render module gets golden-file
  tests.
- **Observability:** per-job API cost is logged for unit-economics visibility.

## Repository Layout (proposed)

```
competitive-research/
  modules/
    sitemap/
    keywords/
    topical_map/
    draft_post/
    render/
  orchestrator/        # runs the chain, manages job folders
  templates/           # Jinja2 report templates, branding config
  jobs/                # per-client job folders
  tests/               # unit + golden-file tests, fixtures
  .env                 # secrets (gitignored)
```

## Out of Scope (for now)

- Full custom web app with auth/DB/queue.
- Client-facing web dashboard / microsite (future upsell; data is structured to allow it later).
- White-label / per-client branding.
- Multi-tenant scale concerns.

## Sequencing

All four parts are in scope for v1 (end-to-end). Suggested build order is bottom-up by
dependency: sitemap → keywords → topical map (depends on sitemap + keyword gaps) → draft post
(depends on topical map + sitemap) → render (depends on all). Detailed steps to be produced in
the implementation plan.
