import pytest

from src.hk_transport.sources.airline_caac_route_licence import (
    OUTPUT_COLUMNS,
    parse_caac_route_licence_text,
)


def test_parse_caac_route_licence_event_tables() -> None:
    text = """
    中国民用航空局 2026 年夏秋航季换季国内航线经营许可新增情况表
    25 新增许可 登记 九元航 广州-嘉兴 2026.03.29 14
    30 新增许可 登记 春秋航 广州-无锡 2026.03.29 14
    24 新增许可 登记 首都航 北京-文山-丽江 2026.03.29 14
    1 新增许可 登记 南航 国内（不含港澳台）货运航线 换发
    1 注销 登记 首都航 北京-攀枝花 2026.03.10
    """
    result = parse_caac_route_licence_text(text, page_number=2, retrieved_at="test")

    assert list(result.columns) == OUTPUT_COLUMNS
    assert len(result) == 5
    spring = result.loc[result["airline_short_name"].eq("春秋航")].iloc[0]
    assert spring["airline_normalized_name"] == "Spring Airlines"
    assert spring["planned_start_date"] == "2026-03-29"
    assert spring["initial_frequency_per_week"] == pytest.approx(14.0)
    assert spring["frequency_status"] == "stated_initial_frequency"

    multi_leg = result.loc[result["route_text"].eq("北京-文山-丽江")].iloc[0]
    assert multi_leg["origin_city"] == "北京"
    assert multi_leg["intermediate_stops"] == "文山"
    assert multi_leg["destination_city"] == "丽江"
    assert multi_leg["route_leg_count"] == 2

    cancelled = result.loc[result["table_type"].eq("cancelled_route_licence")].iloc[0]
    assert cancelled["cancellation_date"] == "2026-03-10"
    assert cancelled["point_in_time_status"] == "official_release_date_available_planned_supply"

    cargo = result.loc[result["table_type"].eq("renewed_domestic_cargo_licence")].iloc[0]
    assert cargo["frequency_status"] == "not_stated"
    assert cargo["note"] == "换发"


def test_parse_caac_route_licence_requires_rows() -> None:
    with pytest.raises(ValueError, match="no event rows"):
        parse_caac_route_licence_text("序号 航司 航线", retrieved_at="test")
