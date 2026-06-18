# Draft Post Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Draft Post module to `compresearch` that selects the highest-opportunity article from the topical map, generates a complete SEO-optimized blog post via the Claude API, style-matched to the client's own existing writing (auto-fetched from their crawled pages), with internal-link suggestions drawn only from the client's real URLs — written to a job's `data.json`.

**Architecture:** Mirrors the topical-map module. The Claude call is isolated behind an injectable generator (`DraftGenerator = Callable[[str], DraftPost]` with a `.model` attribute) and the style-sample fetching reuses the sitemap module's injectable `Fetcher` — so the whole module tests fully offline with zero API spend and zero network. The real generator uses the official `anthropic` SDK with structured output and **`claude-opus-4-8`** (the client-facing quality showcase). This is the last analysis module; it consumes the outputs of all three prior modules (`data.topical_map` for the topic, `data.sitemap` for style samples + internal-link candidates).

**Tech Stack:** Python 3.11+ (running on 3.14), pydantic v2, `anthropic` SDK, `lxml` (HTML→text), pytest. Builds on Plans 1–3 (merged to `master`). No new dependencies.

---

## Context for the implementer

Already present in `compresearch` (do not recreate): `models.py` (schema incl. `JobConfig`, `JobData`, `SitemapResult`/`DomainSitemap`/`UrlEntry`, `KeywordResult`, `TopicalMapResult`/`TopicalMap`/`PillarTopic`/`TopicCluster`/`ArticleIdea`), `settings.py` (`get_secret`), `job_store.py` (`load_data`, `save_data`, `create_job`), `sitemap.py` (exports `Fetcher`, `http_fetch`), `keywords.py`, `topical_map.py` (`ClaudeTopicalMapGenerator`, `build_topical_map_prompt`, `Generator`), `cli.py` (subcommands `sitemap`, `keywords`, `topical-map`; `run_from_args(argv, fetch=http_fetch, provider=None, generator=None) -> Path`). 67 tests pass. Run tests with `.venv\Scripts\python -m pytest` (Windows). Work on a feature branch off `master`; commit per task with the messages given.

**Decisions already made (from brainstorming):**
- **Style match:** auto-fetch and extract text from a few of the client's existing pages (selected from the URLs the sitemap module crawled), feed them to the LLM as a style reference. Optional `style_sample` override on the job config. Degrade gracefully if pages can't be fetched.
- **Model:** **`claude-opus-4-8`** is the configurable default (exact model-ID string — no date suffix).
- **Topic selection:** auto-pick the article with the highest `estimated_volume`; a CLI `--keyword` lets the operator target a specific topic. Re-run to draft more articles (zero checkpoints).
- **Generation:** one structured Claude call producing the full draft (title tag, meta description, outline, body markdown, internal links).

**Claude API notes (from the claude-api reference):** use `client.messages.parse(model="claude-opus-4-8", max_tokens=16000, thinking={"type":"adaptive"}, messages=[...], output_format=DraftPost).parsed_output`; guard `parsed_output is None` (refusal / max_tokens) by raising. `anthropic.Anthropic()` reads `ANTHROPIC_API_KEY` from env. `claude-opus-4-8` uses adaptive thinking; `max_tokens=16000` is fine non-streaming. The same `messages.parse`/`output_format` SDK fallback note from Plan 3 applies if needed (isolated to the generator).

---

## File Structure

| File | Responsibility |
|------|----------------|
| `compresearch/models.py` (modify) | Add `style_sample` to `JobConfig`; add `InternalLink`, `DraftPost`, `DraftPostResult`; add `draft_post` to `JobData` |
| `compresearch/draft_post.py` (create) | Topic selection, style-sample fetch/extract, prompt builder, `ClaudeDraftPostGenerator`, `run_draft_post` |
| `compresearch/cli.py` (modify) | Add a `draft-post` subcommand with clean error handling |
| `tests/test_draft_post.py` (create) | Selection, style extraction, prompt, orchestration — all offline (fake generator + fake fetch) |
| `tests/test_cli.py` (modify) | End-to-end `draft-post` run with a fake generator; missing-API-key clean exit |
| `README.md` (modify) | Document the draft-post usage; mark the module complete |

---

## Task 1: Draft post data models

**Files:**
- Modify: `compresearch/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_models.py -k draft_post`
Expected: FAIL — `ImportError: cannot import name 'InternalLink'`.

- [ ] **Step 3: Write the implementation**

In `compresearch/models.py`, add `style_sample` to `JobConfig` (after `business_description`):

```python
    style_sample: str | None = None
```

Add the draft-post models (after the topical-map models, before `JobConfig`):

```python
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
```

Extend `JobData`:

```python
class JobData(BaseModel):
    config: JobConfig
    sitemap: SitemapResult | None = None
    keywords: KeywordResult | None = None
    topical_map: TopicalMapResult | None = None
    draft_post: DraftPostResult | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_models.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add compresearch/models.py tests/test_models.py
git commit -m "feat: add draft-post data models and style_sample"
```

---

## Task 2: Topic selection

**Files:**
- Create: `compresearch/draft_post.py`
- Test: `tests/test_draft_post.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_draft_post.py
from compresearch.draft_post import select_topic
from compresearch.models import TopicalMap, PillarTopic, TopicCluster, ArticleIdea


def _map():
    return TopicalMap(pillars=[PillarTopic(name="P", clusters=[TopicCluster(name="C", articles=[
        ArticleIdea(title="Low one", target_keyword="low", estimated_volume=100),
        ArticleIdea(title="High one", target_keyword="high", estimated_volume=900),
        ArticleIdea(title="Unknown vol", target_keyword="unknown"),
    ])])])


def test_select_topic_picks_highest_volume():
    assert select_topic(_map()).target_keyword == "high"


def test_select_topic_honors_preferred_keyword():
    assert select_topic(_map(), preferred_keyword="low").target_keyword == "low"


def test_select_topic_none_when_empty():
    assert select_topic(None) is None
    assert select_topic(TopicalMap(pillars=[])) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_draft_post.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'compresearch.draft_post'`.

- [ ] **Step 3: Write the implementation**

```python
# compresearch/draft_post.py
from __future__ import annotations

from compresearch.models import ArticleIdea, TopicalMap


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_draft_post.py`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/draft_post.py tests/test_draft_post.py
git commit -m "feat: add draft-post topic selection"
```

---

## Task 3: Style-sample fetching + text extraction

**Files:**
- Modify: `compresearch/draft_post.py`
- Test: `tests/test_draft_post.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_draft_post.py`:

```python
from compresearch.draft_post import _select_style_urls, fetch_style_samples


def make_fetch(pages: dict[str, bytes]):
    def fetch(url: str) -> bytes:
        if url not in pages:
            raise FileNotFoundError(url)
        return pages[url]
    return fetch


BLOG_HTML = (
    b"<html><head><style>.x{color:red}</style></head>"
    b"<body><script>var a=1;</script>"
    b"<h1>Our CRM Guide</h1><p>We help teams close deals faster.</p></body></html>"
)


def test_select_style_urls_prefers_content_pages():
    urls = ["https://acme.com/about", "https://acme.com/blog/a", "https://acme.com/blog/b"]
    assert _select_style_urls(urls, 3) == ["https://acme.com/blog/a", "https://acme.com/blog/b"]


def test_select_style_urls_falls_back_to_non_root():
    urls = ["https://acme.com/", "https://acme.com/about"]
    assert _select_style_urls(urls, 3) == ["https://acme.com/about"]


def test_fetch_style_samples_extracts_clean_text():
    fetch = make_fetch({"https://acme.com/blog/crm-guide": BLOG_HTML})
    samples = fetch_style_samples(
        ["https://acme.com/blog/crm-guide", "https://acme.com/"], fetch
    )
    assert len(samples) == 1
    assert "Our CRM Guide" in samples[0]
    assert "We help teams close deals faster." in samples[0]
    assert "var a" not in samples[0]   # script stripped
    assert "color:red" not in samples[0]  # style stripped


def test_fetch_style_samples_skips_fetch_failures():
    fetch = make_fetch({})  # every fetch raises
    assert fetch_style_samples(["https://acme.com/blog/x"], fetch) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_draft_post.py -k style`
Expected: FAIL — `ImportError: cannot import name '_select_style_urls'`.

- [ ] **Step 3: Write the implementation**

Add these imports to the top of `compresearch/draft_post.py` (with the existing ones):

```python
import logging
from urllib.parse import urlparse

from lxml import html as lxml_html

from compresearch.sitemap import Fetcher
```

Append:

```python
CONTENT_PATH_HINTS = ("blog", "article", "news", "post", "insight", "guide", "resource")


def _select_style_urls(urls: list[str], max_samples: int) -> list[str]:
    """Prefer content/blog-looking pages; fall back to any non-homepage URL."""
    content = [u for u in urls if any(hint in u.lower() for hint in CONTENT_PATH_HINTS)]
    pool = content or [u for u in urls if urlparse(u).path.strip("/")]
    return pool[:max_samples]


def _extract_text(content: bytes) -> str:
    """Strip scripts/styles and collapse a page's visible text to a single string."""
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_draft_post.py -k style`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/draft_post.py tests/test_draft_post.py
git commit -m "feat: fetch and extract client style samples for draft posts"
```

---

## Task 4: Prompt builder

**Files:**
- Modify: `compresearch/draft_post.py`
- Test: `tests/test_draft_post.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_draft_post.py`:

```python
from compresearch.draft_post import build_draft_post_prompt


def test_prompt_includes_topic_style_and_links():
    prompt = build_draft_post_prompt(
        title="What is a CRM?",
        target_keyword="what is a crm",
        search_intent="informational",
        business_description="Acme sells CRM software",
        style_samples=["We help teams close deals faster."],
        internal_link_candidates=["https://acme.com/pricing", "https://acme.com/blog/crm-tips"],
    )
    assert "what is a crm" in prompt.lower()
    assert "We help teams close deals faster." in prompt   # style sample surfaced
    assert "https://acme.com/pricing" in prompt            # internal-link candidate surfaced
    assert "internal link" in prompt.lower()
    assert "meta description" in prompt.lower()


def test_prompt_handles_no_style_and_no_links():
    prompt = build_draft_post_prompt(
        title="What is a CRM?",
        target_keyword="what is a crm",
        search_intent=None,
        business_description=None,
        style_samples=[],
        internal_link_candidates=[],
    )
    assert "no style samples" in prompt.lower()
    assert "empty internal_links" in prompt.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_draft_post.py -k prompt`
Expected: FAIL — `ImportError: cannot import name 'build_draft_post_prompt'`.

- [ ] **Step 3: Write the implementation**

Append to `compresearch/draft_post.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_draft_post.py -k prompt`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/draft_post.py tests/test_draft_post.py
git commit -m "feat: add draft-post prompt builder"
```

---

## Task 5: Generator + `run_draft_post` orchestration

**Files:**
- Modify: `compresearch/draft_post.py`
- Test: `tests/test_draft_post.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_draft_post.py`:

```python
from compresearch.draft_post import run_draft_post
from compresearch.job_store import create_job, load_data, save_data
from compresearch.models import (
    JobConfig, SitemapResult, DomainSitemap, UrlEntry,
    TopicalMapResult, DraftPost, InternalLink,
)


def make_draft_generator(captured, post=None, raises=None, model="fake-model"):
    class FakeGenerator:
        def __init__(self):
            self.model = model

        def __call__(self, prompt):
            captured.append(prompt)
            if raises is not None:
                raise raises
            return post
    return FakeGenerator()


def _seed_draft_job(tmp_path, with_sitemap=True):
    cfg = JobConfig(
        client_name="Acme Co",
        client_url="https://acme.com",
        business_description="Acme sells CRM software",
    )
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = load_data(job_dir)
    data.topical_map = TopicalMapResult(
        map=TopicalMap(pillars=[PillarTopic(name="CRM", clusters=[TopicCluster(
            name="Basics",
            articles=[ArticleIdea(title="What is a CRM?", target_keyword="what is a crm",
                                  estimated_volume=2000)],
        )])]),
        model="m",
    )
    if with_sitemap:
        data.sitemap = SitemapResult(client=DomainSitemap(
            domain="https://acme.com",
            urls=[UrlEntry(loc="https://acme.com/blog/crm-tips"),
                  UrlEntry(loc="https://acme.com/pricing")],
        ))
    save_data(job_dir, data)
    return job_dir


def test_run_draft_post_persists_and_filters_internal_links(tmp_path):
    job_dir = _seed_draft_job(tmp_path)
    post = DraftPost(
        title="What is a CRM?",
        target_keyword="what is a crm",
        body_markdown="# What is a CRM?\n\n...",
        internal_links=[
            InternalLink(anchor="CRM tips", url="https://acme.com/blog/crm-tips"),
            InternalLink(anchor="made up", url="https://acme.com/not-a-real-page"),
        ],
    )
    captured = []
    fetch = make_fetch({
        "https://acme.com/blog/crm-tips": b"<html><body><p>CRM tips live here.</p></body></html>",
    })
    run_draft_post(job_dir, generator=make_draft_generator(captured, post=post), fetch=fetch)

    data = load_data(job_dir)
    assert data.draft_post.post.title == "What is a CRM?"
    assert data.draft_post.selected_keyword == "what is a crm"
    assert data.draft_post.model == "fake-model"
    # invented URL filtered out; only the real client URL survives
    assert [l.url for l in data.draft_post.post.internal_links] == ["https://acme.com/blog/crm-tips"]
    # prompt grounded in the topic, the fetched style sample, and a candidate URL
    assert "what is a crm" in captured[0].lower()
    assert "CRM tips live here." in captured[0]
    assert "https://acme.com/pricing" in captured[0]


def test_run_draft_post_without_topical_map_records_error(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    captured = []
    run_draft_post(job_dir, generator=make_draft_generator(captured, post=None))
    data = load_data(job_dir)
    assert data.draft_post.post is None
    assert "No topical-map article" in data.draft_post.error
    assert captured == []  # generator never called when there's no topic


def test_run_draft_post_captures_generator_error(tmp_path):
    job_dir = _seed_draft_job(tmp_path, with_sitemap=False)
    run_draft_post(job_dir, generator=make_draft_generator([], raises=RuntimeError("boom")))
    data = load_data(job_dir)
    assert data.draft_post.post is None
    assert "boom" in data.draft_post.error
    assert data.draft_post.selected_keyword == "what is a crm"


def test_run_draft_post_uses_style_sample_override(tmp_path):
    job_dir = _seed_draft_job(tmp_path, with_sitemap=False)
    data = load_data(job_dir)
    data.config.style_sample = "Punchy. Direct. No fluff."
    save_data(job_dir, data)
    captured = []
    post = DraftPost(title="What is a CRM?", body_markdown="# hi")
    run_draft_post(job_dir, generator=make_draft_generator(captured, post=post))
    assert "Punchy. Direct. No fluff." in captured[0]  # override used, no fetch needed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_draft_post.py -k run_draft_post`
Expected: FAIL — `ImportError: cannot import name 'run_draft_post'`.

- [ ] **Step 3: Write the implementation**

Add these imports to the top of `compresearch/draft_post.py`:

```python
from pathlib import Path
from typing import Callable

import anthropic

from compresearch.job_store import load_data, save_data
from compresearch.models import DraftPost, DraftPostResult, JobData
from compresearch.settings import get_secret
from compresearch.sitemap import http_fetch
```

Append:

```python
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

    def __call__(self, prompt: str) -> DraftPost:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
            output_format=DraftPost,
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_draft_post.py`
Expected: PASS (all draft-post tests green).

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python -m pytest`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add compresearch/draft_post.py tests/test_draft_post.py
git commit -m "feat: add Claude draft-post generator and run_draft_post"
```

---

## Task 6: CLI `draft-post` subcommand

**Files:**
- Modify: `compresearch/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
from compresearch.models import (
    TopicalMapResult, TopicalMap, PillarTopic, TopicCluster, ArticleIdea, DraftPost,
)
from compresearch.job_store import save_data


def _draft_fake_generator(post):
    class FakeGenerator:
        model = "fake-model"

        def __call__(self, prompt):
            return post
    return FakeGenerator()


def test_draft_post_subcommand(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = load_data(job_dir)
    data.topical_map = TopicalMapResult(map=TopicalMap(pillars=[PillarTopic(
        name="P", clusters=[TopicCluster(name="C", articles=[
            ArticleIdea(title="What is a CRM?", target_keyword="what is a crm",
                        estimated_volume=100)])])]))
    save_data(job_dir, data)  # no sitemap -> no style fetch, fully offline

    post = DraftPost(title="What is a CRM?", body_markdown="# Hi")
    returned = run_from_args(
        ["draft-post", "--job-dir", str(job_dir)],
        draft_generator=_draft_fake_generator(post),
    )
    assert returned == job_dir
    assert load_data(returned).draft_post.post.title == "What is a CRM?"


def test_draft_post_subcommand_missing_api_key_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    import pytest
    with pytest.raises(SystemExit) as exc:
        run_from_args(["draft-post", "--job-dir", str(job_dir)])  # no generator -> from_settings
    assert exc.value.code == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py -k draft_post`
Expected: FAIL — `run_from_args` has no `draft_generator` parameter (`TypeError`), or argparse rejects the `draft-post` subcommand.

- [ ] **Step 3: Write the implementation**

In `compresearch/cli.py`:

1. Add the import: `from compresearch.draft_post import run_draft_post, DraftGenerator`.
2. Add a `draft_generator` parameter to `run_from_args` (after `generator`):

```python
def run_from_args(
    argv: list[str],
    fetch: Fetcher = http_fetch,
    provider=None,
    generator: Generator | None = None,
    draft_generator: DraftGenerator | None = None,
) -> Path:
```

3. Add the subparser (after the `topical-map` subparser):

```python
    dp = sub.add_parser("draft-post", help="Generate a sample blog post for an existing job")
    dp.add_argument("--job-dir", required=True)
    dp.add_argument("--keyword", default=None,
                    help="Target a specific topic keyword (default: highest-volume topic)")
```

4. Add the dispatch branch (after the `topical-map` branch, before the final `raise`):

```python
    if args.command == "draft-post":
        job_dir = Path(args.job_dir)
        try:
            run_draft_post(
                job_dir, generator=draft_generator, fetch=fetch, preferred_keyword=args.keyword
            )
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        return job_dir
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py`
Expected: PASS (all existing CLI tests plus the two new draft-post tests).

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python -m pytest`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add compresearch/cli.py tests/test_cli.py
git commit -m "feat: add draft-post CLI subcommand"
```

---

## Task 7: Docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the README**

Add a section after the topical-map section and flip the status checklist line. Add:

```markdown
## Run the draft-post module

The draft post runs on a job that already has a topical map (run that first). It picks the
highest-opportunity article, generates a full SEO-optimized post, style-matched to the
client's own existing pages (auto-fetched from the crawled sitemap URLs), with internal-link
suggestions drawn only from the client's real URLs. It calls the Claude API.

Set `ANTHROPIC_API_KEY` in `.env`, then:

```
.venv\Scripts\python -m compresearch.cli draft-post --job-dir jobs\acme-co
```

Target a specific topic with `--keyword "your keyword"` (default: the highest-volume topic).
Provide a manual writing sample via `style_sample` in the job's `job.yaml` to override the
auto-fetched style reference. The result is written to `data.json` under `draft_post`. The
default model is `claude-opus-4-8`.
```

Change the draft-post status line:

```markdown
- [x] Draft post module
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document draft-post module usage"
```

---

## Self-Review Notes

- **Spec coverage:** Auto-pick highest-opportunity topic from the topical map (Task 2); generate a full SEO post (title tag, meta description, outline, body, ~1000-1500 words) via Claude (Tasks 4–5); **style-matching from the client's own auto-fetched pages** with an optional `style_sample` override (Tasks 1, 3, 5) — the brainstorming decision; **internal-link suggestions drawn only from the client's real sitemap URLs**, post-filtered so the LLM can't invent links (Task 5) — the spec's quality upgrade; `claude-opus-4-8` as the configurable showcase model (Task 5). Output persisted to `data.json` under `draft_post` (Tasks 1, 5), ready for the render module. Error isolation, the refusal/None guard, a no-topic guard, a missing-API-key clean CLI exit, and graceful style-fetch degradation mirror the hardened behavior of the prior modules.
- **Placeholder scan:** No TBDs; every code/test step is complete. The SDK-version fallback (from Plan 3) applies and is isolated to the generator.
- **Type/name consistency:** `InternalLink`, `DraftPost`, `DraftPostResult`, `select_topic`, `_select_style_urls`, `_extract_text`, `fetch_style_samples`, `build_draft_post_prompt`, `ClaudeDraftPostGenerator`, `DEFAULT_DRAFT_POST_MODEL`, `DraftGenerator`, `_client_urls`, `run_draft_post` are used consistently across tasks and tests. The draft module names its generator alias `DraftGenerator` (distinct from the topical module's `Generator`) so `cli.py` can import both without collision. `run_from_args` gains a `draft_generator` param used only by the `draft-post` branch.
- **Reuse:** style fetching reuses the sitemap module's `Fetcher`/`http_fetch` (injectable → offline-testable) and `lxml` for HTML→text; no new dependencies.
- **Known follow-ups:** the live `messages.parse` Opus 4.8 call is exercised only against a real account (offline tests inject a fake generator) — confirm against the API when a key is available. The deferred `tests/conftest.py` dedup (now spanning four test files with `make_fetch`/`make_provider`/`make_fake_generator`/`make_draft_generator`) is queued as a background task. With all four analysis modules done, the next plan (Render) consumes `data.sitemap`, `data.keywords`, `data.topical_map`, `data.draft_post` to produce the branded PDF + Google Sheet.
