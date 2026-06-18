# tests/conftest.py
"""Shared fixtures and helpers for the test suite.

Consolidates the fake fetcher, fake keyword provider, fake topical-map generator,
and the sitemap byte fixtures that were previously duplicated (and had drifted)
across the individual test modules.
"""
from compresearch.keywords import _domain_key

import pytest


@pytest.fixture
def make_fetch():
    """Factory for a dict-backed fake fetcher; raises FileNotFoundError for unknown URLs."""
    def _make_fetch(pages: dict[str, bytes]):
        def fetch(url: str) -> bytes:
            if url not in pages:
                raise FileNotFoundError(url)
            return pages[url]
        return fetch
    return _make_fetch


@pytest.fixture
def make_provider():
    """Factory for a fake keyword Provider.

    Backed by ``{domain_key: list[KeywordEntry]}``; raises RuntimeError for unknowns.
    """
    def _make_provider(domain_to_entries):
        def provider(domain):
            key = _domain_key(domain)
            if key not in domain_to_entries:
                raise RuntimeError(f"no data for {key}")
            return domain_to_entries[key]
        return provider
    return _make_provider


@pytest.fixture
def make_fake_generator():
    """Factory for a fake topical-map generator.

    Appends each prompt to ``captured`` so call sites can assert on the grounding
    data; optionally returns ``result`` or raises ``raises`` to simulate errors.
    """
    def _make_fake_generator(captured, result=None, raises=None, model="fake-model"):
        class FakeGenerator:
            def __init__(self):
                self.model = model

            def __call__(self, prompt):
                captured.append(prompt)
                if raises is not None:
                    raise raises
                return result
        return FakeGenerator()
    return _make_fake_generator


@pytest.fixture
def urlset() -> bytes:
    """A urlset sitemap with three URLs and mixed lastmod formats."""
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://acme.com/blog/post-1</loc><lastmod>2026-01-10</lastmod></url>
  <url><loc>https://acme.com/blog/post-2</loc><lastmod>2026-02-10T08:00:00+00:00</lastmod></url>
  <url><loc>https://acme.com/about</loc></url>
</urlset>"""


@pytest.fixture
def client_map() -> bytes:
    """A minimal client sitemap with a single blog URL."""
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://acme.com/blog/a</loc></url>
</urlset>"""


@pytest.fixture
def rival_map() -> bytes:
    """A competitor sitemap with a blog URL and a 'case-studies' section the client lacks."""
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://rival.com/blog/a</loc></url>
  <url><loc>https://rival.com/case-studies/x</loc></url>
  <url><loc>https://rival.com/case-studies/y</loc></url>
</urlset>"""
