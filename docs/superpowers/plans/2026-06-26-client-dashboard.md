# Client-Facing Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single self-contained, branded HTML dashboard as an additional per-job output that lets the client explore the same `data.json` interactively.

**Architecture:** A new `compresearch/dashboard.py` module follows the exact shape of `render.py`: a pure `build_dashboard_context` view-model read straight from `data.json` (the full dataset, not the PDF's curated subset), a Jinja2 `render_dashboard_html` over a new self-contained template, and a resilient `run_dashboard` that writes `outputs/<slug>-dashboard.html`. It plugs into the orchestrator as a cheap always-on output step and gets a CLI subcommand + `refresh-outputs` inclusion.

**Tech Stack:** Python 3.14, pydantic v2, Jinja2 (already used by `render.py`), pytest. No new dependencies. The dashboard HTML uses inline CSS + vanilla JS (no CDN/framework).

**Spec:** `docs/superpowers/specs/2026-06-26-client-dashboard-design.md`

---

## File structure

- Create: `compresearch/dashboard.py` — view-model, HTML renderer, `run_dashboard`.
- Create: `compresearch/templates/dashboard.html.j2` — the self-contained dashboard template.
- Create: `tests/test_dashboard.py` — unit tests for the module.
- Modify: `compresearch/models.py` — add `DashboardResult` + `JobData.dashboard`.
- Modify: `compresearch/orchestrator.py` — add the `dashboard` step.
- Modify: `compresearch/cli.py` — `dashboard` subcommand, `refresh-outputs` inclusion, summary lines.
- Modify: `tests/test_orchestrator.py`, `tests/test_cli.py` — update step-list expectations.
- Modify: `README.md`, `.claude/skills/competitive-research/SKILL.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`.

Reused as-is from `render.py`: `markdown_to_html`, `_logo_html`, `_bar_chart_svg`, `TEMPLATES_DIR`. From `utils.py`: `short_domain`. From `job_store.py`: `load_data`, `save_data`, `slugify`. From `branding.py`: `load_branding`.

---

### Task 1: Data model — `DashboardResult` and `JobData.dashboard`

**Files:**
- Modify: `compresearch/models.py`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_dashboard.py` with:

```python
from compresearch.models import DashboardResult, JobData, JobConfig


def test_dashboard_result_defaults():
    r = DashboardResult()
    assert r.html_path is None
    assert r.error is None


def test_jobdata_has_dashboard_field_defaulting_none():
    data = JobData(config=JobConfig(client_name="Acme Co", client_url="https://acme.com"))
    assert data.dashboard is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_dashboard.py -q`
Expected: FAIL with `ImportError: cannot import name 'DashboardResult'`.

- [ ] **Step 3: Add the model and field**

In `compresearch/models.py`, add this class next to `DraftExportResult`:

```python
class DashboardResult(BaseModel):
    html_path: str | None = None   # local outputs/<slug>-dashboard.html
    error: str | None = None
```

In the `JobData` model, add the field after `sheet`:

```python
    sheet: SheetResult | None = None
    dashboard: DashboardResult | None = None
    run_report: RunReport | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_dashboard.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/models.py tests/test_dashboard.py
git commit -m "feat: add DashboardResult model and JobData.dashboard"
```

---

### Task 2: `build_dashboard_context` (pure view-model)

**Files:**
- Create: `compresearch/dashboard.py`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dashboard.py`:

```python
from compresearch.models import (
    Branding, SitemapResult, DomainSitemap, SitemapGap,
    KeywordResult, DomainKeywords, KeywordEntry, KeywordGap, QuickWin, ProvidedKeyword,
    TopicalMapResult, TopicalMap, PillarTopic, TopicCluster, ArticleIdea,
    DraftPostResult, DraftPost, InternalLink,
)


def _full_jobdata():
    return JobData(
        config=JobConfig(client_name="Acme Co", client_url="https://acme.com",
                         competitor_urls=["https://rival.com"]),
        sitemap=SitemapResult(
            client=DomainSitemap(domain="https://acme.com", total_urls=30),
            competitors=[DomainSitemap(domain="https://rival.com", total_urls=120)],
            gaps=[SitemapGap(section="case-studies", competitors_with=["https://rival.com"])],
        ),
        keywords=KeywordResult(
            client=DomainKeywords(domain="https://acme.com",
                                  keywords=[KeywordEntry(keyword="crm", search_volume=1000, position=8)],
                                  total_keywords=1),
            competitors=[DomainKeywords(domain="https://rival.com",
                                        keywords=[KeywordEntry(keyword="free crm", search_volume=800, position=4)],
                                        total_keywords=1)],
            gaps=[KeywordGap(keyword="free crm", search_volume=800, difficulty=30.0,
                             best_competitor_position=4, traffic_value=80.0,
                             competitors_ranking=["https://rival.com"])],
            quick_wins=[QuickWin(keyword="crm software", position=8, search_volume=1000,
                                 traffic_value=30.0, url="https://acme.com/crm")],
            provided=[ProvidedKeyword(keyword="best crm", search_volume=500, difficulty=20.0,
                                      client_position=12, best_competitor_position=3,
                                      competitors_ranking=["https://rival.com"])],
        ),
        topical_map=TopicalMapResult(map=TopicalMap(summary="A map.", pillars=[PillarTopic(
            name="CRM Basics", clusters=[TopicCluster(name="Intro", articles=[
                ArticleIdea(title="What is a CRM?", target_keyword="what is a crm")])])])),
        draft_posts=[DraftPostResult(post=DraftPost(
            title="What is a CRM?", target_keyword="what is a crm", word_count=1200,
            meta_description="A guide.", body_markdown="# What is a CRM?\n\nA CRM **helps** teams.",
            internal_links=[InternalLink(anchor="pricing", url="https://acme.com/pricing")]))],
    )


def test_build_dashboard_context_shape_and_completeness():
    from compresearch.dashboard import build_dashboard_context
    ctx = build_dashboard_context(_full_jobdata(), Branding(), report_date="June 2026")
    assert ctx["client_name"] == "Acme Co"
    assert ctx["report_date"] == "June 2026"
    assert ctx["summary"] == {"competitor_count": 1, "content_gap_count": 1,
                              "keyword_gap_count": 1, "quick_win_count": 1, "is_partial": False}
    assert ctx["keyword_gaps"][0]["keyword"] == "free crm"
    assert ctx["quick_wins"][0]["url"] == "https://acme.com/crm"
    # per-domain keyword tables: client + 1 competitor
    assert [d["domain"] for d in ctx["domain_keywords"]] == ["acme.com", "rival.com"]
    assert ctx["provided"][0]["keyword"] == "best crm"
    assert ctx["topical_map"]["pillars"][0].name == "CRM Basics"
    # draft body markdown rendered to HTML
    assert "<strong>helps</strong>" in ctx["drafts"][0]["body_html"]
    assert ctx["content_volume_svg"].startswith("<svg")


def test_build_dashboard_context_tolerates_missing_sections():
    from compresearch.dashboard import build_dashboard_context
    data = JobData(config=JobConfig(client_name="X", client_url="https://x.com"))
    ctx = build_dashboard_context(data, Branding())
    assert ctx["keyword_gaps"] == []
    assert ctx["drafts"] == []
    assert ctx["domain_keywords"] == []
    assert ctx["topical_map"]["pillars"] == []
    assert ctx["content_volume_svg"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_dashboard.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'compresearch.dashboard'`.

- [ ] **Step 3: Create `compresearch/dashboard.py` with the view-model**

```python
# compresearch/dashboard.py
from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from compresearch.branding import load_branding
from compresearch.job_store import load_data, save_data, slugify
from compresearch.models import Branding, DashboardResult, JobData
from compresearch.render import TEMPLATES_DIR, _bar_chart_svg, _logo_html, markdown_to_html
from compresearch.utils import short_domain


def build_dashboard_context(data: JobData, branding: Branding, report_date: str | None = None) -> dict:
    """Turn a finished JobData + branding into the dashboard view-model. Pure; tolerates any
    missing analysis section. Mirrors render.build_report_context but keeps the FULL dataset
    (uncapped lists, per-domain keyword tables, every draft) and typed values for client-side
    sorting."""
    config = data.config

    sitemap_domains: list[dict] = []
    sitemap_gaps: list[dict] = []
    if data.sitemap is not None:
        if data.sitemap.client is not None:
            sitemap_domains.append({"domain": short_domain(data.sitemap.client.domain),
                                    "total": data.sitemap.client.total_urls,
                                    "posts_per_month": data.sitemap.client.posts_per_month})
        for comp in data.sitemap.competitors:
            sitemap_domains.append({"domain": short_domain(comp.domain),
                                    "total": comp.total_urls,
                                    "posts_per_month": comp.posts_per_month})
        sitemap_gaps = [{"section": g.section,
                         "competitors": [short_domain(d) for d in g.competitors_with]}
                        for g in data.sitemap.gaps]

    keyword_gaps: list[dict] = []
    quick_wins: list[dict] = []
    domain_keywords: list[dict] = []
    provided: list[dict] = []
    if data.keywords is not None:
        keyword_gaps = [{"keyword": g.keyword, "volume": g.search_volume, "difficulty": g.difficulty,
                         "traffic_value": g.traffic_value, "best_position": g.best_competitor_position,
                         "competitors": [short_domain(d) for d in g.competitors_ranking]}
                        for g in data.keywords.gaps]
        quick_wins = [{"keyword": w.keyword, "position": w.position, "volume": w.search_volume,
                       "traffic_value": w.traffic_value, "url": w.url}
                      for w in data.keywords.quick_wins]
        domains = ([data.keywords.client] if data.keywords.client else []) + list(data.keywords.competitors)
        for dk in domains:
            domain_keywords.append({"domain": short_domain(dk.domain),
                                    "keywords": [{"keyword": e.keyword, "volume": e.search_volume,
                                                  "difficulty": e.difficulty, "position": e.position,
                                                  "url": e.url} for e in dk.keywords]})
        provided = [{"keyword": p.keyword, "volume": p.search_volume, "difficulty": p.difficulty,
                     "client_position": p.client_position, "best_position": p.best_competitor_position,
                     "competitors": [short_domain(d) for d in p.competitors_ranking]}
                    for p in data.keywords.provided]

    pillars = []
    topical_summary = None
    if data.topical_map is not None and data.topical_map.map is not None:
        pillars = data.topical_map.map.pillars
        topical_summary = data.topical_map.map.summary

    # body_html is trusted LLM output rendered with |safe in the template (same boundary as
    # the PDF). The dashboard is a static file handed to the client, not served to untrusted
    # visitors; if that ever changes, sanitize before rendering.
    drafts = [{"title": d.post.title, "target_keyword": d.post.target_keyword,
               "title_tag": d.post.title_tag, "meta_description": d.post.meta_description,
               "word_count": d.post.word_count, "body_html": markdown_to_html(d.post.body_markdown),
               "internal_links": [{"anchor": l.anchor, "url": l.url} for l in d.post.internal_links]}
              for d in data.draft_posts if d.post is not None]

    content_volume_svg = _bar_chart_svg(
        [d["domain"] for d in sitemap_domains], [d["total"] for d in sitemap_domains],
        bar_color=branding.accent_color, text_color=branding.text_color,
    )
    keyword_counts = [{"domain": dk["domain"], "total": len(dk["keywords"])} for dk in domain_keywords]
    keyword_counts_svg = _bar_chart_svg(
        [d["domain"] for d in keyword_counts], [d["total"] for d in keyword_counts],
        bar_color=branding.primary_color, text_color=branding.text_color,
    )

    is_partial = bool(
        (data.sitemap and data.sitemap.is_partial) or (data.keywords and data.keywords.is_partial)
    )

    return {
        "branding": branding,
        "logo_html": _logo_html(branding),
        "client_name": config.client_name,
        "client_url": config.client_url,
        "report_date": report_date or "",
        "summary": {
            "competitor_count": len(config.competitor_urls),
            "content_gap_count": len(sitemap_gaps),
            "keyword_gap_count": len(keyword_gaps),
            "quick_win_count": len(quick_wins),
            "is_partial": is_partial,
        },
        "content_volume_svg": content_volume_svg,
        "keyword_counts_svg": keyword_counts_svg,
        "sitemap": {"domains": sitemap_domains, "gaps": sitemap_gaps},
        "keyword_gaps": keyword_gaps,
        "quick_wins": quick_wins,
        "domain_keywords": domain_keywords,
        "provided": provided,
        "topical_map": {"summary": topical_summary, "pillars": pillars},
        "drafts": drafts,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_dashboard.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/dashboard.py tests/test_dashboard.py
git commit -m "feat: add build_dashboard_context view-model"
```

---

### Task 3: Template + `render_dashboard_html`

**Files:**
- Create: `compresearch/templates/dashboard.html.j2`
- Modify: `compresearch/dashboard.py`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dashboard.py`:

```python
def test_render_dashboard_html_contains_sections_and_is_self_contained():
    from compresearch.dashboard import build_dashboard_context, render_dashboard_html
    html = render_dashboard_html(build_dashboard_context(_full_jobdata(), Branding()))
    # key content present
    assert "Acme Co" in html
    assert "free crm" in html                      # keyword gap
    assert "What is a CRM?" in html                # topical map + draft
    assert "<strong>helps</strong>" in html        # rendered draft body
    assert "<svg" in html                          # inline chart
    # tabs rendered
    assert 'data-tab="keywords"' in html
    assert 'data-tab="domains"' in html
    # self-contained: no external CSS/JS/asset references
    assert "<link" not in html
    assert "src=\"http" not in html
    assert "src='http" not in html
    assert "cdn" not in html.lower()


def test_render_dashboard_html_handles_empty_job():
    from compresearch.dashboard import build_dashboard_context, render_dashboard_html
    data = JobData(config=JobConfig(client_name="X", client_url="https://x.com"))
    html = render_dashboard_html(build_dashboard_context(data, Branding()))
    assert "X" in html                              # renders without error
    assert 'data-tab="keywords"' not in html        # absent sections produce no tab
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_dashboard.py -q`
Expected: FAIL with `AttributeError`/`ImportError` for `render_dashboard_html`.

- [ ] **Step 3: Create the template**

Create `compresearch/templates/dashboard.html.j2`:

```jinja
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ client_name }} — competitive research</title>
<style>
body{font-family:{{ branding.font_family }};color:{{ branding.text_color }};margin:0;background:#f5f7fa;}
.wrap{max-width:1000px;margin:0 auto;padding:24px;}
.header{background:{{ branding.primary_color }};color:#fff;border-radius:10px 10px 0 0;padding:20px 24px;display:flex;align-items:center;gap:16px;}
.header h1{font-size:20px;margin:0;font-weight:600;}
.header .sub{color:#c2cdda;font-size:13px;margin-top:2px;}
.panelwrap{background:#fff;border:1px solid #e4e7eb;border-top:none;border-radius:0 0 10px 10px;padding:20px 24px;}
.cards{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:16px;}
.card{flex:1;min-width:120px;background:#f5f7fa;border-radius:8px;padding:12px;}
.card .label{font-size:12px;color:{{ branding.muted_color }};}
.card .value{font-size:26px;font-weight:600;}
.tabs{display:flex;flex-wrap:wrap;gap:4px;border-bottom:2px solid #e4e7eb;margin-bottom:16px;}
.tab{font-size:13px;padding:8px 14px;border:none;background:none;cursor:pointer;color:{{ branding.muted_color }};border-bottom:2px solid transparent;margin-bottom:-2px;}
.tab.active{color:{{ branding.primary_color }};border-bottom-color:{{ branding.accent_color }};font-weight:600;}
.panel{display:none;}
.panel.active{display:block;}
table{width:100%;border-collapse:collapse;font-size:13px;}
th,td{padding:8px 10px;border-bottom:1px solid #eef1f4;text-align:left;}
th{color:{{ branding.muted_color }};cursor:pointer;white-space:nowrap;}
td.num,th.num{text-align:right;}
input.filter{width:100%;padding:8px 10px;margin-bottom:10px;border:1px solid #d8dee5;border-radius:6px;font-size:13px;}
.muted{color:{{ branding.muted_color }};font-size:12px;}
h2{font-size:16px;color:{{ branding.primary_color }};}
.draft{border:1px solid #e4e7eb;border-radius:8px;padding:16px;margin-bottom:14px;}
a{color:{{ branding.accent_color }};}
.chart{margin:8px 0 16px;}
ul.links{padding-left:18px;}
</style></head><body>
<div class="wrap">
  <div class="header">
    <div>{{ logo_html|safe if logo_html else branding.agency_name }}</div>
    <div style="flex:1">
      <h1>{{ client_name }} — competitive research</h1>
      <div class="sub">Prepared by {{ branding.agency_name }}{% if report_date %} · {{ report_date }}{% endif %} · vs {{ summary.competitor_count }} competitors</div>
    </div>
  </div>
  <div class="panelwrap">
    {% if summary.is_partial %}<div class="muted" style="margin-bottom:12px;">Note: some data could not be fully retrieved; this dashboard reflects what was available.</div>{% endif %}
    <div class="cards">
      <div class="card"><div class="label">Competitors</div><div class="value">{{ summary.competitor_count }}</div></div>
      <div class="card"><div class="label">Content gaps</div><div class="value">{{ summary.content_gap_count }}</div></div>
      <div class="card"><div class="label">Keyword gaps</div><div class="value">{{ summary.keyword_gap_count }}</div></div>
      <div class="card"><div class="label">Quick wins</div><div class="value">{{ summary.quick_win_count }}</div></div>
    </div>
    <div class="tabs" role="tablist">
      <button class="tab active" data-tab="overview">Overview</button>
      {% if sitemap.gaps %}<button class="tab" data-tab="content">Content gaps</button>{% endif %}
      {% if keyword_gaps %}<button class="tab" data-tab="keywords">Keyword gaps</button>{% endif %}
      {% if quick_wins %}<button class="tab" data-tab="wins">Quick wins</button>{% endif %}
      {% if domain_keywords %}<button class="tab" data-tab="domains">Keywords by domain</button>{% endif %}
      {% if topical_map.pillars %}<button class="tab" data-tab="map">Topical map</button>{% endif %}
      {% if drafts %}<button class="tab" data-tab="drafts">Draft posts</button>{% endif %}
      {% if provided %}<button class="tab" data-tab="provided">Client keywords</button>{% endif %}
    </div>

    <div class="panel active" data-panel="overview">
      {% if content_volume_svg %}<h2>Published pages by domain</h2><div class="chart">{{ content_volume_svg|safe }}</div>{% endif %}
      {% if keyword_counts_svg %}<h2>Ranking keywords by domain</h2><div class="chart">{{ keyword_counts_svg|safe }}</div>{% endif %}
      {% if not content_volume_svg and not keyword_counts_svg %}<p class="muted">No analysis data available yet.</p>{% endif %}
    </div>

    {% if sitemap.gaps %}
    <div class="panel" data-panel="content">
      <p class="muted">Content sections competitors publish that {{ client_name }} has none of.</p>
      <table data-sortable><thead><tr><th>Section</th><th>Competitors</th></tr></thead><tbody>
      {% for g in sitemap.gaps %}<tr><td>{{ g.section }}</td><td>{{ g.competitors|join(', ') }}</td></tr>{% endfor %}
      </tbody></table>
    </div>
    {% endif %}

    {% if keyword_gaps %}
    <div class="panel" data-panel="keywords">
      <input class="filter" type="text" placeholder="Filter keywords..." data-filter="kwgap">
      <table data-sortable><thead><tr>
        <th>Keyword</th><th class="num" data-num>Volume</th><th class="num" data-num>Difficulty</th>
        <th class="num" data-num>Traffic value</th><th class="num" data-num>Best comp. pos.</th><th>Competitors</th>
      </tr></thead><tbody data-rows="kwgap">
      {% for g in keyword_gaps %}<tr>
        <td>{{ g.keyword }}</td>
        <td class="num">{{ g.volume if g.volume is not none else '—' }}</td>
        <td class="num">{{ g.difficulty if g.difficulty is not none else '—' }}</td>
        <td class="num">{{ '%.0f'|format(g.traffic_value) if g.traffic_value is not none else '—' }}</td>
        <td class="num">{{ g.best_position if g.best_position is not none else '—' }}</td>
        <td>{{ g.competitors|join(', ') }}</td></tr>{% endfor %}
      </tbody></table>
    </div>
    {% endif %}

    {% if quick_wins %}
    <div class="panel" data-panel="wins">
      <table data-sortable><thead><tr><th>Keyword</th><th class="num" data-num>Position</th><th class="num" data-num>Volume</th><th class="num" data-num>Traffic value</th></tr></thead><tbody>
      {% for w in quick_wins %}<tr>
        <td>{% if w.url %}<a href="{{ w.url }}">{{ w.keyword }}</a>{% else %}{{ w.keyword }}{% endif %}</td>
        <td class="num">{{ w.position }}</td>
        <td class="num">{{ w.volume if w.volume is not none else '—' }}</td>
        <td class="num">{{ '%.0f'|format(w.traffic_value) if w.traffic_value is not none else '—' }}</td></tr>{% endfor %}
      </tbody></table>
    </div>
    {% endif %}

    {% if domain_keywords %}
    <div class="panel" data-panel="domains">
      {% for dk in domain_keywords %}
      <h2>{{ dk.domain }} <span class="muted">({{ dk.keywords|length }} keywords)</span></h2>
      <table data-sortable><thead><tr><th>Keyword</th><th class="num" data-num>Volume</th><th class="num" data-num>Difficulty</th><th class="num" data-num>Position</th></tr></thead><tbody>
      {% for e in dk.keywords %}<tr>
        <td>{{ e.keyword }}</td>
        <td class="num">{{ e.volume if e.volume is not none else '—' }}</td>
        <td class="num">{{ e.difficulty if e.difficulty is not none else '—' }}</td>
        <td class="num">{{ e.position if e.position is not none else '—' }}</td></tr>{% endfor %}
      </tbody></table>
      {% endfor %}
    </div>
    {% endif %}

    {% if topical_map.pillars %}
    <div class="panel" data-panel="map">
      {% if topical_map.summary %}<p class="muted">{{ topical_map.summary }}</p>{% endif %}
      {% for pillar in topical_map.pillars %}
      <h2>{{ pillar.name }}</h2>
      {% for cluster in pillar.clusters %}
      <div class="muted" style="margin:6px 0 2px;">{{ cluster.name }}</div>
      <ul>{% for a in cluster.articles %}<li>{{ a.title }}{% if a.target_keyword %} <span class="muted">· {{ a.target_keyword }}</span>{% endif %}</li>{% endfor %}</ul>
      {% endfor %}
      {% endfor %}
    </div>
    {% endif %}

    {% if drafts %}
    <div class="panel" data-panel="drafts">
      {% for d in drafts %}
      <div class="draft">
        <h2 style="margin-top:0;">{{ d.title }}</h2>
        <div class="muted">{% if d.target_keyword %}Target keyword: {{ d.target_keyword }}{% endif %}{% if d.word_count %} · {{ d.word_count }} words{% endif %}</div>
        {% if d.meta_description %}<div class="muted" style="margin:6px 0;">{{ d.meta_description }}</div>{% endif %}
        <div>{{ d.body_html|safe }}</div>
        {% if d.internal_links %}<h3>Suggested internal links</h3><ul class="links">{% for l in d.internal_links %}<li>{{ l.anchor }} → {{ l.url }}</li>{% endfor %}</ul>{% endif %}
      </div>
      {% endfor %}
    </div>
    {% endif %}

    {% if provided %}
    <div class="panel" data-panel="provided">
      <table data-sortable><thead><tr><th>Keyword</th><th class="num" data-num>Volume</th><th class="num" data-num>Difficulty</th><th class="num" data-num>Client pos.</th><th class="num" data-num>Best comp. pos.</th></tr></thead><tbody>
      {% for p in provided %}<tr>
        <td>{{ p.keyword }}</td>
        <td class="num">{{ p.volume if p.volume is not none else '—' }}</td>
        <td class="num">{{ p.difficulty if p.difficulty is not none else '—' }}</td>
        <td class="num">{{ p.client_position if p.client_position is not none else '—' }}</td>
        <td class="num">{{ p.best_position if p.best_position is not none else '—' }}</td></tr>{% endfor %}
      </tbody></table>
    </div>
    {% endif %}
  </div>
  <p class="muted" style="text-align:center;margin-top:14px;">Generated by {{ branding.agency_name }}</p>
</div>
<script>
(function(){
  var tabs=document.querySelectorAll('.tab'),panels=document.querySelectorAll('.panel');
  tabs.forEach(function(t){t.addEventListener('click',function(){
    tabs.forEach(function(x){x.classList.toggle('active',x===t);});
    panels.forEach(function(p){p.classList.toggle('active',p.getAttribute('data-panel')===t.getAttribute('data-tab'));});
  });});
  document.querySelectorAll('input.filter').forEach(function(inp){
    inp.addEventListener('input',function(){
      var q=inp.value.toLowerCase();
      var body=document.querySelector('[data-rows="'+inp.getAttribute('data-filter')+'"]');
      if(!body)return;
      Array.prototype.forEach.call(body.rows,function(r){
        r.style.display=r.cells[0].textContent.toLowerCase().indexOf(q)>-1?'':'none';
      });
    });
  });
  document.querySelectorAll('table[data-sortable]').forEach(function(tbl){
    var ths=tbl.tHead.rows[0].cells,asc={};
    Array.prototype.forEach.call(ths,function(th,i){
      th.addEventListener('click',function(){
        asc[i]=!asc[i];
        var num=th.hasAttribute('data-num'),body=tbl.tBodies[0];
        var rows=Array.prototype.slice.call(body.rows);
        rows.sort(function(a,b){
          var av=a.cells[i].textContent.replace(/[$,—]/g,'').trim();
          var bv=b.cells[i].textContent.replace(/[$,—]/g,'').trim();
          var c=num?((parseFloat(av)||0)-(parseFloat(bv)||0)):av.localeCompare(bv);
          return asc[i]?c:-c;
        });
        rows.forEach(function(r){body.appendChild(r);});
      });
    });
  });
})();
</script>
</body></html>
```

- [ ] **Step 4: Add `render_dashboard_html` to `compresearch/dashboard.py`**

Append after `build_dashboard_context`:

```python
def render_dashboard_html(context: dict, templates_dir: Path = TEMPLATES_DIR) -> str:
    """Render the self-contained dashboard HTML from the context view-model."""
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    return env.get_template("dashboard.html.j2").render(**context)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_dashboard.py -q`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
git add compresearch/templates/dashboard.html.j2 compresearch/dashboard.py tests/test_dashboard.py
git commit -m "feat: add self-contained dashboard HTML template and renderer"
```

---

### Task 4: `run_dashboard` (write file + record path, resilient)

**Files:**
- Modify: `compresearch/dashboard.py`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dashboard.py`:

```python
from compresearch.job_store import create_job, load_data, save_data


def test_run_dashboard_writes_html_and_records_path(tmp_path):
    from compresearch.dashboard import run_dashboard
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = _full_jobdata()
    data.config = cfg
    save_data(job_dir, data)

    run_dashboard(job_dir)

    reloaded = load_data(job_dir)
    assert reloaded.dashboard.error is None
    assert reloaded.dashboard.html_path.endswith("acme-co-dashboard.html")
    written = (job_dir / "outputs" / "acme-co-dashboard.html").read_text(encoding="utf-8")
    assert written.startswith("<!DOCTYPE html>")
    assert "free crm" in written


def test_run_dashboard_captures_render_error(tmp_path, monkeypatch):
    from compresearch import dashboard
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)

    def boom(context, templates_dir=dashboard.TEMPLATES_DIR):
        raise RuntimeError("template broke")

    monkeypatch.setattr(dashboard, "render_dashboard_html", boom)
    dashboard.run_dashboard(job_dir)

    data = load_data(job_dir)
    assert data.dashboard.html_path is None
    assert "template broke" in data.dashboard.error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_dashboard.py -q`
Expected: FAIL with `AttributeError: module 'compresearch.dashboard' has no attribute 'run_dashboard'`.

- [ ] **Step 3: Add `run_dashboard` to `compresearch/dashboard.py`**

Append:

```python
def run_dashboard(job_dir, branding: Branding | None = None) -> JobData:
    """Render the client dashboard to a single self-contained HTML file and record its
    path in data.json. Never raises — failures are captured like the other steps."""
    data = load_data(job_dir)
    branding = branding or load_branding()
    slug = slugify(data.config.client_name)
    output_path = Path(job_dir) / "outputs" / f"{slug}-dashboard.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        html = render_dashboard_html(build_dashboard_context(data, branding))
        output_path.write_text(html, encoding="utf-8")
        data.dashboard = DashboardResult(html_path=str(output_path))
    except Exception as exc:
        logging.warning("Dashboard render failed for %s: %s", data.config.client_url, exc)
        data.dashboard = DashboardResult(error=str(exc))
    save_data(job_dir, data)
    return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_dashboard.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/dashboard.py tests/test_dashboard.py
git commit -m "feat: add run_dashboard writing the self-contained dashboard file"
```

---

### Task 5: Orchestrator integration (dashboard step)

**Files:**
- Modify: `compresearch/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Update orchestrator tests for the new step**

In `tests/test_orchestrator.py`, in `test_run_job_runs_all_six_steps_offline`, change the expected step-name list to include `dashboard`:

```python
    assert [s.name for s in report.steps] == [
        "sitemap", "keywords", "topical_map", "draft_post", "draft_export", "render", "sheet", "dashboard",
    ]
```

And add, after the existing deliverable assertions in that test:

```python
    assert data.dashboard.html_path.endswith("acme-co-dashboard.html")
```

In `test_run_job_skips_cached_steps_on_resume`, add to the status assertions:

```python
    assert statuses["dashboard"] == "ok"   # cheap output step always re-runs
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_orchestrator.py -q`
Expected: FAIL (step list mismatch / `data.dashboard` is None).

- [ ] **Step 3: Add the dashboard step to the orchestrator**

In `compresearch/orchestrator.py`, add the import near the other step imports:

```python
from compresearch.dashboard import run_dashboard
```

In `_run_pipeline`, immediately after the `# 7. Google Sheet` block (after its `record("sheet", ...)`/`except`), add:

```python
    # 8. Client dashboard (cheap output; always runs so it reflects the latest data)
    t = time.monotonic()
    try:
        run_dashboard(job_dir)
        status, err = _section_status(job_dir, "dashboard")
        record("dashboard", status, err, t)
    except Exception as exc:
        record("dashboard", "failed", str(exc), t)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_orchestrator.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add compresearch/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: run the client dashboard as a pipeline output step"
```

---

### Task 6: CLI — `dashboard` subcommand, refresh-outputs, summary lines

**Files:**
- Modify: `compresearch/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Update/add CLI tests**

In `tests/test_cli.py`, in `test_run_job_subcommand_end_to_end`, update the expected step list:

```python
    assert [s.name for s in data.run_report.steps] == [
        "sitemap", "keywords", "topical_map", "draft_post", "draft_export", "render", "sheet", "dashboard",
    ]
```

Append two new tests to `tests/test_cli.py`:

```python
def test_dashboard_subcommand_writes_file(tmp_path):
    from compresearch.models import JobData, DraftPostResult
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = JobData(config=cfg, draft_post=DraftPostResult(post=DraftPost(
        title="What is a CRM?", body_markdown="# What is a CRM?\n\nBody.")))
    save_data(job_dir, data)

    returned = run_from_args(["dashboard", "--job-dir", str(job_dir)])
    assert returned == job_dir
    reloaded = load_data(job_dir)
    assert reloaded.dashboard.html_path.endswith("acme-co-dashboard.html")
    assert (job_dir / "outputs" / "acme-co-dashboard.html").exists()


def test_refresh_outputs_includes_dashboard(tmp_path):
    from compresearch.models import JobData, DraftPostResult
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = JobData(config=cfg, draft_posts=[DraftPostResult(post=DraftPost(
        title="T", body_markdown="# T\n\nBody."))])
    save_data(job_dir, data)

    def html_to_pdf(html, output_path):
        from pathlib import Path as _P
        _P(output_path).write_text("PDF", encoding="utf-8")

    run_from_args(
        ["refresh-outputs", "--job-dir", str(job_dir)],
        html_to_pdf=html_to_pdf,
        sheet_writer=lambda title, tabs: "https://docs.google.com/spreadsheets/d/FAKE",
        doc_writer=lambda title, html: "https://docs.google.com/document/d/DOC/edit",
    )
    assert load_data(job_dir).dashboard.html_path is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py -q`
Expected: FAIL (unknown command `dashboard` / step list mismatch / `dashboard` is None).

- [ ] **Step 3: Wire the dashboard into the CLI**

In `compresearch/cli.py`, add the import next to the other run-step imports:

```python
from compresearch.dashboard import run_dashboard
```

Add a subparser next to the `draft-export` parser (after the `de` parser block):

```python
    db = sub.add_parser("dashboard", help="Build the self-contained client dashboard HTML for an existing job")
    db.add_argument("--job-dir", required=True)
```

Add the handler next to the other per-step handlers (after the `draft-export` handler block):

```python
    if args.command == "dashboard":
        job_dir = Path(args.job_dir)
        with job_log(job_dir):
            run_dashboard(job_dir)
        _verify_step(job_dir, "dashboard")
        return job_dir
```

In the `refresh-outputs` handler, add `run_dashboard` inside the `with job_log(job_dir):` block, after `run_sheet(...)`:

```python
    if args.command == "refresh-outputs":
        job_dir = Path(args.job_dir)
        with job_log(job_dir):
            run_draft_export(job_dir, doc_writer=doc_writer)
            run_render(job_dir, html_to_pdf=html_to_pdf)
            run_sheet(job_dir, writer=sheet_writer)
            run_dashboard(job_dir)
        _print_outputs_summary(load_data(job_dir))
        return job_dir
```

In `_print_run_summary`, add a dashboard line after the `Sheet:` line:

```python
    if data.sheet is not None and data.sheet.sheet_url:
        print(f"  Sheet: {data.sheet.sheet_url}")
    if data.dashboard is not None and data.dashboard.html_path:
        print(f"  Dashboard: {data.dashboard.html_path}")
```

In `_print_outputs_summary`, add the same dashboard line after its `Sheet:` line:

```python
    if data.sheet is not None and data.sheet.sheet_url:
        print(f"  Sheet: {data.sheet.sheet_url}")
    if data.dashboard is not None and data.dashboard.html_path:
        print(f"  Dashboard: {data.dashboard.html_path}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS (all tests).

- [ ] **Step 6: Commit**

```bash
git add compresearch/cli.py tests/test_cli.py
git commit -m "feat: add dashboard CLI command, refresh-outputs and summary integration"
```

---

### Task 7: Documentation

**Files:**
- Modify: `README.md`, `.claude/skills/competitive-research/SKILL.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`

- [ ] **Step 1: README — add a dashboard section**

In `README.md`, after the "Create the Google Sheet appendix" section, add:

```markdown
## Build the client dashboard

Turns a job's finished `data.json` into a single self-contained, branded HTML dashboard the
client can open in any browser (no server) — the same data as the Sheet, but explorable with
tabs and sortable/filterable tables.

```
.venv\Scripts\python -m compresearch.cli dashboard --job-dir jobs\acme-co
```

The file is written to `jobs\<slug>\outputs\<slug>-dashboard.html` and its path is recorded in
`data.json` under `dashboard`. It's also produced by the full `run-job` and by `refresh-outputs`.
```

Also, in the `run-job` output description near the top, add the dashboard to the produced outputs (change "the branded PDF report and Google Sheet" phrasing to also mention "and a self-contained HTML dashboard").

- [ ] **Step 2: SKILL.md — mention the dashboard**

In `.claude/skills/competitive-research/SKILL.md`, in the "Report back" section, add the dashboard to the list of deliverables the summary prints (PDF path, Sheet URL, **dashboard HTML path**, draft exports, cost).

- [ ] **Step 3: ARCHITECTURE.md — module table + data.json sections**

In `docs/ARCHITECTURE.md`:
- Add to the module table: `| \`dashboard.py\` | \`run_dashboard\` — builds the self-contained, branded interactive HTML dashboard from data.json |`
- In the `data.json` "grows one section per step" sentence, add `dashboard` to the list.
- Update the orchestrator row/diagram note to mention the dashboard output step if step counts are stated.

- [ ] **Step 4: ROADMAP.md — mark shipped**

In `docs/ROADMAP.md`, move "Client-facing web dashboard or microsite" out of "Out of scope" and add to the Shipped → Enhancements list:

```markdown
- [x] Client-facing dashboard — single self-contained, branded interactive HTML (tabs, sortable/filterable tables) built from data.json, written to outputs/
```

Update the "Out of scope" note so it refers only to the *hosted* microsite (live URL), not the local-file dashboard.

- [ ] **Step 5: Commit**

```bash
git add README.md .claude/skills/competitive-research/SKILL.md docs/ARCHITECTURE.md docs/ROADMAP.md
git commit -m "docs: document the client dashboard output"
```

---

## Self-review

**Spec coverage:**
- Single self-contained HTML in outputs/ → Task 3 (template, no external refs) + Task 4 (`run_dashboard`). ✓
- Full dataset mirroring the Sheet (gaps, quick wins, per-domain keywords, provided, topical map, all drafts) → Task 2 view-model + Task 3 template. ✓
- Interactivity (tabs, sort, filter), no CDN → Task 3 template inline JS + self-containment test. ✓
- Branding consistent with PDF → reuses `_logo_html`/`_bar_chart_svg`, branding colors in template. ✓
- `DashboardResult` + `JobData.dashboard` → Task 1. ✓
- Cheap always-on step after `sheet` → Task 5. ✓
- Standalone CLI command + refresh-outputs + summary → Task 6. ✓
- Tested offline → Tasks 1–6 tests. ✓
- Docs (README/SKILL/ARCHITECTURE/ROADMAP) → Task 7. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `build_dashboard_context` → `render_dashboard_html` → `run_dashboard` signatures consistent across tasks; `DashboardResult.html_path`/`.error` used consistently; orchestrator/CLI reference `data.dashboard.html_path` and the `"dashboard"` section name consistently; `_verify_step(job_dir, "dashboard")` matches the `DashboardResult` (has `.error`, no `is_partial`). ✓
