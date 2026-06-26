# Setup & First Live Run

How to get the engine fully operational and run a real competitive-research job end to end.
Estimated one-time setup: ~30–45 minutes (mostly the Google service account).

The code is done and fully tested offline. What's left is wiring up the four paid/external
services and doing a first live run. You can do this incrementally — each credential only
gates the step that uses it.

---

## 0. Prerequisites (once)

```powershell
# from the project root: C:\Users\gdesc\Documents\Software\Competitive Research
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium   # one-time; needed for the PDF
.venv\Scripts\python -m pytest -q                      # sanity check: should say "222 passed"
```

There is already a `.env` file in the project root with blank keys — fill it in as you go below.
**Never commit `.env`** (it's gitignored).

---

## 1. Claude API key — for the topical map + draft post

1. Go to https://console.anthropic.com → **API keys** → create a key.
2. Put it in `.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```

Cost: a few cents to ~$0.10 of tokens per job (topical map on Sonnet, draft post on Opus).

---

## 2. DataForSEO — for the keyword step (API mode)

*(Skip this if you'd rather use manual KeySearch CSVs — see §5.)*

1. Sign up at https://dataforseo.com and add a little credit.
2. Your login is your account email; the password is your account password (or an API password
   from the dashboard).
3. Put both in `.env`:
   ```
   DATAFORSEO_LOGIN=you@tagonline.com
   DATAFORSEO_PASSWORD=...
   ```

Cost: a few cents per domain looked up.

> Note: this path is built and unit-tested but hasn't been run against the live API yet. The
> first real run is the shakedown — if the response shape differs from what we assumed, it's a
> small, isolated fix in `keywords.parse_ranked_keywords` (everything else stays the same).

---

## 3. Google service account — for the Sheet

This is the fiddliest one. You need a service account with the Sheets + Drive APIs enabled.

1. Go to https://console.cloud.google.com → create (or pick) a project.
2. **APIs & Services → Library** → enable **Google Sheets API** *and* **Google Drive API**.
3. **APIs & Services → Credentials → Create credentials → Service account.** Name it anything
   (e.g. `comp-research`). No roles needed.
4. Open the service account → **Keys → Add key → Create new key → JSON.** A `.json` file
   downloads. Save it somewhere safe (e.g. `C:\Users\gdesc\keys\comp-research.json`).
5. Put the path and your Google email in `.env` (use forward slashes):
   ```
   GOOGLE_SERVICE_ACCOUNT_JSON=C:/Users/gdesc/keys/comp-research.json
   GOOGLE_SHARE_EMAIL=you@tagonline.com
   ```

How sharing works: the service account creates the Sheet in its own Drive, then shares it
(as editor) with `GOOGLE_SHARE_EMAIL`. It shows up under **"Shared with me"** for that account.

Cost: free.

> Note: also built and unit-tested but not yet run live. The empty-row API issue is already
> fixed, so the first run should just work — if a gspread call signature differs on your
> installed version, it's a one-line fix in `sheets.GoogleSheetWriter.__call__`.

---

## 4. Branding (optional but recommended for client-ready PDFs)

Out of the box the PDF uses clean default colors and a text logo. To brand it as TAG Online:

```powershell
copy compresearch\branding.example.json compresearch\branding.json
```

Then edit `compresearch\branding.json`:
- `primary_color` / `accent_color` — your hex brand colors
- `font_family` — a CSS font stack
- `logo_path` — absolute path to your logo PNG, **forward slashes** (e.g. `C:/Users/gdesc/tag-logo.png`)

If you skip this, the report still looks polished — just generic.

---

## 5. Run a job

**Full pipeline (API keyword mode):**

```powershell
.venv\Scripts\python -m compresearch.cli run-job `
  --client-name "Acme Co" `
  --client-url "https://acme.com" `
  --competitors "https://rival-a.com,https://rival-b.com" `
  --business-description "Acme sells CRM software to small businesses"
```

**Manual keyword mode** (no DataForSEO): add `--keyword-source manual`, and before running,
create `jobs\acme-co\keywords_input\` and drop one CSV per domain named by the domain
(`acme-com.csv`, `rival-a-com.csv`, …) with columns `keyword,search_volume,difficulty,position,url`.
(You can create the job first by running any step, or just run `run-job` once — it creates the
folder — then add the CSVs and re-run.)

At the end it prints a summary like:

```
Competitive research job complete:
  [OK ] sitemap
  [OK ] keywords
  [OK ] topical_map
  [OK ] draft_post
  [OK ] render
  [OK ] sheet
  PDF:   jobs\acme-co\outputs\acme-co-competitive-research.pdf
  Sheet: https://docs.google.com/spreadsheets/d/...
  Estimated API cost: $0.0612
```

Marks: `[OK ]` passed, `[~~ ]` partial (ran but some data was incomplete — e.g. one competitor
unreachable), `[XX ]` failed (reason inline, with a `fix:` hint for common credential problems),
`[-- ]` skipped (a cached result was reused). Failed/partial steps don't stop the others.
Because it's resilient, you can fill in credentials incrementally: run it with only some keys set,
see which steps pass, add the next credential, and **re-run with `run-job --job-dir jobs\<slug>`**
— completed steps are skipped, so only the failed/remaining ones execute (add `--force` to redo
everything). A full log of each run is saved to `jobs\<slug>\run.log`.

**Inside Claude Code:** just say *"run a competitive research job for Acme at acme.com vs rival-a.com and rival-b.com"* — the `competitive-research` skill walks through it.

---

## 6. Verifying the first run

- **PDF:** open `jobs\<slug>\outputs\<slug>-competitive-research.pdf` — check the sections render and the branding looks right.
- **Sheet:** open the printed URL (or find it under "Shared with me" in `GOOGLE_SHARE_EMAIL`'s Drive) — one tab per analysis section (and one per drafted post).
- **`data.json`:** `jobs\<slug>\data.json` holds everything, including `run_report` (per-step status + cost).
- **If a step failed:** the summary names it and the reason (with a `fix:` hint); `data.json`'s matching section has the full `.error`, and `jobs\<slug>\run.log` has the complete log. Most first-run failures are a missing/typo'd `.env` value or an un-enabled Google API. Fix it and re-run with `run-job --job-dir jobs\<slug>` — only the failed step re-executes.

---

## Troubleshooting quick hits

| Symptom | Likely cause |
|---|---|
| `ANTHROPIC_API_KEY must be set` | Key missing/blank in `.env` |
| topical_map/draft_post `[XX]` with an auth error | Bad Claude key, or billing not set up |
| keywords `[XX]` | DataForSEO creds wrong, or no credit; or use `--keyword-source manual` |
| sheet `[XX]` `must be set` | `GOOGLE_SERVICE_ACCOUNT_JSON` / `GOOGLE_SHARE_EMAIL` missing |
| sheet `[XX]` permission/API error | Sheets API or Drive API not enabled on the project |
| render `[XX]` | `playwright install chromium` not run |
| Logo missing in PDF | `logo_path` wrong or has backslashes — use forward slashes, absolute path |
