from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from minerals_signal_data.backtest import run_weekly_long_only_backtest
from minerals_signal_data.market_data import (
    attach_fx_to_stock_prices,
    fetch_fx_to_usd_history,
    fetch_public_mineral_prices,
    fetch_public_stock_prices,
)
from minerals_signal_data.signals import build_stock_weekly_signals, build_weekly_mineral_signals
from minerals_signal_data.storage import MineralsSignalStorage
from minerals_signal_data.workbook import build_price_universe, load_critical_minerals, load_expanded_stock_mapping


def _resolve_stock_mapping_path(
    workbook_path: str | Path, stock_mapping_path: str | Path | None
) -> str | Path:
    """Resolve the stock-mapping source.

    For .xlsx inputs the mapping lives on a sheet of the same file, so the
    workbook path is reused. For CSV inputs the mapping is a separate file;
    if not given explicitly, default to a sibling ``stock_mapping.csv``.
    """
    if stock_mapping_path is not None:
        return stock_mapping_path
    path = Path(workbook_path)
    if path.suffix.lower() == ".csv":
        return path.with_name("stock_mapping.csv")
    return workbook_path


class MineralsSignalPipeline:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.storage = MineralsSignalStorage(self.base_dir)

    def load_workbook(
        self,
        workbook_path: str | Path,
        *,
        stock_mapping_path: str | Path | None = None,
        run_label: str = "latest",
    ) -> dict[str, Path]:
        minerals = load_critical_minerals(workbook_path)
        stock_mapping = load_expanded_stock_mapping(
            _resolve_stock_mapping_path(workbook_path, stock_mapping_path)
        )
        price_universe = build_price_universe(minerals)
        tracking_split = build_tracking_split(price_universe)
        return {
            "critical_minerals": self.storage.write_dataset("critical_minerals", minerals, run_label=run_label),
            "stock_mapping_expanded": self.storage.write_dataset(
                "stock_mapping_expanded", stock_mapping, run_label=run_label
            ),
            "mineral_price_universe": self.storage.write_dataset(
                "mineral_price_universe", price_universe, run_label=run_label
            ),
            "mineral_tracking_split": self.storage.write_dataset(
                "mineral_tracking_split", tracking_split, run_label=run_label
            ),
        }

    def fetch_price_history(
        self,
        workbook_path: str | Path,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        manual_prices_path: str | Path | None = None,
        run_label: str = "latest",
    ) -> dict[str, Path]:
        minerals = load_critical_minerals(workbook_path)
        price_universe = build_price_universe(minerals)
        prices = fetch_public_mineral_prices(
            price_universe,
            start_date=start_date,
            end_date=end_date,
            manual_prices_path=manual_prices_path,
        )
        return {
            "mineral_price_series_daily": self.storage.write_dataset(
                "mineral_price_series_daily", prices, run_label=run_label
            )
        }

    def derive_signals(
        self,
        workbook_path: str | Path,
        mineral_prices_path: str | Path,
        *,
        stock_mapping_path: str | Path | None = None,
        run_label: str = "latest",
    ) -> dict[str, Path]:
        minerals = load_critical_minerals(workbook_path)
        price_universe = build_price_universe(minerals)
        stock_mapping = load_expanded_stock_mapping(
            _resolve_stock_mapping_path(workbook_path, stock_mapping_path)
        )
        mineral_prices = pd.read_csv(mineral_prices_path)
        mineral_signals = build_weekly_mineral_signals(mineral_prices, price_universe)
        stock_signals = build_stock_weekly_signals(mineral_signals, stock_mapping)
        diagnostics = build_signal_diagnostics(price_universe, stock_mapping, mineral_signals, stock_signals)
        return {
            "mineral_signal_weekly": self.storage.write_dataset(
                "mineral_signal_weekly", mineral_signals, run_label=run_label
            ),
            "stock_signal_weekly": self.storage.write_dataset("stock_signal_weekly", stock_signals, run_label=run_label),
            "signal_diagnostics_weekly": self.storage.write_dataset(
                "signal_diagnostics_weekly", diagnostics, run_label=run_label
            ),
        }

    def backtest(
        self,
        stock_signals_path: str | Path,
        stock_prices_path: str | Path,
        *,
        run_label: str = "latest",
    ) -> dict[str, Path]:
        stock_signals = pd.read_csv(stock_signals_path)
        stock_prices = pd.read_csv(stock_prices_path)
        holdings, returns, diagnostics = run_weekly_long_only_backtest(stock_signals, stock_prices)
        return {
            "portfolio_holdings_weekly": self.storage.write_dataset(
                "portfolio_holdings_weekly", holdings, run_label=run_label
            ),
            "portfolio_returns_weekly": self.storage.write_dataset(
                "portfolio_returns_weekly", returns, run_label=run_label
            ),
            "backtest_diagnostics_weekly": self.storage.write_dataset(
                "backtest_diagnostics_weekly", diagnostics, run_label=run_label
            ),
        }

    def validate(
        self,
        workbook_path: str | Path,
        *,
        stock_mapping_path: str | Path | None = None,
    ) -> dict[str, int]:
        minerals = load_critical_minerals(workbook_path)
        price_universe = build_price_universe(minerals)
        stock_mapping = load_expanded_stock_mapping(
            _resolve_stock_mapping_path(workbook_path, stock_mapping_path)
        )
        return {
            "minerals": len(minerals),
            "supported_minerals": int(price_universe["is_active_for_v1"].sum()),
            "direct_minerals": int((price_universe["trackability_grade"] == "direct").sum()),
            "proxy_minerals": int((price_universe["trackability_grade"] == "proxy").sum()),
            "stock_mappings": len(stock_mapping),
        }

    def run_v1(
        self,
        workbook_path: str | Path,
        *,
        stock_mapping_path: str | Path | None = None,
        start_date: str = "2022-01-01",
        end_date: str | None = None,
        run_label: str = "latest",
    ) -> dict[str, Path]:
        minerals = load_critical_minerals(workbook_path)
        price_universe = build_price_universe(minerals)
        stock_mapping = load_expanded_stock_mapping(
            _resolve_stock_mapping_path(workbook_path, stock_mapping_path)
        )

        live_price_universe = price_universe.loc[
            (price_universe["is_active_for_v1"]) & (price_universe["price_source_type"] == "yfinance_futures")
        ].copy()
        live_stock_mapping = stock_mapping.loc[
            stock_mapping["normalized_mineral_id"].isin(live_price_universe["normalized_mineral_id"])
        ].copy()

        mineral_prices = fetch_public_mineral_prices(
            live_price_universe,
            start_date=start_date,
            end_date=end_date,
        )
        mineral_signals = build_weekly_mineral_signals(mineral_prices, live_price_universe)
        stock_signals = build_stock_weekly_signals(mineral_signals, live_stock_mapping)
        stock_prices = fetch_public_stock_prices(
            live_stock_mapping.loc[
                live_stock_mapping["ticker_normalized"].isin(stock_signals["ticker_normalized"].unique())
            ],
            start_date=start_date,
            end_date=end_date,
        )
        fx_history = fetch_fx_to_usd_history(start_date=start_date, end_date=end_date)
        stock_prices = attach_fx_to_stock_prices(stock_prices, fx_history)

        holdings, returns, backtest_diagnostics = run_weekly_long_only_backtest(stock_signals, stock_prices)
        signal_diagnostics = build_signal_diagnostics(live_price_universe, live_stock_mapping, mineral_signals, stock_signals)
        summary = build_backtest_summary(
            live_price_universe=live_price_universe,
            live_stock_mapping=live_stock_mapping,
            mineral_prices=mineral_prices,
            mineral_signals=mineral_signals,
            stock_prices=stock_prices,
            stock_signals=stock_signals,
            holdings=holdings,
            returns=returns,
        )

        outputs = {
            "mineral_price_universe_live": self.storage.write_dataset(
                "mineral_price_universe_live", live_price_universe, run_label=run_label
            ),
            "stock_mapping_expanded_live": self.storage.write_dataset(
                "stock_mapping_expanded_live", live_stock_mapping, run_label=run_label
            ),
            "mineral_price_series_daily": self.storage.write_dataset(
                "mineral_price_series_daily", mineral_prices, run_label=run_label
            ),
            "mineral_signal_weekly": self.storage.write_dataset(
                "mineral_signal_weekly", mineral_signals, run_label=run_label
            ),
            "stock_price_series_daily": self.storage.write_dataset(
                "stock_price_series_daily", stock_prices, run_label=run_label
            ),
            "stock_signal_weekly": self.storage.write_dataset(
                "stock_signal_weekly", stock_signals, run_label=run_label
            ),
            "portfolio_holdings_weekly": self.storage.write_dataset(
                "portfolio_holdings_weekly", holdings, run_label=run_label
            ),
            "portfolio_returns_weekly": self.storage.write_dataset(
                "portfolio_returns_weekly", returns, run_label=run_label
            ),
            "signal_diagnostics_weekly": self.storage.write_dataset(
                "signal_diagnostics_weekly", signal_diagnostics, run_label=run_label
            ),
            "backtest_diagnostics_weekly": self.storage.write_dataset(
                "backtest_diagnostics_weekly", backtest_diagnostics, run_label=run_label
            ),
            "backtest_summary": self.storage.write_dataset(
                "backtest_summary", summary, run_label=run_label
            ),
        }
        outputs.update(self._write_backtest_charts(returns=returns, holdings=holdings, run_label=run_label))
        return outputs

    def run_v2(
        self,
        workbook_path: str | Path,
        *,
        stock_mapping_path: str | Path | None = None,
        start_date: str = "2022-01-01",
        end_date: str | None = None,
        run_label: str = "latest",
        min_mineral_coverage: int = 0,
    ) -> dict[str, Path]:
        minerals = load_critical_minerals(workbook_path)
        price_universe = build_price_universe(minerals)
        stock_mapping = load_expanded_stock_mapping(
            _resolve_stock_mapping_path(workbook_path, stock_mapping_path)
        )

        live_price_universe = price_universe.loc[
            price_universe["is_active_for_v1"]
            & price_universe["price_source_type"].isin(
                ["yfinance_futures", "tradingeconomics_api", "investing_html", "fred_series"]
            )
        ].copy()
        live_stock_mapping = stock_mapping.loc[
            stock_mapping["normalized_mineral_id"].isin(live_price_universe["normalized_mineral_id"])
        ].copy()

        mineral_prices = fetch_public_mineral_prices(
            live_price_universe,
            start_date=start_date,
            end_date=end_date,
        )
        fetched_mineral_ids = set(mineral_prices["normalized_mineral_id"].unique()) if not mineral_prices.empty else set()
        if min_mineral_coverage > 0 and len(fetched_mineral_ids) < min_mineral_coverage:
            raise RuntimeError(
                "V2 mineral price coverage below threshold: fetched "
                f"{len(fetched_mineral_ids)} mineral(s), require >= {min_mineral_coverage}. "
                "Upstream price sources may be blocked or unavailable; refusing to write a "
                "degraded run."
            )
        fetched_price_universe = live_price_universe.loc[
            live_price_universe["normalized_mineral_id"].isin(fetched_mineral_ids)
        ].copy()
        fetched_stock_mapping = live_stock_mapping.loc[
            live_stock_mapping["normalized_mineral_id"].isin(fetched_mineral_ids)
        ].copy()

        mineral_signals = build_weekly_mineral_signals(mineral_prices, fetched_price_universe)
        stock_signals = build_stock_weekly_signals(mineral_signals, fetched_stock_mapping)
        stock_prices = fetch_public_stock_prices(
            fetched_stock_mapping.loc[
                fetched_stock_mapping["ticker_normalized"].isin(stock_signals["ticker_normalized"].unique())
            ],
            start_date=start_date,
            end_date=end_date,
        )
        fx_history = fetch_fx_to_usd_history(start_date=start_date, end_date=end_date)
        stock_prices = attach_fx_to_stock_prices(stock_prices, fx_history)
        holdings, returns, backtest_diagnostics = run_weekly_long_only_backtest(stock_signals, stock_prices)
        signal_diagnostics = build_signal_diagnostics(
            fetched_price_universe,
            fetched_stock_mapping,
            mineral_signals,
            stock_signals,
        )
        coverage = build_v2_source_coverage(price_universe, mineral_prices)
        tracking_split = build_tracking_split(price_universe)
        summary = build_backtest_summary(
            live_price_universe=fetched_price_universe,
            live_stock_mapping=fetched_stock_mapping,
            mineral_prices=mineral_prices,
            mineral_signals=mineral_signals,
            stock_prices=stock_prices,
            stock_signals=stock_signals,
            holdings=holdings,
            returns=returns,
        )

        outputs = {
            "v2_source_coverage": self.storage.write_dataset("v2_source_coverage", coverage, run_label=run_label),
            "mineral_tracking_split": self.storage.write_dataset(
                "mineral_tracking_split", tracking_split, run_label=run_label
            ),
            "mineral_price_universe_live": self.storage.write_dataset(
                "mineral_price_universe_live", fetched_price_universe, run_label=run_label
            ),
            "stock_mapping_expanded_live": self.storage.write_dataset(
                "stock_mapping_expanded_live", fetched_stock_mapping, run_label=run_label
            ),
            "mineral_price_series_daily": self.storage.write_dataset(
                "mineral_price_series_daily", mineral_prices, run_label=run_label
            ),
            "mineral_signal_weekly": self.storage.write_dataset(
                "mineral_signal_weekly", mineral_signals, run_label=run_label
            ),
            "stock_price_series_daily": self.storage.write_dataset(
                "stock_price_series_daily", stock_prices, run_label=run_label
            ),
            "stock_signal_weekly": self.storage.write_dataset(
                "stock_signal_weekly", stock_signals, run_label=run_label
            ),
            "portfolio_holdings_weekly": self.storage.write_dataset(
                "portfolio_holdings_weekly", holdings, run_label=run_label
            ),
            "portfolio_returns_weekly": self.storage.write_dataset(
                "portfolio_returns_weekly", returns, run_label=run_label
            ),
            "signal_diagnostics_weekly": self.storage.write_dataset(
                "signal_diagnostics_weekly", signal_diagnostics, run_label=run_label
            ),
            "backtest_diagnostics_weekly": self.storage.write_dataset(
                "backtest_diagnostics_weekly", backtest_diagnostics, run_label=run_label
            ),
            "backtest_summary": self.storage.write_dataset(
                "backtest_summary", summary, run_label=run_label
            ),
        }
        outputs.update(self._write_backtest_charts(returns=returns, holdings=holdings, run_label=run_label))
        return outputs

    def run_live(
        self,
        workbook_path: str | Path,
        *,
        stock_mapping_path: str | Path | None = None,
        start_date: str = "2022-01-01",
        end_date: str | None = None,
        run_label: str = "latest",
    ) -> dict[str, Path]:
        minerals = load_critical_minerals(workbook_path)
        price_universe = build_price_universe(minerals)
        stock_mapping = load_expanded_stock_mapping(
            _resolve_stock_mapping_path(workbook_path, stock_mapping_path)
        )

        live_price_universe = price_universe.loc[
            price_universe["is_active_for_v1"]
            & price_universe["price_source_type"].isin(["yfinance_futures", "fred_series"])
        ].copy()
        live_stock_mapping = stock_mapping.loc[
            stock_mapping["normalized_mineral_id"].isin(live_price_universe["normalized_mineral_id"])
        ].copy()

        mineral_prices = fetch_public_mineral_prices(
            live_price_universe,
            start_date=start_date,
            end_date=end_date,
        )
        fetched_mineral_ids = set(mineral_prices["normalized_mineral_id"].unique()) if not mineral_prices.empty else set()
        fetched_price_universe = live_price_universe.loc[
            live_price_universe["normalized_mineral_id"].isin(fetched_mineral_ids)
        ].copy()
        fetched_stock_mapping = live_stock_mapping.loc[
            live_stock_mapping["normalized_mineral_id"].isin(fetched_mineral_ids)
        ].copy()

        stock_prices = fetch_public_stock_prices(
            fetched_stock_mapping,
            start_date=start_date,
            end_date=end_date,
        )
        fx_history = fetch_fx_to_usd_history(start_date=start_date, end_date=end_date)
        stock_prices = attach_fx_to_stock_prices(stock_prices, fx_history)
        coverage = build_v2_source_coverage(price_universe, mineral_prices)
        tracking_split = build_tracking_split(price_universe)

        return {
            "v2_source_coverage": self.storage.write_dataset("v2_source_coverage", coverage, run_label=run_label),
            "mineral_tracking_split": self.storage.write_dataset(
                "mineral_tracking_split", tracking_split, run_label=run_label
            ),
            "mineral_price_universe_live": self.storage.write_dataset(
                "mineral_price_universe_live", fetched_price_universe, run_label=run_label
            ),
            "stock_mapping_expanded_live": self.storage.write_dataset(
                "stock_mapping_expanded_live", fetched_stock_mapping, run_label=run_label
            ),
            "mineral_price_series_daily": self.storage.write_dataset(
                "mineral_price_series_daily", mineral_prices, run_label=run_label
            ),
            "stock_price_series_daily": self.storage.write_dataset(
                "stock_price_series_daily", stock_prices, run_label=run_label
            ),
        }

    def _write_backtest_charts(self, *, returns: pd.DataFrame, holdings: pd.DataFrame, run_label: str) -> dict[str, Path]:
        outputs: dict[str, Path] = {}
        if returns.empty:
            return outputs

        chart_path = self.storage.output_path(
            "backtest_charts",
            run_label=run_label,
            file_name="portfolio_cumulative_return.png",
        )
        plot_portfolio_returns(returns, chart_path)
        outputs["portfolio_cumulative_return_chart"] = chart_path

        if not holdings.empty:
            market_chart = self.storage.output_path(
                "backtest_charts",
                run_label=run_label,
                file_name="holdings_by_market.png",
            )
            plot_holdings_by_market(holdings, market_chart)
            outputs["holdings_by_market_chart"] = market_chart
        return outputs


def build_signal_diagnostics(
    price_universe: pd.DataFrame,
    stock_mapping: pd.DataFrame,
    mineral_signals: pd.DataFrame,
    stock_signals: pd.DataFrame,
) -> pd.DataFrame:
    diagnostics = [
        {"metric": "supported_minerals", "value": int(price_universe["is_active_for_v1"].sum())},
        {"metric": "unsupported_minerals", "value": int((price_universe["trackability_grade"] == "unsupported").sum())},
        {"metric": "direct_signal_rows", "value": int((mineral_signals.get("signal_quality") == "direct").sum())},
        {"metric": "proxy_signal_rows", "value": int((mineral_signals.get("signal_quality") == "proxy").sum())},
        {"metric": "tradeable_stock_signal_rows", "value": int(stock_signals.get("is_tradeable_signal", pd.Series(dtype=bool)).sum())},
        {"metric": "us_stock_rows", "value": int((stock_mapping["market"] == "US").sum())},
        {"metric": "hk_stock_rows", "value": int((stock_mapping["market"] == "HK").sum())},
        {"metric": "cn_a_stock_rows", "value": int((stock_mapping["market"] == "CN_A").sum())},
    ]
    return pd.DataFrame(diagnostics)


def build_v2_source_coverage(price_universe: pd.DataFrame, mineral_prices: pd.DataFrame) -> pd.DataFrame:
    fetched_ids = set(mineral_prices["normalized_mineral_id"].unique()) if not mineral_prices.empty else set()
    coverage = price_universe.copy()
    coverage["has_fetched_history"] = coverage["normalized_mineral_id"].isin(fetched_ids)
    coverage["history_row_count"] = coverage["normalized_mineral_id"].map(
        mineral_prices.groupby("normalized_mineral_id").size().to_dict() if not mineral_prices.empty else {}
    ).fillna(0).astype(int)
    coverage["fetch_status"] = coverage.apply(
        lambda row: "fetched"
        if row["has_fetched_history"]
        else ("available_but_unfetched" if row["is_active_for_v1"] else "inactive"),
        axis=1,
    )
    return coverage.sort_values(["has_fetched_history", "normalized_mineral_id"], ascending=[False, True]).reset_index(drop=True)


def build_tracking_split(price_universe: pd.DataFrame) -> pd.DataFrame:
    easy_next = {
        "antimony",
        "graphite",
        "manganese",
        "silicon",
        "vanadium",
    }
    proxy_bucket = {
        "cerium",
        "chromium",
        "dysprosium",
        "europium",
        "fluorspar",
        "gadolinium",
        "lanthanum",
        "magnesium",
        "metallurgical_coal",
        "niobium",
        "phosphate_rock",
        "potash",
        "praseodymium",
        "samarium",
        "scandium",
        "tellurium",
        "terbium",
        "tungsten",
        "yttrium",
    }
    rows: list[dict[str, object]] = []
    for row in price_universe.itertuples(index=False):
        if bool(row.is_active_for_v1):
            split = "already_tracked" if row.price_source_type != "manual_proxy" else "proxy_index"
        elif row.normalized_mineral_id in easy_next:
            split = "easy_next"
        elif row.normalized_mineral_id in proxy_bucket:
            split = "proxy_index"
        else:
            split = "paywalled_or_impractical"
        rows.append(
            {
                "normalized_mineral_id": row.normalized_mineral_id,
                "mineral_name": row.mineral_name,
                "tracking_split": split,
                "live_dashboard_status": (
                    "shown_live"
                    if bool(row.is_active_for_v1) and row.price_source_type in {"yfinance_futures", "fred_series"}
                    else ("research_only" if bool(row.is_active_for_v1) else "unsupported")
                ),
                "trackability_grade": row.trackability_grade,
                "price_source_type": row.price_source_type,
                "price_symbol_or_series_id": row.price_symbol_or_series_id,
                "is_active_for_v1": row.is_active_for_v1,
            }
        )
    return pd.DataFrame(rows).sort_values(["tracking_split", "normalized_mineral_id"]).reset_index(drop=True)


def build_backtest_summary(
    *,
    live_price_universe: pd.DataFrame,
    live_stock_mapping: pd.DataFrame,
    mineral_prices: pd.DataFrame,
    mineral_signals: pd.DataFrame,
    stock_prices: pd.DataFrame,
    stock_signals: pd.DataFrame,
    holdings: pd.DataFrame,
    returns: pd.DataFrame,
) -> pd.DataFrame:
    portfolio_returns = returns["portfolio_return"] if not returns.empty else pd.Series(dtype=float)
    cumulative_return = (1.0 + portfolio_returns).prod() - 1.0 if not portfolio_returns.empty else 0.0
    hit_rate = (portfolio_returns > 0).mean() if not portfolio_returns.empty else 0.0
    summary = [
        {"metric": "live_minerals", "value": int(live_price_universe["normalized_mineral_id"].nunique())},
        {"metric": "live_stock_links", "value": int(len(live_stock_mapping))},
        {"metric": "fetched_mineral_price_rows", "value": int(len(mineral_prices))},
        {"metric": "fetched_stock_price_rows", "value": int(len(stock_prices))},
        {"metric": "mineral_signal_rows", "value": int(len(mineral_signals))},
        {"metric": "stock_signal_rows", "value": int(len(stock_signals))},
        {"metric": "holding_rows", "value": int(len(holdings))},
        {"metric": "weekly_rebalances", "value": int(len(returns))},
        {"metric": "cumulative_return", "value": float(cumulative_return)},
        {"metric": "average_weekly_return", "value": float(portfolio_returns.mean() if not portfolio_returns.empty else 0.0)},
        {"metric": "weekly_volatility", "value": float(portfolio_returns.std(ddof=0) if not portfolio_returns.empty else 0.0)},
        {"metric": "positive_week_ratio", "value": float(hit_rate)},
        {"metric": "average_active_names", "value": float(returns["active_name_count"].mean() if not returns.empty else 0.0)},
    ]
    return pd.DataFrame(summary)


def plot_portfolio_returns(returns: pd.DataFrame, output_path: Path) -> None:
    frame = returns.copy()
    frame["signal_date"] = pd.to_datetime(frame["signal_date"])
    frame["cumulative_return"] = (1.0 + frame["portfolio_return"]).cumprod() - 1.0
    plt.figure(figsize=(10, 5))
    plt.plot(frame["signal_date"], frame["cumulative_return"], color="#154c79", linewidth=2)
    plt.title("Mineral-Linked Stock Signals V1: Cumulative Return")
    plt.xlabel("Rebalance Week")
    plt.ylabel("Cumulative Return")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=160)
    plt.close()


def plot_holdings_by_market(holdings: pd.DataFrame, output_path: Path) -> None:
    frame = holdings.copy()
    frame["signal_date"] = pd.to_datetime(frame["signal_date"])
    grouped = (
        frame.groupby(["signal_date", "market"])["ticker_normalized"]
        .nunique()
        .unstack(fill_value=0)
        .sort_index()
    )
    plt.figure(figsize=(10, 5))
    grouped.plot.area(ax=plt.gca(), alpha=0.85)
    plt.title("Active Holdings by Market")
    plt.xlabel("Rebalance Week")
    plt.ylabel("Count of Holdings")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=160)
    plt.close()
