# tests/test_utils.py
from compresearch.utils import short_domain


def test_short_domain_strips_scheme_and_www():
    assert short_domain("https://www.acme.com/blog") == "acme.com"
    assert short_domain("rival.com") == "rival.com"
    assert short_domain("http://sub.acme.co.uk/x") == "sub.acme.co.uk"
