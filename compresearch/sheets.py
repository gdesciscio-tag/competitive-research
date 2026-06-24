# compresearch/sheets.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from compresearch.job_store import load_data, save_data
from compresearch.models import Branding, DomainKeywords, JobData, SheetResult
from compresearch.utils import short_domain
from compresearch.settings import get_secret
from compresearch.branding import load_branding


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
    banding: bool = False       # alternating row stripes on the data rows
    auto_resize: bool = False   # size columns to fit their content


def _cell(value):
    """Google Sheets cells: render None as an empty string."""
    return "" if value is None else value


_NO_DATA = "—"


def _provided_cell(value):
    """Client-provided-keyword tab cells: render an em dash for absent data, so a
    blank (no DataForSEO volume, or nobody ranking) reads as 'no data' rather than
    a failure. Real zeros (e.g. difficulty 0) are preserved."""
    return _NO_DATA if value is None or value == "" else value


def _cadence_note(dom) -> str:
    """Flag a posts/month figure that can't be trusted (too few or outlier dates)."""
    if dom.posts_per_month is not None and not dom.posts_per_month_reliable:
        return "estimate unreliable — sparse or outlier publish dates"
    return ""


def _safe_value(cell):
    """Neutralize accidental formula injection. Values are written with USER_ENTERED
    (raw=False) so that intended =HYPERLINK formulas evaluate; that also means a text cell
    starting with = + - @ would be parsed as a formula. Prefix such text with an apostrophe
    (renders as plain text) while leaving real =HYPERLINK formulas untouched."""
    if isinstance(cell, str) and cell[:1] in ("=", "+", "-", "@") and not cell.startswith("=HYPERLINK("):
        return "'" + cell
    return cell


# Fixed semantic heatmap endpoints (not brand colors).
_GREEN = {"red": 0.42, "green": 0.66, "blue": 0.31}
_RED = {"red": 0.85, "green": 0.33, "blue": 0.31}
_WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
_BAND_GRAY = {"red": 0.953, "green": 0.957, "blue": 0.965}  # ~#F3F4F6, subtle stripe


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

    if n_rows > 1:
        for col, pattern in sorted(tab.number_formats.items()):
            requests.append({"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": n_rows,
                          "startColumnIndex": col, "endColumnIndex": col + 1},
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": pattern}}},
                "fields": "userEnteredFormat.numberFormat",
            }})

    if n_rows > 1:
        for scale in tab.color_scales:
            if scale.direction == "low_good":
                low, high = _GREEN, _RED
            elif scale.direction == "high_good":
                low, high = _RED, _GREEN
            else:
                raise ValueError(f"Unknown color scale direction: {scale.direction!r}")
            requests.append({"addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": n_rows,
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

    # Alternating row stripes on the data rows (header row keeps its brand fill).
    if tab.banding and n_rows > 1:
        requests.append({"addBanding": {"bandedRange": {
            "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": n_rows,
                      "startColumnIndex": 0, "endColumnIndex": n_cols},
            "rowProperties": {"firstBandColor": _WHITE, "secondBandColor": _BAND_GRAY},
        }}})

    # Size columns to their content. Appended last so it accounts for the bold
    # header and any other width-affecting formatting above.
    if tab.auto_resize and n_cols > 0:
        requests.append({"autoResizeDimensions": {"dimensions": {
            "sheetId": sheet_id, "dimension": "COLUMNS",
            "startIndex": 0, "endIndex": n_cols,
        }}})

    return requests


# Google Sheets tab names cannot contain these characters and cap at 100 chars.
_INVALID_TAB_CHARS = str.maketrans({c: " " for c in ":\\/?*[]"})


def _sheet_tab_name(name: str) -> str:
    # Truncate to the 100-char cap first, then strip — otherwise a sanitized
    # character at position 100 could leave a trailing space after the slice.
    return name.translate(_INVALID_TAB_CHARS)[:100].strip() or "Sheet"


def _keyword_list_rows(dk: DomainKeywords) -> list[list]:
    """Rows for a single domain's ranked keyword list, sorted by volume desc."""
    rows = [["Keyword", "Volume", "Difficulty", "Position", "URL"]]
    for e in sorted(dk.keywords, key=lambda k: k.search_volume or 0, reverse=True):
        if e.url:
            safe_url = e.url.replace('"', "%22")
            url_cell = f'=HYPERLINK("{safe_url}", "{safe_url}")'
        else:
            url_cell = ""
        rows.append([e.keyword, _cell(e.search_volume), _cell(e.difficulty),
                     _cell(e.position), url_cell])
    return rows


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

    # --- Sitemap ---
    if data.sitemap is not None:
        rows = [["Site", "Total pages", "Posts/month", "Note"]]
        domains = ([data.sitemap.client] if data.sitemap.client is not None else []) \
            + list(data.sitemap.competitors)
        for dom in domains:
            rows.append([short_domain(dom.domain), dom.total_urls,
                         _cell(dom.posts_per_month), _cadence_note(dom)])
        if data.sitemap.gaps:
            rows += [[], ["Content gaps"], ["Section", "Competitors with it"]]
            for gap in data.sitemap.gaps:
                rows.append([gap.section, ", ".join(short_domain(d) for d in gap.competitors_with)])
        tabs.append(SheetTab("Sitemap", rows, header=True, number_formats={1: "#,##0"}))

    # --- Keywords ---
    # Raw keyword inventories (provided wishlist, client, competitors) come first,
    # then the derived analysis tabs (gaps, quick wins).
    if data.keywords is not None:
        # --- Client-provided keyword wishlist (only when supplied) ---
        if data.keywords.provided:
            prov_rows = [["Keyword", "Volume", "Difficulty", "Client rank",
                          "Competitors ranking", "Best competitor rank"]]
            for p in data.keywords.provided:
                comps = ", ".join(short_domain(d) for d in p.competitors_ranking)
                prov_rows.append([
                    p.keyword, _provided_cell(p.search_volume), _provided_cell(p.difficulty),
                    _provided_cell(p.client_position), _provided_cell(comps),
                    _provided_cell(p.best_competitor_position),
                ])
            tabs.append(SheetTab(
                "Client-Provided Keywords", prov_rows, header=True, basic_filter=True,
                number_formats={1: "#,##0", 2: "0", 3: "0", 5: "0"},
            ))

        # --- Client's own ranked keywords ---
        if data.keywords.client is not None and data.keywords.client.keywords:
            tabs.append(SheetTab(
                _sheet_tab_name(f"{config.client_name} — Keywords"),
                _keyword_list_rows(data.keywords.client),
                header=True, basic_filter=True,
                number_formats={1: "#,##0", 2: "0", 3: "0"},
            ))

        # --- One tab per competitor ---
        for comp in data.keywords.competitors:
            if not comp.keywords:
                continue
            tabs.append(SheetTab(
                _sheet_tab_name(short_domain(comp.domain)),
                _keyword_list_rows(comp),
                header=True, basic_filter=True,
                number_formats={1: "#,##0", 2: "0", 3: "0"},
            ))

        # --- Keyword gaps (analysis) ---
        gap_rows = [["Keyword", "Volume", "Difficulty", "Best competitor rank",
                     "Est. traffic value", "Competitors"]]
        for g in data.keywords.gaps:
            gap_rows.append([
                g.keyword, _cell(g.search_volume), _cell(g.difficulty),
                _cell(g.best_competitor_position), _cell(g.traffic_value),
                ", ".join(short_domain(d) for d in g.competitors_ranking),
            ])
        tabs.append(SheetTab(
            "Keyword Gaps", gap_rows, header=True, basic_filter=True,
            number_formats={1: "#,##0", 2: "0", 3: "0", 4: "$#,##0"},
            color_scales=[ColorScale(2, "low_good")],
        ))

        # --- Quick wins (analysis) ---
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

    # --- Topical map ---
    if data.topical_map is not None and data.topical_map.map is not None:
        rows = [["Pillar", "Cluster", "Article", "Target keyword", "Intent", "Est. volume"]]
        for pillar in data.topical_map.map.pillars:
            for cluster in pillar.clusters:
                for article in cluster.articles:
                    rows.append([
                        pillar.name, cluster.name, article.title,
                        _cell(article.target_keyword), _cell(article.search_intent),
                        _cell(article.estimated_volume),
                    ])
        tabs.append(SheetTab("Topical Map", rows, header=True, number_formats={5: "#,##0"}))

    # --- Draft post (metadata only; the prose lives in the exported Doc/HTML) ---
    if data.draft_post is not None and data.draft_post.post is not None:
        post = data.draft_post.post
        rows = [
            ["Title", post.title],
            ["Target keyword", _cell(post.target_keyword)],
            ["Title tag", _cell(post.title_tag)],
            ["Meta description", _cell(post.meta_description)],
        ]
        doc_url = data.draft_export.doc_url if data.draft_export is not None else None
        if doc_url:
            # Escape any double-quote so a stray quote can't break out of the formula string.
            safe_url = doc_url.replace('"', "%22")
            rows.append(["Document", f'=HYPERLINK("{safe_url}", "Open draft")'])
        tabs.append(SheetTab("Draft Post", rows))

    # Polish applied uniformly: auto-size every tab's columns, and stripe the
    # data rows of the table tabs (those with a header row).
    for tab in tabs:
        tab.auto_resize = True
        if tab.header:
            tab.banding = True

    return tabs


SheetWriter = Callable[[str, list[SheetTab]], str]


class GoogleSheetWriter:
    """Writes the sheet model to a new Google Sheet via gspread and shares it. gspread is
    imported lazily so importing this module (and the test suite) does not require it."""

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
                safe_rows = [[_safe_value(c) for c in (row if row else [""])] for row in tab.rows]
                worksheet.update(range_name="A1", values=safe_rows, raw=False)
            placed.append((tab, worksheet))
        spreadsheet.share(self.share_email, perm_type="user", role="writer")
        self._apply_formatting(spreadsheet, placed)
        return spreadsheet.url

    def _apply_formatting(self, spreadsheet, placed) -> None:
        """Best-effort: a formatting failure must never lose the already-written data."""
        try:
            branding = self.branding or load_branding()
            requests: list[dict] = []
            for tab, worksheet in placed:
                requests += build_format_requests(tab, worksheet.id, branding)
            if not requests:
                return
            spreadsheet.batch_update({"requests": requests})
        except Exception as exc:
            logging.warning("Sheet formatting failed (data is intact): %s", exc)

    @classmethod
    def from_settings(cls) -> "GoogleSheetWriter":
        sa_path = get_secret("GOOGLE_SERVICE_ACCOUNT_JSON")
        share_email = get_secret("GOOGLE_SHARE_EMAIL")
        folder_id = get_secret("GOOGLE_SHARED_DRIVE_ID")
        if not sa_path:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON must be set to create a Google Sheet")
        if not share_email:
            raise RuntimeError("GOOGLE_SHARE_EMAIL must be set to share the created Google Sheet")
        import gspread

        return cls(gspread.service_account(filename=sa_path), share_email, folder_id or None,
                   load_branding())


def run_sheet(job_dir, writer: SheetWriter | None = None) -> JobData:
    """Build the sheet model, write it to a Google Sheet, and record the URL in data.json."""
    data = load_data(job_dir)
    if (
        data.sitemap is None
        and data.keywords is None
        and data.topical_map is None
        and data.draft_post is None
    ):
        logging.warning(
            "Sheet for %s has no analysis sections yet; run the analysis modules first",
            data.config.client_url,
        )
    if writer is None:
        writer = GoogleSheetWriter.from_settings()
    title = f"{data.config.client_name} — Competitive Research"
    try:
        tabs = build_sheet_model(data, run_date=date.today().isoformat())
        url = writer(title, tabs)
        data.sheet = SheetResult(sheet_url=url)
    except Exception as exc:
        logging.warning("Google Sheet creation failed for %s: %s", data.config.client_url, exc)
        data.sheet = SheetResult(error=str(exc))
    save_data(job_dir, data)
    return data
