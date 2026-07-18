from __future__ import annotations

from ai_hiring_data.models import SourceSpec


COHORT_VERSION = "2026-07-mvp"
INDEED_SOURCE = SourceSpec(
    source_id="indeed_ai_tracker",
    source_kind="macro_csv",
    source_url="https://raw.githubusercontent.com/hiring-lab/ai-tracker/main/AI_posting.csv",
)


def _ashby(company_id: str, name: str, token: str, segment: str) -> SourceSpec:
    return SourceSpec(
        source_id=f"ashby_{company_id}",
        source_kind="job_board",
        source_url=f"https://api.ashbyhq.com/posting-api/job-board/{token}",
        company_id=company_id,
        company_name=name,
        company_segment=segment,
        source_platform="ashby",
        board_token=token,
        careers_url=f"https://jobs.ashbyhq.com/{token}",
    )


def _greenhouse(company_id: str, name: str, token: str, segment: str) -> SourceSpec:
    return SourceSpec(
        source_id=f"greenhouse_{company_id}",
        source_kind="job_board",
        source_url=f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
        company_id=company_id,
        company_name=name,
        company_segment=segment,
        source_platform="greenhouse",
        board_token=token,
        careers_url=f"https://job-boards.greenhouse.io/{token}",
    )


BOARD_SPECS: tuple[SourceSpec, ...] = (
    _ashby("openai", "OpenAI", "openai", "Frontier model lab"),
    _greenhouse("anthropic", "Anthropic", "anthropic", "Frontier model lab"),
    _ashby("perplexity", "Perplexity", "perplexity", "AI application"),
    _ashby("cursor", "Cursor", "cursor", "AI application"),
    _greenhouse("xai", "xAI", "xai", "Frontier model lab"),
    _ashby("cohere", "Cohere", "cohere", "Model platform"),
    _greenhouse("together_ai", "Together AI", "togetherai", "Model infrastructure"),
    _ashby("fireworks_ai", "Fireworks AI", "fireworksai", "Model infrastructure"),
    _greenhouse("scale_ai", "Scale AI", "scaleai", "AI data platform"),
    _ashby("elevenlabs", "ElevenLabs", "elevenlabs", "Generative media"),
)

SOURCE_SPECS: tuple[SourceSpec, ...] = (INDEED_SOURCE, *BOARD_SPECS)
ROLE_FAMILIES: tuple[str, ...] = (
    "Research",
    "AI / ML",
    "Engineering / Infrastructure",
    "Product / Design",
    "Safety / Policy",
    "Sales / GTM",
    "Operations",
    "Other",
)
