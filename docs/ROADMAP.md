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

- [x] Live verification — full `run-job` exercised against the real DataForSEO API, Google Sheets, Google Docs, and Claude on the ATS Hire job (2026-06-26); all external paths work end to end.

---

## Next — technical follow-ups

- [ ] **Treat an empty topical map as a failure.** `run_topical_map` currently records success
  when the LLM returns a map with zero pillars/articles, so the step shows OK, the cache treats
  it as complete, and the downstream draft step fails with "No topical-map article available to
  draft" (seen on a real ATS Hire run). It should set `TopicalMapResult.error` on an empty map so
  the step reports failed and a plain `run-job --job-dir` resume retries it automatically.

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
