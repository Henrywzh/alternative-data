"""Dated Hong Kong-listed airline broker forecasts from AkShare/Etnet."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


HK_FORECAST_UNIVERSE: dict[str, dict[str, str]] = {
    "0293": {"ticker": "0293.HK", "company": "Cathay Pacific", "forecast_currency": "HKD"},
    "0753": {"ticker": "0753.HK", "company": "Air China", "forecast_currency": "RMB"},
    "0670": {"ticker": "0670.HK", "company": "China Eastern Airlines", "forecast_currency": "RMB"},
    "01055": {"ticker": "01055.HK", "company": "China Southern Airlines", "forecast_currency": "RMB"},
}

HK_FORECAST_COLUMNS = [
    "dataset_id", "ticker", "company", "fiscal_year", "report_date",
    "institution", "rating", "net_profit_native_mn", "eps_native",
    "dividend_native", "forecast_currency", "target_price_hkd",
    "target_price_currency", "source_quality", "source_url",
    "net_profit_usd_mn_at_report", "eps_usd_at_report", "dividend_usd_at_report",
    "forecast_fx_pair", "forecast_fx_observation_date", "forecast_fx_value",
    "target_price_usd_at_report", "target_price_fx_observation_date",
    "target_price_fx_value", "source_note", "retrieved_at",
]

HK_REVISION_COLUMNS = [
    "dataset_id", "ticker", "company", "fiscal_year", "institution",
    "report_date", "prior_report_date", "net_profit_native_mn",
    "prior_net_profit_native_mn", "net_profit_change_native_mn",
    "net_profit_change_pct", "eps_native", "prior_eps_native",
    "eps_change_native", "eps_change_pct", "target_price_hkd",
    "prior_target_price_hkd", "target_price_change_pct", "rating",
    "forecast_currency", "target_price_currency",
    "net_profit_usd_mn_at_report", "eps_usd_at_report", "target_price_usd_at_report",
    "forecast_fx_pair", "forecast_fx_observation_date", "forecast_fx_value",
    "target_price_fx_observation_date", "target_price_fx_value",
    "source_quality", "source_url", "source_note", "retrieved_at",
]

HK_AGGREGATE_COLUMNS = [
    "dataset_id", "ticker", "company", "snapshot_date", "fiscal_year",
    "eps_avg_native", "eps_low_native", "eps_high_native", "eps_currency",
    "eps_avg_usd", "eps_low_usd", "eps_high_usd", "net_profit_avg_native_mn",
    "net_profit_low_native_mn", "net_profit_high_native_mn", "net_profit_currency",
    "net_profit_avg_usd_mn", "net_profit_low_usd_mn", "net_profit_high_usd_mn",
    "target_price_avg_hkd", "target_price_median_hkd", "target_price_avg_usd",
    "target_price_median_usd", "broker_count", "forecast_date_min",
    "forecast_date_max", "ratings_2026", "source_quality", "source_url",
    "revenue_consensus_available", "revisions_history_available", "notes", "retrieved_at",
]


def _retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fx_asof(
    fx_rates: pd.DataFrame | None,
    *,
    pair: str,
    as_of: pd.Timestamp,
) -> tuple[str | None, float | None]:
    """Return the latest available USD quote-currency rate on/before a date."""
    if fx_rates is None or fx_rates.empty:
        return None, None
    frame = fx_rates.loc[fx_rates["pair"].eq(pair)].copy()
    if frame.empty:
        return None, None
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    target = pd.Timestamp(as_of)
    if getattr(target, "tzinfo", None) is not None:
        target = target.tz_localize(None)
    frame = frame.loc[frame["observation_date"].le(target.normalize())].dropna(
        subset=["observation_date", "value"]
    )
    if frame.empty:
        return None, None
    row = frame.sort_values("observation_date").iloc[-1]
    return row["observation_date"].strftime("%Y-%m-%d"), float(row["value"])


def _usd_forecast_fields(
    *,
    report_date: pd.Timestamp,
    forecast_currency: str,
    net_profit_native_mn: float | None,
    eps_native: float | None,
    dividend_native: float | None,
    target_price_hkd: float | None,
    fx_rates: pd.DataFrame | None,
) -> dict[str, Any]:
    forecast_pair = "USD_HKD" if forecast_currency == "HKD" else "USD_CNY"
    forecast_fx_date, forecast_fx = _fx_asof(
        fx_rates, pair=forecast_pair, as_of=report_date
    )
    target_fx_date, target_fx = _fx_asof(
        fx_rates, pair="USD_HKD", as_of=report_date
    )
    return {
        "net_profit_usd_mn_at_report": (
            net_profit_native_mn / forecast_fx
            if net_profit_native_mn is not None and forecast_fx
            else None
        ),
        "eps_usd_at_report": (
            eps_native / forecast_fx if eps_native is not None and forecast_fx else None
        ),
        "dividend_usd_at_report": (
            dividend_native / forecast_fx
            if dividend_native is not None and forecast_fx
            else None
        ),
        "forecast_fx_pair": forecast_pair,
        "forecast_fx_observation_date": forecast_fx_date,
        "forecast_fx_value": forecast_fx,
        "target_price_usd_at_report": (
            target_price_hkd / target_fx
            if target_price_hkd is not None and target_fx
            else None
        ),
        "target_price_fx_observation_date": target_fx_date,
        "target_price_fx_value": target_fx,
    }


def enrich_hk_forecast_usd_columns(
    forecasts: pd.DataFrame,
    *,
    fx_rates: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Add point-in-time USD views using the nearest prior FX observation."""
    result = forecasts.copy()
    if result.empty:
        for column in HK_FORECAST_COLUMNS:
            if column not in result:
                result[column] = pd.Series(dtype="object")
        return result
    rows: list[dict[str, Any]] = []
    for _, row in result.iterrows():
        report_date = pd.to_datetime(row.get("report_date"), errors="coerce")
        currency = str(
            row.get("forecast_currency")
            or ("HKD" if row.get("company") == "Cathay Pacific" else "RMB")
        )
        native_profit = pd.to_numeric(row.get("net_profit_native_mn"), errors="coerce")
        native_eps = pd.to_numeric(row.get("eps_native"), errors="coerce")
        native_dividend = pd.to_numeric(row.get("dividend_native"), errors="coerce")
        target_price = pd.to_numeric(row.get("target_price_hkd"), errors="coerce")
        fields = (
            _usd_forecast_fields(
                report_date=report_date,
                forecast_currency=currency,
                net_profit_native_mn=None if pd.isna(native_profit) else float(native_profit),
                eps_native=None if pd.isna(native_eps) else float(native_eps),
                dividend_native=None if pd.isna(native_dividend) else float(native_dividend),
                target_price_hkd=None if pd.isna(target_price) else float(target_price),
                fx_rates=fx_rates,
            )
            if not pd.isna(report_date)
            else {}
        )
        output = row.to_dict()
        output.update(fields)
        rows.append(output)
    return pd.DataFrame(rows)


def build_hk_consensus_snapshot(
    forecasts: pd.DataFrame,
    *,
    snapshot_date: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Aggregate the latest dated broker observations for market expectations."""
    if forecasts.empty:
        return pd.DataFrame(columns=HK_AGGREGATE_COLUMNS)
    retrieved = retrieved_at or _retrieved_at()
    snapshot = snapshot_date or pd.Timestamp(retrieved).strftime("%Y-%m-%d")
    source = forecasts.copy()
    source["report_date"] = pd.to_datetime(source["report_date"], errors="coerce")
    rows: list[dict[str, Any]] = []
    for (ticker, company, fiscal_year), group in source.groupby(
        ["ticker", "company", "fiscal_year"], dropna=False
    ):
        def numeric_series(column: str) -> pd.Series:
            return pd.to_numeric(group.get(column, pd.Series(index=group.index)), errors="coerce").dropna()

        def mean(column: str) -> float | None:
            values = numeric_series(column)
            return float(values.mean()) if not values.empty else None

        def minimum(column: str) -> float | None:
            values = numeric_series(column)
            return float(values.min()) if not values.empty else None

        def maximum(column: str) -> float | None:
            values = numeric_series(column)
            return float(values.max()) if not values.empty else None

        def median(column: str) -> float | None:
            values = numeric_series(column)
            return float(values.median()) if not values.empty else None

        report_dates = group["report_date"].dropna()
        currency = str(group["forecast_currency"].dropna().iloc[0]) if group["forecast_currency"].notna().any() else None
        ratings = None
        if int(fiscal_year) == 2026 and "rating" in group:
            counts = group["rating"].dropna().astype(str).value_counts()
            ratings = ";".join(f"{rating}={count}" for rating, count in counts.items())
        rows.append(
            {
                "dataset_id": "airline_consensus_snapshot",
                "ticker": ticker,
                "company": company,
                "snapshot_date": snapshot,
                "fiscal_year": int(fiscal_year),
                "eps_avg_native": mean("eps_native"),
                "eps_low_native": minimum("eps_native"),
                "eps_high_native": maximum("eps_native"),
                "eps_currency": currency,
                "eps_avg_usd": mean("eps_usd_at_report"),
                "eps_low_usd": minimum("eps_usd_at_report"),
                "eps_high_usd": maximum("eps_usd_at_report"),
                "net_profit_avg_native_mn": mean("net_profit_native_mn"),
                "net_profit_low_native_mn": minimum("net_profit_native_mn"),
                "net_profit_high_native_mn": maximum("net_profit_native_mn"),
                "net_profit_currency": currency,
                "net_profit_avg_usd_mn": mean("net_profit_usd_mn_at_report"),
                "net_profit_low_usd_mn": minimum("net_profit_usd_mn_at_report"),
                "net_profit_high_usd_mn": maximum("net_profit_usd_mn_at_report"),
                "target_price_avg_hkd": mean("target_price_hkd"),
                "target_price_median_hkd": median("target_price_hkd"),
                "target_price_avg_usd": mean("target_price_usd_at_report"),
                "target_price_median_usd": median("target_price_usd_at_report"),
                "broker_count": int(group["institution"].dropna().astype(str).nunique()),
                "forecast_date_min": report_dates.min().strftime("%Y-%m-%d") if not report_dates.empty else None,
                "forecast_date_max": report_dates.max().strftime("%Y-%m-%d") if not report_dates.empty else None,
                "ratings_2026": ratings,
                "source_quality": "discovery_snapshot",
                "source_url": group["source_url"].dropna().iloc[0] if group["source_url"].notna().any() else None,
                "revenue_consensus_available": False,
                "revisions_history_available": False,
                "notes": (
                    "Derived from the current dated public Etnet/AkShare broker rows. "
                    "USD profit/EPS/target-price fields average the report-date FX conversions; "
                    "this is not a complete institutional consensus-vintage history."
                ),
                "retrieved_at": retrieved,
            }
        )
    return pd.DataFrame(rows, columns=HK_AGGREGATE_COLUMNS).sort_values(
        ["ticker", "fiscal_year"]
    ).reset_index(drop=True)


def normalize_hk_profit_forecast(
    frame: pd.DataFrame,
    *,
    code: str,
    snapshot_date: str | None = None,
    fx_rates: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Normalize dated broker forecasts with explicit reporting currencies."""
    required = {"财政年度", "纯利/亏损", "每股盈利", "证券商", "评级", "目标价", "更新日期"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"HK forecast table is missing columns: {sorted(missing)}")
    metadata = HK_FORECAST_UNIVERSE[code]
    retrieved = retrieved_at or _retrieved_at()
    rows: list[dict[str, Any]] = []
    for _, source in frame.iterrows():
        fiscal_year = pd.to_numeric(source["财政年度"], errors="coerce")
        report_date = pd.to_datetime(source["更新日期"], errors="coerce")
        if pd.isna(fiscal_year) or pd.isna(report_date):
            continue
        # Etnet labels profit/EPS/dividend in the issuer reporting currency;
        # this is HKD for Cathay and RMB for the mainland airlines. Profit is
        # in reporting-currency million and EPS is reporting-currency/share
        # expressed in cents. Target price is HKD/share.
        eps_cents = pd.to_numeric(source["每股盈利"], errors="coerce")
        eps = None if pd.isna(eps_cents) else float(eps_cents) / 100.0
        def numeric(column: str) -> float | None:
            value = pd.to_numeric(source[column], errors="coerce")
            return None if pd.isna(value) else float(value)
        native_profit = numeric("纯利/亏损")
        native_dividend = numeric("每股派息")
        target_price = numeric("目标价")
        usd_fields = _usd_forecast_fields(
            report_date=report_date,
            forecast_currency=metadata["forecast_currency"],
            net_profit_native_mn=native_profit,
            eps_native=eps,
            dividend_native=native_dividend,
            target_price_hkd=target_price,
            fx_rates=fx_rates,
        )
        rows.append(
            {
                "dataset_id": "airline_hk_sell_side_forecasts",
                "ticker": metadata["ticker"],
                "company": metadata["company"],
                "fiscal_year": int(fiscal_year),
                "report_date": report_date.strftime("%Y-%m-%d"),
                "institution": source["证券商"],
                "rating": source["评级"],
                "net_profit_native_mn": native_profit,
                "eps_native": eps,
                "dividend_native": native_dividend,
                "forecast_currency": metadata["forecast_currency"],
                "target_price_hkd": target_price,
                "target_price_currency": "HKD",
                "source_quality": "akshare_discovery",
                "source_url": f"https://www.etnet.com.hk/www/sc/stocks/realtime/quote_profit.php?code={code.lstrip('0') or '0'}",
                **usd_fields,
                "source_note": (
                    "Dated public Etnet/AkShare broker forecast observation; Etnet labels profit/EPS/dividend "
                    f"in {metadata['forecast_currency']} for this issuer, while target price is HKD/share. "
                    f"EPS converted from {metadata['forecast_currency']} cents to {metadata['forecast_currency']}/share. "
                    "USD views use the nearest prior ECB USD/quote-currency observation on the broker report date. "
                    "The provider currently exposes one latest row per broker/fiscal year; append across refreshes "
                    "to build revisions. This is not a complete institutional consensus tape."
                ),
                "retrieved_at": retrieved,
            }
        )
    result = pd.DataFrame(rows, columns=HK_FORECAST_COLUMNS)
    if result.empty:
        return result
    return result.sort_values(["ticker", "fiscal_year", "institution", "report_date"]).reset_index(drop=True)


def normalize_hk_forecast_revisions(
    forecasts: pd.DataFrame,
    *,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Compare each broker's forecast with its prior dated row."""
    retrieved = retrieved_at or _retrieved_at()
    source = forecasts.copy()
    source["report_date"] = pd.to_datetime(source["report_date"], errors="coerce")
    source = source.dropna(subset=["report_date"]).sort_values(
        ["ticker", "fiscal_year", "institution", "report_date"]
    )
    previous: dict[tuple[str, int, str], dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for _, report in source.iterrows():
        key = (str(report["ticker"]), int(report["fiscal_year"]), str(report["institution"]))
        report_date = report["report_date"].strftime("%Y-%m-%d")
        prior = previous.get(key, {})
        eps = pd.to_numeric(report["eps_native"], errors="coerce")
        profit = pd.to_numeric(report["net_profit_native_mn"], errors="coerce")
        target = pd.to_numeric(report["target_price_hkd"], errors="coerce")
        prev_eps = prior.get("eps_native")
        prev_profit = prior.get("net_profit_native_mn")
        prev_target = prior.get("target_price_hkd")
        eps_change = float(eps - prev_eps) if pd.notna(eps) and prev_eps is not None else None
        profit_change = float(profit - prev_profit) if pd.notna(profit) and prev_profit is not None else None
        target_change_pct = None
        if pd.notna(target) and prev_target not in (None, 0):
            target_change_pct = 100.0 * (float(target) / float(prev_target) - 1.0)
        rows.append(
            {
                "dataset_id": "airline_hk_forecast_revisions",
                "ticker": report["ticker"],
                "company": report["company"],
                "fiscal_year": report["fiscal_year"],
                "institution": report["institution"],
                "report_date": report_date,
                "prior_report_date": prior.get("report_date"),
                "net_profit_native_mn": profit,
                "prior_net_profit_native_mn": prev_profit,
                "net_profit_change_native_mn": profit_change,
                "net_profit_change_pct": (
                    100.0 * profit_change / abs(float(prev_profit))
                    if profit_change is not None and prev_profit not in (None, 0)
                    else None
                ),
                "eps_native": eps,
                "prior_eps_native": prev_eps,
                "eps_change_native": eps_change,
                "eps_change_pct": (
                    100.0 * eps_change / abs(float(prev_eps))
                    if eps_change is not None and prev_eps not in (None, 0)
                    else None
                ),
                "target_price_hkd": target,
                "prior_target_price_hkd": prev_target,
                "target_price_change_pct": target_change_pct,
                "rating": report["rating"],
                "forecast_currency": report.get(
                    "forecast_currency",
                    "HKD" if str(report.get("company")) == "Cathay Pacific" else "RMB",
                ),
                "target_price_currency": report.get("target_price_currency", "HKD"),
                "net_profit_usd_mn_at_report": report.get("net_profit_usd_mn_at_report"),
                "eps_usd_at_report": report.get("eps_usd_at_report"),
                "target_price_usd_at_report": report.get("target_price_usd_at_report"),
                "forecast_fx_pair": report.get("forecast_fx_pair"),
                "forecast_fx_observation_date": report.get("forecast_fx_observation_date"),
                "forecast_fx_value": report.get("forecast_fx_value"),
                "target_price_fx_observation_date": report.get("target_price_fx_observation_date"),
                "target_price_fx_value": report.get("target_price_fx_value"),
                "source_quality": "akshare_discovery",
                "source_url": report["source_url"],
                "source_note": (
                    "Derived from dated Etnet/AkShare broker rows; prior value is the previous available "
                    "report by the same institution and fiscal year. Forecast profit/EPS use the issuer "
                    "reporting currency; target price is in HKD. Not a complete consensus revision history."
                ),
                "retrieved_at": retrieved,
            }
        )
        previous[key] = {
            "report_date": report_date,
            "eps_native": None if pd.isna(eps) else float(eps),
            "net_profit_native_mn": None if pd.isna(profit) else float(profit),
            "target_price_hkd": None if pd.isna(target) else float(target),
        }
    return pd.DataFrame(rows, columns=HK_REVISION_COLUMNS)


def fetch_hk_airline_consensus() -> dict[str, pd.DataFrame]:
    """Fetch and persist dated HK broker forecasts and revision rows."""
    import akshare as ak

    retrieved = _retrieved_at()
    fx_path = NORMALIZED_DIR / "airline_fx_rates.parquet"
    fx_rates = pd.read_parquet(fx_path) if fx_path.exists() else None
    forecast_frames: list[pd.DataFrame] = []
    for code in HK_FORECAST_UNIVERSE:
        raw = ak.stock_hk_profit_forecast_et(symbol=code)
        forecast_frames.append(
            normalize_hk_profit_forecast(
                raw, code=code, fx_rates=fx_rates, retrieved_at=retrieved
            )
        )
    current_records = [
        record
        for frame in forecast_frames
        for record in frame.to_dict(orient="records")
    ]
    current = pd.DataFrame.from_records(current_records, columns=HK_FORECAST_COLUMNS)
    forecast_path = NORMALIZED_DIR / "airline_hk_sell_side_forecasts.csv"
    if forecast_path.exists():
        prior = pd.read_csv(forecast_path)
        prior = enrich_hk_forecast_usd_columns(prior, fx_rates=fx_rates)
        forecasts = pd.concat([prior, current], ignore_index=True)
        forecasts = forecasts.drop_duplicates(
            subset=["ticker", "fiscal_year", "institution", "report_date"],
            keep="last",
        ).sort_values(["ticker", "fiscal_year", "institution", "report_date"]).reset_index(drop=True)
    else:
        forecasts = current
    revisions = normalize_hk_forecast_revisions(forecasts, retrieved_at=retrieved)
    forecasts.to_csv(forecast_path, index=False)
    revisions.to_csv(NORMALIZED_DIR / "airline_hk_forecast_revisions.csv", index=False)
    build_hk_consensus_snapshot(
        forecasts, snapshot_date=datetime.fromisoformat(retrieved.replace("Z", "+00:00")).strftime("%Y-%m-%d"), retrieved_at=retrieved
    ).to_csv(NORMALIZED_DIR / "airline_consensus_snapshot.csv", index=False)
    return {"forecasts": forecasts, "revisions": revisions}


def source_paths() -> dict[str, Path]:
    return {
        "forecasts": NORMALIZED_DIR / "airline_hk_sell_side_forecasts.csv",
        "revisions": NORMALIZED_DIR / "airline_hk_forecast_revisions.csv",
    }
