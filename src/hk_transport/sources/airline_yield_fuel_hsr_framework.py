"""Comparable yield, fuel and HSR research layers for mainland airlines.

This module does not invent route fares, realized surcharge recovery or
standalone subsidiary economics. It creates a comparable panel from the
existing primary-report layer and explicit research queues for fields that
remain unavailable or only partially observed.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

DRIVERS_PATH = NORMALIZED_DIR / "airline_earnings_driver_comparability.csv"
FUEL_PATH = NORMALIZED_DIR / "airline_fuel_sensitivity_scenarios.csv"
HEDGE_PATH = NORMALIZED_DIR / "airline_hedging_disclosures.csv"
SURCHARGE_PATH = NORMALIZED_DIR / "airline_fuel_surcharges.parquet"
CANDIDATE_PATH = NORMALIZED_DIR / "airline_hsr_route_candidates.csv"
QUEUE_PATH = NORMALIZED_DIR / "airline_hsr_route_query_queue.csv"
OBSERVATION_PATH = NORMALIZED_DIR / "airline_hsr_route_observations.csv"

YIELD_OUTPUT_PATH = NORMALIZED_DIR / "airline_yield_pricing_matrix.csv"
FUEL_OUTPUT_PATH = NORMALIZED_DIR / "airline_fuel_pass_through_hedge_matrix.csv"
QUEUE_OUTPUT_PATH = NORMALIZED_DIR / "airline_yield_fuel_research_queue.csv"
HSR_OUTPUT_PATH = NORMALIZED_DIR / "airline_hsr_research_coverage.csv"

MAINLAND_COMPANIES = (
    ("Air China", "601111.SH"),
    ("China Southern Airlines", "600029.SH"),
    ("China Eastern Airlines", "600115.SH"),
    ("Spring Airlines", "601021.SH"),
    ("Hainan Airlines Holdings", "600221.SH"),
    ("Juneyao Airlines", "603885.SH"),
)
PERIODS = ("FY2025", "1H2025")


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _date(value: object) -> str:
    text = str(value)[:10]
    return text if len(text) == 10 and text[4] == "-" and text[7] == "-" else "pending"


def _latest_date(frames: list[pd.DataFrame | None], columns: tuple[str, ...]) -> str:
    dates: list[str] = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        for column in columns:
            if column in frame.columns:
                dates.extend(_date(value) for value in frame[column].dropna())
    valid = [value for value in dates if value != "pending"]
    return max(valid) if valid else "pending"


def _driver_row(drivers: pd.DataFrame, company: str, period: str, metric: str) -> pd.Series:
    rows = drivers[
        drivers["company"].eq(company)
        & drivers["statement_period"].eq(period)
        & drivers["canonical_metric"].eq(metric)
        & drivers["value_native"].notna()
    ]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _driver_value(drivers: pd.DataFrame, company: str, period: str, metric: str) -> float | None:
    return _num(_driver_row(drivers, company, period, metric).get("value_native"))


def _driver_scope(drivers: pd.DataFrame, company: str, period: str, metric: str) -> str:
    row = _driver_row(drivers, company, period, metric)
    return str(row.get("metric_scope", "missing")) if not row.empty else "missing"


def _driver_field_source(drivers: pd.DataFrame, company: str, period: str, metric: str) -> tuple[str, str, str]:
    row = _driver_row(drivers, company, period, metric)
    if row.empty:
        return "", "", "pending"
    return str(row.get("source_url", "")), str(row.get("source_page", "")), str(row.get("information_date", ""))


def build_airline_yield_pricing_matrix(
    *, drivers: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    drivers = drivers if drivers is not None else pd.read_csv(DRIVERS_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    for company, ticker in MAINLAND_COMPANIES:
        for period in PERIODS:
            total_revenue = _driver_value(drivers, company, period, "total_revenue")
            passenger_revenue = _driver_value(drivers, company, period, "passenger_revenue")
            cargo_revenue = _driver_value(drivers, company, period, "cargo_revenue")
            rpk = _driver_value(drivers, company, period, "rpk")
            ask = _driver_value(drivers, company, period, "ask")
            reported_yield = _driver_value(drivers, company, period, "passenger_yield")
            derived_yield = passenger_revenue / rpk if passenger_revenue is not None and rpk else None
            yield_url, yield_page, yield_date = _driver_field_source(drivers, company, period, "passenger_yield")
            rev_url, rev_page, rev_date = _driver_field_source(drivers, company, period, "passenger_revenue")
            rpk_url, rpk_page, rpk_date = _driver_field_source(drivers, company, period, "rpk")
            source_urls = "; ".join(dict.fromkeys(value for value in (yield_url, rev_url, rpk_url) if value))
            source_pages = "; ".join(dict.fromkeys(value for value in (yield_page, rev_page, rpk_page) if value))
            rows.append({
                "dataset_id": "airline_yield_pricing_matrix",
                "snapshot_as_of_date": _latest_date([drivers], ("information_date", "period_end")),
                "company": company,
                "ticker": ticker,
                "statement_period": period,
                "period_end": str(_driver_row(drivers, company, period, "total_revenue").get("period_end", "")),
                "report_information_date": max((_date(value) for value in (yield_date, rev_date, rpk_date) if _date(value) != "pending"), default="pending"),
                "metric_scope": _driver_scope(drivers, company, period, "total_revenue"),
                "total_revenue_native_mn": total_revenue,
                "passenger_revenue_native_mn": passenger_revenue,
                "cargo_revenue_native_mn": cargo_revenue,
                "passenger_revenue_mix_pct": 100.0 * passenger_revenue / total_revenue if passenger_revenue is not None and total_revenue else None,
                "cargo_revenue_mix_pct": 100.0 * cargo_revenue / total_revenue if cargo_revenue is not None and total_revenue else None,
                "ask_mn_seat_km": ask,
                "rpk_mn_passenger_km": rpk,
                "passenger_load_factor_pct": _driver_value(drivers, company, period, "passenger_load_factor_pct"),
                "reported_passenger_yield_native": reported_yield,
                "reported_passenger_yield_unit": str(_driver_row(drivers, company, period, "passenger_yield").get("native_unit", "")),
                "derived_passenger_yield_native": derived_yield,
                "derived_yield_unit": "native currency/RPK" if derived_yield is not None else "",
                "yield_difference_reported_minus_derived": reported_yield - derived_yield if reported_yield is not None and derived_yield is not None else None,
                "rask_proxy_native": _driver_value(drivers, company, period, "rask_proxy"),
                "cask_native": _driver_value(drivers, company, period, "cask"),
                "yield_scope": _driver_scope(drivers, company, period, "passenger_yield"),
                "derived_yield_scope": "same_scope_check_required",
                "rask_scope": _driver_scope(drivers, company, period, "rask_proxy"),
                "cask_scope": _driver_scope(drivers, company, period, "cask"),
                "pricing_data_status": (
                    "reported_yield_plus_mix_available" if reported_yield is not None and passenger_revenue is not None
                    else "reported_yield_only" if reported_yield is not None
                    else "derived_yield_only" if derived_yield is not None else "yield_missing"
                ),
                "pricing_research_caveat": "No route-level fare, discount, advance-booking or ancillary-revenue time series is present; passenger yield is issuer-period or derived from passenger revenue/RPK.",
                "source_url": source_urls,
                "source_page": source_pages,
                "source_quality": "primary_issuer_driver_layer",
                "retrieved_at": retrieved,
            })
    result = pd.DataFrame(rows)
    result.to_csv(YIELD_OUTPUT_PATH, index=False)
    return result


def _latest_hedge_rows(hedges: pd.DataFrame, company: str, period: str) -> pd.DataFrame:
    rows = hedges[hedges["company"].eq(company) & hedges["statement_period"].eq(period)].copy()
    if rows.empty:
        return rows
    rows["_date"] = pd.to_datetime(rows["information_date"], errors="coerce")
    return rows.sort_values("_date")


def build_airline_fuel_pass_through_hedge_matrix(
    *, drivers: pd.DataFrame | None = None,
    fuel: pd.DataFrame | None = None,
    hedges: pd.DataFrame | None = None,
    surcharges: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    drivers = drivers if drivers is not None else pd.read_csv(DRIVERS_PATH)
    fuel = fuel if fuel is not None else pd.read_csv(FUEL_PATH)
    hedges = hedges if hedges is not None else pd.read_csv(HEDGE_PATH)
    surcharges = surcharges if surcharges is not None else pd.read_parquet(SURCHARGE_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    mainland_surcharge = surcharges[
        surcharges["carrier_scope"].eq("Mainland China passenger airlines")
        & surcharges["route_band"].isin(["up to 800 km", ">800 km"])
    ].sort_values("effective_from")
    rows: list[dict[str, object]] = []
    for company, ticker in MAINLAND_COMPANIES:
        for period in PERIODS:
            fuel_rows = fuel[fuel["company"].eq(company) & fuel["baseline_period"].eq("FY2025")]
            plus = fuel_rows[pd.to_numeric(fuel_rows["scenario_fuel_price_change_pct"], errors="coerce").eq(5.0)]
            minus = fuel_rows[pd.to_numeric(fuel_rows["scenario_fuel_price_change_pct"], errors="coerce").eq(-5.0)]
            plus = plus.iloc[0] if not plus.empty and period == "FY2025" else pd.Series(dtype=object)
            minus = minus.iloc[0] if not minus.empty and period == "FY2025" else pd.Series(dtype=object)
            hedge_rows = _latest_hedge_rows(hedges, company, period)
            hedge_statuses = ";".join(dict.fromkeys(str(v) for v in hedge_rows.get("hedge_status", pd.Series(dtype=object)).dropna()))
            hedge_types = ";".join(dict.fromkeys(str(v) for v in hedge_rows.get("disclosure_type", pd.Series(dtype=object)).dropna()))
            numeric_hedge = hedge_rows[hedge_rows["notional_native"].notna() | hedge_rows["fair_value_change_native"].notna()] if not hedge_rows.empty else pd.DataFrame()
            notional_rows = hedge_rows[hedge_rows["notional_native"].notna()] if not hedge_rows.empty else pd.DataFrame()
            fair_rows = hedge_rows[hedge_rows["fair_value_change_native"].notna() | hedge_rows["fair_value_end_native"].notna()] if not hedge_rows.empty else pd.DataFrame()
            notional = _num(notional_rows.iloc[-1].get("notional_native")) if not notional_rows.empty else None
            notional_unit = str(notional_rows.iloc[-1].get("notional_unit", "")) if not notional_rows.empty else ""
            fair_change = _num(fair_rows.iloc[-1].get("fair_value_change_native")) if not fair_rows.empty else None
            fair_end = _num(fair_rows.iloc[-1].get("fair_value_end_native")) if not fair_rows.empty else None
            hedge_source = str(hedge_rows.iloc[-1].get("source_url", "")) if not hedge_rows.empty else ""
            hedge_page = str(hedge_rows.iloc[-1].get("source_page", "")) if not hedge_rows.empty else ""
            up800 = mainland_surcharge[mainland_surcharge["route_band"].eq(">800 km")]
            short = mainland_surcharge[mainland_surcharge["route_band"].eq("up to 800 km")]
            latest_surcharge_date = str(mainland_surcharge.iloc[-1].get("effective_from", "")) if not mainland_surcharge.empty else ""
            rows.append({
                "dataset_id": "airline_fuel_pass_through_hedge_matrix",
                "snapshot_as_of_date": _latest_date([drivers, fuel, hedges, surcharges], ("information_date", "jet_fuel_observation_date", "effective_from")),
                "company": company, "ticker": ticker, "statement_period": period,
                "fuel_cost_native_mn": _driver_value(drivers, company, period, "fuel_cost"),
                "fuel_cost_share_pct": _driver_value(drivers, company, period, "fuel_cost_share_pct"),
                "fuel_cost_per_ask_native": _driver_value(drivers, company, period, "fuel_cost_per_ask"),
                "plus5_pre_tax_profit_impact_usd_mn": _num(plus.get("pre_tax_profit_impact_usd_mn")),
                "minus5_pre_tax_profit_impact_usd_mn": _num(minus.get("pre_tax_profit_impact_usd_mn")),
                "sensitivity_method": str(plus.get("scenario_method", "not_available")),
                "issuer_sensitivity_available": bool(plus.get("issuer_sensitivity_available", False)) if not plus.empty else False,
                "jet_fuel_observation_date": str(plus.get("jet_fuel_observation_date", "")) if not plus.empty else "",
                "hedge_status": hedge_statuses or "no_hedging_row_for_period",
                "hedge_disclosure_types": hedge_types,
                "numeric_hedge_anchor_available": bool(not numeric_hedge.empty),
                "hedge_notional_native": notional,
                "hedge_notional_unit": notional_unit,
                "hedge_fair_value_change_native": fair_change,
                "hedge_fair_value_end_native": fair_end,
                "hedge_source_url": hedge_source,
                "hedge_source_page": hedge_page,
                "surcharge_gt800_current_cny": _num(up800.iloc[-1].get("current_value")) if not up800.empty else None,
                "surcharge_upto800_current_cny": _num(short.iloc[-1].get("current_value")) if not short.empty else None,
                "surcharge_effective_from": latest_surcharge_date,
                "pass_through_status": "schedule_context_only_no_realized_recovery",
                "pass_through_research_gap": "Need route-level surcharge eligibility, passenger-volume pass-through and realized fuel recovery; current schedule is policy context only.",
                "hedge_research_gap": "Numeric hedge anchor is not available for most names; scan-result/no-futures/policy rows must not be read as zero hedge cost.",
                "fuel_scope": _driver_scope(drivers, company, period, "fuel_cost"),
                "source_quality": "primary_driver_plus_hedge_scan_and_policy_schedule",
                "source_paths": ";".join(str(path) for path in (DRIVERS_PATH, FUEL_PATH, HEDGE_PATH, SURCHARGE_PATH)),
                "retrieved_at": retrieved,
            })
    result = pd.DataFrame(rows)
    result.to_csv(FUEL_OUTPUT_PATH, index=False)
    return result


def build_airline_yield_fuel_research_queue(
    *, yield_matrix: pd.DataFrame | None = None,
    fuel_matrix: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    yield_matrix = yield_matrix if yield_matrix is not None else pd.read_csv(YIELD_OUTPUT_PATH) if YIELD_OUTPUT_PATH.exists() else build_airline_yield_pricing_matrix()
    fuel_matrix = fuel_matrix if fuel_matrix is not None else pd.read_csv(FUEL_OUTPUT_PATH) if FUEL_OUTPUT_PATH.exists() else build_airline_fuel_pass_through_hedge_matrix()
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    needs = [
        ("route_fare_time_series", "yield_pricing", "high", "missing_free_pit_series", "Dated OTA/Ctrip flight-fare snapshots or issuer regional yield disclosure", "Revenue/yield bridge remains company-period only"),
        ("advance_booking_and_fare_class", "yield_pricing", "medium", "missing", "Dated booking-window, fare-class or load-factor observations", "Demand volume may not translate into realized pricing"),
        ("ancillary_revenue", "yield_pricing", "medium", "not_separately_disclosed", "Issuer note extraction plus ancillary KPI disclosures", "RASK proxy may mix ticket, cargo and ancillary revenue"),
        ("domestic_international_yield_split", "yield_pricing", "high", "partial", "Issuer regional traffic/yield tables; route-level fare snapshots", "International mix can distort group yield comparison"),
        ("realized_fuel_surcharge_recovery", "fuel_pass_through", "high", "schedule_only", "Join effective surcharge policy to eligible passenger traffic and reported fuel cost", "Published surcharge is not realized fuel-cost recovery"),
        ("hedge_notional_and_realized_pnl", "fuel_hedging", "high", "partial_report_scan", "Primary interim/annual risk-note extraction; preserve notional, fair value and realized P&L separately", "Mechanical fuel sensitivity may overstate or understate earnings impact"),
        ("nonfuel_unit_cost", "fuel_pass_through", "medium", "partial", "Issuer ATK/nonfuel cost rows, labor, lease, maintenance and airport costs", "CASK change cannot be attributed to fuel alone"),
        ("fuel_contract_and_fx_lag", "fuel_pass_through", "medium", "missing", "Contract terms, purchase timing and route/currency exposure from filings", "Spot fuel benchmark may not match accounting fuel expense"),
    ]
    rows: list[dict[str, object]] = []
    for company, ticker in MAINLAND_COMPANIES:
        pricing_rows = yield_matrix[yield_matrix["company"].eq(company)]
        fuel_rows = fuel_matrix[fuel_matrix["company"].eq(company)]
        pricing_status = ";".join(dict.fromkeys(str(v) for v in pricing_rows["pricing_data_status"].dropna()))
        for need, category, priority, status, source_strategy, implication in needs:
            current_status = status
            evidence = ""
            if need == "hedge_notional_and_realized_pnl" and not fuel_rows.empty and fuel_rows["numeric_hedge_anchor_available"].any():
                current_status = "numeric_anchor_available_for_some_periods"
            elif need == "domestic_international_yield_split" and pricing_status:
                current_status = "company_period_yield_only_regional_split_pending"
            elif need == "nonfuel_unit_cost":
                current_status = "partial_primary_report_coverage"
            evidence = pricing_status if category == "yield_pricing" else ";".join(dict.fromkeys(str(v) for v in fuel_rows["hedge_status"].dropna()))
            rows.append({
                "dataset_id": "airline_yield_fuel_research_queue",
                "snapshot_as_of_date": _latest_date([yield_matrix, fuel_matrix], ("snapshot_as_of_date",)),
                "company": company, "ticker": ticker, "research_need": need,
                "category": category, "priority": priority, "current_status": current_status,
                "current_evidence": evidence, "source_strategy": source_strategy,
                "why_it_matters": implication, "validation_output": "dated_source_row_with_unit_scope_and_information_date",
                "source_quality": "research_gap_contract", "retrieved_at": retrieved,
            })
    result = pd.DataFrame(rows)
    result.to_csv(QUEUE_OUTPUT_PATH, index=False)
    return result


def build_airline_hsr_research_coverage(
    *, candidates: pd.DataFrame | None = None,
    queue: pd.DataFrame | None = None,
    observations: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    candidates = candidates if candidates is not None else pd.read_csv(CANDIDATE_PATH)
    queue = queue if queue is not None else pd.read_csv(QUEUE_PATH)
    observations = observations if observations is not None else pd.read_csv(OBSERVATION_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    for index, (company, ticker) in enumerate(MAINLAND_COMPANIES, start=1):
        c = candidates[candidates["company"].eq(company)]
        q = queue[queue["company"].eq(company)]
        o = observations[observations["company"].eq(company)]
        verified = o[o["route_observation_status"].eq("verified_snapshot")] if not o.empty else pd.DataFrame()
        weighted = q[q["hsr_ask_weighted_exposure"].notna()] if not q.empty else pd.DataFrame()
        if c.empty:
            status = "no_route_candidates_extracted_yet"
            next_action = "Parse dated domestic new-route details from issuer monthly bulletins, then create direct-rail query legs"
            priority = "high" if company in {"Air China", "Hainan Airlines Holdings"} else "medium"
        elif verified.empty or weighted.empty:
            status = "partial_route_panel_missing_rail_or_ask_weight"
            next_action = "Fill dated train time/fare/frequency, airport-station access and route ASK weights; preserve no-direct-train as not-applicable only when geography is verified"
            priority = "high" if company in {"Spring Airlines", "Juneyao Airlines"} else "medium"
        else:
            status = "partial_route_panel_with_verified_observations"
            next_action = "Expand route sample and add repeated observations across holiday/season windows"
            priority = "medium"
        rows.append({
            "dataset_id": "airline_hsr_research_coverage",
            # `observation_date` can be a future travel date for a fare/train
            # snapshot.  The PIT cutoff is the source/query `as_of_date`, not
            # the date of the journey being observed.
            "snapshot_as_of_date": _latest_date([candidates, queue, observations], ("as_of_date",)),
            "company": company, "ticker": ticker, "priority": priority,
            "candidate_route_count": len(c), "query_leg_count": len(q),
            "verified_observation_count": len(verified), "ask_weighted_leg_count": len(weighted),
            "hsr_substitution_score_available": int(q["hsr_substitution_score"].notna().sum()) if not q.empty else 0,
            "coverage_status": status, "next_action": next_action,
            "current_caveat": "Route candidates are event-driven, not a complete route universe; missing candidates do not mean no HSR exposure.",
            "source_paths": ";".join(str(path) for path in (CANDIDATE_PATH, QUEUE_PATH, OBSERVATION_PATH)),
            "source_quality": "derived_route_coverage_contract", "retrieved_at": retrieved,
        })
    result = pd.DataFrame(rows)
    result.to_csv(HSR_OUTPUT_PATH, index=False)
    return result


def fetch_airline_yield_fuel_hsr_framework() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    yield_matrix = build_airline_yield_pricing_matrix()
    fuel_matrix = build_airline_fuel_pass_through_hedge_matrix()
    research_queue = build_airline_yield_fuel_research_queue(yield_matrix=yield_matrix, fuel_matrix=fuel_matrix)
    hsr_coverage = build_airline_hsr_research_coverage()
    return yield_matrix, fuel_matrix, research_queue, hsr_coverage
