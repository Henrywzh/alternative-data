from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

from minerals_signal_data.models import PriceSourceRecord

CRITICAL_MINERALS_SHEET = "Critical minerals"
STOCK_MAPPING_SHEET = "Stock mapping"

_A_SHARE_PATTERN = re.compile(r"\b\d{6}\.(?:SH|SZ|BJ)\b", re.IGNORECASE)
_HK_PATTERN = re.compile(r"\b\d{3,5}\.HK\b", re.IGNORECASE)
_US_PATTERN = re.compile(r"\b[A-Z]{1,5}(?:\.[A-Z])?\b")
_PRIMARY_CONTEXT_PATTERN = re.compile(r"primary(?:\s+for)?\s+(?P<body>[^;,.]+)", re.IGNORECASE)
_SECONDARY_CONTEXT_PATTERN = re.compile(r"(secondary|adjacent|byproduct)", re.IGNORECASE)


PRICE_SOURCE_DEFAULTS: dict[str, PriceSourceRecord] = {
    "aluminum": PriceSourceRecord(
        normalized_mineral_id="aluminum",
        mineral_name="Aluminum",
        trackability_grade="direct",
        price_source_type="yfinance_futures",
        price_symbol_or_series_id="ALI=F",
        price_currency="USD",
        price_unit="metric ton",
        publish_lag_assumption_days=1,
        is_active_for_v1=True,
    ),
    "antimony": PriceSourceRecord(
        normalized_mineral_id="antimony",
        mineral_name="Antimony",
        trackability_grade="proxy",
        price_source_type="yfinance_futures",
        price_symbol_or_series_id="HG=F",
        price_currency="USD",
        price_unit="lb",
        publish_lag_assumption_days=2,
        is_active_for_v1=True,
        proxy_target="copper",
        proxy_type="commodity_cross_proxy",
        proxy_instrument="HG=F",
        proxy_display_name="COMEX Copper Futures",
    ),
    "cobalt": PriceSourceRecord(
        normalized_mineral_id="cobalt",
        mineral_name="Cobalt",
        trackability_grade="direct",
        price_source_type="investing_html",
        price_symbol_or_series_id="https://www.investing.com/commodities/cobalt-historical-data",
        price_currency="USD",
        price_unit="metric ton",
        publish_lag_assumption_days=1,
        is_active_for_v1=True,
    ),
    "copper": PriceSourceRecord(
        normalized_mineral_id="copper",
        mineral_name="Copper",
        trackability_grade="direct",
        price_source_type="yfinance_futures",
        price_symbol_or_series_id="HG=F",
        price_currency="USD",
        price_unit="lb",
        publish_lag_assumption_days=1,
        is_active_for_v1=True,
    ),
    "gallium": PriceSourceRecord(
        normalized_mineral_id="gallium",
        mineral_name="Gallium",
        trackability_grade="direct",
        price_source_type="investing_html",
        price_symbol_or_series_id="https://www.investing.com/commodities/gallium-99.99-min-united-states-futures-historical-data",
        price_currency="USD",
        price_unit="kg",
        publish_lag_assumption_days=3,
        is_active_for_v1=True,
    ),
    "germanium": PriceSourceRecord(
        normalized_mineral_id="germanium",
        mineral_name="Germanium",
        trackability_grade="direct",
        price_source_type="investing_html",
        price_symbol_or_series_id="https://www.investing.com/commodities/germanium-99.99-min-china-futures-historical-data",
        price_currency="CNY",
        price_unit="kg",
        publish_lag_assumption_days=3,
        is_active_for_v1=True,
    ),
    "lead": PriceSourceRecord(
        normalized_mineral_id="lead",
        mineral_name="Lead",
        trackability_grade="direct",
        price_source_type="fred_series",
        price_symbol_or_series_id="PLEADUSDM",
        price_currency="USD",
        price_unit="metric ton",
        publish_lag_assumption_days=30,
        is_active_for_v1=True,
    ),
    "graphite": PriceSourceRecord(
        normalized_mineral_id="graphite",
        mineral_name="Graphite",
        trackability_grade="proxy",
        price_source_type="yfinance_futures",
        price_symbol_or_series_id="LIT",
        price_currency="USD",
        price_unit="etf_share",
        publish_lag_assumption_days=2,
        is_active_for_v1=True,
        proxy_target="lithium",
        proxy_type="etf",
        proxy_instrument="LIT",
        proxy_display_name="Global X Lithium & Battery Tech ETF",
    ),
    "indium": PriceSourceRecord(
        normalized_mineral_id="indium",
        mineral_name="Indium",
        trackability_grade="direct",
        price_source_type="investing_html",
        price_symbol_or_series_id="https://www.investing.com/commodities/indium-99.99-min-united-states-futures-historical-data",
        price_currency="USD",
        price_unit="kg",
        publish_lag_assumption_days=3,
        is_active_for_v1=True,
    ),
    "lithium": PriceSourceRecord(
        normalized_mineral_id="lithium",
        mineral_name="Lithium",
        trackability_grade="proxy",
        price_source_type="yfinance_futures",
        price_symbol_or_series_id="LIT",
        price_currency="USD",
        price_unit="etf_share",
        publish_lag_assumption_days=1,
        is_active_for_v1=True,
        proxy_type="etf",
        proxy_instrument="LIT",
        proxy_display_name="Global X Lithium & Battery Tech ETF",
    ),
    "manganese": PriceSourceRecord(
        normalized_mineral_id="manganese",
        mineral_name="Manganese",
        trackability_grade="proxy",
        price_source_type="yfinance_futures",
        price_symbol_or_series_id="S32.AX",
        price_currency="AUD",
        price_unit="equity_proxy",
        publish_lag_assumption_days=1,
        is_active_for_v1=True,
        proxy_target="south32_producer_equity",
        proxy_type="producer_equity",
        proxy_instrument="S32.AX",
        proxy_display_name="South32 Ltd",
    ),
    "molybdenum": PriceSourceRecord(
        normalized_mineral_id="molybdenum",
        mineral_name="Molybdenum",
        trackability_grade="direct",
        price_source_type="investing_html",
        price_symbol_or_series_id="https://www.investing.com/commodities/molybdenum-bar-99.9-min-china-futures-historical-data",
        price_currency="CNY",
        price_unit="ton",
        publish_lag_assumption_days=3,
        is_active_for_v1=True,
    ),
    "neodymium": PriceSourceRecord(
        normalized_mineral_id="neodymium",
        mineral_name="Neodymium",
        trackability_grade="proxy",
        price_source_type="yfinance_futures",
        price_symbol_or_series_id="REMX",
        price_currency="USD",
        price_unit="etf_share",
        publish_lag_assumption_days=1,
        is_active_for_v1=True,
        proxy_type="etf",
        proxy_instrument="REMX",
        proxy_display_name="VanEck Rare Earth/Strategic Metals ETF",
    ),
    "nickel": PriceSourceRecord(
        normalized_mineral_id="nickel",
        mineral_name="Nickel",
        trackability_grade="direct",
        price_source_type="yfinance_futures",
        price_symbol_or_series_id="NIY=F",
        price_currency="USD",
        price_unit="metric ton",
        publish_lag_assumption_days=1,
        is_active_for_v1=True,
    ),
    "palladium": PriceSourceRecord(
        normalized_mineral_id="palladium",
        mineral_name="Palladium",
        trackability_grade="direct",
        price_source_type="yfinance_futures",
        price_symbol_or_series_id="PA=F",
        price_currency="USD",
        price_unit="oz",
        publish_lag_assumption_days=1,
        is_active_for_v1=True,
    ),
    "platinum": PriceSourceRecord(
        normalized_mineral_id="platinum",
        mineral_name="Platinum",
        trackability_grade="direct",
        price_source_type="yfinance_futures",
        price_symbol_or_series_id="PL=F",
        price_currency="USD",
        price_unit="oz",
        publish_lag_assumption_days=1,
        is_active_for_v1=True,
    ),
    "silver": PriceSourceRecord(
        normalized_mineral_id="silver",
        mineral_name="Silver",
        trackability_grade="direct",
        price_source_type="yfinance_futures",
        price_symbol_or_series_id="SI=F",
        price_currency="USD",
        price_unit="oz",
        publish_lag_assumption_days=1,
        is_active_for_v1=True,
    ),
    "silicon": PriceSourceRecord(
        normalized_mineral_id="silicon",
        mineral_name="Silicon",
        trackability_grade="proxy",
        price_source_type="yfinance_futures",
        price_symbol_or_series_id="GSM",
        price_currency="USD",
        price_unit="equity_proxy",
        publish_lag_assumption_days=1,
        is_active_for_v1=True,
        proxy_target="ferroglobe_producer_equity",
        proxy_type="producer_equity",
        proxy_instrument="GSM",
        proxy_display_name="Ferroglobe PLC",
    ),
    "tin": PriceSourceRecord(
        normalized_mineral_id="tin",
        mineral_name="Tin",
        trackability_grade="direct",
        price_source_type="fred_series",
        price_symbol_or_series_id="PTINUSDM",
        price_currency="USD",
        price_unit="metric ton",
        publish_lag_assumption_days=30,
        is_active_for_v1=True,
    ),
    "tantalum": PriceSourceRecord(
        normalized_mineral_id="tantalum",
        mineral_name="Tantalum",
        trackability_grade="proxy",
        price_source_type="yfinance_futures",
        price_symbol_or_series_id="AMG.AS",
        price_currency="EUR",
        price_unit="equity_proxy",
        publish_lag_assumption_days=1,
        is_active_for_v1=True,
        proxy_target="amg_producer_equity",
        proxy_type="producer_equity",
        proxy_instrument="AMG.AS",
        proxy_display_name="AMG Critical Materials N.V.",
    ),
    "uranium": PriceSourceRecord(
        normalized_mineral_id="uranium",
        mineral_name="Uranium",
        trackability_grade="proxy",
        price_source_type="yfinance_futures",
        price_symbol_or_series_id="URA",
        price_currency="USD",
        price_unit="etf_share",
        publish_lag_assumption_days=1,
        is_active_for_v1=True,
        proxy_type="etf",
        proxy_instrument="URA",
        proxy_display_name="Global X Uranium ETF",
    ),
    "vanadium": PriceSourceRecord(
        normalized_mineral_id="vanadium",
        mineral_name="Vanadium",
        trackability_grade="proxy",
        price_source_type="yfinance_futures",
        price_symbol_or_series_id="LGO",
        price_currency="USD",
        price_unit="equity_proxy",
        publish_lag_assumption_days=1,
        is_active_for_v1=True,
        proxy_target="largo_producer_equity",
        proxy_type="producer_equity",
        proxy_instrument="LGO",
        proxy_display_name="Largo Inc.",
    ),
    "zinc": PriceSourceRecord(
        normalized_mineral_id="zinc",
        mineral_name="Zinc",
        trackability_grade="direct",
        price_source_type="fred_series",
        price_symbol_or_series_id="PZINCUSDM",
        price_currency="USD",
        price_unit="metric ton",
        publish_lag_assumption_days=30,
        is_active_for_v1=True,
    ),
}


def normalize_mineral_id(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")


def normalize_ticker(value: str) -> tuple[str, str]:
    token = value.strip().upper()
    if _A_SHARE_PATTERN.fullmatch(token):
        return token, "CN_A"
    if _HK_PATTERN.fullmatch(token):
        return token.zfill(7) if token.endswith(".HK") and len(token.split(".")[0]) < 4 else token, "HK"
    return token, "US"


def _coerce_bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.map(lambda value: str(value).strip().lower() in {"true", "1", "yes"})


def load_critical_minerals(workbook_path: str | Path) -> pd.DataFrame:
    path = Path(workbook_path)
    if path.suffix.lower() == ".csv":
        # Already-normalized reference CSV: columns match the post-rename schema.
        frame = pd.read_csv(path).copy()
    else:
        frame = pd.read_excel(path, sheet_name=CRITICAL_MINERALS_SHEET).rename(
            columns={
                "Importance rank (computed)": "importance_rank",
                "Importance tier": "importance_tier",
                "Mineral": "mineral_name",
                "2025 U.S. net import reliance": "net_import_reliance_2025",
                "NIR_numeric_for_sort": "net_import_reliance_numeric",
                "Strategic application bucket": "strategic_application_bucket",
                "Applications (USGS Table 6)": "applications",
                "Source / note": "source_note",
            }
        ).copy()
    if "normalized_mineral_id" not in frame.columns:
        frame["normalized_mineral_id"] = frame["mineral_name"].map(normalize_mineral_id)
    frame["importance_rank"] = frame["importance_rank"].astype("Int64")
    return frame


def build_price_universe(minerals: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for row in minerals.itertuples(index=False):
        mineral_id = row.normalized_mineral_id
        mapped = PRICE_SOURCE_DEFAULTS.get(mineral_id)
        if mapped is None:
            mapped = PriceSourceRecord(
                normalized_mineral_id=mineral_id,
                mineral_name=row.mineral_name,
                trackability_grade="unsupported",
                price_source_type="manual_proxy",
                price_symbol_or_series_id=None,
                price_currency=None,
                price_unit=None,
                publish_lag_assumption_days=5,
                is_active_for_v1=False,
            )
        record = mapped.to_dict()
        record["mineral_name"] = row.mineral_name
        records.append(record)
    return pd.DataFrame(records).sort_values(["trackability_grade", "normalized_mineral_id"]).reset_index(drop=True)


def load_expanded_stock_mapping(workbook_path: str | Path) -> pd.DataFrame:
    path = Path(workbook_path)
    if path.suffix.lower() == ".csv":
        # Already-exploded reference CSV (one row per ticker); pass through.
        frame = pd.read_csv(path).copy()
        if "normalized_mineral_id" not in frame.columns:
            frame["normalized_mineral_id"] = frame["mineral_name"].map(normalize_mineral_id)
        frame["is_primary_exposure"] = _coerce_bool_series(frame["is_primary_exposure"])
        return frame.sort_values(
            ["normalized_mineral_id", "market", "ticker_normalized"]
        ).reset_index(drop=True)

    frame = pd.read_excel(path, sheet_name=STOCK_MAPPING_SHEET)
    frame = frame.rename(
        columns={
            "Importance rank": "importance_rank",
            "Tier": "importance_tier",
            "Mineral": "mineral_name",
            "2025 U.S. net import reliance": "net_import_reliance_2025",
            "Applications": "applications",
            "Strategic application bucket": "strategic_application_bucket",
            "China A-share / HK related stocks": "cn_hk_stocks",
            "US-listed related stocks": "us_stocks",
            "Exposure purity": "exposure_purity",
            "Mapping note": "mapping_note",
            "Source URL / evidence": "source_url",
        }
    ).copy()
    frame["normalized_mineral_id"] = frame["mineral_name"].map(normalize_mineral_id)

    rows: list[dict[str, object]] = []
    for row in frame.itertuples(index=False):
        rows.extend(_explode_stock_cell(row, row.cn_hk_stocks, preferred_market=None))
        rows.extend(_explode_stock_cell(row, row.us_stocks, preferred_market="US"))

    return pd.DataFrame(rows).sort_values(
        ["normalized_mineral_id", "market", "ticker_normalized"]
    ).reset_index(drop=True)


def _explode_stock_cell(row: object, cell_value: object, *, preferred_market: str | None) -> list[dict[str, object]]:
    if not isinstance(cell_value, str) or not cell_value.strip():
        return []

    tickers = _extract_tickers(cell_value, preferred_market=preferred_market)
    rows: list[dict[str, object]] = []
    for ticker_raw in tickers:
        ticker_normalized, market = normalize_ticker(ticker_raw)
        rows.append(
            {
                "mineral_name": row.mineral_name,
                "normalized_mineral_id": row.normalized_mineral_id,
                "ticker_raw": ticker_raw,
                "ticker_normalized": ticker_normalized,
                "market": market if preferred_market is None else market,
                "exposure_purity": row.exposure_purity,
                "mapping_note": row.mapping_note,
                "is_primary_exposure": _is_primary_ticker(row.exposure_purity, ticker_raw),
                "importance_rank": row.importance_rank,
                "importance_tier": row.importance_tier,
            }
        )
    return rows


def _extract_tickers(text: str, *, preferred_market: str | None) -> list[str]:
    candidates: list[str] = []
    for pattern in (_A_SHARE_PATTERN, _HK_PATTERN):
        candidates.extend(match.group(0).upper() for match in pattern.finditer(text))
    cleaned_text = re.sub(_A_SHARE_PATTERN, " ", text)
    cleaned_text = re.sub(_HK_PATTERN, " ", cleaned_text)

    if preferred_market == "US" or ("US-LISTED" in text.upper()) or not candidates:
        candidates.extend(
            token
            for token in _US_PATTERN.findall(cleaned_text)
            if token not in {"NO", "US", "HK", "A", "SHARE", "LISTED", "PRODUCER"}
        )

    deduped: list[str] = []
    seen: set[str] = set()
    for ticker in candidates:
        normalized = ticker.upper().strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def _is_primary_ticker(exposure_purity: object, ticker: str) -> bool:
    if not isinstance(exposure_purity, str):
        return False
    text = exposure_purity.upper()
    normalized = ticker.upper().replace(".SZ", "").replace(".SH", "").replace(".BJ", "").replace(".HK", "")
    primary_chunks = [match.group("body").upper() for match in _PRIMARY_CONTEXT_PATTERN.finditer(exposure_purity)]
    if primary_chunks:
        return any(normalized in re.findall(r"[A-Z0-9]+", chunk) for chunk in primary_chunks)
    if "PRIMARY/SECONDARY" in text:
        return True
    if "PRIMARY" in text and not _SECONDARY_CONTEXT_PATTERN.search(text):
        return True
    return False
