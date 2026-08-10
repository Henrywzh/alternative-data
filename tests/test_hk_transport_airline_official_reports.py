from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.hk_transport.sources.airline_official_reports import (
    _segment_closing_rows,
    _statement_value_from_line,
)


ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = ROOT / "data" / "normalized" / "hk_transport"


def test_waterfall_statement_parser_skips_note_numbers_and_preserves_negative_cells() -> None:
    assert _statement_value_from_line(
        "财务费用 七（67） 158,967,460 108,403,569",
        ("财务费用",),
    ) == pytest.approx(158_967_460.0)
    assert _statement_value_from_line(
        "财务费用 42 4,853,956 6,766,999",
        ("财务费用",),
    ) == pytest.approx(4_853_956.0)
    assert _statement_value_from_line(
        "投资收益（损失以“－”号填列） 注释 68 3,744,822.54 -181,651.96",
        ("投资收益",),
    ) == pytest.approx(3_744_822.54)
    assert _statement_value_from_line(
        "信用减值损失 四 (51) - (21)",
        ("信用减值损失",),
    ) is None
    assert _statement_value_from_line(
        "二、营业亏损  (2,047,902)  (3,431,959)",
        ("营业亏损",),
    ) == pytest.approx(-2_047_902.0)
    assert _statement_value_from_line(
        "投资收益/(损失) 四 (49) 79 (599)",
        ("投资收益",),
    ) == pytest.approx(79.0)
    assert _statement_value_from_line(
        "公允价值变动收益 四 (50) 32 195",
        ("公允价值变动收益",),
    ) == pytest.approx(32.0)


def test_statement_parser_keeps_variance_table_current_period() -> None:
    # A three-column variance table (current / prior / change) must return the
    # current-period value, not the prior period.  The bare-note-number rule
    # previously misread the current-period figure as a note number.
    assert _statement_value_from_line(
        "投资收益 162 130 24.62",
        ("投资收益",),
    ) == pytest.approx(162.0)
    assert _statement_value_from_line(
        "财务费用 2,213 3,027 -26.89",
        ("财务费用",),
    ) == pytest.approx(2_213.0)


def test_segment_closing_rows_recovers_tax_and_net_from_segment_note() -> None:
    pages = [
        "六、 分部信息\n"
        "航空分部 其他业务分部 未分配的金额 分部间抵销 合计\n"
        "(亏损)/利润总额 (1,767) 39 197 - (1,531)\n"
        "所得税费用 (40) (21) - - (61)\n"
        "净(亏损)/利润 (1,807) 18 197 - (1,592)\n",
        "七、 关联方\nrelated-party note",
    ]
    wanted = {
        "income_tax_expense": ("所得税费用",),
        "net_income_total": ("净(亏损)/利润", "净利润"),
    }
    result = _segment_closing_rows(pages, wanted)
    by_metric = {metric: value for metric, value, _ in result}
    assert by_metric == {
        "income_tax_expense": -61.0,
        "net_income_total": -1592.0,
    }


def test_segment_closing_rows_ignores_management_discussion_table() -> None:
    pages = [
        "报告期净利润（百万） -252 2 -192 103 -28 -72\n"
        "上一报告期净利润（百万） -542 -26 -336 -163 94 18",
        "六、 分部信息\n"
        "(亏损)/利润总额 (1,767) 39 197 - (1,531)\n"
        "所得税费用 (40) (21) - - (61)\n"
        "净(亏损)/利润 (1,807) 18 197 - (1,592)\n",
    ]
    wanted = {
        "income_tax_expense": ("所得税费用",),
        "net_income_total": ("净(亏损)/利润", "净利润"),
    }
    result = _segment_closing_rows(pages, wanted)
    by_metric = {metric: value for metric, value, _ in result}
    assert by_metric["net_income_total"] == -1592.0
    assert by_metric["income_tax_expense"] == -61.0


def test_segment_closing_rows_excludes_two_period_tables() -> None:
    # China Southern's segment note repeats the columns for the prior year
    # (10 numeric cells), so the last number is the PRIOR-year total.  The
    # column-count guard must reject such rows instead of returning a
    # wrong-period value.
    pages = [
        "六、 分部信息\n"
        "航空营运业务分部 其他业务分部 分部间抵销 未分配项目 合计\n"
        "所得税费用 1,160 569 172 71 2 2 94 42 1,428 684\n"
        "净利润 / (亏损) (1,115) 53 292 305 28 16 (37) (899) (832) (525)\n",
    ]
    wanted = {
        "income_tax_expense": ("所得税费用",),
        "net_income_total": ("净(亏损)/利润", "净(损失)/利润", "净利润"),
    }
    result = _segment_closing_rows(pages, wanted)
    assert result == []


def test_segment_closing_rows_excludes_table_header_fragment() -> None:
    # A header fragment carries the label in the middle of the line and
    # date-like numbers; the label-position guard must reject it.
    pages = [
        "六、 分部信息\n"
        "12月31日 于母公司 6月30日 发生额 减：所得税费用 税后归属于母公司 税后归属于少数股东\n"
        "所得税费用 (40) (21) - - (61)\n"
        "净(亏损)/利润 (1,807) 18 197 - (1,592)\n",
    ]
    wanted = {
        "income_tax_expense": ("所得税费用",),
        "net_income_total": ("净(亏损)/利润", "净(损失)/利润"),
    }
    result = _segment_closing_rows(pages, wanted)
    by_metric = {metric: value for metric, value, _ in result}
    assert by_metric == {
        "income_tax_expense": -61.0,
        "net_income_total": -1592.0,
    }


def test_segment_closing_rows_rejects_eps_table_net_profit_label() -> None:
    # EPS-per-share tables contain "净利润/(亏损)" with small per-share
    # values; the generic "净利润" label was removed from the wanted set so
    # these must not be returned.
    pages = [
        "六、 分部信息\n"
        "归属于母公司股东的净利润/(亏损) 2.44 (4.72) 0.05 (0.09)\n"
        "净(亏损)/利润 (1,807) 18 197 - (1,592)\n",
    ]
    wanted = {
        "net_income_total": ("净(亏损)/利润", "净(损失)/利润"),
    }
    result = _segment_closing_rows(pages, wanted)
    assert result == [("net_income_total", -1592.0, 1)]


def test_curated_official_report_registry_is_primary_and_fully_parsed() -> None:
    registry = pd.read_csv(TRANSPORT / "airline_official_report_registry.csv")

    assert len(registry) == 12
    assert registry["parse_status"].eq("parsed").all()
    assert registry["announcement_date"].notna().all()
    assert registry["source_quality"].eq("primary_issuer").all()
    assert registry["source_url"].str.contains("static.cninfo.com.cn").all()


def test_official_driver_snapshot_has_sane_group_level_units() -> None:
    drivers = pd.read_csv(TRANSPORT / "airline_official_report_drivers.csv")
    annual = drivers[drivers["report_type"].eq("annual")]

    assert len(annual["report_id"].unique()) == 6
    assert annual["announced_at"].notna().all()
    assert annual["source_page"].notna().all()
    assert annual["source_quality"].eq("primary_issuer").all()

    for metric, low, high in (
        ("total_revenue", 10_000, 250_000),
        ("operating_cost", 10_000, 250_000),
        ("fuel_cost", 500, 60_000),
        ("ask", 10_000, 500_000),
        ("passengers", 5, 250),
        ("passenger_load_factor_pct", 50, 100),
        ("fuel_cost_share_pct_derived", 10, 45),
    ):
        values = annual.loc[annual["metric"].eq(metric), "value_native"]
        assert len(values) == 6, metric
        assert values.between(low, high).all(), metric

    # China Southern's FY2025 report provides flight hours and fleet data but
    # no issuer-reported group daily-utilization row in the extracted
    # operating-information tables.  Keep that disclosure gap explicit rather
    # than filling it with a derived estimate under the reported KPI name.
    daily = annual.loc[annual["metric"].eq("daily_utilization"), "value_native"]
    assert len(daily) == 5
    assert daily.between(1, 20).all()

    fleet = annual.loc[annual["metric"].eq("fleet_total"), "value_native"]
    assert fleet.between(30, 1_200).all()

    cash = annual.loc[annual["metric"].eq("cash_and_cash_equivalents"), "value_native"]
    assert len(cash) == 5
    assert cash.gt(0).all()
    liabilities = annual.loc[annual["metric"].eq("total_liabilities"), "value_native"]
    leverage = annual.loc[annual["metric"].eq("liabilities_to_assets_pct_derived"), "value_native"]
    assert len(liabilities) == 5
    assert len(leverage) == 5
    assert leverage.between(0, 100).all()
    debt = annual.loc[annual["metric"].eq("interest_bearing_debt"), "value_native"]
    capex = annual.loc[annual["metric"].eq("capex_cash_paid"), "value_native"]
    assert len(debt) == 3
    assert len(capex) == 3
    assert debt.gt(0).all()
    assert capex.gt(0).all()


def test_official_interim_driver_snapshot_has_sane_values_and_verified_anchors() -> None:
    drivers = pd.read_csv(TRANSPORT / "airline_official_report_drivers.csv")
    interim = drivers[drivers["report_type"].eq("interim")]

    for metric, low, high in (
        ("ask", 10_000, 500_000),
        ("passengers", 1, 250),
        ("passenger_load_factor_pct", 0, 100),
        ("cargo_load_factor_pct", 0, 100),
        ("passenger_yield", 0.01, 5),
        ("cargo_yield", 0.01, 10),
        ("cask", 0.05, 2),
        ("cask_derived", 0.05, 2),
        ("fuel_cost_share_pct_derived", 0, 100),
        ("fuel_cost_share_pct_reported", 0, 100),
        ("daily_utilization", 0, 24),
    ):
        values = pd.to_numeric(interim.loc[interim["metric"].eq(metric), "value_native"], errors="coerce")
        assert values.notna().all(), metric
        assert values.between(low, high).all(), metric

    def value(ticker: str, metric: str) -> float:
        rows = interim.loc[interim["ticker"].eq(ticker) & interim["metric"].eq(metric), "value_native"]
        assert len(rows) == 1, (ticker, metric)
        return float(rows.iloc[0])

    # These values are anchored to the formal operating tables, not nearby
    # narrative numbers in the same PDF.
    assert value("0753.HK / 601111.SH", "passenger_load_factor_pct") == 80.72
    assert value("01055.HK / 600029.SH", "passenger_load_factor_pct") == 85.47
    assert value("0670.HK / 600115.SH", "passenger_load_factor_pct") == 84.81
    assert value("601021.SH", "ask") == 29_307.9501
    assert value("601021.SH", "passenger_load_factor_pct") == 90.52
    assert value("600221.SH", "ask") == 77_921.27

    cash = interim.loc[interim["metric"].eq("cash_and_cash_equivalents"), "value_native"]
    assert len(cash) == 6
    assert cash.gt(0).all()
    liabilities = interim.loc[interim["metric"].eq("total_liabilities"), "value_native"]
    leverage = interim.loc[interim["metric"].eq("liabilities_to_assets_pct_derived"), "value_native"]
    assert len(liabilities) == 6
    assert len(leverage) == 6
    assert leverage.between(0, 100).all()
    debt = interim.loc[interim["metric"].eq("interest_bearing_debt"), "value_native"]
    capex = interim.loc[interim["metric"].eq("capex_cash_paid"), "value_native"]
    assert len(debt) == 3
    assert len(capex) == 4
    assert debt.gt(0).all()
    assert capex.gt(0).all()

    # Hainan reports passenger-and-other revenue rather than a pure passenger
    # ticket line. Keep the scope explicit while allowing a labelled yield/RASK
    # proxy to be built from the same issuer report.
    assert value("600221.SH", "passenger_revenue") == 28_953.261
    hainan_yield = interim.loc[
        interim["ticker"].eq("600221.SH") & interim["metric"].eq("passenger_yield_derived"),
        "value_native",
    ]
    assert len(hainan_yield) == 1
    assert hainan_yield.item() == pytest.approx(28_953.261 / 64_480.17)

    # When passenger revenue is not separately disclosed, a labelled RASK
    # proxy can still be constructed from the issuer's yield and RPK/ASK.
    for report_id in ("600115_2025_fy", "601021_2025_h1", "603885_2025_h1"):
        report = drivers.loc[drivers["report_id"].eq(report_id)].set_index("metric")["value_native"]
        assert "rask_from_reported_yield_derived" in report.index
        assert report["rask_from_reported_yield_derived"] == pytest.approx(
            report["passenger_yield"] * report["rpk"] / report["ask"]
        )

    # Eastern's consolidated 1H2025 note separately discloses passenger and
    # cargo service revenue; use that primary anchor instead of the yield-only
    # fallback for this report.
    eastern_h1 = drivers.loc[drivers["report_id"].eq("600115_2025_h1")].set_index("metric")
    assert eastern_h1.loc["passenger_revenue", "value_native"] == 61_813.0
    assert eastern_h1.loc["cargo_revenue", "value_native"] == 2_577.0
    assert eastern_h1.loc["rask_derived", "value_native"] == pytest.approx(61_813.0 / 155_022.29)
    assert "rask_from_reported_yield_derived" not in eastern_h1.index

    hainan_implied = interim.loc[
        interim["ticker"].eq("600221.SH")
        & interim["metric"].eq("fuel_cost_implied_from_reported_share"),
        "value_native",
    ]
    assert len(hainan_implied) == 1
    assert hainan_implied.item() == pytest.approx(9_766.4142585)
    hainan_note = interim.loc[
        interim["ticker"].eq("600221.SH")
        & interim["metric"].eq("fuel_cost_implied_from_reported_share"),
        "source_note",
    ].item()
    assert "no direct RMB fuel-cost line" in hainan_note


def test_juneyao_fy2025_attributable_profit_uses_primary_issuer_table() -> None:
    drivers = pd.read_csv(TRANSPORT / "airline_official_report_drivers.csv")
    rows = drivers.loc[
        drivers["ticker"].eq("603885.SH")
        & drivers["statement_period"].eq("FY2025")
        & drivers["metric"].eq("attributable_net_income")
    ]
    assert len(rows) == 1
    assert rows["value_native"].item() == 1_039.63838235
    assert rows["source_page"].item() == 7


def test_official_money_rows_have_usd_translation_and_operating_rows_do_not() -> None:
    drivers = pd.read_csv(TRANSPORT / "airline_official_report_drivers.csv")
    money = drivers[drivers["native_unit"].eq("RMB million")]
    operating = drivers[~drivers["native_unit"].eq("RMB million")]

    assert money["value_usd"].notna().all()
    assert money["fx_pair"].eq("USD_CNY").all()
    assert operating["value_usd"].isna().all()
