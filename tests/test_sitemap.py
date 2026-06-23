# tests/test_sitemap.py
from compresearch.sitemap import discover_sitemaps


def test_discover_reads_sitemaps_from_robots(make_fetch):
    fetch = make_fetch({
        "https://acme.com/robots.txt": b"User-agent: *\nSitemap: https://acme.com/sitemap_index.xml\n",
    })
    assert discover_sitemaps("https://acme.com", fetch) == ["https://acme.com/sitemap_index.xml"]


def test_discover_falls_back_to_default_when_no_robots(make_fetch):
    fetch = make_fetch({})  # robots.txt fetch raises -> fallback
    assert discover_sitemaps("https://acme.com", fetch) == ["https://acme.com/sitemap.xml"]


def test_discover_normalizes_bare_domain(make_fetch):
    fetch = make_fetch({})
    assert discover_sitemaps("acme.com", fetch) == ["https://acme.com/sitemap.xml"]


import gzip as _gzip
from datetime import date
from compresearch.sitemap import fetch_sitemap_urls

INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://acme.com/sitemap-posts.xml</loc></sitemap>
</sitemapindex>"""


def test_fetch_parses_urlset_with_lastmod(make_fetch, urlset):
    fetch = make_fetch({"https://acme.com/sitemap.xml": urlset})
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


def test_fetch_recurses_into_sitemap_index(make_fetch, urlset):
    fetch = make_fetch({
        "https://acme.com/sitemap_index.xml": INDEX,
        "https://acme.com/sitemap-posts.xml": urlset,
    })
    entries = fetch_sitemap_urls("https://acme.com/sitemap_index.xml", fetch)
    assert len(entries) == 3


def test_fetch_handles_gzip(make_fetch, urlset):
    fetch = make_fetch({"https://acme.com/sitemap.xml.gz": _gzip.compress(urlset)})
    entries = fetch_sitemap_urls("https://acme.com/sitemap.xml.gz", fetch)
    assert len(entries) == 3


def test_fetch_tolerates_leading_whitespace(make_fetch, urlset):
    """Some servers emit a stray newline before the XML declaration (e.g. atshire.com)."""
    fetch = make_fetch({"https://acme.com/sitemap.xml": b"\n" + urlset})
    entries = fetch_sitemap_urls("https://acme.com/sitemap.xml", fetch)
    assert len(entries) == 3


def test_fetch_tolerates_utf8_bom(make_fetch, urlset):
    """A UTF-8 BOM before the declaration must not break parsing."""
    fetch = make_fetch({"https://acme.com/sitemap.xml": b"\xef\xbb\xbf" + urlset})
    entries = fetch_sitemap_urls("https://acme.com/sitemap.xml", fetch)
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


def test_categorize_folds_root_level_singletons_into_individual_pages():
    # Sites that put blog posts at the root (e.g. acme.com/my-post) shouldn't make each
    # post its own one-page "section" — those fold into "(individual pages)".
    urls = [
        UrlEntry(loc="https://acme.com/blog/post-1"),   # real section (has children)
        UrlEntry(loc="https://acme.com/blog/post-2"),
        UrlEntry(loc="https://acme.com/the-key-to-being-found"),  # root-level post
        UrlEntry(loc="https://acme.com/another-post"),           # root-level post
        UrlEntry(loc="https://acme.com/about"),                  # standalone page
        UrlEntry(loc="https://acme.com/"),                       # homepage
    ]
    counts = categorize_urls(urls)
    assert counts["blog"] == 2
    assert counts["(individual pages)"] == 3   # the-key..., another-post, about
    assert counts["(root)"] == 1
    assert "the-key-to-being-found" not in counts
    assert "about" not in counts


def test_categorize_keeps_a_singleton_section_that_has_children():
    # A first segment with a child path is a real section even if it appears once.
    counts = categorize_urls([UrlEntry(loc="https://acme.com/services/seo")])
    assert counts == {"services": 1}


def test_categorize_folds_distinct_root_slugs_together():
    # Two different root-level slugs are two individual pages, grouped into one bucket.
    counts = categorize_urls([
        UrlEntry(loc="https://acme.com/case-study-a"),
        UrlEntry(loc="https://acme.com/case-study-b"),
    ])
    assert counts == {"(individual pages)": 2}


def test_is_content_section_filters_cms_noise():
    from compresearch.sitemap import _is_content_section
    for keep in ("case-studies", "services", "service-areas", "blog", "industries"):
        assert _is_content_section(keep) is True, keep
    for drop in ("author", "category", "tag", "type", "colio_item", "colio_group",
                 "portfolio_category", "casestudies-categories", "product_category",
                 "(root)", "(individual pages)"):
        assert _is_content_section(drop) is False, drop


def test_find_gaps_excludes_cms_taxonomy():
    from compresearch.sitemap import _find_gaps
    from compresearch.models import DomainSitemap
    client = DomainSitemap(domain="https://acme.com", section_counts={"blog": 3})
    rival = DomainSitemap(
        domain="https://rival.com",
        section_counts={"case-studies": 2, "category": 9, "tag": 40, "colio_item": 5},
    )
    sections = [g.section for g in _find_gaps(client, [rival])]
    assert "case-studies" in sections
    assert "category" not in sections and "tag" not in sections and "colio_item" not in sections


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


def test_analyze_domain_happy_path(make_fetch, urlset):
    fetch = make_fetch({
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": urlset,
    })
    result = analyze_domain("https://acme.com", fetch)
    assert result.error is None
    assert result.total_urls == 3
    # /about is a root-level standalone page -> folded into "(individual pages)"
    assert result.section_counts == {"blog": 2, "(individual pages)": 1}
    assert result.posts_per_month is not None


def test_analyze_domain_captures_errors(make_fetch):
    fetch = make_fetch({})  # every fetch raises
    result = analyze_domain("https://broken.com", fetch)
    assert result.error is not None
    assert result.total_urls == 0


from compresearch.sitemap import compare_domains


def test_compare_domains_finds_gaps(make_fetch, client_map, rival_map):
    fetch = make_fetch({
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": client_map,
        "https://rival.com/robots.txt": b"Sitemap: https://rival.com/sitemap.xml\n",
        "https://rival.com/sitemap.xml": rival_map,
    })
    result = compare_domains("https://acme.com", ["https://rival.com"], fetch)

    assert result.client.total_urls == 1
    assert result.competitors[0].total_urls == 3
    # 'case-studies' is a section the competitor has and the client lacks
    assert [g.section for g in result.gaps] == ["case-studies"]
    assert result.gaps[0].client_count == 0
    assert result.gaps[0].competitors_with == ["https://rival.com"]


from compresearch.sitemap import run_sitemap
from compresearch.job_store import create_job, load_data
from compresearch.models import JobConfig


def test_run_sitemap_writes_results_to_data_json(tmp_path, make_fetch, client_map, rival_map):
    cfg = JobConfig(
        client_name="Acme Co",
        client_url="https://acme.com",
        competitor_urls=["https://rival.com"],
    )
    job_dir = create_job(cfg, jobs_dir=tmp_path)

    fetch = make_fetch({
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": client_map,
        "https://rival.com/robots.txt": b"Sitemap: https://rival.com/sitemap.xml\n",
        "https://rival.com/sitemap.xml": rival_map,
    })
    run_sitemap(job_dir, fetch=fetch)

    data = load_data(job_dir)
    assert data.sitemap is not None
    assert data.sitemap.client.total_urls == 1
    assert [g.section for g in data.sitemap.gaps] == ["case-studies"]


def test_find_gaps_empty_when_client_failed(make_fetch, rival_map):
    # client fetch fails entirely; only the competitor succeeds
    fetch = make_fetch({
        "https://rival.com/robots.txt": b"Sitemap: https://rival.com/sitemap.xml\n",
        "https://rival.com/sitemap.xml": rival_map,
    })
    result = compare_domains("https://acme.com", ["https://rival.com"], fetch)
    assert result.client.error is not None
    assert result.gaps == []
    assert result.is_partial is True


def test_compare_domains_is_partial_when_competitor_fails(make_fetch, client_map):
    fetch = make_fetch({
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": client_map,
        # rival.com not in dict -> its fetches fail
    })
    result = compare_domains("https://acme.com", ["https://rival.com"], fetch)
    assert result.client.error is None
    assert result.competitors[0].error is not None
    assert result.is_partial is True


def test_clean_run_is_not_partial(make_fetch, client_map, rival_map):
    fetch = make_fetch({
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": client_map,
        "https://rival.com/robots.txt": b"Sitemap: https://rival.com/sitemap.xml\n",
        "https://rival.com/sitemap.xml": rival_map,
    })
    result = compare_domains("https://acme.com", ["https://rival.com"], fetch)
    assert result.is_partial is False
