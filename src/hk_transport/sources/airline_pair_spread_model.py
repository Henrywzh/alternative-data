"""Spring - Juneyao direct earnings-spread model (priority 6).

Instead of forecasting the two absolute earnings levels and subtracting,
this model directly forecasts the pair spread, letting the common risks
(fuel, macro, RMB, domestic travel) cancel.  It uses pair-level operating
variables that measure the RELATIVE advantage:

* ASK growth gap (Spring ASK vs Juneyao ASK) - capacity advantage
* RPK-ASK gap difference - demand-pricing advantage
* load-factor difference - cabin pricing power
* unit-cost (CASK) difference - cost advantage (from unit economics)

The model regresses the historical annualised spread on these pair-level
drivers and produces a H1-2026 spread forecast.  It is a transparent
relative-value model, not a fitted black box: the drivers are the same
economic forces as the unit-economics and capacity layers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ..config import NORMALIZED_DIR, ROOT_DIR

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_spread_model.csv"
DATASET_ID = "airline_pair_spread_model"

FINANCIAL_HISTORY_PATH = NORMALIZED_DIR / "airline_financial_history_trend.csv"
MONTHLY_RAW_PATH = (
    ROOT_DIR / "data" / "processed" / "airline_traffic"
    / "china_airlines_monthly.parquet"
)
UNIT_ECONOMICS_PATH = NORMALIZED_DIR / "airline_unit_economics.csv"

OUTPUT_COLUMNS = [
    "dataset_id",
    "pair_id",
    "period",
    "target_year",
    "spread_actual_native_mn",
    "ask_growth_gap_pp",
    "rpk_ask_gap_diff_pp",
    "lf_diff_pp",
    "cask_diff_native",
    "spread_predicted_native_mn",
    "spread_residual_native_mn",
    "spread_direction_correct",
    "model_status",
    "source_note",
    "retrieved_at",
]

PAIR_ID = "601021.SH__603885.SH"
LONG = "601021"
SHORT = "603885"


def _num(value: Any) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _fy_spread() -> pd.Series:
    fh = pd.read_csv(FINANCIAL_HISTORY_PATH)

    def fy_income(code: str) -> pd.Series:
        s = fh[fh["ticker"].str.contains(code, na=False) & fh["metric"].eq("attributable_net_income") & fh["period_type"].eq("FY")]
        if s.empty:
            s = fh[fh["ticker"].str.contains(code, na=False) & fh["metric"].eq("net_income") & fh["period_type"].eq("FY")]
        s = s.copy()
        s["year"] = pd.to_datetime(s["period_end"]).dt.year
        return s.groupby("year")["value_native"].last()

    sp = fy_income(LONG)
    jy = fy_income(SHORT)
    both = pd.concat([sp, jy], axis=1, keys=["spring", "juneyao"]).dropna()
    return both["spring"] - both["juneyao"]


def _pair_monthly() -> pd.DataFrame:
    m = pq.read_table(MONTHLY_RAW_PATH).to_pandas()
    m["month_parsed"] = pd.to_datetime(m["month"])
    m["year"] = m["month_parsed"].dt.year

    def total_series(code: str, metric: str) -> pd.Series:
        s = m[
            m["airline_code"].eq(code)
            & m["region"].eq("Total")
            & m["metric"].eq(metric)
        ].set_index("month_parsed")["value"]
        # Duplicate months (e.g. different vintages) -> last wins.
        return s[~s.index.duplicated(keep="last")]

    rows = []
    for metric in ("ask", "rpk", "passenger_load_factor_pct"):
        if metric == "passenger_load_factor_pct":
            # No company-total LF row is published; derive from total
            # RPK/ASK (same convention as the imputed KPI layer).
            sp = total_series(LONG, "rpk") / total_series(LONG, "ask") * 100.0
            jy = total_series(SHORT, "rpk") / total_series(SHORT, "ask") * 100.0
        else:
            sp = total_series(LONG, metric)
            jy = total_series(SHORT, metric)
        df = pd.concat([sp, jy], axis=1, keys=["spring", "juneyao"])
        df["year"] = df.index.year
        if metric == "ask":
            annual = df.groupby("year").sum()
            rows.append(("ask_growth_gap_pp", annual["spring"].pct_change() * 100 - annual["juneyao"].pct_change() * 100))
        elif metric == "rpk":
            annual = df.groupby("year").sum()
            rows.append(("rpk_growth_gap_pp", annual["spring"].pct_change() * 100 - annual["juneyao"].pct_change() * 100))
        else:
            annual = df.groupby("year").mean()
            rows.append(("lf_diff_pp", annual["spring"] - annual["juneyao"]))
    out = pd.concat([r[1] for r in rows], axis=1)
    out.columns = [r[0] for r in rows]
    return out


def build_airline_pair_spread_model() -> pd.DataFrame:
    """Build the direct pair-spread forecast."""
    retrieved = datetime.now(timezone.utc).isoformat()
    spread = _fy_spread()
    drivers = _pair_monthly()
    unit = pd.read_csv(UNIT_ECONOMICS_PATH)
    cask_sp = _num(unit[unit["company"].eq("Spring Airlines")]["cask_native"].iloc[0])
    cask_jy = _num(unit[unit["company"].eq("Juneyao Airlines")]["cask_native"].iloc[0])
    cask_diff = (cask_jy - cask_sp) if cask_sp is not None and cask_jy is not None else None

    joined = pd.concat([spread.rename("spread"), drivers], axis=1).dropna()
    # Simple linear driver: spread = a + b1 x ask_gap + b2 x rpk-ask gap + b3 x lf_diff
    X = joined[["ask_growth_gap_pp", "rpk_growth_gap_pp", "lf_diff_pp"]].values
    y = joined["spread"].values
    rows: list[dict[str, Any]] = []
    if len(joined) >= 5:
        Xc = np.column_stack([np.ones(len(X)), X])
        try:
            beta, *_ = np.linalg.lstsq(Xc, y, rcond=None)
            y_hat = Xc @ beta
        except np.linalg.LinAlgError:
            beta = None
            y_hat = np.full(len(y), np.nan)
        for year, actual, pred in zip(joined.index, y, y_hat):
            rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "pair_id": PAIR_ID,
                    "period": "FY",
                    "target_year": int(year),
                    "spread_actual_native_mn": actual,
                    "ask_growth_gap_pp": joined.loc[year, "ask_growth_gap_pp"],
                    "rpk_ask_gap_diff_pp": joined.loc[year, "rpk_growth_gap_pp"] - joined.loc[year, "ask_growth_gap_pp"],
                    "lf_diff_pp": joined.loc[year, "lf_diff_pp"],
                    "cask_diff_native": cask_diff,
                    "spread_predicted_native_mn": pred,
                    "spread_residual_native_mn": actual - pred,
                    "spread_direction_correct": bool(np.sign(pred) == np.sign(actual)) if not np.isnan(pred) else None,
                    "model_status": "historical_fit",
                    "source_note": (
                        "Direct pair-spread model: Spring - Juneyao net "
                        "income spread regressed on pair-level ASK-growth gap, "
                        "RPK-ASK gap difference and load-factor difference; "
                        "common risks (fuel/macro/RMB/domestic demand) cancel "
                        "in the difference.  CASK difference from unit "
                        "economics held as the structural cost advantage."
                    ),
                    "retrieved_at": retrieved,
                }
            )
        # H1-2026 forecast: use the most recent pair-level operating gap.
        last = drivers.iloc[-1]
        if beta is not None:
            fwd = np.array([1.0, last["ask_growth_gap_pp"], last["rpk_growth_gap_pp"] - last["ask_growth_gap_pp"], last["lf_diff_pp"]])
            # Rebuild X with the same 4 columns (intercept, ask_gap, rpk_gap, lf)
            Xc_full = np.column_stack([np.ones(len(joined)), joined["ask_growth_gap_pp"], joined["rpk_growth_gap_pp"], joined["lf_diff_pp"]])
            beta_full, *_ = np.linalg.lstsq(Xc_full, y, rcond=None)
            fwd_vec = np.array([1.0, last["ask_growth_gap_pp"], last["rpk_growth_gap_pp"], last["lf_diff_pp"]])
            fwd_spread = float(fwd_vec @ beta_full)
            rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "pair_id": PAIR_ID,
                    "period": "H1",
                    "target_year": 2026,
                    "spread_actual_native_mn": None,
                    "ask_growth_gap_pp": last["ask_growth_gap_pp"],
                    "rpk_ask_gap_diff_pp": last["rpk_growth_gap_pp"] - last["ask_growth_gap_pp"],
                    "lf_diff_pp": last["lf_diff_pp"],
                    "cask_diff_native": cask_diff,
                    "spread_predicted_native_mn": fwd_spread,
                    "spread_residual_native_mn": None,
                    "spread_direction_correct": None,
                    "model_status": "current_forecast",
                    "source_note": (
                        "H1-2026 pair-spread forecast from the same driver "
                        "regression using the most recent pair-level gaps; "
                        "annualised basis, research forecast not a trade "
                        "signal."
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
    "build_airline_pair_spread_model",
    "source_path",
]
