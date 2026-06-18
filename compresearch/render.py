# compresearch/render.py
from __future__ import annotations

from urllib.parse import urlparse
from xml.sax.saxutils import escape


def _short_domain(url: str) -> str:
    """Netloc without scheme or leading 'www.', for chart/table labels."""
    netloc = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    netloc = netloc[4:] if netloc.startswith("www.") else netloc
    return netloc or url


def _bar_chart_svg(
    labels: list[str],
    values: list[int],
    width: int = 560,
    height: int = 240,
    bar_color: str = "#E2703A",
    text_color: str = "#1F2933",
) -> str:
    """Render a simple vertical bar chart as a standalone, deterministic SVG string."""
    if not values:
        return ""
    max_val = max(values) or 1
    count = len(values)
    pad = 40
    chart_h = height - 2 * pad
    chart_w = width - 2 * pad
    gap = 16
    bar_w = (chart_w - gap * (count - 1)) / count if count else 0
    parts: list[str] = []
    for index, (label, value) in enumerate(zip(labels, values)):
        bar_h = (value / max_val) * chart_h
        x = pad + index * (bar_w + gap)
        y = pad + (chart_h - bar_h)
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
            f'fill="{bar_color}" rx="3"/>'
        )
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
            f'font-size="12" fill="{text_color}">{value}</text>'
        )
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{height - pad + 16:.1f}" text-anchor="middle" '
            f'font-size="11" fill="{text_color}">{escape(label)}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'width="100%" role="img">{"".join(parts)}</svg>'
    )
