from __future__ import annotations

import pandas as pd

from src.market_monitor.activity import build_etf_fund_activity
from src.market_monitor.sources import etf_shares


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
            },
            {
                "fund_id": "159919",
                "ticker": "159919",
                "exposure_id": "csi300",
                "index_id": "000300",
                "fund_name": "沪深300ETF嘉实",
                "venue": "SZ",
            },
        ]
    )


def test_sse_and_szse_adapters_keep_actual_observation_dates_and_units() -> None:
    sse = etf_shares._normalise_sse(
        pd.DataFrame(
            {
                "基金代码": [510300],
                "基金简称": ["沪深300ETF"],
                # AKShare has already converted the SSE endpoint's 万份 field
                # into actual shares before it reaches this adapter.
                "基金份额": [1_234_500.0],
                "统计日期": ["2026-08-21"],
            }
        ),
        retrieved_at_utc="2026-08-21T10:00:00+00:00",
    )
    szse = etf_shares._normalise_szse(
        pd.DataFrame(
            {
                "基金代码": [159919],
                "基金简称": ["沪深300ETF嘉实"],
                "基金份额": [2_000_000.0],
                "日期": ["2026-08-21"],
            }
        ),
        retrieved_at_utc="2026-08-21T10:00:00+00:00",
    )

    assert sse.loc[0, "fund_id"] == "510300"
    assert sse.loc[0, "shares_outstanding"] == 1_234_500.0
    assert sse.loc[0, "venue"] == "SH"
    assert sse.loc[0, "source_observed_date"] == "2026-08-21"
    assert szse.loc[0, "fund_id"] == "159919"
    assert szse.loc[0, "shares_outstanding"] == 2_000_000.0
    assert szse.loc[0, "venue"] == "SZ"


class _FakeAKShare:
    def __init__(self) -> None:
        self.sse_dates: list[str] = []
        self.szse_ranges: list[tuple[str, str]] = []

    def fund_etf_scale_sse(self, *, date: str) -> pd.DataFrame:
        self.sse_dates.append(date)
        return pd.DataFrame(
            {
                "基金代码": [510300],
                "基金简称": ["沪深300ETF"],
                "基金份额": [1_000_000.0],
                "统计日期": [f"{date[:4]}-{date[4:6]}-{date[6:]}"],
            }
        )

    def fund_scale_daily_szse(
        self, *, start_date: str, end_date: str, symbol: str
    ) -> pd.DataFrame:
        self.szse_ranges.append((start_date, end_date))
        return pd.DataFrame(
            {
                "日期": ["2026-08-20", "2026-08-21"],
                "基金代码": [159919, 159919],
                "基金简称": ["沪深300ETF嘉实", "沪深300ETF嘉实"],
                "基金份额": [2_000_000.0, 2_100_000.0],
            }
        )


def test_share_fetch_uses_known_etf_sessions_and_excludes_future_dates() -> None:
    fake = _FakeAKShare()
    shares, errors = etf_shares.fetch_etf_share_history(
        _metadata(),
        ["2026-08-20", "2026-08-21", "2026-08-22"],
        as_of_date="2026-08-21",
        ak_module=fake,
    )

    assert errors == []
    assert fake.sse_dates == ["20260820", "20260821"]
    assert len(fake.szse_ranges) == 1
    assert set(shares["fund_id"]) == {"510300", "159919"}
    assert set(shares["observation_date"]) == {"2026-08-20", "2026-08-21"}
    assert shares["observation_date"].max() == "2026-08-21"


def test_share_fetch_rejects_source_dates_outside_requested_sessions() -> None:
    class _FutureResponse:
        def fund_etf_scale_sse(self, *, date: str) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "基金代码": [510300],
                    "基金简称": ["沪深300ETF"],
                    "基金份额": [1_000_000.0],
                    "统计日期": ["2026-08-22"],
                }
            )

    shares, errors = etf_shares.fetch_etf_share_history(
        _metadata().iloc[[0]],
        ["2026-08-20", "2026-08-21"],
        as_of_date="2026-08-21",
        ak_module=_FutureResponse(),
    )

    assert shares.empty
    assert errors
    assert all(error.get("severity") == "optional" for error in errors)
    assert any("rejected" in error["error"] for error in errors)


def test_empty_share_response_is_reported_as_optional_notice() -> None:
    class _EmptyResponse:
        def fund_etf_scale_sse(self, *, date: str) -> pd.DataFrame:
            return pd.DataFrame()

    shares, errors = etf_shares.fetch_etf_share_history(
        _metadata().iloc[[0]],
        ["2026-08-21"],
        as_of_date="2026-08-21",
        ak_module=_EmptyResponse(),
    )

    assert shares.empty
    assert len(errors) == 1
    assert errors[0]["severity"] == "optional"
    assert "no accepted tracked observations" in errors[0]["error"]


def test_activity_metadata_stays_on_the_configured_china_hk_tab() -> None:
    from src.market_monitor.config import etf_activity_exposures
    from src.market_monitor.pipeline import _activity_metadata

    metadata = pd.concat(
        [
            _metadata(),
            pd.DataFrame(
                [
                    {
                        "fund_id": "510000",
                        "ticker": "510000",
                        "exposure_id": "dow",
                        "index_id": "dow",
                        "fund_name": "Dow wrapper",
                        "venue": "SH",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    scoped = _activity_metadata(metadata)

    assert set(scoped["exposure_id"]) <= etf_activity_exposures()
    assert "dow" not in set(scoped["exposure_id"])


def test_activity_validates_flow_only_with_two_share_observations_and_same_day_nav() -> None:
    shares = pd.DataFrame(
        {
            "observation_date": ["2026-08-20", "2026-08-21"],
            "fund_id": ["510300", "510300"],
            "venue": ["SH", "SH"],
            "shares_outstanding": [1_000.0, 1_100.0],
            "fund_name": ["沪深300ETF", "沪深300ETF"],
            "source": ["sse:fund_etf_scale_sse"] * 2,
            "source_observed_date": ["2026-08-20", "2026-08-21"],
            "retrieved_at_utc": ["2026-08-21T10:00:00+00:00"] * 2,
            "observation_type": ["published_share_count"] * 2,
        }
    )
    prices = pd.DataFrame(
        {
            "fund_id": ["510300", "510300"],
            "date": ["2026-08-20", "2026-08-21"],
            "close": [4.0, 4.0],
        }
    )
    premium_history = pd.DataFrame(
        {
            "fund_id": ["510300", "510300"],
            "date": ["2026-08-20", "2026-08-21"],
            "premium_pct": [0.0, 0.0],
            "basis": ["nav", "nav"],
        }
    )

    activity = build_etf_fund_activity(
        shares,
        _metadata().iloc[[0]],
        prices=prices,
        premium_history=premium_history,
    )

    first, second = activity.iloc[0], activity.iloc[1]
    assert first["flow_status"] == "insufficient_history"
    assert pd.isna(first["shares_change"])
    assert second["flow_status"] == "validated"
    assert second["shares_change"] == 100.0
    assert second["nav"] == 4.0
    assert second["estimated_flow_cny"] == 400.0
    assert second["flow_pct_aum"] == 400.0 / 4_400.0 * 100.0


def test_activity_keeps_share_change_when_nav_is_not_available() -> None:
    shares = pd.DataFrame(
        {
            "observation_date": ["2026-08-20", "2026-08-21"],
            "fund_id": ["510300", "510300"],
            "venue": ["SH", "SH"],
            "shares_outstanding": [1_000.0, 1_100.0],
            "fund_name": ["沪深300ETF", "沪深300ETF"],
        }
    )
    activity = build_etf_fund_activity(shares, _metadata().iloc[[0]])

    assert activity.iloc[1]["flow_status"] == "shares_only"
    assert pd.isna(activity.iloc[1]["estimated_flow_cny"])
