from __future__ import annotations

import pandas as pd


def run_weekly_long_only_backtest(
    stock_signals: pd.DataFrame,
    stock_prices: pd.DataFrame,
    *,
    transaction_cost_bps: float = 10.0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if stock_signals.empty or stock_prices.empty:
        empty = pd.DataFrame()
        return empty, empty, empty

    signals = stock_signals.copy()
    signals["as_of_date"] = pd.to_datetime(signals["as_of_date"])
    signals["rebalance_date"] = signals["as_of_date"].dt.to_period("W-FRI").dt.end_time.dt.normalize()
    signals = (
        signals.sort_values(["ticker_normalized", "as_of_date"])
        .groupby(["rebalance_date", "ticker_normalized"], as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )

    prices = stock_prices.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["ticker_normalized", "date"])

    holdings_rows: list[dict[str, object]] = []
    returns_rows: list[dict[str, object]] = []
    diagnostics_rows: list[dict[str, object]] = []

    signal_dates = sorted(pd.to_datetime(signals["rebalance_date"]).unique())
    previous_names: set[str] = set()

    for index, signal_date in enumerate(signal_dates):
        next_signal_date = signal_dates[index + 1] if index + 1 < len(signal_dates) else None
        week_signals = signals.loc[
            (pd.to_datetime(signals["rebalance_date"]) == signal_date) & (signals["is_tradeable_signal"])
        ].copy()
        if week_signals.empty:
            returns_rows.append(
                {
                    "signal_date": signal_date,
                    "portfolio_return": 0.0,
                    "active_name_count": 0,
                }
            )
            diagnostics_rows.append(
                {
                    "signal_date": signal_date,
                    "turnover": 0.0,
                    "active_name_count": 0,
                }
            )
            previous_names = set()
            continue

        chosen = week_signals.sort_values(["stock_signal_score", "ticker_normalized"], ascending=[False, True]).copy()
        chosen["weight"] = 1.0 / len(chosen)
        current_names = set(chosen["ticker_normalized"])
        turnover = 1.0 if not previous_names else len(current_names.symmetric_difference(previous_names)) / max(
            len(current_names.union(previous_names)), 1
        )

        ticker_returns: list[float] = []
        for row in chosen.itertuples(index=False):
            ticker_prices = prices.loc[prices["ticker_normalized"] == row.ticker_normalized].copy()
            exec_mask = ticker_prices["date"] > signal_date
            if not exec_mask.any():
                continue
            entry_row = ticker_prices.loc[exec_mask].iloc[0]
            if next_signal_date is not None:
                exit_mask = ticker_prices["date"] > next_signal_date
                exit_row = ticker_prices.loc[exit_mask].iloc[0] if exit_mask.any() else ticker_prices.iloc[-1]
            else:
                exit_row = ticker_prices.iloc[-1]
            if entry_row["date"] >= exit_row["date"]:
                continue
            local_return = float(exit_row["adj_close"] / entry_row["adj_close"] - 1.0)
            base_currency_return = float(
                (exit_row.get("fx_to_usd", 1.0) * exit_row["adj_close"])
                / (entry_row.get("fx_to_usd", 1.0) * entry_row["adj_close"])
                - 1.0
            )
            net_return = base_currency_return - (transaction_cost_bps / 10000.0)
            ticker_returns.append(net_return)
            holdings_rows.append(
                {
                    "signal_date": signal_date,
                    "execution_date": entry_row["date"],
                    "exit_date": exit_row["date"],
                    "ticker_normalized": row.ticker_normalized,
                    "market": row.market,
                    "weight": row.weight,
                    "stock_signal_score": row.stock_signal_score,
                    "local_return": local_return,
                    "base_currency_return": base_currency_return,
                }
            )

        portfolio_return = sum(ticker_returns) / len(ticker_returns) if ticker_returns else 0.0
        returns_rows.append(
            {
                "signal_date": signal_date,
                "portfolio_return": portfolio_return,
                "active_name_count": len(chosen),
            }
        )
        diagnostics_rows.append(
            {
                "signal_date": signal_date,
                "turnover": turnover,
                "active_name_count": len(chosen),
            }
        )
        previous_names = current_names

    holdings = pd.DataFrame(holdings_rows)
    returns = pd.DataFrame(returns_rows)
    diagnostics = pd.DataFrame(diagnostics_rows)
    return holdings, returns, diagnostics
