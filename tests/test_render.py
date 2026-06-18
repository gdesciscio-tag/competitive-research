# tests/test_render.py
import json

from compresearch.branding import load_branding


def test_load_branding_defaults_when_no_override(tmp_path):
    b = load_branding(tmp_path / "missing.json")
    assert b.agency_name == "TAG Online"


def test_load_branding_merges_override(tmp_path):
    path = tmp_path / "branding.json"
    path.write_text(json.dumps({"agency_name": "Acme Agency", "accent_color": "#00FF00"}),
                    encoding="utf-8")
    b = load_branding(path)
    assert b.agency_name == "Acme Agency"        # overridden
    assert b.accent_color == "#00FF00"           # overridden
    assert b.primary_color.startswith("#")       # default preserved


from compresearch.render import _bar_chart_svg, _short_domain


def test_short_domain():
    assert _short_domain("https://www.acme.com/blog") == "acme.com"
    assert _short_domain("rival.com") == "rival.com"


def test_bar_chart_svg_renders_values_and_labels():
    svg = _bar_chart_svg(["acme.com", "rival.com"], [10, 30])
    assert svg.startswith("<svg")
    assert "rival.com" in svg
    assert ">30<" in svg   # value label present
    assert "<rect" in svg  # bars present


def test_bar_chart_svg_empty_returns_empty():
    assert _bar_chart_svg([], []) == ""


def test_bar_chart_svg_escapes_labels():
    svg = _bar_chart_svg(["a&b.com"], [5])
    assert "a&amp;b.com" in svg
    assert "a&b.com" not in svg
