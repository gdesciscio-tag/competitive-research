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
