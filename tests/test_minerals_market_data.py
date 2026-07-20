from __future__ import annotations

import pandas as pd

import minerals_signal_data.market_data as market_data


def _mapping() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ticker_normalized": "002842.SZ", "market": "CN_A"},
            {"ticker_normalized": "3993.HK", "market": "HK"},
        ]
    )


def test_tencent_quote_parser_keeps_same_day_timestamp(monkeypatch) -> None:
    body = (
        'v_sz002842="51~翔鹭钨业~002842~28.84~32.04~32.69~0~0~0~28.84~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~20260720161454~-3.20~-9.99~32.99~28.84~";'
        'v_hk03993="100~洛阳钼业~03993~16.130~15.490~15.790~0~0~0~16.130~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~2026/07/20 16:08:31~0.640~4.13~16.310~15.200~";'
    )

    class Response:
        text = body

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(market_data.requests, "get", lambda *args, **kwargs: Response())

    result = market_data.fetch_tencent_quotes(_mapping())

    assert set(result["ticker_normalized"]) == {"002842.SZ", "3993.HK"}
    assert set(result["price_source"]) == {"tencent"}
    assert result.loc[result["ticker_normalized"] == "002842.SZ", "adj_close"].iloc[0] == 28.84
    assert result["source_timestamp"].notna().all()
    assert result["date"].dt.strftime("%Y-%m-%d").eq("2026-07-20").all()


def test_same_day_quotes_use_akshare_when_tencent_has_no_rows(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(market_data, "fetch_tencent_quotes", lambda mapping: market_data._empty_quote_frame())

    def fake_akshare(mapping: pd.DataFrame) -> pd.DataFrame:
        calls.append("akshare")
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-07-20"),
                    "adj_close": 28.84,
                    "ticker_normalized": "002842.SZ",
                    "market": "CN_A",
                    "price_source": "akshare_eastmoney",
                    "source_timestamp": pd.Timestamp("2026-07-20T08:00:00Z"),
                    "price_is_adjusted": False,
                }
            ]
        )

    monkeypatch.setattr(market_data, "fetch_akshare_quotes", fake_akshare)
    monkeypatch.setattr(
        market_data,
        "fetch_yfinance_latest_quote",
        lambda *args, **kwargs: market_data._empty_quote_frame(),
    )

    result = market_data.fetch_same_day_stock_quotes(
        pd.DataFrame([{"ticker_normalized": "002842.SZ", "market": "CN_A"}]),
        as_of_date="2026-07-20",
    )

    assert calls == ["akshare"]
    assert result.iloc[0]["price_source"] == "akshare_eastmoney"


def test_same_day_quotes_use_yfinance_when_tencent_and_akshare_fail(monkeypatch) -> None:
    monkeypatch.setattr(market_data, "fetch_tencent_quotes", lambda mapping: market_data._empty_quote_frame())
    monkeypatch.setattr(market_data, "fetch_akshare_quotes", lambda mapping: (_ for _ in ()).throw(RuntimeError("blocked")))
    monkeypatch.setattr(
        market_data,
        "fetch_yfinance_latest_quote",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-07-17"),
                    "adj_close": 27.5,
                    "ticker_normalized": "002842.SZ",
                    "market": "CN_A",
                    "price_source": "yfinance",
                    "source_timestamp": pd.NaT,
                    "price_is_adjusted": True,
                }
            ]
        ),
    )

    result = market_data.fetch_same_day_stock_quotes(
        pd.DataFrame([{"ticker_normalized": "002842.SZ", "market": "CN_A"}]),
        as_of_date="2026-07-20",
    )

    assert result.iloc[0]["price_source"] == "yfinance"
    assert result.iloc[0]["adj_close"] == 27.5


def test_public_stock_prices_replaces_yahoo_latest_with_same_day_quote(monkeypatch) -> None:
    def fake_history(*args, **kwargs) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-07-17"), "price": 27.5},
            ]
        )

    monkeypatch.setattr(market_data, "fetch_yfinance_history", fake_history)
    monkeypatch.setattr(
        market_data,
        "fetch_same_day_stock_quotes",
        lambda mapping: pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-07-20"),
                    "adj_close": 28.84,
                    "ticker_normalized": "002842.SZ",
                    "market": "CN_A",
                    "price_source": "tencent",
                    "source_timestamp": pd.Timestamp("2026-07-20T08:14:54Z"),
                    "price_is_adjusted": False,
                }
            ]
        ),
    )

    result = market_data.fetch_public_stock_prices(
        pd.DataFrame([{"ticker_normalized": "002842.SZ", "market": "CN_A"}]),
        start_date="2026-01-01",
    )

    assert set(result["date"]) == {pd.Timestamp("2026-07-17"), pd.Timestamp("2026-07-20")}
    latest = result.loc[result["date"] == pd.Timestamp("2026-07-20")].iloc[0]
    assert latest["adj_close"] == 28.84
    assert latest["price_source"] == "tencent"


def test_akshare_row_normalization_handles_cn_and_hk_codes() -> None:
    frame = pd.DataFrame(
        [
            {"代码": "002842", "最新价": 28.84},
            {"代码": "3993", "最新价": 16.13},
        ]
    )
    retrieved_at = pd.Timestamp("2026-07-20T08:00:00Z")

    a_rows = market_data._akshare_quote_rows(
        frame.iloc[[0]], market="CN_A", requested={"002842.SZ"}, retrieved_at=retrieved_at
    )
    hk_rows = market_data._akshare_quote_rows(
        frame.iloc[[1]], market="HK", requested={"03993.HK"}, retrieved_at=retrieved_at
    )

    assert a_rows[0]["ticker_normalized"] == "002842.SZ"
    assert hk_rows[0]["ticker_normalized"] == "03993.HK"
