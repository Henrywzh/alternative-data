from __future__ import annotations

import pandas as pd

from src.hk_real_estate.shkp_h1_backtest import (
    H1_REPORT_REGISTRY_DATA,
    build_shkp_h1_actual_vs_nowcast,
    build_shkp_h1_component_actual_vs_nowcast,
    build_shkp_h1_to_fy_bridge,
    h1_report_registry,
    parse_shkp_h1_report_text,
)


def _report(year: int) -> dict[str, object]:
    return {
        "report_id": f"test_{year}",
        "fiscal_label": f"FY{year - 1}/{str(year)[-2:]}",
        "fiscal_year_end": year,
        "period_start": f"{year - 1}-07-01",
        "period_end": f"{year - 1}-12-31",
        "release_date": f"{year}-02-25",
        "source_url": "https://www.shkp.com/test.pdf",
    }


def test_registry_covers_official_h1_reports_and_release_dates() -> None:
    registry = h1_report_registry()
    assert len(registry) == 10
    assert registry["period_type"].eq("interim").all()
    assert registry["pit_quality"].eq("strict_release_date_observed").all()
    assert registry["release_date"].min() == "2017-02-28"
    assert registry["release_date"].max() == "2026-02-26"
    assert registry["source_url"].nunique() == len(H1_REPORT_REGISTRY_DATA)


def test_parser_handles_legacy_footnotes_and_newer_highlights() -> None:
    text = """Financial Highlights and Corporate Information
FINANCIAL HIGHLIGHTS
For the six months ended 31 December 2016 2016 2015 Change (%)
Financial Highlights (HK$ million)
Revenue 46,343 34,902 32.8
Profit attributable to the Company's shareholders
  — Reported 20,659 14,724 40.3
  — Underlying1 14,608 9,298 57.1
Gross rental income2 10,803 10,351 4.4
Net rental income2 8,273 7,943 4.2
Financial Information per Share (HK$)
  — Reported 7.14 5.11 39.7
  — Underlying1 5.05 3.23 56.3
Interim dividends 1.10 1.05 4.8
CORPORATE INFORMATION
"""
    parsed = parse_shkp_h1_report_text(_report(2017), text)
    values = dict(zip(parsed["metric"], parsed["value"]))
    assert values["group_revenue"] == 46343
    assert values["underlying_profit_attributable"] == 14608
    assert values["gross_rental_income"] == 10803
    assert values["net_rental_income"] == 8273
    assert values["underlying_eps"] == 5.05
    assert values["interim_dividend"] == 1.10


def test_parser_keeps_missing_hk_split_missing() -> None:
    text = """FINANCIAL HIGHLIGHTS
For the six months ended 31 December 2018 2018 2017 Change (%)
Financial Highlights (HK$ million)
Revenue 37,112 55,166 -32.7
Profit attributable to the Company's shareholders — Reported 20,469 33,031 -38.0
 — Underlying (1) 13,733 19,973 -31.2
Gross rental income (3) 12,286 11,506 +6.8
Net rental income (3) 9,508 8,891 +6.9
CORPORATE INFORMATION
"""
    parsed = parse_shkp_h1_report_text(_report(2019), text)
    assert not parsed.loc[parsed["metric"].eq("hk_property_sales_revenue")].any(axis=None)


def test_parser_uses_segment_table_for_hk_components_and_hotel() -> None:
    text = """FINANCIAL HIGHLIGHTS
For the six months ended 31 December 2017 2017 2016 Change (%)
Financial Highlights (HK$ million)
Revenue 55,166 46,343 19.0
Financial Information per Share (HK$)
Interim dividends 1.10 1.05 4.8
Property sales Hong Kong 31,735 12,645 26 26 31,761 12,671 Mainland China 1,697 709 1,125 515 2,822 1,224
Property rental Hong Kong 7,527 5,733 1,484 1,240 9,011 6,973 Mainland China 1,889 1,505 251 146 2,140 1,651
Hotel operation 2,293 660 445 116 2,738 776 Telecommunications
CORPORATE INFORMATION
"""
    parsed = parse_shkp_h1_report_text(_report(2018), text)
    values = dict(zip(parsed["metric"], parsed["value"]))
    assert values["hk_property_sales_revenue"] == 31761
    assert values["hk_rental_revenue"] == 9011
    assert values["hotel_revenue"] == 2738


def _annual_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"period_end": "2021-06-30", "model_metric": "group_revenue", "value": 100.0, "unit": "HKD_m", "currency": "HKD", "annual_source": "official_financial_summary_curated", "source_url": "official"},
            {"period_end": "2022-06-30", "model_metric": "group_revenue", "value": 120.0, "unit": "HKD_m", "currency": "HKD", "annual_source": "official_financial_summary_curated", "source_url": "official"},
            {"period_end": "2023-06-30", "model_metric": "group_revenue", "value": 150.0, "unit": "HKD_m", "currency": "HKD", "annual_source": "official_financial_summary_curated", "source_url": "official"},
        ]
    )


def _panel() -> pd.DataFrame:
    rows = []
    for year, h1 in ((2021, 50.0), (2022, 60.0), (2023, 75.0)):
        r = _report(year)
        rows.append(
            {
                "fact_id": f"fact_{year}", "ticker": "0016.HK", "report_id": r["report_id"],
                "fiscal_label": r["fiscal_label"], "fiscal_year_end": year,
                "period_start": r["period_start"], "period_end": r["period_end"],
                "period_type": "interim", "scope": "group", "segment": "consolidated",
                "metric": "group_revenue", "value": h1, "unit": "HKD_m", "currency": "HKD",
                "value_operator": "=", "source_page": 4, "source_url": "official",
                "release_date": r["release_date"], "availability_date": r["release_date"],
                "pit_quality": "strict_release_date_observed", "source_method": "test",
                "evidence_excerpt": "test", "caveat": "test",
            }
        )
    return pd.DataFrame(rows)


def test_bridge_uses_hkd_m_units_and_calculates_h2_arithmetically() -> None:
    bridge = build_shkp_h1_to_fy_bridge(_panel(), _annual_frame())
    assert list(bridge["full_year_actual"]) == [100.0, 120.0, 150.0]
    assert list(bridge["h2_actual"]) == [50.0, 60.0, 75.0]
    assert list(bridge["h1_share_pct"]) == [50.0, 50.0, 50.0]
    assert bridge["pit_quality"].str.contains("annual_source").all()


def test_backtest_training_years_are_strictly_prior_to_target() -> None:
    backtest = build_shkp_h1_actual_vs_nowcast(_panel(), _annual_frame(), lookback=2)
    assert backtest["target_fiscal_year"].tolist() == [2021, 2022, 2023]
    row = backtest.loc[backtest["target_fiscal_year"].eq(2023)].iloc[0]
    assert row["training_years"] == "2021,2022"
    assert row["prior_share_forecast"] == 150.0
    assert row["prior_share_ape_pct"] == 0.0


def _component_panel() -> pd.DataFrame:
    rows = []
    values = {
        2019: (100.0, 20.0, 30.0, 10.0),
        2020: (110.0, 25.0, 30.0, 10.0),
        2021: (120.0, 30.0, 31.0, 11.0),
    }
    for year, (group, development, rental, hotel) in values.items():
        report = _report(year)
        for metric, value, scope, segment in (
            ("group_revenue", group, "group", "consolidated"),
            ("hk_property_sales_revenue", development, "hong_kong", "property_sales"),
            ("hk_rental_revenue", rental, "hong_kong", "property_rental"),
            ("hotel_revenue", hotel, "group", "hotel_operations"),
        ):
            rows.append(
                {
                    "fact_id": f"{metric}_{year}", "ticker": "0016.HK", "report_id": report["report_id"],
                    "fiscal_label": report["fiscal_label"], "fiscal_year_end": year,
                    "period_start": report["period_start"], "period_end": report["period_end"],
                    "period_type": "interim", "scope": scope, "segment": segment,
                    "metric": metric, "value": value, "unit": "HKD_m", "currency": "HKD",
                    "value_operator": "=", "source_page": 4, "source_url": "official",
                    "release_date": report["release_date"], "availability_date": report["release_date"],
                    "pit_quality": "strict_release_date_observed", "source_method": "test",
                    "evidence_excerpt": "test", "caveat": "test",
                }
            )
    return pd.DataFrame(rows)


def test_component_backtest_is_additive_and_uses_prior_years_only() -> None:
    panel = _component_panel()
    annual = _annual_frame().rename(columns={"value": "value"})
    # Replace the simple annual group values with a component history whose
    # residual is explicitly group minus the three named components.
    component_annual = pd.DataFrame(
        [
            {"fiscal_year_end": 2019, "fiscal_label": "FY2018/19", "group_revenue_hkd_m": 180.0, "hk_development_revenue_hkd_m": 35.0, "hk_rental_revenue_hkd_m": 60.0, "hotel_revenue_hkd_m": 20.0, "residual_revenue_hkd_m": 65.0, "source_status": "complete", "caveat": "test"},
            {"fiscal_year_end": 2020, "fiscal_label": "FY2019/20", "group_revenue_hkd_m": 190.0, "hk_development_revenue_hkd_m": 40.0, "hk_rental_revenue_hkd_m": 62.0, "hotel_revenue_hkd_m": 22.0, "residual_revenue_hkd_m": 66.0, "source_status": "complete", "caveat": "test"},
            {"fiscal_year_end": 2021, "fiscal_label": "FY2020/21", "group_revenue_hkd_m": 200.0, "hk_development_revenue_hkd_m": 45.0, "hk_rental_revenue_hkd_m": 64.0, "hotel_revenue_hkd_m": 24.0, "residual_revenue_hkd_m": 67.0, "source_status": "complete", "caveat": "test"},
        ]
    )
    backtest, _ = build_shkp_h1_component_actual_vs_nowcast(panel, annual, component_annual=component_annual, lookback=2)
    row = backtest.loc[backtest["target_fiscal_year"].eq(2021)].iloc[0]
    assert row["model_status"] == "valid_holdout"
    assert row["training_years"] == "2019,2020"
    assert row["fy_component_forecast_hkd_m"] == row["h1_group_revenue_hkd_m"] + row["h2_component_forecast_hkd_m"]
    assert row["component_coverage_status"] == "all_components_observed"


def test_component_backtest_does_not_score_missing_named_component() -> None:
    panel = _component_panel().loc[lambda d: d["metric"].ne("hotel_revenue")]
    annual = _annual_frame()
    component_annual = pd.DataFrame(
        [{"fiscal_year_end": 2021, "fiscal_label": "FY2020/21", "group_revenue_hkd_m": 200.0, "hk_development_revenue_hkd_m": 45.0, "hk_rental_revenue_hkd_m": 64.0, "hotel_revenue_hkd_m": 24.0, "residual_revenue_hkd_m": 67.0, "source_status": "complete", "caveat": "test"}]
    )
    backtest, _ = build_shkp_h1_component_actual_vs_nowcast(panel, annual, component_annual=component_annual)
    assert backtest["model_status"].eq("insufficient_component_coverage").all()
