# compresearch/models.py
from __future__ import annotations

from datetime import date

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


class JobConfig(BaseModel):
    client_name: str
    client_url: str
    competitor_urls: list[str] = Field(default_factory=list)
    keyword_source: str = "api"  # "api" | "manual"


class JobData(BaseModel):
    config: JobConfig
    sitemap: SitemapResult | None = None
    # Future sections (keywords, topical_map, draft_post) added in later plans.
