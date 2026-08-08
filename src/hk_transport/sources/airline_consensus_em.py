"""Current free Eastmoney/AkShare EPS and rating-count snapshot for airlines."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR
from .airline_financials import A_SHARE_AIRLINES, _fx_asof


OUTPUT_PATH = NORMALIZED_DIR / "airline_consensus_em_snapshot.csv"
SOURCE_URL = "https://data.eastmoney.com/report/profitforecast.jshtml"

OUTPUT_COLUMNS = [
    "dataset_id", "ticker", "company", "snapshot_date", "fiscal_year",
    "eps_avg_native", "eps_avg_usd_at_snapshot", "eps_currency",
    "research_report_count_6m", "rating_buy_count", "rating_add_count",
    "rating_neutral_count", "rating_reduce_count", "rating_sell_count",
    "rating_total_count", "buy_add_pct", "source_quality", "source_url",
    "revision_history_available", "source_note", "retrieved_at",
]


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def normalize_em_profit_forecast(
    frame: pd.DataFrame,
    *,
    fx_rates: pd.DataFrame | None = None,
    snapshot_date: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Normalize the current Eastmoney aggregate for the six airline names."""
    required = {
        "代码", "名称", "研报数", "机构投资评级(近六个月)-买入",
        "机构投资评级(近六个月)-增持", "机构投资评级(近六个月)-中性",
        "机构投资评级(近六个月)-减持", "机构投资评级(近六个月)-卖出",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Eastmoney forecast is missing columns: {sorted(missing)}")
    snap = snapshot_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    metadata_by_symbol = {symbol: metadata for symbol, metadata in A_SHARE_AIRLINES.items()}
    for symbol, metadata in metadata_by_symbol.items():
        source = frame.loc[frame["代码"].astype(str).str.zfill(6).eq(symbol)].copy()
        if source.empty:
            continue
        source_row = source.iloc[0]
        fx_date, fx_value = _fx_asof(fx_rates, pair="USD_CNY", as_of=pd.Timestamp(snap))
        rating_columns = {
            "rating_buy_count": "机构投资评级(近六个月)-买入",
            "rating_add_count": "机构投资评级(近六个月)-增持",
            "rating_neutral_count": "机构投资评级(近六个月)-中性",
            "rating_reduce_count": "机构投资评级(近六个月)-减持",
            "rating_sell_count": "机构投资评级(近六个月)-卖出",
        }
        ratings = {key: _number(source_row.get(column)) for key, column in rating_columns.items()}
        total_ratings = sum(value or 0 for value in ratings.values())
        buy_add = (ratings["rating_buy_count"] or 0) + (ratings["rating_add_count"] or 0)
        for year in (2025, 2026, 2027, 2028):
            eps = _number(source_row.get(f"{year}预测每股收益"))
            if eps is None and year != 2026:
                continue
            rows.append({
                "dataset_id": "airline_consensus_em",
                "ticker": metadata["ticker"],
                "company": metadata["company"],
                "snapshot_date": snap,
                "fiscal_year": year,
                "eps_avg_native": eps,
                "eps_avg_usd_at_snapshot": eps / fx_value if eps is not None and fx_value else None,
                "eps_currency": "RMB/share",
                "research_report_count_6m": _number(source_row.get("研报数")),
                **ratings,
                "rating_total_count": total_ratings,
                "buy_add_pct": 100.0 * buy_add / total_ratings if total_ratings else None,
                "source_quality": "akshare_discovery",
                "source_url": SOURCE_URL,
                "revision_history_available": False,
                "source_note": (
                    "Current Eastmoney profit-forecast aggregate retrieved through AkShare. "
                    "Rating counts cover the latest six months; EPS is a current aggregate, "
                    f"not a historical broker-vintage series. USD EPS uses USD/CNY as of {fx_date or 'unavailable'}."
                ),
                "retrieved_at": retrieved,
            })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_consensus_em() -> pd.DataFrame:
    try:
        import akshare as ak
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("akshare is required for the Eastmoney airline consensus layer") from exc
    frame = ak.stock_profit_forecast_em()
    result = normalize_em_profit_forecast(
        frame,
        fx_rates=pd.read_parquet(NORMALIZED_DIR / "airline_fx_rates.parquet")
        if (NORMALIZED_DIR / "airline_fx_rates.parquet").exists()
        else None,
    )
    if OUTPUT_PATH.exists():
        prior = pd.read_csv(OUTPUT_PATH)
        result = merge_em_consensus_history(prior, result)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def merge_em_consensus_history(prior: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """Append current snapshots while replacing only the same PIT key."""
    result = pd.concat([prior, current], ignore_index=True)
    if result.empty:
        return result
    key = ["ticker", "snapshot_date", "fiscal_year"]
    result = result.drop_duplicates(key, keep="last")
    return result.sort_values(key).reset_index(drop=True)


def source_path() -> Path:
    return OUTPUT_PATH
