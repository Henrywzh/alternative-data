from __future__ import annotations

from typing import Any

import pandas as pd
import numpy as np
import pytest

from market_monitor.heatmaps import (
    FLOW_CALENDAR_DAYS,
    build_flow_snapshot,
    build_return_snapshot,
)
from market_monitor.us_etf.universe import HEATMAP_ETFS


def _spy() -> dict[str, str]:
    return {
        "ticker": "SPY",
        "name_en": "SPDR S&P 500 ETF",
        "name_zh": "标普500 ETF",
        "category": "broad_equity",
        "currency": "USD",
    }


def _metadata() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fund_id": "510300",
                "ticker": "510300",
                "exposure_id": "csi300",
                "index_id": "000300",
                "fund_name": "沪深300ETF",
                "venue": "SH",
                "category": "broad_equity",
            },
            {
                "fund_id": "159919",
                "ticker": "159919",
                "exposure_id": "csi300",
                "index_id": "000300",
                "fund_name": "沪深300ETF嘉实",
                "venue": "SZ",
                "category": "broad_equity",
            },
        ]
    )


def _activity(
    date: str,
    flow: float | None,
    status: str,
    fund_id: str = "510300",
    size: float | None = 10_000_000.0,
) -> dict[str, Any]:
    return {
        "observation_date": date,
        "fund_id": fund_id,
        "estimated_flow_cny": flow,
        "flow_status": status,
        "aum_nav_estimate_cny": size,
    }


def test_heatmap_universe_covers_five_asset_groups() -> None:
    assert {row["category"] for row in HEATMAP_ETFS} == {
        "broad_equity",
        "sector",
        "international",
        "commodity",
        "fixed_income",
    }


def test_heatmap_universe_has_unique_tickers_and_reference_members() -> None:
    tickers = [row["ticker"] for row in HEATMAP_ETFS]
    required = {
        "SPY",
        "QQQ",
        "XLK",
        "EFA",
        "GLD",
        "AGG",
        "IVV",
        "DIA",
        "RSP",
        "MDY",
        "IWM",
        "EEM",
        "SLV",
        "USO",
        "SHY",
        "HYG",
        "LQD",
        "IEF",
    }

    assert len(tickers) == len(set(tickers))
    assert required <= set(tickers)
    assert all(
        {"ticker", "name_en", "name_zh", "category", "currency"} <= row.keys()
        for row in HEATMAP_ETFS
    )


def test_return_snapshot_uses_trading_session_and_calendar_ytd() -> None:
    prices = pd.DataFrame(
        [
            {"date": "2025-12-31", "ticker": "SPY", "close": 100.0},
            {"date": "2026-01-02", "ticker": "SPY", "close": 110.0},
            {"date": "2026-01-05", "ticker": "SPY", "close": 121.0},
        ]
    )

    result = build_return_snapshot(prices, [_spy()], as_of="2026-01-05").iloc[0]

    assert result["as_of"] == "2026-01-05"
    assert result["latest_price"] == pytest.approx(121.0)
    assert result["return_1d_pct"] == pytest.approx(10.0)
    assert result["return_ytd_pct"] == pytest.approx(21.0)
    assert pd.isna(result["return_1m_pct"])


def test_return_snapshot_ytd_is_null_without_prior_year_baseline() -> None:
    prices = pd.DataFrame(
        [
            {"date": "2026-01-02", "ticker": "SPY", "close": 110.0},
            {"date": "2026-01-05", "ticker": "SPY", "close": 121.0},
        ]
    )

    result = build_return_snapshot(prices, [_spy()], as_of="2026-01-05").iloc[0]

    assert result["latest_price"] == pytest.approx(121.0)
    assert result["return_1d_pct"] == pytest.approx(10.0)
    assert pd.isna(result["return_ytd_pct"])


def test_return_snapshot_deduplicates_dates_and_rejects_non_positive_closes() -> None:
    prices = pd.DataFrame(
        [
            {"date": "2026-01-02", "ticker": "SPY", "close": 100.0},
            {"date": "2026-01-02", "ticker": "SPY", "close": 110.0},
            {"date": "2026-01-05", "ticker": "SPY", "close": 0.0},
            {"date": "2026-01-06", "ticker": "SPY", "close": 121.0},
        ]
    )

    result = build_return_snapshot(prices, [_spy()]).iloc[0]

    assert result["latest_price"] == pytest.approx(121.0)
    assert result["return_1d_pct"] == pytest.approx(10.0)


def test_return_snapshot_preserves_nulls_for_missing_or_short_histories() -> None:
    prices = pd.DataFrame(
        [
            {"date": "2026-01-02", "ticker": "SPY", "close": 100.0},
            {"date": "2026-01-05", "ticker": "SPY", "close": 110.0},
            {"date": "2026-01-05", "ticker": "QQQ", "close": 200.0},
        ]
    )
    universe = [_spy(), {**_spy(), "ticker": "QQQ", "name_en": "Invesco QQQ"}]

    result = build_return_snapshot(prices, universe).set_index("ticker")

    assert result.loc["SPY", "return_1d_pct"] == pytest.approx(10.0)
    assert pd.isna(result.loc["SPY", "return_1w_pct"])
    assert result.loc["QQQ", "latest_price"] == pytest.approx(200.0)
    assert pd.isna(result.loc["QQQ", "return_1d_pct"])


def test_return_snapshot_does_not_use_rows_after_as_of() -> None:
    prices = pd.DataFrame(
        [
            {"date": "2026-01-02", "ticker": "SPY", "close": 100.0},
            {"date": "2026-01-05", "ticker": "SPY", "close": 110.0},
            {"date": "2026-01-06", "ticker": "SPY", "close": 121.0},
        ]
    )

    result = build_return_snapshot(prices, [_spy()], as_of="2026-01-05").iloc[0]

    assert result["latest_price"] == pytest.approx(110.0)
    assert result["as_of"] == "2026-01-05"


def test_return_snapshot_handles_empty_prices_and_calculates_all_windows() -> None:
    empty_result = build_return_snapshot(pd.DataFrame(), [_spy()], as_of="2026-01-05")
    assert len(empty_result) == 1
    assert empty_result.iloc[0]["as_of"] == "2026-01-05"
    assert pd.isna(empty_result.iloc[0]["latest_price"])
    assert pd.isna(empty_result.iloc[0]["return_1d_pct"])

    dates = pd.date_range("2024-12-15", periods=280, freq="B").strftime("%Y-%m-%d")
    prices = pd.DataFrame([{"date": d, "ticker": "SPY", "close": 100.0 + i} for i, d in enumerate(dates)])
    full_result = build_return_snapshot(prices, [_spy()]).iloc[0]
    assert not pd.isna(full_result["return_1d_pct"])
    assert not pd.isna(full_result["return_1w_pct"])
    assert not pd.isna(full_result["return_1m_pct"])
    assert not pd.isna(full_result["return_3m_pct"])
    assert not pd.isna(full_result["return_1y_pct"])
    assert not pd.isna(full_result["return_ytd_pct"])


def test_flow_snapshot_sums_only_validated_rows() -> None:
    rows = pd.DataFrame(
        [
            _activity("2026-09-12", 100.0, "validated"),
            _activity("2026-09-13", 999.0, "shares_only"),
            _activity("2026-09-14", -40.0, "validated"),
        ]
    )
    row = build_flow_snapshot(rows, _metadata()).iloc[0]
    assert row["flow_1w"] == pytest.approx(60.0)
    assert row["valid_observations"] == 2
    assert row["first_valid_flow_date"] == "2026-09-12"
    assert row["latest_valid_flow_date"] == "2026-09-14"
    assert row["coverage_status"] == "validated"
    assert row["size_value"] == pytest.approx(10_000_000.0)
    assert row["size_basis"] == "nav_estimate"


def test_flow_snapshot_accepts_validated_market_cap_proxy_rows() -> None:
    rows = pd.DataFrame(
        [
            {
                "observation_date": "2026-09-14",
                "ticker": "SPY",
                "estimated_flow": 110.0,
                "flow_status": "validated_proxy",
                "size_value": 1_210.0,
                "size_basis": "market_cap_proxy",
            }
        ]
    )
    metadata = pd.DataFrame([{"fund_id": "SPY", "ticker": "SPY", "category": "broad_equity"}])
    row = build_flow_snapshot(rows, metadata).iloc[0]
    assert row["flow_1d"] == pytest.approx(110.0)
    assert row["coverage_status"] == "validated_proxy"
    assert row["size_basis"] == "market_cap_proxy"


def test_flow_snapshot_does_not_turn_unavailable_into_zero() -> None:
    row = build_flow_snapshot(
        pd.DataFrame([_activity("2026-09-14", None, "shares_only")]),
        _metadata(),
    ).iloc[0]
    assert pd.isna(row["flow_1d"])
    assert pd.isna(row["flow_1w"])
    assert pd.isna(row["flow_1m"])
    assert pd.isna(row["flow_3m"])
    assert pd.isna(row["flow_ytd"])
    assert row["valid_observations"] == 0
    assert pd.isna(row["first_valid_flow_date"]) or row["first_valid_flow_date"] is None
    assert pd.isna(row["latest_valid_flow_date"]) or row["latest_valid_flow_date"] is None
    assert row["coverage_status"] == "shares_only"


def test_flow_snapshot_handles_empty_inputs_and_unobserved_funds() -> None:
    meta = _metadata()
    rows = pd.DataFrame([_activity("2026-09-14", 50.0, "validated", fund_id="510300")])
    result = build_flow_snapshot(rows, meta).set_index("fund_id")

    assert result.loc["510300", "flow_1d"] == pytest.approx(50.0)
    assert result.loc["510300", "valid_observations"] == 1
    assert result.loc["510300", "coverage_status"] == "validated"

    assert pd.isna(result.loc["159919", "flow_1d"])
    assert result.loc["159919", "valid_observations"] == 0
    assert result.loc["159919", "coverage_status"] == "unavailable"
    assert pd.isna(result.loc["159919", "size_value"])

    empty_result = build_flow_snapshot(pd.DataFrame(), meta, as_of="2026-09-14")
    assert len(empty_result) == len(meta)
    assert (empty_result["coverage_status"] == "unavailable").all()
    assert (empty_result["valid_observations"] == 0).all()


def test_flow_snapshot_calculates_all_windows_and_calendar_ytd() -> None:
    rows = pd.DataFrame(
        [
            _activity("2025-12-15", 100.0, "validated"),
            _activity("2026-02-01", 10.0, "validated"),
            _activity("2026-07-01", 10.0, "validated"),
            _activity("2026-08-20", 10.0, "validated"),
            _activity("2026-09-10", 10.0, "validated"),
            _activity("2026-09-14", 10.0, "validated"),
        ]
    )
    row = build_flow_snapshot(rows, _metadata().iloc[[0]], as_of="2026-09-14").iloc[0]
    assert row["flow_1d"] == pytest.approx(10.0)
    assert row["flow_1w"] == pytest.approx(20.0)
    assert row["flow_1m"] == pytest.approx(30.0)
    assert row["flow_3m"] == pytest.approx(40.0)
    assert row["flow_ytd"] == pytest.approx(50.0)
    assert row["valid_observations"] == 6
    assert row["first_valid_flow_date"] == "2025-12-15"
    assert row["latest_valid_flow_date"] == "2026-09-14"


def test_flow_snapshot_respects_as_of_filter() -> None:
    rows = pd.DataFrame(
        [
            _activity("2026-09-10", 10.0, "validated"),
            _activity("2026-09-14", 20.0, "validated"),
            _activity("2026-09-15", 30.0, "validated"),
        ]
    )
    row = build_flow_snapshot(rows, _metadata().iloc[[0]], as_of="2026-09-14").iloc[0]
    assert row["as_of"] == "2026-09-14"
    assert row["flow_1d"] == pytest.approx(20.0)
    assert row["valid_observations"] == 2
    assert row["latest_valid_flow_date"] == "2026-09-14"


def test_flow_snapshot_anchors_each_fund_to_its_latest_observation_in_asynchronous_dataset() -> None:
    rows = pd.DataFrame(
        [
            # CN fund observed through Monday 2026-09-14
            _activity("2026-09-12", 100.0, "validated", fund_id="510300"),
            _activity("2026-09-14", -40.0, "validated", fund_id="510300"),
            # US fund observed through Friday 2026-09-11
            _activity("2026-09-10", 50.0, "validated", fund_id="SPY"),
            _activity("2026-09-11", 25.0, "validated", fund_id="SPY"),
        ]
    )
    metadata = pd.DataFrame(
        [
            {"fund_id": "510300", "ticker": "510300", "category": "broad_equity"},
            {"fund_id": "SPY", "ticker": "SPY", "category": "broad_equity"},
        ]
    )
    result = build_flow_snapshot(rows, metadata).set_index("fund_id")

    # Dataset-level as_of is the latest date overall (2026-09-14)
    assert result.loc["510300", "as_of"] == "2026-09-14"
    assert result.loc["SPY", "as_of"] == "2026-09-14"

    # CN fund is anchored to 2026-09-14
    assert result.loc["510300", "flow_1d"] == pytest.approx(-40.0)
    assert result.loc["510300", "flow_1w"] == pytest.approx(60.0)

    # US fund is anchored to its own latest observation (2026-09-11)
    assert result.loc["SPY", "flow_1d"] == pytest.approx(25.0)
    assert result.loc["SPY", "flow_1w"] == pytest.approx(75.0)


def test_flow_snapshot_handles_nan_and_custom_size_basis() -> None:
    rows = pd.DataFrame(
        [
            {
                "observation_date": "2026-09-14",
                "fund_id": "510300",
                "estimated_flow_cny": 10.0,
                "flow_status": "validated",
                "size_value": 1_000_000.0,
                "size_basis": np.nan,
            },
            {
                "observation_date": "2026-09-14",
                "fund_id": "159919",
                "estimated_flow_cny": 20.0,
                "flow_status": "validated",
                "size_value": 2_000_000.0,
                "size_basis": "market_cap_proxy",
            },
        ]
    )
    result = build_flow_snapshot(rows, _metadata()).set_index("fund_id")
    assert result.loc["510300", "size_basis"] == "nav_estimate"
    assert result.loc["159919", "size_basis"] == "market_cap_proxy"


def test_flow_snapshot_normalizes_lowercase_tickers_and_coalesces_fund_id_fallback() -> None:
    rows = pd.DataFrame(
        [
            # fund_id is None, ticker is lowercase 'spy'
            {
                "observation_date": "2026-09-14",
                "fund_id": None,
                "ticker": "spy",
                "estimated_flow_cny": 55.0,
                "flow_status": "validated",
                "size_value": 500_000.0,
            },
            # fund_id is lowercase 'qqq', ticker is None
            {
                "observation_date": "2026-09-14",
                "fund_id": "qqq",
                "ticker": None,
                "estimated_flow_cny": 45.0,
                "flow_status": "validated",
                "size_value": 400_000.0,
            },
        ]
    )
    metadata = pd.DataFrame(
        [
            {"ticker": "SPY", "category": "broad_equity"},
            {"fund_id": "QQQ", "category": "broad_equity"},
        ]
    )
    result = build_flow_snapshot(rows, metadata)
    spy_row = result[result["ticker"] == "SPY"].iloc[0]
    qqq_row = result[result["fund_id"] == "QQQ"].iloc[0]

    assert spy_row["flow_1d"] == pytest.approx(55.0)
    assert spy_row["valid_observations"] == 1
    assert spy_row["coverage_status"] == "validated"

    assert qqq_row["flow_1d"] == pytest.approx(45.0)
    assert qqq_row["valid_observations"] == 1
    assert qqq_row["coverage_status"] == "validated"
