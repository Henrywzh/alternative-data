"""Per-company cockpit overlays for Research Control Tower.

Generic company tabs (quote, price, consensus, PE, filings, thesis, evidence)
already key off entity_id / listing_id. This module only stores data-routing
overlays that cannot be inferred from the marts: OpenRouter model filters and
HK Stock Connect codes. It must not contain invented KPIs, thesis copy, or
mark-to-market cards.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OpenRouterFilter:
    slug_prefixes: tuple[str, ...] = ()
    origin_names: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    title: str = ""
    signal_name: str = "tokens"
    caption: str = ""


@dataclass(frozen=True)
class SouthboundSpec:
    mart_filename: str
    security_code: str
    canonical_ticker: str
    listing_id: str


@dataclass(frozen=True)
class SegmentSpec:
    metric: str
    label: str


@dataclass(frozen=True)
class CompanyProfile:
    entity_id: str
    reporting_currency_symbol: str = "¥"
    reporting_currency: str = "CNY"
    segment_metrics: tuple[SegmentSpec, ...] = ()
    openrouter: OpenRouterFilter | None = None
    southbound: SouthboundSpec | None = None
    alt_data_caption: str = ""


PROFILES: dict[str, CompanyProfile] = {
    "TENCENT": CompanyProfile(
        entity_id="TENCENT",
        reporting_currency_symbol="¥",
        reporting_currency="CNY",
        segment_metrics=(
            SegmentSpec("revenue_vas", "VAS (Games & Social)"),
            SegmentSpec("revenue_marketing_services", "Marketing Services (Ads)"),
            SegmentSpec("revenue_online_advertising", "Marketing Services (Ads)"),
            SegmentSpec("revenue_fintech_business_services", "Fintech & Enterprise Cloud"),
        ),
        openrouter=OpenRouterFilter(
            slug_prefixes=("tencent/",),
            origin_names=("Tencent",),
            entity_ids=("tencent",),
            title="Tencent Hunyuan (混元) AI Token & API Economics (OpenRouter Signal)",
            signal_name="Hunyuan tokens",
            caption="Estimated revenue is a priced-route reconstruction, not Tencent Cloud billed revenue.",
        ),
        southbound=SouthboundSpec(
            mart_filename="tencent_southbound_holdings.parquet",
            security_code="00700",
            canonical_ticker="0700.HK",
            listing_id="0700_HK",
        ),
        alt_data_caption="Non-filing signals for Tencent: OpenRouter Hunyuan usage and Stock Connect southbound ownership. These are not official issuer financials.",
    ),
    "ALIBABA": CompanyProfile(
        entity_id="ALIBABA",
        reporting_currency_symbol="¥",
        reporting_currency="CNY",
        segment_metrics=(
            SegmentSpec("revenue_china_commerce", "China commerce"),
            SegmentSpec("revenue_international_commerce", "International commerce"),
            SegmentSpec("revenue_cloud", "Cloud"),
            SegmentSpec("revenue_cainiao", "Cainiao"),
            SegmentSpec("revenue_local_consumer_services", "Local consumer services"),
            SegmentSpec("revenue_digital_media_entertainment", "Digital media & entertainment"),
        ),
        openrouter=OpenRouterFilter(
            slug_prefixes=("qwen/",),
            origin_names=("Alibaba (Qwen)", "Alibaba"),
            entity_ids=("alibaba", "qwen"),
            title="Alibaba Qwen AI Token & API Economics (OpenRouter Signal)",
            signal_name="Qwen tokens",
            caption="Estimated revenue is a priced-route reconstruction, not Alibaba Cloud billed revenue.",
        ),
        southbound=SouthboundSpec(
            mart_filename="alibaba_southbound_holdings.parquet",
            security_code="09988",
            canonical_ticker="9988.HK",
            listing_id="9988_HK",
        ),
        alt_data_caption="Non-filing signals for Alibaba: OpenRouter Qwen usage and Stock Connect southbound ownership of 9988.HK. These are not official issuer financials.",
    ),
    "MINIMAX": CompanyProfile(
        entity_id="MINIMAX",
        reporting_currency_symbol="¥",
        reporting_currency="CNY",
        openrouter=OpenRouterFilter(
            slug_prefixes=("minimax/",),
            origin_names=("MiniMax", "Minimax"),
            entity_ids=("minimax",),
            title="MiniMax AI Token & API Economics (OpenRouter Signal)",
            signal_name="MiniMax tokens",
            caption="Estimated revenue is a priced-route reconstruction, not MiniMax billed revenue.",
        ),
        alt_data_caption="Non-filing signals for MiniMax: OpenRouter token and estimated-revenue usage. These are not official issuer financials.",
    ),
    "Z_AI": CompanyProfile(
        entity_id="Z_AI",
        reporting_currency_symbol="¥",
        reporting_currency="CNY",
        openrouter=OpenRouterFilter(
            slug_prefixes=("z-ai/",),
            origin_names=("智谱AI (Z.ai)", "Z.AI", "Zhipu"),
            entity_ids=("z-ai", "zai"),
            title="Z.AI GLM Token & API Economics (OpenRouter Signal)",
            signal_name="GLM tokens",
            caption="Estimated revenue is a priced-route reconstruction, not Z.AI billed revenue.",
        ),
        alt_data_caption="Non-filing signals for Z.AI: OpenRouter GLM usage. These are not official issuer financials.",
    ),
    "MOONSHOT": CompanyProfile(
        entity_id="MOONSHOT",
        reporting_currency_symbol="¥",
        reporting_currency="CNY",
        openrouter=OpenRouterFilter(
            slug_prefixes=("moonshotai/",),
            origin_names=("Moonshot AI",),
            entity_ids=("moonshotai", "moonshot", "kimi"),
            title="Moonshot AI / Kimi Token & API Economics (OpenRouter Signal)",
            signal_name="Kimi tokens",
            caption="Estimated revenue is a priced-route reconstruction, not Moonshot billed revenue.",
        ),
        alt_data_caption="Non-filing signals for Moonshot AI: OpenRouter Kimi usage. Company remains private / pre-listing, so quote, filings and southbound modules stay unavailable.",
    ),
}


GENERIC_SEGMENT_LABELS: dict[str, str] = {
    "revenue_vas": "VAS (Games & Social)",
    "revenue_marketing_services": "Marketing Services (Ads)",
    "revenue_online_advertising": "Marketing Services (Ads)",
    "revenue_fintech_business_services": "Fintech & Enterprise Cloud",
    "revenue_china_commerce": "China commerce",
    "revenue_international_commerce": "International commerce",
    "revenue_cloud": "Cloud",
    "revenue_cainiao": "Cainiao",
    "revenue_local_consumer_services": "Local consumer services",
    "revenue_digital_media_entertainment": "Digital media & entertainment",
}


def get_company_profile(entity_id: str | None) -> CompanyProfile:
    key = str(entity_id or "").strip().upper()
    if key in PROFILES:
        return PROFILES[key]
    return CompanyProfile(entity_id=key or "UNKNOWN")


def segment_label(metric: str, profile: CompanyProfile | None = None) -> str:
    metric_key = str(metric or "").strip()
    if profile is not None:
        for spec in profile.segment_metrics:
            if spec.metric == metric_key:
                return spec.label
    if metric_key in GENERIC_SEGMENT_LABELS:
        return GENERIC_SEGMENT_LABELS[metric_key]
    pretty = metric_key.replace("revenue_", "").replace("_", " ").strip()
    return pretty.title() if pretty else metric_key
