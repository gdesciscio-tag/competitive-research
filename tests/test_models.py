# tests/test_models.py
import pytest

from datetime import date
from pydantic import ValidationError
from compresearch.models import (
    UrlEntry, DomainSitemap, SitemapGap, SitemapResult, JobConfig, JobData,
)


def test_jobconfig_defaults():
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    assert cfg.competitor_urls == []
    assert cfg.keyword_source == "api"


def test_jobdata_round_trip_through_json():
    cfg = JobConfig(
        client_name="Acme Co",
        client_url="https://acme.com",
        competitor_urls=["https://rival.com"],
    )
    sitemap = SitemapResult(
        client=DomainSitemap(
            domain="https://acme.com",
            urls=[UrlEntry(loc="https://acme.com/blog/x", lastmod=date(2026, 1, 1))],
            section_counts={"blog": 1},
            total_urls=1,
            posts_per_month=2.5,
        ),
        competitors=[DomainSitemap(domain="https://rival.com")],
        gaps=[SitemapGap(section="services", competitors_with=["https://rival.com"], client_count=0)],
    )
    data = JobData(config=cfg, sitemap=sitemap)

    restored = JobData.model_validate_json(data.model_dump_json())
    assert restored.config.client_name == "Acme Co"
    assert restored.sitemap.client.urls[0].lastmod == date(2026, 1, 1)
    assert restored.sitemap.gaps[0].section == "services"


def test_jobdata_sitemap_optional():
    data = JobData(config=JobConfig(client_name="X", client_url="https://x.com"))
    assert data.sitemap is None


def test_jobconfig_rejects_invalid_keyword_source():
    with pytest.raises(ValidationError):
        JobConfig(client_name="X", client_url="https://x.com", keyword_source="bogus")


from compresearch.models import (
    KeywordEntry, DomainKeywords, KeywordGap, QuickWin, KeywordResult,
)


def test_keyword_models_round_trip():
    result = KeywordResult(
        client=DomainKeywords(
            domain="https://acme.com",
            keywords=[KeywordEntry(keyword="crm software", search_volume=1000,
                                   difficulty=40.0, position=8, url="https://acme.com/crm")],
            total_keywords=1,
        ),
        competitors=[DomainKeywords(domain="https://rival.com")],
        gaps=[KeywordGap(keyword="free crm", search_volume=500,
                         competitors_ranking=["https://rival.com"],
                         best_competitor_position=3, traffic_value=55.0)],
        quick_wins=[QuickWin(keyword="crm software", position=8,
                             search_volume=1000, traffic_value=30.0)],
        is_partial=False,
    )
    restored = KeywordResult.model_validate_json(result.model_dump_json())
    assert restored.client.keywords[0].keyword == "crm software"
    assert restored.gaps[0].best_competitor_position == 3
    assert restored.quick_wins[0].position == 8
    assert restored.is_partial is False


def test_jobdata_has_optional_keywords():
    from compresearch.models import JobConfig, JobData
    data = JobData(config=JobConfig(client_name="X", client_url="https://x.com"))
    assert data.keywords is None


def test_jobconfig_rejects_invalid_url():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        JobConfig(client_name="X", client_url="https://")
    with pytest.raises(ValidationError):
        JobConfig(client_name="X", client_url="https://x.com", competitor_urls=[""])


def test_jobconfig_accepts_bare_domain():
    cfg = JobConfig(client_name="X", client_url="acme.com", competitor_urls=["rival.com"])
    assert cfg.client_url == "acme.com"


from compresearch.models import (
    ArticleIdea, TopicCluster, PillarTopic, TopicalMap, TopicalMapResult,
)


def test_topical_map_models_round_trip():
    result = TopicalMapResult(
        map=TopicalMap(
            pillars=[PillarTopic(
                name="CRM Basics",
                description="Foundational CRM education",
                clusters=[TopicCluster(
                    name="Getting started",
                    articles=[ArticleIdea(
                        title="What is a CRM?",
                        target_keyword="what is a crm",
                        search_intent="informational",
                        estimated_volume=2000,
                        rationale="Fills an informational gap.",
                    )],
                )],
            )],
            summary="Three pillars covering CRM education and comparison.",
        ),
        model="claude-sonnet-4-6",
    )
    restored = TopicalMapResult.model_validate_json(result.model_dump_json())
    assert restored.map.pillars[0].clusters[0].articles[0].target_keyword == "what is a crm"
    assert restored.model == "claude-sonnet-4-6"
    assert restored.error is None


def test_jobconfig_business_description_optional_and_jobdata_topical_map():
    from compresearch.models import JobConfig, JobData
    cfg = JobConfig(client_name="X", client_url="https://x.com")
    assert cfg.business_description is None
    cfg2 = JobConfig(client_name="X", client_url="https://x.com",
                     business_description="We sell CRM software")
    assert cfg2.business_description == "We sell CRM software"
    assert JobData(config=cfg).topical_map is None


from compresearch.models import InternalLink, DraftPost, DraftPostResult


def test_draft_post_models_round_trip():
    result = DraftPostResult(
        post=DraftPost(
            title="What is a CRM?",
            target_keyword="what is a crm",
            title_tag="What Is a CRM? A Plain-English Guide",
            meta_description="A clear guide to what a CRM is and why it matters.",
            outline=["What a CRM does", "Who needs one"],
            body_markdown="# What is a CRM?\n\nA CRM is...",
            internal_links=[InternalLink(anchor="our pricing", url="https://acme.com/pricing")],
            word_count=1200,
        ),
        model="claude-opus-4-8",
        selected_keyword="what is a crm",
    )
    restored = DraftPostResult.model_validate_json(result.model_dump_json())
    assert restored.post.internal_links[0].url == "https://acme.com/pricing"
    assert restored.selected_keyword == "what is a crm"
    assert restored.error is None


def test_jobconfig_style_sample_optional_and_jobdata_draft_post():
    from compresearch.models import JobConfig, JobData
    cfg = JobConfig(client_name="X", client_url="https://x.com")
    assert cfg.style_sample is None
    assert JobData(config=cfg).draft_post is None


def test_branding_defaults():
    from compresearch.models import Branding
    b = Branding()
    assert b.agency_name == "TAG Online"
    assert b.primary_color.startswith("#")
    assert b.logo_path is None
