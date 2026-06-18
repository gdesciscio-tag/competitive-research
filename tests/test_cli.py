# tests/test_cli.py
import pytest

from compresearch.cli import run_from_args
from compresearch.job_store import create_job, load_data, save_data
from compresearch.models import (
    JobConfig, TopicalMap, PillarTopic, TopicCluster, ArticleIdea,
    TopicalMapResult, DraftPost,
)


def test_run_from_args_creates_job_and_runs_sitemap(tmp_path, make_fetch, client_map):
    fetch = make_fetch({
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": client_map,
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


def test_keywords_subcommand_api_mode_missing_credentials_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com", keyword_source="api")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
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


def test_topical_map_subcommand(tmp_path, make_fake_generator):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    business_description="Acme sells CRM software")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    fake_map = TopicalMap(pillars=[PillarTopic(
        name="CRM Basics",
        clusters=[TopicCluster(name="Intro", articles=[ArticleIdea(title="What is a CRM?")])],
    )])

    returned = run_from_args(
        ["topical-map", "--job-dir", str(job_dir)],
        generator=make_fake_generator([], result=fake_map),
    )
    assert returned == job_dir
    data = load_data(returned)
    assert data.topical_map.map.pillars[0].name == "CRM Basics"


def test_topical_map_subcommand_missing_api_key_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    with pytest.raises(SystemExit) as exc:
        run_from_args(["topical-map", "--job-dir", str(job_dir)])  # no generator -> from_settings
    assert exc.value.code == 1


def _fake_draft_generator(result):
    class FakeDraftGenerator:
        model = "fake-draft-model"

        def __call__(self, prompt):
            return result
    return FakeDraftGenerator()


def _seed_job_with_topical_map(tmp_path):
    """Create a job that has a topical map but NO sitemap — fully offline (no style fetch)."""
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    business_description="Acme sells CRM software")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = load_data(job_dir)
    data.topical_map = TopicalMapResult(
        map=TopicalMap(pillars=[PillarTopic(
            name="CRM Basics",
            clusters=[TopicCluster(name="Intro", articles=[
                ArticleIdea(title="What is a CRM?", target_keyword="what is a crm",
                            estimated_volume=2000),
            ])],
        )]),
        model="fake-model",
    )
    save_data(job_dir, data)
    return job_dir


def test_draft_post_subcommand(tmp_path):
    job_dir = _seed_job_with_topical_map(tmp_path)
    fake_post = DraftPost(
        title="What is a CRM?",
        target_keyword="what is a crm",
        body_markdown="# What is a CRM?\n\nA CRM is ...",
    )

    returned = run_from_args(
        ["draft-post", "--job-dir", str(job_dir)],
        draft_generator=_fake_draft_generator(fake_post),
    )
    assert returned == job_dir
    data = load_data(returned)
    assert data.draft_post is not None
    assert data.draft_post.post.title == "What is a CRM?"
    assert data.draft_post.error is None


def test_draft_post_subcommand_missing_api_key_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    job_dir = _seed_job_with_topical_map(tmp_path)
    with pytest.raises(SystemExit) as exc:
        run_from_args(["draft-post", "--job-dir", str(job_dir)])  # no draft_generator -> from_settings
    assert exc.value.code == 1
