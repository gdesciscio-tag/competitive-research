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
