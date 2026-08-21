from __future__ import annotations

from pathlib import Path

import pandas as pd

import scripts.research_control_tower_price_bars as price_bars


def _listing_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "listing_id": "0700_HK",
                "entity_id": "TENCENT",
                "canonical_ticker": "0700.HK",
                "currency": "HKD",
                "mapping_status": "verified",
                "collection_eligible": "true",
                "listing_status": "active",
                "active_from": "2026-01-01",
                "active_to": "",
            },
            {
                "listing_id": "TCEHY_US",
                "entity_id": "TENCENT",
                "canonical_ticker": "TCEHY.US",
                "currency": "USD",
                "mapping_status": "unresolved",
                "collection_eligible": "false",
                "listing_status": "active",
                "active_from": "2026-01-01",
                "active_to": "",
            },
        ]
    )


def test_price_bar_provider_gate_rejects_tcehy_and_retains_0700(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    listings_path = tmp_path / "listings.csv"
    output_path = tmp_path / "price_bars.parquet"
    _listing_rows().to_csv(listings_path, index=False)
    pd.DataFrame([{
        "basket_id": "STAGE",
        "active_from": "2026-01-01",
        "active_to": "",
    }]).to_csv(tmp_path / "baskets.csv", index=False)
    pd.DataFrame([
        {"basket_id": "STAGE", "entity_id": "TENCENT", "active_from": "2026-01-01", "active_to": ""},
        {"basket_id": "STAGE", "entity_id": "TENCENT", "active_from": "2020-01-01", "active_to": "2026-01-01"},
    ]).to_csv(tmp_path / "basket_memberships.csv", index=False)
    observed: dict[str, list[str]] = {"financial_data": [], "yfinance": []}

    def fake_financial(listings, cutoff, now):
        observed["financial_data"] = listings["listing_id"].tolist()
        return [], []

    def fake_yfinance(listings, cutoff, now):
        observed["yfinance"] = listings["listing_id"].tolist()
        return [], []

    monkeypatch.setattr(price_bars, "_rows_from_financial_data", fake_financial)
    monkeypatch.setattr(price_bars, "_rows_from_yfinance", fake_yfinance)

    assert price_bars.main([
        "--listings", str(listings_path),
        "--output", str(output_path),
        "--basket", "STAGE",
    ]) == 0

    assert observed["financial_data"] == ["0700_HK"]
    assert observed["yfinance"] == []
    assert output_path.exists()
    output = capsys.readouterr().out
    assert "TCEHY_US" in output
    assert "mapping_status=unresolved" in output
