"""Forward H1-2026 net-income bridge from the 1H2025 interim waterfall.

The v3 model produces a forward waterfall proxy only where the FY2025 annual
report waterfall reconciles (Air China, China Southern).  Spring and Juneyao
annual statements are scanned-image PDFs with no text layer, so their annual
waterfall is marked partial.  Their 1H2025 interim statements ARE
text-parseable and already carried in ``airline_official_report_drivers.csv``.
Since the live research bet is the 1H2026 report season, the 1H2025 interim
waterfall is the correct PIT anchor for a forward H1-2026 net-income bridge.

Method (explicitly labelled, not issuer guidance):

* Operating contribution: H1-2026 walk-forward operating-profit proxy per
  model variant (flat-ASK, flat-RPK, yield-mix, fuel/non-fuel, integrated).
* Finance cost: 1H2025 absolute scaled by forecast/1H2025 revenue (no forward
  debt schedule available; same convention as the v3 FY proxy).
* Other income / investment income / non-operating lines: 1H2025 absolute
  carry (no identifiable free forward driver).
* Tax: 1H2025 effective rate on forward profit before tax when positive,
  otherwise absolute carry.
* NCI: 1H2025 NCI/net-income ratio applied to forward net income when
  interpretable; Spring/Juneyao interim reports reconcile attributable to net
  income total (NCI ~ 0).
* EPS: forward attributable net income divided by the implied basic share
  count carried in the v3 output.

This is a research bridge that replaces the static FY2026 net-to-operating
conversion ratios in the independent view with a real interim waterfall; it is
not a trade approval.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_forward_net_income_bridge.csv"
DATASET_ID = "airline_forward_net_income_bridge"

REPORT_DRIVERS_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
WALK_FORWARD_PATH = (
    NORMALIZED_DIR / "airline_walk_forward_model_v2_current_forecast.csv"
)
V3_PATH = NORMALIZED_DIR / "airline_earnings_model_v3.csv"

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "ticker",
    "horizon",
    "model_name",
    "h1_2025_operating_profit_native_mn",
    "h1_2025_finance_cost_native_mn",
    "h1_2025_profit_before_tax_native_mn",
    "h1_2025_income_tax_native_mn",
    "h1_2025_effective_tax_rate_pct",
    "h1_2025_net_income_total_native_mn",
    "h1_2025_minority_interest_native_mn",
    "h1_2025_attributable_net_income_native_mn",
    "h1_2025_nci_share_pct",
    "h1_2025_revenue_source",
    "forecast_h1_2026_operating_profit_native_mn",
    "forecast_h1_2026_revenue_native_mn",
    "h1_2025_revenue_native_mn",
    "revenue_scale_factor",
    "forward_finance_cost_native_mn",
    "forward_other_income_native_mn",
    "forward_investment_income_native_mn",
    "forward_non_operating_income_native_mn",
    "forward_non_operating_expense_native_mn",
    "forward_profit_before_tax_native_mn",
    "forward_income_tax_native_mn",
    "forward_income_tax_method",
    "forward_net_income_total_native_mn",
    "forward_minority_interest_native_mn",
    "forward_minority_interest_method",
    "forward_attributable_net_income_native_mn",
    "forward_attributable_net_income_usd_mn",
    "implied_basic_shares_mn",
    "forward_basic_eps_rmb_per_share",
    "forward_fx_usd_cny",
    "bridge_status",
    "source_note",
    "retrieved_at",
]

WATERFALL_METRICS = {
    "operating_profit": "h1_2025_operating_profit_native_mn",
    "finance_cost": "h1_2025_finance_cost_native_mn",
    "other_income": "forward_other_income_native_mn",
    "investment_income": "forward_investment_income_native_mn",
    "non_operating_income": "forward_non_operating_income_native_mn",
    "non_operating_expense": "forward_non_operating_expense_native_mn",
    "income_tax_expense": "h1_2025_income_tax_native_mn",
    "net_income_total": "h1_2025_net_income_total_native_mn",
    "minority_interest": "h1_2025_minority_interest_native_mn",
    "attributable_net_income": "h1_2025_attributable_net_income_native_mn",
    "total_revenue": "h1_2025_revenue_native_mn",
}


def _load_report_drivers() -> pd.DataFrame:
    if not REPORT_DRIVERS_PATH.exists():
        raise FileNotFoundError(REPORT_DRIVERS_PATH)
    return pd.read_csv(REPORT_DRIVERS_PATH)


def _load_walk_forward() -> pd.DataFrame:
    if not WALK_FORWARD_PATH.exists():
        raise FileNotFoundError(WALK_FORWARD_PATH)
    return pd.read_csv(WALK_FORWARD_PATH)


def _load_v3() -> pd.DataFrame:
    if not V3_PATH.exists():
        raise FileNotFoundError(V3_PATH)
    return pd.read_csv(V3_PATH)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def build_airline_forward_net_income_bridge() -> pd.DataFrame:
    """Build the H1-2026 forward net-income bridge and persist it."""
    retrieved = datetime.now(timezone.utc).isoformat()
    drivers = _load_report_drivers()
    walk = _load_walk_forward()
    v3 = _load_v3()

    # 1H2025 interim waterfall per company (period column label from the
    # official-report layer is 1H2025).
    interim = drivers[
        drivers["report_type"].eq("interim")
        & drivers["statement_period"].eq("1H2025")
    ]
    if interim.empty:
        raise ValueError("No 1H2025 interim rows in airline_official_report_drivers")

    # H1-2026 walk-forward operating forecasts (all model variants).
    forecasts = walk[walk["statement_period"].eq("1H2026")].copy()
    if forecasts.empty:
        raise ValueError("No 1H2026 rows in airline_walk_forward_model_v2_current_forecast")

    # v3 anchors: implied basic shares + latest FX.
    v3_anchor = v3.groupby("company").first()

    # Core lines required to build the bridge; optional below-operating lines
    # (investment income, fair-value changes, impairments, non-operating
    # income/expense, minority interest) default to zero when not separately
    # disclosed and are recorded in the source note.  Minority interest is
    # derived from the net-income identity when not disclosed.
    required = {
        "operating_profit",
        "finance_cost",
        "income_tax_expense",
        "net_income_total",
    }
    optional = {
        "other_income",
        "investment_income",
        "fair_value_change_income",
        "credit_impairment_loss",
        "asset_impairment_loss",
        "asset_disposal_income",
        "non_operating_income",
        "non_operating_expense",
        "minority_interest",
        "attributable_net_income",
        "total_revenue",
    }

    rows: list[dict[str, Any]] = []
    for company, fgroup in forecasts.groupby("company"):
        company_drivers = interim[interim["company"].eq(company)]
        if company_drivers.empty:
            company_drivers = pd.DataFrame()
        waterfall = company_drivers.set_index("metric")["value_native"].to_dict()
        missing = [m for m in required if m not in waterfall]
        # Annual-anchor fallback: when the interim waterfall is incomplete
        # (typically because the formal interim income statement is embedded
        # as image pages, e.g. Air China's CID-font financials), fall back to
        # the FY2025 annual waterfall for the below-operating structure and
        # calibrate the level with the interim profit-before-tax / attributable
        # anchors when those are disclosed.
        annual_waterfall: dict[str, float] = {}
        annual_drivers = drivers[
            drivers["company"].eq(company) & drivers["report_type"].eq("annual")
        ]
        if not annual_drivers.empty:
            annual_waterfall = {
                metric: value
                for metric, value in annual_drivers.set_index("metric")[
                    "value_native"
                ].to_dict().items()
                if value is not None and pd.notna(value)
            }
        use_annual_fallback = bool(missing) and all(
            m in annual_waterfall
            for m in ("operating_profit", "finance_cost", "income_tax_expense",
                      "net_income_total")
        )
        if missing and not use_annual_fallback:
            rows.append(
                _missing_row(
                    company,
                    fgroup,
                    v3_anchor,
                    retrieved,
                    f"missing_interim_metrics={','.join(sorted(missing))}",
                )
            )
            continue
        fallback_source = "interim_waterfall"
        if use_annual_fallback:
            # Interim anchors (PBT / attributable) calibrate the annual
            # structure to the current interim period where disclosed.  Keep
            # the interim revenue anchor so revenue scaling is not inflated
            # by a full-year annual revenue base.
            interim_anchors = {
                k: v for k, v in waterfall.items() if v is not None
            }
            waterfall = {**annual_waterfall, **interim_anchors}
            fallback_source = "annual_waterfall_interim_pbt_calibrated"
        # Revenue anchor: official interim total revenue, else the walk-forward
        # prior-period (1H2025) revenue used for the H1-2026 forecast.
        h1_revenue = _num(waterfall.get("total_revenue"))
        h1_revenue_source = "official_interim_total_revenue"
        if use_annual_fallback:
            h1_revenue = _num(interim_anchors.get("total_revenue"))
            h1_revenue_source = "official_interim_total_revenue"
            if h1_revenue in (None, 0):
                h1_revenue = _num(waterfall.get("total_revenue"))
                h1_revenue_source = "annual_total_revenue_fallback"
        if h1_revenue in (None, 0):
            prior_revenues = fgroup["prior_revenue_native_mn"].dropna()
            h1_revenue = (
                float(prior_revenues.iloc[0]) if len(prior_revenues) else None
            )
            h1_revenue_source = "walk_forward_prior_period_revenue"
        h1_operating = _num(waterfall.get("operating_profit"))
        h1_finance = _num(waterfall.get("finance_cost"))
        h1_pbt = _num(waterfall.get("profit_total"))
        h1_tax = _num(waterfall.get("income_tax_expense"))
        h1_net = _num(waterfall.get("net_income_total"))
        h1_attr = _num(waterfall.get("attributable_net_income"))
        h1_nci = _num(waterfall.get("minority_interest"))
        if h1_nci is None and h1_net is not None and h1_attr is not None:
            h1_nci = h1_net - h1_attr
        effective_rate = None
        if use_annual_fallback:
            # Calibrate with the disclosed interim profit-before-tax when the
            # interim tax line is not separately disclosed: derive the rate
            # from the annual structure instead of a loss-year artifact.
            annual_pbt = _num(annual_waterfall.get("profit_total"))
            annual_tax = _num(annual_waterfall.get("income_tax_expense"))
            interim_pbt = _num(interim_anchors.get("profit_total"))
            if (
                interim_pbt is not None
                and annual_pbt not in (None, 0)
                and annual_tax is not None
            ):
                effective_rate = 100.0 * annual_tax / annual_pbt
        else:
            if h1_pbt not in (None, 0) and h1_tax is not None:
                effective_rate = 100.0 * h1_tax / h1_pbt
            elif (
                h1_attr is not None
                and h1_nci is not None
                and h1_tax is not None
                and (h1_attr + h1_nci) not in (None, 0)
            ):
                # Fallback effective rate from the net-income identity when
                # profit before tax is not separately disclosed.
                derived_pbt = h1_attr + h1_nci + h1_tax
                if derived_pbt not in (None, 0):
                    effective_rate = 100.0 * h1_tax / derived_pbt
        nci_share = None
        if h1_net not in (None, 0) and h1_nci is not None:
            nci_share = 100.0 * h1_nci / h1_net

        for _, frow in fgroup.iterrows():
            forecast_operating = _num(frow["predicted_operating_profit_proxy_native_mn"])
            forecast_revenue = _num(frow["predicted_revenue_native_mn"])
            if (
                forecast_operating is None
                or forecast_revenue is None
                or h1_revenue in (None, 0)
                or h1_operating is None
                or h1_finance is None
                or h1_tax is None
                or h1_net is None
            ):
                rows.append(
                    _missing_row(
                        company,
                        fgroup.iloc[[fgroup.index.get_loc(frow.name)]],
                        v3_anchor,
                        retrieved,
                        "missing_forecast_or_waterfall_value",
                    )
                )
                continue

            revenue_scale = forecast_revenue / h1_revenue
            if use_annual_fallback:
                # Annual fallback: the FY finance cost is a full-year number.
                # Scale it to the interim revenue base first (annual finance x
                # interim/annual revenue), then grow it with the forecast
                # revenue factor so the H1-2026 finance leg stays at H1 scale.
                annual_revenue = _num(annual_waterfall.get("total_revenue"))
                if h1_revenue not in (None, 0) and annual_revenue not in (None, 0):
                    h1_finance_scaled = h1_finance * h1_revenue / annual_revenue
                else:
                    h1_finance_scaled = h1_finance
                forward_finance = h1_finance_scaled * revenue_scale
            else:
                forward_finance = h1_finance * revenue_scale
            annual_revenue = _num(annual_waterfall.get("total_revenue"))
            annual_scale = 1.0
            if (
                use_annual_fallback
                and h1_revenue not in (None, 0)
                and annual_revenue not in (None, 0)
            ):
                annual_scale = h1_revenue / annual_revenue
            other_income = _num(waterfall.get("other_income"))
            investment_income = _num(waterfall.get("investment_income"))
            non_operating_income = _num(waterfall.get("non_operating_income"))
            non_operating_expense = _num(waterfall.get("non_operating_expense"))
            if use_annual_fallback:
                if other_income is not None:
                    other_income = other_income * annual_scale
                if investment_income is not None:
                    investment_income = investment_income * annual_scale
                if non_operating_income is not None:
                    non_operating_income = non_operating_income * annual_scale
                if non_operating_expense is not None:
                    non_operating_expense = non_operating_expense * annual_scale
            forward_pbt = (
                forecast_operating
                - forward_finance
                + (other_income or 0.0)
                + (investment_income or 0.0)
                + (non_operating_income or 0.0)
                - (non_operating_expense or 0.0)
            )
            # Loss-year deferred-tax artifacts can push the 1H2025 effective
            # rate far outside a normal band (e.g. Southern's 239.6% on a
            # loss-year PBT with reversal effects).  Only apply the rate when
            # it is economically plausible; otherwise carry the absolute tax
            # line (same guard as the v3 regime-flip logic).
            if (
                effective_rate is not None
                and 0.0 <= effective_rate <= 60.0
                and forward_pbt > 0
            ):
                forward_tax = effective_rate / 100.0 * forward_pbt
                tax_method = "h1_2025_effective_rate_on_forward_pbt"
            else:
                forward_tax = h1_tax
                tax_method = "h1_2025_absolute_carry"
                if use_annual_fallback:
                    forward_tax = (h1_tax or 0.0) * annual_scale
                    tax_method = "h1_2025_annual_absolute_carry_scaled_to_interim"
            forward_net = forward_pbt - forward_tax

            forward_nci = h1_nci
            nci_method = "h1_2025_absolute_carry"
            if (
                nci_share is not None
                and h1_nci not in (None, 0)
                and forward_net > 0
                and nci_share > 0
            ):
                forward_nci = nci_share / 100.0 * forward_net
                nci_method = "h1_2025_nci_share_on_forward_net_income"
            elif h1_nci in (None, 0):
                forward_nci = 0.0
                nci_method = "h1_2025_nci_zero_or_not_disclosed"
            if use_annual_fallback and nci_method == "h1_2025_absolute_carry":
                forward_nci = (h1_nci or 0.0) * annual_scale
                nci_method = "h1_2025_annual_nci_carry_scaled_to_interim"
            forward_attr = forward_net - (forward_nci or 0.0)

            anchor = v3_anchor.loc[company] if company in v3_anchor.index else None
            shares = _num(anchor["implied_basic_shares_mn"]) if anchor is not None else None
            fx = _num(anchor["forward_fx_usd_cny"]) if anchor is not None else None
            eps = forward_attr / shares if shares not in (None, 0) else None
            attr_usd = forward_attr / fx if fx not in (None, 0) else None
            rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "company": company,
                    "ticker": frow["ticker"],
                    "horizon": "1H2026",
                    "model_name": frow["model_name"],
                    "h1_2025_operating_profit_native_mn": h1_operating,
                    "h1_2025_finance_cost_native_mn": h1_finance,
                    "h1_2025_profit_before_tax_native_mn": h1_pbt,
                    "h1_2025_income_tax_native_mn": h1_tax,
                    "h1_2025_effective_tax_rate_pct": effective_rate,
                    "h1_2025_net_income_total_native_mn": h1_net,
                    "h1_2025_minority_interest_native_mn": h1_nci,
                    "h1_2025_attributable_net_income_native_mn": h1_attr,
                    "h1_2025_nci_share_pct": nci_share,
                    "h1_2025_revenue_source": h1_revenue_source,
                    "forecast_h1_2026_operating_profit_native_mn": forecast_operating,
                    "forecast_h1_2026_revenue_native_mn": forecast_revenue,
                    "h1_2025_revenue_native_mn": h1_revenue,
                    "h1_2025_revenue_source": h1_revenue_source,
                    "revenue_scale_factor": revenue_scale,
                    "forward_finance_cost_native_mn": forward_finance,
                    "forward_other_income_native_mn": other_income,
                    "forward_investment_income_native_mn": investment_income,
                    "forward_non_operating_income_native_mn": non_operating_income,
                    "forward_non_operating_expense_native_mn": non_operating_expense,
                    "forward_profit_before_tax_native_mn": forward_pbt,
                    "forward_income_tax_native_mn": forward_tax,
                    "forward_income_tax_method": tax_method,
                    "forward_net_income_total_native_mn": forward_net,
                    "forward_minority_interest_native_mn": forward_nci,
                    "forward_minority_interest_method": nci_method,
                    "forward_attributable_net_income_native_mn": forward_attr,
                    "forward_attributable_net_income_usd_mn": attr_usd,
                    "implied_basic_shares_mn": shares,
                    "forward_basic_eps_rmb_per_share": eps,
                    "forward_fx_usd_cny": fx,
                    "bridge_status": (
                        "available_h1_2025_interim_waterfall"
                        if fallback_source == "interim_waterfall"
                        else "available_annual_waterfall_interim_pbt_calibrated"
                    ),
                    "source_note": (
                        "Forward H1-2026 net-income bridge anchored on the "
                        "1H2025 interim official waterfall; operating leg from "
                        "the walk-forward H1-2026 model variant.  Finance cost "
                        "scaled with forecast revenue; non-operating lines "
                        "carried at 1H2025 absolute; tax and NCI as labelled. "
                        "Research bridge, not issuer guidance or a trade approval."
                        if fallback_source == "interim_waterfall"
                        else (
                            "Forward H1-2026 net-income bridge with "
                            "annual-waterfall fallback: the formal interim "
                            "income statement is an image/CID-font page in "
                            "this issuer's report, so the below-operating "
                            "structure (finance cost, tax, NCI) is taken from "
                            "the FY2025 annual waterfall and the level is "
                            "calibrated with the disclosed interim "
                            "profit-before-tax / attributable anchors where "
                            "available.  Operating leg from the walk-forward "
                            "H1-2026 model variant.  Research bridge, not "
                            "issuer guidance or a trade approval."
                        )
                    ),
                    "retrieved_at": retrieved,
                }
            )
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    result = result.drop_duplicates(
        subset=["company", "horizon", "model_name"], keep="last"
    ).sort_values(["company", "model_name"]).reset_index(drop=True)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def _missing_row(
    company: str,
    fgroup: pd.DataFrame,
    v3_anchor: pd.DataFrame,
    retrieved: str,
    reason: str,
) -> dict[str, Any]:
    anchor = v3_anchor.loc[company] if company in v3_anchor.index else None
    shares = _num(anchor["implied_basic_shares_mn"]) if anchor is not None else None
    fx = _num(anchor["forward_fx_usd_cny"]) if anchor is not None else None
    row = {
        "dataset_id": DATASET_ID,
        "company": company,
        "ticker": fgroup["ticker"].iloc[0] if len(fgroup) else None,
        "horizon": "1H2026",
        "model_name": fgroup["model_name"].iloc[0] if len(fgroup) else None,
        "implied_basic_shares_mn": shares,
        "forward_fx_usd_cny": fx,
        "bridge_status": f"not_available_{reason}",
        "source_note": f"Bridge not built: {reason}",
        "retrieved_at": retrieved,
    }
    return row


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "build_airline_forward_net_income_bridge",
    "source_path",
]
