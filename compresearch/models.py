# compresearch/models.py
from __future__ import annotations

from datetime import date
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


def _has_host(url: str) -> bool:
    return bool(urlparse(url if "://" in url else "https://" + url).netloc)


class UrlEntry(BaseModel):
    loc: str
    lastmod: date | None = None


class DomainSitemap(BaseModel):
    domain: str
    urls: list[UrlEntry] = Field(default_factory=list)
    section_counts: dict[str, int] = Field(default_factory=dict)
    total_urls: int = 0
    posts_per_month: float | None = None
    error: str | None = None


class SitemapGap(BaseModel):
    section: str
    competitors_with: list[str] = Field(default_factory=list)
    client_count: int = 0


class SitemapResult(BaseModel):
    client: DomainSitemap | None = None
    competitors: list[DomainSitemap] = Field(default_factory=list)
    gaps: list[SitemapGap] = Field(default_factory=list)
    is_partial: bool = False


class KeywordEntry(BaseModel):
    keyword: str
    search_volume: int | None = None
    difficulty: float | None = None
    position: int | None = None
    url: str | None = None


class DomainKeywords(BaseModel):
    domain: str
    keywords: list[KeywordEntry] = Field(default_factory=list)
    total_keywords: int = 0
    error: str | None = None


class KeywordGap(BaseModel):
    keyword: str
    search_volume: int | None = None
    difficulty: float | None = None
    competitors_ranking: list[str] = Field(default_factory=list)
    best_competitor_position: int | None = None
    traffic_value: float | None = None


class QuickWin(BaseModel):
    keyword: str
    position: int
    search_volume: int | None = None
    url: str | None = None
    traffic_value: float | None = None


class KeywordResult(BaseModel):
    client: DomainKeywords | None = None
    competitors: list[DomainKeywords] = Field(default_factory=list)
    gaps: list[KeywordGap] = Field(default_factory=list)
    quick_wins: list[QuickWin] = Field(default_factory=list)
    is_partial: bool = False


class JobConfig(BaseModel):
    client_name: str
    client_url: str
    competitor_urls: list[str] = Field(default_factory=list)
    keyword_source: Literal["api", "manual"] = "api"

    @field_validator("client_url")
    @classmethod
    def _client_url_has_host(cls, value: str) -> str:
        if not _has_host(value):
            raise ValueError(f"client_url is not a valid URL: {value!r}")
        return value

    @field_validator("competitor_urls")
    @classmethod
    def _competitor_urls_have_host(cls, value: list[str]) -> list[str]:
        for url in value:
            if not _has_host(url):
                raise ValueError(f"competitor_url is not a valid URL: {url!r}")
        return value


class JobData(BaseModel):
    config: JobConfig
    sitemap: SitemapResult | None = None
    keywords: KeywordResult | None = None
    # Future sections (topical_map, draft_post) added in later plans.
