"""Check the hand-typed US expense ratios against what the provider publishes.

A registry of fees typed in by hand drifts: issuers cut them, and nothing in
the pipeline notices. The CN side learned this when a reconciliation pass found
16 of 23 wrong, and what hid it was three wrappers sharing one placeholder --
the fee component of the score differentiated nothing, so nothing looked odd.

The US universe had the same shape: eleven SPDR sectors sharing one 0.09%, and
a verification against the issuers on 2026-08-22 found 17 of 27 entries stale,
including all eleven of those. This module exists so the next cut is caught by
the pipeline rather than by someone thinking to look.

yfinance reports the *annual report* expense ratio, which can legitimately
differ from the current prospectus figure. On the 2026-08-22 verification it
agreed with the issuer on every one of the seven entries checked by hand
(SOXX, XLK, IGV, ITA, IHI, ICLN, CIBR), so it is used as the observation and
a mismatch is reported for a human to confirm -- never silently applied.
"""

from __future__ import annotations

import logging
from typing import Any

from .universe import ALL_US_ETFS

logger = logging.getLogger(__name__)

# Below this the difference is rounding in the provider's own reporting, not a
# fee change. One basis point is a real cut and is worth reporting.
FEE_TOLERANCE = 0.00005


def observed_expense_ratios(tickers: list[str] | None = None) -> dict[str, float]:
    """Read each fund's reported expense ratio from yfinance."""
    import yfinance as yf

    targets = tickers or [item["ticker"] for item in ALL_US_ETFS]
    observed: dict[str, float] = {}
    for ticker in targets:
        try:
            operations = yf.Ticker(ticker).funds_data.fund_operations
        except Exception as exc:  # provider shape changes, network, delisting
            logger.warning("expense ratio unavailable for %s: %s", ticker, exc)
            continue
        if operations is None or "Annual Report Expense Ratio" not in operations.index:
            continue
        value = operations.loc["Annual Report Expense Ratio"].iloc[0]
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if value == value and value > 0:  # NaN-safe
            observed[ticker] = value
    return observed


def reconcile_us_fees(observed: dict[str, float]) -> list[dict[str, str]]:
    """Report registry entries that disagree with the observed fee.

    Returns one entry per disagreement, shaped like the pipeline's other
    fetch_errors rows and tagged as an event: a fee that moved is news about
    the fund, not a failed call, and must not mark the run unhealthy.
    """

    problems: list[dict[str, str]] = []
    for item in ALL_US_ETFS:
        ticker = item["ticker"]
        stated = item.get("expense_ratio")
        actual = observed.get(ticker)
        if actual is None:
            continue
        if stated is None:
            problems.append(
                {
                    "dataset": "us_etf_fee", "ticker": ticker, "severity": "event",
                    "error": (
                        f"FeeUnknown: registry states no expense ratio for {ticker}; "
                        f"provider reports {actual:.4%}"
                    ),
                }
            )
            continue
        if abs(float(stated) - actual) <= FEE_TOLERANCE:
            continue
        problems.append(
            {
                "dataset": "us_etf_fee", "ticker": ticker, "severity": "event",
                "error": (
                    f"FeeMismatch: registry states {ticker} expense ratio "
                    f"{float(stated):.4%}, provider reports {actual:.4%}"
                ),
            }
        )
    return problems


def check_us_fees(tickers: list[str] | None = None) -> list[dict[str, str]]:
    """Fetch and reconcile in one call, for pipeline and CLI use."""
    return reconcile_us_fees(observed_expense_ratios(tickers))


__all__ = [
    "FEE_TOLERANCE",
    "check_us_fees",
    "observed_expense_ratios",
    "reconcile_us_fees",
]
