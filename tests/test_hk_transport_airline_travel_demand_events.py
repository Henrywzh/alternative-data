from __future__ import annotations

import pytest

from src.hk_transport.sources.airline_travel_demand_events import (
    SOURCE_SPECS,
    parse_mct_tourism_article,
    parse_mot_spring_transport_article,
)


def _spec(event_id: str) -> dict[str, object]:
    return next(spec for spec in SOURCE_SPECS if spec["event_id"] == event_id)


def test_mct_spring_derives_duration_adjusted_growth_from_official_prior_increase() -> None:
    payload = (
        "2026年春节假期国内出游5.96亿人次。春节假日9天，全国国内出游5.96亿人次，"
        "较2025年春节假日8天增加0.95亿人次；国内出游总花费8034.83亿元，"
        "较2025年春节假日8天增加1264.81亿元。"
    )
    result = parse_mct_tourism_article(payload, spec=_spec("mct_2026_spring_tourism"))
    travelers = result.set_index("metric").loc["domestic_travelers"]
    spend = result.set_index("metric").loc["domestic_tourism_spend"]

    assert travelers["value"] == pytest.approx(596.0)
    assert travelers["prior_value"] == pytest.approx(501.0)
    assert travelers["prior_duration_days"] == 8
    assert travelers["yoy_method"] == "derived_from_source_reported_prior_period_increase_and_duration"
    assert travelers["daily_yoy_pct"] == pytest.approx(5.744067)
    assert spend["value"] == pytest.approx(803_483.0)
    assert spend["prior_value"] == pytest.approx(677_002.0)


def test_mot_parser_keeps_total_yoy_separate_from_submode_rows() -> None:
    payload = (
        "春运40天全社会跨区域人员流动量94亿人次，日均2.35亿人次，"
        "比2025年同期增长4.3％。其中，铁路客运量累计5.38亿人次，"
        "公路人员流动量累计87.36亿人次，水路、民航客运量累计3595万人次、9439万人次。"
    )
    result = parse_mot_spring_transport_article(
        payload,
        spec=_spec("mot_2026_spring_transport"),
    ).set_index("metric")

    assert result.loc["cross_regional_person_flow", "value"] == pytest.approx(9_400.0)
    assert result.loc["cross_regional_person_flow", "yoy_pct"] == pytest.approx(4.3)
    assert result.loc["rail_passengers", "value"] == pytest.approx(538.0)
    assert result.loc["waterway_passengers", "value"] == pytest.approx(35.95)
    assert result.loc["civil_aviation_passengers", "value"] == pytest.approx(94.39)
    assert result.loc["civil_aviation_passengers", "yoy_pct"] != result.loc["cross_regional_person_flow", "yoy_pct"]
    assert result.loc["civil_aviation_passengers", "yoy_method"] == "not_reported_for_submode"
