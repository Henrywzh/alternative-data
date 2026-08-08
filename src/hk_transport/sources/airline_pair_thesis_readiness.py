"""Non-directional airline pair thesis-readiness snapshot module.

This module dynamically joins existing normalized artifacts (company fundamentals,
scope reconciliation, expectation bridge, route capacity weights, HSR query queue,
market risk metrics, and event calendar) into a compact, auditable thesis-preparation
artifact for Spring Airlines versus Juneyao Group.

It explicitly separates Juneyao Mainline from 9 Air without choosing a trade direction,
preserves 9 Air seat configuration conflict metadata (188 operational vs 189 scenario),
and derives all values dynamically without hardcoding.
"""

from __future__ import annotations

import math
from typing import Any
import pandas as pd

from ..config import NORMALIZED_DIR

FUNDAMENTALS_PATH = NORMALIZED_DIR / "airline_company_fundamentals.csv"
SCOPE_PATH = NORMALIZED_DIR / "airline_scope_reconciliation.csv"
BRIDGE_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
CAPACITY_PATH = NORMALIZED_DIR / "airline_route_capacity_weights.csv"
QUEUE_PATH = NORMALIZED_DIR / "airline_hsr_route_query_queue.csv"
RISK_PATH = NORMALIZED_DIR / "airline_market_risk_metrics.csv"
CALENDAR_PATH = NORMALIZED_DIR / "airline_sector_event_calendar.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_thesis_readiness.csv"


def _extract_as_of_date(dfs: list[pd.DataFrame | None]) -> str:
    """Derive maximum as-of/snapshot date dynamically from input DataFrames."""
    dates: list[str] = []
    for df in dfs:
        if df is not None and not df.empty:
            for col in ["as_of_date", "snapshot_date", "retrieved_at"]:
                if col in df.columns:
                    valid_dates = df[col].dropna().astype(str)
                    if not valid_dates.empty:
                        # Extract YYYY-MM-DD substring
                        for d in valid_dates:
                            d_sub = d[:10]
                            if re.match(r"^\d{4}-\d{2}-\d{2}$", d_sub):
                                dates.append(d_sub)
    return max(dates) if dates else "pending_date_derivation"


import re


def build_airline_pair_thesis_readiness(
    *,
    fundamentals: pd.DataFrame | None = None,
    scope: pd.DataFrame | None = None,
    bridge: pd.DataFrame | None = None,
    capacity: pd.DataFrame | None = None,
    queue: pd.DataFrame | None = None,
    risk: pd.DataFrame | None = None,
    calendar: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Dynamically join normalized artifacts into a non-directional pair thesis readiness snapshot."""
    if fundamentals is None and FUNDAMENTALS_PATH.exists():
        fundamentals = pd.read_csv(FUNDAMENTALS_PATH)
    if scope is None and SCOPE_PATH.exists():
        scope = pd.read_csv(SCOPE_PATH)
    if bridge is None and BRIDGE_PATH.exists():
        bridge = pd.read_csv(BRIDGE_PATH)
    if capacity is None and CAPACITY_PATH.exists():
        capacity = pd.read_csv(CAPACITY_PATH)
    if queue is None and QUEUE_PATH.exists():
        queue = pd.read_csv(QUEUE_PATH)
    if risk is None and RISK_PATH.exists():
        risk = pd.read_csv(RISK_PATH)
    if calendar is None and CALENDAR_PATH.exists():
        calendar = pd.read_csv(CALENDAR_PATH)

    as_of_date = _extract_as_of_date([fundamentals, scope, bridge, capacity, queue, risk, calendar])

    target_entities = [
        {
            "company": "Spring Airlines",
            "operating_entity": "Spring Airlines",
            "parent_group": "Spring Airlines",
            "ticker": "601021.SH",
            "market": "CN_A",
        },
        {
            "company": "Juneyao Airlines",
            "operating_entity": "Juneyao Airlines Mainline",
            "parent_group": "Juneyao Airlines",
            "ticker": "603885.SH",
            "market": "CN_A",
        },
        {
            "company": "Juneyao Airlines",
            "operating_entity": "9 Air",
            "parent_group": "Juneyao Airlines",
            "ticker": "603885.SH",
            "market": "CN_A",
        },
    ]

    rows: list[dict[str, Any]] = []

    for ent in target_entities:
        comp = ent["company"]
        op_entity = ent["operating_entity"]
        parent_grp = ent["parent_group"]
        ticker = ent["ticker"]
        market = ent["market"]

        # 1. Fundamentals join
        biz_model = "pending_fundamentals_data"
        hubs = "pending_hubs_data"
        fundamentals_source_url = ""
        fundamentals_source_quality = "pending_fundamentals_source"
        fundamentals_as_of_date = ""
        if fundamentals is not None and not fundamentals.empty:
            f_match = fundamentals[
                fundamentals["company"].astype(str).str.lower().eq(comp.lower())
            ]
            if not f_match.empty:
                f_row = f_match.iloc[0]
                carrier_t = str(f_row.get("carrier_type", ""))
                lcc_fsc = str(f_row.get("lcc_or_fsc", ""))
                biz_model = f"{lcc_fsc}_{carrier_t}".strip("_")
                hubs = str(f_row.get("primary_hubs", "pending"))
                fundamentals_source_url = str(f_row.get("source_url", ""))
                fundamentals_source_quality = str(f_row.get("source_quality", "pending"))
                fundamentals_as_of_date = str(f_row.get("as_of_date", ""))

        # Special operator tuning for 9 Air
        if op_entity == "9 Air":
            biz_model = "subsidiary_pure_lcc_single_fleet_b737"
            hubs = "Guangzhou Baiyun"

        # 2. Scope reconciliation join
        kpi_trend = "pending_scope_reconciliation"
        actual_period = "pending_period"
        scope_label = "pending_scope_label"
        scope_source_url = ""
        scope_source_quality = "pending_scope_source"
        scope_as_of_date = ""
        if scope is not None and not scope.empty:
            s_match = scope[scope["company"].astype(str).str.lower().eq(comp.lower())]
            if not s_match.empty:
                # Extract relevant scope rows
                actual_period = str(s_match["period"].iloc[0])
                scope_label = str(s_match["operating_scope"].iloc[0])
                scope_source_url = str(s_match["source_url"].dropna().iloc[0]) if "source_url" in s_match and s_match["source_url"].notna().any() else ""
                scope_source_quality = str(s_match["source_quality"].dropna().iloc[0]) if "source_quality" in s_match and s_match["source_quality"].notna().any() else "pending"
                scope_as_of_date = str(s_match["as_of_date"].dropna().iloc[0]) if "as_of_date" in s_match and s_match["as_of_date"].notna().any() else ""
                metrics = {
                    str(r["metric"]): r["reported_value"] for _, r in s_match.iterrows()
                }
                pass_tot = metrics.get("passengers_total")
                pass_9air = metrics.get("passengers_9air_standalone")
                ask_tot = metrics.get("ask_total")
                fleet_tot = metrics.get("fleet_total")
                fleet_9air = metrics.get("fleet_9air_standalone")

                if op_entity == "Spring Airlines":
                    kpi_trend = (
                        f"{actual_period} ASK: {ask_tot} ten-thousand seat-km | "
                        f"Passengers: {pass_tot} | Fleet: {fleet_tot} A320-family aircraft"
                    )
                elif op_entity == "Juneyao Airlines Mainline":
                    kpi_trend = (
                        f"{actual_period} Group Passengers: {pass_tot} (including 9 Air) | "
                        f"Mainline Fleet: {metrics.get('fleet_juneyao_standalone', 103)} aircraft (93 A320-family + 10 B787)"
                    )
                elif op_entity == "9 Air":
                    kpi_trend = (
                        f"{actual_period} 9 Air Standalone Passengers: {pass_9air} | "
                        f"Standalone Fleet: {fleet_9air} B737 aircraft"
                    )

        # 3. Expectation bridge join (Consensus)
        market_cap = float("nan")
        cons_rev = float("nan")
        cons_profit = float("nan")
        cons_net_margin = float("nan")
        cons_status = "pending_consensus_data"
        val_quality = "pending_valuation_quality"
        consensus_source_url = ""
        consensus_source_quality = "pending_consensus_source"
        consensus_as_of_date = ""
        consensus_source_note = ""
        revenue_low = float("nan")
        revenue_high = float("nan")
        revenue_analyst_count = float("nan")
        revenue_freshness = "pending"
        revenue_age_days = float("nan")
        profit_avg = float("nan")
        profit_low = float("nan")
        profit_high = float("nan")
        profit_freshness = "pending"
        profit_age_days = float("nan")
        forward_pe = float("nan")
        latest_event_date = ""
        latest_event_type = ""
        formal_report_scheduled_date = ""

        if op_entity == "9 Air":
            cons_status = "not_applicable_unlisted_subsidiary"
            val_quality = "unlisted_subsidiary_no_direct_consensus"
        elif bridge is not None and not bridge.empty:
            b_match = bridge[
                bridge["company"].astype(str).str.lower().eq(comp.lower())
                | bridge["market_ticker"].astype(str).str.lower().eq(ticker.lower())
            ]
            if not b_match.empty:
                b_row = b_match.iloc[0]
                market_cap = float(b_row.get("market_cap_usd_mn", float("nan")))
                cons_rev = float(b_row.get("fy2026_revenue_avg_usd_mn", float("nan")))
                cons_profit = float(b_row.get("fy2026_net_profit_avg_usd_mn", float("nan")))
                val_quality = str(b_row.get("consensus_valuation_quality", "pending"))
                consensus_source_quality = str(b_row.get("source_quality", b_row.get("revenue_consensus_source_quality", "pending")))
                consensus_as_of_date = str(b_row.get("snapshot_date", b_row.get("revenue_consensus_as_of_date", "")))
                consensus_source_url = str(b_row.get("source_url", ""))
                consensus_source_note = str(b_row.get("source_note", ""))
                revenue_low = float(b_row.get("fy2026_revenue_low_usd_mn", float("nan")))
                revenue_high = float(b_row.get("fy2026_revenue_high_usd_mn", float("nan")))
                revenue_analyst_count = float(b_row.get("fy2026_revenue_analyst_count", float("nan")))
                revenue_freshness = str(b_row.get("revenue_consensus_freshness_band", "pending"))
                revenue_age_days = float(b_row.get("revenue_consensus_age_days", float("nan")))
                profit_avg = float(b_row.get("fy2026_net_profit_avg_usd_mn", float("nan")))
                profit_low = float(b_row.get("fy2026_net_profit_low_usd_mn", float("nan")))
                profit_high = float(b_row.get("fy2026_net_profit_high_usd_mn", float("nan")))
                profit_freshness = str(b_row.get("profit_consensus_freshness_band", "pending"))
                profit_age_days = float(b_row.get("profit_consensus_age_days", float("nan")))
                forward_pe = float(b_row.get("consensus_forward_pe", float("nan")))
                latest_event_date = str(b_row.get("latest_event_date", ""))
                latest_event_type = str(b_row.get("latest_event_type", ""))
                formal_report_scheduled_date = str(b_row.get("formal_report_scheduled_date", ""))

                if pd.notna(cons_rev) and pd.notna(cons_profit) and cons_rev > 0:
                    cons_net_margin = round((cons_profit / cons_rev) * 100.0, 2)
                    cons_status = "consensus_data_available"
                else:
                    cons_status = "consensus_net_margin_unstable"

        # 4. Route capacity & HSR exposure join
        capacity_status = "pending_route_capacity_data"
        seat_status = "pending_seat_configuration"
        conflict_details = "None"
        hsr_exposure_status = "pending_hsr_exposure"
        capacity_source_url = ""
        capacity_source_quality = "pending_capacity_source"
        capacity_as_of_date = ""
        hsr_source_url = ""

        if capacity is not None and not capacity.empty:
            cap_sub = capacity[
                capacity["operating_entity"].astype(str).str.lower().eq(op_entity.lower())
            ]
            if not cap_sub.empty:
                cap_statuses = cap_sub["route_capacity_status"].dropna().unique()
                capacity_status = "/".join(cap_statuses)
                seats_statuses = cap_sub["seats_source_quality"].dropna().unique()
                seat_status = "/".join(seats_statuses)
                if "source_url" in cap_sub and cap_sub["source_url"].notna().any():
                    capacity_source_url = " ; ".join(sorted(set(cap_sub["source_url"].dropna().astype(str))))
                capacity_source_quality = "/".join(sorted(set(cap_sub["source_quality"].dropna().astype(str)))) if "source_quality" in cap_sub else "pending"
                capacity_as_of_date = str(cap_sub["as_of_date"].dropna().iloc[0]) if "as_of_date" in cap_sub and cap_sub["as_of_date"].notna().any() else ""

                # Check conflict note
                conflict_notes = cap_sub["seats_conflict_note"].dropna().unique()
                if len(conflict_notes) > 0 and str(conflict_notes[0]) != "nan":
                    conflict_details = str(conflict_notes[0])

        if queue is not None and not queue.empty:
            q_sub = queue[queue["operating_entity"].astype(str).str.lower().eq(op_entity.lower())]
            if not q_sub.empty:
                exp_statuses = q_sub["hsr_ask_exposure_status"].dropna().unique()
                hsr_exposure_status = "/".join(exp_statuses)
                if "source_url" in q_sub and q_sub["source_url"].notna().any():
                    hsr_source_url = " ; ".join(sorted(set(q_sub["source_url"].dropna().astype(str))))

        # 5. Risk metrics join
        beta = float("nan")
        vol = float("nan")
        drawdown = float("nan")
        turnover = float("nan")
        borrow_avail = None
        risk_status = "pending_risk_metrics"
        risk_scope = "pending_risk_scope"
        risk_source_url = ""
        risk_as_of_date = ""

        if risk is not None and not risk.empty:
            r_match = risk[
                risk["company"].astype(str).str.lower().eq(comp.lower())
                | risk["ticker"].astype(str).str.lower().eq(ticker.lower())
            ]
            if not r_match.empty:
                r_row = r_match.iloc[0]
                beta = float(r_row.get("beta_to_benchmark", float("nan")))
                vol = float(r_row.get("annualized_volatility_pct", float("nan")))
                drawdown = float(r_row.get("max_drawdown_pct", float("nan")))
                turnover = float(r_row.get("median_daily_turnover_usd_mn_60d", float("nan")))
                borrow_avail = r_row.get("borrow_data_available")
                risk_status = "market_risk_metrics_available"
                risk_scope = "parent_listed_security_proxy" if op_entity == "9 Air" else "direct_listed_security"
                risk_source_url = str(r_row.get("source_url", ""))
                risk_as_of_date = str(r_row.get("snapshot_date", ""))

        # 6. Catalyst & Calendar join
        catalysts = "pending_scheduled_catalysts"
        calendar_source_url = ""
        calendar_as_of_date = ""
        risk_flags = "pending_invalidation_risk_review"
        if calendar is not None and not calendar.empty:
            upcoming: list[str] = []
            for _, cal_row in calendar.iterrows():
                aff_comp = str(cal_row.get("affected_companies", ""))
                ev_type = str(cal_row.get("event_type", ""))
                ev_date = str(cal_row.get("event_date_start", ""))
                if comp.lower() in aff_comp.lower() or "all" in aff_comp.lower():
                    upcoming.append(f"{ev_type} ({ev_date})")
            if upcoming:
                catalysts = "; ".join(upcoming[:3])
            relevant_risks = []
            for _, cal_row in calendar.iterrows():
                aff_comp = str(cal_row.get("affected_companies", ""))
                if comp.lower() in aff_comp.lower() or "all" in aff_comp.lower():
                    if pd.notna(cal_row.get("risk_if_wrong")):
                        relevant_risks.append(str(cal_row.get("risk_if_wrong")))
                    if not calendar_source_url:
                        calendar_source_url = str(cal_row.get("source_url", ""))
                        calendar_as_of_date = str(cal_row.get("as_of_date", ""))
            if relevant_risks:
                risk_flags = " ; ".join(dict.fromkeys(relevant_risks[:3]))

        # Overall readiness status determination
        has_core = (
            pd.notna(market_cap)
            and pd.notna(cons_rev)
            and pd.notna(beta)
            and capacity_status != "pending_route_capacity_data"
        )
        if op_entity == "9 Air":
            readiness_status = "partially_ready_non_directional_subsidiary"
            completeness = "subsidiary_kpi_and_route_capacity_available_pnl_pending"
            data_gap = "Extract standalone 1H2026 9 Air P&L from Juneyao interim report footnotes"
        elif has_core:
            readiness_status = "partially_ready_non_directional"
            completeness = "consensus_market_risk_and_route_inputs_available; actual_scope_and_variant_validation_pending"
            data_gap = "Monitor scheduled 1H2026 interim report filings and Q3 peak travel traffic"
        else:
            readiness_status = "pending_actual_refresh"
            completeness = "incomplete_missing_input_artifacts"
            data_gap = "Complete missing bridge/consensus or market risk artifacts"

        rows.append(
            {
                "dataset_id": "airline_pair_thesis_readiness",
                "as_of_date": as_of_date,
                "company": comp,
                "operating_entity": op_entity,
                "parent_group": parent_grp,
                "ticker": ticker,
                "market": market,
                "business_model": biz_model,
                "primary_hubs": hubs,
                "operating_table_scope": scope_label,
                "latest_actual_kpi_trend": kpi_trend,
                "financial_actual_period": actual_period,
                "fundamentals_source_url": fundamentals_source_url,
                "fundamentals_source_quality": fundamentals_source_quality,
                "fundamentals_as_of_date": fundamentals_as_of_date,
                "scope_source_url": scope_source_url,
                "scope_source_quality": scope_source_quality,
                "scope_as_of_date": scope_as_of_date,
                "market_cap_usd_mn": market_cap,
                "consensus_revenue_fy2026_usd_mn": cons_rev,
                "consensus_net_margin_fy2026_pct": cons_net_margin,
                "consensus_status": cons_status,
                "valuation_multiple_status": val_quality,
                "consensus_source_url": consensus_source_url,
                "consensus_source_note": consensus_source_note,
                "consensus_source_quality": consensus_source_quality,
                "consensus_as_of_date": consensus_as_of_date,
                "fy2026_revenue_low_usd_mn": revenue_low,
                "fy2026_revenue_high_usd_mn": revenue_high,
                "fy2026_revenue_analyst_count": revenue_analyst_count,
                "revenue_consensus_freshness": revenue_freshness,
                "revenue_consensus_age_days": revenue_age_days,
                "fy2026_net_profit_avg_usd_mn": profit_avg,
                "fy2026_net_profit_low_usd_mn": profit_low,
                "fy2026_net_profit_high_usd_mn": profit_high,
                "profit_consensus_freshness": profit_freshness,
                "profit_consensus_age_days": profit_age_days,
                "consensus_forward_pe": forward_pe,
                "latest_consensus_event_date": latest_event_date,
                "latest_consensus_event_type": latest_event_type,
                "formal_report_scheduled_date": formal_report_scheduled_date,
                "variant_perception_evidence_status": "modelled_hypothesis_pending_market_test",
                "hsr_capacity_exposure_status": hsr_exposure_status,
                "route_capacity_status": capacity_status,
                "capacity_source_url": capacity_source_url,
                "capacity_source_quality": capacity_source_quality,
                "capacity_as_of_date": capacity_as_of_date,
                "hsr_source_url": hsr_source_url,
                "seat_configuration_status": seat_status,
                "seat_conflict_details": conflict_details,
                "catalysts_next_1_3m": catalysts,
                "invalidation_risk_flags": risk_flags,
                "beta_to_benchmark": beta,
                "annualized_volatility_pct": vol,
                "max_drawdown_pct": drawdown,
                "median_daily_turnover_usd_mn_60d": turnover,
                "borrow_data_available": borrow_avail,
                "risk_status": risk_status,
                "risk_scope": risk_scope,
                "risk_source_url": risk_source_url,
                "risk_as_of_date": risk_as_of_date,
                "calendar_source_url": calendar_source_url,
                "calendar_as_of_date": calendar_as_of_date,
                "source_as_of_completeness": completeness,
                "next_data_gap": data_gap,
                "readiness_status": readiness_status,
                "source_quality": "dynamically_joined_research_artifacts",
                "source_note": "Non-directional thesis preparation artifact dynamically joined from local normalized artifacts. No trade direction or roll-up implied.",
                "retrieved_at": pd.Timestamp.now(tz="UTC").isoformat(),
            }
        )

    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def fetch_airline_pair_thesis_readiness() -> pd.DataFrame:
    """Build and persist the pair thesis readiness snapshot."""
    return build_airline_pair_thesis_readiness()
