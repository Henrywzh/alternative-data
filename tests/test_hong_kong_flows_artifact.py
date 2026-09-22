"""Offline contracts for the Hong Kong institutional context artifact."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = (
    ROOT
    / "apps"
    / "asia-markets-dashboard"
    / "scripts"
    / "build_hong_kong_flows_artifact.py"
)
GLOBAL_BUILDER_PATH = (
    ROOT
    / "apps"
    / "asia-markets-dashboard"
    / "scripts"
    / "build_global_market_regime_artifact.py"
)


def _load_builder():
    spec = importlib.util.spec_from_file_location("hong_kong_flows_artifact", BUILDER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_global_builder():
    spec = importlib.util.spec_from_file_location("global_market_regime_artifact", GLOBAL_BUILDER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hong_kong_artifact_excludes_canonical_southbound_dataset(monkeypatch) -> None:
    builder = _load_builder()
    frames = {
        builder.HKMA_PATH: pd.DataFrame(
            [
                {
                    "date": "2026-09-16",
                    "series_id": "HKMA_HIBOR_1M",
                    "value": 2.1,
                    "fetched_at": "2026-09-17T00:00:00Z",
                    "source_url": builder.HKMA_SOURCE_URL,
                    "source_tier": "official_api",
                }
            ]
        ),
        builder.HKEX_PATH: pd.DataFrame(
            [
                {
                    "trade_date": "2026-09-16",
                    "short_selling_security_count": 100,
                    "short_selling_shares_available": 1_000_000,
                    "fetched_at": "2026-09-17T00:00:00Z",
                }
            ]
        ),
        builder.MSCI_PATH: pd.DataFrame(
            [
                {
                    "review_cycle": "2026-08-STANDARD",
                    "announcement_date": "2026-08-12",
                    "effective_date": "2026-08-31",
                    "action": "ADD",
                    "index_name": "MSCI HONG KONG INDEX",
                    "country": "HK",
                    "security_name": "Example Holdings",
                    "size_segment": "STANDARD",
                    "source_url": builder.MSCI_SOURCE_URL,
                }
            ]
        ),
        builder.SOUTHBOUND_PATH: pd.DataFrame(
            [{"trade_date": "2014-11-17", "net_buy_yi": 21.3}]
        ),
    }
    monkeypatch.setattr(builder, "_read_parquet", lambda path: frames.get(path, pd.DataFrame()))

    artifact, status = builder._build_artifact()
    datasets = artifact["snapshot"]["datasets"]

    assert "southbound_market_flow" not in datasets
    assert "hkex_short_inventory_daily" in datasets
    assert "hkma_liquidity_daily" in datasets
    assert "msci_index_events" in datasets
    reference = next(
        row for row in datasets["source_health"] if row["series_id"] == "southbound_market_flow"
    )
    assert reference["status"] == "Reference"
    assert status["overall_status"] == "Healthy"


def test_factset_loader_filters_empty_articles_and_reports_fill_floor(tmp_path) -> None:
    builder = _load_global_builder()
    path = tmp_path / "factset.parquet"
    pd.DataFrame(
        [
            {
                "report_date": "2026-08-07",
                "reference_quarter": "2026Q2",
                "blended_earnings_growth_yoy": 47.4,
                "forward_12m_pe": 20.0,
                "forward_12m_pe_10y_avg": 19.0,
                "source_url": "https://insight.factset.com/example",
                "fetched_at": "2026-09-17T00:00:00Z",
            },
            {
                "report_date": "2026-09-04",
                "reference_quarter": "2026Q3",
                "source_url": "https://insight.factset.com/empty",
                "fetched_at": "2026-09-17T00:00:00Z",
            },
        ]
    ).to_parquet(path, index=False)
    builder.FACTSET_PATH = path

    frame, health = builder._load_factset_earnings()

    assert len(frame) == 1
    assert frame.iloc[0]["report_date"].strftime("%Y-%m-%d") == "2026-08-07"
    assert health["records"] == 2
    assert health["usable_records"] == 1
    assert health["status"] == "Partial"
    assert health["fill_rate_last_24"] == 0.5
    assert health["article_catalog_path"] == "data/normalized/factset_earnings/factset_article_catalog.parquet"
