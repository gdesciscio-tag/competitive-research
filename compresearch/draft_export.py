# compresearch/draft_export.py
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape

from compresearch.branding import load_branding
from compresearch.job_store import load_data, save_data, slugify
from compresearch.models import Branding, DraftExportItem, DraftExportResult, DraftPost, JobData
from compresearch.render import markdown_to_html
from compresearch.settings import get_secret


def build_draft_html(post: DraftPost, branding: Branding) -> str:
    """Render a DraftPost into a complete, standalone, lightly-branded HTML document.

    Browser-viewable and clean enough to paste into a CMS or convert to a Google Doc.
    Pure and deterministic. Title and SEO metadata are LLM output and are escaped; the
    body HTML is the already-rendered Markdown (trusted; see render.markdown_to_html).
    """
    meta_rows = []
    for label, value in (
        ("Target keyword", post.target_keyword),
        ("Title tag", post.title_tag),
        ("Meta description", post.meta_description),
    ):
        if value:
            meta_rows.append(
                f"<tr><th align='left'>{escape(label)}</th><td>{escape(value)}</td></tr>"
            )
    meta_table = f"<table>{''.join(meta_rows)}</table>" if meta_rows else ""

    def _link_item(link) -> str:
        # The url field is LLM-sourced; only emit a real href for http(s) schemes so a
        # javascript:/data: URL cannot become a live link in the browser-viewable output.
        if link.url.lower().startswith(("http://", "https://")):
            return f"<li><a href=\"{escape(link.url)}\">{escape(link.anchor)}</a></li>"
        return f"<li>{escape(link.anchor)}</li>"

    links_html = ""
    if post.internal_links:
        items = "".join(_link_item(link) for link in post.internal_links)
        links_html = f"<h2>Internal links</h2><ul>{items}</ul>"

    body_html = markdown_to_html(post.body_markdown)

    # branding.* come from the trusted branding config (not user/LLM input).
    return (
        "<!DOCTYPE html>"
        "<html><head><meta charset=\"utf-8\">"
        f"<title>{escape(post.title)}</title>"
        f"<style>body{{font-family:{branding.font_family};color:{branding.text_color};}}"
        f"h1,h2{{color:{branding.primary_color};}}"
        "table{border-collapse:collapse;margin:0 0 1em;}"
        "th,td{padding:2px 8px;}</style></head><body>"
        f"<h1>{escape(post.title)}</h1>"
        f"{meta_table}"
        f"{body_html}"
        f"{links_html}"
        "</body></html>"
    )


DOC_MIME = "application/vnd.google-apps.document"

DocWriter = Callable[[str, str], str]


class GoogleDocWriter:
    """Uploads draft HTML to Google Drive, converted to a Google Doc, inside a Shared
    Drive folder, and shares it. The googleapiclient import is lazy so importing this
    module (and the test suite) does not require it."""

    def __init__(self, service, share_email: str, folder_id: str | None = None) -> None:
        self.service = service
        self.share_email = share_email
        self.folder_id = folder_id

    def __call__(self, title: str, html: str) -> str:
        from googleapiclient.http import MediaInMemoryUpload

        body = {"name": title, "mimeType": DOC_MIME}
        if self.folder_id:
            body["parents"] = [self.folder_id]
        media = MediaInMemoryUpload(html.encode("utf-8"), mimetype="text/html", resumable=False)
        created = self.service.files().create(
            body=body,
            media_body=media,
            fields="id,webViewLink",
            supportsAllDrives=True,
        ).execute()
        doc_id = created["id"]
        self.service.permissions().create(
            fileId=doc_id,
            body={"type": "user", "role": "writer", "emailAddress": self.share_email},
            supportsAllDrives=True,
            sendNotificationEmail=False,
        ).execute()
        return created.get("webViewLink") or f"https://docs.google.com/document/d/{doc_id}/edit"

    @classmethod
    def from_settings(cls) -> "GoogleDocWriter":
        sa_path = get_secret("GOOGLE_SERVICE_ACCOUNT_JSON")
        share_email = get_secret("GOOGLE_SHARE_EMAIL")
        folder_id = get_secret("GOOGLE_SHARED_DRIVE_ID")
        if not sa_path:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON must be set to create a Google Doc")
        if not share_email:
            raise RuntimeError("GOOGLE_SHARE_EMAIL must be set to share the created Google Doc")
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_service_account_file(
            sa_path, scopes=["https://www.googleapis.com/auth/drive"]
        )
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return cls(service, share_email, folder_id or None)


def run_draft_export(job_dir: Path, doc_writer: DocWriter | None = None, branding: Branding | None = None) -> JobData:
    """Render every draft to a local HTML file and a Google Doc; record them in data.json.

    Exports each entry in data.draft_posts (so a re-drafted/second post is included). The
    first draft keeps the stable `<slug>-draft.html` name; extras get `-2`, `-3`, … Each
    draft's HTML is written first; a Drive/Doc failure leaves that HTML in place and marks
    the item partial. Top-level fields mirror the first draft. Never raises — failures are
    captured like the other steps.
    """
    data = load_data(job_dir)
    drafts = [d for d in data.draft_posts if d.post is not None]
    if not drafts:
        logging.warning(
            "No draft post to export for %s; run the draft-post module first",
            data.config.client_url,
        )
        data.draft_export = DraftExportResult(error="No draft post available to export")
        save_data(job_dir, data)
        return data

    branding = branding or load_branding()
    slug = slugify(data.config.client_name)
    multiple = len(drafts) > 1

    # Resolve the Doc writer once; if it's unavailable every item is HTML-only/partial.
    writer = doc_writer
    writer_error: str | None = None
    if writer is None:
        try:
            writer = GoogleDocWriter.from_settings()
        except Exception as exc:
            logging.warning("Google Doc writer unavailable for %s: %s", data.config.client_url, exc)
            writer_error = str(exc)

    items: list[DraftExportItem] = []
    for index, draft in enumerate(drafts):
        post = draft.post
        suffix = "" if index == 0 else f"-{index + 1}"
        output_path = Path(job_dir) / "outputs" / f"{slug}-draft{suffix}.html"
        item = DraftExportItem(selected_keyword=draft.selected_keyword)

        try:
            html = build_draft_html(post, branding)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html, encoding="utf-8")
            item.html_path = str(output_path)
        except Exception as exc:
            logging.warning("Draft HTML render failed for %s: %s", data.config.client_url, exc)
            item.error = str(exc)
            items.append(item)
            continue

        if writer is None:
            item.is_partial = True
            item.error = writer_error
            items.append(item)
            continue

        title = f"{data.config.client_name} — Draft Post"
        if multiple:
            title = f"{title}: {post.title}"
        try:
            item.doc_url = writer(title, html)
        except Exception as exc:
            logging.warning("Google Doc creation failed for %s: %s", data.config.client_url, exc)
            item.is_partial = True
            item.error = str(exc)
        items.append(item)

    first = items[0]
    data.draft_export = DraftExportResult(
        items=items,
        html_path=first.html_path,
        doc_url=first.doc_url,
        is_partial=any(i.is_partial for i in items),
        error=first.error,
    )
    save_data(job_dir, data)
    return data
