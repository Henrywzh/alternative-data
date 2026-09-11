from __future__ import annotations

from pathlib import Path

from sp_pmi_data.client import SpPmiClient
from sp_pmi_data.models import SpPmiObservation
from sp_pmi_data.storage import SpPmiStorage


def _pmi_obs(period: str, reg: str, sec: str, flash: bool, hd: float, orders: float, inv: float, fetched_at: str) -> SpPmiObservation:
    return SpPmiObservation(
        period=period,
        region=reg,
        sector=sec,
        is_flash=flash,
        headline_pmi=hd,
        new_orders_index=orders,
        output_index=51.0,
        finished_goods_inventory_index=inv,
        input_prices_index=55.0,
        output_prices_index=53.0,
        employment_index=50.5,
        orders_to_inventory_ratio=round(orders / inv, 4) if inv > 0 else None,
        price_pass_through_spread=-2.0,
        release_date="2026-08-21",
        fetched_at=fetched_at,
    )


def test_sp_pmi_upsert_observations_dedupes(tmp_path: Path) -> None:
    storage = SpPmiStorage(tmp_path)
    storage.upsert_observations([
        _pmi_obs("2026-08", "US", "MANUFACTURING", True, 49.5, 48.0, 50.0, "t1"),
        _pmi_obs("2026-08", "GLOBAL", "COMPOSITE", False, 52.5, 53.0, 49.0, "t1"),
    ])
    merged = storage.upsert_observations([
        _pmi_obs("2026-08", "US", "MANUFACTURING", False, 49.8, 48.5, 50.0, "t2"),
        _pmi_obs("2026-09", "US", "MANUFACTURING", True, 50.2, 50.5, 49.5, "t2"),
    ])
    assert len(merged) == 4


def test_sp_pmi_subindex_signals() -> None:
    obs = SpPmiClient.derive_subindex_signals(
        period="2026-08",
        region="GLOBAL",
        sector="MANUFACTURING",
        headline=53.5,
        new_orders=54.0,
        inventory=48.0,
        output=53.8,
        input_prices=56.0,
        output_prices=54.0,
        employment=51.0,
        is_flash=False,
        release_date="2026-09-01",
    )
    assert obs.orders_to_inventory_ratio == round(54.0 / 48.0, 4)
    assert obs.price_pass_through_spread == -2.0
