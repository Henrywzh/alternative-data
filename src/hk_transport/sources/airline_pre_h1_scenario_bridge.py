"""Pre-H1, non-directional scenario bridge for Spring versus Juneyao.

This is a mechanical stress-test layer, not an independent forecast or trade
recommendation. It combines FY2025 actuals, current FY2026 consensus, the
latest issuer monthly operating diagnostics, a separate fuel-price overlay,
and the scheduled 1H2026 report catalyst.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

HISTORICAL_PATH = NORMALIZED_DIR / "airline_historical_earnings_bridge.csv"
EXPECTATION_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
OPERATING_PATH = NORMALIZED_DIR / "airline_operating_diagnostics.csv"
FUEL_PATH = NORMALIZED_DIR / "airline_fuel_sensitivity_scenarios.csv"
CALENDAR_PATH = NORMALIZED_DIR / "airline_sector_event_calendar.csv"
SECTOR_PATH = NORMALIZED_DIR / "airline_sector_expectation_snapshot.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pre_h1_scenario_bridge.csv"

SCENARIOS = {
    "bear": {"revenue_delta_pct": -5.0, "margin_delta_pp": -2.0, "fuel_shock_pct": 5.0},
    "base": {"revenue_delta_pct": 0.0, "margin_delta_pp": 0.0, "fuel_shock_pct": 0.0},
    "bull": {"revenue_delta_pct": 5.0, "margin_delta_pp": 2.0, "fuel_shock_pct": -5.0},
}


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _date_from_frames(frames: list[pd.DataFrame | None]) -> str:
    dates: list[str] = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        for column in ("snapshot_date", "as_of_date", "retrieved_at"):
            if column in frame.columns:
                for value in frame[column].dropna().astype(str):
                    candidate = value[:10]
                    if len(candidate) == 10 and candidate[4] == "-" and candidate[7] == "-":
                        dates.append(candidate)
    return max(dates) if dates else "pending_date_derivation"


def build_airline_pre_h1_scenario_bridge(
    *,
    historical: pd.DataFrame | None = None,
    expectations: pd.DataFrame | None = None,
    operating: pd.DataFrame | None = None,
    fuel: pd.DataFrame | None = None,
    calendar: pd.DataFrame | None = None,
    sector: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build six rows: three scenarios for each core listed airline."""
    historical = historical if historical is not None else pd.read_csv(HISTORICAL_PATH)
    expectations = expectations if expectations is not None else pd.read_csv(EXPECTATION_PATH)
    operating = operating if operating is not None else pd.read_csv(OPERATING_PATH)
    fuel = fuel if fuel is not None else pd.read_csv(FUEL_PATH)
    calendar = calendar if calendar is not None else pd.read_csv(CALENDAR_PATH)
    sector = sector if sector is not None else pd.read_csv(SECTOR_PATH)

    companies = ["Spring Airlines", "Juneyao Airlines"]
    as_of = _date_from_frames([historical, expectations, operating, fuel, calendar, sector])
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    base_rows: list[dict[str, object]] = []

    for company in companies:
        hist = historical[
            historical["company"].eq(company)
            & historical["period_end"].astype(str).eq("2025-12-31")
        ]
        exp = expectations[expectations["company"].eq(company)]
        op = operating[operating["company"].eq(company)]
        fuel_company = fuel[fuel["company"].eq(company)]
        sector_company = sector[sector["company"].eq(company)]
        hist_row = hist.iloc[0] if not hist.empty else pd.Series(dtype=object)
        exp_row = exp.iloc[0] if not exp.empty else pd.Series(dtype=object)
        op_row = op.iloc[0] if not op.empty else pd.Series(dtype=object)
        sector_row = sector_company.iloc[0] if not sector_company.empty else pd.Series(dtype=object)

        revenue = _num(exp_row.get("fy2026_revenue_avg_usd_mn"))
        profit = _num(exp_row.get("fy2026_net_profit_avg_usd_mn"))
        margin = 100.0 * profit / revenue if revenue not in (None, 0) and profit is not None else None
        scheduled = str(exp_row.get("formal_report_scheduled_date", ""))
        latest_event_date = str(exp_row.get("latest_event_date", ""))
        latest_event_type = str(exp_row.get("latest_event_type", ""))
        warning_date = str(exp_row.get("latest_event_date", "")) if str(exp_row.get("latest_event_type", "")) == "earnings_warning" else ""
        warning_low_native = _num(exp_row.get("latest_event_value_min")) if warning_date else None
        warning_high_native = _num(exp_row.get("latest_event_value_max")) if warning_date else None
        warning_mid_native = (
            (warning_low_native + warning_high_native) / 2.0
            if warning_low_native is not None and warning_high_native is not None
            else None
        )
        warning_to_consensus_status = "no_earnings_warning_available"
        if warning_date:
            latest_profit_consensus_date = str(exp_row.get("profit_consensus_latest_observation_date", ""))
            warning_to_consensus_status = (
                "warning_after_latest_profit_consensus_observation"
                if latest_profit_consensus_date and latest_profit_consensus_date < warning_date
                else "warning_and_consensus_date_alignment_pending"
            )
        consensus_profit_native = _num(exp_row.get("fy2026_net_profit_avg_native_mn"))
        fx_native_to_usd = profit / consensus_profit_native if profit is not None and consensus_profit_native not in (None, 0) else None
        implied_h2_low_native = consensus_profit_native - warning_high_native if consensus_profit_native is not None and warning_high_native is not None else None
        implied_h2_high_native = consensus_profit_native - warning_low_native if consensus_profit_native is not None and warning_low_native is not None else None
        implied_h2_mid_native = consensus_profit_native - warning_mid_native if consensus_profit_native is not None and warning_mid_native is not None else None
        historical_h1 = historical[
            historical["company"].eq(company)
            & historical["period_end"].astype(str).eq("2025-06-30")
        ]
        historical_h1_profit = _num(historical_h1.iloc[0].get("attributable_net_income_usd_mn")) if not historical_h1.empty else None
        historical_fy_profit = _num(hist_row.get("attributable_net_income_usd_mn"))
        historical_h2_profit = historical_fy_profit - historical_h1_profit if historical_fy_profit is not None and historical_h1_profit is not None else None

        for scenario, assumptions in SCENARIOS.items():
            fuel_shock = assumptions["fuel_shock_pct"]
            fuel_row = fuel_company[
                fuel_company["scenario_fuel_price_change_pct"].eq(fuel_shock)
            ]
            fuel_item = fuel_row.iloc[0] if not fuel_row.empty else pd.Series(dtype=object)
            # The sensitivity table stores non-zero shocks only; base is explicitly zero.
            fuel_impact = 0.0 if fuel_shock == 0.0 else _num(fuel_item.get("pre_tax_profit_impact_usd_mn"))
            scenario_revenue = revenue * (1 + assumptions["revenue_delta_pct"] / 100) if revenue is not None else None
            scenario_margin = margin + assumptions["margin_delta_pp"] if margin is not None else None
            scenario_profit_before_fuel = (
                scenario_revenue * scenario_margin / 100
                if scenario_revenue is not None and scenario_margin is not None
                else None
            )
            scenario_profit_after_fuel = (
                scenario_profit_before_fuel + fuel_impact
                if scenario_profit_before_fuel is not None and fuel_impact is not None
                else None
            )
            base_rows.append(
                {
                    "dataset_id": "airline_pre_h1_scenario_bridge",
                    "pair_id": "601021.SH__603885.SH",
                    "company": company,
                    "ticker": str(exp_row.get("market_ticker", hist_row.get("ticker", ""))),
                    "scenario": scenario,
                    "as_of_date": as_of,
                    "actual_fy2025_revenue_usd_mn": _num(hist_row.get("revenue_usd_mn")),
                    "actual_fy2025_profit_usd_mn": _num(hist_row.get("attributable_net_income_usd_mn")),
                    "actual_fy2025_margin_pct": _num(hist_row.get("net_margin_pct")),
                    "consensus_fy2026_revenue_usd_mn": revenue,
                    "consensus_fy2026_revenue_low_usd_mn": _num(exp_row.get("fy2026_revenue_low_usd_mn")),
                    "consensus_fy2026_revenue_high_usd_mn": _num(exp_row.get("fy2026_revenue_high_usd_mn")),
                    "consensus_fy2026_revenue_analyst_count": _num(exp_row.get("fy2026_revenue_analyst_count")),
                    "consensus_fy2026_profit_usd_mn": profit,
                    "consensus_fy2026_profit_low_usd_mn": _num(exp_row.get("fy2026_net_profit_low_usd_mn")),
                    "consensus_fy2026_profit_high_usd_mn": _num(exp_row.get("fy2026_net_profit_high_usd_mn")),
                    "consensus_implied_margin_pct": margin,
                    "revenue_consensus_freshness": str(exp_row.get("revenue_consensus_freshness_band", "pending")),
                    "profit_consensus_freshness": str(exp_row.get("profit_consensus_freshness_band", "pending")),
                    "profit_consensus_age_days": _num(exp_row.get("profit_consensus_age_days")),
                    "q2_ask_yoy_pct": _num(op_row.get("q2_ask_yoy_pct")),
                    "q2_rpk_yoy_pct": _num(op_row.get("q2_rpk_yoy_pct")),
                    "q2_rpk_minus_ask_gap_pp": _num(op_row.get("q2_rpk_minus_ask_gap_pp")),
                    "june_rpk_minus_ask_gap_pp": _num(op_row.get("june_rpk_minus_ask_gap_pp")),
                    "operating_snapshot_date": str(op_row.get("snapshot_date", "")),
                    "operating_data_status": "preliminary_monthly_release_pending_formal_1h2026",
                    "sector_snapshot_date": str(sector_row.get("snapshot_date", "")),
                    "sector_h1_ask_yoy_pct": _num(sector_row.get("h1_ask_yoy_pct")),
                    "sector_h1_rpk_yoy_pct": _num(sector_row.get("h1_rpk_yoy_pct")),
                    "sector_h1_rpk_minus_ask_gap_pp": _num(sector_row.get("h1_rpk_minus_ask_growth_gap_pp")),
                    "sector_jet_fuel_spot_usd_per_gallon": _num(sector_row.get("jet_fuel_spot_usd_per_gallon")),
                    "sector_h1_jet_fuel_avg_usd_per_gallon": _num(sector_row.get("h1_2026_jet_fuel_avg_usd_per_gallon")),
                    "sector_h1_jet_fuel_yoy_pct": _num(sector_row.get("h1_jet_fuel_avg_yoy_pct")),
                    "sector_energy_observation_date": str(sector_row.get("energy_observation_date", "")),
                    "fuel_cost_share_pct": _num(exp_row.get("latest_report_fuel_cost_share_pct")),
                    "fuel_shock_pct": fuel_shock,
                    "fuel_profit_impact_usd_mn": fuel_impact,
                    "scenario_revenue_delta_pct": assumptions["revenue_delta_pct"],
                    "scenario_margin_delta_pp": assumptions["margin_delta_pp"],
                    "scenario_revenue_usd_mn": scenario_revenue,
                    "scenario_margin_pct": scenario_margin,
                    "scenario_profit_before_fuel_usd_mn": scenario_profit_before_fuel,
                    "scenario_profit_after_fuel_usd_mn": scenario_profit_after_fuel,
                    "formal_report_scheduled_date": scheduled,
                    "latest_event_date": latest_event_date,
                    "latest_event_type": latest_event_type,
                    "warning_date": warning_date,
                    "warning_profit_low_native_mn": warning_low_native,
                    "warning_profit_high_native_mn": warning_high_native,
                    "warning_profit_mid_native_mn": warning_mid_native,
                    "warning_native_unit": str(exp_row.get("latest_event_native_unit", "")) if warning_date else "",
                    "warning_source_quality": str(exp_row.get("latest_event_source_quality", "")) if warning_date else "",
                    "warning_source_url": str(exp_row.get("latest_event_source_url", "")) if warning_date else "",
                    "warning_to_consensus_status": warning_to_consensus_status,
                    "implied_h2_profit_low_native_mn": implied_h2_low_native,
                    "implied_h2_profit_mid_native_mn": implied_h2_mid_native,
                    "implied_h2_profit_high_native_mn": implied_h2_high_native,
                    "implied_h2_profit_low_usd_mn": implied_h2_low_native * fx_native_to_usd if implied_h2_low_native is not None and fx_native_to_usd is not None else None,
                    "implied_h2_profit_mid_usd_mn": implied_h2_mid_native * fx_native_to_usd if implied_h2_mid_native is not None and fx_native_to_usd is not None else None,
                    "implied_h2_profit_high_usd_mn": implied_h2_high_native * fx_native_to_usd if implied_h2_high_native is not None and fx_native_to_usd is not None else None,
                    "historical_h2_2025_profit_usd_mn": historical_h2_profit,
                    "implied_h2_mid_minus_historical_h2_2025_usd_mn": (
                        implied_h2_mid_native * fx_native_to_usd - historical_h2_profit
                        if implied_h2_mid_native is not None and fx_native_to_usd is not None and historical_h2_profit is not None
                        else None
                    ),
                    "scenario_status": "mechanical_pre_h1_stress_test_not_forecast",
                    "source_quality": "derived_multi_source_stress_test",
                    "source_note": (
                        "FY2025 actuals and FY2026 consensus are joined from the historical and expectation bridges; "
                        "Q2/June operating fields are issuer-release diagnostics; fuel overlay is a separate mechanical "
                        "price shock. H1 2026 formal actuals are pending and no trade direction is implied."
                    ),
                    "actual_source_note": str(hist_row.get("source_note", "")),
                    "consensus_source_quality": str(exp_row.get("source_quality", "")),
                    "operating_source_quality": str(op_row.get("source_quality", "")),
                    "fuel_source_quality": str(fuel_item.get("source_quality", "")),
                    "fuel_observation_date": str(fuel_item.get("jet_fuel_observation_date", "")),
                    "sector_source_quality": str(sector_row.get("source_quality", "")),
                    "retrieved_at": retrieved,
                }
            )

    result = pd.DataFrame(base_rows)
    pair_gaps = result.pivot(index="scenario", columns="company", values="scenario_profit_after_fuel_usd_mn")
    result["pair_profit_gap_spring_minus_juneyao_usd_mn"] = result.apply(
        lambda row: (
            pair_gaps.loc[row["scenario"], "Spring Airlines"] - pair_gaps.loc[row["scenario"], "Juneyao Airlines"]
            if row["scenario"] in pair_gaps.index
            and pd.notna(pair_gaps.loc[row["scenario"], "Spring Airlines"])
            and pd.notna(pair_gaps.loc[row["scenario"], "Juneyao Airlines"])
            else None
        ),
        axis=1,
    )
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def fetch_airline_pre_h1_scenario_bridge() -> pd.DataFrame:
    return build_airline_pre_h1_scenario_bridge()
