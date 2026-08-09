import pandas as pd
import pytest

from src.hk_transport.sources.airline_caac_sector_monthly import (
    OUTPUT_COLUMNS,
    parse_caac_sector_kpi_tables,
    parse_caac_sector_kpi_text,
)


SAMPLE_TEXT = """
中国民航2026年6月份主要生产指标统计
统计指标 计算单位 本月实际完成数 比上年同月增长% 当年累计实际完成数 比上年同期增长%
一、运输完成情况
运输总周转量 亿吨公里 133.4 0.2 833.7 6.4
国内航线 亿吨公里 78.5 -5.1 502.7 1.9
其中：港澳台航线 亿吨公里 1.3 -1.6 7.7 8.6
国际航线 亿吨公里 54.9 9.0 331.0 14.1
货邮运输量 万吨 88.8 0.4 507.3 6.0
二、航班效率
飞机日利用率 小时/日 8.2 -0.6 8.9 -0.1
正班客座率 % 84.7 0.0 85.7 1.6
正班载运率 % 75.7 0.8 74.0 1.4
三、机场完成情况
旅客吞吐量 万人次 11386.7 -6.3 74545.5 1.0
其中：东部地区 万人次 6036.8 -4.5 39946.3 2.4
货邮吞吐量 万吨 189.6 1.1 1079.5 4.7
起降架次 万架次 92.6 -9.4 583.3 -3.8
注：相关数为快报数据汇总，最终数据以年报为准
"""


def test_parse_caac_text_preserves_month_ytd_and_scope() -> None:
    result = parse_caac_sector_kpi_text(
        SAMPLE_TEXT,
        observation_month="2026-06",
        source_release_date="2026-07-21",
        source_url="https://example.test/caac.pdf",
        retrieved_at="2026-08-09T00:00:00+00:00",
    )

    assert list(result.columns) == OUTPUT_COLUMNS
    assert len(result) == 24
    total_turnover = result.loc[
        result["metric"].eq("total_transport_turnover")
        & result["period_type"].eq("monthly")
        & result["scope"].eq("total")
    ].iloc[0]
    assert total_turnover["value"] == pytest.approx(133.4)
    assert total_turnover["yoy_pct"] == pytest.approx(0.2)
    assert total_turnover["scope"] == "total"
    hkt = result.loc[
        result["scope"].eq("hk_macao_taiwan") & result["metric"].eq("total_transport_turnover")
    ].iloc[0]
    assert hkt["value"] == pytest.approx(1.3)
    ytd = result.loc[
        result["metric"].eq("airport_passenger_throughput")
        & result["period_type"].eq("ytd")
        & result["scope"].eq("total")
    ].iloc[0]
    assert ytd["value"] == pytest.approx(74545.5)
    assert ytd["point_in_time_status"] == "release_date_safe_observation"


def test_parse_caac_rejects_invalid_month() -> None:
    with pytest.raises(ValueError, match="Invalid CAAC observation_month"):
        parse_caac_sector_kpi_text(
            SAMPLE_TEXT,
            observation_month="202606",
            source_release_date="2026-07-21",
            source_url="https://example.test/caac.pdf",
        )


def test_parse_caac_english_tables_handles_compact_labels_and_northeast() -> None:
    tables = [
        [
            ["Indicator", "Unit", "Value", "YoY % Increase", "Value", "YoY % Increase"],
            ["III. Traffic Handled by Airports", None, None, None, None, None],
            ["Passenger Throughput", "10,000 Passengers", "100.0", "1.0", "200.0", "2.0"],
            ["Eastern Region", "10,000 Passengers", "50.0", "1.0", "100.0", "2.0"],
            ["Northeastern Region", "10,000 Passengers", "5.0", "-1.0", "10.0", "-2.0"],
            ["Cargo and Mail Throughput", "10,000 Tonnes", "20.0", "3.0", "40.0", "4.0"],
        ]
    ]
    result = parse_caac_sector_kpi_tables(
        tables,
        observation_month="2025-06",
        source_release_date="2025-07-21",
        source_url="https://example.test/caac-english.pdf",
        retrieved_at="2026-08-09T00:00:00+00:00",
    )

    assert len(result) == 8
    northeast = result.loc[result["scope"].eq("northeast")].iloc[0]
    assert northeast["metric"] == "airport_passenger_throughput"
    assert northeast["value"] == pytest.approx(5.0)
