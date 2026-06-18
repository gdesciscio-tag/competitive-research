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
