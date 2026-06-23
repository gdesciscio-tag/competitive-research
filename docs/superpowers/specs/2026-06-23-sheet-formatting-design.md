# Sheet Formatting — Design

**Date:** 2026-06-23
**Status:** Approved (pending spec review)

## Problem

`build_sheet_model` ([compresearch/sheets.py](../../../compresearch/sheets.py)) produces `SheetTab(name, rows)` —
pure values — and `GoogleSheetWriter.__call__` writes them with a bare
`worksheet.update(range_name="A1", values=safe_rows)` and nothing else. No bold, no frozen
headers, no number formats, no color. The data is correct but lands in a raw container that
reads as "dumped" rather than "designed" on a client-facing deliverable.

## Goal

Make the generated Google Sheet look designed and let a non-technical operator read the
insight at a glance, driven by `branding.json` colors. Scope: all six formatting items —
(1) frozen branded header rows, (2) number/currency formats, (3) insight color scales,
(4) basic filters, (5) auto-resize, (6) polish (hyperlinks, merged Overview title block,
tab colors).

## Non-Goals

- No change to which tabs exist or what data they contain (that is `build_sheet_model`'s
  current responsibility and stays as-is apart from added formatting metadata + a run-date row).
- No change outside the Sheet path (`compresearch/sheets.py` + its tests).

## Decisions (from brainstorming)

- **Scope:** all six items.
- **Architecture:** Approach A — declarative formatting metadata on the model; a pure
  translator builds raw Sheets API request objects; the writer sends one `batch_update`.

## Architecture

### 1. Model enrichment (`sheets.py`)

`SheetTab` gains formatting fields, all defaulting to "no formatting" so untouched tabs render
exactly as today. Two small helper dataclasses support color scales and the Overview title.

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
    header: bool = False                                          # row 0 = bold white on brand, frozen
    number_formats: dict[int, str] = field(default_factory=dict)  # col -> pattern, e.g. "#,##0", "$#,##0"
    color_scales: list[ColorScale] = field(default_factory=list)
    basic_filter: bool = False                                    # filter over the data range
    tab_color: bool = False                                       # tint the worksheet tab brand color
    title_block: TitleBlock | None = None                         # Overview merged title
```

### 2. What each tab declares (in `build_sheet_model`)

- **Overview** — `title_block=TitleBlock(span=2)` on the "Competitive Research" row;
  `tab_color=True`; a new `["Generated", run_date]` row. `build_sheet_model` gains a
  `run_date: str | None = None` parameter; `run_sheet` defaults it to `date.today().isoformat()`,
  mirroring how `render` takes `report_date`.
- **Sitemap** — `header=True`; `number_formats={1: "#,##0"}` (Total pages). The gaps sub-table
  lower in the same tab stays plain; formatting targets the top header row and the numeric column.
- **Keyword Gaps** — `header=True`, `basic_filter=True`;
  `number_formats={1: "#,##0", 2: "0", 3: "0", 4: "$#,##0"}`
  (Volume, Difficulty, Best competitor rank, Est. traffic value);
  `color_scales=[ColorScale(2, "low_good")]` (difficulty: easy = green).
- **Quick Wins** — `header=True`, `basic_filter=True`; the URL column (index 4) becomes a real
  `=HYPERLINK(url)` cell **only when a URL is present** (blank cell otherwise, never
  `=HYPERLINK("")`); the URL is double-quote-escaped like the Draft Post Document link; `number_formats={1: "0", 2: "#,##0", 3: "$#,##0"}`
  (Current position, Volume, Est. traffic value);
  `color_scales=[ColorScale(1, "low_good")]` (position: closer to #1 = green).
- **Topical Map** — `header=True`; `number_formats={5: "#,##0"}` (Est. volume).
- **Draft Post** — unchanged. It is a label/value sheet with no header row and already carries
  its own `=HYPERLINK` Document row.

### 3. Translator: `build_format_requests(tab, sheet_id, branding) -> list[dict]` (pure)

Maps a tab's metadata to raw Sheets API request objects. One feature -> one (or two) request types:

- **header** -> `repeatCell` over row 0 (`backgroundColor` = brand primary, `textFormat` = bold +
  white foreground) **and** `updateSheetProperties` with `gridProperties.frozenRowCount = 1`.
- **number_formats** -> one `repeatCell` per column with
  `userEnteredFormat.numberFormat {type: "NUMBER", pattern}` over that column's data rows.
- **color_scales** -> one `addConditionalFormatRule` per scale, a `GradientRule` over the column's
  data rows. `low_good`: minpoint green, maxpoint red; `high_good`: reversed.
- **basic_filter** -> `setBasicFilter` over the used range (header + data).
- **tab_color** -> `updateSheetProperties` with `tabColor` = brand primary.
- **title_block** -> `mergeCells` across `span` columns on row 0, plus a `repeatCell` giving that
  cell larger, bold, brand-colored text.

Brand colors come from the `Branding` object (loaded from `branding.json`) via a small
`_hex_to_rgb("#AB1D42") -> {"red": .., "green": .., "blue": ..}` helper (floats 0..1). The
green/red heatmap endpoints are fixed semantic colors, not brand colors.

Ranges use a `GridRange` with `sheetId=sheet_id` and the row/column indices derived from
`tab.rows` (e.g. header = rows [0,1); data = rows [1, len(rows))).

### 4. Writer integration (`GoogleSheetWriter.__call__`)

After the existing value-writing loop:

1. Build a `[(tab, worksheet.id)]` list as worksheets are created.
2. Accumulate `build_format_requests(tab, sheet_id, self.branding)` across all tabs into one
   `requests` list.
3. Send a single `spreadsheet.batch_update({"requests": requests})`.

`GoogleSheetWriter` gains a `branding` attribute, set in `from_settings()` via
`load_branding()` and injectable through `__init__` for tests (default `load_branding()` or a
passed-in `Branding`).

### 5. Error handling

Formatting is best-effort polish and must never lose the data. The `batch_update` call is
wrapped in its own try/except: a formatting failure logs a warning but the method still returns
the sheet URL with the data intact. (This is in addition to `run_sheet`'s outer try/except, so a
single malformed request can't blank out an otherwise-good sheet.)

### 6. Testing

- **Model:** assert `build_sheet_model` sets the right metadata — e.g. Keyword Gaps has
  `header=True`, `number_formats[4] == "$#,##0"`, and a `ColorScale(2, "low_good")`; Overview has
  a `title_block` and `tab_color=True` and a "Generated" row with the passed `run_date`.
- **Translator:** `build_format_requests` is pure — feed it a tab + a fake `sheet_id` + a
  `Branding`, assert the emitted request dicts: frozen row count = 1, the brand `backgroundColor`
  on the header, the `numberFormat` patterns per column, the gradient min/max colors per
  direction, the basic-filter range, the merged title block. Fully offline.
- **`_hex_to_rgb`** unit test (e.g. `"#AB1D42"` -> expected float triple).
- **Writer:** extend the existing fake `_SS`/`_WS` to capture `batch_update`; assert one batched
  call carrying the accumulated requests; assert that a `batch_update` exception still returns the
  URL (error isolation) with the data writes already done.
- Existing sheet tests stay green because metadata defaults to "off" where not set.

## Affected Files

- `compresearch/sheets.py` — `ColorScale`/`TitleBlock` types, enriched `SheetTab`,
  `build_sheet_model` metadata + `run_date` param, `build_format_requests`, `_hex_to_rgb`,
  `GoogleSheetWriter` branding + `batch_update` integration, `run_sheet` run-date default.
- `tests/test_sheets.py` — model metadata, translator, `_hex_to_rgb`, writer batch/isolation tests.
