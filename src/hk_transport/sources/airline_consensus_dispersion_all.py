"""All-name consensus dispersion and vintage reconciliation layer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


HK_PATH = NORMALIZED_DIR / "airline_consensus_snapshot.csv"
A_PATH = NORMALIZED_DIR / "airline_consensus_ashare_snapshot.csv"
EM_PATH = NORMALIZED_DIR / "airline_consensus_em_snapshot.csv"
PUBLIC_REPORT_PATH = NORMALIZED_DIR / "airline_public_report_evidence.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_consensus_dispersion_all.csv"

OUTPUT_COLUMNS = [
    "dataset_id", "company", "snapshot_date", "hk_ticker", "a_ticker",
    "hk_profit_avg_usd_mn", "hk_profit_low_usd_mn", "hk_profit_high_usd_mn",
    "hk_profit_range_width_pct", "hk_profit_range_crosses_zero", "hk_broker_count",
    "hk_forecast_date_min", "hk_forecast_date_max", "a_profit_avg_usd_mn",
    "a_profit_low_usd_mn", "a_profit_high_usd_mn", "a_profit_range_width_pct",
    "a_profit_range_crosses_zero", "a_forecast_count", "a_forecast_date_min",
    "a_forecast_date_max", "profit_sign_disagreement_hk_vs_a", "em_snapshot_date",
    "em_rating_total_count_2026", "em_buy_add_pct_2026", "vintage_status",
    "dispersion_status",
    "public_eps_count", "public_eps_low_native", "public_eps_median_native",
    "public_eps_high_native", "public_eps_latest_report_date",
    "public_net_profit_count", "public_net_profit_low_native",
    "public_net_profit_median_native", "public_net_profit_high_native",
    "public_net_profit_latest_report_date",
    "public_revenue_count", "public_revenue_low_native",
    "public_revenue_median_native", "public_revenue_high_native",
    "source_quality", "source_note", "retrieved_at",
]


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _range_width(avg: float | None, low: float | None, high: float | None) -> float | None:
    if avg is None or low is None or high is None or avg == 0:
        return None
    return 100.0 * (high - low) / abs(avg)


def _crosses_zero(low: float | None, high: float | None) -> bool | None:
    if low is None or high is None:
        return None
    return low < 0 < high


def _latest_date(frame: pd.DataFrame, column: str) -> str | None:
    if frame.empty or column not in frame.columns:
        return None
    values = pd.to_datetime(frame[column], errors="coerce").dropna()
    return values.max().strftime("%Y-%m-%d") if not values.empty else None


def _row(frame: pd.DataFrame, company: str) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=object)
    rows = frame.loc[frame["company"].eq(company)]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def build_airline_consensus_dispersion_all(
    *,
    hk: pd.DataFrame | None = None,
    ashare: pd.DataFrame | None = None,
    em: pd.DataFrame | None = None,
    public_report_evidence: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    hk = hk if hk is not None else pd.read_csv(HK_PATH)
    ashare = ashare if ashare is not None else pd.read_csv(A_PATH)
    em = em if em is not None else pd.read_csv(EM_PATH)
    public_report_evidence = (
        public_report_evidence
        if public_report_evidence is not None
        else pd.read_csv(PUBLIC_REPORT_PATH)
        if PUBLIC_REPORT_PATH.exists()
        else pd.DataFrame()
    )
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    hk = hk.loc[hk["fiscal_year"].eq(2026)].copy()
    ashare = ashare.loc[ashare["fiscal_year"].eq(2026) & ashare["metric"].eq("net_profit")].copy()
    em = em.loc[em["fiscal_year"].eq(2026)].copy()
    companies = sorted(set(hk.get("company", [])) | set(ashare.get("company", [])) | set(em.get("company", [])))
    rows: list[dict[str, Any]] = []
    for company in companies:
        hk_row = _row(hk, company)
        a_row = _row(ashare, company)
        em_row = _row(em, company)
        public = public_report_evidence.loc[
            public_report_evidence["company"].eq(company)
        ] if not public_report_evidence.empty else pd.DataFrame()

        def public_stats(metric: str) -> dict[str, Any]:
            subset = public.loc[public["metric"].eq(metric)] if not public.empty else pd.DataFrame()
            values = pd.to_numeric(
                subset.get("forecast_value_native", pd.Series(dtype=float)), errors="coerce"
            ).dropna()
            dated = subset.loc[subset["report_date"].notna()] if not subset.empty else pd.DataFrame()
            return {
                "count": int(len(values)),
                "low": values.min() if not values.empty else None,
                "median": values.median() if not values.empty else None,
                "high": values.max() if not values.empty else None,
                "latest_date": _latest_date(dated, "report_date"),
            }

        public_eps = public_stats("eps")
        public_net_profit = public_stats("net_profit")
        public_revenue = public_stats("revenue")
        hk_avg = _number(hk_row.get("net_profit_avg_usd_mn"))
        hk_low = _number(hk_row.get("net_profit_low_usd_mn"))
        hk_high = _number(hk_row.get("net_profit_high_usd_mn"))
        a_avg = _number(a_row.get("value_avg_usd_at_snapshot"))
        a_low = _number(a_row.get("value_low_usd_at_snapshot"))
        a_high = _number(a_row.get("value_high_usd_at_snapshot"))
        sign_disagreement = (
            bool(hk_avg * a_avg < 0)
            if hk_avg is not None and a_avg is not None and hk_avg != 0 and a_avg != 0
            else None
        )
        if hk_avg is not None and a_avg is not None:
            vintage = "dual_market_consensus"
        elif hk_avg is not None:
            vintage = "hk_only_consensus"
        elif a_avg is not None:
            vintage = "a_share_only_consensus"
        else:
            vintage = "no_profit_consensus"
        statuses: list[str] = []
        if sign_disagreement:
            statuses.append("profit_sign_disagreement")
        if _crosses_zero(hk_low, hk_high) or _crosses_zero(a_low, a_high):
            statuses.append("range_crosses_zero")
        if not statuses:
            statuses.append("no_sign_disagreement")
        rows.append({
            "dataset_id": "airline_consensus_dispersion_all",
            "company": company,
            "snapshot_date": max(
                [value for value in (hk_row.get("snapshot_date"), a_row.get("snapshot_date"), em_row.get("snapshot_date")) if pd.notna(value)]
                or [None]
            ),
            "hk_ticker": hk_row.get("ticker"), "a_ticker": a_row.get("ticker"),
            "hk_profit_avg_usd_mn": hk_avg, "hk_profit_low_usd_mn": hk_low, "hk_profit_high_usd_mn": hk_high,
            "hk_profit_range_width_pct": _range_width(hk_avg, hk_low, hk_high),
            "hk_profit_range_crosses_zero": _crosses_zero(hk_low, hk_high),
            "hk_broker_count": _number(hk_row.get("broker_count")),
            "hk_forecast_date_min": hk_row.get("forecast_date_min"), "hk_forecast_date_max": hk_row.get("forecast_date_max"),
            "a_profit_avg_usd_mn": a_avg, "a_profit_low_usd_mn": a_low, "a_profit_high_usd_mn": a_high,
            "a_profit_range_width_pct": _range_width(a_avg, a_low, a_high),
            "a_profit_range_crosses_zero": _crosses_zero(a_low, a_high),
            "a_forecast_count": _number(a_row.get("forecast_count")),
            "a_forecast_date_min": a_row.get("forecast_date_min"), "a_forecast_date_max": a_row.get("forecast_date_max"),
            "profit_sign_disagreement_hk_vs_a": sign_disagreement,
            "em_snapshot_date": em_row.get("snapshot_date"),
            "em_rating_total_count_2026": _number(em_row.get("rating_total_count")),
            "em_buy_add_pct_2026": _number(em_row.get("buy_add_pct")),
            "vintage_status": vintage,
            "dispersion_status": ";".join(statuses),
            "public_eps_count": public_eps["count"],
            "public_eps_low_native": public_eps["low"],
            "public_eps_median_native": public_eps["median"],
            "public_eps_high_native": public_eps["high"],
            "public_eps_latest_report_date": public_eps["latest_date"],
            "public_net_profit_count": public_net_profit["count"],
            "public_net_profit_low_native": public_net_profit["low"],
            "public_net_profit_median_native": public_net_profit["median"],
            "public_net_profit_high_native": public_net_profit["high"],
            "public_net_profit_latest_report_date": public_net_profit["latest_date"],
            "public_revenue_count": public_revenue["count"],
            "public_revenue_low_native": public_revenue["low"],
            "public_revenue_median_native": public_revenue["median"],
            "public_revenue_high_native": public_revenue["high"],
            "source_quality": "derived_consensus_reconciliation",
            "source_note": (
                "HK and A-share public consensus ranges are compared in USD using each layer's own snapshot convention. "
                "The 10jqka institution ranges are retained in native RMB as a separate current-public-report dispersion "
                "view; revenue rows are page-snapshot-only. Sign/range disagreement is a reconciliation flag, not a trade "
                "signal; forecast vintages remain asynchronous."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_consensus_dispersion_all() -> pd.DataFrame:
    result = build_airline_consensus_dispersion_all()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
