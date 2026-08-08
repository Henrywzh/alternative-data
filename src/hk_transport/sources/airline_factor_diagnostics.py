"""Free-data factor proxies for airline pair construction diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from math import log
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR


PAIR_RISK_PATH = NORMALIZED_DIR / "airline_pair_risk_metrics.csv"
MARKET_RISK_PATH = NORMALIZED_DIR / "airline_market_risk_metrics.csv"
BRIDGE_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_factor_diagnostics.csv"

OUTPUT_COLUMNS = [
    "dataset_id", "pair_id", "asset_a", "company_a", "market_a", "asset_b", "company_b", "market_b",
    "same_market", "snapshot_date", "beta_benchmark_a", "beta_benchmark_b", "beta_gap_a_minus_b",
    "log_size_gap_a_minus_b", "value_revenue_multiple_a", "value_revenue_multiple_b",
    "value_revenue_multiple_gap_a_minus_b", "momentum_3m_a_pct", "momentum_3m_b_pct",
    "momentum_3m_gap_a_minus_b_pct", "momentum_1y_a_pct", "momentum_1y_b_pct",
    "momentum_1y_gap_a_minus_b_pct", "volatility_a_pct", "volatility_b_pct",
    "volatility_gap_a_minus_b_pct", "max_drawdown_a_pct", "max_drawdown_b_pct",
    "max_drawdown_gap_a_minus_b_pct", "mechanical_beta_a_to_b", "mechanical_beta_b_to_a",
    "borrow_data_available_a", "borrow_data_available_b", "source_quality", "source_note", "retrieved_at",
]


def _row(frame: pd.DataFrame, company: str) -> pd.Series:
    rows = frame.loc[frame["company"].eq(company)] if not frame.empty else pd.DataFrame()
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _number(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _gap(a: object, b: object) -> float | None:
    first, second = _number(a), _number(b)
    return first - second if first is not None and second is not None else None


def _log_gap(a: object, b: object) -> float | None:
    first, second = _number(a), _number(b)
    if first is None or second is None or first <= 0 or second <= 0:
        return None
    return log(first) - log(second)


def build_airline_pair_factor_diagnostics(
    *,
    pair_risk: pd.DataFrame | None = None,
    market_risk: pd.DataFrame | None = None,
    bridge: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    pair_risk = pair_risk if pair_risk is not None else pd.read_csv(PAIR_RISK_PATH)
    market_risk = market_risk if market_risk is not None else pd.read_csv(MARKET_RISK_PATH)
    bridge = bridge if bridge is not None else pd.read_csv(BRIDGE_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    for _, pair in pair_risk.iterrows():
        a = _row(market_risk, str(pair["company_a"]))
        b = _row(market_risk, str(pair["company_b"]))
        bridge_a = _row(bridge, str(pair["company_a"]))
        bridge_b = _row(bridge, str(pair["company_b"]))
        pair_id = "__".join(sorted([str(pair["asset_a"]), str(pair["asset_b"])]))
        rows.append({
            "dataset_id": "airline_pair_factor_diagnostics",
            "pair_id": pair_id,
            "asset_a": pair["asset_a"], "company_a": pair["company_a"], "market_a": pair["market_a"],
            "asset_b": pair["asset_b"], "company_b": pair["company_b"], "market_b": pair["market_b"],
            "same_market": pair["same_market"], "snapshot_date": pair["snapshot_date"],
            "beta_benchmark_a": a.get("beta_to_benchmark"),
            "beta_benchmark_b": b.get("beta_to_benchmark"),
            "beta_gap_a_minus_b": _gap(a.get("beta_to_benchmark"), b.get("beta_to_benchmark")),
            "log_size_gap_a_minus_b": _log_gap(a.get("market_cap_usd_mn"), b.get("market_cap_usd_mn")),
            "value_revenue_multiple_a": bridge_a.get("market_cap_to_consensus_revenue_usd"),
            "value_revenue_multiple_b": bridge_b.get("market_cap_to_consensus_revenue_usd"),
            "value_revenue_multiple_gap_a_minus_b": _gap(bridge_a.get("market_cap_to_consensus_revenue_usd"), bridge_b.get("market_cap_to_consensus_revenue_usd")),
            "momentum_3m_a_pct": a.get("three_month_return_pct"),
            "momentum_3m_b_pct": b.get("three_month_return_pct"),
            "momentum_3m_gap_a_minus_b_pct": _gap(a.get("three_month_return_pct"), b.get("three_month_return_pct")),
            "momentum_1y_a_pct": a.get("one_year_return_pct"),
            "momentum_1y_b_pct": b.get("one_year_return_pct"),
            "momentum_1y_gap_a_minus_b_pct": _gap(a.get("one_year_return_pct"), b.get("one_year_return_pct")),
            "volatility_a_pct": a.get("annualized_volatility_pct"),
            "volatility_b_pct": b.get("annualized_volatility_pct"),
            "volatility_gap_a_minus_b_pct": _gap(a.get("annualized_volatility_pct"), b.get("annualized_volatility_pct")),
            "max_drawdown_a_pct": a.get("max_drawdown_pct"),
            "max_drawdown_b_pct": b.get("max_drawdown_pct"),
            "max_drawdown_gap_a_minus_b_pct": _gap(a.get("max_drawdown_pct"), b.get("max_drawdown_pct")),
            "mechanical_beta_a_to_b": pair.get("beta_a_to_b"),
            "mechanical_beta_b_to_a": pair.get("beta_b_to_a"),
            "borrow_data_available_a": pair.get("borrow_data_available_a"),
            "borrow_data_available_b": pair.get("borrow_data_available_b"),
            "source_quality": "derived_free_factor_proxies",
            "source_note": (
                "Free-data factor proxies: benchmark beta, log market-cap size gap, market-cap/consensus-revenue "
                "value proxy, momentum, volatility and drawdown. These are not formal Barra exposures, do not "
                "neutralize industry/country/currency factors and do not establish borrow feasibility."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_pair_factor_diagnostics() -> pd.DataFrame:
    result = build_airline_pair_factor_diagnostics()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
