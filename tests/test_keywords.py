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


def test_dataforseo_provider_default_limit_is_200():
    # Keep the per-domain keyword cap modest to bound DataForSEO cost.
    assert DataForSEOProvider(login="x", password="y")._limit == 200


from compresearch.keywords import analyze_keywords
from compresearch.models import KeywordEntry


def test_analyze_keywords_gaps_and_quick_wins(make_provider):
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


def test_analyze_keywords_marks_partial_and_skips_gaps_on_client_failure(make_provider):
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


def test_run_keywords_with_injected_provider(tmp_path, make_provider):
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


def test_analyze_keywords_multi_competitor_gap_aggregation(make_provider):
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


def test_quick_wins_sorted_by_traffic_value(make_provider):
    provider = make_provider({
        "acme.com": [
            KeywordEntry(keyword="low value", search_volume=2000, position=19),  # ~20
            KeywordEntry(keyword="high value", search_volume=500, position=5),   # ~30
        ],
    })
    result = analyze_keywords("https://acme.com", [], provider)
    assert [w.keyword for w in result.quick_wins] == ["high value", "low value"]


def test_gap_search_volume_uses_max_across_competitors(make_provider):
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


def test_analyze_keywords_partial_competitor_failure_still_yields_gaps(make_provider):
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


from compresearch.keywords import analyze_provided_keywords
from compresearch.models import KeywordEntry, DomainKeywords


def _dk(domain, entries):
    return DomainKeywords(domain=domain, keywords=entries, total_keywords=len(entries))


def test_analyze_provided_keywords_cross_references_and_enriches():
    client = _dk("atshire.com", [
        KeywordEntry(keyword="photonics recruiter", search_volume=50, position=7),
    ])
    competitors = [
        _dk("bluesignal.com", [
            KeywordEntry(keyword="rf engineering recruiter", search_volume=300, position=4),
        ]),
        _dk("broadstaffglobal.com", [
            KeywordEntry(keyword="rf engineering recruiter", search_volume=300, position=9),
        ]),
    ]

    def enricher(terms):
        # Authoritative volume/difficulty for every term, even ones nobody ranks for
        return [
            KeywordEntry(keyword="rf engineering recruiter", search_volume=320, difficulty=18),
            KeywordEntry(keyword="photonics recruiter", search_volume=90, difficulty=12),
            KeywordEntry(keyword="semiconductor recruiter", search_volume=140, difficulty=22),
        ]

    result = analyze_provided_keywords(
        ["RF Engineering Recruiter", "Photonics Recruiter", "Semiconductor Recruiter"],
        client, competitors, enricher,
    )
    by_kw = {p.keyword: p for p in result}

    rf = by_kw["RF Engineering Recruiter"]
    assert rf.search_volume == 320 and rf.difficulty == 18      # from enrichment
    assert rf.client_position is None                            # client doesn't rank
    assert sorted(rf.competitors_ranking) == ["bluesignal.com", "broadstaffglobal.com"]
    assert rf.best_competitor_position == 4                      # best (lowest) of 4 and 9

    ph = by_kw["Photonics Recruiter"]
    assert ph.client_position == 7                               # client ranks
    assert ph.competitors_ranking == []

    semi = by_kw["Semiconductor Recruiter"]
    assert semi.search_volume == 140                             # enrichment only
    assert semi.client_position is None and semi.competitors_ranking == []


def test_analyze_provided_keywords_without_enricher_falls_back_to_ranked_volume():
    client = _dk("atshire.com", [])
    competitors = [_dk("bluesignal.com", [
        KeywordEntry(keyword="rf engineering recruiter", search_volume=300, position=4),
    ])]
    # enricher=None (manual mode / no creds): volume falls back to matched ranked data
    result = analyze_provided_keywords(["RF Engineering Recruiter"], client, competitors, None)
    assert result[0].search_volume == 300
    assert result[0].best_competitor_position == 4


def test_analyze_provided_keywords_survives_enricher_error():
    client = _dk("atshire.com", [])
    def boom(terms):
        raise RuntimeError("dataforseo down")
    result = analyze_provided_keywords(["RF Engineering Recruiter"], client, [], boom)
    assert len(result) == 1
    assert result[0].search_volume is None       # enrichment failed, no ranked match


from compresearch.keywords import read_provided_keywords


def test_read_provided_keywords_skips_blanks_comments_and_dedupes(tmp_path):
    input_dir = tmp_path / "keywords_input"
    input_dir.mkdir()
    (input_dir / "client_provided.txt").write_text(
        "# client wishlist\n"
        "RF Engineering Recruiter\n"
        "\n"
        "Photonics Recruiter\n"
        "rf engineering recruiter\n",  # duplicate (case-insensitive) — dropped
        encoding="utf-8",
    )
    assert read_provided_keywords(tmp_path) == [
        "RF Engineering Recruiter",
        "Photonics Recruiter",
    ]


def test_read_provided_keywords_missing_file_returns_empty(tmp_path):
    assert read_provided_keywords(tmp_path) == []


from compresearch.keywords import parse_keyword_overview


def test_parse_keyword_overview_reads_volume_and_difficulty():
    payload = {
        "tasks": [{
            "result": [{
                "items": [
                    {
                        "keyword": "rf engineering recruiter",
                        "keyword_info": {"search_volume": 320},
                        "keyword_properties": {"keyword_difficulty": 18},
                    },
                    {
                        "keyword": "photonics recruiter",
                        "keyword_info": {"search_volume": 90},
                        "keyword_properties": {"keyword_difficulty": 12},
                    },
                    {"keyword": None},  # skipped — no keyword
                ]
            }]
        }]
    }
    entries = parse_keyword_overview(payload)
    assert [e.keyword for e in entries] == ["rf engineering recruiter", "photonics recruiter"]
    assert entries[0].search_volume == 320
    assert entries[0].difficulty == 18
    assert entries[1].search_volume == 90
