# compresearch/draft_post.py
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import anthropic
from lxml import html as lxml_html

from compresearch.job_store import load_data, save_data
from compresearch.models import ArticleIdea, DraftPost, DraftPostResult, JobData, TopicalMap
from compresearch.settings import get_secret
from compresearch.sitemap import Fetcher, http_fetch


def select_topic(
    topical_map: TopicalMap | None, preferred_keyword: str | None = None
) -> ArticleIdea | None:
    """Pick the article to draft: the operator's preferred keyword if given, else the
    highest-estimated-volume article. Returns None if there are no articles."""
    if topical_map is None:
        return None
    articles = [
        article
        for pillar in topical_map.pillars
        for cluster in pillar.clusters
        for article in cluster.articles
    ]
    if not articles:
        return None
    if preferred_keyword:
        needle = preferred_keyword.lower()
        for article in articles:
            if (article.target_keyword or "").lower() == needle or needle in article.title.lower():
                return article
    return max(articles, key=lambda a: a.estimated_volume or 0)


CONTENT_PATH_HINTS = ("blog", "article", "news", "post", "insight", "guide", "resource")


def _select_style_urls(urls: list[str], max_samples: int) -> list[str]:
    """Prefer content/blog-looking pages; fall back to any non-homepage URL."""
    content = [u for u in urls if any(hint in u.lower() for hint in CONTENT_PATH_HINTS)]
    pool = content or [u for u in urls if urlparse(u).path.strip("/")]
    return pool[:max_samples]


def _extract_text(content: bytes) -> str:
    """Strip scripts/styles and collapse a page's visible text to a single string."""
    if not content:
        return ""
    doc = lxml_html.fromstring(content)
    for element in doc.xpath("//script | //style"):
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)
    return " ".join(doc.text_content().split())


def fetch_style_samples(
    client_urls: list[str], fetch: Fetcher, max_samples: int = 3, max_chars: int = 1500
) -> list[str]:
    """Fetch a few of the client's existing pages and return cleaned text snippets.
    Never raises — pages that fail to fetch or parse are skipped with a warning."""
    samples: list[str] = []
    for url in _select_style_urls(client_urls, max_samples):
        try:
            text = _extract_text(fetch(url))
        except Exception as exc:
            logging.warning("Could not fetch style sample from %s: %s", url, exc)
            continue
        if text:
            samples.append(text[:max_chars])
    return samples


def build_draft_post_prompt(
    title: str,
    target_keyword: str | None,
    search_intent: str | None,
    business_description: str | None,
    style_samples: list[str],
    internal_link_candidates: list[str],
    max_candidates: int = 30,
) -> str:
    """Build the Claude prompt for a complete, style-matched blog post (deterministic)."""
    lines: list[str] = [
        "You are an expert content marketer and SEO copywriter. Write a complete, "
        "publish-ready blog post for a client.",
        f"\nWorking title: {title}",
    ]
    if target_keyword:
        lines.append(f"Primary target keyword: {target_keyword}")
    if search_intent:
        lines.append(f"Search intent: {search_intent}")
    if business_description:
        lines.append(f"Client business: {business_description}")

    if style_samples:
        lines.append(
            "\nMatch the voice, tone, vocabulary, sentence rhythm, and formatting of these "
            "samples from the client's own existing content:"
        )
        for index, sample in enumerate(style_samples, 1):
            lines.append(f"--- Sample {index} ---\n{sample}")
    else:
        lines.append(
            "\nNo style samples are available; write in a clear, professional, engaging voice."
        )

    if internal_link_candidates:
        lines.append(
            "\nSuggest 2-5 internal links using ONLY these existing client URLs (choose the "
            "most relevant, with natural anchor text). Do not invent or modify URLs:"
        )
        for url in internal_link_candidates[:max_candidates]:
            lines.append(f"- {url}")
    else:
        lines.append(
            "\nNo internal-link candidate URLs are available; return an empty internal_links list."
        )

    lines.append(
        """
Produce: an SEO title tag (<= 60 characters), a meta description (<= 160 characters), an
outline of the H2/H3 headings, and the full body in Markdown (about 1000-1500 words) that
uses the primary keyword naturally in the title, opening, and headings. Include the chosen
internal links. Return the result in the required structured format."""
    )
    return "\n".join(lines)


DEFAULT_DRAFT_POST_MODEL = "claude-opus-4-8"

DraftGenerator = Callable[[str], DraftPost]


class ClaudeDraftPostGenerator:
    """Generates a DraftPost via the Claude API. The network call is isolated here so
    the rest of the module tests offline with a fake generator."""

    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        model: str = DEFAULT_DRAFT_POST_MODEL,
        max_tokens: int = 16000,
    ) -> None:
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens
        self.last_usage: dict | None = None

    def __call__(self, prompt: str) -> DraftPost:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
            output_format=DraftPost,
        )
        usage = getattr(response, "usage", None)
        self.last_usage = (
            {
                "input_tokens": getattr(usage, "input_tokens", 0) or 0,
                "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            }
            if usage is not None
            else None
        )
        post = response.parsed_output
        if post is None:
            raise RuntimeError(
                f"Claude returned no structured output (stop_reason="
                f"{getattr(response, 'stop_reason', None)!r})"
            )
        return post

    @classmethod
    def from_settings(cls) -> "ClaudeDraftPostGenerator":
        if not get_secret("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY must be set to generate a draft post")
        return cls()


def _client_urls(data: JobData) -> list[str]:
    if data.sitemap is not None and data.sitemap.client is not None:
        return [entry.loc for entry in data.sitemap.client.urls]
    return []


def run_draft_post(
    job_dir: Path,
    generator: DraftGenerator | None = None,
    fetch: Fetcher = http_fetch,
    preferred_keyword: str | None = None,
) -> JobData:
    """Select a topic, generate a style-matched draft, and persist it to data.json."""
    data = load_data(job_dir)
    if generator is None:
        generator = ClaudeDraftPostGenerator.from_settings()
    model = getattr(generator, "model", None)

    topical_map = data.topical_map.map if data.topical_map is not None else None
    article = select_topic(topical_map, preferred_keyword)
    if article is None:
        logging.warning(
            "No topical-map article to draft for %s; run the topical-map module first",
            data.config.client_url,
        )
        data.draft_post = DraftPostResult(
            model=model, error="No topical-map article available to draft"
        )
        save_data(job_dir, data)
        return data

    candidates = _client_urls(data)
    if data.config.style_sample:
        style_samples = [data.config.style_sample]
    else:
        style_samples = fetch_style_samples(candidates, fetch) if candidates else []

    prompt = build_draft_post_prompt(
        title=article.title,
        target_keyword=article.target_keyword,
        search_intent=article.search_intent,
        business_description=data.config.business_description,
        style_samples=style_samples,
        internal_link_candidates=candidates,
    )
    selected = article.target_keyword or article.title
    try:
        post = generator(prompt)
        candidate_set = set(candidates)
        post.internal_links = [link for link in post.internal_links if link.url in candidate_set]
        data.draft_post = DraftPostResult(post=post, model=model, selected_keyword=selected)
    except Exception as exc:
        logging.warning("Draft post generation failed for %s: %s", data.config.client_url, exc)
        data.draft_post = DraftPostResult(model=model, selected_keyword=selected, error=str(exc))
    save_data(job_dir, data)
    return data
