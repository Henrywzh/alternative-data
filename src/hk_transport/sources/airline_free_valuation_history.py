"""Free historical valuation coverage for the airline long/short workstream.

This module deliberately excludes subscription-only providers.  It captures
the free AKShare/Baidu dated valuation series that are directly exposed for
PE, P/B and market capitalisation, and records the free Eastmoney current
P/S/P/E/P/B comparison separately.  It does not silently turn a current
multiple into historical data: every observation carries its provider,
basis, and point-in-time status.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


HISTORY_OUTPUT_PATH = NORMALIZED_DIR / "airline_free_valuation_history.csv"
CURRENT_OUTPUT_PATH = NORMALIZED_DIR / "airline_free_current_valuation.csv"
MATRIX_OUTPUT_PATH = NORMALIZED_DIR / "airline_valuation_source_matrix.csv"


AIRLINE_CONFIG: dict[str, dict[str, str]] = {
    "0293.HK": {
        "company": "Cathay Pacific",
        "market": "HK",
        "baidu_function": "stock_hk_valuation_baidu",
        "baidu_symbol": "00293",
        "eastmoney_function": "stock_hk_valuation_comparison_em",
        "eastmoney_symbol": "00293",
    },
    "01055.HK": {
        "company": "China Southern Airlines",
        "market": "HK",
        "baidu_function": "stock_hk_valuation_baidu",
        "baidu_symbol": "01055",
        "eastmoney_function": "stock_hk_valuation_comparison_em",
        "eastmoney_symbol": "01055",
    },
    "0670.HK": {
        "company": "China Eastern Airlines",
        "market": "HK",
        "baidu_function": "stock_hk_valuation_baidu",
        "baidu_symbol": "00670",
        "eastmoney_function": "stock_hk_valuation_comparison_em",
        "eastmoney_symbol": "00670",
    },
    "0753.HK": {
        "company": "Air China",
        "market": "HK",
        "baidu_function": "stock_hk_valuation_baidu",
        "baidu_symbol": "00753",
        "eastmoney_function": "stock_hk_valuation_comparison_em",
        "eastmoney_symbol": "00753",
    },
    "600221.SH": {
        "company": "Hainan Airlines Holdings",
        "market": "CN_A",
        "baidu_function": "stock_zh_valuation_baidu",
        "baidu_symbol": "600221",
        "eastmoney_function": "stock_zh_valuation_comparison_em",
        "eastmoney_symbol": "SH600221",
    },
    "601021.SH": {
        "company": "Spring Airlines",
        "market": "CN_A",
        "baidu_function": "stock_zh_valuation_baidu",
        "baidu_symbol": "601021",
        "eastmoney_function": "stock_zh_valuation_comparison_em",
        "eastmoney_symbol": "SH601021",
    },
    "603885.SH": {
        "company": "Juneyao Airlines",
        "market": "CN_A",
        "baidu_function": "stock_zh_valuation_baidu",
        "baidu_symbol": "603885",
        "eastmoney_function": "stock_zh_valuation_comparison_em",
        "eastmoney_symbol": "SH603885",
    },
}


DIRECT_INDICATORS: dict[str, str] = {
    "pe_ttm": "市盈率(TTM)",
    "pe_static": "市盈率(静)",
    "pb": "市净率",
    "market_cap": "总市值",
}

HISTORY_COLUMNS = [
    "dataset_id", "asset", "company", "market", "observation_date",
    "metric", "value", "basis", "provider_function", "provider_indicator",
    "provider_period", "source_quality", "point_in_time_status",
    "source_url", "source_note", "retrieved_at",
]

CURRENT_COLUMNS = [
    "dataset_id", "asset", "company", "market", "observation_date",
    "metric", "value", "basis", "provider_function", "source_quality",
    "point_in_time_status", "source_url", "source_note", "retrieved_at",
]

MATRIX_COLUMNS = [
    "dataset_id", "asset", "company", "market", "metric", "source_route",
    "direct_history_available", "current_snapshot_available", "observation_count",
    "observation_start_date", "observation_end_date", "positive_value_count",
    "non_positive_value_count", "missing_value_count", "coverage_status",
    "point_in_time_status", "next_action", "source_quality", "source_url",
    "retrieved_at",
]


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _history_source_url(config: dict[str, str], indicator: str, period: str) -> str:
    return (
        f"akshare.{config['baidu_function']}"
        f"(symbol={config['baidu_symbol']}, indicator={indicator}, period={period})"
    )


def _current_source_url(config: dict[str, str]) -> str:
    return f"akshare.{config['eastmoney_function']}(symbol={config['eastmoney_symbol']})"


def _current_column_map(market: str) -> dict[str, str]:
    if market == "HK":
        return {
            "市盈率-TTM": "pe_ttm",
            "市盈率-LYR": "pe_static",
            "市净率-MRQ": "pb",
            "市净率-LYR": "pb_ltm",
            "市销率-TTM": "ps_ttm",
            "市销率-LYR": "ps_ltm",
        }
    return {
        "市盈率-TTM": "pe_ttm",
        "市盈率-25E": "pe_fy2025e",
        "市盈率-26E": "pe_fy2026e",
        "市盈率-27E": "pe_fy2027e",
        "市销率-TTM": "ps_ttm",
        "市销率-24A": "ps_fy2024a",
        "市销率-25E": "ps_fy2025e",
        "市销率-26E": "ps_fy2026e",
        "市销率-27E": "ps_fy2027e",
        "市净率-MRQ": "pb",
        "市净率-24A": "pb_fy2024a",
    }


def build_airline_valuation_source_matrix(
    *,
    history: pd.DataFrame | None = None,
    current: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build a per-asset/per-metric coverage and PIT status matrix."""

    history = history if history is not None else pd.DataFrame(columns=HISTORY_COLUMNS)
    current = current if current is not None else pd.DataFrame(columns=CURRENT_COLUMNS)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    for asset, config in AIRLINE_CONFIG.items():
        for metric in (*DIRECT_INDICATORS.keys(), "ps_ttm"):
            hist = history.loc[
                history.get("asset", pd.Series(dtype=str)).eq(asset)
                & history.get("metric", pd.Series(dtype=str)).eq(metric)
            ].copy()
            values = pd.to_numeric(hist.get("value"), errors="coerce") if not hist.empty else pd.Series(dtype=float)
            dates = pd.to_datetime(hist.get("observation_date"), errors="coerce") if not hist.empty else pd.Series(dtype="datetime64[ns]")
            current_rows = current.loc[
                current.get("asset", pd.Series(dtype=str)).eq(asset)
                & current.get("metric", pd.Series(dtype=str)).eq(metric)
            ] if not current.empty else pd.DataFrame()
            direct_history = metric in DIRECT_INDICATORS and not hist.empty
            current_available = not current_rows.empty
            if metric == "ps_ttm":
                route = "eastmoney_current_then_free_reconstruction"
                next_action = "Use current Eastmoney PS; construct dated PS from free market_cap_and_announcement_aligned_revenue"
                pit_status = "current_snapshot_only_until_reconstructed"
                quality = "free_eastmoney_current_only" if current_available else "free_source_not_available"
                coverage = "current_only" if current_available else "missing"
            else:
                route = "akshare_baidu_dated_history"
                next_action = "Validate provider denominator semantics and join to announcement-aligned financials"
                pit_status = "vendor_dated_market_cap_history" if metric == "market_cap" else "vendor_dated_ratio_denominator_semantics_unverified"
                quality = "akshare_baidu_valuation_history" if direct_history else "free_source_fetch_failed"
                coverage = "dated_history" if direct_history else "missing"
            valid_values = values.dropna()
            valid_dates = dates.dropna()
            rows.append(
                {
                    "dataset_id": "airline_valuation_source_matrix",
                    "asset": asset,
                    "company": config["company"],
                    "market": config["market"],
                    "metric": metric,
                    "source_route": route,
                    "direct_history_available": bool(direct_history),
                    "current_snapshot_available": bool(current_available),
                    "observation_count": int(len(valid_values)),
                    "observation_start_date": valid_dates.min().date().isoformat() if not valid_dates.empty else None,
                    "observation_end_date": valid_dates.max().date().isoformat() if not valid_dates.empty else None,
                    "positive_value_count": int((valid_values > 0).sum()),
                    "non_positive_value_count": int((valid_values <= 0).sum()),
                    "missing_value_count": int(values.isna().sum()) if not values.empty else 0,
                    "coverage_status": coverage,
                    "point_in_time_status": pit_status,
                    "next_action": next_action,
                    "source_quality": quality,
                    "source_url": _current_source_url(config) if metric == "ps_ttm" else _history_source_url(config, DIRECT_INDICATORS[metric], "全部"),
                    "retrieved_at": retrieved,
                }
            )
    return pd.DataFrame(rows, columns=MATRIX_COLUMNS)


def _fetch_baidu_history(*, ak: Any, asset: str, config: dict[str, str], retrieved: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    function = getattr(ak, config["baidu_function"])
    for metric, indicator in DIRECT_INDICATORS.items():
        period = "全部"
        try:
            frame = function(symbol=config["baidu_symbol"], indicator=indicator, period=period)
        except Exception:
            # Keep the fallback explicit in the observation metadata.  Some
            # public mirrors intermittently reject the "全部" period.
            period = "近三年"
            try:
                frame = function(symbol=config["baidu_symbol"], indicator=indicator, period=period)
            except Exception:
                frame = pd.DataFrame()
        if frame is None or frame.empty or not {"date", "value"}.issubset(frame.columns):
            continue
        for _, item in frame.iterrows():
            date = pd.to_datetime(item.get("date"), errors="coerce")
            value = _num(item.get("value"))
            if pd.isna(date) or value is None:
                continue
            rows.append(
                {
                    "dataset_id": "airline_free_valuation_history",
                    "asset": asset,
                    "company": config["company"],
                    "market": config["market"],
                    "observation_date": date.date().isoformat(),
                    "metric": metric,
                    "value": value,
                    "basis": "provider_defined_baidu_indicator",
                    "provider_function": config["baidu_function"],
                    "provider_indicator": indicator,
                    "provider_period": period,
                    "source_quality": "akshare_baidu_valuation_history",
                    "point_in_time_status": "vendor_dated_market_cap_history" if metric == "market_cap" else "vendor_dated_ratio_denominator_semantics_unverified",
                    "source_url": _history_source_url(config, indicator, period),
                    "source_note": "Free provider historical valuation observation; not yet announcement-aligned for thesis fair-value use.",
                    "retrieved_at": retrieved,
                }
            )
    return rows


def _fetch_eastmoney_current(*, ak: Any, asset: str, config: dict[str, str], retrieved: str) -> list[dict[str, Any]]:
    function = getattr(ak, config["eastmoney_function"])
    try:
        frame = function(symbol=config["eastmoney_symbol"])
    except Exception:
        return []
    if frame is None or frame.empty:
        return []
    code_col = "代码" if "代码" in frame.columns else None
    if code_col:
        target = config["eastmoney_symbol"].replace("SH", "").replace("SZ", "")
        exact = frame.loc[frame[code_col].astype(str).str.replace(".0", "", regex=False).eq(target)]
        if not exact.empty:
            frame = exact
    row = frame.iloc[0]
    rows: list[dict[str, Any]] = []
    for provider_column, metric in _current_column_map(config["market"]).items():
        if provider_column not in row.index:
            continue
        value = _num(row.get(provider_column))
        if value is None:
            continue
        rows.append(
            {
                "dataset_id": "airline_free_current_valuation",
                "asset": asset,
                "company": config["company"],
                "market": config["market"],
                "observation_date": retrieved[:10],
                "metric": metric,
                "value": value,
                "basis": provider_column,
                "provider_function": config["eastmoney_function"],
                "source_quality": "akshare_eastmoney_current_comparison",
                "point_in_time_status": "current_snapshot_only",
                "source_url": _current_source_url(config),
                "source_note": "Free Eastmoney comparison snapshot; not a historical daily valuation series.",
                "retrieved_at": retrieved,
            }
        )
    return rows


def fetch_airline_free_valuation_history() -> pd.DataFrame:
    """Fetch free historical PE/PB/market-cap and current free P/S layers."""

    import akshare as ak

    retrieved = datetime.now(timezone.utc).isoformat()
    history_rows: list[dict[str, Any]] = []
    current_rows: list[dict[str, Any]] = []
    for asset, config in AIRLINE_CONFIG.items():
        history_rows.extend(_fetch_baidu_history(ak=ak, asset=asset, config=config, retrieved=retrieved))
        current_rows.extend(_fetch_eastmoney_current(ak=ak, asset=asset, config=config, retrieved=retrieved))
    history = pd.DataFrame(history_rows, columns=HISTORY_COLUMNS)
    current = pd.DataFrame(current_rows, columns=CURRENT_COLUMNS)
    matrix = build_airline_valuation_source_matrix(history=history, current=current, retrieved_at=retrieved)
    history.to_csv(HISTORY_OUTPUT_PATH, index=False)
    current.to_csv(CURRENT_OUTPUT_PATH, index=False)
    matrix.to_csv(MATRIX_OUTPUT_PATH, index=False)
    return matrix


def source_paths() -> tuple[Any, Any, Any]:
    return HISTORY_OUTPUT_PATH, CURRENT_OUTPUT_PATH, MATRIX_OUTPUT_PATH
