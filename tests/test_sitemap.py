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


import gzip as _gzip
from datetime import date
from compresearch.sitemap import fetch_sitemap_urls

URLSET = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://acme.com/blog/post-1</loc><lastmod>2026-01-10</lastmod></url>
  <url><loc>https://acme.com/blog/post-2</loc><lastmod>2026-02-10T08:00:00+00:00</lastmod></url>
  <url><loc>https://acme.com/about</loc></url>
</urlset>"""

INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://acme.com/sitemap-posts.xml</loc></sitemap>
</sitemapindex>"""


def test_fetch_parses_urlset_with_lastmod():
    fetch = make_fetch({"https://acme.com/sitemap.xml": URLSET})
    entries = fetch_sitemap_urls("https://acme.com/sitemap.xml", fetch)
    locs = [e.loc for e in entries]
    assert locs == [
        "https://acme.com/blog/post-1",
        "https://acme.com/blog/post-2",
        "https://acme.com/about",
    ]
    assert entries[0].lastmod == date(2026, 1, 10)
    assert entries[1].lastmod == date(2026, 2, 10)
    assert entries[2].lastmod is None


def test_fetch_recurses_into_sitemap_index():
    fetch = make_fetch({
        "https://acme.com/sitemap_index.xml": INDEX,
        "https://acme.com/sitemap-posts.xml": URLSET,
    })
    entries = fetch_sitemap_urls("https://acme.com/sitemap_index.xml", fetch)
    assert len(entries) == 3


def test_fetch_handles_gzip():
    fetch = make_fetch({"https://acme.com/sitemap.xml.gz": _gzip.compress(URLSET)})
    entries = fetch_sitemap_urls("https://acme.com/sitemap.xml.gz", fetch)
    assert len(entries) == 3


from compresearch.sitemap import categorize_urls
from compresearch.models import UrlEntry


def test_categorize_counts_first_path_segment():
    urls = [
        UrlEntry(loc="https://acme.com/blog/a"),
        UrlEntry(loc="https://acme.com/blog/b"),
        UrlEntry(loc="https://acme.com/services/x"),
        UrlEntry(loc="https://acme.com/"),
    ]
    counts = categorize_urls(urls)
    assert counts == {"blog": 2, "services": 1, "(root)": 1}


from compresearch.sitemap import infer_cadence


def test_infer_cadence_posts_per_month():
    # 4 posts spanning ~2 months (60 days / 30.44 = 1.97 months) -> 2.0/month
    urls = [
        UrlEntry(loc="a", lastmod=date(2026, 1, 1)),
        UrlEntry(loc="b", lastmod=date(2026, 1, 20)),
        UrlEntry(loc="c", lastmod=date(2026, 2, 15)),
        UrlEntry(loc="d", lastmod=date(2026, 3, 2)),
    ]
    assert infer_cadence(urls) == 2.0


def test_infer_cadence_needs_two_dates():
    assert infer_cadence([UrlEntry(loc="a", lastmod=date(2026, 1, 1))]) is None
    assert infer_cadence([UrlEntry(loc="a")]) is None


from compresearch.sitemap import analyze_domain


def test_analyze_domain_happy_path():
    fetch = make_fetch({
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": URLSET,
    })
    result = analyze_domain("https://acme.com", fetch)
    assert result.error is None
    assert result.total_urls == 3
    assert result.section_counts == {"blog": 2, "about": 1}
    assert result.posts_per_month is not None


def test_analyze_domain_captures_errors():
    fetch = make_fetch({})  # every fetch raises
    result = analyze_domain("https://broken.com", fetch)
    assert result.error is not None
    assert result.total_urls == 0


from compresearch.sitemap import compare_domains

CLIENT_MAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://acme.com/blog/a</loc></url>
</urlset>"""

RIVAL_MAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://rival.com/blog/a</loc></url>
  <url><loc>https://rival.com/case-studies/x</loc></url>
  <url><loc>https://rival.com/case-studies/y</loc></url>
</urlset>"""


def test_compare_domains_finds_gaps():
    fetch = make_fetch({
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": CLIENT_MAP,
        "https://rival.com/robots.txt": b"Sitemap: https://rival.com/sitemap.xml\n",
        "https://rival.com/sitemap.xml": RIVAL_MAP,
    })
    result = compare_domains("https://acme.com", ["https://rival.com"], fetch)

    assert result.client.total_urls == 1
    assert result.competitors[0].total_urls == 3
    # 'case-studies' is a section the competitor has and the client lacks
    assert [g.section for g in result.gaps] == ["case-studies"]
    assert result.gaps[0].client_count == 0
    assert result.gaps[0].competitors_with == ["https://rival.com"]
