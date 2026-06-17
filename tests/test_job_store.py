# tests/test_job_store.py
from compresearch.job_store import slugify, create_job, load_config, load_data, save_data
from compresearch.models import JobConfig


def test_slugify():
    assert slugify("Acme Co. Ltd!") == "acme-co-ltd"
    assert slugify("  Multiple   Spaces ") == "multiple-spaces"


def test_create_job_writes_files(tmp_path):
    cfg = JobConfig(
        client_name="Acme Co",
        client_url="https://acme.com",
        competitor_urls=["https://rival.com"],
    )
    job_dir = create_job(cfg, jobs_dir=tmp_path)

    assert job_dir == tmp_path / "acme-co"
    assert (job_dir / "job.yaml").exists()
    assert (job_dir / "data.json").exists()
    assert (job_dir / "outputs").is_dir()


def test_load_config_and_data_round_trip(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)

    loaded_cfg = load_config(job_dir)
    assert loaded_cfg.client_name == "Acme Co"

    data = load_data(job_dir)
    assert data.config.client_url == "https://acme.com"
    assert data.sitemap is None


def test_save_data_persists_changes(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)

    data = load_data(job_dir)
    data.config.keyword_source = "manual"
    save_data(job_dir, data)

    assert load_data(job_dir).config.keyword_source == "manual"
