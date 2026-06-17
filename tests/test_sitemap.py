# tests/test_sitemap.py
from compresearch.sitemap import discover_sitemaps


def make_fetch(pages: dict[str, bytes]):
    """Build a fake fetcher backed by a dict; raises for unknown URLs."""
    def fetch(url: str) -> bytes:
        if url not in pages:
            raise FileNotFoundError(url)
        return pages[url]
    return fetch


def test_discover_reads_sitemaps_from_robots():
    fetch = make_fetch({
        "https://acme.com/robots.txt": b"User-agent: *\nSitemap: https://acme.com/sitemap_index.xml\n",
    })
    assert discover_sitemaps("https://acme.com", fetch) == ["https://acme.com/sitemap_index.xml"]


def test_discover_falls_back_to_default_when_no_robots():
    fetch = make_fetch({})  # robots.txt fetch raises -> fallback
    assert discover_sitemaps("https://acme.com", fetch) == ["https://acme.com/sitemap.xml"]


def test_discover_normalizes_bare_domain():
    fetch = make_fetch({})
    assert discover_sitemaps("acme.com", fetch) == ["https://acme.com/sitemap.xml"]
