# compresearch/models.py
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


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


class JobData(BaseModel):
    config: JobConfig
    sitemap: SitemapResult | None = None
    keywords: KeywordResult | None = None
    # Future sections (topical_map, draft_post) added in later plans.
