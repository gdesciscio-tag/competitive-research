# Roadmap

The single place to see what's built, what's next, and what's deliberately out of scope.
For how the system works see [ARCHITECTURE.md](ARCHITECTURE.md); for setup see [SETUP.md](SETUP.md).

_Last updated: 2026-06-26._

---

## Shipped

**Core pipeline (MVP):**
- [x] Foundation — job store, `data.json` schema, settings
- [x] Sitemap module — crawl, section categorization, cadence, content gaps
- [x] Keywords module — DataForSEO API + manual KeySearch CSV; gaps, quick wins, traffic value
- [x] Topical map module — Claude builds pillars → clusters → articles, grounded in real gaps
- [x] Draft post module — Claude writes a style-matched SEO post with real internal links
- [x] Render module — branded PDF (Playwright) + Google Sheet appendix (gspread)
- [x] Orchestrator + Claude Code skill — one command runs the whole chain, resiliently

**Enhancements:**
- [x] Draft export — each draft to standalone HTML + a Google Doc
- [x] Multiple drafts per job — `draft_posts` list; a new keyword adds a post, same keyword re-rolls (with `--force`)
- [x] `refresh-outputs` — rebuild PDF / Sheet / exported drafts after re-drafting
- [x] Step caching — completed analysis steps skip on re-run; `run-job --job-dir` resumes; `--force` recomputes
- [x] Per-job run log (`run.log`) + plain-language `fix:` hints for common credential errors
- [x] Draft quality checks — internal SEO flags (keyword placement, meta/title length, word count)
- [x] DataForSEO per-call cost folded into the run report total (was Claude-only)
- [x] Standalone CLI commands exit non-zero when a step captured an error (no false "Job complete")
- [x] Location-page slug detection — root-level pages sharing a hyphen prefix surface as a `<prefix>-*` section instead of vanishing into "(individual pages)"
- [x] Client-facing dashboard — single self-contained, branded interactive HTML (tabs, sortable/filterable tables) built from data.json, written to outputs/

---

## Next — live verification

The code is fully tested offline; these paths are built but not yet exercised against the real services:

- [ ] **DataForSEO (API keyword mode)** — first live run is the shakedown; any response-shape
  mismatch is an isolated fix in `keywords.parse_ranked_keywords`.
- [ ] **Google Sheets writer** — first live run; a gspread signature difference would be a one-line
  fix in `sheets.GoogleSheetWriter.__call__`.

---

## Later — Phase 2

- [ ] **Operator-facing web form.** The same job inputs become a simple form (fill → click run →
  links to the PDF and Sheet). Same modules underneath; only the trigger changes.

## Out of scope (for now)

Deliberately deferred — the data is structured to allow these later, but they aren't planned work:

- Full custom web app with auth / DB / queue
- Hosted dashboard microsite — a live per-client URL (the local self-contained dashboard ships; hosting/auth/privacy is the deferred part)
- White-label / per-client branding (branding is currently fixed to TAG Online)
- Multi-tenant scale concerns
