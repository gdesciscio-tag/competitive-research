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
