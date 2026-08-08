"""Sector-level airline expectation snapshot for long/short research."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


BRIDGE_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
TREND_PATH = NORMALIZED_DIR / "airline_sector_trend_snapshot.csv"
EVENT_PATH = NORMALIZED_DIR / "airline_event_timeline.csv"
REVISION_PATH = NORMALIZED_DIR / "airline_revision_coverage.csv"
ENERGY_PATH = NORMALIZED_DIR / "airline_energy_prices.parquet"
OUTPUT_PATH = NORMALIZED_DIR / "airline_sector_expectation_snapshot.csv"

CN_COMPANIES = {
    "Air China",
    "China Southern Airlines",
    "China Eastern Airlines",
    "Spring Airlines",
    "Juneyao Airlines",
    "Hainan Airlines Holdings",
}

OUTPUT_COLUMNS = [
    "dataset_id", "scope_type", "scope_id", "sector_group", "company", "ticker", "market",
    "snapshot_date", "native_currency", "company_count", "latest_financial_period",
    "latest_report_announcement_date", "latest_report_revenue_native_mn",
    "latest_report_revenue_coverage_n", "latest_report_attributable_profit_native_mn",
    "latest_report_profit_coverage_n", "latest_report_operating_cost_native_mn",
    "latest_report_fuel_cost_native_mn", "latest_report_fuel_cost_share_pct",
    "latest_report_passenger_revenue_native_mn", "latest_report_passenger_revenue_coverage_n",
    "latest_report_ask_mn_seat_km", "latest_report_ask_coverage_n",
    "latest_report_rpk_mn_passenger_km", "latest_report_rpk_coverage_n",
    "latest_report_passenger_load_factor_pct", "latest_report_passenger_yield_native",
    "latest_report_rask_native", "latest_report_cask_native",
    "latest_report_cash_and_cash_equivalents_native_mn", "latest_report_cash_coverage_n",
    "latest_report_total_liabilities_native_mn", "latest_report_total_liabilities_coverage_n",
    "latest_report_liabilities_to_assets_pct", "latest_report_liabilities_to_assets_coverage_n",
    "latest_report_interest_bearing_debt_native_mn", "latest_report_interest_bearing_debt_coverage_n",
    "latest_report_capex_cash_paid_native_mn", "latest_report_capex_cash_paid_coverage_n",
    "latest_report_net_borrowings_native_mn", "latest_report_net_borrowings_coverage_n",
    "latest_report_available_unrestricted_liquidity_native_mn", "latest_report_available_unrestricted_liquidity_coverage_n",
    "market_cap_usd_mn", "energy_observation_date", "jet_fuel_spot_usd_per_gallon",
    "brent_spot_usd_per_barrel", "energy_source_release_date",
    "h1_2025_jet_fuel_avg_usd_per_gallon", "h1_2026_jet_fuel_avg_usd_per_gallon",
    "h1_jet_fuel_avg_yoy_pct", "h1_2025_brent_avg_usd_per_barrel",
    "h1_2026_brent_avg_usd_per_barrel", "h1_brent_avg_yoy_pct",
    "h1_2025_wti_avg_usd_per_barrel", "h1_2026_wti_avg_usd_per_barrel",
    "h1_wti_avg_yoy_pct", "h1_rpk_minus_ask_growth_gap_pp",
    "h1_ask_yoy_pct", "h1_rpk_yoy_pct", "h1_passengers_yoy_pct",
    "h1_passenger_lf_change_pp", "h1_cargo_tonnes_yoy_pct", "h1_freight_lf_change_pp",
    "h1_overall_lf_change_pp", "fy2026_revenue_consensus_avg_native_mn",
    "fy2026_revenue_consensus_low_native_mn", "fy2026_revenue_consensus_high_native_mn",
    "fy2026_revenue_consensus_coverage_n", "fy2026_revenue_consensus_avg_usd_mn",
    "fy2026_revenue_growth_vs_latest_actual_pct",
    "fy2026_net_profit_consensus_avg_native_mn", "fy2026_net_profit_consensus_low_native_mn",
    "fy2026_net_profit_consensus_high_native_mn", "fy2026_net_profit_consensus_coverage_n",
    "fy2026_net_profit_consensus_avg_usd_mn",
    "fy2026_net_profit_delta_vs_latest_actual_native_mn", "formal_report_status",
    "formal_report_scheduled_date", "formal_report_actual_disclosure_date", "latest_event_date",
    "latest_event_type", "h1_earnings_warning_company_count", "hk_broker_company_count",
    "hk_broker_true_revision_count", "unified_estimate_revision_count",
    "unified_up_revision_count", "unified_down_revision_count",
    "unified_revision_balance", "unified_revision_company_coverage_n",
    "unified_latest_estimate_revision_date", "market_cap_to_consensus_revenue_usd",
    "consensus_valuation_quality", "source_quality", "source_note", "retrieved_at",
]


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _sum(frame: pd.DataFrame, column: str) -> float | None:
    values = pd.to_numeric(frame[column], errors="coerce")
    if values.notna().sum() == 0:
        return None
    return float(values.sum())


def _coverage(frame: pd.DataFrame, column: str) -> int:
    return int(pd.to_numeric(frame[column], errors="coerce").notna().sum())


def _trend_metric(
    trends: pd.DataFrame,
    *,
    scope_type: str,
    company: str | None,
    metric: str,
    field: str,
) -> float | None:
    mask = (
        trends["scope_type"].eq(scope_type)
        & trends["metric"].eq(metric)
        & trends["region"].eq("Total")
    )
    if company is not None:
        mask &= trends["company"].eq(company)
    rows = trends.loc[mask]
    if rows.empty:
        return None
    return _number(rows.iloc[0].get(field))


def _latest_event_stats(events: pd.DataFrame, companies: set[str]) -> dict[str, Any]:
    rows = events.loc[events["company"].isin(companies)].copy()
    warnings = rows.loc[rows["event_type"].eq("earnings_warning")]
    return {
        "latest_event_date": rows["event_date"].max() if not rows.empty else None,
        "latest_event_type": "earnings_warning" if not warnings.empty else None,
        "h1_earnings_warning_company_count": int(warnings["company"].nunique()),
    }


def _formal_report_summary(frame: pd.DataFrame) -> dict[str, Any]:
    statuses = frame["formal_report_status"].dropna().astype(str)
    unique_statuses = sorted(set(statuses))
    if not unique_statuses:
        status = None
    elif len(unique_statuses) == 1:
        status = unique_statuses[0]
    else:
        status = "+".join(unique_statuses)
    scheduled = pd.to_datetime(frame["formal_report_scheduled_date"], errors="coerce").dropna()
    actual = pd.to_datetime(frame["formal_report_actual_disclosure_date"], errors="coerce").dropna()
    return {
        "formal_report_status": status,
        "formal_report_scheduled_date": scheduled.min().strftime("%Y-%m-%d") if not scheduled.empty else None,
        "formal_report_actual_disclosure_date": actual.max().strftime("%Y-%m-%d") if not actual.empty else None,
    }


def _h1_energy_regime(frame: pd.DataFrame) -> dict[str, float | None]:
    """Compute comparable Jan-Jun daily EIA averages without filling gaps."""
    output: dict[str, float | None] = {}
    if frame is None or frame.empty:
        return output
    source = frame.loc[frame["frequency"].eq("daily")].copy()
    if source.empty:
        return output
    source["_date"] = pd.to_datetime(source["observation_date"], errors="coerce")
    source["_value"] = pd.to_numeric(source["value"], errors="coerce")
    series_map = {
        "EER_EPJK_PF4_RGC_DPG": "jet_fuel_avg_usd_per_gallon",
        "RBRTE": "brent_avg_usd_per_barrel",
        "RWTC": "wti_avg_usd_per_barrel",
    }
    for series_id, suffix in series_map.items():
        values: dict[int, float | None] = {}
        rows = source.loc[source["series_id"].eq(series_id)]
        for year in (2025, 2026):
            subset = rows.loc[
                rows["_date"].dt.year.eq(year) & rows["_date"].dt.month.le(6)
            ]["_value"].dropna()
            values[year] = float(subset.mean()) if not subset.empty else None
            output[f"h1_{year}_{suffix}"] = values[year]
        if values[2025] not in (None, 0) and values[2026] is not None:
            output[f"h1_{suffix.removesuffix('_avg_usd_per_gallon').removesuffix('_avg_usd_per_barrel')}_avg_yoy_pct"] = (
                100.0 * (values[2026] / values[2025] - 1.0)
            )
    return output


def _company_row(
    row: pd.Series,
    trends: pd.DataFrame,
    events: pd.DataFrame,
    revisions: pd.DataFrame,
    energy_regime: dict[str, float | None],
    retrieved: str,
) -> dict[str, Any]:
    company = str(row["company"])
    warning_count = int(
        events.loc[
            events["company"].eq(company) & events["event_type"].eq("earnings_warning"),
            "company",
        ].nunique()
    )
    revision_rows = revisions.loc[revisions["company"].eq(company)] if not revisions.empty else pd.DataFrame()
    revision = revision_rows.iloc[0] if not revision_rows.empty else pd.Series(dtype=object)
    revision_count = _number(revision.get("unified_estimate_revision_count"))
    up_revision_count = _number(revision.get("unified_up_revision_count"))
    down_revision_count = _number(revision.get("unified_down_revision_count"))
    return {
        "dataset_id": "airline_sector_expectation_snapshot",
        "scope_type": "company",
        "scope_id": row["market_ticker"],
        "sector_group": "CATHAY_GROUP" if company == "Cathay Pacific" else "CN_MAINLAND_AIRLINES",
        "company": company,
        "ticker": row["market_ticker"],
        "market": row["market"],
        "snapshot_date": row["snapshot_date"],
        "native_currency": row["latest_financial_currency"],
        "company_count": 1,
        "latest_financial_period": row["latest_financial_period"],
        "latest_report_announcement_date": row["latest_report_announcement_date"],
        "latest_report_revenue_native_mn": _number(row["latest_report_revenue_native_mn"]),
        "latest_report_revenue_coverage_n": int(pd.notna(row["latest_report_revenue_native_mn"])),
        "latest_report_attributable_profit_native_mn": _number(row["latest_report_attributable_profit_native_mn"]),
        "latest_report_profit_coverage_n": int(pd.notna(row["latest_report_attributable_profit_native_mn"])),
        "latest_report_operating_cost_native_mn": _number(row["latest_report_operating_cost_native_mn"]),
        "latest_report_fuel_cost_native_mn": _number(row["latest_report_fuel_cost_native_mn"]),
        "latest_report_fuel_cost_share_pct": _number(row["latest_report_fuel_cost_share_pct"]),
        "latest_report_passenger_revenue_native_mn": _number(row.get("latest_report_passenger_revenue_native_mn")),
        "latest_report_passenger_revenue_coverage_n": int(pd.notna(row.get("latest_report_passenger_revenue_native_mn"))),
        "latest_report_ask_mn_seat_km": _number(row.get("latest_report_ask_mn_seat_km")),
        "latest_report_ask_coverage_n": int(pd.notna(row.get("latest_report_ask_mn_seat_km"))),
        "latest_report_rpk_mn_passenger_km": _number(row.get("latest_report_rpk_mn_passenger_km")),
        "latest_report_rpk_coverage_n": int(pd.notna(row.get("latest_report_rpk_mn_passenger_km"))),
        "latest_report_passenger_load_factor_pct": _number(row.get("latest_report_passenger_load_factor_pct")),
        "latest_report_passenger_yield_native": _number(row.get("latest_report_passenger_yield_native")),
        "latest_report_rask_native": _number(row.get("latest_report_rask_native")),
        "latest_report_cask_native": _number(row.get("latest_report_cask_native")),
        "latest_report_cash_and_cash_equivalents_native_mn": _number(row.get("latest_report_cash_and_cash_equivalents_native_mn")),
        "latest_report_cash_coverage_n": int(pd.notna(row.get("latest_report_cash_and_cash_equivalents_native_mn"))),
        "latest_report_total_liabilities_native_mn": _number(row.get("latest_report_total_liabilities_native_mn")),
        "latest_report_total_liabilities_coverage_n": int(pd.notna(row.get("latest_report_total_liabilities_native_mn"))),
        "latest_report_liabilities_to_assets_pct": _number(row.get("latest_report_liabilities_to_assets_pct")),
        "latest_report_liabilities_to_assets_coverage_n": int(pd.notna(row.get("latest_report_liabilities_to_assets_pct"))),
        "latest_report_interest_bearing_debt_native_mn": _number(row.get("latest_report_interest_bearing_debt_native_mn")),
        "latest_report_interest_bearing_debt_coverage_n": int(pd.notna(row.get("latest_report_interest_bearing_debt_native_mn"))),
        "latest_report_capex_cash_paid_native_mn": _number(row.get("latest_report_capex_cash_paid_native_mn")),
        "latest_report_capex_cash_paid_coverage_n": int(pd.notna(row.get("latest_report_capex_cash_paid_native_mn"))),
        "latest_report_net_borrowings_native_mn": _number(row.get("latest_report_net_borrowings_native_mn")),
        "latest_report_net_borrowings_coverage_n": int(pd.notna(row.get("latest_report_net_borrowings_native_mn"))),
        "latest_report_available_unrestricted_liquidity_native_mn": _number(row.get("latest_report_available_unrestricted_liquidity_native_mn")),
        "latest_report_available_unrestricted_liquidity_coverage_n": int(pd.notna(row.get("latest_report_available_unrestricted_liquidity_native_mn"))),
        "market_cap_usd_mn": _number(row["market_cap_usd_mn"]),
        "energy_observation_date": row.get("energy_observation_date"),
        "jet_fuel_spot_usd_per_gallon": _number(row.get("jet_fuel_spot_usd_per_gallon")),
        "brent_spot_usd_per_barrel": _number(row.get("brent_spot_usd_per_barrel")),
        "energy_source_release_date": row.get("energy_source_release_date"),
        **energy_regime,
        "h1_ask_yoy_pct": _number(row["h1_ask_yoy_pct"]),
        "h1_rpk_yoy_pct": _number(row["h1_rpk_yoy_pct"]),
        "h1_rpk_minus_ask_growth_gap_pp": (
            _number(row["h1_rpk_yoy_pct"]) - _number(row["h1_ask_yoy_pct"])
            if pd.notna(row.get("h1_rpk_yoy_pct")) and pd.notna(row.get("h1_ask_yoy_pct"))
            else None
        ),
        "h1_passengers_yoy_pct": _number(row["h1_passengers_yoy_pct"]),
        "h1_passenger_lf_change_pp": _number(row["h1_passenger_lf_change_pp"]),
        "h1_cargo_tonnes_yoy_pct": _number(row["h1_cargo_tonnes_yoy_pct"]),
        "h1_freight_lf_change_pp": _number(row["h1_freight_lf_change_pp"]),
        "h1_overall_lf_change_pp": _trend_metric(
            trends, scope_type="company", company=company, metric="overall_load_factor_pct", field="yoy_change_abs"
        ),
        "fy2026_revenue_consensus_avg_native_mn": _number(row["fy2026_revenue_avg_native_mn"]),
        "fy2026_revenue_consensus_low_native_mn": _number(row["fy2026_revenue_low_native_mn"]),
        "fy2026_revenue_consensus_high_native_mn": _number(row["fy2026_revenue_high_native_mn"]),
        "fy2026_revenue_consensus_coverage_n": int(pd.notna(row["fy2026_revenue_avg_native_mn"])),
        "fy2026_revenue_consensus_avg_usd_mn": _number(row.get("fy2026_revenue_avg_usd_mn")),
        "fy2026_revenue_growth_vs_latest_actual_pct": (
            100.0 * (_number(row["fy2026_revenue_avg_native_mn"]) / _number(row["latest_report_revenue_native_mn"]) - 1.0)
            if row["latest_financial_period"] == "FY2025"
            and pd.notna(row["fy2026_revenue_avg_native_mn"])
            and pd.notna(row["latest_report_revenue_native_mn"])
            else None
        ),
        "fy2026_net_profit_consensus_avg_native_mn": _number(row["fy2026_net_profit_avg_native_mn"]),
        "fy2026_net_profit_consensus_low_native_mn": _number(row["fy2026_net_profit_low_native_mn"]),
        "fy2026_net_profit_consensus_high_native_mn": _number(row["fy2026_net_profit_high_native_mn"]),
        "fy2026_net_profit_consensus_coverage_n": int(pd.notna(row["fy2026_net_profit_avg_native_mn"])),
        "fy2026_net_profit_consensus_avg_usd_mn": _number(row.get("fy2026_net_profit_avg_usd_mn")),
        "fy2026_net_profit_delta_vs_latest_actual_native_mn": (
            _number(row["fy2026_net_profit_avg_native_mn"]) - _number(row["latest_report_attributable_profit_native_mn"])
            if row["latest_financial_period"] == "FY2025"
            and pd.notna(row["fy2026_net_profit_avg_native_mn"])
            and pd.notna(row["latest_report_attributable_profit_native_mn"])
            else None
        ),
        "formal_report_status": row["formal_report_status"],
        "formal_report_scheduled_date": row["formal_report_scheduled_date"],
        "formal_report_actual_disclosure_date": row["formal_report_actual_disclosure_date"],
        "latest_event_date": row["latest_event_date"],
        "latest_event_type": row["latest_event_type"],
        "h1_earnings_warning_company_count": warning_count,
        "hk_broker_company_count": int(pd.notna(row["hk_broker_observation_count"])),
        "hk_broker_true_revision_count": int(_number(row["hk_broker_true_revision_count"]) or 0),
        "unified_estimate_revision_count": revision_count,
        "unified_up_revision_count": up_revision_count,
        "unified_down_revision_count": down_revision_count,
        "unified_revision_balance": (
            up_revision_count - down_revision_count
            if up_revision_count is not None and down_revision_count is not None
            else None
        ),
        "unified_revision_company_coverage_n": int(revision_count > 0) if revision_count is not None else 0,
        "unified_latest_estimate_revision_date": revision.get("unified_latest_estimate_revision_date"),
        "market_cap_to_consensus_revenue_usd": _number(row.get("market_cap_to_consensus_revenue_usd")),
        "consensus_valuation_quality": row.get("consensus_valuation_quality"),
        "source_quality": "derived_company_bridge",
        "source_note": "Company row copied from the auditable airline expectation bridge; native units and source scope are retained.",
        "retrieved_at": retrieved,
    }


def build_airline_sector_expectation_snapshot(
    *,
    bridge: pd.DataFrame | None = None,
    trends: pd.DataFrame | None = None,
    events: pd.DataFrame | None = None,
    revisions: pd.DataFrame | None = None,
    energy: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build company rows plus a six-company RMB sector aggregate."""
    bridge = bridge if bridge is not None else pd.read_csv(BRIDGE_PATH)
    trends = trends if trends is not None else pd.read_csv(TREND_PATH)
    events = events if events is not None else pd.read_csv(EVENT_PATH)
    revisions = revisions if revisions is not None else (
        pd.read_csv(REVISION_PATH) if REVISION_PATH.exists() else pd.DataFrame()
    )
    energy = energy if energy is not None else (
        pd.read_parquet(ENERGY_PATH) if ENERGY_PATH.exists() else pd.DataFrame()
    )
    energy_regime = _h1_energy_regime(energy)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()

    # Use one A-share row per underlying mainland group for the sector aggregate.
    mainland = bridge.loc[
        bridge["company"].isin(CN_COMPANIES) & bridge["market"].eq("CN_A")
    ].drop_duplicates("company").copy()
    if len(mainland) != len(CN_COMPANIES):
        raise ValueError(f"expected {len(CN_COMPANIES)} mainland groups, found {len(mainland)}")

    warning_stats = _latest_event_stats(events, CN_COMPANIES)
    formal = _formal_report_summary(mainland)
    actual_revenue = _sum(mainland, "latest_report_revenue_native_mn")
    actual_profit = _sum(mainland, "latest_report_attributable_profit_native_mn")
    consensus_revenue = _sum(mainland, "fy2026_revenue_avg_native_mn")
    consensus_profit = _sum(mainland, "fy2026_net_profit_avg_native_mn")
    actual_profit_coverage = _coverage(mainland, "latest_report_attributable_profit_native_mn")
    revenue_coverage = _coverage(mainland, "fy2026_revenue_avg_native_mn")
    profit_coverage = _coverage(mainland, "fy2026_net_profit_avg_native_mn")
    consensus_revenue_usd = _sum(mainland, "fy2026_revenue_avg_usd_mn")
    consensus_profit_usd = _sum(mainland, "fy2026_net_profit_avg_usd_mn")
    market_cap_usd = _sum(mainland, "market_cap_usd_mn")
    market_cap_to_revenue_usd = (
        market_cap_usd / consensus_revenue_usd
        if market_cap_usd is not None and consensus_revenue_usd
        else None
    )
    valuation_quality = (
        "unstable_profit_base"
        if mainland["consensus_valuation_quality"].astype(str).eq("unstable_profit_base").any()
        else "profit_based_multiple_usable"
    )
    energy_rows = mainland.loc[mainland["energy_observation_date"].notna()].copy()
    if not energy_rows.empty:
        energy_rows["_energy_date"] = pd.to_datetime(energy_rows["energy_observation_date"], errors="coerce")
        energy_row = energy_rows.sort_values("_energy_date").iloc[-1]
    else:
        energy_row = pd.Series(dtype=object)
    fuel_cost = _sum(mainland, "latest_report_fuel_cost_native_mn")
    operating_cost = _sum(mainland, "latest_report_operating_cost_native_mn")
    passenger_revenue = _sum(mainland, "latest_report_passenger_revenue_native_mn")
    passenger_revenue_coverage = _coverage(mainland, "latest_report_passenger_revenue_native_mn")
    ask = _sum(mainland, "latest_report_ask_mn_seat_km")
    rpk = _sum(mainland, "latest_report_rpk_mn_passenger_km")
    ask_coverage = _coverage(mainland, "latest_report_ask_mn_seat_km")
    rpk_coverage = _coverage(mainland, "latest_report_rpk_mn_passenger_km")
    weighted_yield = (
        float(
            (
                pd.to_numeric(mainland["latest_report_passenger_yield_native"], errors="coerce")
                * pd.to_numeric(mainland["latest_report_rpk_mn_passenger_km"], errors="coerce")
            ).sum()
            / rpk
        )
        if rpk and _coverage(mainland, "latest_report_passenger_yield_native") == len(mainland)
        else None
    )
    weighted_rask = (
        float(
            (
                pd.to_numeric(mainland["latest_report_rask_native"], errors="coerce")
                * pd.to_numeric(mainland["latest_report_ask_mn_seat_km"], errors="coerce")
            ).sum()
            / ask
        )
        if ask and _coverage(mainland, "latest_report_rask_native") == len(mainland)
        else None
    )
    weighted_cask = operating_cost / ask if operating_cost is not None and ask else None
    broker_coverage = int(mainland["hk_broker_observation_count"].notna().sum())
    broker_revisions = int(pd.to_numeric(mainland["hk_broker_true_revision_count"], errors="coerce").fillna(0).sum())
    revision_rows = revisions.loc[revisions["company"].isin(CN_COMPANIES)] if not revisions.empty else pd.DataFrame()
    revision_count = int(pd.to_numeric(revision_rows.get("unified_estimate_revision_count", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    up_revision_count = int(pd.to_numeric(revision_rows.get("unified_up_revision_count", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    down_revision_count = int(pd.to_numeric(revision_rows.get("unified_down_revision_count", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    revision_dates = pd.to_datetime(
        revision_rows.get("unified_latest_estimate_revision_date", pd.Series(dtype=str)), errors="coerce"
    ).dropna()
    revision_company_coverage = int(
        pd.to_numeric(revision_rows.get("unified_estimate_revision_count", pd.Series(dtype=float)), errors="coerce")
        .fillna(0).gt(0).sum()
    )
    profit_coverage_note = (
        f"Profit actual coverage is {actual_profit_coverage}/{len(mainland)}."
        if actual_profit_coverage == len(mainland)
        else f"Profit actual coverage is {actual_profit_coverage}/{len(mainland)} because one or more attributable-profit rows remain unparsed."
    )
    aggregate = {
        "dataset_id": "airline_sector_expectation_snapshot",
        "scope_type": "sector_aggregate",
        "scope_id": "SECTOR_CN_AIRLINES",
        "sector_group": "CN_MAINLAND_AIRLINES",
        "company": "Six-company mainland listed airline universe",
        "ticker": "SECTOR_CN_AIRLINES",
        "market": "CN_A/HK",
        "snapshot_date": mainland["snapshot_date"].max(),
        "native_currency": "RMB",
        "company_count": len(mainland),
        "latest_financial_period": "FY2025",
        "latest_report_announcement_date": None,
        "latest_report_revenue_native_mn": actual_revenue,
        "latest_report_revenue_coverage_n": _coverage(mainland, "latest_report_revenue_native_mn"),
        "latest_report_attributable_profit_native_mn": actual_profit,
        "latest_report_profit_coverage_n": actual_profit_coverage,
        "latest_report_operating_cost_native_mn": operating_cost,
        "latest_report_fuel_cost_native_mn": fuel_cost,
        "latest_report_fuel_cost_share_pct": 100.0 * fuel_cost / operating_cost if fuel_cost and operating_cost else None,
        "latest_report_passenger_revenue_native_mn": passenger_revenue,
        "latest_report_passenger_revenue_coverage_n": passenger_revenue_coverage,
        "latest_report_ask_mn_seat_km": ask,
        "latest_report_ask_coverage_n": ask_coverage,
        "latest_report_rpk_mn_passenger_km": rpk,
        "latest_report_rpk_coverage_n": rpk_coverage,
        "latest_report_passenger_load_factor_pct": 100.0 * rpk / ask if ask and rpk and ask_coverage == len(mainland) and rpk_coverage == len(mainland) else None,
        "latest_report_passenger_yield_native": weighted_yield,
        "latest_report_rask_native": weighted_rask,
        "latest_report_cask_native": weighted_cask,
        "latest_report_cash_and_cash_equivalents_native_mn": _sum(mainland, "latest_report_cash_and_cash_equivalents_native_mn"),
        "latest_report_cash_coverage_n": _coverage(mainland, "latest_report_cash_and_cash_equivalents_native_mn"),
        "latest_report_total_liabilities_native_mn": _sum(mainland, "latest_report_total_liabilities_native_mn"),
        "latest_report_total_liabilities_coverage_n": _coverage(mainland, "latest_report_total_liabilities_native_mn"),
        # A ratio cannot be summed and the bridge does not carry total assets
        # for a weighted aggregate; retain company-level ratios only.
        "latest_report_liabilities_to_assets_pct": None,
        "latest_report_liabilities_to_assets_coverage_n": _coverage(mainland, "latest_report_liabilities_to_assets_pct"),
        "latest_report_interest_bearing_debt_native_mn": _sum(mainland, "latest_report_interest_bearing_debt_native_mn"),
        "latest_report_interest_bearing_debt_coverage_n": _coverage(mainland, "latest_report_interest_bearing_debt_native_mn"),
        "latest_report_capex_cash_paid_native_mn": _sum(mainland, "latest_report_capex_cash_paid_native_mn"),
        "latest_report_capex_cash_paid_coverage_n": _coverage(mainland, "latest_report_capex_cash_paid_native_mn"),
        "latest_report_net_borrowings_native_mn": None,
        "latest_report_net_borrowings_coverage_n": _coverage(mainland, "latest_report_net_borrowings_native_mn"),
        "latest_report_available_unrestricted_liquidity_native_mn": None,
        "latest_report_available_unrestricted_liquidity_coverage_n": _coverage(mainland, "latest_report_available_unrestricted_liquidity_native_mn"),
        "market_cap_usd_mn": market_cap_usd,
        "energy_observation_date": energy_row.get("energy_observation_date"),
        "jet_fuel_spot_usd_per_gallon": _number(energy_row.get("jet_fuel_spot_usd_per_gallon")),
        "brent_spot_usd_per_barrel": _number(energy_row.get("brent_spot_usd_per_barrel")),
        "energy_source_release_date": energy_row.get("energy_source_release_date"),
        **energy_regime,
        "h1_ask_yoy_pct": _trend_metric(trends, scope_type="sector", company=None, metric="ask", field="yoy_change_pct"),
        "h1_rpk_yoy_pct": _trend_metric(trends, scope_type="sector", company=None, metric="rpk", field="yoy_change_pct"),
        "h1_rpk_minus_ask_growth_gap_pp": (
            _trend_metric(trends, scope_type="sector", company=None, metric="rpk", field="yoy_change_pct")
            - _trend_metric(trends, scope_type="sector", company=None, metric="ask", field="yoy_change_pct")
        ),
        "h1_passengers_yoy_pct": _trend_metric(trends, scope_type="sector", company=None, metric="passengers", field="yoy_change_pct"),
        "h1_passenger_lf_change_pp": _trend_metric(trends, scope_type="sector", company=None, metric="passenger_load_factor_pct", field="yoy_change_abs"),
        "h1_cargo_tonnes_yoy_pct": _trend_metric(trends, scope_type="sector", company=None, metric="cargo_tonnes", field="yoy_change_pct"),
        "h1_freight_lf_change_pp": _trend_metric(trends, scope_type="sector", company=None, metric="freight_load_factor_pct", field="yoy_change_abs"),
        "h1_overall_lf_change_pp": _trend_metric(trends, scope_type="sector", company=None, metric="overall_load_factor_pct", field="yoy_change_abs"),
        "fy2026_revenue_consensus_avg_native_mn": consensus_revenue,
        "fy2026_revenue_consensus_low_native_mn": _sum(mainland, "fy2026_revenue_low_native_mn") if _coverage(mainland, "fy2026_revenue_low_native_mn") == len(mainland) else None,
        "fy2026_revenue_consensus_high_native_mn": _sum(mainland, "fy2026_revenue_high_native_mn") if _coverage(mainland, "fy2026_revenue_high_native_mn") == len(mainland) else None,
        "fy2026_revenue_consensus_coverage_n": revenue_coverage,
        "fy2026_revenue_consensus_avg_usd_mn": consensus_revenue_usd,
        "fy2026_revenue_growth_vs_latest_actual_pct": 100.0 * (consensus_revenue / actual_revenue - 1.0) if consensus_revenue and actual_revenue else None,
        "fy2026_net_profit_consensus_avg_native_mn": consensus_profit,
        "fy2026_net_profit_consensus_low_native_mn": _sum(mainland, "fy2026_net_profit_low_native_mn"),
        "fy2026_net_profit_consensus_high_native_mn": _sum(mainland, "fy2026_net_profit_high_native_mn"),
        "fy2026_net_profit_consensus_coverage_n": profit_coverage,
        "fy2026_net_profit_consensus_avg_usd_mn": consensus_profit_usd,
        "fy2026_net_profit_delta_vs_latest_actual_native_mn": consensus_profit - actual_profit if actual_profit_coverage == len(mainland) else None,
        **formal,
        **warning_stats,
        "hk_broker_company_count": broker_coverage,
        "hk_broker_true_revision_count": broker_revisions,
        "unified_estimate_revision_count": revision_count,
        "unified_up_revision_count": up_revision_count,
        "unified_down_revision_count": down_revision_count,
        "unified_revision_balance": up_revision_count - down_revision_count,
        "unified_revision_company_coverage_n": revision_company_coverage,
        "unified_latest_estimate_revision_date": revision_dates.max().strftime("%Y-%m-%d") if not revision_dates.empty else None,
        "market_cap_to_consensus_revenue_usd": market_cap_to_revenue_usd,
        "consensus_valuation_quality": valuation_quality,
        "source_quality": "derived_sector_aggregate",
        "source_note": (
            "Six-company mainland A-share aggregate in RMB. H1 operating trends are derived from monthly issuer releases; "
            "FY2025 financial actuals and FY2026 consensus are asynchronous company-level layers. "
            f"{profit_coverage_note} "
            f"Passenger-related revenue coverage is {passenger_revenue_coverage}/{len(mainland)}; weighted yield/RASK/CASK "
            "use the available issuer-reported or explicitly derived company unit-economics proxies and are not a pure ticket-only measure. "
            f"Primary cash coverage is {_coverage(mainland, 'latest_report_cash_and_cash_equivalents_native_mn')}/{len(mainland)}, "
            f"total-liabilities coverage is {_coverage(mainland, 'latest_report_total_liabilities_native_mn')}/{len(mainland)}, "
            f"interest-bearing-debt coverage is {_coverage(mainland, 'latest_report_interest_bearing_debt_native_mn')}/{len(mainland)}, "
            f"and cash-capex coverage is {_coverage(mainland, 'latest_report_capex_cash_paid_native_mn')}/{len(mainland)}; "
            "the liabilities-to-assets ratio is retained at company level because it is not additive without total-assets weighting. "
            f"revenue consensus coverage is {revenue_coverage}/{len(mainland)} because Hainan has an average-only fallback. "
            f"Unified estimate revisions total {revision_count} ({up_revision_count} up, {down_revision_count} down) across "
            f"{revision_company_coverage}/{len(mainland)} mainland companies; this is sparse public evidence, not a full consensus tape. "
            "USD consensus and valuation fields use the latest share-class market snapshot; valuation quality is unstable "
            "when any constituent's profit consensus range crosses zero."
        ),
        "retrieved_at": retrieved,
    }

    rows = [aggregate]
    company_rows = bridge.loc[
        bridge["company"].eq("Cathay Pacific")
        | (bridge["company"].isin(CN_COMPANIES) & bridge["market"].eq("CN_A"))
    ].drop_duplicates("company")
    for _, row in company_rows.iterrows():
        rows.append(_company_row(row, trends, events, revisions, energy_regime, retrieved))
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_sector_expectation_snapshot() -> pd.DataFrame:
    result = build_airline_sector_expectation_snapshot()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
