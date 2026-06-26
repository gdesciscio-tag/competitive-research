# Competitive Research Automation

TAG Online's competitive research & analysis engine. See the design at
`docs/superpowers/specs/2026-06-17-competitive-research-automation-design.md`.

## Setup

```
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in API keys as modules are added.

## Run a full job (one command)

Run the entire pipeline — sitemap, keywords, topical map, draft post, branded PDF, and Google
Sheet — for one client:

```
.venv\Scripts\python -m compresearch.cli run-job \
  --client-name "Acme Co" \
  --client-url "https://acme.com" \
  --competitors "https://rival-a.com,https://rival-b.com" \
  --business-description "Acme sells CRM software"
```

It prints a per-step pass/fail summary, the PDF path, the Google Sheet URL, and the estimated
Claude cost for the job. The pipeline is resilient: a failed step is recorded and the rest still
run. Inside Claude Code, the `competitive-research` skill walks an operator through the same flow.

## Run the sitemap module

```
.venv\Scripts\python -m compresearch.cli sitemap \
  --client-name "Acme Co" \
  --client-url "https://acme.com" \
  --competitors "https://rival-a.com,https://rival-b.com"
```

Results land in `jobs/<slug>/data.json`.

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

**Client-provided keywords (optional):** to include a "Client-Provided Keywords" tab in
the Sheet, drop a plain-text file at `jobs\<slug>\keywords_input\client_provided.txt`
before running — one keyword per line (blank lines and lines starting with `#` are
ignored). In `api` keyword mode each phrase is enriched with search volume and difficulty
via DataForSEO and cross-referenced against the client's and competitors' rankings. In
`manual` mode the tab still renders, with volume/difficulty filled in only where a phrase
matches the supplied ranking data.

## Run the topical-map module

The topical map runs on a job that already has sitemap and keyword results (run those
first so the map is grounded in real gaps). It calls the Claude API.

Set `ANTHROPIC_API_KEY` in `.env`, optionally add a `business_description` to the job's
`job.yaml`, then:

```
.venv\Scripts\python -m compresearch.cli topical-map --job-dir jobs\acme-co
```

The result (pillars → clusters → article ideas, each tied to a target keyword) is written
to `data.json` under `topical_map`. The default model is `claude-sonnet-4-6`.

## Run the draft-post module

The draft-post module runs on a job that already has a topical map (run the topical-map
module first so there is an article to draft). It calls the Claude API.

Set `ANTHROPIC_API_KEY` in `.env`, then:

```
.venv\Scripts\python -m compresearch.cli draft-post --job-dir jobs\acme-co
```

To target a specific keyword instead of the highest-volume article:

```
.venv\Scripts\python -m compresearch.cli draft-post --job-dir jobs\acme-co --keyword "what is a crm"
```

The result (SEO title, meta description, heading outline, full body in Markdown, and
suggested internal links) is written to `data.json` under `draft_post`. The default
model is `claude-opus-4-8`.

**Drafting another post afterward:** the full `run-job` drafts one post (the highest-volume
article). To draft an additional post, run `draft-post` again against the same job with a
different `--keyword`. Each new keyword is **kept alongside** the existing drafts (re-running
the *same* keyword re-rolls that one in place). All drafts are stored under `draft_posts` in
`data.json`. After drafting more posts, run `refresh-outputs` (below) so the PDF, Google
Sheet, and exported drafts include them.

## Refresh the outputs after re-drafting

The draft step only updates `data.json`. To regenerate the deliverables (export every draft
to HTML + a Google Doc, rebuild the branded PDF, and rebuild the Google Sheet) so they reflect
all current drafts, run:

```
.venv\Scripts\python -m compresearch.cli refresh-outputs --job-dir jobs\acme-co
```

The first draft keeps the stable `<slug>-draft.html` name; additional drafts get `-2`, `-3`, …
The PDF gains a numbered "Sample Blog Post" section per draft, and the Sheet gains a
"Draft Post" tab per draft (each linking to its own Doc).

## Render the branded PDF report

The render module turns a job's finished `data.json` into a branded TAG Online PDF report.
It works with whatever analysis sections are present (run sitemap/keywords/topical-map/draft-post first for a complete report).

**One-time setup for real PDF output** (the test suite does not need this):

```
.venv\Scripts\python -m playwright install chromium
```

**Generate the report:**

```
.venv\Scripts\python -m compresearch.cli render --job-dir jobs\acme-co
```

The PDF is written to `jobs\<slug>\outputs\<slug>-competitive-research.pdf` and its path is
recorded in `data.json` under `render`.

**Branding:** copy `compresearch\branding.example.json` to `compresearch\branding.json` and
edit the colors, fonts, and `logo_path` to your real TAG Online assets. Without it, the report
uses clean built-in defaults and a text logo.

## Create the Google Sheet appendix

The sheet module turns a job's finished `data.json` into a shared Google Sheet with tabs
(Overview, Sitemap, Keyword Gaps, Quick Wins, Topical Map, Draft Post).

**One-time setup:**
1. In Google Cloud, create a service account and enable the Google Sheets API and Google Drive API.
2. Download the service-account JSON key.
3. In `.env`, set `GOOGLE_SERVICE_ACCOUNT_JSON` to the JSON file path and `GOOGLE_SHARE_EMAIL`
   to the Google account that should own/see the sheets (each created sheet is shared with it
   as editor and appears under "Shared with me").

**Create the sheet:**

```
.venv\Scripts\python -m compresearch.cli sheet --job-dir jobs\acme-co
```

The shareable URL is recorded in `data.json` under `sheet`.

## Test

```
.venv\Scripts\python -m pytest
```

## Status

- [x] Foundation (job store, schema, settings)
- [x] Sitemap module
- [x] Keywords module
- [x] Topical map module
- [x] Draft post module
- [x] Render module (branded PDF + Google Sheet)
- [x] Orchestrator + Claude Code skill
