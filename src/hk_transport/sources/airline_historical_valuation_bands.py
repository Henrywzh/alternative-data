"""Construct free annual P/S history and valuation-band diagnostics.

The free provider exposes long dated market-cap, P/E and P/B observations but
not a long dated P/S series.  This module uses the free market-cap series and
the existing free financial-history revenue rows to construct a transparent
annual-revenue P/S proxy.  It is deliberately labelled period-end-only unless
an issuer announcement date is available and precedes the market observation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


FREE_HISTORY_PATH = NORMALIZED_DIR / "airline_free_valuation_history.csv"
FREE_CURRENT_PATH = NORMALIZED_DIR / "airline_free_current_valuation.csv"
FINANCIAL_HISTORY_PATH = NORMALIZED_DIR / "airline_financial_history_trend.csv"
COMPARABILITY_PATH = NORMALIZED_DIR / "airline_earnings_driver_comparability.csv"
OFFICIAL_DRIVERS_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
FX_PATH = NORMALIZED_DIR / "airline_fx_rates.parquet"
CONSTRUCTED_OUTPUT_PATH = NORMALIZED_DIR / "airline_free_constructed_ps_history.csv"
BANDS_OUTPUT_PATH = NORMALIZED_DIR / "airline_historical_valuation_bands.csv"
RECONCILIATION_OUTPUT_PATH = NORMALIZED_DIR / "airline_valuation_reconciliation_audit.csv"


ASSET_COMPANY = {
    "0293.HK": ("Cathay Pacific", "HK", "HKD"),
    "01055.HK": ("China Southern Airlines", "HK", "HKD"),
    "0670.HK": ("China Eastern Airlines", "HK", "HKD"),
    "0753.HK": ("Air China", "HK", "HKD"),
    "600221.SH": ("Hainan Airlines Holdings", "CN_A", "RMB"),
    "601021.SH": ("Spring Airlines", "CN_A", "RMB"),
    "603885.SH": ("Juneyao Airlines", "CN_A", "RMB"),
}

CONSTRUCTED_COLUMNS = [
    "dataset_id", "asset", "company", "market", "observation_date",
    "metric", "value", "basis", "market_cap_provider_value",
    "market_cap_native_mn", "market_cap_currency", "revenue_native_mn",
    "revenue_currency", "revenue_period_end", "revenue_announced_at",
    "fx_pair", "fx_value", "point_in_time_status", "source_quality",
    "source_paths", "source_note", "retrieved_at",
]

BANDS_COLUMNS = [
    "dataset_id", "asset", "company", "market", "metric", "window",
    "as_of_date", "window_start_date", "observation_count",
    "positive_observation_count", "non_positive_observation_count",
    "excluded_pre_announcement_count",
    "min_value", "p25_value", "median_value", "p75_value", "max_value",
    "current_value", "current_basis", "current_source",
    "current_percentile_positive", "point_in_time_status", "source_quality",
    "source_paths", "retrieved_at",
]

RECONCILIATION_COLUMNS = [
    "dataset_id", "asset", "company", "metric", "direct_value", "direct_basis",
    "direct_observation_date", "dated_value", "dated_basis", "dated_observation_date",
    "relative_difference_pct", "comparison_status", "point_in_time_status",
    "source_paths", "retrieved_at",
]


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _nearest_prior_fx(fx: pd.DataFrame, pair: str, date: pd.Timestamp) -> float | None:
    if fx.empty:
        return None
    frame = fx.loc[fx["pair"].eq(pair)].copy()
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.loc[frame["observation_date"].le(date)].dropna(subset=["observation_date", "value"])
    return _num(frame.sort_values("observation_date").iloc[-1]["value"]) if not frame.empty else None


def _annual_revenue_rows(
    financial_history: pd.DataFrame,
    official_drivers: pd.DataFrame,
    comparability_drivers: pd.DataFrame | None = None,
) -> pd.DataFrame:
    frame = financial_history.copy()
    frame = frame.loc[
        frame.get("metric", pd.Series(dtype=str)).eq("total_revenue")
        & frame.get("period_type", pd.Series(dtype=str)).eq("FY")
    ].copy()
    comparability_drivers = comparability_drivers if comparability_drivers is not None else pd.DataFrame()
    if not comparability_drivers.empty and {"company", "canonical_metric", "statement_period", "period_end", "value_native"}.issubset(comparability_drivers.columns):
        cathay = comparability_drivers.loc[
            comparability_drivers["company"].eq("Cathay Pacific")
            & comparability_drivers["canonical_metric"].eq("total_revenue")
            & comparability_drivers["statement_period"].eq("FY2025")
        ].copy()
        if not cathay.empty:
            cathay = cathay.rename(columns={"information_date": "announced_at"})
            cathay["metric"] = "total_revenue"
            cathay["period_type"] = "FY"
            cathay["value_native"] = pd.to_numeric(cathay["value_native"], errors="coerce")
            cathay["period_end"] = pd.to_datetime(cathay["period_end"], errors="coerce")
            cathay["announced_at"] = pd.to_datetime(cathay.get("announced_at"), errors="coerce")
            cathay = cathay[["company", "period_type", "period_end", "metric", "value_native", "native_currency", "announced_at"]]
            frame = pd.concat([frame, cathay], ignore_index=True, sort=False)
    if frame.empty:
        return pd.DataFrame()
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="coerce")
    frame["value_native"] = pd.to_numeric(frame["value_native"], errors="coerce")
    frame = frame.dropna(subset=["period_end", "value_native"])
    frame = frame.loc[frame["value_native"].gt(0)]
    if "announced_at" not in frame.columns:
        frame["announced_at"] = None
    if not official_drivers.empty:
        drivers = official_drivers.loc[official_drivers["metric"].eq("total_revenue")].copy()
        drivers["period_end"] = pd.to_datetime(drivers["period_end"], errors="coerce")
        drivers["announced_at"] = pd.to_datetime(drivers["announced_at"], errors="coerce")
        announcement = drivers[["company", "period_end", "announced_at"]].drop_duplicates()
        frame = frame.merge(announcement, on=["company", "period_end"], how="left", suffixes=("", "_official"))
        frame["announced_at"] = frame["announced_at_official"].combine_first(frame["announced_at"])
        frame = frame.drop(columns=["announced_at_official"])
    return frame.sort_values(["company", "period_end"])


def build_airline_free_constructed_ps_history(
    *,
    free_history: pd.DataFrame,
    financial_history: pd.DataFrame,
    official_drivers: pd.DataFrame | None = None,
    comparability_drivers: pd.DataFrame | None = None,
    fx_rates: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build an annual-revenue P/S series from free inputs."""

    official_drivers = official_drivers if official_drivers is not None else pd.DataFrame()
    fx_rates = fx_rates if fx_rates is not None else pd.DataFrame()
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    market = free_history.loc[free_history["metric"].eq("market_cap")].copy()
    market["observation_date"] = pd.to_datetime(market["observation_date"], errors="coerce")
    market["value"] = pd.to_numeric(market["value"], errors="coerce")
    market = market.dropna(subset=["observation_date", "value"])
    revenue = _annual_revenue_rows(financial_history, official_drivers, comparability_drivers)
    rows: list[dict[str, Any]] = []
    for asset, (company, market_name, market_currency) in ASSET_COMPANY.items():
        market_rows = market.loc[market["asset"].eq(asset)].sort_values("observation_date")
        company_revenue = revenue.loc[revenue["company"].eq(company)]
        for _, market_row in market_rows.iterrows():
            observation_date = pd.Timestamp(market_row["observation_date"])
            prior = company_revenue.loc[company_revenue["period_end"].le(observation_date)]
            if prior.empty:
                continue
            revenue_row = prior.iloc[-1]
            revenue_native_mn = _num(revenue_row.get("value_native"))
            provider_market_cap = _num(market_row.get("value"))
            if revenue_native_mn is None or provider_market_cap is None:
                continue
            # Baidu valuation history returns market cap in 100-million local
            # currency units; this factor is cross-checked against the current
            # airline_market_snapshot native-million values.
            market_cap_native_mn = provider_market_cap * 100.0
            revenue_currency = _text(revenue_row.get("native_currency")) or "RMB"
            fx_pair = ""
            fx_value = 1.0
            numerator_rmb_mn = market_cap_native_mn
            if market_currency == "HKD" and revenue_currency == "HKD":
                # Cathay's market cap and official revenue are both HKD;
                # do not apply the HKD-to-RMB conversion used for H-share
                # market caps against mainland RMB provider revenue.
                numerator_rmb_mn = market_cap_native_mn
            elif market_currency == "HKD":
                usd_cny = _nearest_prior_fx(fx_rates, "USD_CNY", observation_date)
                usd_hkd = _nearest_prior_fx(fx_rates, "USD_HKD", observation_date)
                if usd_cny is None or usd_hkd in (None, 0):
                    continue
                fx_value = usd_cny / usd_hkd
                fx_pair = "HKD_RMB_derived_from_USD_CNY_USD_HKD"
                numerator_rmb_mn = market_cap_native_mn * fx_value
            ps = numerator_rmb_mn / revenue_native_mn if revenue_native_mn > 0 else None
            if ps is None:
                continue
            announced = pd.to_datetime(revenue_row.get("announced_at"), errors="coerce")
            if pd.notna(announced) and observation_date >= announced:
                pit_status = "announcement_aligned_for_available_report_date"
            elif pd.notna(announced):
                pit_status = "pre_announcement_lookahead"
            else:
                pit_status = "period_end_only_no_announcement_date"
            rows.append(
                {
                    "dataset_id": "airline_free_constructed_ps_history",
                    "asset": asset,
                    "company": company,
                    "market": market_name,
                    "observation_date": observation_date.date().isoformat(),
                    "metric": "ps_annual_period_end",
                    "value": ps,
                    "basis": "market_cap_divided_by_latest_annual_revenue",
                    "market_cap_provider_value": provider_market_cap,
                    "market_cap_native_mn": market_cap_native_mn,
                    "market_cap_currency": market_currency,
                    "revenue_native_mn": revenue_native_mn,
                    "revenue_currency": revenue_currency,
                    "revenue_period_end": revenue_row["period_end"].date().isoformat(),
                    "revenue_announced_at": announced.date().isoformat() if pd.notna(announced) else None,
                    "fx_pair": fx_pair,
                    "fx_value": fx_value,
                    "point_in_time_status": pit_status,
                    "source_quality": "free_market_cap_plus_free_financial_history",
                    "source_paths": f"{FREE_HISTORY_PATH};{FINANCIAL_HISTORY_PATH};{COMPARABILITY_PATH};{FX_PATH};{OFFICIAL_DRIVERS_PATH}",
                    "source_note": "Baidu market cap raw value multiplied by 100 to native million; HKD market cap is converted to RMB only when the revenue denominator is RMB, while Cathay HKD market cap is kept against Cathay HKD revenue. Annual revenue is provider period-end history, with Cathay FY2025 sourced from the canonical issuer-driver comparability layer; announcement alignment is available only where a source information date exists.",
                    "retrieved_at": retrieved,
                }
            )
    return pd.DataFrame(rows, columns=CONSTRUCTED_COLUMNS)


def _current_value(current: pd.DataFrame, asset: str, metric: str, fallback: pd.DataFrame) -> tuple[float | None, str, str]:
    if not current.empty:
        rows = current.loc[current["asset"].eq(asset) & current["metric"].eq(metric)].copy()
        if not rows.empty:
            if "observation_date" in rows.columns:
                rows["observation_date"] = pd.to_datetime(rows["observation_date"], errors="coerce")
                row = rows.sort_values("observation_date").iloc[-1]
            else:
                row = rows.iloc[-1]
            return _num(row.get("value")), _text(row.get("basis")), "airline_free_current_valuation.csv"
    rows = fallback.loc[fallback["asset"].eq(asset) & fallback["metric"].eq(metric)].copy()
    if rows.empty:
        return None, "", ""
    rows["observation_date"] = pd.to_datetime(rows["observation_date"], errors="coerce")
    row = rows.sort_values("observation_date").iloc[-1]
    return _num(row.get("value")), _text(row.get("basis")), "airline_free_valuation_history.csv"


def build_airline_historical_valuation_bands(
    *,
    free_history: pd.DataFrame,
    free_current: pd.DataFrame,
    constructed_ps: pd.DataFrame,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Create 1Y/3Y/5Y/all valuation bands for each priority market leg."""

    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    direct = free_history.loc[free_history["metric"].isin(["pe_ttm", "pb"])].copy()
    direct["observation_date"] = pd.to_datetime(direct["observation_date"], errors="coerce")
    direct["value"] = pd.to_numeric(direct["value"], errors="coerce")
    ps = constructed_ps.copy()
    if not ps.empty:
        ps["observation_date"] = pd.to_datetime(ps["observation_date"], errors="coerce")
        ps["value"] = pd.to_numeric(ps["value"], errors="coerce")
    series = pd.concat([direct, ps[["asset", "company", "market", "observation_date", "metric", "value", "point_in_time_status", "source_quality", "source_paths"]]], ignore_index=True, sort=False)
    series = series.dropna(subset=["observation_date", "value"])
    rows: list[dict[str, Any]] = []
    for asset, (company, market_name, _) in ASSET_COMPANY.items():
        for metric in ["pe_ttm", "pb", "ps_annual_period_end"]:
            subset = series.loc[series["asset"].eq(asset) & series["metric"].eq(metric)].copy()
            if subset.empty:
                continue
            as_of = subset["observation_date"].max()
            current_metric = "ps_ttm" if metric == "ps_annual_period_end" else metric
            current, current_basis, current_source = _current_value(free_current, asset, current_metric, direct)
            for window, days in [("1y", 365), ("3y", 3 * 365), ("5y", 5 * 365), ("all", None)]:
                window_start = as_of - timedelta(days=days) if days is not None else subset["observation_date"].min()
                raw_sample = subset.loc[subset["observation_date"].ge(window_start)]
                excluded_lookahead = 0
                if metric == "ps_annual_period_end" and "point_in_time_status" in raw_sample.columns:
                    excluded_lookahead = int(raw_sample["point_in_time_status"].eq("pre_announcement_lookahead").sum())
                    sample = raw_sample.loc[~raw_sample["point_in_time_status"].eq("pre_announcement_lookahead")]
                else:
                    sample = raw_sample
                values = pd.to_numeric(sample["value"], errors="coerce").dropna()
                positive = values.loc[values.gt(0)]
                percentile = None
                if current is not None and not positive.empty and current > 0:
                    percentile = float((positive <= current).mean() * 100.0)
                pit = "historical_vendor_or_constructed_series_requires_denominator_review"
                if metric == "ps_annual_period_end":
                    pit = "period_end_only_except_rows_with_announcement_alignment"
                rows.append(
                    {
                        "dataset_id": "airline_historical_valuation_bands",
                        "asset": asset,
                        "company": company,
                        "market": market_name,
                        "metric": metric,
                        "window": window,
                        "as_of_date": as_of.date().isoformat(),
                        "window_start_date": pd.Timestamp(window_start).date().isoformat(),
                        "observation_count": int(len(values)),
                        "positive_observation_count": int(len(positive)),
                        "non_positive_observation_count": int((values <= 0).sum()),
                        "excluded_pre_announcement_count": excluded_lookahead,
                        "min_value": _num(positive.min()) if not positive.empty else None,
                        "p25_value": _num(positive.quantile(0.25)) if not positive.empty else None,
                        "median_value": _num(positive.median()) if not positive.empty else None,
                        "p75_value": _num(positive.quantile(0.75)) if not positive.empty else None,
                        "max_value": _num(positive.max()) if not positive.empty else None,
                        "current_value": current,
                        "current_basis": current_basis,
                        "current_source": current_source,
                        "current_percentile_positive": percentile,
                        "point_in_time_status": pit,
                        "source_quality": "free_vendor_history_or_free_constructed_annual_ps",
                        "source_paths": f"{FREE_HISTORY_PATH};{FREE_CURRENT_PATH};{CONSTRUCTED_OUTPUT_PATH};{COMPARABILITY_PATH}",
                        "retrieved_at": retrieved,
                    }
                )
    return pd.DataFrame(rows, columns=BANDS_COLUMNS)


def build_airline_valuation_reconciliation_audit(
    *,
    free_history: pd.DataFrame,
    free_current: pd.DataFrame,
    constructed_ps: pd.DataFrame,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Compare free-provider current values with the latest dated layers."""

    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for asset, (company, _, _) in ASSET_COMPANY.items():
        for metric in ("pe_ttm", "pb", "ps_ttm"):
            current_rows = free_current.loc[free_current["asset"].eq(asset) & free_current["metric"].eq(metric)].copy()
            direct_value = None
            direct_basis = ""
            direct_date = ""
            if not current_rows.empty:
                current_rows["observation_date"] = pd.to_datetime(current_rows["observation_date"], errors="coerce")
                current_row = current_rows.sort_values("observation_date").iloc[-1]
                direct_value = _num(current_row.get("value"))
                direct_basis = _text(current_row.get("basis"))
                direct_date = _text(current_row.get("observation_date"))[:10]
            dated_source = constructed_ps if metric == "ps_ttm" else free_history
            dated_metric = "ps_annual_period_end" if metric == "ps_ttm" else metric
            if dated_source.empty or not {"asset", "metric"}.issubset(dated_source.columns):
                dated_rows = pd.DataFrame()
            else:
                dated_rows = dated_source.loc[dated_source["asset"].eq(asset) & dated_source["metric"].eq(dated_metric)].copy()
            dated_value = None
            dated_basis = ""
            dated_date = ""
            pit_status = "missing_dated_layer"
            if not dated_rows.empty:
                dated_rows["observation_date"] = pd.to_datetime(dated_rows["observation_date"], errors="coerce")
                dated_row = dated_rows.sort_values("observation_date").iloc[-1]
                dated_value = _num(dated_row.get("value"))
                dated_basis = _text(dated_row.get("basis"))
                dated_date = _text(dated_row.get("observation_date"))[:10]
                pit_status = _text(dated_row.get("point_in_time_status")) or "dated_layer_status_missing"
            relative_difference = None
            if direct_value is not None and dated_value not in (None, 0):
                relative_difference = (direct_value / dated_value - 1.0) * 100.0
            if direct_value is None or dated_value is None:
                comparison = "missing_direct_or_dated_value"
            elif metric == "ps_ttm":
                comparison = "basis_mismatch_current_ttm_vs_latest_annual_revenue"
            elif abs(relative_difference or 0.0) <= 20.0:
                comparison = "provider_cross_check_within_20pct"
            else:
                comparison = "provider_cross_check_difference_over_20pct"
            rows.append(
                {
                    "dataset_id": "airline_valuation_reconciliation_audit",
                    "asset": asset,
                    "company": company,
                    "metric": metric,
                    "direct_value": direct_value,
                    "direct_basis": direct_basis,
                    "direct_observation_date": direct_date,
                    "dated_value": dated_value,
                    "dated_basis": dated_basis,
                    "dated_observation_date": dated_date,
                    "relative_difference_pct": relative_difference,
                    "comparison_status": comparison,
                    "point_in_time_status": pit_status,
                    "source_paths": f"{FREE_CURRENT_PATH};{FREE_HISTORY_PATH};{CONSTRUCTED_OUTPUT_PATH};{COMPARABILITY_PATH}",
                    "retrieved_at": retrieved,
                }
            )
    return pd.DataFrame(rows, columns=RECONCILIATION_COLUMNS)


def fetch_airline_historical_valuation_bands() -> pd.DataFrame:
    """Build free constructed P/S history and valuation bands from local layers."""

    retrieved = datetime.now(timezone.utc).isoformat()
    free_history = pd.read_csv(FREE_HISTORY_PATH)
    free_current = pd.read_csv(FREE_CURRENT_PATH)
    financial_history = pd.read_csv(FINANCIAL_HISTORY_PATH)
    comparability = pd.read_csv(COMPARABILITY_PATH) if COMPARABILITY_PATH.exists() else pd.DataFrame()
    official = pd.read_csv(OFFICIAL_DRIVERS_PATH) if OFFICIAL_DRIVERS_PATH.exists() else pd.DataFrame()
    fx = pd.read_parquet(FX_PATH) if FX_PATH.exists() else pd.DataFrame()
    constructed = build_airline_free_constructed_ps_history(
        free_history=free_history,
        financial_history=financial_history,
        official_drivers=official,
        comparability_drivers=comparability,
        fx_rates=fx,
        retrieved_at=retrieved,
    )
    bands = build_airline_historical_valuation_bands(
        free_history=free_history,
        free_current=free_current,
        constructed_ps=constructed,
        retrieved_at=retrieved,
    )
    reconciliation = build_airline_valuation_reconciliation_audit(
        free_history=free_history,
        free_current=free_current,
        constructed_ps=constructed,
        retrieved_at=retrieved,
    )
    constructed.to_csv(CONSTRUCTED_OUTPUT_PATH, index=False)
    bands.to_csv(BANDS_OUTPUT_PATH, index=False)
    reconciliation.to_csv(RECONCILIATION_OUTPUT_PATH, index=False)
    return bands
