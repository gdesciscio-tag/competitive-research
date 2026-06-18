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
