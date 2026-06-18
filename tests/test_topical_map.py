# tests/test_topical_map.py
from compresearch.topical_map import build_topical_map_prompt


def test_prompt_includes_grounding_data():
    prompt = build_topical_map_prompt(
        client_url="https://acme.com",
        business_description="Acme sells CRM software",
        existing_sections=["blog", "pricing"],
        sitemap_gaps=["case-studies"],
        keyword_gaps=[("free crm", 800), ("crm comparison", None)],
        quick_wins=[("crm software", 8)],
    )
    assert "https://acme.com" in prompt
    assert "Acme sells CRM software" in prompt
    assert "case-studies" in prompt          # sitemap gap surfaced
    assert "free crm" in prompt              # keyword gap surfaced
    assert "crm software" in prompt          # quick win surfaced
    assert "blog" in prompt                  # existing section listed to avoid
    assert "topical map" in prompt.lower()


def test_prompt_handles_missing_business_description():
    prompt = build_topical_map_prompt(
        client_url="https://acme.com",
        business_description=None,
        existing_sections=[],
        sitemap_gaps=[],
        keyword_gaps=[],
        quick_wins=[],
    )
    assert "infer" in prompt.lower()         # tells the model to infer context
