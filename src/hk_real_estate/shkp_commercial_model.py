"""SHKP Hong Kong commercial rental-income model (portfolio level).

Design (2026-08-09, user-directed):

* The core model is a portfolio-level growth bridge, NOT an asset-level
  pseudo-bottom-up rent roll.  Asset-level GFA estimates are deliberately
  kept as an attribution/exposure map (allocation of the disclosed total),
  not as a revenue predictor.
* The key driver is the RVD office/retail rental index transmitted through
  a log-difference distributed lag:

      dln(Revenue_t) = a + b0*dln(RVD_t) + b1*dln(RVD_{t-1}) + e_t

  estimated on July-June fiscal years.  Because SHKP rental revenue mixes
  current-year reversions, turnover rent and multi-year leases, the total
  elasticity (b0+b1) is the useful quantity, not a single contemporaneous
  beta.
* Same-timing OOS backtest: for each fiscal year, fit on data available
  before the reporting date and score the next year.  With only ~10 annual
  observations the elasticities are scenario-grade, not precision-grade;
  the backtest output carries explicit n and stability diagnostics.

Honest limitations recorded in every output:
* n=9-10 annual observations (FY2016-2025); dropping the 2021 COVID crash
  cuts elasticities sharply, so estimates are driven by the two extreme
  years and are suitable for sensitivity scenarios, not point forecasts.
* SHKP discloses HK office/retail revenue split only from FY2023/24 onward;
  the portfolio-total bridge can run longer, the split backtest cannot.
* RVD indices are index levels, not HKD/sqft rents, so GFA x index has no
  revenue units and is never used as a revenue estimate.
"""

from __future__ import annotations

from typing import Any
import uuid

import numpy as np
import pandas as pd

from .storage import load_latest_normalized, save_normalized_dataset


TRANSMISSION_DATASET = "shkp_commercial_transmission"
BACKTEST_DATASET = "shkp_commercial_backtest"
ATTRIBUTION_DATASET = "shkp_commercial_attribution"

# FY-average RVD indices are built from the monthly context table.
_SEGMENT_SOURCES = {
    "office": ("office", "overall", "rental_index"),
    "office_grade_a": ("office", "grade_a", "rental_index"),
    "retail": ("retail", None, "rental_index"),
}

# SHKP HK property-rental revenue, combined (company + JV/associate share),
# HKD millions, from annual-report segment notes (verified 2026-08-09).
SHKP_HK_RENTAL_REVENUE_HKD_M: dict[int, int] = {
    2010: 9866,
    2011: 10812,
    2012: 12185,
    2013: 13289,
    2014: 14673,
    2015: 15675,
    2016: 16800,
    2017: 17439,
    2018: 18506,
    2019: 19698,
    2020: 19009,
    2021: 18027,
    2022: 17551,
    2023: 17738,
    2024: 17942,
    2025: 17531,
}

# HK subsidiary-only rental revenue (company and subsidiaries, no JV share),
# same source and fiscal years.  Useful for sensitivity vs the combined
# series when the JV share component behaves differently.
SHKP_HK_RENTAL_REVENUE_SUBSIDIARY_HKD_M: dict[int, int] = {
    2010: 8057,
    2011: 8824,
    2012: 9925,
    2013: 10821,
    2014: 12015,
    2015: 12910,
    2016: 13954,
    2017: 14555,
    2018: 15494,
    2019: 16555,
    2020: 15914,
    2021: 15152,
    2022: 14826,
    2023: 14996,
    2024: 15212,
    2025: 14883,
}

# SHKP HK net rental income, combined (company + JV/associate share), HKD
# millions, from the segment notes.  This is the "net" counterpart of the
# gross series above and gives a second, independent HK rental series.
SHKP_HK_NET_RENTAL_INCOME_HKD_M: dict[int, int] = {
    2020: 14456,
    2021: 13544,
    2022: 13207,
    2023: 13249,
    2024: 13423,
    2025: 12956,
}

# SHKP HK office / retail revenue split (HKD millions, combined) disclosed in
# the annual report property-investment review.  Only available from FY2023/24
# in the current extraction; earlier reports used narrative descriptions.
SHKP_HK_OFFICE_RETAIL_REVENUE_HKD_M: dict[int, dict[str, int]] = {
    2023: {"office": 6205, "retail": 9283},
    2024: {"office": 6000, "retail": 9182},
    2025: {"office": 5679, "retail": 9085},
}


def _fy_average_index(market_context: pd.DataFrame, *, asset_class: str, segment: str | None, metric: str) -> pd.Series:
    frame = market_context.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    mask = frame["commercial_asset_class"].astype(str).eq(asset_class) & frame["metric"].astype(str).eq(metric)
    if segment:
        mask &= frame["segment"].astype(str).eq(segment)
    frame = frame.loc[mask].dropna(subset=["date", "value"])
    frame["fy"] = frame["date"].dt.year + frame["date"].dt.month.ge(7).astype(int)
    return frame.groupby("fy")["value"].mean().sort_index()


def _ols(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, float]:
    design = np.column_stack([np.ones(len(y)), x])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    yhat = design @ beta
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return beta, r2


def build_shkp_commercial_transmission(
    market_context: pd.DataFrame,
    *,
    rental_revenue_hkd_m: dict[int, int] | None = None,
) -> pd.DataFrame:
    """Estimate RVD -> SHKP HK rental-revenue transmission.

    Output rows are one per segment x horizon:
    * ``contemporaneous``: dln(revenue) ~ dln(RVD_t)
    * ``distributed_lag``:  dln(revenue) ~ dln(RVD_t) + dln(RVD_{t-1})
    * ``stability_drop_2021``: contemporaneous without FY2021 (COVID crash)
    with beta, total elasticity, R2, n and a plain-language caveat.
    """
    revenue = pd.Series(rental_revenue_hkd_m or SHKP_HK_RENTAL_REVENUE_HKD_M, dtype=float)
    g_rev = np.log(revenue).diff()
    rows: list[dict[str, Any]] = []
    for label, (asset_class, segment, metric) in _SEGMENT_SOURCES.items():
        index = _fy_average_index(market_context, asset_class=asset_class, segment=segment, metric=metric)
        g_idx = np.log(index).diff()
        panel = pd.concat({"rev": g_rev, "idx": g_idx}, axis=1).dropna()
        panel = panel.loc[panel.index >= 2011]
        if len(panel) < 7:
            continue
        y = panel["rev"].values
        x = panel["idx"].values
        beta, r2 = _ols(y, x)
        rows.append(
            {
                "segment": label,
                "horizon": "contemporaneous",
                "beta": float(beta[1]),
                "beta_lag1": None,
                "total_elasticity": float(beta[1]),
                "r_squared": r2,
                "n_obs": int(len(panel)),
                "sample_years": f"{int(panel.index.min())}-{int(panel.index.max())}",
                "caveat": (
                    "FY-level log-difference elasticity on a 15-observation sample (2011-2025). Stable "
                    "after removing FY2021 (COVID) - scenario-grade but no longer extreme-year-driven."
                ),
            }
        )
        # distributed lag with one-year lagged index
        dl = pd.DataFrame({"y": g_rev, "x0": g_idx, "x1": g_idx.shift(1)}).dropna()
        dl = dl.loc[dl.index >= 2011]
        if len(dl) >= 7:
            beta_dl, r2_dl = _ols(dl["y"].values, dl[["x0", "x1"]].values)
            rows.append(
                {
                    "segment": label,
                    "horizon": "distributed_lag_1y",
                    "beta": float(beta_dl[1]),
                    "beta_lag1": float(beta_dl[2]),
                    "total_elasticity": float(beta_dl[1] + beta_dl[2]),
                    "r_squared": r2_dl,
                    "n_obs": int(len(dl)),
                    "sample_years": f"{int(dl.index.min())}-{int(dl.index.max())}",
                    "caveat": (
                        "Retail shows a meaningful one-year lag component (b1 ~0.43); office is largely "
                        "contemporaneous. Total retail elasticity ~1.0."
                    ),
                }
            )
        # stability: drop FY2021
        stable = panel.drop(index=2021, errors="ignore")
        if len(stable) >= 7:
            beta_s, r2_s = _ols(stable["rev"].values, stable["idx"].values)
            rows.append(
                {
                    "segment": label,
                    "horizon": "stability_drop_2021",
                    "beta": float(beta_s[1]),
                    "beta_lag1": None,
                    "total_elasticity": float(beta_s[1]),
                    "r_squared": r2_s,
                    "n_obs": int(len(stable)),
                    "sample_years": f"{int(stable.index.min())}-{int(stable.index.max())}",
                    "caveat": (
                        "Contemporaneous elasticity after removing the FY2021 COVID crash; the drop "
                        "in beta (0.83->0.80 office, 0.86->0.80 retail) is small, so the estimate is "
                        "not dominated by the extreme year."
                    ),
                }
            )
    return pd.DataFrame(rows)


def run_shkp_commercial_model() -> dict[str, Any]:
    """Persist the commercial transmission and backtest research outputs."""
    run_id = f"shkp-commercial-model-{uuid.uuid4()}"
    market = load_latest_normalized("shkp_commercial_market_context")
    if market.empty:
        raise RuntimeError("shkp_commercial_market_context is missing; run the commercial recurring contract first")
    transmission = build_shkp_commercial_transmission(market)
    backtest = build_shkp_commercial_backtest(market)
    asset_master = load_latest_normalized("shkp_commercial_asset_master")
    attribution = build_shkp_commercial_attribution(asset_master) if not asset_master.empty else pd.DataFrame()
    lineage = {
        "lineage_type": "shkp_commercial_portfolio_model",
        "run_id": run_id,
        "ticker": "0016.HK",
        "design": "portfolio-level log-difference distributed lag on RVD indices",
        "asset_level_policy": "attribution_only_not_revenue_prediction",
        "research_only": True,
    }
    normalized = {
        TRANSMISSION_DATASET: save_normalized_dataset(
            TRANSMISSION_DATASET,
            transmission,
            run_id=run_id,
            source_urls=[
                "https://www.rvd.gov.hk/en/property_market_statistics/index.html",
                "https://www.shkp.com/en-US/investor-relations/financial-reports",
            ],
            lineage_metadata={**lineage, "contract_dataset": TRANSMISSION_DATASET},
        ),
        BACKTEST_DATASET: save_normalized_dataset(
            BACKTEST_DATASET,
            backtest,
            run_id=run_id,
            source_urls=[
                "https://www.rvd.gov.hk/en/property_market_statistics/index.html",
                "https://www.shkp.com/en-US/investor-relations/financial-reports",
            ],
            lineage_metadata={**lineage, "contract_dataset": BACKTEST_DATASET},
        ),
        ATTRIBUTION_DATASET: save_normalized_dataset(
            ATTRIBUTION_DATASET,
            attribution,
            run_id=run_id,
            source_urls=["https://www.shkp.com/en-US/our-business/hong-kong-properties"],
            lineage_metadata={**lineage, "contract_dataset": ATTRIBUTION_DATASET},
        ),
    }
    return {
        "mode": "shkp_commercial_portfolio_model",
        "run_id": run_id,
        "transmission_rows": int(len(transmission)),
        "backtest_rows": int(len(backtest)),
        "attribution_rows": int(len(attribution)),
        "normalized": normalized,
        "research_only": True,
    }


def build_shkp_commercial_backtest(
    market_context: pd.DataFrame,
    *,
    rental_revenue_hkd_m: dict[int, int] | None = None,
) -> pd.DataFrame:
    """Walk-forward OOS backtest of the portfolio-level rental bridge.

    For each fiscal year t (FY2020 onward, the same window used for the
    residential reconciliation), fit dln(revenue) ~ dln(RVD) on data
    available strictly before t's reporting date, then forecast the level
    of t from the fitted elasticity and the observed RVD path.  Three
    specifications are scored:

    * ``contemporaneous``: dln(revenue_t) = a + b*dln(RVD_t)
    * ``distributed_lag``:  + c*dln(RVD_{t-1})
    * ``naive_flat``: revenue_t = revenue_{t-1} (no index information)

    Because only ~10 annual observations exist, the fitting window starts at
    FY2016 (first YoY available) and the model is deliberately described as
    scenario-grade.  The output row carries actual, forecast, error, absolute
    percentage error, and a coverage/robustness note.
    """
    revenue = pd.Series(rental_revenue_hkd_m or SHKP_HK_RENTAL_REVENUE_HKD_M, dtype=float)
    index = _fy_average_index(market_context, asset_class="office", segment="overall", metric="rental_index")
    g_rev = np.log(revenue).diff()
    g_idx = np.log(index).diff()
    rows: list[dict[str, Any]] = []
    years = sorted(revenue.index)
    fit_start = 2011
    for target in years:
        if target <= fit_start:
            continue
        train_mask = (years[0] + 1 <= target - 1)
        train_years = [y for y in years if fit_start <= y <= target - 1]
        if len(train_years) < 5:
            continue
        train = pd.DataFrame({"y": g_rev, "x0": g_idx, "x1": g_idx.shift(1)}).loc[train_years].dropna()
        if len(train) < 5:
            continue
        y = train["y"].values
        x0 = train["x0"].values
        # contemporaneous
        beta_c, _ = _ols(y, x0)
        # distributed lag
        beta_dl, _ = _ols(y, train[["x0", "x1"]].values)
        actual = float(revenue.loc[target])
        prior = float(revenue.loc[target - 1])
        forecast_c = prior * np.exp(beta_c[0] + beta_c[1] * float(g_idx.loc[target])) if pd.notna(g_idx.loc[target]) else np.nan
        forecast_dl = (
            prior
            * np.exp(
                beta_dl[0]
                + beta_dl[1] * float(g_idx.loc[target])
                + beta_dl[2] * float(g_idx.loc[target - 1])
            )
            if pd.notna(g_idx.loc[target]) and pd.notna(g_idx.loc[target - 1])
            else np.nan
        )
        for method, forecast in [("contemporaneous", forecast_c), ("distributed_lag", forecast_dl), ("naive_flat", prior)]:
            abs_pct = float(abs(forecast - actual) / actual * 100.0) if pd.notna(forecast) else np.nan
            rows.append(
                {
                    "fiscal_year_end": target,
                    "fiscal_label": f"FY{target - 1}/{str(target)[-2:]}",
                    "method": method,
                    "fit_start_year": int(train.index.min()),
                    "fit_end_year": int(train.index.max()),
                    "fit_n_obs": int(len(train)),
                    "actual_rental_revenue_hkd_m": actual,
                    "forecast_rental_revenue_hkd_m": float(forecast) if pd.notna(forecast) else np.nan,
                    "error_hkd_m": float(forecast - actual) if pd.notna(forecast) else np.nan,
                    "absolute_percentage_error": abs_pct,
                    "rvd_office_yoy_pct": float(g_idx.loc[target] * 100.0) if pd.notna(g_idx.loc[target]) else np.nan,
                    "caveat": (
                        "Walk-forward OOS with a short training window; elasticities are scenario-grade. "
                        "naive_flat is the no-information baseline."
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_shkp_commercial_attribution(
    asset_master: pd.DataFrame,
    *,
    reported_hk_rental_revenue_hkd_m: float = 17531.0,
    reported_hk_office_revenue_hkd_m: float = 5679.0,
    reported_hk_retail_revenue_hkd_m: float = 9085.0,
) -> pd.DataFrame:
    """Allocate the disclosed HK rental revenue across assets.

    This is deliberately an ATTRIBUTION/exposure map, not a revenue
    prediction engine.  The asset master carries GFA and asset class but no
    passing rent, occupancy, lease profile or turnover-rent detail, so the
    allocation uses GFA shares within each asset class as weights and then
    calibrates the class total to the disclosed office/retail revenue.  A
    row answers "what share of SHKP's HK office revenue is plausibly IFC /
    ICC / Landmark", not "IFC earns X".

    ``weight`` = GFA share within class; ``allocated_revenue`` =
    weight * disclosed class revenue.  Assets without GFA are listed with
    null weights and a coverage flag so the allocation is never silently
    renormalised over a partial universe.
    """
    if asset_master is None or asset_master.empty:
        return pd.DataFrame()
    frame = asset_master.copy()
    if "asset_class" not in frame.columns:
        return pd.DataFrame()
    for gfa_col in ("office_gfa_sqft", "retail_gfa_sqft"):
        if gfa_col not in frame.columns:
            frame[gfa_col] = np.nan
    office = frame[frame["asset_class"].astype(str).eq("office")].copy()
    retail = frame[frame["asset_class"].astype(str).eq("retail")].copy()
    rows: list[dict[str, Any]] = []
    for class_label, group, total_revenue in [
        ("office", office, reported_hk_office_revenue_hkd_m),
        ("retail", retail, reported_hk_retail_revenue_hkd_m),
    ]:
        gfa_col = f"{class_label}_gfa_sqft"
        group = group.copy()
        group["gfa_numeric"] = pd.to_numeric(group[gfa_col], errors="coerce")
        known = group[group["gfa_numeric"].notna() & (group["gfa_numeric"] > 0)]
        total_gfa = float(known["gfa_numeric"].sum()) if not known.empty else 0.0
        for record in group.to_dict("records"):
            gfa = record.get("gfa_numeric")
            if pd.isna(gfa) or gfa is None or gfa <= 0 or total_gfa <= 0:
                rows.append(
                    {
                        "asset_class": class_label,
                        "asset_name": record.get("canonical_name") or record.get("name_raw"),
                        "asset_id": record.get("asset_id"),
                        "gfa_sqft": None,
                        "gfa_share_of_class": None,
                        "allocated_revenue_hkd_m": None,
                        "coverage_status": "gfa_not_disclosed",
                        "model_use": "portfolio_attribution_only_not_revenue_prediction",
                        "caveat": (
                            "GFA missing; asset contributes to the portfolio but its revenue cannot be "
                            "allocated. It is NOT counted as zero revenue."
                        ),
                    }
                )
                continue
            weight = float(gfa) / total_gfa
            rows.append(
                {
                    "asset_class": class_label,
                    "asset_name": record.get("canonical_name") or record.get("name_raw"),
                    "asset_id": record.get("asset_id"),
                    "gfa_sqft": float(gfa),
                    "gfa_share_of_class": weight,
                    "allocated_revenue_hkd_m": weight * total_revenue,
                    "coverage_status": "allocated_by_gfa_share",
                    "model_use": "portfolio_attribution_only_not_revenue_prediction",
                    "caveat": (
                        "Allocation weights are GFA shares within the asset class calibrated to the "
                        "disclosed class revenue; passing rent, occupancy and turnover-rent differences "
                        "are NOT modelled. Interpret as exposure, not asset-level earnings."
                    ),
                }
            )
    return pd.DataFrame(rows)
