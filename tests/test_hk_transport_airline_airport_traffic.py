from __future__ import annotations

import pytest

from src.hk_transport.sources.airline_airport_traffic import (
    SOURCE_SPECS,
    parse_shanghai_dual_airport,
    parse_szx_can_layout,
)


def _spec(event_id: str) -> dict[str, object]:
    return next(spec for spec in SOURCE_SPECS if spec["event_id"] == event_id)


def test_shanghai_dual_airport_parser_captures_both_hubs_and_scope_rows() -> None:
    spec = dict(_spec("sha_2026_06"))
    text = (
        "飞机起降量（架次） 旅客吞吐量（万人次） 货邮吞吐量（万吨）\n"
        "浦东国际机场\n"
        "本月 同比±% 本月 同比±% 本月 同比±%\n"
        "总计 44,342 -1.19 686.35 -0.55 40.05 17.88\n"
        "境内航线 25,349 0.61 371.02 -2.29 3.03 0.10\n"
        "飞机起降量（架次） 旅客吞吐量（万人次） 货邮吞吐量（万吨）\n"
        "虹桥国际机场\n"
        "本月 同比±% 本月 同比±% 本月 同比±%\n"
        "总计 22,715 -0.40 404.16 -0.80 3.75 3.68\n"
    )
    result = parse_shanghai_dual_airport(
        b"",
        spec=spec,
        text=text,
        retrieved_at="2026-08-09T00:00:00+00:00",
    )

    assert len(result) == 9
    assert result["airport"].unique().tolist() == ["SHA-PVG", "SHA-SHA"]
    pvg = result[result["airport"].eq("SHA-PVG")]
    pvg_total = pvg[pvg["scope"].eq("total")].set_index("metric")
    assert pvg_total.loc["aircraft_movements", "value"] == pytest.approx(44_342.0)
    assert pvg_total.loc["passenger_throughput", "value"] == pytest.approx(686.35)
    assert pvg_total.loc["cargo_throughput", "value"] == pytest.approx(40.05)
    assert result["yoy_pct"].isna().sum() == 0
    assert result["source_release_date"].eq("2026-07-15").all()


def test_szx_can_layout_parses_month_and_cumulative_columns() -> None:
    text = (
        "项目 本月实际 同比增长 本年累计 同比增长\n"
        "旅客吞吐量（万人次） 542.25 -2.10% 2,840.90 3.64%\n"
        "其中：国内航线 491.30 -2.06% 2,572.78 3.53%\n"
        "地区航线 4.43 4.74% 22.50 15.82%\n"
        "国际航线 46.53 -3.10% 245.63 3.82%\n"
        "货邮吞吐量（万吨） 17.34 2.78% 81.09 1.95%\n"
        "其中：国内航线 8.60 3.63% 39.26 2.89%\n"
        "地区航线 0.57 -4.71% 2.74 0.75%\n"
        "国际航线 8.16 2.46% 39.09 1.11%\n"
        "航班起降架次（架次） 36,582 -1.86% 187,595 1.43%\n"
        "其中：国内航线 31,511 -1.71% 162,024 1.80%\n"
        "地区航线 350 1.45% 1,697 5.08%\n"
        "国际航线 4,721 -3.06% 23,874 -1.20%\n"
    )
    result = parse_szx_can_layout(
        b"",
        spec=dict(_spec("szx_2026_05")),
        text=text,
        retrieved_at="2026-08-09T00:00:00+00:00",
    )

    assert len(result) == 12
    totals = result[result["scope"].eq("total")].set_index("metric")
    assert totals.loc["passenger_throughput", "value"] == pytest.approx(542.25)
    assert totals.loc["passenger_throughput", "ytd_value"] == pytest.approx(2_840.9)
    assert totals.loc["aircraft_movements", "value"] == pytest.approx(36_582.0)
    domestic = result[result["scope"].eq("domestic")].set_index("metric")
    assert domestic.loc["passenger_throughput", "value"] == pytest.approx(491.30)


def test_can_wide_layout_scales_passenger_and_cargo_units() -> None:
    text = (
        "起降架次（架次） 旅客吞吐量（人次） 货邮吞吐量（吨）\n"
        "项目\n"
        "本月数 同比增长 本月数 同比增长 本月数 同比增长\n"
        "总计 45,529.00 -0.12% 6,998,421.00 1.96% 203,378.39 -1.45%\n"
        "其中：国内航线 34,752.00 -2.95% 5,367,571.00 -2.17% 62,659.70 -13.06%\n"
        "地区航线 440.00 23.60% 79,843.00 43.19% 6,909.18 27.55%\n"
        "国际航线 10,337.00 9.75% 1,551,007.00 17.38% 133,809.51 3.83%\n"
    )
    result = parse_szx_can_layout(
        b"",
        spec=dict(_spec("can_2026_05")),
        text=text,
        retrieved_at="2026-08-09T00:00:00+00:00",
    )

    assert len(result) == 12
    totals = result[result["scope"].eq("total")].set_index("metric")
    assert totals.loc["aircraft_movements", "value"] == pytest.approx(45_529.0)
    assert totals.loc["passenger_throughput", "value"] == pytest.approx(699.8421)
    assert totals.loc["passenger_throughput", "unit"] == "10k persons"
    assert totals.loc["cargo_throughput", "value"] == pytest.approx(20.3378)
    assert totals.loc["cargo_throughput", "unit"] == "10k tonnes"


def test_can_numbered_prefix_layout_normalizes_person_and_tonne_units() -> None:
    text = (
        "月度 累计\n"
        "项目\n"
        "本月数 同比增长 累计数 同比增长\n"
        "一、起降架次（架次） 49,519.00 3.58% 49,519.00 3.58%\n"
        "其中：国内航线 37,795.00 0.70% 37,795.00 0.70%\n"
        "地区航线 448.00 15.76% 448.00 15.76%\n"
        "国际航线 11,276.00 14.05% 11,276.00 14.05%\n"
        "二、旅客吞吐量（人次） 7,493,811.00 4.95% 7,493,811.00 4.95%\n"
        "其中：国内航线 5,751,996.00 1.12% 5,751,996.00 1.12%\n"
        "地区航线 66,573.00 24.73% 66,573.00 24.73%\n"
        "国际航线 1,675,242.00 19.74% 1,675,242.00 19.74%\n"
        "三、货邮吞吐量（吨） 205,258.81 4.90% 205,258.81 4.90%\n"
        "其中：国内航线 66,090.07 -8.07% 66,090.07 -8.07%\n"
        "地区航线 6,316.62 -2.03% 6,316.62 -2.03%\n"
        "国际航线 132,852.12 13.23% 132,852.12 13.23%\n"
    )
    result = parse_szx_can_layout(
        b"",
        spec=dict(_spec("can_2026_01")),
        text=text,
        retrieved_at="2026-08-09T00:00:00+00:00",
    )

    assert len(result) == 12
    totals = result[result["scope"].eq("total")].set_index("metric")
    assert totals.loc["aircraft_movements", "value"] == pytest.approx(49_519.0)
    assert totals.loc["passenger_throughput", "value"] == pytest.approx(749.3811)
    assert totals.loc["passenger_throughput", "unit"] == "10k persons"
    assert totals.loc["passenger_throughput", "ytd_value"] == pytest.approx(749.3811)
    assert totals.loc["cargo_throughput", "value"] == pytest.approx(20.5259)
    assert totals.loc["cargo_throughput", "unit"] == "10k tonnes"
    regional = result[result["scope"].eq("regional")].set_index("metric")
    assert regional.loc["aircraft_movements", "value"] == pytest.approx(448.0)
