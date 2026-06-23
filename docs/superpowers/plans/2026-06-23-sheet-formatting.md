# Sheet Formatting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the generated Google Sheet look designed — frozen branded headers, number/currency formats, insight color scales, basic filters, auto-resize, hyperlinks, a merged Overview title block, and tab colors — driven by `branding.json`.

**Architecture:** `build_sheet_model` declares formatting as metadata on each `SheetTab` (pure). A pure `build_format_requests(tab, sheet_id, branding)` translates that metadata into raw Sheets API request objects. `GoogleSheetWriter` accumulates the requests across tabs and sends one `batch_update` after writing values, isolated so a formatting failure never loses the data.

**Tech Stack:** Python 3.14, gspread 6.x (`Spreadsheet.batch_update`, `Worksheet.id`), pydantic, pytest.

---

## File Structure

- `compresearch/sheets.py` — `ColorScale`/`TitleBlock` dataclasses, enriched `SheetTab`, `build_sheet_model` metadata + `run_date`, `_hex_to_rgb`, `build_format_requests`, `GoogleSheetWriter` branding + batch_update, `run_sheet` run-date default.
- `tests/test_sheets.py` — model metadata, `_hex_to_rgb`, translator, writer batch/isolation tests.

Run the suite at any checkpoint: `.venv\Scripts\python -m pytest -q`

This plan runs on branch `fix/sitemap-whitespace-and-topical-map-budget` (per user decision). Do NOT create a new branch.

---

### Task 1: Formatting metadata on the model

**Files:**
- Modify: `compresearch/sheets.py` (add dataclasses; add fields to `SheetTab`)
- Test: `tests/test_sheets.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_sheets.py`:

```python
def test_sheettab_formatting_fields_default_off():
    from compresearch.sheets import SheetTab, ColorScale, TitleBlock
    t = SheetTab("X", [["a"]])
    assert t.header is False
    assert t.number_formats == {}
    assert t.color_scales == []
    assert t.basic_filter is False
    assert t.tab_color is False
    assert t.title_block is None
    # the helper types exist and carry their fields
    assert ColorScale(2, "low_good").direction == "low_good"
    assert TitleBlock(3).span == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_sheets.py::test_sheettab_formatting_fields_default_off -v`
Expected: FAIL with `ImportError: cannot import name 'ColorScale'`

- [ ] **Step 3: Add the dataclasses and fields**

In `compresearch/sheets.py`, replace the existing `SheetTab` dataclass with:

```python
@dataclass
class ColorScale:
    col: int                      # 0-based column index
    direction: str                # "low_good" (green->red) or "high_good" (red->green)


@dataclass
class TitleBlock:
    span: int                     # number of columns to merge across row 0


@dataclass
class SheetTab:
    name: str
    rows: list[list] = field(default_factory=list)
    header: bool = False
    number_formats: dict[int, str] = field(default_factory=dict)
    color_scales: list[ColorScale] = field(default_factory=list)
    basic_filter: bool = False
    tab_color: bool = False
    title_block: "TitleBlock | None" = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_sheets.py::test_sheettab_formatting_fields_default_off -v`
Expected: PASS

- [ ] **Step 5: Run the whole sheet test file (no regressions)**

Run: `.venv\Scripts\python -m pytest tests/test_sheets.py -q`
Expected: PASS (existing tests unaffected — new fields default off)

- [ ] **Step 6: Commit**

```bash
git add compresearch/sheets.py tests/test_sheets.py
git commit -m "feat: add formatting metadata fields to SheetTab"
```

---

### Task 2: build_sheet_model declares per-tab formatting

**Files:**
- Modify: `compresearch/sheets.py` (`build_sheet_model` + `run_sheet`)
- Test: `tests/test_sheets.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sheets.py`:

```python
def test_build_sheet_model_declares_formatting():
    data = _full_jobdata()
    tabs = {t.name: t for t in build_sheet_model(data, run_date="2026-06-23")}

    overview = tabs["Overview"]
    assert overview.tab_color is True
    assert overview.title_block is not None and overview.title_block.span == 2
    assert any(row == ["Generated", "2026-06-23"] for row in overview.rows)

    kg = tabs["Keyword Gaps"]
    assert kg.header is True
    assert kg.basic_filter is True
    assert kg.number_formats == {1: "#,##0", 2: "0", 3: "0", 4: "$#,##0"}
    assert any(cs.col == 2 and cs.direction == "low_good" for cs in kg.color_scales)

    qw = tabs["Quick Wins"]
    assert qw.header is True and qw.basic_filter is True
    assert qw.number_formats == {1: "0", 2: "#,##0", 3: "$#,##0"}
    assert any(cs.col == 1 and cs.direction == "low_good" for cs in qw.color_scales)
    # URL column became a clickable HYPERLINK (row 1 is the single quick-win)
    assert any("HYPERLINK" in str(c) and "acme.com/crm" in str(c) for c in qw.rows[1])

    assert tabs["Sitemap"].header is True
    assert tabs["Sitemap"].number_formats == {1: "#,##0"}
    assert tabs["Topical Map"].header is True
    assert tabs["Topical Map"].number_formats == {5: "#,##0"}


def test_build_sheet_model_no_run_date_omits_generated_row():
    data = _full_jobdata()
    overview = next(t for t in build_sheet_model(data) if t.name == "Overview")
    assert not any(row and row[0] == "Generated" for row in overview.rows)


def test_quick_wins_blank_url_is_not_hyperlink():
    data = JobData(
        config=JobConfig(client_name="X", client_url="https://x.com"),
        keywords=KeywordResult(quick_wins=[QuickWin(keyword="bare", position=5)]),  # url=None
    )
    qw = next(t for t in build_sheet_model(data) if t.name == "Quick Wins")
    assert qw.rows[1][4] == ""          # blank, not =HYPERLINK("")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_sheets.py::test_build_sheet_model_declares_formatting -v`
Expected: FAIL — `build_sheet_model()` takes no `run_date` argument / formatting fields are unset.

- [ ] **Step 3: Update `build_sheet_model` and `run_sheet`**

In `compresearch/sheets.py`, add `from datetime import date` to the imports at the top.

Change the `build_sheet_model` signature and the Overview block. Replace:

```python
def build_sheet_model(data: JobData) -> list[SheetTab]:
    """Turn a finished JobData into a list of sheet tabs (name + rows). Pure; only emits
    a tab for an analysis section that is present."""
    config = data.config
    tabs: list[SheetTab] = []

    # --- Overview (always) ---
    sitemap_gap_count = len(data.sitemap.gaps) if data.sitemap is not None else 0
    keyword_gap_count = len(data.keywords.gaps) if data.keywords is not None else 0
    quick_win_count = len(data.keywords.quick_wins) if data.keywords is not None else 0
    overview = [
        ["Competitive Research"],
        ["Client", config.client_name],
        ["Website", config.client_url],
        ["Competitors", ", ".join(config.competitor_urls)],
        [],
        ["Content gaps", sitemap_gap_count],
        ["Keyword gaps", keyword_gap_count],
        ["Quick wins", quick_win_count],
    ]
    tabs.append(SheetTab("Overview", overview))
```

with:

```python
def build_sheet_model(data: JobData, run_date: str | None = None) -> list[SheetTab]:
    """Turn a finished JobData into a list of sheet tabs (name + rows + formatting metadata).
    Pure; only emits a tab for an analysis section that is present."""
    config = data.config
    tabs: list[SheetTab] = []

    # --- Overview (always) ---
    sitemap_gap_count = len(data.sitemap.gaps) if data.sitemap is not None else 0
    keyword_gap_count = len(data.keywords.gaps) if data.keywords is not None else 0
    quick_win_count = len(data.keywords.quick_wins) if data.keywords is not None else 0
    overview = [["Competitive Research"]]
    if run_date:
        overview.append(["Generated", run_date])
    overview += [
        ["Client", config.client_name],
        ["Website", config.client_url],
        ["Competitors", ", ".join(config.competitor_urls)],
        [],
        ["Content gaps", sitemap_gap_count],
        ["Keyword gaps", keyword_gap_count],
        ["Quick wins", quick_win_count],
    ]
    tabs.append(SheetTab("Overview", overview, tab_color=True, title_block=TitleBlock(span=2)))
```

In the `# --- Sitemap ---` block, change the tab append from
`tabs.append(SheetTab("Sitemap", rows))` to:

```python
        tabs.append(SheetTab("Sitemap", rows, header=True, number_formats={1: "#,##0"}))
```

In the `# --- Keywords ---` block, change the Keyword Gaps append from
`tabs.append(SheetTab("Keyword Gaps", gap_rows))` to:

```python
        tabs.append(SheetTab(
            "Keyword Gaps", gap_rows, header=True, basic_filter=True,
            number_formats={1: "#,##0", 2: "0", 3: "0", 4: "$#,##0"},
            color_scales=[ColorScale(2, "low_good")],
        ))
```

Still in the `# --- Keywords ---` block, replace the Quick Wins build (the `win_rows` loop and
its append) with a version that emits a HYPERLINK for the URL column and declares formatting:

```python
        win_rows = [["Keyword", "Current position", "Volume", "Est. traffic value", "URL"]]
        for w in data.keywords.quick_wins:
            if w.url:
                safe_url = w.url.replace('"', "%22")
                url_cell = f'=HYPERLINK("{safe_url}", "{safe_url}")'
            else:
                url_cell = ""
            win_rows.append([w.keyword, w.position, _cell(w.search_volume),
                             _cell(w.traffic_value), url_cell])
        tabs.append(SheetTab(
            "Quick Wins", win_rows, header=True, basic_filter=True,
            number_formats={1: "0", 2: "#,##0", 3: "$#,##0"},
            color_scales=[ColorScale(1, "low_good")],
        ))
```

In the `# --- Topical map ---` block, change the append from
`tabs.append(SheetTab("Topical Map", rows))` to:

```python
        tabs.append(SheetTab("Topical Map", rows, header=True, number_formats={5: "#,##0"}))
```

Finally, in `run_sheet`, pass the run date. Change:

```python
        tabs = build_sheet_model(data)
```

to:

```python
        tabs = build_sheet_model(data, run_date=date.today().isoformat())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_sheets.py -q`
Expected: PASS (the three new tests plus all existing — note the existing `test_build_sheet_model_full_job_has_all_tabs` still passes because the Quick Wins keyword/values are unchanged and the URL is now a HYPERLINK containing `acme.com/crm`).

- [ ] **Step 5: Commit**

```bash
git add compresearch/sheets.py tests/test_sheets.py
git commit -m "feat: declare per-tab formatting and run date in build_sheet_model"
```

---

### Task 3: `_hex_to_rgb` and the `build_format_requests` translator

**Files:**
- Modify: `compresearch/sheets.py` (add `_hex_to_rgb`, `build_format_requests`, import `Branding`)
- Test: `tests/test_sheets.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sheets.py` (top-level imports for `Branding` and the new functions go inside the
tests to keep them local, matching the file's existing style):

```python
def test_hex_to_rgb():
    from compresearch.sheets import _hex_to_rgb
    rgb = _hex_to_rgb("#AB1D42")
    assert round(rgb["red"], 3) == round(171 / 255, 3)
    assert round(rgb["green"], 3) == round(29 / 255, 3)
    assert round(rgb["blue"], 3) == round(66 / 255, 3)


def _req_types(requests):
    return [next(iter(r)) for r in requests]


def test_build_format_requests_header_freeze_and_number_formats():
    from compresearch.sheets import build_format_requests, SheetTab, _hex_to_rgb
    from compresearch.models import Branding
    branding = Branding(primary_color="#AB1D42")
    tab = SheetTab("Keyword Gaps",
                   [["Keyword", "Volume"], ["free crm", 800]],
                   header=True, number_formats={1: "#,##0"})
    reqs = build_format_requests(tab, sheet_id=99, branding=branding)
    types = _req_types(reqs)
    assert "repeatCell" in types          # header style + number format both use repeatCell
    assert "updateSheetProperties" in types  # frozen row
    # header repeatCell carries the brand background and targets sheet 99
    header_req = next(r["repeatCell"] for r in reqs
                      if "repeatCell" in r and r["repeatCell"]["range"].get("startRowIndex") == 0
                      and r["repeatCell"]["range"].get("endRowIndex") == 1)
    assert header_req["range"]["sheetId"] == 99
    bg = header_req["cell"]["userEnteredFormat"]["backgroundColor"]
    assert round(bg["red"], 3) == round(171 / 255, 3)
    assert header_req["cell"]["userEnteredFormat"]["textFormat"]["bold"] is True
    # a number-format repeatCell exists for column 1 with the pattern
    num_req = next(r["repeatCell"] for r in reqs
                   if "repeatCell" in r
                   and r["repeatCell"]["cell"]["userEnteredFormat"].get("numberFormat", {}).get("pattern") == "#,##0")
    assert num_req["range"]["startColumnIndex"] == 1
    assert num_req["range"]["startRowIndex"] == 1   # data rows only, below header
    # frozen row
    freeze = next(r["updateSheetProperties"] for r in reqs if "updateSheetProperties" in r
                  and "gridProperties" in r["updateSheetProperties"]["properties"])
    assert freeze["properties"]["gridProperties"]["frozenRowCount"] == 1


def test_build_format_requests_color_scale_filter_tabcolor_title():
    from compresearch.sheets import build_format_requests, SheetTab, ColorScale, TitleBlock
    from compresearch.models import Branding
    branding = Branding(primary_color="#AB1D42")

    kg = SheetTab("Keyword Gaps", [["Keyword", "Difficulty"], ["a", 30]],
                  header=True, basic_filter=True, color_scales=[ColorScale(1, "low_good")])
    reqs = build_format_requests(kg, sheet_id=5, branding=branding)
    types = _req_types(reqs)
    assert "addConditionalFormatRule" in types
    assert "setBasicFilter" in types
    grad = next(r["addConditionalFormatRule"]["rule"]["gradientRule"]
                for r in reqs if "addConditionalFormatRule" in r)
    # low_good: MIN point is green-ish (more green than red), MAX point is red-ish
    assert grad["minpoint"]["color"]["green"] > grad["minpoint"]["color"]["red"]
    assert grad["maxpoint"]["color"]["red"] > grad["maxpoint"]["color"]["green"]

    ov = SheetTab("Overview", [["Competitive Research"], ["Client", "Acme"]],
                  tab_color=True, title_block=TitleBlock(span=2))
    reqs2 = build_format_requests(ov, sheet_id=0, branding=branding)
    types2 = _req_types(reqs2)
    assert "mergeCells" in types2
    assert "updateSheetProperties" in types2   # tab color
    merge = next(r["mergeCells"]["range"] for r in reqs2 if "mergeCells" in r)
    assert merge["startRowIndex"] == 0 and merge["endColumnIndex"] == 2


def test_build_format_requests_empty_for_plain_tab():
    from compresearch.sheets import build_format_requests, SheetTab
    from compresearch.models import Branding
    tab = SheetTab("Draft Post", [["Title", "X"]])   # no formatting flags
    assert build_format_requests(tab, sheet_id=1, branding=Branding()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_sheets.py::test_hex_to_rgb -v`
Expected: FAIL with `ImportError: cannot import name '_hex_to_rgb'`

- [ ] **Step 3: Implement `_hex_to_rgb` and `build_format_requests`**

In `compresearch/sheets.py`, add `Branding` to the models import:

```python
from compresearch.models import Branding, JobData, SheetResult
```

Add these, after the `_cell` helper (before `build_sheet_model`):

```python
# Fixed semantic heatmap endpoints (not brand colors).
_GREEN = {"red": 0.42, "green": 0.66, "blue": 0.31}
_RED = {"red": 0.85, "green": 0.33, "blue": 0.31}


def _hex_to_rgb(hex_color: str) -> dict:
    """Convert '#RRGGBB' to a Sheets API color dict with 0..1 float channels."""
    h = hex_color.lstrip("#")
    return {
        "red": int(h[0:2], 16) / 255,
        "green": int(h[2:4], 16) / 255,
        "blue": int(h[4:6], 16) / 255,
    }


def build_format_requests(tab: "SheetTab", sheet_id: int, branding: Branding) -> list[dict]:
    """Translate a tab's formatting metadata into raw Sheets API request objects (pure).

    Returns [] for a tab with no formatting flags. Ranges are 0-based half-open and scoped
    to sheet_id. Brand colors come from branding; heatmap endpoints are fixed semantic colors.
    """
    requests: list[dict] = []
    n_rows = len(tab.rows)
    n_cols = max((len(r) for r in tab.rows), default=1)
    brand = _hex_to_rgb(branding.primary_color)

    if tab.header:
        requests.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {
                "backgroundColor": brand,
                "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }})
        requests.append({"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }})

    for col, pattern in sorted(tab.number_formats.items()):
        requests.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": max(n_rows, 1),
                      "startColumnIndex": col, "endColumnIndex": col + 1},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": pattern}}},
            "fields": "userEnteredFormat.numberFormat",
        }})

    for scale in tab.color_scales:
        low, high = (_GREEN, _RED) if scale.direction == "low_good" else (_RED, _GREEN)
        requests.append({"addConditionalFormatRule": {
            "rule": {
                "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": max(n_rows, 1),
                            "startColumnIndex": scale.col, "endColumnIndex": scale.col + 1}],
                "gradientRule": {
                    "minpoint": {"color": low, "type": "MIN"},
                    "maxpoint": {"color": high, "type": "MAX"},
                },
            },
            "index": 0,
        }})

    if tab.basic_filter:
        requests.append({"setBasicFilter": {"filter": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": max(n_rows, 1),
                      "startColumnIndex": 0, "endColumnIndex": n_cols},
        }}})

    if tab.tab_color:
        requests.append({"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "tabColor": brand},
            "fields": "tabColor",
        }})

    if tab.title_block is not None:
        span = tab.title_block.span
        requests.append({"mergeCells": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": span},
            "mergeType": "MERGE_ALL",
        }})
        requests.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": span},
            "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True, "fontSize": 14, "foregroundColor": brand},
            }},
            "fields": "userEnteredFormat.textFormat",
        }})

    return requests
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_sheets.py -q`
Expected: PASS (all new translator tests plus existing).

- [ ] **Step 5: Commit**

```bash
git add compresearch/sheets.py tests/test_sheets.py
git commit -m "feat: translate sheet formatting metadata to Sheets API requests"
```

---

### Task 4: Apply formatting in `GoogleSheetWriter` (one batched call, isolated)

**Files:**
- Modify: `compresearch/sheets.py` (`GoogleSheetWriter` + `from_settings`; import `load_branding`)
- Test: `tests/test_sheets.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sheets.py`:

```python
def _formatting_fake_spreadsheet():
    """A fake gspread Spreadsheet/Worksheet that records batch_update calls."""
    captured = {"batch": None, "updates": []}

    class _WS:
        _next_id = 0

        def __init__(self):
            _WS._next_id += 1
            self.id = _WS._next_id

        def update_title(self, name):
            pass

        def update(self, range_name=None, values=None):
            captured["updates"].append(values)

    class _SS:
        url = "https://docs.google.com/spreadsheets/d/FAKE"

        def __init__(self):
            self.sheet1 = _WS()

        def add_worksheet(self, title, rows, cols):
            return _WS()

        def share(self, email, perm_type, role):
            pass

        def batch_update(self, body):
            captured["batch"] = body
            return body

    class _Client:
        def create(self, title, folder_id=None):
            return _SS()

    return _Client(), captured


def test_writer_sends_one_batched_format_update():
    from compresearch.sheets import GoogleSheetWriter, build_sheet_model
    from compresearch.models import Branding
    client, captured = _formatting_fake_spreadsheet()
    writer = GoogleSheetWriter(client, "team@example.com", branding=Branding(primary_color="#AB1D42"))
    tabs = build_sheet_model(_full_jobdata(), run_date="2026-06-23")
    url = writer("Acme — Competitive Research", tabs)
    assert url.endswith("FAKE")
    assert captured["batch"] is not None
    reqs = captured["batch"]["requests"]
    # header styling + a basic filter both made it into the single batch
    kinds = {next(iter(r)) for r in reqs}
    assert "repeatCell" in kinds and "setBasicFilter" in kinds and "updateSheetProperties" in kinds


def test_writer_formatting_failure_still_returns_url():
    from compresearch.sheets import GoogleSheetWriter, build_sheet_model
    from compresearch.models import Branding
    client, captured = _formatting_fake_spreadsheet()

    ss = client.create("t")
    def boom(body):
        raise RuntimeError("bad request")
    # Patch the spreadsheet instance the writer will create to raise on batch_update.
    class _Client2:
        def create(self, title, folder_id=None):
            s = ss
            s.batch_update = boom
            return s
    writer = GoogleSheetWriter(_Client2(), "team@example.com", branding=Branding())
    tabs = build_sheet_model(_full_jobdata(), run_date="2026-06-23")
    url = writer("Acme — Competitive Research", tabs)   # must NOT raise
    assert url.endswith("FAKE")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_sheets.py::test_writer_sends_one_batched_format_update -v`
Expected: FAIL — `GoogleSheetWriter.__init__()` got an unexpected keyword argument `branding` (and no batch_update is sent).

- [ ] **Step 3: Update `GoogleSheetWriter`**

In `compresearch/sheets.py`, add the branding import near the others:

```python
from compresearch.branding import load_branding
```

Replace the `GoogleSheetWriter.__init__` and `__call__` with:

```python
    def __init__(self, client, share_email: str, folder_id: str | None = None,
                 branding: Branding | None = None) -> None:
        self.client = client
        self.share_email = share_email
        self.folder_id = folder_id
        self.branding = branding

    def __call__(self, title: str, tabs: list[SheetTab]) -> str:
        # When a Shared Drive (or folder) id is configured, create the Sheet inside it so
        # the file is owned by the drive rather than the quota-less service account.
        spreadsheet = self.client.create(title, folder_id=self.folder_id)
        placed: list[tuple[SheetTab, object]] = []
        for index, tab in enumerate(tabs):
            cols = max((len(row) for row in tab.rows), default=1)
            if index == 0:
                worksheet = spreadsheet.sheet1
                worksheet.update_title(tab.name)
            else:
                worksheet = spreadsheet.add_worksheet(
                    title=tab.name, rows=max(len(tab.rows) + 2, 10), cols=max(cols, 4)
                )
            if tab.rows:
                # The Sheets API rejects empty inner rows ([]); render blank spacer rows
                # as a single empty cell so both the layout and the API are satisfied.
                safe_rows = [row if row else [""] for row in tab.rows]
                worksheet.update(range_name="A1", values=safe_rows, raw=False)
            placed.append((tab, worksheet))
        spreadsheet.share(self.share_email, perm_type="user", role="writer")
        self._apply_formatting(spreadsheet, placed)
        return spreadsheet.url

    def _apply_formatting(self, spreadsheet, placed) -> None:
        """Best-effort: a formatting failure must never lose the already-written data."""
        branding = self.branding or load_branding()
        requests: list[dict] = []
        for tab, worksheet in placed:
            requests += build_format_requests(tab, worksheet.id, branding)
        if not requests:
            return
        try:
            spreadsheet.batch_update({"requests": requests})
        except Exception as exc:
            logging.warning("Sheet formatting failed (data is intact): %s", exc)
```

Note the `worksheet.update(...)` call gains `raw=False` so the Quick Wins / Document
`=HYPERLINK(...)` strings are parsed as formulas, not stored as literal text.

In `from_settings`, pass branding. Change the final return:

```python
        return cls(gspread.service_account(filename=sa_path), share_email, folder_id or None)
```

to:

```python
        return cls(gspread.service_account(filename=sa_path), share_email, folder_id or None,
                   load_branding())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_sheets.py -q`
Expected: PASS. Note: the existing `test_google_sheet_writer_sanitizes_empty_rows` calls
`worksheet.update(range_name=, values=)`; its fake `_WS.update` signature is
`def update(self, range_name=None, values=None)` — add `**kwargs` to it so the new `raw=False`
keyword is accepted. Make that one-line change to that fake if the test errors on the unexpected
keyword.

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add compresearch/sheets.py tests/test_sheets.py
git commit -m "feat: apply branded formatting in one batched Sheets update"
```

---

### Task 5: Full suite + live smoke check

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: all pass, no errors.

- [ ] **Step 2: Regenerate the real TAG Online sheet**

Run: `.venv\Scripts\python -m compresearch.cli sheet --job-dir jobs/tag-online`
Expected: exits cleanly (`Job complete: jobs\tag-online`).

- [ ] **Step 3: Verify the formatting landed**

Run: `.venv\Scripts\python -c "import json;d=json.load(open('jobs/tag-online/data.json'));print(d['sheet'])"`
Expected: `sheet_url` present, `error` null. Open the sheet URL and confirm by eye: frozen
brand-colored header rows, thousands/currency number formats on the Keyword Gaps / Quick Wins /
Topical Map numeric columns, a green→red difficulty scale and a green→red quick-win-position scale,
filters on Keyword Gaps and Quick Wins, a merged branded title on Overview with a Generated date,
and brand-tinted Overview tab. Confirm the Quick Wins URL cells are clickable.

- [ ] **Step 4: Final commit (only if the working tree has changes)**

```bash
git add -A
git commit -m "test: verify sheet formatting end to end" --allow-empty
```

---

## Self-Review Notes

- **Spec coverage:** metadata model (T1) ✓; per-tab declarations incl. run date, Overview title/tab color, Quick Wins HYPERLINK (T2) ✓; `_hex_to_rgb` + translator for header/freeze/number-formats/color-scales/filter/tab-color/title-block (T3) ✓; writer one-batch application + error isolation + `raw=False` for HYPERLINK + branding from settings (T4) ✓; verification incl. live smoke (T5) ✓.
- **Type consistency:** `ColorScale(col, direction)`, `TitleBlock(span)`, `SheetTab(... header, number_formats, color_scales, basic_filter, tab_color, title_block)`, `build_format_requests(tab, sheet_id, branding) -> list[dict]`, `build_sheet_model(data, run_date=None)`, `GoogleSheetWriter(client, share_email, folder_id=None, branding=None)` — all used identically across tasks.
- **Column indices** verified against the actual headers: Keyword Gaps {Volume=1, Difficulty=2, Best rank=3, Traffic value=4}; Quick Wins {position=1, Volume=2, Traffic value=3, URL=4}; Topical Map {Est. volume=5}; Sitemap {Total pages=1}.
