# tests/test_keywords.py
from compresearch.keywords import estimate_traffic_value


def test_traffic_value_uses_position_ctr():
    # position 1 ~ 0.28 CTR
    assert estimate_traffic_value(1000, 1) == 280.0
    # position 8 ~ 0.03 CTR
    assert estimate_traffic_value(1000, 8) == 30.0
    # positions 11-20 ~ 0.01
    assert estimate_traffic_value(1000, 15) == 10.0
    # beyond 20 ~ 0.005
    assert estimate_traffic_value(1000, 50) == 5.0


def test_traffic_value_none_when_inputs_missing():
    assert estimate_traffic_value(None, 5) is None
    assert estimate_traffic_value(1000, None) is None
    assert estimate_traffic_value(1000, 0) is None


from compresearch.keywords import parse_keyword_csv, make_manual_provider, _domain_key

CSV_CONTENT = """keyword,search_volume,difficulty,position,url
crm software,1000,40,8,https://acme.com/crm
free crm,,,,
sales tools,500,25,3,https://acme.com/sales
"""


def test_domain_key_strips_scheme_and_www():
    assert _domain_key("https://www.acme.com/path") == "acme.com"
    assert _domain_key("acme.com") == "acme.com"


def test_parse_keyword_csv(tmp_path):
    csv_path = tmp_path / "acme-com.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    entries = parse_keyword_csv(str(csv_path))
    assert len(entries) == 3
    assert entries[0].keyword == "crm software"
    assert entries[0].search_volume == 1000
    assert entries[0].position == 8
    # blank numeric fields become None
    assert entries[1].keyword == "free crm"
    assert entries[1].search_volume is None
    assert entries[1].url is None


def test_make_manual_provider_maps_by_domain(tmp_path):
    csv_path = tmp_path / "acme-com.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    provider = make_manual_provider({"acme.com": str(csv_path)})
    entries = provider("https://www.acme.com")
    assert len(entries) == 3


def test_make_manual_provider_raises_for_missing_domain():
    provider = make_manual_provider({})
    import pytest
    with pytest.raises(FileNotFoundError):
        provider("https://acme.com")


from compresearch.keywords import parse_ranked_keywords

DATAFORSEO_PAYLOAD = {
    "tasks": [
        {
            "result": [
                {
                    "items": [
                        {
                            "keyword_data": {
                                "keyword": "crm software",
                                "keyword_info": {"search_volume": 1000},
                                "keyword_properties": {"keyword_difficulty": 40},
                            },
                            "ranked_serp_element": {
                                "serp_item": {"rank_absolute": 8, "url": "https://acme.com/crm"}
                            },
                        },
                        {
                            "keyword_data": {
                                "keyword": "free crm",
                                "keyword_info": {"search_volume": 500},
                                "keyword_properties": {"keyword_difficulty": 25},
                            },
                            "ranked_serp_element": {
                                "serp_item": {"rank_absolute": 3, "url": "https://acme.com/free"}
                            },
                        },
                    ]
                }
            ]
        }
    ]
}


def test_parse_ranked_keywords():
    entries = parse_ranked_keywords(DATAFORSEO_PAYLOAD)
    assert len(entries) == 2
    assert entries[0].keyword == "crm software"
    assert entries[0].search_volume == 1000
    assert entries[0].difficulty == 40
    assert entries[0].position == 8
    assert entries[0].url == "https://acme.com/crm"


def test_parse_ranked_keywords_tolerates_missing_fields():
    payload = {"tasks": [{"result": [{"items": [
        {"keyword_data": {"keyword": "bare term"}},
        {"keyword_data": {}},  # no keyword -> skipped
    ]}]}]}
    entries = parse_ranked_keywords(payload)
    assert len(entries) == 1
    assert entries[0].keyword == "bare term"
    assert entries[0].search_volume is None
    assert entries[0].position is None


def test_parse_ranked_keywords_empty_payload():
    assert parse_ranked_keywords({}) == []


from compresearch.keywords import DataForSEOProvider


def test_dataforseo_provider_uses_injected_raw_fetch():
    calls = []

    def fake_raw_fetch(domain_key: str) -> dict:
        calls.append(domain_key)
        return DATAFORSEO_PAYLOAD

    provider = DataForSEOProvider(login="x", password="y", raw_fetch=fake_raw_fetch)
    entries = provider("https://www.acme.com")
    assert calls == ["acme.com"]            # scheme/www stripped before the API call
    assert len(entries) == 2
    assert entries[0].keyword == "crm software"


from compresearch.keywords import analyze_keywords
from compresearch.models import KeywordEntry


def make_provider(domain_to_entries):
    """Fake Provider: dict of domain_key -> list[KeywordEntry]; raises for unknowns."""
    def provider(domain):
        key = _domain_key(domain)
        if key not in domain_to_entries:
            raise RuntimeError(f"no data for {key}")
        return domain_to_entries[key]
    return provider


def test_analyze_keywords_gaps_and_quick_wins():
    provider = make_provider({
        "acme.com": [
            KeywordEntry(keyword="crm software", search_volume=1000, position=8, url="https://acme.com/crm"),
            KeywordEntry(keyword="sales tools", search_volume=500, position=3),
        ],
        "rival.com": [
            KeywordEntry(keyword="crm software", search_volume=1000, position=2),
            KeywordEntry(keyword="free crm", search_volume=800, position=4),
        ],
    })
    result = analyze_keywords("https://acme.com", ["https://rival.com"], provider)

    # gap = keyword a competitor ranks for that the client does not
    assert [g.keyword for g in result.gaps] == ["free crm"]
    assert result.gaps[0].competitors_ranking == ["https://rival.com"]
    assert result.gaps[0].best_competitor_position == 4
    assert result.gaps[0].traffic_value is not None

    # quick win = client ranks position 5-20 ("crm software" at 8; "sales tools" at 3 excluded)
    assert [w.keyword for w in result.quick_wins] == ["crm software"]
    assert result.quick_wins[0].position == 8
    assert result.is_partial is False


def test_analyze_keywords_marks_partial_and_skips_gaps_on_client_failure():
    provider = make_provider({
        "rival.com": [KeywordEntry(keyword="free crm", search_volume=800, position=4)],
    })  # acme.com missing -> client lookup fails
    result = analyze_keywords("https://acme.com", ["https://rival.com"], provider)
    assert result.client.error is not None
    assert result.gaps == []
    assert result.quick_wins == []
    assert result.is_partial is True


from compresearch.keywords import run_keywords
from compresearch.job_store import create_job, load_data
from compresearch.models import JobConfig


def test_run_keywords_with_injected_provider(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    competitor_urls=["https://rival.com"])
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    provider = make_provider({
        "acme.com": [KeywordEntry(keyword="crm software", search_volume=1000, position=8)],
        "rival.com": [KeywordEntry(keyword="free crm", search_volume=800, position=4)],
    })
    run_keywords(job_dir, provider=provider)

    data = load_data(job_dir)
    assert data.keywords is not None
    assert [g.keyword for g in data.keywords.gaps] == ["free crm"]
    assert [w.keyword for w in data.keywords.quick_wins] == ["crm software"]


def test_run_keywords_manual_source_reads_input_dir(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    competitor_urls=["https://rival.com"], keyword_source="manual")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    input_dir = job_dir / "keywords_input"
    input_dir.mkdir()
    (input_dir / "acme-com.csv").write_text(
        "keyword,search_volume,difficulty,position,url\ncrm software,1000,40,8,\n",
        encoding="utf-8",
    )
    (input_dir / "rival-com.csv").write_text(
        "keyword,search_volume,difficulty,position,url\nfree crm,800,30,4,\n",
        encoding="utf-8",
    )
    run_keywords(job_dir)  # no provider -> manual provider built from input dir

    data = load_data(job_dir)
    assert [g.keyword for g in data.keywords.gaps] == ["free crm"]


def test_analyze_keywords_multi_competitor_gap_aggregation():
    provider = make_provider({
        "acme.com": [],
        "rival1.com": [KeywordEntry(keyword="free crm", search_volume=800, position=5)],
        "rival2.com": [KeywordEntry(keyword="free crm", search_volume=900, position=2)],
    })
    result = analyze_keywords(
        "https://acme.com", ["https://rival1.com", "https://rival2.com"], provider
    )
    assert len(result.gaps) == 1
    gap = result.gaps[0]
    assert set(gap.competitors_ranking) == {"https://rival1.com", "https://rival2.com"}
    assert gap.best_competitor_position == 2  # minimum across competitors
    assert result.is_partial is False


def test_domain_key_rejects_url_without_host():
    import pytest
    with pytest.raises(ValueError):
        _domain_key("https://")


def test_domain_to_filename():
    from compresearch.keywords import _domain_to_filename
    assert _domain_to_filename("acme.com") == "acme-com"
    assert _domain_to_filename("sub.acme.co.uk") == "sub-acme-co-uk"


def test_quick_wins_sorted_by_traffic_value():
    provider = make_provider({
        "acme.com": [
            KeywordEntry(keyword="low value", search_volume=2000, position=19),  # ~20
            KeywordEntry(keyword="high value", search_volume=500, position=5),   # ~30
        ],
    })
    result = analyze_keywords("https://acme.com", [], provider)
    assert [w.keyword for w in result.quick_wins] == ["high value", "low value"]


def test_gap_search_volume_uses_max_across_competitors():
    provider = make_provider({
        "acme.com": [],
        "rival1.com": [KeywordEntry(keyword="free crm", search_volume=100, position=6)],
        "rival2.com": [KeywordEntry(keyword="free crm", search_volume=5000, position=8)],
    })
    result = analyze_keywords(
        "https://acme.com", ["https://rival1.com", "https://rival2.com"], provider
    )
    assert len(result.gaps) == 1
    assert result.gaps[0].search_volume == 5000


def test_analyze_keywords_partial_competitor_failure_still_yields_gaps():
    provider = make_provider({
        "acme.com": [KeywordEntry(keyword="crm", search_volume=1000, position=2)],
        "rival1.com": [KeywordEntry(keyword="free crm", search_volume=800, position=4)],
        # rival2.com missing -> provider raises -> captured as error
    })
    result = analyze_keywords(
        "https://acme.com", ["https://rival1.com", "https://rival2.com"], provider
    )
    assert result.is_partial is True
    assert result.gaps != []  # gaps from the successful competitor still computed
    assert any(c.error for c in result.competitors)
