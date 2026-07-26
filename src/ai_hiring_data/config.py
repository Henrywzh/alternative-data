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

    # Tech expansion (2026-07) — Greenhouse
    _greenhouse("databricks", "Databricks", "databricks", "AI/data platform"),
    _greenhouse("stripe", "Stripe", "stripe", "Fintech"),
    _greenhouse("mongodb", "MongoDB", "mongodb", "Infrastructure"),
    _greenhouse("cloudflare", "Cloudflare", "cloudflare", "Network infrastructure"),
    _greenhouse("elastic", "Elastic", "elastic", "Search/data infrastructure"),
    _greenhouse("pinterest", "Pinterest", "pinterest", "Social"),
    _greenhouse("reddit", "Reddit", "reddit", "Social"),
    _greenhouse("twilio", "Twilio", "twilio", "Communication API"),
    _greenhouse("coinbase", "Coinbase", "coinbase", "Crypto/fintech"),
    _greenhouse("instacart", "Instacart", "instacart", "E-commerce"),
    _greenhouse("roblox", "Roblox", "roblox", "Gaming"),
    _greenhouse("airbnb", "Airbnb", "airbnb", "Travel"),
    _greenhouse("dropbox", "Dropbox", "dropbox", "Cloud storage"),
    _greenhouse("gitlab", "GitLab", "gitlab", "DevOps"),

    # Tech expansion (2026-07) — Ashby
    _ashby("notion", "Notion", "notion", "Productivity"),
    _ashby("supabase", "Supabase", "supabase", "Infrastructure"),
    _ashby("posthog", "PostHog", "posthog", "Analytics"),

    # Tech expansion wave 2 (2026-07) — Greenhouse
    _greenhouse("lyft", "Lyft", "lyft", "Ride sharing"),
    _greenhouse("datadog", "Datadog", "datadog", "Monitoring/observability"),
    _greenhouse("newrelic", "New Relic", "newrelic", "APM/monitoring"),
    _greenhouse("fastly", "Fastly", "fastly", "CDN/edge computing"),
    _greenhouse("okta", "Okta", "okta", "Identity/security"),
    _greenhouse("epicgames", "Epic Games", "epicgames", "Gaming/Unreal Engine"),
    _greenhouse("asana", "Asana", "asana", "Project management"),
    _greenhouse("discord", "Discord", "discord", "Social/communication"),
    _greenhouse("vercel", "Vercel", "vercel", "Frontend deployment"),
    _greenhouse("clickhouse", "ClickHouse", "clickhouse", "Real-time analytics DB"),
    _greenhouse("planetscale", "PlanetScale", "planetscale", "Serverless MySQL"),
    _greenhouse("cockroachlabs", "Cockroach Labs", "cockroachlabs", "Distributed SQL"),
    _greenhouse("algolia", "Algolia", "algolia", "Search API"),
    _greenhouse("graphcore", "Graphcore", "graphcore", "AI chip"),
    _greenhouse("lightmatter", "Lightmatter", "lightmatter", "AI photonic chip"),
    _greenhouse("netlify", "Netlify", "netlify", "Web deployment"),
    _greenhouse("circleci", "CircleCI", "circleci", "CI/CD"),
    _greenhouse("buildkite", "Buildkite", "buildkite", "CI/CD"),
    _greenhouse("launchdarkly", "LaunchDarkly", "launchdarkly", "Feature management"),
    _greenhouse("mixpanel", "Mixpanel", "mixpanel", "Product analytics"),
    _greenhouse("brex", "Brex", "brex", "Fintech/corporate cards"),
    _greenhouse("chime", "Chime", "chime", "Neobank"),
    _greenhouse("monzo", "Monzo", "monzo", "Neobank"),
    _greenhouse("figma", "Figma", "figma", "Design collaboration"),
    _greenhouse("otter", "Otter", "otter", "AI transcription"),
    _greenhouse("fivetran", "Fivetran", "fivetran", "Data pipeline"),

    # Tech expansion wave 2 (2026-07) — Ashby
    _ashby("snowflake", "Snowflake", "snowflake", "Cloud data warehouse"),
    _ashby("confluent", "Confluent", "confluent", "Kafka/data streaming"),
    _ashby("linear", "Linear", "linear", "Project management"),
    _ashby("sentry", "Sentry", "sentry", "Error monitoring"),
    _ashby("neon", "Neon", "neon", "Serverless Postgres"),
    _ashby("cerebras", "Cerebras", "cerebras", "AI chip"),
    _ashby("replit", "Replit", "replit", "Cloud IDE"),
    _ashby("render", "Render", "render", "Cloud hosting"),
    _ashby("railway", "Railway", "railway", "Cloud hosting"),
    _ashby("plaid", "Plaid", "plaid", "Fintech API"),
    _ashby("nubank", "Nubank", "nubank", "Neobank"),
    _ashby("miro", "Miro", "miro", "Collaboration whiteboard"),
    _ashby("airbyte", "Airbyte", "airbyte", "Data integration"),
    _ashby("motherduck", "MotherDuck", "motherduck", "DuckDB cloud"),
    _ashby("pinecone", "Pinecone", "pinecone", "Vector database"),
    _ashby("weaviate", "Weaviate", "weaviate", "Vector database"),
    _ashby("modal", "Modal", "modal", "Cloud GPU/serverless"),

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
