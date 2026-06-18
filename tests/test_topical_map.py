# tests/test_topical_map.py
from compresearch.topical_map import build_topical_map_prompt


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


from compresearch.topical_map import run_topical_map
from compresearch.job_store import create_job, load_data, save_data
from compresearch.models import (
    JobConfig, SitemapResult, SitemapGap, DomainSitemap,
    KeywordResult, KeywordGap, QuickWin, TopicalMap, PillarTopic, TopicCluster, ArticleIdea,
)


def make_fake_generator(captured, result=None, raises=None, model="fake-model"):
    class FakeGenerator:
        def __init__(self):
            self.model = model

        def __call__(self, prompt):
            captured.append(prompt)
            if raises is not None:
                raise raises
            return result
    return FakeGenerator()


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


def test_run_topical_map_persists_result_and_grounds_prompt(tmp_path):
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


def test_run_topical_map_captures_generator_error(tmp_path):
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
    from compresearch.topical_map import ClaudeTopicalMapGenerator

    class _Resp:
        parsed_output = None
        stop_reason = "refusal"

    class _Messages:
        def parse(self, **kwargs):
            return _Resp()

    class _Client:
        messages = _Messages()

    gen = ClaudeTopicalMapGenerator(client=_Client())
    import pytest
    with pytest.raises(RuntimeError):
        gen("some prompt")


def test_run_topical_map_with_no_prior_modules_warns_and_persists(tmp_path, caplog):
    import logging
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    fake_map = TopicalMap(pillars=[])
    captured = []
    with caplog.at_level(logging.WARNING):
        run_topical_map(job_dir, generator=make_fake_generator(captured, result=fake_map))
    data = load_data(job_dir)
    assert data.topical_map is not None
    assert data.topical_map.map is not None
    assert "no sitemap or keyword gaps" in caplog.text
