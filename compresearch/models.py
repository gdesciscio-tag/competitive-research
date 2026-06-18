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


class ArticleIdea(BaseModel):
    title: str
    target_keyword: str | None = None
    search_intent: str | None = None
    estimated_volume: int | None = None
    rationale: str | None = None


class TopicCluster(BaseModel):
    name: str
    articles: list[ArticleIdea] = Field(default_factory=list)


class PillarTopic(BaseModel):
    name: str
    description: str | None = None
    clusters: list[TopicCluster] = Field(default_factory=list)


class TopicalMap(BaseModel):
    pillars: list[PillarTopic] = Field(default_factory=list)
    summary: str | None = None


class TopicalMapResult(BaseModel):
    # No is_partial flag (unlike SitemapResult/KeywordResult): a topical map is one
    # atomic LLM call, so success/failure is binary — see the `error` field.
    map: TopicalMap | None = None
    model: str | None = None
    error: str | None = None


class InternalLink(BaseModel):
    anchor: str
    url: str


class DraftPost(BaseModel):
    title: str
    target_keyword: str | None = None
    title_tag: str | None = None
    meta_description: str | None = None
    outline: list[str] = Field(default_factory=list)
    body_markdown: str
    internal_links: list[InternalLink] = Field(default_factory=list)
    word_count: int | None = None


class DraftPostResult(BaseModel):
    # No is_partial flag (like TopicalMapResult): one atomic LLM call — success/failure
    # is binary, see the `error` field.
    post: DraftPost | None = None
    model: str | None = None
    selected_keyword: str | None = None  # which topic was drafted
    error: str | None = None


class Branding(BaseModel):
    agency_name: str = "TAG Online"
    primary_color: str = "#16314F"   # deep navy (placeholder — override in branding.json)
    accent_color: str = "#E2703A"    # warm accent (placeholder)
    text_color: str = "#1F2933"
    muted_color: str = "#52606D"
    font_family: str = "Georgia, 'Times New Roman', serif"
    logo_path: str | None = None     # None -> the agency name is rendered as a text logo


class RenderResult(BaseModel):
    pdf_path: str | None = None
    error: str | None = None


class SheetResult(BaseModel):
    sheet_url: str | None = None
    error: str | None = None


class StepResult(BaseModel):
    name: str
    status: str  # "ok" | "failed" | "skipped"
    error: str | None = None
    duration_seconds: float | None = None
    cost_usd: float | None = None


class RunReport(BaseModel):
    steps: list[StepResult] = Field(default_factory=list)
    total_cost_usd: float = 0.0


class JobConfig(BaseModel):
    client_name: str
    client_url: str
    competitor_urls: list[str] = Field(default_factory=list)
    business_description: str | None = None
    style_sample: str | None = None
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
    topical_map: TopicalMapResult | None = None
    draft_post: DraftPostResult | None = None
    render: RenderResult | None = None
    sheet: SheetResult | None = None
    run_report: RunReport | None = None
