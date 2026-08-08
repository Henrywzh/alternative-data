from __future__ import annotations

import pandas as pd
from pathlib import Path

from hk_transport.sources.airline_short_side_proxies import (
    normalize_sse_margin_detail,
    parse_hkex_short_turnover,
)


def test_parse_hkex_short_turnover_uses_current_table_not_adjustment_table() -> None:
    html = """
    <html><body>
    SHORT SELLING TURNOVER - DAILY REPORT
    CODE NAME OF STOCK Total Short Selling Turnover Total Turnover
    (SH) ($) (SH) ($)
        293 CATHAY PAC AIR 7,434,000 111,859,770 24,245,604 364,305,983
        670 CHINA EAST AIR 1,030,000 3,412,640 8,240,000 27,326,382
    PREVIOUS DAY'S ADJUSTED SHORT SELLING TURNOVER
        293 CATHAY PAC AIR 5,714,000 84,258,790
    </body></html>
    """
    result = parse_hkex_short_turnover(
        html,
        observation_date="2026-08-06",
        retrieved_at="2026-08-07T00:00:00+00:00",
    )
    assert len(result) == 2
    cathay = result.loc[result["ticker"].eq("0293.HK")].iloc[0]
    assert cathay["short_turnover_shares"] == 7434000
    assert cathay["total_turnover_native"] == 364305983
    assert round(cathay["short_turnover_pct"], 4) == round(100 * 111859770 / 364305983, 4)
    assert bool(cathay["borrow_data_available"]) is False


def test_normalize_sse_margin_detail_keeps_short_balance_separate_from_borrow() -> None:
    raw = pd.DataFrame(
        [
            {
                "信用交易日期": "20260806",
                "标的证券代码": "601111",
                "标的证券简称": "中国国航",
                "融资余额": "100",
                "融资买入额": "10",
                "融资偿还额": "8",
                "融券余量": "12345",
                "融券卖出量": "678",
                "融券偿还量": "111",
            }
        ]
    )
    result = normalize_sse_margin_detail(
        raw,
        observation_date="2026-08-06",
        retrieved_at="2026-08-07T00:00:00+00:00",
    )
    assert len(result) == 1
    row = result.iloc[0]
    assert row["ticker"] == "601111.SH"
    assert row["margin_short_balance_shares"] == 12345
    assert row["margin_short_sell_volume"] == 678
    assert bool(row["margin_security_present"]) is True
    assert bool(row["borrow_data_available"]) is False


def test_current_short_side_proxy_snapshot_covers_hk_and_a_share_names() -> None:
    frame = pd.read_csv(Path("data/normalized/hk_transport/airline_short_side_proxies.csv"))
    assert len(frame) == 10
    assert set(frame["market"]) == {"HK", "CN_A"}
    assert frame["observation_date"].eq("2026-08-06").all()
    assert frame["short_proxy_status"].eq("observed").all()
    assert frame["borrow_data_available"].eq(False).all()
