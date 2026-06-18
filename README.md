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

## Test

```
.venv\Scripts\python -m pytest
```

## Status

- [x] Foundation (job store, schema, settings)
- [x] Sitemap module
- [x] Keywords module
- [x] Topical map module
- [ ] Draft post module
- [ ] Render module (Google Sheet + PDF)
- [ ] Orchestrator + Claude Code skill
