# tests/test_topical_map.py
import logging

import pytest

from compresearch.topical_map import (
    build_topical_map_prompt,
    run_topical_map,
    ClaudeTopicalMapGenerator,
)
from compresearch.job_store import create_job, load_data, save_data
from compresearch.models import (
    JobConfig, SitemapResult, SitemapGap, DomainSitemap,
    KeywordResult, KeywordGap, QuickWin, TopicalMap, PillarTopic, TopicCluster, ArticleIdea,
)


def test_prompt_includes_grounding_data():
    prompt = build_topical_map_prompt(
        client_url="https://acme.com",
        business_description="Acme sells CRM software",
        existing_sections=["blog", "pricing"],
        sitemap_gaps=["case-studies"],
        keyword_gaps=[("free crm", 800), ("crm comparison", None)],
        quick_wins=[("crm software", 8)],
    )
    assert "https://acme.com" in prompt
    assert "Acme sells CRM software" in prompt
    assert "case-studies" in prompt          # sitemap gap surfaced
    assert "free crm" in prompt              # keyword gap surfaced
    assert "crm software" in prompt          # quick win surfaced
    assert "blog" in prompt                  # existing section listed to avoid
    assert "topical map" in prompt.lower()


def test_prompt_handles_missing_business_description():
    prompt = build_topical_map_prompt(
        client_url="https://acme.com",
        business_description=None,
        existing_sections=[],
        sitemap_gaps=[],
        keyword_gaps=[],
        quick_wins=[],
    )
    assert "infer" in prompt.lower()         # tells the model to infer context


def _seed_job(tmp_path):
    cfg = JobConfig(
        client_name="Acme Co",
        client_url="https://acme.com",
        competitor_urls=["https://rival.com"],
        business_description="Acme sells CRM software",
    )
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = load_data(job_dir)
    data.sitemap = SitemapResult(
        client=DomainSitemap(domain="https://acme.com", section_counts={"blog": 3}),
        gaps=[SitemapGap(section="case-studies", competitors_with=["https://rival.com"])],
    )
    data.keywords = KeywordResult(
        gaps=[KeywordGap(keyword="free crm", search_volume=800, best_competitor_position=4)],
        quick_wins=[QuickWin(keyword="crm software", position=8, search_volume=1000)],
    )
    save_data(job_dir, data)
    return job_dir


def test_run_topical_map_persists_result_and_grounds_prompt(tmp_path, make_fake_generator):
    job_dir = _seed_job(tmp_path)
    fake_map = TopicalMap(pillars=[PillarTopic(
        name="CRM Basics",
        clusters=[TopicCluster(name="Getting started", articles=[
            ArticleIdea(title="What is a CRM?", target_keyword="free crm")])],
    )])
    captured = []
    run_topical_map(job_dir, generator=make_fake_generator(captured, result=fake_map))

    data = load_data(job_dir)
    assert data.topical_map is not None
    assert data.topical_map.error is None
    assert data.topical_map.model == "fake-model"
    assert data.topical_map.map.pillars[0].name == "CRM Basics"
    # prompt was grounded in the prior modules' data
    assert "case-studies" in captured[0]
    assert "free crm" in captured[0]
    assert "crm software" in captured[0]
    assert "blog" in captured[0]


def test_run_topical_map_captures_generator_error(tmp_path, make_fake_generator):
    job_dir = _seed_job(tmp_path)
    captured = []
    run_topical_map(
        job_dir,
        generator=make_fake_generator(captured, raises=RuntimeError("api down")),
    )
    data = load_data(job_dir)
    assert data.topical_map is not None
    assert data.topical_map.map is None
    assert "api down" in data.topical_map.error
    assert data.topical_map.model == "fake-model"


def test_generator_raises_when_parsed_output_is_none():
    class _Resp:
        parsed_output = None
        stop_reason = "refusal"

    class _Messages:
        def parse(self, **kwargs):
            return _Resp()

    class _Client:
        messages = _Messages()

        def with_options(self, **kwargs):
            return self

    gen = ClaudeTopicalMapGenerator(client=_Client())
    with pytest.raises(RuntimeError):
        gen("some prompt")


def test_run_topical_map_with_no_prior_modules_warns_and_persists(tmp_path, caplog, make_fake_generator):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    fake_map = TopicalMap(pillars=[])
    captured = []
    with caplog.at_level(logging.WARNING):
        run_topical_map(job_dir, generator=make_fake_generator(captured, result=fake_map))
    data = load_data(job_dir)
    assert data.topical_map is not None
    assert data.topical_map.map is not None
    assert "no sitemap gaps and no keyword gaps" in caplog.text


def test_no_gap_warning_when_keyword_gaps_present_without_sitemap(tmp_path, caplog, make_fake_generator):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = load_data(job_dir)
    data.keywords = KeywordResult(gaps=[KeywordGap(keyword="free crm", search_volume=800)])
    save_data(job_dir, data)
    captured = []
    fake_map = TopicalMap(pillars=[])
    with caplog.at_level(logging.WARNING):
        run_topical_map(job_dir, generator=make_fake_generator(captured, result=fake_map))
    assert "no sitemap gaps and no keyword gaps" not in caplog.text


def test_prompt_honors_empty_business_description():
    prompt = build_topical_map_prompt(
        client_url="https://acme.com",
        business_description="",
        existing_sections=[],
        sitemap_gaps=[],
        keyword_gaps=[],
        quick_wins=[],
    )
    assert "infer" not in prompt.lower()   # explicit empty string is honored, not inferred


def test_generator_records_last_usage():
    from compresearch.topical_map import ClaudeTopicalMapGenerator
    from compresearch.models import TopicalMap

    class _Usage:
        input_tokens = 1200
        output_tokens = 800

    class _Resp:
        parsed_output = TopicalMap(pillars=[])
        usage = _Usage()

    class _Messages:
        def parse(self, **kwargs):
            return _Resp()

    class _Client:
        messages = _Messages()

        def with_options(self, **kwargs):
            return self

    gen = ClaudeTopicalMapGenerator(client=_Client())
    assert gen.last_usage is None          # nothing recorded before the first call
    gen("prompt")
    assert gen.last_usage == {"input_tokens": 1200, "output_tokens": 800}


def test_run_topical_map_skips_when_cached(tmp_path):
    from compresearch.models import TopicalMapResult
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = load_data(job_dir)
    data.topical_map = TopicalMapResult(map=TopicalMap(pillars=[PillarTopic(name="P")]), model="cached")
    save_data(job_dir, data)
    # No generator passed: if it didn't skip it would hit from_settings/the API. It skips.
    run_topical_map(job_dir)
    assert load_data(job_dir).topical_map.model == "cached"


def test_run_topical_map_force_recomputes(tmp_path, make_fake_generator):
    from compresearch.models import TopicalMapResult
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = load_data(job_dir)
    data.topical_map = TopicalMapResult(map=TopicalMap(pillars=[PillarTopic(name="Old")]), model="cached")
    save_data(job_dir, data)
    new_map = TopicalMap(pillars=[PillarTopic(name="New")])
    run_topical_map(job_dir, generator=make_fake_generator([], result=new_map), force=True)
    assert load_data(job_dir).topical_map.map.pillars[0].name == "New"
