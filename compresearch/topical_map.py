# compresearch/topical_map.py
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import anthropic

from compresearch.job_store import load_data, save_data
from compresearch.models import JobData, TopicalMap, TopicalMapResult
from compresearch.settings import get_secret


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
    if business_description is not None:
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


DEFAULT_TOPICAL_MAP_MODEL = "claude-sonnet-4-6"

Generator = Callable[[str], TopicalMap]


class ClaudeTopicalMapGenerator:
    """Generates a TopicalMap via the Claude API. The network call is isolated here
    so the rest of the module is tested offline with a fake generator."""

    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        model: str = DEFAULT_TOPICAL_MAP_MODEL,
        # Adaptive thinking shares this budget with the visible output, so the
        # map JSON needs headroom beyond what thinking consumes. A rich grounding
        # set (many keyword gaps + a deep sitemap) produces a large map; 16K left
        # too little after thinking and truncated the JSON mid-string. Sonnet 4.6
        # allows up to 64K output — 32K is safe non-streaming and ample here.
        max_tokens: int = 32000,
    ) -> None:
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens
        self.last_usage: dict | None = None

    def __call__(self, prompt: str) -> TopicalMap:
        # With max_tokens this high the SDK's non-streaming guard would refuse the
        # request (it estimates >10 min from max_tokens alone). A topical-map call
        # actually returns in well under a minute, so we set an explicit, generous
        # timeout to suppress the guard rather than restructuring into a stream.
        response = self.client.with_options(timeout=1800.0).messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
            output_format=TopicalMap,
        )
        usage = getattr(response, "usage", None)
        self.last_usage = (
            {
                "input_tokens": getattr(usage, "input_tokens", 0) or 0,
                "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            }
            if usage is not None
            else None
        )
        topical_map = response.parsed_output
        if topical_map is None:
            raise RuntimeError(
                f"Claude returned no structured output (stop_reason="
                f"{getattr(response, 'stop_reason', None)!r})"
            )
        return topical_map

    @classmethod
    def from_settings(cls) -> "ClaudeTopicalMapGenerator":
        if not get_secret("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY must be set to generate a topical map")
        return cls()


def _gather_topical_inputs(
    data: JobData,
) -> tuple[str, str | None, list[str], list[str], list[tuple[str, int | None]], list[tuple[str, int]]]:
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


def _map_has_article_ideas(topical_map: TopicalMap) -> bool:
    """True when the map contains at least one concrete article idea.

    A map with no pillars — or pillars/clusters that bottom out with no articles —
    gives the downstream draft step nothing to work with, so it is treated as a
    failed generation rather than a cached success."""
    return any(
        cluster.articles
        for pillar in topical_map.pillars
        for cluster in pillar.clusters
    )


def run_topical_map(job_dir: Path, generator: Generator | None = None, force: bool = False) -> JobData:
    """Generate a topical map for a job and persist it to data.json.

    Skips the LLM call when a successful map is already cached, unless force=True."""
    data = load_data(job_dir)
    if (
        not force
        and data.topical_map is not None
        and data.topical_map.error is None
        and data.topical_map.map is not None
    ):
        logging.info("Skipping topical map for %s: cached result present (use --force to re-run)",
                     data.config.client_url)
        return data
    if generator is None:
        generator = ClaudeTopicalMapGenerator.from_settings()

    inputs = _gather_topical_inputs(data)
    (_, _, _, sitemap_gaps, keyword_gaps, _) = inputs
    if not sitemap_gaps and not keyword_gaps:
        logging.warning(
            "Topical map for %s has no sitemap gaps and no keyword gaps to ground on; "
            "run the sitemap and keywords modules first for best results",
            data.config.client_url,
        )
    prompt = build_topical_map_prompt(*inputs)
    model = getattr(generator, "model", None)
    try:
        topical_map = generator(prompt)
        if not _map_has_article_ideas(topical_map):
            # An empty map satisfies `map is not None and error is None`, so without this
            # guard the orchestrator's cache check would mark the step complete and a plain
            # `run-job --job-dir <dir>` resume would NOT regenerate it. Recording it as a
            # failure instead keeps the pipeline resilient and lets resume retry it.
            logging.warning(
                "Topical map for %s came back empty (no article ideas); recording as failed",
                data.config.client_url,
            )
            data.topical_map = TopicalMapResult(model=model, error="Topical map came back empty")
        else:
            data.topical_map = TopicalMapResult(map=topical_map, model=model)
    except Exception as exc:
        logging.warning("Topical map generation failed for %s: %s", data.config.client_url, exc)
        data.topical_map = TopicalMapResult(model=model, error=str(exc))
    save_data(job_dir, data)
    return data
