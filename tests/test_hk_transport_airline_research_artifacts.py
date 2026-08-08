from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = ROOT / "data" / "normalized" / "hk_transport"


def test_airline_event_timeline_has_point_in_time_lineage_and_usd_ranges() -> None:
    frame = pd.read_csv(TRANSPORT / "airline_event_timeline.csv")

    assert len(frame) == 20
    assert set(frame["ticker"]) == {
        "0293.HK",
        "0753.HK",
        "0670.HK",
        "01055.HK",
        "601021.SH",
        "600221.SH",
        "603885.SH",
        "SECTOR_BIG3",
    }
    required = ["event_date", "period_end", "source_url", "source_quality", "retrieved_at"]
    assert frame[required].notna().all().all()
    assert frame.loc[frame["event_type"].eq("earnings_warning"), "value_usd_min"].notna().all()
    assert frame.loc[frame["event_type"].eq("earnings_warning"), "fx_pair"].eq("USD_CNY").all()
    assert frame.loc[frame["metric"].eq("one_off_air_china_dilution_gain"), "source_quality"].item() == "primary_issuer"
    assert frame.loc[frame["event_type"].eq("financial_results"), "source_quality"].eq("primary_issuer").all()
    guidance = frame.loc[frame["metric"].eq("group_passenger_capacity_growth_target")].iloc[0]
    assert guidance["value_min"] == 10.0
    assert guidance["source_quality"] == "primary_issuer"
    spring_guidance = frame.loc[frame["metric"].eq("planned_fleet_additions")].iloc[0]
    assert spring_guidance["value_min"] == 12.0
    assert spring_guidance["source_quality"] == "primary_issuer"
    hainan_guidance = frame.loc[frame["metric"].eq("fleet_net_growth_target")].iloc[0]
    assert hainan_guidance["value_min"] == 3.0
    assert hainan_guidance["value_max"] == 5.0
    assert hainan_guidance["source_quality"] == "primary_issuer"
    assert frame.loc[frame["ticker"].eq("SECTOR_BIG3"), "source_quality"].eq("secondary_reuters").all()
    warnings = frame.loc[frame["event_type"].eq("earnings_warning")]
    assert warnings["source_quality"].eq("primary_issuer").all()
    assert warnings["source_url"].str.contains("static.cninfo.com.cn|global.ceair.com", regex=True).all()


def test_cathay_driver_snapshot_keeps_operating_units_separate_from_money() -> None:
    frame = pd.read_csv(TRANSPORT / "airline_financial_driver_snapshot.csv")

    assert len(frame) == 76
    assert set(frame["ticker"]) == {"0293.HK", "01055.HK"}
    money = frame[frame["native_currency"].notna()]
    non_money = frame[frame["native_currency"].isna()]
    assert money["value_usd"].notna().all()
    money_needing_fx = money[money["native_currency"].ne("USD")]
    assert money_needing_fx["fx_pair"].notna().all()
    assert non_money["value_usd"].isna().all()
    assert {"passenger_yield", "fuel_cost", "fuel_hedging_loss_gain", "cost_per_atk_ex_fuel"}.issubset(
        set(frame["metric"])
    )
    assert frame.loc[frame["ticker"].eq("01055.HK"), "source_quality"].eq("issuer_report_mirror").all()


def test_cathay_fy2025_annual_driver_snapshot_is_primary_and_page_anchored() -> None:
    frame = pd.read_csv(TRANSPORT / "airline_cathay_annual_driver_snapshot.csv")

    assert len(frame) == 31
    assert frame["statement_period"].eq("FY2025").all()
    assert frame["period_end"].eq("2025-12-31").all()
    assert frame["source_quality"].eq("primary_issuer").all()
    assert frame["source_page"].notna().all()
    assert frame.loc[frame["metric"].eq("total_revenue"), "value_native"].item() == 116766.0
    assert frame.loc[frame["metric"].eq("fuel_cost"), "value_native"].item() == 31344.0
    assert frame.loc[frame["metric"].eq("ask"), "value_native"].item() == 140681.0


def test_consensus_snapshot_is_explicitly_static_and_covers_four_hk_names() -> None:
    frame = pd.read_csv(TRANSPORT / "airline_consensus_snapshot.csv")

    assert len(frame) == 12
    assert set(frame["fiscal_year"]) == {2026, 2027, 2028}
    assert set(frame["ticker"]) == {"0293.HK", "0753.HK", "0670.HK", "01055.HK"}
    assert frame["revenue_consensus_available"].eq(False).all()
    assert frame["revisions_history_available"].eq(False).all()
    assert frame["source_quality"].eq("discovery_snapshot").all()
    assert frame["source_url"].str.contains("etnet.com.hk").all()


def test_sell_side_revision_proxy_has_dated_non_duplicate_observations() -> None:
    frame = pd.read_csv(TRANSPORT / "airline_sell_side_forecast_revisions.csv")

    assert len(frame) > 100
    assert frame[["ticker", "institution", "fiscal_year", "report_date", "eps_native"]].notna().all().all()
    assert frame.duplicated(["ticker", "institution", "fiscal_year", "report_date"]).sum() == 0
    assert frame["source_quality"].eq("akshare_discovery").all()
    assert frame["prior_report_date"].notna().any()


def test_sell_side_revenue_layer_has_pdf_lineage_and_revisions() -> None:
    forecasts = pd.read_csv(TRANSPORT / "airline_sell_side_revenue_forecasts.csv")
    revisions = pd.read_csv(TRANSPORT / "airline_sell_side_revenue_revisions.csv")

    assert len(forecasts) == 95
    assert len(revisions) == 95
    assert forecasts["source_quality"].eq("sell_side_pdf_extracted").all()
    assert forecasts[["report_date", "source_page", "report_url"]].notna().all().all()
    assert revisions["prior_report_date"].notna().any()
    assert revisions["revenue_change_native_mn"].notna().any()
