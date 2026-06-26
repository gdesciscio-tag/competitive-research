---
name: competitive-research
description: Run a full competitive research & analysis job for a client — crawls the client and competitors, finds keyword gaps and quick wins, builds a data-driven topical map, drafts a sample blog post, and produces a branded PDF report plus a Google Sheet. Use when someone asks for a competitive research report or analysis for a client.
---

# Competitive Research

Run a complete competitive-research job for a client with one command.

## Gather inputs (ask the operator)

- **Client name** (e.g. "Acme Co")
- **Client website URL** (e.g. https://acme.com)
- **Competitor URLs** (comma-separated)
- **Business description** (one line — what the client does/sells; improves the topical map)
- **Keyword source**: `api` (DataForSEO, default) or `manual` (operator pastes KeySearch CSVs into `jobs/<slug>/keywords_input/` first)

## Prerequisites (one-time)

Confirm `.env` has the needed keys before running:
- `ANTHROPIC_API_KEY` (topical map + draft post)
- `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` (keyword API mode)
- `GOOGLE_SERVICE_ACCOUNT_JSON` + `GOOGLE_SHARE_EMAIL` (Google Sheet)
- For real PDF output: `python -m playwright install chromium` has been run once

## Run the job

```
.venv\Scripts\python -m compresearch.cli run-job \
  --client-name "<name>" \
  --client-url "<url>" \
  --competitors "<comma-separated urls>" \
  --business-description "<one line>"
```

Add `--keyword-source manual` for the manual KeySearch path.

## Draft additional posts (optional)

The job drafts one post (the highest-volume topic). To add more, run `draft-post` against the
existing job with a different `--keyword` — each new keyword is kept alongside the others.
Re-running the *same* keyword is skipped as cached; add `--force` to re-roll it. Then run
`refresh-outputs --job-dir <dir>` to rebuild the PDF, Google Sheet, and exported drafts so
they include every draft.

```
.venv\Scripts\python -m compresearch.cli draft-post --job-dir jobs\<slug> --keyword "<topic>"
.venv\Scripts\python -m compresearch.cli refresh-outputs --job-dir jobs\<slug>
```

## Report back

The command prints a per-step summary (which steps succeeded/failed/were skipped as cached),
the branded PDF path, the shared Google Sheet URL, and the estimated Claude cost for the job.
Relay those to the operator. The pipeline is resilient — if one step fails (e.g. a missing
credential), the others still run and the summary shows exactly what was produced, with a
`fix:` hint for common credential problems. A full log is saved to `jobs/<slug>/run.log`.

The summary may also list internal "quality notes" for a draft (keyword placement, meta
length, word count) — these are for the operator only, not the client.

**Re-running / fixing a failed step:** re-run with `run-job --job-dir jobs/<slug>` to resume
without redoing completed work; add `--force` to recompute everything. So if a step failed on
a missing credential, set the credential and re-run — only the failed/remaining steps execute.
