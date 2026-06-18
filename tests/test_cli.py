# tests/test_cli.py
from compresearch.cli import run_from_args
from compresearch.job_store import load_data

CLIENT_MAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://acme.com/blog/a</loc></url>
</urlset>"""


def make_fetch(pages):
    def fetch(url):
        if url not in pages:
            raise FileNotFoundError(url)
        return pages[url]
    return fetch


def test_run_from_args_creates_job_and_runs_sitemap(tmp_path):
    fetch = make_fetch({
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": CLIENT_MAP,
    })
    job_dir = run_from_args(
        [
            "sitemap",
            "--client-name", "Acme Co",
            "--client-url", "https://acme.com",
            "--competitors", "",
            "--jobs-dir", str(tmp_path),
        ],
        fetch=fetch,
    )
    assert job_dir == tmp_path / "acme-co"
    data = load_data(job_dir)
    assert data.sitemap.client.total_urls == 1


from compresearch.job_store import create_job
from compresearch.models import JobConfig


def test_keywords_subcommand_api_mode_missing_credentials_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com", keyword_source="api")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    import pytest
    with pytest.raises(SystemExit) as exc:
        run_from_args(["keywords", "--job-dir", str(job_dir)])
    assert exc.value.code == 1


def test_keywords_subcommand_manual_mode(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    competitor_urls=["https://rival.com"], keyword_source="manual")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    input_dir = job_dir / "keywords_input"
    input_dir.mkdir()
    (input_dir / "acme-com.csv").write_text(
        "keyword,search_volume,difficulty,position,url\ncrm software,1000,40,8,\n", encoding="utf-8")
    (input_dir / "rival-com.csv").write_text(
        "keyword,search_volume,difficulty,position,url\nfree crm,800,30,4,\n", encoding="utf-8")

    returned = run_from_args(["keywords", "--job-dir", str(job_dir)])
    assert returned == job_dir
    data = load_data(returned)
    assert [g.keyword for g in data.keywords.gaps] == ["free crm"]


from compresearch.models import (
    TopicalMap, PillarTopic, TopicCluster, ArticleIdea,
)


def _fake_generator(result):
    class FakeGenerator:
        model = "fake-model"

        def __call__(self, prompt):
            return result
    return FakeGenerator()


def test_topical_map_subcommand(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    business_description="Acme sells CRM software")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    fake_map = TopicalMap(pillars=[PillarTopic(
        name="CRM Basics",
        clusters=[TopicCluster(name="Intro", articles=[ArticleIdea(title="What is a CRM?")])],
    )])

    returned = run_from_args(
        ["topical-map", "--job-dir", str(job_dir)],
        generator=_fake_generator(fake_map),
    )
    assert returned == job_dir
    data = load_data(returned)
    assert data.topical_map.map.pillars[0].name == "CRM Basics"


def test_topical_map_subcommand_missing_api_key_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    import pytest
    with pytest.raises(SystemExit) as exc:
        run_from_args(["topical-map", "--job-dir", str(job_dir)])  # no generator -> from_settings
    assert exc.value.code == 1
