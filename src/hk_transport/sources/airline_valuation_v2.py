"""Valuation v2: Street vs Own multiples for the 1H2026 pair decision.

Roadmap item 3.  Answers the question: even if Spring beats, is the stock
still cheap?  Two valuation sets per carrier:

    Street set  - price / consensus FY2026 EPS (what the market pays for
                  what Street expects)
    Own set     - price / v4 seasonality-adjusted FY2026 EPS (what the
                  market pays for what we expect)

Plus P/B (current vs 1y percentile) and EV/EBITDAR where the free data
allow it.  The expectation gap is then:

    PE_Street / PE_Own - 1

which is the multiple the stock re-rates if WE are right and Street
converges to our number (holding price constant).

Seasonality adjustment comes from consensus-reverse-v2 (Spring x2.03,
Juneyao x2.67 - the x2 convention understates Juneyao's FY EPS, so Own
P/E uses the season-adjusted EPS).

Honest limits: EV/EBITDAR is missing for most carriers (no reliable
free debt/cash/lease split for all six); P/B history is only ~1 year of
public Baidu data; prices are the latest snapshot (2026-08-10), not PIT.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..config import NORMALIZED_DIR

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_valuation_v2.csv"
PAIR_OUTPUT_PATH = NORMALIZED_DIR / "airline_valuation_v2_pair.csv"
DATASET_ID = "airline_valuation_v2"

EXPECTATION_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
V4_LIVE_PATH = NORMALIZED_DIR / "airline_earnings_model_v4_live_forecast.csv"
SANITY_PATH = NORMALIZED_DIR / "airline_consensus_reverse_v2_sanity.csv"
VALUATION_SNAPSHOT_PATH = NORMALIZED_DIR / "airline_valuation_snapshot.csv"
HIST_PB_PATH = NORMALIZED_DIR / "airline_historical_pb_valuation.csv"
CURRENT_VAL_PATH = NORMALIZED_DIR / "airline_free_current_valuation.csv"
V3_PATH = NORMALIZED_DIR / "airline_earnings_model_v3.csv"

COMPANIES = [
    "Air China",
    "China Eastern Airlines",
    "China Southern Airlines",
    "Hainan Airlines Holdings",
    "Juneyao Airlines",
    "Spring Airlines",
]


def _num(value: object) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _row(frame: pd.DataFrame, **criteria: object) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=object)
    mask = pd.Series(True, index=frame.index)
    for column, value in criteria.items():
        if column not in frame.columns:
            return pd.Series(dtype=object)
        mask &= frame[column].eq(value)
    rows = frame.loc[mask]
    if rows.empty:
        return pd.Series(dtype=object)
    if "market" in rows.columns:
        cn_a = rows[rows.market.eq("CN_A")]
        if not cn_a.empty:
            return cn_a.iloc[0]
    return rows.iloc[0]


def _a_share_price(expectation: pd.DataFrame, company: str) -> tuple[float | None, str]:
    """A-share price for the company (Spring/Juneyao/Hainan are A-only in
    the price layer; the big three quote HKD in the H-share row and RMB in
    the A-share row - prefer the CN_A row)."""
    row = _row(expectation, company=company, market="CN_A")
    if row.empty:
        row = _row(expectation, company=company)
    price = _num(row.get("latest_price_native"))
    return price, str(row.get("price_currency", ""))


def _provider_metric(cv: pd.DataFrame, company: str, metric: str) -> float | None:
    row = _row(cv, company=company, metric=metric)
    if row.empty:
        return None
    return _num(row.get("value"))


def build_airline_valuation_v2() -> dict[str, pd.DataFrame]:
    """Build Street vs Own valuation sets + pair table."""
    retrieved = datetime.now(timezone.utc).isoformat()
    expectation = pd.read_csv(EXPECTATION_PATH)
    v4_live = pd.read_csv(V4_LIVE_PATH)
    sanity = pd.read_csv(SANITY_PATH)
    snapshot = pd.read_csv(VALUATION_SNAPSHOT_PATH)
    hist_pb = pd.read_csv(HIST_PB_PATH)
    cv = pd.read_csv(CURRENT_VAL_PATH)
    v3 = pd.read_csv(V3_PATH)

    rows: list[dict[str, Any]] = []
    for company in COMPANIES:
        price, currency = _a_share_price(expectation, company)
        cons_eps = _num(_row(expectation, company=company).get("a_share_eps_2026_native"))
        v4_row = _row(v4_live, company=company)
        h1_eps = _num(v4_row.get("eps_overlay_rmb"))
        san = _row(sanity, company=company)
        season_mult = _num(san.get("seasonality_fy_multiplier"))
        own_eps = h1_eps * season_mult if (h1_eps is not None and season_mult) else None

        # P/E is only meaningful when the EPS base is not near zero
        # (Air China's consensus 0.006 -> 955x is a data artifact, not a
        # valuation claim).
        MIN_EPS_FOR_PE = 0.05
        pe_street = price / cons_eps if (price and cons_eps and abs(cons_eps) >= MIN_EPS_FOR_PE) else None
        pe_own = price / own_eps if (price and own_eps and abs(own_eps) >= MIN_EPS_FOR_PE) else None
        re_rate_if_right = (pe_own / pe_street - 1.0) * 100.0 if (pe_own and pe_street) else None

        # v3 model EPS for reference.
        v3b = _row(v3, company=company, scenario="base")
        v3_eps = _num(v3b.get("v3_basic_eps_proxy_rmb_per_share"))
        pe_v3 = price / v3_eps if (price and v3_eps and abs(v3_eps) >= MIN_EPS_FOR_PE) else None

        pb = _provider_metric(cv, company, "pb")
        pb_pct = _num(_row(hist_pb, company=company).get("current_pb_percentile_1y"))
        pb_median = _num(_row(hist_pb, company=company).get("pb_median_1y"))

        # EV/EBITDAR from existing snapshot where available.
        snap = _row(snapshot, company=company)
        ev_ebitdar = _num(snap.get("ev_ebitdar"))
        ev_status = str(snap.get("ev_ebitdar_status", ""))

        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "snapshot_date": "2026-08-10",
                "price_native": price,
                "price_currency": currency,
                "consensus_eps_fy2026_rmb": cons_eps,
                "v4_h1_eps_rmb": h1_eps,
                "seasonality_multiplier": season_mult,
                "v4_fy_eps_season_adj_rmb": own_eps,
                "pe_street": pe_street,
                "pe_own": pe_own,
                "pe_v3": pe_v3,
                "re_rate_if_own_eps_materialises_pct": re_rate_if_right,
                "pb_current": pb,
                "pb_1y_percentile": pb_pct,
                "pb_1y_median": pb_median,
                "ev_ebitdar": ev_ebitdar,
                "ev_ebitdar_status": ev_status,
                "retrieved_at": retrieved,
            }
        )

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_PATH, index=False)

    # Pair table: Spring vs Juneyao, all multiples.
    sp = df[df.company.eq("Spring Airlines")].iloc[0]
    jy = df[df.company.eq("Juneyao Airlines")].iloc[0]
    pair = pd.DataFrame(
        [
            {
                "metric": "pe_street",
                "spring": sp["pe_street"],
                "juneyao": jy["pe_street"],
                "spring_minus_juneyao": sp["pe_street"] - jy["pe_street"] if (sp["pe_street"] is not None and jy["pe_street"] is not None) else None,
                "note": "Market price for Street expectations: Spring cheaper on consensus",
            },
            {
                "metric": "pe_own",
                "spring": sp["pe_own"],
                "juneyao": jy["pe_own"],
                "spring_minus_juneyao": sp["pe_own"] - jy["pe_own"] if (sp["pe_own"] is not None and jy["pe_own"] is not None) else None,
                "note": "Market price for OUR season-adjusted EPS",
            },
            {
                "metric": "re_rate_if_own_eps_materialises_pct",
                "spring": sp["re_rate_if_own_eps_materialises_pct"],
                "juneyao": jy["re_rate_if_own_eps_materialises_pct"],
                "spring_minus_juneyao": None,
                "note": "Multiple compression/expansion if price holds and EPS moves to our number",
            },
            {
                "metric": "pb_1y_percentile",
                "spring": sp["pb_1y_percentile"],
                "juneyao": jy["pb_1y_percentile"],
                "spring_minus_juneyao": None,
                "note": "P/B position within 1y range (low = cheap vs own history)",
            },
        ]
    )
    pair["retrieved_at"] = retrieved
    pair.to_csv(PAIR_OUTPUT_PATH, index=False)

    return {"valuation": df, "pair": pair}


__all__ = [
    "OUTPUT_PATH",
    "PAIR_OUTPUT_PATH",
    "build_airline_valuation_v2",
]
