# compresearch/utils.py
from __future__ import annotations

from urllib.parse import urlparse


def short_domain(url: str) -> str:
    """Netloc without scheme or leading 'www.', for labels and tables."""
    netloc = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    netloc = netloc[4:] if netloc.startswith("www.") else netloc
    return netloc or url
