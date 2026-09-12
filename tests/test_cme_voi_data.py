from __future__ import annotations

from pathlib import Path

from cme_voi_data.client import CmeBulletinClient
from cme_voi_data.models import CmeObservation
from cme_voi_data.storage import CmeVoiStorage


def _cme_obs(dt: str, code: str, month: str, p: float, p_chg: float, vol: int, oi: int, oi_chg: int, flow: str, fetched_at: str) -> CmeObservation:
    return CmeObservation(
        trade_date=dt,
        product_code=code,
        contract_month=month,
        settle_price=p,
        price_change=p_chg,
        volume=vol,
        open_interest=oi,
        open_interest_change=oi_chg,
        flow_regime=flow,
        fetched_at=fetched_at,
    )


def test_cme_upsert_observations_dedupes(tmp_path: Path) -> None:
    storage = CmeVoiStorage(tmp_path)
    storage.upsert_observations([
        _cme_obs("2026-09-01", "ES", "2026-09", 5650.0, 15.0, 120000, 1800000, 2500, "BULLISH_INFLOW", "t1"),
        _cme_obs("2026-09-01", "NQ", "2026-09", 19800.0, -50.0, 80000, 450000, -1200, "LONG_LIQUIDATION", "t1"),
    ])
    merged = storage.upsert_observations([
        _cme_obs("2026-09-01", "ES", "2026-09", 5650.0, 15.0, 125000, 1800000, 2500, "BULLISH_INFLOW", "t2"),
        _cme_obs("2026-09-02", "ES", "2026-09", 5670.0, 20.0, 110000, 1805000, 5000, "BULLISH_INFLOW", "t2"),
    ])
    assert len(merged) == 3
    es_0901 = merged[(merged["product_code"] == "ES") & (merged["trade_date"] == "2026-09-01")]
    assert len(es_0901) == 1
    assert es_0901.iloc[0]["volume"] == 125000


def test_cme_flow_classification() -> None:
    assert CmeBulletinClient.classify_positioning_flow(10.0, 500) == "BULLISH_INFLOW"
    assert CmeBulletinClient.classify_positioning_flow(-10.0, 500) == "BEARISH_INFLOW"
    assert CmeBulletinClient.classify_positioning_flow(10.0, -500) == "SHORT_COVERING"
    assert CmeBulletinClient.classify_positioning_flow(-10.0, -500) == "LONG_LIQUIDATION"
    assert CmeBulletinClient.classify_positioning_flow(0.0, 500) == "NEUTRAL"
