from __future__ import annotations

import pandas as pd

from minerals_signal_data.backtest import run_weekly_long_only_backtest
from minerals_signal_data.market_data import (
    _resolve_tradingeconomics_api_key,
    attach_fx_to_stock_prices,
    fetch_fred_history,
    fetch_investing_history,
    fetch_tradingeconomics_history,
    to_yfinance_equity_symbol,
)
from minerals_signal_data.pipeline import MineralsSignalPipeline, build_signal_diagnostics, build_tracking_split, build_v2_source_coverage
from minerals_signal_data.signals import build_stock_weekly_signals, build_weekly_mineral_signals


def _fixture_price_universe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "normalized_mineral_id": "copper",
                "mineral_name": "Copper",
                "trackability_grade": "direct",
                "price_source_type": "yfinance_futures",
                "price_symbol_or_series_id": "HG=F",
                "price_currency": "USD",
                "price_unit": "lb",
                "publish_lag_assumption_days": 3,
                "is_active_for_v1": True,
            },
            {
                "normalized_mineral_id": "graphite",
                "mineral_name": "Graphite",
                "trackability_grade": "proxy",
                "price_source_type": "manual_proxy",
                "price_symbol_or_series_id": "graphite_proxy",
                "price_currency": "USD",
                "price_unit": "index",
                "publish_lag_assumption_days": 2,
                "is_active_for_v1": True,
            },
            {
                "normalized_mineral_id": "tantalum",
                "mineral_name": "Tantalum",
                "trackability_grade": "unsupported",
                "price_source_type": "manual_proxy",
                "price_symbol_or_series_id": None,
                "price_currency": None,
                "price_unit": None,
                "publish_lag_assumption_days": 5,
                "is_active_for_v1": False,
            },
        ]
    )


def _fixture_daily_mineral_prices() -> pd.DataFrame:
    dates = pd.date_range("2025-01-03", periods=16, freq="W-FRI")
    rows = []
    for offset, date in enumerate(dates):
        rows.append(
            {
                "date": date,
                "normalized_mineral_id": "copper",
                "mineral_name": "Copper",
                "price": 100 + offset,
            }
        )
        rows.append(
            {
                "date": date,
                "normalized_mineral_id": "graphite",
                "mineral_name": "Graphite",
                "price": 50 + offset,
            }
        )
        rows.append(
            {
                "date": date,
                "normalized_mineral_id": "tantalum",
                "mineral_name": "Tantalum",
                "price": 30 + offset,
            }
        )
    return pd.DataFrame(rows)


def _fixture_stock_mapping() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "mineral_name": "Copper",
                "normalized_mineral_id": "copper",
                "ticker_raw": "FCX",
                "ticker_normalized": "FCX",
                "market": "US",
                "exposure_purity": "Primary",
                "mapping_note": "Direct producer",
                "is_primary_exposure": True,
            },
            {
                "mineral_name": "Graphite",
                "normalized_mineral_id": "graphite",
                "ticker_raw": "2237.HK",
                "ticker_normalized": "2237.HK",
                "market": "HK",
                "exposure_purity": "Primary",
                "mapping_note": "Proxy exposure",
                "is_primary_exposure": True,
            },
            {
                "mineral_name": "Tantalum",
                "normalized_mineral_id": "tantalum",
                "ticker_raw": "000962.SZ",
                "ticker_normalized": "000962.SZ",
                "market": "CN_A",
                "exposure_purity": "Primary",
                "mapping_note": "Unsupported",
                "is_primary_exposure": True,
            },
        ]
    )


def test_weekly_mineral_signals_apply_lag_and_use_only_past_prices() -> None:
    signals = build_weekly_mineral_signals(_fixture_daily_mineral_prices(), _fixture_price_universe())
    latest_copper = signals.loc[signals["normalized_mineral_id"] == "copper"].iloc[-1]

    assert latest_copper["signal_state"] == "bullish"
    assert latest_copper["ret_4w"] > 0
    assert latest_copper["ret_12w"] > 0
    assert latest_copper["as_of_date"] > latest_copper["signal_date"]
    assert latest_copper["as_of_date"] == latest_copper["signal_date"] + pd.Timedelta(days=3)


def test_unsupported_minerals_do_not_create_stock_signals() -> None:
    mineral_signals = build_weekly_mineral_signals(_fixture_daily_mineral_prices(), _fixture_price_universe())
    stock_signals = build_stock_weekly_signals(mineral_signals, _fixture_stock_mapping())

    assert "000962.SZ" not in set(stock_signals["ticker_normalized"])
    assert set(stock_signals["ticker_normalized"]) == {"FCX", "2237.HK"}


def test_backtest_executes_on_next_available_session_without_future_leakage() -> None:
    mineral_signals = build_weekly_mineral_signals(_fixture_daily_mineral_prices(), _fixture_price_universe())
    stock_signals = build_stock_weekly_signals(mineral_signals, _fixture_stock_mapping())
    stock_signals = stock_signals.loc[pd.to_datetime(stock_signals["as_of_date"]) >= pd.Timestamp("2025-04-18")].copy()
    latest_rebalance_date = pd.Timestamp("2025-04-25")

    stock_prices = pd.DataFrame(
        [
            {"ticker_normalized": "FCX", "date": "2025-04-28", "adj_close": 10.0, "fx_to_usd": 1.0},
            {"ticker_normalized": "FCX", "date": "2025-05-05", "adj_close": 10.8, "fx_to_usd": 1.0},
            {"ticker_normalized": "2237.HK", "date": "2025-04-29", "adj_close": 8.0, "fx_to_usd": 0.128},
            {"ticker_normalized": "2237.HK", "date": "2025-05-06", "adj_close": 8.4, "fx_to_usd": 0.128},
        ]
    )
    holdings, returns, diagnostics = run_weekly_long_only_backtest(stock_signals, stock_prices, transaction_cost_bps=0)

    assert set(holdings["ticker_normalized"]) == {"FCX", "2237.HK"}
    assert set(pd.to_datetime(holdings["signal_date"])) == {latest_rebalance_date}
    assert (pd.to_datetime(holdings["execution_date"]) > latest_rebalance_date).all()
    assert holdings.loc[holdings["ticker_normalized"] == "2237.HK", "execution_date"].iloc[0] == pd.Timestamp("2025-04-29")
    assert holdings.loc[holdings["ticker_normalized"] == "FCX", "execution_date"].iloc[0] == pd.Timestamp("2025-04-28")
    assert returns["portfolio_return"].iloc[0] > 0
    assert diagnostics["active_name_count"].iloc[0] == 2


def test_signal_diagnostics_count_direct_and_proxy_usage() -> None:
    price_universe = _fixture_price_universe()
    mineral_signals = build_weekly_mineral_signals(_fixture_daily_mineral_prices(), price_universe)
    stock_mapping = _fixture_stock_mapping()
    stock_signals = build_stock_weekly_signals(mineral_signals, stock_mapping)
    diagnostics = build_signal_diagnostics(price_universe, stock_mapping, mineral_signals, stock_signals)

    metrics = dict(zip(diagnostics["metric"], diagnostics["value"]))
    assert metrics["supported_minerals"] == 2
    assert metrics["unsupported_minerals"] == 1
    assert metrics["direct_signal_rows"] > 0
    assert metrics["proxy_signal_rows"] > 0
    assert metrics["tradeable_stock_signal_rows"] > 0


def test_yfinance_symbol_conversion_handles_us_hk_and_a_share() -> None:
    assert to_yfinance_equity_symbol("FCX", "US") == "FCX"
    assert to_yfinance_equity_symbol("0815.HK", "HK") == "0815.HK"
    assert to_yfinance_equity_symbol("600362.SH", "CN_A") == "600362.SS"
    assert to_yfinance_equity_symbol("000630.SZ", "CN_A") == "000630.SZ"


def test_attach_fx_to_stock_prices_maps_hk_and_cn_a_to_usd_series() -> None:
    stock_prices = pd.DataFrame(
        [
            {"ticker_normalized": "FCX", "market": "US", "date": "2025-01-03", "adj_close": 10.0},
            {"ticker_normalized": "0815.HK", "market": "HK", "date": "2025-01-03", "adj_close": 8.0},
            {"ticker_normalized": "000630.SZ", "market": "CN_A", "date": "2025-01-03", "adj_close": 12.0},
        ]
    )
    fx_history = pd.DataFrame(
        [
            {"date": "2025-01-02", "market": "HK", "fx_to_usd": 1.0 / 7.8},
            {"date": "2025-01-02", "market": "CN_A", "fx_to_usd": 1.0 / 7.3},
        ]
    )

    attached = attach_fx_to_stock_prices(stock_prices, fx_history)

    assert attached.loc[attached["market"] == "US", "fx_to_usd"].iloc[0] == 1.0
    assert attached.loc[attached["market"] == "HK", "fx_to_usd"].iloc[0] == 1.0 / 7.8
    assert attached.loc[attached["market"] == "CN_A", "fx_to_usd"].iloc[0] == 1.0 / 7.3


def test_fetch_tradingeconomics_history_parses_market_rows(monkeypatch) -> None:
    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict[str, object]]:
            return [
                {"Symbol": "LC:COM", "Date": "02/01/2025", "Close": 165000.0},
                {"Symbol": "LC:COM", "Date": "03/01/2025", "Close": 166500.0},
            ]

    def fake_get(*args, **kwargs):
        return DummyResponse()

    monkeypatch.setattr("minerals_signal_data.market_data.requests.get", fake_get)
    frame = fetch_tradingeconomics_history("LC:COM", start_date="2025-01-01", end_date="2025-01-10", api_key="demo")

    assert list(frame.columns) == ["date", "price"]
    assert len(frame) == 2
    assert frame["price"].iloc[0] == 165000.0
    assert str(frame["date"].iloc[0].date()) == "2025-01-02"


def test_fetch_investing_history_parses_html_table(monkeypatch) -> None:
    html = """
    <html><body>
    <table>
      <thead><tr><th>Date</th><th>Price</th><th>Open</th></tr></thead>
      <tbody>
        <tr><td>Nov 01, 2024</td><td>70,500.00</td><td>70,500.00</td></tr>
        <tr><td>Oct 31, 2024</td><td>69,500.00</td><td>69,500.00</td></tr>
      </tbody>
    </table>
    </body></html>
    """

    class DummyResponse:
        text = html

        def raise_for_status(self) -> None:
            return None

    def fake_get(*args, **kwargs):
        return DummyResponse()

    monkeypatch.setattr("minerals_signal_data.market_data.requests.get", fake_get)
    frame = fetch_investing_history("https://example.com/history")

    assert list(frame.columns) == ["date", "price"]
    assert len(frame) == 2
    assert frame["price"].iloc[1] == 70500.0
    assert str(frame["date"].iloc[0].date()) == "2024-10-31"


def test_resolve_tradingeconomics_api_key_reads_dot_config(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / ".config"
    config_path.write_text("TRADING_ECONOMICS_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TRADING_ECONOMICS_API_KEY", raising=False)
    monkeypatch.delenv("TRADINGECONOMICS_API_KEY", raising=False)

    assert _resolve_tradingeconomics_api_key() == "test-key"


def test_build_v2_source_coverage_marks_fetched_and_unfetched_sources() -> None:
    price_universe = pd.DataFrame(
        [
            {"normalized_mineral_id": "copper", "is_active_for_v1": True},
            {"normalized_mineral_id": "lithium", "is_active_for_v1": True},
            {"normalized_mineral_id": "tantalum", "is_active_for_v1": False},
        ]
    )
    prices = pd.DataFrame(
        [
            {"normalized_mineral_id": "copper", "date": "2025-01-01", "price": 1.0},
            {"normalized_mineral_id": "copper", "date": "2025-01-02", "price": 2.0},
        ]
    )

    coverage = build_v2_source_coverage(price_universe, prices)
    statuses = dict(zip(coverage["normalized_mineral_id"], coverage["fetch_status"]))
    counts = dict(zip(coverage["normalized_mineral_id"], coverage["history_row_count"]))

    assert statuses["copper"] == "fetched"
    assert statuses["lithium"] == "available_but_unfetched"
    assert statuses["tantalum"] == "inactive"
    assert counts["copper"] == 2


def test_build_tracking_split_marks_easy_proxy_and_impractical_buckets() -> None:
    price_universe = pd.DataFrame(
        [
            {
                "normalized_mineral_id": "copper",
                "mineral_name": "Copper",
                "trackability_grade": "direct",
                "price_source_type": "yfinance_futures",
                "price_symbol_or_series_id": "HG=F",
                "is_active_for_v1": True,
            },
            {
                "normalized_mineral_id": "graphite",
                "mineral_name": "Graphite",
                "trackability_grade": "proxy",
                "price_source_type": "manual_proxy",
                "price_symbol_or_series_id": "graphite_proxy",
                "is_active_for_v1": False,
            },
            {
                "normalized_mineral_id": "dysprosium",
                "mineral_name": "Dysprosium",
                "trackability_grade": "unsupported",
                "price_source_type": "manual_proxy",
                "price_symbol_or_series_id": None,
                "is_active_for_v1": False,
            },
            {
                "normalized_mineral_id": "hafnium",
                "mineral_name": "Hafnium",
                "trackability_grade": "unsupported",
                "price_source_type": "manual_proxy",
                "price_symbol_or_series_id": None,
                "is_active_for_v1": False,
            },
        ]
    )
    split = build_tracking_split(price_universe)
    result = dict(zip(split["normalized_mineral_id"], split["tracking_split"]))
    live_status = dict(zip(split["normalized_mineral_id"], split["live_dashboard_status"]))

    assert result["copper"] == "already_tracked"
    assert result["graphite"] == "easy_next"
    assert result["dysprosium"] == "proxy_index"
    assert result["hafnium"] == "paywalled_or_impractical"
    assert live_status["copper"] == "shown_live"
    assert live_status["graphite"] == "unsupported"


def test_run_live_excludes_investing_sources_and_backtest_outputs(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_public_mineral_prices(price_universe: pd.DataFrame, **kwargs) -> pd.DataFrame:
        captured["source_types"] = set(price_universe["price_source_type"])
        captured["mineral_ids"] = set(price_universe["normalized_mineral_id"])
        return pd.DataFrame(
            [
                {"date": "2025-01-03", "normalized_mineral_id": "copper", "mineral_name": "Copper", "price": 4.1},
                {"date": "2025-01-03", "normalized_mineral_id": "graphite", "mineral_name": "Graphite", "price": 52.0},
            ]
        )

    def fake_fetch_public_stock_prices(stock_mapping: pd.DataFrame, **kwargs) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"ticker_normalized": row.ticker_normalized, "market": row.market, "date": "2025-01-03", "adj_close": 10.0}
                for row in stock_mapping.drop_duplicates(["ticker_normalized", "market"]).itertuples(index=False)
            ]
        )

    monkeypatch.setattr("minerals_signal_data.pipeline.fetch_public_mineral_prices", fake_fetch_public_mineral_prices)
    monkeypatch.setattr("minerals_signal_data.pipeline.fetch_public_stock_prices", fake_fetch_public_stock_prices)
    monkeypatch.setattr(
        "minerals_signal_data.pipeline.fetch_fx_to_usd_history",
        lambda **kwargs: pd.DataFrame(
            [
                {"date": "2025-01-03", "market": "HK", "fx_to_usd": 1.0 / 7.8},
                {"date": "2025-01-03", "market": "CN_A", "fx_to_usd": 1.0 / 7.3},
            ]
        ),
    )

    pipeline = MineralsSignalPipeline(tmp_path)
    outputs = pipeline.run_live(
        "data/reference/minerals_signal_data/critical_minerals.csv",
        stock_mapping_path="data/reference/minerals_signal_data/stock_mapping.csv",
        start_date="2025-01-01",
        run_label="test",
    )

    assert captured["source_types"] == {"yfinance_futures", "fred_series"}
    assert "cobalt" not in captured["mineral_ids"]
    assert "stock_signal_weekly" not in outputs
    assert "portfolio_returns_weekly" not in outputs

    universe = pd.read_csv(outputs["mineral_price_universe_live"])
    assert set(universe["normalized_mineral_id"]) == {"copper", "graphite"}
    assert "investing_html" not in set(universe["price_source_type"])

    mapping = pd.read_csv(outputs["stock_mapping_expanded_live"])
    assert "tungsten" in set(mapping["normalized_mineral_id"])


def test_fetch_fred_history_forward_fills_monthly_to_daily(monkeypatch) -> None:
    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "observations": [
                    {"date": "2024-01-01", "value": "100"},
                    {"date": "2024-02-01", "value": "."},  # missing value, skipped
                    {"date": "2024-03-01", "value": "110"},
                ]
            }

    monkeypatch.setattr(
        "minerals_signal_data.market_data.requests.get",
        lambda *args, **kwargs: _FakeResponse(),
    )

    frame = fetch_fred_history("PLEADUSDM", start_date="2024-01-01", end_date="2024-03-15", api_key="dummy")

    assert list(frame.columns) == ["date", "price"]
    # Monthly observations forward-filled onto business days (no >3-day gaps).
    assert frame["date"].diff().dropna().dt.days.max() <= 3
    assert frame["price"].iloc[0] == 100.0
    assert frame["price"].iloc[-1] == 110.0


def test_fetch_fred_history_without_key_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        "minerals_signal_data.market_data._resolve_fred_api_key", lambda: None
    )
    frame = fetch_fred_history("PLEADUSDM", start_date="2024-01-01")
    assert frame.empty
    assert list(frame.columns) == ["date", "price"]


def test_reference_price_universe_has_reliable_free_coverage() -> None:
    from minerals_signal_data.workbook import build_price_universe, load_critical_minerals

    universe = build_price_universe(
        load_critical_minerals("data/reference/minerals_signal_data/critical_minerals.csv")
    )
    reliable = universe.loc[
        universe["is_active_for_v1"]
        & universe["price_source_type"].isin(["yfinance_futures", "fred_series"])
    ]
    # yfinance + FRED sources do not depend on bot-block-prone HTML scraping; this is
    # the floor that must clear the weekly workflow's --min-mineral-coverage gate.
    assert len(reliable) >= 18
    # The previously-dead proxy minerals now carry a real instrument.
    for mineral_id in ("antimony", "graphite", "lithium"):
        row = universe.loc[universe["normalized_mineral_id"] == mineral_id].iloc[0]
        assert row["price_source_type"] == "yfinance_futures"
