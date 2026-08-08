from pathlib import Path

import pandas as pd

from hk_transport.sources.airline_stock_connect_short_selling import (
    parse_hkex_stock_connect_short_selling,
)


def test_parse_hkex_stock_connect_short_selling_keeps_available_display_separate() -> None:
    javascript = '''
    tabData = [{"content":[{"table":{"tr":[
      {"tableTitle":false,"td":[[" ","601111","AIR CHINA","Available","123","456789","0.12%","0.34%"]]},
      {"tableTitle":false,"td":[[" ","603885","JUNEYAO AIRLINES","212900","7","890","0.01%","0.02%"]]},
      {"tableTitle":false,"td":[[" ","000001","OTHER","100","1","2","3.00%","4.00%"]]}
    ]}}]}]
    '''
    result = parse_hkex_stock_connect_short_selling(
        javascript,
        observation_date="2026-08-06",
        source_url="https://www.hkex.hk/example.js",
        retrieved_at="2026-08-07T00:00:00+00:00",
    )
    assert len(result) == 2
    air_china = result.loc[result["ticker"].eq("601111.SH")].iloc[0]
    assert air_china["remaining_available_display"] == "Available"
    assert pd.isna(air_china["remaining_available_shares"])
    assert air_china["short_selling_turnover_shares"] == 123
    juneyao = result.loc[result["ticker"].eq("603885.SH")].iloc[0]
    assert juneyao["remaining_available_shares"] == 212900
    assert juneyao["short_selling_pct_10d"] == 0.02
    assert bool(juneyao["borrow_data_available"]) is False


def test_current_stock_connect_short_selling_history_covers_six_a_share_airlines() -> None:
    frame = pd.read_csv(
        Path("data/normalized/hk_transport/airline_stock_connect_short_selling.csv")
    )
    assert len(frame) >= 6
    assert frame["company"].nunique() == 6
    assert frame["observation_date"].notna().all()
    assert frame["short_selling_turnover_shares"].ge(0).all()
    assert frame["short_selling_turnover_value_rmb"].ge(0).all()
    assert frame["short_selling_pct_today"].dropna().ge(0).all()
    assert frame["short_selling_pct_10d"].dropna().ge(0).all()
    assert frame["borrow_data_available"].eq(False).all()
