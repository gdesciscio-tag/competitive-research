from compresearch.models import Branding, DraftPost, InternalLink


def _post():
    return DraftPost(
        title="What Is a VSL?",
        target_keyword="video sales letter",
        title_tag="What Is a VSL? A Quick Guide",
        meta_description="A VSL turns visitors into customers.",
        body_markdown="## Intro\n\nA VSL is a **video sales letter**.",
        internal_links=[InternalLink(anchor="our services", url="https://acme.com/services")],
    )


def test_build_draft_html_includes_title_metadata_body_and_links():
    from compresearch.draft_export import build_draft_html

    html = build_draft_html(_post(), Branding())
    assert "<h1>What Is a VSL?</h1>" in html
    assert "video sales letter" in html          # target keyword in metadata header
    assert "What Is a VSL? A Quick Guide" in html  # title tag
    assert "A VSL turns visitors into customers." in html  # meta description
    assert "<strong>video sales letter</strong>" in html   # body rendered via markdown_to_html
    assert "https://acme.com/services" in html   # internal link url
    assert "our services" in html                # internal link anchor


def test_build_draft_html_escapes_metadata():
    from compresearch.draft_export import build_draft_html

    post = _post()
    post.title = "A < B & C"
    html = build_draft_html(post, Branding())
    assert "A &lt; B &amp; C" in html            # title escaped in the <h1>
