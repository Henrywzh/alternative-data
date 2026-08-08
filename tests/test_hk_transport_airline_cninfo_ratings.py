from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_cninfo_rating_events import normalize_cninfo_rating_events


def test_cninfo_rating_event_normalization_keeps_previous_rating_and_scope() -> None:
    source = pd.DataFrame(
        {
            "证券代码": ["601111", "600029", "000001"],
            "证券简称": ["中国国航", "南方航空", "other"],
            "发布日期": ["2026-07-21", "2026-07-21", "2026-07-21"],
            "研究机构简称": ["中信", "华泰", "other"],
            "研究员名称": ["A", "B", "C"],
            "投资评级": ["买入", "增持", "买入"],
            "是否首次评级": ["不是首次评级"] * 3,
            "评级变化": ["维持", "未知", "维持"],
            "前一次投资评级": ["买入", "不评级", "买入"],
            "目标价格-下限": [8.0, 7.0, 1.0],
            "目标价格-上限": [8.5, 7.5, 1.0],
        }
    )
    result = normalize_cninfo_rating_events([("2026-07-21", source)], retrieved_at="2026-08-07T00:00:00+00:00")
    assert len(result) == 2
    assert result["history_scope"].eq("queried_public_report_dates").all()
    assert result["source_quality"].eq("cninfo_discovery").all()
    air_china = result.loc[result["ticker"].str.contains("601111")].iloc[0]
    assert air_china["previous_rating"] == "买入"
    assert air_china["rating_direction"] == "maintain_or_new"
