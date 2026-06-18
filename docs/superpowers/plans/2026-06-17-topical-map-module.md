# Topical Map Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Topical Map module to `compresearch` that uses the Claude API to turn the already-collected sitemap gaps + keyword gaps (plus an optional operator business description) into a data-driven topical map — pillars → clusters → article ideas, each tied to a target keyword — written to a job's `data.json`.

**Architecture:** Mirrors the sitemap/keywords modules. The LLM call is isolated behind an injectable **generator** (`Callable[[str], TopicalMap]` with a `.model` attribute), so the prompt-building and orchestration logic test fully offline with a fake generator (zero API spend), exactly as the sitemap `Fetcher` and keyword `Provider` do. The real generator (`ClaudeTopicalMapGenerator`) calls the official `anthropic` SDK with structured outputs. This is the first module to consume *both* prior modules' outputs (`data.sitemap.gaps`, `data.keywords.gaps`/`quick_wins`) and the first to call an LLM.

**Tech Stack:** Python 3.11+ (running on 3.14), pydantic v2, the `anthropic` SDK (Claude API), pytest. Builds on Plans 1 + 2 (merged to `master`).

---

## Context for the implementer

Already present in `compresearch` (do not recreate): `models.py` (schema incl. `JobConfig`, `JobData`, `SitemapResult`/`SitemapGap`, `KeywordResult`/`KeywordGap`/`QuickWin`), `settings.py` (`get_secret`), `job_store.py` (`load_data`, `save_data`, `create_job`), `sitemap.py`, `keywords.py`, `cli.py` (argparse with `sitemap` + `keywords` subcommands and `run_from_args(argv, fetch=http_fetch, provider=None) -> Path`). 55 tests pass. Run tests with `.venv\Scripts\python -m pytest` (Windows). Work on a feature branch off `master`; commit per task with the messages given.

**Decisions already made (from brainstorming):**
- Business context: an **optional** `business_description` on the job config (operator blurb). If blank, the module auto-derives context from the domain, crawled sections, and keyword data.
- Model: **`claude-sonnet-4-6`** is the configurable default. (Exact model-ID string — no date suffix.)
- The module consumes prior gaps; it does no keyword/semantic clustering of its own beyond what the LLM produces.

**Claude API notes (from the claude-api reference):**
- Use the official `anthropic` SDK (`anthropic.Anthropic()` reads `ANTHROPIC_API_KEY` from the environment).
- Structured output: `client.messages.parse(model=..., max_tokens=..., messages=[...], output_format=<PydanticModel>)` returns `.parsed_output` (a validated instance). This is the recommended path. Our schema uses only plain types + nested objects/arrays + optional fields — all supported by structured outputs (no recursion, no min/max constraints).
- `claude-sonnet-4-6` supports adaptive thinking: pass `thinking={"type": "adaptive"}`. Structured outputs are compatible with thinking.
- `max_tokens=16000` (non-streaming is fine under that ceiling).
- If the installed `anthropic` version lacks `messages.parse`/`output_format`, fall back inside the generator to `client.messages.create(..., output_config={"format": {"type": "json_schema", "schema": TopicalMap.model_json_schema()}})` then `TopicalMap.model_validate_json(text)` on the first text block. This fallback is isolated to the generator and not exercised by the offline tests.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `requirements.txt` (modify) | Add the `anthropic` dependency |
| `compresearch/models.py` (modify) | Add `business_description` to `JobConfig`; add `ArticleIdea`, `TopicCluster`, `PillarTopic`, `TopicalMap`, `TopicalMapResult`; add `topical_map` to `JobData` |
| `compresearch/topical_map.py` (create) | Prompt builder, `ClaudeTopicalMapGenerator`, input gathering, `run_topical_map` |
| `compresearch/cli.py` (modify) | Add a `topical-map` subcommand with clean error handling |
| `tests/test_topical_map.py` (create) | Prompt builder + orchestration via a fake generator (offline) |
| `tests/test_cli.py` (modify) | End-to-end `topical-map` run with a fake generator; missing-API-key clean exit |
| `README.md` (modify) | Document the topical-map usage; update status checklist |

---

## Task 1: Topical map data models

**Files:**
- Modify: `compresearch/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
from compresearch.models import (
    ArticleIdea, TopicCluster, PillarTopic, TopicalMap, TopicalMapResult,
)


def test_topical_map_models_round_trip():
    result = TopicalMapResult(
        map=TopicalMap(
            pillars=[PillarTopic(
                name="CRM Basics",
                description="Foundational CRM education",
                clusters=[TopicCluster(
                    name="Getting started",
                    articles=[ArticleIdea(
                        title="What is a CRM?",
                        target_keyword="what is a crm",
                        search_intent="informational",
                        estimated_volume=2000,
                        rationale="Fills an informational gap.",
                    )],
                )],
            )],
            summary="Three pillars covering CRM education and comparison.",
        ),
        model="claude-sonnet-4-6",
    )
    restored = TopicalMapResult.model_validate_json(result.model_dump_json())
    assert restored.map.pillars[0].clusters[0].articles[0].target_keyword == "what is a crm"
    assert restored.model == "claude-sonnet-4-6"
    assert restored.error is None


def test_jobconfig_business_description_optional_and_jobdata_topical_map():
    from compresearch.models import JobConfig, JobData
    cfg = JobConfig(client_name="X", client_url="https://x.com")
    assert cfg.business_description is None
    cfg2 = JobConfig(client_name="X", client_url="https://x.com",
                     business_description="We sell CRM software")
    assert cfg2.business_description == "We sell CRM software"
    assert JobData(config=cfg).topical_map is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_models.py -k topical_map`
Expected: FAIL — `ImportError: cannot import name 'ArticleIdea'`.

- [ ] **Step 3: Write the implementation**

In `compresearch/models.py`, add `business_description` to `JobConfig` (place it after `competitor_urls`, before `keyword_source`):

```python
    business_description: str | None = None
```

Add the topical-map models (after the keyword models, before `JobConfig`):

```python
class ArticleIdea(BaseModel):
    title: str
    target_keyword: str | None = None
    search_intent: str | None = None
    estimated_volume: int | None = None
    rationale: str | None = None


class TopicCluster(BaseModel):
    name: str
    articles: list[ArticleIdea] = Field(default_factory=list)


class PillarTopic(BaseModel):
    name: str
    description: str | None = None
    clusters: list[TopicCluster] = Field(default_factory=list)


class TopicalMap(BaseModel):
    pillars: list[PillarTopic] = Field(default_factory=list)
    summary: str | None = None


class TopicalMapResult(BaseModel):
    map: TopicalMap | None = None
    model: str | None = None
    error: str | None = None
```

Extend `JobData`:

```python
class JobData(BaseModel):
    config: JobConfig
    sitemap: SitemapResult | None = None
    keywords: KeywordResult | None = None
    topical_map: TopicalMapResult | None = None
    # Future sections (draft_post) added in later plans.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_models.py`
Expected: PASS (all model tests green).

- [ ] **Step 5: Commit**

```bash
git add compresearch/models.py tests/test_models.py
git commit -m "feat: add topical-map data models and business_description"
```

---

## Task 2: Prompt builder

**Files:**
- Create: `compresearch/topical_map.py`
- Test: `tests/test_topical_map.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_topical_map.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'compresearch.topical_map'`.

- [ ] **Step 3: Write the implementation**

```python
# compresearch/topical_map.py
from __future__ import annotations


def build_topical_map_prompt(
    client_url: str,
    business_description: str | None,
    existing_sections: list[str],
    sitemap_gaps: list[str],
    keyword_gaps: list[tuple[str, int | None]],
    quick_wins: list[tuple[str, int]],
    max_pillars: int = 7,
) -> str:
    """Build the Claude prompt for a data-driven topical map (deterministic — no timestamps)."""
    lines: list[str] = [
        "You are an expert SEO content strategist. Produce a data-driven topical map "
        "for a client's content marketing programme.",
        f"\nClient website: {client_url}",
    ]
    if business_description:
        lines.append(f"Business description: {business_description}")
    else:
        lines.append(
            "Business description: (not provided — infer the business from the domain, "
            "the existing content sections, and the keyword data below)"
        )
    if existing_sections:
        lines.append(
            "\nContent the client ALREADY has (do not duplicate these sections): "
            + ", ".join(sorted(existing_sections))
        )
    if sitemap_gaps:
        lines.append(
            "\nContent-type gaps (sections competitors have that the client lacks): "
            + ", ".join(sitemap_gaps)
        )
    if keyword_gaps:
        lines.append(
            "\nKeyword gaps (terms competitors rank for that the client does not), "
            "with monthly search volume where known:"
        )
        for keyword, volume in keyword_gaps:
            suffix = f" (volume {volume})" if volume is not None else ""
            lines.append(f"- {keyword}{suffix}")
    if quick_wins:
        lines.append(
            "\nQuick-win keywords (the client already ranks on page 1-2 — strengthen these):"
        )
        for keyword, position in quick_wins:
            lines.append(f"- {keyword} (current position {position})")
    lines.append(
        f"""
Build a topical map of up to {max_pillars} pillar topics. For each pillar provide 2-5
topic clusters, and for each cluster provide 2-5 specific article ideas.

Ground every suggestion in the data above: prefer article ideas that target a specific
keyword gap or quick-win, and fill the content-type gaps. Do not suggest topics the
client already covers. For each article idea include a specific title, the target keyword
(from the gaps/quick-wins where applicable), the search intent (informational, commercial,
transactional, or navigational), an estimated monthly search volume when known, and a
one-sentence rationale. Return the result in the required structured format."""
    )
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_topical_map.py`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add compresearch/topical_map.py tests/test_topical_map.py
git commit -m "feat: add topical-map prompt builder"
```

---

## Task 3: Generator + `run_topical_map` orchestration

**Files:**
- Modify: `requirements.txt`
- Modify: `compresearch/topical_map.py`
- Test: `tests/test_topical_map.py`

- [ ] **Step 1: Add the dependency**

Append `anthropic` to `requirements.txt` (a new line). Then install it:

Run: `.venv\Scripts\python -m pip install anthropic`
Expected: installs successfully. Pin the resolved version into `requirements.txt` (run `.venv\Scripts\python -m pip show anthropic` to get the version, then write e.g. `anthropic==<version>`). If the latest release does not install on the installed Python, pin the newest version that does — the same pragmatic adjustment made for `lxml`/`pydantic` in Plan 1.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_topical_map.py`:

```python
from compresearch.topical_map import run_topical_map
from compresearch.job_store import create_job, load_data, save_data
from compresearch.models import (
    JobConfig, SitemapResult, SitemapGap, DomainSitemap,
    KeywordResult, KeywordGap, QuickWin, TopicalMap, PillarTopic, TopicCluster, ArticleIdea,
)


def make_fake_generator(captured, result=None, raises=None, model="fake-model"):
    class FakeGenerator:
        def __init__(self):
            self.model = model

        def __call__(self, prompt):
            captured.append(prompt)
            if raises is not None:
                raise raises
            return result
    return FakeGenerator()


def _seed_job(tmp_path):
    cfg = JobConfig(
        client_name="Acme Co",
        client_url="https://acme.com",
        competitor_urls=["https://rival.com"],
        business_description="Acme sells CRM software",
    )
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    data = load_data(job_dir)
    data.sitemap = SitemapResult(
        client=DomainSitemap(domain="https://acme.com", section_counts={"blog": 3}),
        gaps=[SitemapGap(section="case-studies", competitors_with=["https://rival.com"])],
    )
    data.keywords = KeywordResult(
        gaps=[KeywordGap(keyword="free crm", search_volume=800, best_competitor_position=4)],
        quick_wins=[QuickWin(keyword="crm software", position=8, search_volume=1000)],
    )
    save_data(job_dir, data)
    return job_dir


def test_run_topical_map_persists_result_and_grounds_prompt(tmp_path):
    job_dir = _seed_job(tmp_path)
    fake_map = TopicalMap(pillars=[PillarTopic(
        name="CRM Basics",
        clusters=[TopicCluster(name="Getting started", articles=[
            ArticleIdea(title="What is a CRM?", target_keyword="free crm")])],
    )])
    captured = []
    run_topical_map(job_dir, generator=make_fake_generator(captured, result=fake_map))

    data = load_data(job_dir)
    assert data.topical_map is not None
    assert data.topical_map.error is None
    assert data.topical_map.model == "fake-model"
    assert data.topical_map.map.pillars[0].name == "CRM Basics"
    # prompt was grounded in the prior modules' data
    assert "case-studies" in captured[0]
    assert "free crm" in captured[0]
    assert "crm software" in captured[0]
    assert "blog" in captured[0]


def test_run_topical_map_captures_generator_error(tmp_path):
    job_dir = _seed_job(tmp_path)
    captured = []
    run_topical_map(
        job_dir,
        generator=make_fake_generator(captured, raises=RuntimeError("api down")),
    )
    data = load_data(job_dir)
    assert data.topical_map is not None
    assert data.topical_map.map is None
    assert "api down" in data.topical_map.error
    assert data.topical_map.model == "fake-model"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_topical_map.py -k run_topical_map`
Expected: FAIL — `ImportError: cannot import name 'run_topical_map'`.

- [ ] **Step 4: Write the implementation**

Append to `compresearch/topical_map.py` (add the imports at the top with the existing ones):

```python
import logging
from pathlib import Path

import anthropic

from compresearch.job_store import load_data, save_data
from compresearch.models import JobData, TopicalMap, TopicalMapResult
from compresearch.settings import get_secret

DEFAULT_TOPICAL_MAP_MODEL = "claude-sonnet-4-6"


class ClaudeTopicalMapGenerator:
    """Generates a TopicalMap via the Claude API. The network call is isolated here
    so the rest of the module is tested offline with a fake generator."""

    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        model: str = DEFAULT_TOPICAL_MAP_MODEL,
        max_tokens: int = 16000,
    ) -> None:
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def __call__(self, prompt: str) -> TopicalMap:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
            output_format=TopicalMap,
        )
        return response.parsed_output

    @classmethod
    def from_settings(cls) -> "ClaudeTopicalMapGenerator":
        if not get_secret("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY must be set to generate a topical map")
        return cls()


def _gather_topical_inputs(data: JobData):
    """Pull grounding inputs from the job's sitemap + keyword results."""
    config = data.config
    existing_sections: list[str] = []
    sitemap_gaps: list[str] = []
    if data.sitemap is not None:
        if data.sitemap.client is not None:
            existing_sections = list(data.sitemap.client.section_counts.keys())
        sitemap_gaps = [gap.section for gap in data.sitemap.gaps]
    keyword_gaps: list[tuple[str, int | None]] = []
    quick_wins: list[tuple[str, int]] = []
    if data.keywords is not None:
        keyword_gaps = [(g.keyword, g.search_volume) for g in data.keywords.gaps[:25]]
        quick_wins = [(w.keyword, w.position) for w in data.keywords.quick_wins[:15]]
    return (
        config.client_url,
        config.business_description,
        existing_sections,
        sitemap_gaps,
        keyword_gaps,
        quick_wins,
    )


def run_topical_map(job_dir: Path, generator=None) -> JobData:
    """Generate a topical map for a job and persist it to data.json."""
    data = load_data(job_dir)
    if generator is None:
        generator = ClaudeTopicalMapGenerator.from_settings()

    inputs = _gather_topical_inputs(data)
    if not inputs[3] and not inputs[4]:  # no sitemap gaps and no keyword gaps
        logging.warning(
            "Topical map for %s has no sitemap or keyword gaps to ground on; "
            "run the sitemap and keywords modules first for best results",
            data.config.client_url,
        )
    prompt = build_topical_map_prompt(*inputs)
    model = getattr(generator, "model", None)
    try:
        topical_map = generator(prompt)
        data.topical_map = TopicalMapResult(map=topical_map, model=model)
    except Exception as exc:
        logging.warning("Topical map generation failed for %s: %s", data.config.client_url, exc)
        data.topical_map = TopicalMapResult(model=model, error=str(exc))
    save_data(job_dir, data)
    return data
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_topical_map.py`
Expected: PASS (all topical-map tests green).

- [ ] **Step 6: Run the full suite**

Run: `.venv\Scripts\python -m pytest`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt compresearch/topical_map.py tests/test_topical_map.py
git commit -m "feat: add Claude topical-map generator and run_topical_map"
```

---

## Task 4: CLI `topical-map` subcommand

**Files:**
- Modify: `compresearch/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
from compresearch.models import (
    TopicalMap, PillarTopic, TopicCluster, ArticleIdea,
)


def _fake_generator(result):
    class FakeGenerator:
        model = "fake-model"

        def __call__(self, prompt):
            return result
    return FakeGenerator()


def test_topical_map_subcommand(tmp_path):
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com",
                    business_description="Acme sells CRM software")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    fake_map = TopicalMap(pillars=[PillarTopic(
        name="CRM Basics",
        clusters=[TopicCluster(name="Intro", articles=[ArticleIdea(title="What is a CRM?")])],
    )])

    returned = run_from_args(
        ["topical-map", "--job-dir", str(job_dir)],
        generator=_fake_generator(fake_map),
    )
    assert returned == job_dir
    data = load_data(returned)
    assert data.topical_map.map.pillars[0].name == "CRM Basics"


def test_topical_map_subcommand_missing_api_key_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = JobConfig(client_name="Acme Co", client_url="https://acme.com")
    job_dir = create_job(cfg, jobs_dir=tmp_path)
    import pytest
    with pytest.raises(SystemExit) as exc:
        run_from_args(["topical-map", "--job-dir", str(job_dir)])  # no generator -> from_settings
    assert exc.value.code == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py -k topical_map`
Expected: FAIL — argparse errors on the unknown `topical-map` subcommand (`SystemExit` with code 2, not 1) / or the generator param is unknown.

- [ ] **Step 3: Write the implementation**

In `compresearch/cli.py`:

1. Add the import: `from compresearch.topical_map import run_topical_map`.
2. Add a `generator=None` parameter to `run_from_args` (alongside `provider=None`):

```python
def run_from_args(argv: list[str], fetch: Fetcher = http_fetch, provider=None, generator=None) -> Path:
```

3. Add the subparser (after the `keywords` subparser):

```python
    tm = sub.add_parser("topical-map", help="Generate a topical map for an existing job")
    tm.add_argument("--job-dir", required=True)
```

4. Add the dispatch branch (after the `keywords` branch, before the final `raise`):

```python
    if args.command == "topical-map":
        job_dir = Path(args.job_dir)
        try:
            run_topical_map(job_dir, generator=generator)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        return job_dir
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_cli.py`
Expected: PASS (existing sitemap/keywords CLI tests plus the two new topical-map tests).

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python -m pytest`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add compresearch/cli.py tests/test_cli.py
git commit -m "feat: add topical-map CLI subcommand"
```

---

## Task 5: Docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the README**

Add a section after the keywords section and flip the status checklist line. Add:

```markdown
## Run the topical-map module

The topical map runs on a job that already has sitemap and keyword results (run those
first so the map is grounded in real gaps). It calls the Claude API.

Set `ANTHROPIC_API_KEY` in `.env`, optionally add a `business_description` to the job's
`job.yaml`, then:

```
.venv\Scripts\python -m compresearch.cli topical-map --job-dir jobs\acme-co
```

The result (pillars → clusters → article ideas, each tied to a target keyword) is written
to `data.json` under `topical_map`. The default model is `claude-sonnet-4-6`.
```

Change the keywords/topical status lines so the topical map is checked:

```markdown
- [x] Topical map module
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document topical-map module usage"
```

---

## Self-Review Notes

- **Spec coverage:** Data-driven topical map grounded in sitemap gaps + keyword gaps/quick-wins (Tasks 2–3) — the spec's key quality upgrade ("feed the actual gaps, not just a business description"). Optional operator `business_description` with auto-derive fallback (Tasks 1–2) — the brainstorming decision. Claude API via the official SDK with structured output and the configurable `claude-sonnet-4-6` default (Task 3). Output persisted to `data.json` under `topical_map` (Tasks 1, 3), consistent with the single-source-of-truth design and ready for the render module (Plan 5). Error isolation + a missing-API-key clean CLI exit + a no-gaps warning mirror the hardened behavior of the sitemap/keywords modules.
- **Placeholder scan:** No TBDs; every code/test step is complete. The SDK-version fallback (create + json_schema) is documented and isolated to the generator.
- **Type/name consistency:** `ArticleIdea`, `TopicCluster`, `PillarTopic`, `TopicalMap`, `TopicalMapResult`, `build_topical_map_prompt`, `ClaudeTopicalMapGenerator`, `DEFAULT_TOPICAL_MAP_MODEL`, `_gather_topical_inputs`, `run_topical_map` are used consistently across tasks and tests. `run_from_args` gains a `generator` param used only by the `topical-map` branch (sitemap uses `fetch`, keywords uses `provider`).
- **Known follow-ups:** the live `messages.parse`/`output_format` call is exercised only against a real account (the offline tests inject a fake generator) — confirm against the Anthropic API when a key is available; the structured-output schema is the first to round-trip nested optional fields through the SDK. The deferred `tests/conftest.py` dedup of fake factories (from Plan 1) still stands and now spans three modules.
