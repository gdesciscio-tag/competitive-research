# compresearch/sheets.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from compresearch.job_store import load_data, save_data
from compresearch.models import JobData, SheetResult
from compresearch.utils import short_domain
from compresearch.settings import get_secret


@dataclass
class SheetTab:
    name: str
    rows: list[list] = field(default_factory=list)


def _cell(value):
    """Google Sheets cells: render None as an empty string."""
    return "" if value is None else value


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

    # --- Sitemap ---
    if data.sitemap is not None:
        rows = [["Site", "Total pages", "Posts/month"]]
        if data.sitemap.client is not None:
            c = data.sitemap.client
            rows.append([short_domain(c.domain), c.total_urls, _cell(c.posts_per_month)])
        for comp in data.sitemap.competitors:
            rows.append([short_domain(comp.domain), comp.total_urls, _cell(comp.posts_per_month)])
        if data.sitemap.gaps:
            rows += [[], ["Content gaps"], ["Section", "Competitors with it"]]
            for gap in data.sitemap.gaps:
                rows.append([gap.section, ", ".join(short_domain(d) for d in gap.competitors_with)])
        tabs.append(SheetTab("Sitemap", rows))

    # --- Keywords ---
    if data.keywords is not None:
        gap_rows = [["Keyword", "Volume", "Difficulty", "Best competitor rank",
                     "Est. traffic value", "Competitors"]]
        for g in data.keywords.gaps:
            gap_rows.append([
                g.keyword, _cell(g.search_volume), _cell(g.difficulty),
                _cell(g.best_competitor_position), _cell(g.traffic_value),
                ", ".join(short_domain(d) for d in g.competitors_ranking),
            ])
        tabs.append(SheetTab("Keyword Gaps", gap_rows))

        win_rows = [["Keyword", "Current position", "Volume", "Est. traffic value", "URL"]]
        for w in data.keywords.quick_wins:
            win_rows.append([w.keyword, w.position, _cell(w.search_volume),
                             _cell(w.traffic_value), _cell(w.url)])
        tabs.append(SheetTab("Quick Wins", win_rows))

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
        tabs.append(SheetTab("Topical Map", rows))

    # --- Draft post ---
    if data.draft_post is not None and data.draft_post.post is not None:
        post = data.draft_post.post
        rows = [
            ["Title", post.title],
            ["Target keyword", _cell(post.target_keyword)],
            ["Title tag", _cell(post.title_tag)],
            ["Meta description", _cell(post.meta_description)],
            [],
        ]
        if post.internal_links:
            rows += [["Internal links"], ["Anchor", "URL"]]
            for link in post.internal_links:
                rows.append([link.anchor, link.url])
            rows.append([])
        rows += [["Body (Markdown)"], [post.body_markdown]]
        tabs.append(SheetTab("Draft Post", rows))

    return tabs


SheetWriter = Callable[[str, list[SheetTab]], str]


class GoogleSheetWriter:
    """Writes the sheet model to a new Google Sheet via gspread and shares it. gspread is
    imported lazily so importing this module (and the test suite) does not require it."""

    def __init__(self, client, share_email: str) -> None:
        self.client = client
        self.share_email = share_email

    def __call__(self, title: str, tabs: list[SheetTab]) -> str:
        spreadsheet = self.client.create(title)
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
                worksheet.update(range_name="A1", values=safe_rows)
        spreadsheet.share(self.share_email, perm_type="user", role="writer")
        return spreadsheet.url

    @classmethod
    def from_settings(cls) -> "GoogleSheetWriter":
        sa_path = get_secret("GOOGLE_SERVICE_ACCOUNT_JSON")
        share_email = get_secret("GOOGLE_SHARE_EMAIL")
        if not sa_path:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON must be set to create a Google Sheet")
        if not share_email:
            raise RuntimeError("GOOGLE_SHARE_EMAIL must be set to share the created Google Sheet")
        import gspread

        return cls(gspread.service_account(filename=sa_path), share_email)


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
        tabs = build_sheet_model(data)
        url = writer(title, tabs)
        data.sheet = SheetResult(sheet_url=url)
    except Exception as exc:
        logging.warning("Google Sheet creation failed for %s: %s", data.config.client_url, exc)
        data.sheet = SheetResult(error=str(exc))
    save_data(job_dir, data)
    return data
