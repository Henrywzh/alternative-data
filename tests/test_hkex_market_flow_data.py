from __future__ import annotations

from pathlib import Path

from hkex_market_flow_data.client import HkexMarketFlowClient
from hkex_market_flow_data.models import HkexDailyFlowObservation
from hkex_market_flow_data.storage import HkexMarketFlowStorage


def _hkex_obs(dt: str, sb_net: float, sb_share: float, short_ratio: float, fetched_at: str) -> HkexDailyFlowObservation:
    return HkexDailyFlowObservation(
        trade_date=dt,
        southbound_buy_turnover_hkd_mln=15000.0,
        southbound_sell_turnover_hkd_mln=12000.0,
        southbound_net_inflow_hkd_mln=sb_net,
        northbound_buy_turnover_rmb_mln=40000.0,
        northbound_sell_turnover_rmb_mln=38000.0,
        northbound_net_inflow_rmb_mln=2000.0,
        total_market_turnover_hkd_mln=120000.0,
        southbound_turnover_share_pct=sb_share,
        short_selling_turnover_hkd_mln=18000.0,
        short_selling_ratio_pct=short_ratio,
        fetched_at=fetched_at,
    )


def test_hkex_upsert_observations_dedupes(tmp_path: Path) -> None:
    storage = HkexMarketFlowStorage(tmp_path)
    storage.upsert_observations([
        _hkex_obs("2026-08-31", 3000.0, 22.5, 15.0, "t1"),
        _hkex_obs("2026-09-01", 2500.0, 21.0, 14.8, "t1"),
    ])
    merged = storage.upsert_observations([
        _hkex_obs("2026-08-31", 3200.0, 22.8, 15.1, "t2"),
        _hkex_obs("2026-09-02", 4000.0, 24.0, 16.0, "t2"),
    ])
    assert len(merged) == 3
    rec_0831 = merged[merged["trade_date"] == "2026-08-31"]
    assert len(rec_0831) == 1
    assert rec_0831.iloc[0]["southbound_net_inflow_hkd_mln"] == 3200.0


def test_hkex_metric_derivation() -> None:
    obs = HkexMarketFlowClient.derive_flow_metrics(
        trade_date="2026-09-01",
        sb_buy_hkd=15000.0,
        sb_sell_hkd=10000.0,
        nb_buy_rmb=45000.0,
        nb_sell_rmb=40000.0,
        total_mkt_hkd=100000.0,
        short_turnover_hkd=15000.0,
    )
    assert obs.southbound_net_inflow_hkd_mln == 5000.0
    assert obs.northbound_net_inflow_rmb_mln == 5000.0
    assert obs.southbound_turnover_share_pct == 25.0
    assert obs.short_selling_ratio_pct == 15.0
