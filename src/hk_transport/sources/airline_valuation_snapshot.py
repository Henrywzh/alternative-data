"""Airline valuation snapshot + implied expectations.

Adds the valuation layer to the equity-underwriting stack: current PE/PS/PB,
constructed EV/EBITDAR where data allows, peer cross-sectional z-scores and
historical-percentile context.  It also converts the current price into the
earnings expectation it implies (the "what is priced in" question):

    implied earnings at current P/E = market cap / current P/E
    implied EPS at current P/E      = price / current P/E

The output is a dated snapshot; valuation is diagnostic only and does not
set a target price.  EV/EBITDAR is built from market cap + interest-bearing
debt - cash, divided by EBITDAR (operating profit + depreciation + lease/
rent) where the components are disclosed; missing components are labelled.
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


OUTPUT_PATH = NORMALIZED_DIR / "airline_valuation_snapshot.csv"
DATASET_ID = "airline_valuation_snapshot"

CURRENT_VALUATION_PATH = NORMALIZED_DIR / "airline_free_current_valuation.csv"
HISTORICAL_BANDS_PATH = NORMALIZED_DIR / "airline_historical_valuation_bands.csv"
MARKET_SNAPSHOT_PATH = NORMALIZED_DIR / "airline_market_snapshot.csv"
DRIVERS_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
UNIT_ECONOMICS_PATH = NORMALIZED_DIR / "airline_unit_economics.csv"
CONSENSUS_PATH = NORMALIZED_DIR / "airline_consensus_ashare_detailed.csv"

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "snapshot_date",
    "price_native",
    "market_cap_native_mn",
    "pe_ttm",
    "pe_fy2026e",
    "ps_ttm",
    "pb_mrq",
    "ev_ebitdar",
    "ev_ebitdar_status",
    "pe_peer_zscore",
    "ps_peer_zscore",
    "pb_peer_zscore",
    "pe_ttm_historical_percentile",
    "pb_historical_percentile",
    "implied_fy2026_net_profit_native_mn",
    "implied_fy2026_eps",
    "consensus_fy2026_eps",
    "model_fy2026_eps",
    "implied_vs_consensus_eps_pct",
    "implied_vs_model_eps_pct",
    "source_note",
    "retrieved_at",
]

COMPANIES = [
    "Spring Airlines",
    "Juneyao Airlines",
    "China Southern Airlines",
    "China Eastern Airlines",
    "Air China",
    "Hainan Airlines Holdings",
]


def _num(value: Any) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _latest(df: pd.DataFrame, company: str, metric: str) -> float | None:
    rows = df[df["company"].eq(company) & df["metric"].eq(metric)]
    if rows.empty:
        return None
    rows = rows.sort_values("observation_date")
    return _num(rows["value"].iloc[-1])


def build_airline_valuation_snapshot() -> pd.DataFrame:
    """Build the valuation + implied-expectations snapshot."""
    retrieved = datetime.now(timezone.utc).isoformat()
    cv = pd.read_csv(CURRENT_VALUATION_PATH)
    bands = pd.read_csv(HISTORICAL_BANDS_PATH)
    ms = pd.read_csv(MARKET_SNAPSHOT_PATH)
    drivers = pd.read_csv(DRIVERS_PATH)
    unit = pd.read_csv(UNIT_ECONOMICS_PATH)
    consensus = pd.read_csv(CONSENSUS_PATH)

    rows: list[dict[str, Any]] = []
    for company in COMPANIES:
        market = ms[ms["company"].eq(company)]
        price = _num(market["latest_price_native"].iloc[0]) if len(market) else None
        mcap = _num(market["market_cap_native_mn"].iloc[0]) if len(market) else None
        pe_ttm = _latest(cv, company, "pe_ttm")
        pe_26e = _latest(cv, company, "pe_fy2026e")
        ps_ttm = _latest(cv, company, "ps_ttm")
        pb = _latest(cv, company, "pb")

        # EV/EBITDAR: mcap + interest-bearing debt - cash, over
        # EBITDAR = operating profit + depreciation + lease/rent.
        annual = drivers[
            drivers["company"].eq(company) & drivers["report_type"].eq("annual")
        ]
        def driver(metric: str) -> float | None:
            r = annual[annual["metric"].eq(metric)]
            return _num(r["value_native"].iloc[0]) if len(r) else None
        debt = driver("interest_bearing_debt")
        cash = driver("cash_and_cash_equivalents")
        op = driver("operating_profit")
        depr = driver("depreciation_amortization")
        ev_ebitdar = None
        ev_status = "missing_components"
        if mcap is not None and debt is not None and cash is not None and op is not None:
            ev = mcap + debt - cash
            # Lease/rent: Spring/Juneyao disclose aircraft lease+depreciation
            # inside the unit-economics aircraft CASK; use it as the lease
            # add-back where depreciation is not separately disclosed.
            ebitdar = op + (depr or 0.0)
            if depr is None:
                unit_row = unit[unit["company"].eq(company)]
                if len(unit_row) and "aircraft_cask_native" in unit_row.columns:
                    ask = _num(unit_row["ask_mn"].iloc[0])
                    aircraft_cask = _num(unit_row["aircraft_cask_native"].iloc[0])
                    if ask not in (None, 0) and aircraft_cask is not None:
                        ebitdar += aircraft_cask * ask
                        ev_status = "lease_addback_from_unit_aircraft_cask"
                    else:
                        ev_status = "lease_addback_missing"
                else:
                    ev_status = "lease_addback_missing"
            else:
                ev_status = "depreciation_from_official_drivers"
            if ebitdar != 0:
                ev_ebitdar = ev / ebitdar

        # Peer z-scores across the six carriers (exclude the carrier itself).
        def peer_z(metric: str) -> float | None:
            vals = {
                c: _latest(cv, c, metric)
                for c in COMPANIES
            }
            peers = [v for c, v in vals.items() if c != company and v is not None]
            own = vals.get(company)
            if own is None or len(peers) < 2:
                return None
            mean = float(np.mean(peers))
            std = float(np.std(peers, ddof=0))
            if std == 0:
                return 0.0
            return (own - mean) / std

        pe_z = peer_z("pe_ttm")
        ps_z = peer_z("ps_ttm")
        pb_z = peer_z("pb")

        def percentile(metric: str, window: str = "1y") -> float | None:
            r = bands[
                bands["company"].eq(company)
                & bands["metric"].eq(metric)
                & bands["window"].eq(window)
            ]
            if r.empty or "current_percentile_positive" not in r.columns:
                return None
            pct = _num(r["current_percentile_positive"].iloc[0])
            return pct

        pe_pct = percentile("pe_ttm") or percentile("PE") or percentile("pe")
        pb_pct = percentile("pb") or percentile("PB")

        # Implied expectations: earnings the current price/PE implies.
        implied_profit = None
        implied_eps = None
        if mcap is not None and pe_26e not in (None, 0):
            implied_profit = mcap / pe_26e
            if price is not None:
                implied_eps = price / pe_26e
        consensus_eps = None
        consensus_profit_mn = None
        model_eps = None
        c_eps = consensus[
            consensus["company"].eq(company)
            & consensus["fiscal_year"].eq(2026)
            & consensus["metric"].eq("net_profit_detailed")
        ]
        if len(c_eps):
            consensus_profit_mn = _num(c_eps["value_avg_native"].iloc[0]) * 100.0
        fb = pd.read_csv(NORMALIZED_DIR / "airline_forward_net_income_bridge.csv")
        fb_row = fb[
            fb["company"].eq(company)
            & fb["model_name"].eq("walk_forward_integrated")
        ]
        if len(fb_row):
            model_eps = _num(fb_row["forward_basic_eps_rmb_per_share"].iloc[0])
            shares = _num(fb_row["implied_basic_shares_mn"].iloc[0])
            if consensus_profit_mn is not None and shares not in (None, 0):
                consensus_eps = consensus_profit_mn / shares
            # Model EPS in the forward bridge is H1-2026; annualise to FY26E
            # for comparison with the FY26E valuation multiple by doubling.
            if model_eps is not None:
                model_eps = model_eps * 2.0

        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "snapshot_date": "2026-08-10",
                "price_native": price,
                "market_cap_native_mn": mcap,
                "pe_ttm": pe_ttm,
                "pe_fy2026e": pe_26e,
                "ps_ttm": ps_ttm,
                "pb_mrq": pb,
                "ev_ebitdar": ev_ebitdar,
                "ev_ebitdar_status": ev_status,
                "pe_peer_zscore": pe_z,
                "ps_peer_zscore": ps_z,
                "pb_peer_zscore": pb_z,
                "pe_ttm_historical_percentile": pe_pct,
                "pb_historical_percentile": pb_pct,
                "implied_fy2026_net_profit_native_mn": implied_profit,
                "implied_fy2026_eps": implied_eps,
                "consensus_fy2026_eps": consensus_eps,
                "model_fy2026_eps": model_eps,
                "implied_vs_consensus_eps_pct": (
                    (implied_eps / consensus_eps - 1.0) * 100.0
                    if implied_eps is not None and consensus_eps not in (None, 0)
                    else None
                ),
                "implied_vs_model_eps_pct": (
                    (implied_eps / model_eps - 1.0) * 100.0
                    if implied_eps is not None and model_eps not in (None, 0)
                    else None
                ),
                "source_note": (
                    "Valuation snapshot: current PE/PS/PB from free provider "
                    "layer; EV/EBITDAR constructed from market cap + debt - "
                    "cash over EBITDAR (lease add-back from unit aircraft "
                    "CASK where depreciation not disclosed); peer z-scores "
                    "across the six-carrier cross-section; implied earnings "
                    "= mcap / current FY26E P/E.  Diagnostic only, no target "
                    "price."
                ),
                "retrieved_at": retrieved,
            }
        )
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "build_airline_valuation_snapshot",
    "source_path",
]
