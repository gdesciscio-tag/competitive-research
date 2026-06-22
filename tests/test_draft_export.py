import pytest

from compresearch.models import Branding, DraftPost, InternalLink


def _post():
    return DraftPost(
        title="What Is a VSL?",
        target_keyword="video sales letter",
        title_tag="What Is a VSL? A Quick Guide",
        meta_description="A VSL turns visitors into customers.",
        body_markdown="## Intro\n\nA VSL is a **video sales letter**.",
        internal_links=[InternalLink(anchor="our services", url="https://acme.com/services")],
    )


def test_build_draft_html_includes_title_metadata_body_and_links():
    from compresearch.draft_export import build_draft_html

    html = build_draft_html(_post(), Branding())
    assert "<h1>What Is a VSL?</h1>" in html
    assert "video sales letter" in html          # target keyword in metadata header
    assert "What Is a VSL? A Quick Guide" in html  # title tag
    assert "A VSL turns visitors into customers." in html  # meta description
    assert "<strong>video sales letter</strong>" in html   # body rendered via markdown_to_html
    assert "https://acme.com/services" in html   # internal link url
    assert "our services" in html                # internal link anchor


def test_build_draft_html_escapes_metadata():
    from compresearch.draft_export import build_draft_html

    post = _post()
    post.title = "A < B & C"
    html = build_draft_html(post, Branding())
    assert "A &lt; B &amp; C" in html            # title escaped in the <h1>
    assert "<title>A &lt; B &amp; C</title>" in html  # title escaped at the <title> site too


def test_build_draft_html_drops_unsafe_link_scheme():
    from compresearch.draft_export import build_draft_html
    from compresearch.models import Branding, DraftPost, InternalLink

    post = DraftPost(
        title="T", body_markdown="body",
        internal_links=[InternalLink(anchor="click me", url="javascript:alert(1)")],
    )
    html = build_draft_html(post, Branding())
    assert "javascript:alert(1)" not in html   # the unsafe url never reaches an href
    assert "href" not in html.split("Internal links")[1]  # no anchor tag in the links list
    assert "click me" in html                  # anchor text still shown as plain text


class _FakeExecutable:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeFiles:
    def __init__(self, calls):
        self._calls = calls

    def create(self, body=None, media_body=None, fields=None, supportsAllDrives=None):
        self._calls["create"] = {
            "body": body, "fields": fields, "supportsAllDrives": supportsAllDrives,
        }
        return _FakeExecutable({"id": "DOC123", "webViewLink": "https://docs.google.com/document/d/DOC123/edit"})


class _FakePermissions:
    def __init__(self, calls):
        self._calls = calls

    def create(self, fileId=None, body=None, supportsAllDrives=None, sendNotificationEmail=None):
        self._calls["permission"] = {"fileId": fileId, "body": body}
        return _FakeExecutable({"id": "perm1"})


class _FakeService:
    def __init__(self):
        self.calls = {}

    def files(self):
        return _FakeFiles(self.calls)

    def permissions(self):
        return _FakePermissions(self.calls)


def test_google_doc_writer_uploads_html_into_folder_and_shares():
    from compresearch.draft_export import GoogleDocWriter

    service = _FakeService()
    writer = GoogleDocWriter(service, "team@example.com", folder_id="DRIVE9")
    url = writer("Acme — Draft Post", "<html><body><h1>Hi</h1></body></html>")

    assert url == "https://docs.google.com/document/d/DOC123/edit"
    create = service.calls["create"]
    assert create["body"]["mimeType"] == "application/vnd.google-apps.document"
    assert create["body"]["parents"] == ["DRIVE9"]
    assert create["supportsAllDrives"] is True
    assert service.calls["permission"]["body"]["emailAddress"] == "team@example.com"


def test_google_doc_writer_from_settings_requires_credentials(monkeypatch):
    from compresearch.draft_export import GoogleDocWriter

    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SHARE_EMAIL", raising=False)
    monkeypatch.delenv("GOOGLE_SHARED_DRIVE_ID", raising=False)
    with pytest.raises(RuntimeError):
        GoogleDocWriter.from_settings()
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "sa.json")
    with pytest.raises(RuntimeError):   # share email still missing
        GoogleDocWriter.from_settings()


from compresearch.job_store import create_job, load_data, save_data
from compresearch.models import JobConfig, JobData, DraftPostResult


def _job_with_draft(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = JobData(config=cfg, draft_post=DraftPostResult(post=_post()))
    save_data(job_dir, data)
    return job_dir


def test_run_draft_export_writes_html_and_records_doc_url(tmp_path):
    from compresearch.draft_export import run_draft_export

    job_dir = _job_with_draft(tmp_path)
    captured = {}

    def fake_doc_writer(title, html):
        captured["title"] = title
        captured["html"] = html
        return "https://docs.google.com/document/d/DOC/edit"

    run_draft_export(job_dir, doc_writer=fake_doc_writer)

    data = load_data(job_dir)
    assert data.draft_export.error is None
    assert data.draft_export.is_partial is False
    assert data.draft_export.doc_url.endswith("/edit")
    assert data.draft_export.html_path.endswith("acme-co-draft.html")
    assert (job_dir / "outputs" / "acme-co-draft.html").read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert captured["title"] == "Acme Co — Draft Post"


def test_run_draft_export_partial_when_doc_writer_fails(tmp_path):
    from compresearch.draft_export import run_draft_export

    job_dir = _job_with_draft(tmp_path)

    def boom(title, html):
        raise RuntimeError("drive unavailable")

    run_draft_export(job_dir, doc_writer=boom)

    data = load_data(job_dir)
    assert data.draft_export.html_path is not None     # HTML still written
    assert (job_dir / "outputs" / "acme-co-draft.html").exists()
    assert data.draft_export.doc_url is None
    assert data.draft_export.is_partial is True
    assert "drive unavailable" in data.draft_export.error


def test_run_draft_export_graceful_when_no_draft(tmp_path):
    from compresearch.draft_export import run_draft_export

    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)  # no draft_post

    run_draft_export(job_dir, doc_writer=lambda t, h: "unused")

    data = load_data(job_dir)
    assert data.draft_export.html_path is None
    assert data.draft_export.doc_url is None
    assert "No draft post" in data.draft_export.error
