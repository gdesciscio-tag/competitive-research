# Competitive Research Engine — Architecture Overview

A Python tool that produces a competitive research & analysis deliverable for a client:
a **branded PDF report** plus a **Google Sheet** appendix. One command runs the whole thing.

This doc is the team's map of how it works. For setup + running it, see [SETUP.md](SETUP.md).

---

## The big picture

```
            run-job (one command)
                   │
   ┌──────┬────────┼─────────┬────────┬───────┐
   ▼      ▼        ▼         ▼        ▼       ▼
 sitemap keywords topical  draft    render   sheet
                   map      post     (PDF)
   │      │        │         │        │       │
   └──────┴────────┴── data.json ─────┴───────┘
                   (single source of truth)
                         │
                ┌────────┴────────┐
                ▼                 ▼
         branded PDF        Google Sheet
```

Every analysis step writes its results into **one file per job**, `jobs/<client-slug>/data.json`.
The two render steps read that file and produce the deliverables. Nothing renders until the
data is there, so the PDF and Sheet can never disagree — they're two views of the same data.

Each step feeds the next: the **topical map is built from the real sitemap + keyword gaps**
(not just a business description), and the **draft post is style-matched to the client's own
pages** and links only to their real URLs. That chaining is where the quality comes from.

---

## A "job"

A job is a self-contained folder:

```
jobs/<client-slug>/
  job.yaml        # the inputs: client name, URL, competitors, keyword source, business description
  data.json       # the single source of truth — every step writes its section here
  keywords_input/ # (manual keyword mode only) the operator drops KeySearch CSVs here
  outputs/        # the generated PDF (and a copy of the run report)
```

`data.json` grows one section per step: `sitemap`, `keywords`, `topical_map`, `draft_post`,
`render`, `sheet`, and a `run_report` (per-step status + cost). All defined as pydantic models
in `compresearch/models.py`.

---

## The modules (`compresearch/`)

| File | What it does |
|------|--------------|
| `models.py` | The whole `data.json` schema (pydantic) |
| `job_store.py` | Create/load/save job folders + `data.json`; `slugify` |
| `settings.py` | Reads secrets from `.env` |
| `sitemap.py` | `run_sitemap` — discover + parse sitemaps, categorize URLs by section, infer cadence, compute content gaps |
| `keywords.py` | `run_keywords` — DataForSEO API (or manual CSV); keyword gaps, quick wins, traffic value |
| `topical_map.py` | `run_topical_map` — Claude (Sonnet 4.6) builds pillars → clusters → articles, grounded in the gaps |
| `draft_post.py` | `run_draft_post` — Claude (Opus 4.8) writes a full SEO post, style-matched, with internal links |
| `render.py` | `run_render` — builds the report HTML (Jinja2) and renders it to PDF via Playwright |
| `sheets.py` | `run_sheet` — writes the six-tab Google Sheet via gspread |
| `branding.py` | Loads `branding.json` (logo/colors/fonts) over built-in defaults |
| `costs.py` | Claude price table + `estimate_cost` |
| `orchestrator.py` | `run_job` — chains all six steps; records per-step status + cost |
| `cli.py` | The command-line interface (one subcommand per step, plus `run-job`) |
| `utils.py` | Small shared helpers (`short_domain`) |
| `templates/report.html.j2` | The branded PDF report template |

---

## Two ideas that make it testable and safe to change

**1. Every external service sits behind an injectable "seam."**
HTTP fetching, the Claude calls, Playwright (Chromium), gspread (Google) — each is a parameter
with a real default that tests replace with a fake. So the entire 128-test suite runs offline:
no network, no API keys, no Chromium, no Google. That's why you can refactor confidently.

Example: `run_render(job_dir, html_to_pdf=render_pdf)` — production passes the real Playwright
renderer; tests pass a fake that captures the HTML.

**2. Steps never crash the pipeline.**
Each `run_*` captures its own errors into its result's `.error` field and returns normally.
The orchestrator records each step as **ok / partial / failed** and keeps going, so a missing
credential or one unreachable competitor degrades gracefully — you still get whatever deliverables
the available data supports, and the run summary tells you exactly what happened.

---

## Cost & credentials

- **Paid steps:** topical map + draft post (Claude API), keywords (DataForSEO, "api" mode), sheet (Google, free but needs a service account).
- Per-job Claude cost is captured from real token usage and printed in the run summary (~a few cents to ~$0.10 for the LLM steps). DataForSEO is a few cents per domain; Google Sheets is free.
- Credentials live in `.env` (gitignored). The keyword step also has a **manual mode** (`--keyword-source manual`) that uses KeySearch CSVs and needs no DataForSEO account.

---

## How to extend it

The pattern is consistent, so adding a step or swapping a provider is mechanical:

- **Swap a data provider** (e.g. KeySearch API instead of DataForSEO): implement a new provider
  with the same `Provider` callable shape and inject it; nothing else changes.
- **Add a new output** (e.g. a Notion export or a client microsite): write a `build_<x>_model`
  (pure, reads `data.json`) + a thin writer behind a seam + a `run_<x>(job_dir, ...) -> JobData`,
  add a CLI subcommand, and chain it in `run_job`. Mirror `sheets.py` as the template.
- **Change the report look:** edit `templates/report.html.j2` and `branding.json` — no Python.

Every module was built test-first; keep that up (`tests/test_<module>.py`) and the suite stays
your safety net.

---

## Known follow-ups (non-blocking)

- DataForSEO returns a per-call `cost` field that isn't yet folded into the run report's total.
- The single-step CLI subcommands print "Job complete" even if that step's `.error` is set
  (the `run-job` summary does surface per-step status correctly).
