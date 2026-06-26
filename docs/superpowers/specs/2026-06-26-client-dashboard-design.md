# Client-Facing Dashboard — Design

_Date: 2026-06-26_

## Summary

Add a new deliverable to the competitive-research job: a **single, self-contained,
branded HTML dashboard** that lets the client explore the same `data.json` interactively,
instead of only reading the flat PDF. It mirrors the completeness of the Google Sheet (more
than the PDF shows) but renders as a polished web page — tabs, sortable/filterable tables,
the topical map, and the draft post(s) — in one file that opens in any browser with no server.

This is an **additional** output alongside the PDF and Sheet, not a replacement.

## Goals

- One self-contained `.html` per job, written to `outputs/`, handed to the client (emailed/shared).
- Surface the full dataset the Sheet shows: all keyword gaps, all quick wins, per-competitor
  keyword tables, client-provided keywords, the full topical map, and every drafted post.
- Interactive but dependency-free: tabs, click-to-sort tables, text filter on large tables —
  vanilla JS, inline CSS, no CDN/framework, works offline.
- TAG-branded, consistent with the PDF (logo, colors, fonts from `branding.json`).
- Follow the established module pattern so it tests fully offline.

## Non-goals

- No hosting / live URL / microsite (explicitly out of scope on the roadmap).
- No Google Drive upload (Drive doesn't render a raw `.html` as a page).
- No history/progress-over-time (that's the separate "living dashboard" idea).
- No shared neutral report-model refactor of `sheets.py` (noted as a future option, not built).

## Approach (chosen: B — dedicated HTML view-model)

A new module builds its own view-model directly from `data.json`, exactly the way
[render.py](../../../compresearch/render.py) `build_report_context` does for the PDF — but pulling
the full dataset rather than the PDF's curated subset. Rejected alternatives:

- **A. Reuse `build_sheet_model()`** — its rows are spreadsheet-shaped (plain strings,
  `=HYPERLINK(...)` formulas, em-dash blanks, formatting as side metadata). Parsing those back
  into typed values + links for sortable HTML fights the format.
- **C. Shared neutral report-model** consumed by both Sheet and dashboard — cleanest DRY end
  state but a real refactor of `sheets.py`; over-engineering now. Revisit if the overlap hurts.

## Architecture

New module `compresearch/dashboard.py`, mirroring `render.py`'s shape:

- `build_dashboard_context(data: JobData, branding: Branding, report_date: str | None = None) -> dict`
  — pure view-model. Tolerates any missing section (like `build_report_context`). Reuses
  `render.markdown_to_html`, `render._logo_html`, `render._bar_chart_svg`, and `utils.short_domain`.
- `render_dashboard_html(context: dict, templates_dir: Path = TEMPLATES_DIR) -> str` — Jinja2
  (`Environment` + `select_autoescape`) over a new `templates/dashboard.html.j2`.
- `run_dashboard(job_dir, branding=None) -> JobData` — builds context, renders HTML, writes
  `outputs/<slug>-dashboard.html`, records the path in `data.json`. Never raises; captures
  failures into the result's `.error` (same contract as the other `run_*`).

### Data model (`models.py`)

```python
class DashboardResult(BaseModel):
    html_path: str | None = None
    error: str | None = None
```

`JobData` gains `dashboard: DashboardResult | None = None`.

### View-model shape

`build_dashboard_context` returns typed, semantic data (numbers stay numbers so the client-side
sort is correct; links are real URLs):

```
{
  branding, logo_html, client_name, client_url, report_date,
  summary: { competitor_count, content_gap_count, keyword_gap_count, quick_win_count, is_partial },
  content_volume_svg, keyword_counts_svg,           # inline SVG bar charts
  sitemap: { domains: [{domain,total,posts_per_month}], gaps: [{section,competitors}] },  # full, not capped
  keyword_gaps: [{keyword, volume, difficulty, traffic_value, best_position, competitors}],  # full
  quick_wins:   [{keyword, position, volume, traffic_value, url}],                            # full
  domain_keywords: [{domain, keywords:[{keyword,volume,difficulty,position,url}]}],           # per client+competitor
  provided: [{keyword, volume, difficulty, client_position, competitors, best_position}],      # when present
  topical_map: { summary, pillars: [...] },
  drafts: [{title, target_keyword, title_tag, meta_description, word_count, body_html, internal_links}],
}
```

Sections render only when their data is present (mirroring the PDF/Sheet tolerance).

### Template & self-containment (`templates/dashboard.html.j2`)

One HTML document with:
- Inline `<style>` (brand colors/fonts from `branding`), inline base64 logo (`_logo_html`),
  inline SVG charts (`_bar_chart_svg`). No external `src`/`href` for assets.
- Tabs: Overview · Content gaps · Keyword gaps · Quick wins · Keywords by domain · Topical map ·
  Draft posts · Client-provided (the last two/three conditional on data). Drafts stack within
  their tab; per-domain keyword tables stack within theirs.
- A small inline vanilla-JS block (after content) for: tab switching, click-to-sort on table
  headers (numeric vs text inferred from a `data-num` attribute), and a text filter on the
  keyword-gap and per-domain tables.

**Trust boundary:** the draft `body_html` is LLM-rendered Markdown emitted with `|safe`, same as
the PDF. The file is a static artifact handed to the client (not served to untrusted users), so
this matches the existing boundary. If it were ever hosted for untrusted visitors, sanitize first.

### Integration

- **Orchestrator** ([orchestrator.py](../../../compresearch/orchestrator.py)): add `dashboard`
  as a cheap output step (always runs, no caching/skip), after `sheet`. Recorded in `run_report`
  with status; no cost.
- **CLI** ([cli.py](../../../compresearch/cli.py)): a standalone `dashboard --job-dir` subcommand
  (wrapped in `job_log`, followed by `_verify_step(job_dir, "dashboard")`); include the dashboard
  in `refresh-outputs` (it's a regenerable output); print its path in the run summary
  (`_print_run_summary` / `_print_outputs_summary`).

## Error handling

`run_dashboard` follows the resilient contract: a render failure is logged and captured into
`DashboardResult.error`, the pipeline continues, and the summary shows the step status. The
template tolerates missing analysis sections so a partial job still produces a useful dashboard.

## Testing (offline, mirrors existing module tests)

- `build_dashboard_context`: shape; full (uncapped) gap/quick-win lists; tolerates missing sections;
  drafts list maps every draft; per-domain keyword tables present.
- `render_dashboard_html`: contains each expected tab/section; draft body Markdown rendered to HTML;
  brand colors applied.
- Self-containment: rendered HTML has no external `http(s)` asset references (`src=`/`href=` for
  CSS/JS/img); logo is inlined as a data URI when configured.
- `run_dashboard`: writes `outputs/<slug>-dashboard.html`, records the path; captures a render
  failure into `.error` without raising.
- Orchestrator: `dashboard` step runs in `run_job` and is recorded; `refresh-outputs` regenerates it.
- CLI: `dashboard` subcommand writes the file; exits non-zero on a captured error (`_verify_step`).

## Documentation

- README: a "Generate the client dashboard" section + mention in the run-job output list.
- SKILL.md: note the dashboard as an output and in report-back.
- ARCHITECTURE.md: add `dashboard.py` to the module table and `dashboard` to the `data.json` sections.
- ROADMAP.md: move "client-facing dashboard" from out-of-scope to Shipped.
