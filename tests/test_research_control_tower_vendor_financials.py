"""Vendor financial overlay is labelled, separate from official actuals."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.research_control_tower.vendor_financials import (
    VendorLoadResult,
    _latest_observation_file,
    _map_akshare,
    _map_yfinance,
    load_vendor_financials,
    materialize_vendor_financials,
    vendor_source_caption,
)


def _yf_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "observation_id": "a",
                "ticker": "9988.HK",
                "statement_type": "income_statement",
                "metric": "revenue",
                "metric_label": "Operating Revenue",
                "fiscal_period_end": "2026-03-31",
                "period_type": "annual",
                "currency": "CNY",
                "currency_semantics": "reporting_currency",
                "unit": "currency",
                "value": 9.87243e11,
                "fetched_at": "2026-07-26T16:10:38Z",
            },
            {
                "observation_id": "b",
                "ticker": "9988.HK",
                "statement_type": "income_statement",
                "metric": "revenue",
                "metric_label": "Total Revenue",
                "fiscal_period_end": "2026-03-31",
                "period_type": "annual",
                "currency": "CNY",
                "currency_semantics": "reporting_currency",
                "unit": "currency",
                "value": 1.02367e12,
                "fetched_at": "2026-07-26T16:10:38Z",
            },
            {
                "observation_id": "c",
                "ticker": "9988.HK",
                "statement_type": "income_statement",
                "metric": "net_income",
                "metric_label": "Net Income",
                "fiscal_period_end": "2026-03-31",
                "period_type": "annual",
                "currency": "CNY",
                "unit": "currency",
                "value": 1.0e11,
                "fetched_at": "2026-07-26T16:10:38Z",
            },
            {
                "observation_id": "d",
                "ticker": "9988.HK",
                "statement_type": "income_statement",
                "metric": "net_income_attributable",
                "metric_label": "Net Income Attributable",
                "fiscal_period_end": "2026-03-31",
                "period_type": "annual",
                "currency": "CNY",
                "unit": "currency",
                "value": 1.03592e11,
                "fetched_at": "2026-07-26T16:10:38Z",
            },
        ]
    )


def test_yfinance_prefers_total_revenue_and_attributable_income():
    mapped = _map_yfinance(
        _yf_frame(),
        entity_id="ALIBABA",
        listing_id="9988_HK",
        source_path=Path("financials-yfinance-fixture.parquet"),
    )
    revenue = mapped.loc[mapped["metric"].eq("revenue_total")]
    profit = mapped.loc[mapped["metric"].eq("net_profit_attributable")]
    assert len(revenue) == 1
    assert float(revenue.iloc[0]["reported_value"]) == 1.02367e12
    assert revenue.iloc[0]["source_metric_label"] == "Total Revenue"
    assert len(profit) == 1
    assert float(profit.iloc[0]["reported_value"]) == 1.03592e11
    assert mapped["metric_basis"].eq("PROVIDER_UNVERIFIED").all()
    assert mapped["source_id"].eq("financial_data:yfinance:financial_observations").all()
    assert "Not official issuer disclosure" in mapped.iloc[0]["source_note"]
    assert not bool(mapped.iloc[0]["interim_is_ytd"])


def test_akshare_interim_is_marked_year_to_date():
    raw = pd.DataFrame(
        [
            {
                "ticker": "0700.HK",
                "metric": "akshare_revenue",
                "metric_label": "akshare_revenue",
                "fiscal_period_end": "2025-09-30",
                "period_type": "interim",
                "currency": "HKD",
                "currency_semantics": "source_reported_unverified",
                "unit": "currency",
                "value": 4.87811e11,
                "fetched_at": "2026-07-28T21:35:26Z",
            },
            {
                "ticker": "0700.HK",
                "metric": "akshare_revenue",
                "metric_label": "akshare_revenue",
                "fiscal_period_end": "2025-12-31",
                "period_type": "annual",
                "currency": "HKD",
                "currency_semantics": "source_reported_unverified",
                "unit": "currency",
                "value": 6.60257e11,
                "fetched_at": "2026-07-28T21:35:26Z",
            },
        ]
    )
    mapped = _map_akshare(
        raw,
        entity_id="TENCENT",
        listing_id="0700_HK",
        source_path=Path("financials-akshare-fixture.parquet"),
    )
    interim = mapped.loc[mapped["period_type"].eq("interim")].iloc[0]
    annual = mapped.loc[mapped["period_type"].eq("annual")].iloc[0]
    assert bool(interim["interim_is_ytd"]) is True
    assert bool(annual["interim_is_ytd"]) is False
    assert interim["currency_semantics"] == "source_reported_unverified"
    assert "year-to-date cumulatives" in interim["source_note"]


def test_caption_never_claims_official_source():
    mapped = _map_yfinance(
        _yf_frame(),
        entity_id="ALIBABA",
        listing_id="9988_HK",
        source_path=Path("financials-yfinance-fixture.parquet"),
    )
    caption = vendor_source_caption(mapped)
    lowered = caption.lower()
    assert caption.startswith("Not official issuer disclosure.")
    assert "yfinance" in caption
    assert "financial-data" in caption
    assert "do not treat as pit official actuals" in lowered
    assert "year-to-date" in lowered
    assert not lowered.startswith("official issuer disclosure")


def test_missing_store_returns_empty_and_does_not_invent_values(tmp_path: Path):
    listings = pd.DataFrame(
        [{"listing_id": "9988_HK", "canonical_ticker": "9988.HK", "native_ticker": "9988", "entity_id": "ALIBABA"}]
    )
    result = load_vendor_financials(
        entity_id="ALIBABA",
        listing_id="9988_HK",
        listings=listings,
        financial_data_root_path=tmp_path,
        local_mart_path=tmp_path / "missing.parquet",
        allow_sibling_fallback=True,
    )
    assert result.frame.empty
    assert result.status == "unavailable"
    caption = vendor_source_caption(result)
    assert caption.startswith("Not official issuer disclosure.")
    assert "missing" in result.detail or "not found" in result.detail


def test_local_mart_is_preferred_over_sibling(tmp_path: Path):
    mart = tmp_path / "vendor_financials_v1.parquet"
    pd.DataFrame(
        [
            {
                "entity_id": "ALIBABA",
                "listing_id": "9988_HK",
                "canonical_ticker": "9988.HK",
                "provider": "yfinance",
                "source_id": "financial_data:yfinance:financial_observations",
                "source_label": "yfinance via financial-data",
                "metric": "revenue_total",
                "source_metric": "revenue",
                "source_metric_label": "Total Revenue",
                "period_type": "annual",
                "period_label": "FY2026",
                "period_end": "2026-03-31",
                "reported_value": 1.0,
                "currency": "CNY",
                "currency_semantics": "reporting_currency",
                "unit": "currency",
                "interim_is_ytd": False,
                "accounting_basis": "Vendor reported (unverified)",
                "metric_basis": "PROVIDER_UNVERIFIED",
                "source_quality": "provider_unverified",
                "pit_class": "vendor_historical_replay",
                "source_license_class": "personal_use_terms_unverified",
                "announcement_date": pd.NaT,
                "retrieved_at_utc": pd.Timestamp("2026-07-26T16:10:38Z"),
                "source_path": "fixture.parquet",
                "source_note": "fixture",
            }
        ]
    ).to_parquet(mart, index=False)
    listings = pd.DataFrame(
        [{"listing_id": "9988_HK", "canonical_ticker": "9988.HK", "native_ticker": "9988", "entity_id": "ALIBABA"}]
    )
    result = load_vendor_financials(
        entity_id="ALIBABA",
        listing_id="9988_HK",
        listings=listings,
        local_mart_path=mart,
        allow_sibling_fallback=False,
    )
    assert result.status == "available"
    assert result.source_kind == "local_mart"
    assert len(result.frame) == 1
    assert float(result.frame.iloc[0]["reported_value"]) == 1.0


def test_latest_observation_file_skips_tiny_newer_manifests(tmp_path: Path):
    yf = tmp_path / "data/processed/hk_financials/financial_observations/source=yfinance"
    old = yf / "snapshot_date=2026-07-26"
    new = yf / "snapshot_date=2026-07-28"
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    complete = old / "financials-yfinance-20260726T161038Z.parquet"
    manifest = new / "financials-yfinance-20260728T213526Z.parquet"
    complete.write_bytes(b"x" * 120_000)
    manifest.write_bytes(b"tiny")
    chosen = _latest_observation_file(tmp_path, "yfinance")
    assert chosen == complete


def test_company_page_keeps_vendor_overlay_labelled_and_separate():
    source = Path('apps/research-control-tower/control_tower/pages/company.py').read_text()
    assert 'Vendor financials overlay (not official)' in source
    assert 'yfinance and/or akshare' in source
    assert 'Official LTM cards stay unavailable' in source
    assert 'Interim is YTD' in source
    overlay_fn = source[source.index('def _vendor_financials_for_view'):source.index('def _vendor_series')]
    assert 'except Exception:' not in overlay_fn
    assert 'except (OSError, ValueError)' in overlay_fn
    assert source.index('_company_earnings_actuals(snapshot, view)') < source.index('_render_vendor_financials_overlay(view)')

