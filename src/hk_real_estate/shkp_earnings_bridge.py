"""SHKP whole-company historical earnings bridge (FY2011-FY2025).

Purpose: pull the 16-year unified bridge that the whole-company earnings
nowcast will sit on:

    segment revenue -> segment operating profit -> underlying profit
    -> (+FV changes + other non-underlying) -> reported profit -> EPS

All values are sourced from the official "Group Financial Summary" /
"Five-Year Financial Summary" pages of the annual reports:

* FY2011-FY2015 from the 2014/15 annual report;
* FY2016-FY2020 from the 2019/20 annual report;
* FY2021-FY2025 from the 2024/25 annual report.

Overlapping years (FY2015 in the first two, FY2020 in the last two) are
kept explicit as reconciliation checks.  The bridge deliberately separates:

* underlying profit (the nowcast target - operating earnings power), and
* reported profit (underlying + investment-property fair-value changes and
  other non-underlying items) - reported EPS is only an accounting bridge,
  never the primary forecast target.

HK segment detail (property sales / rental revenue by region, hotel,
telecom, infrastructure, other) is carried from the segment notes where
available; the FY2021-25 summary-level segment split (property sales /
rental / other businesses, all-region) is included alongside so the two
granularities can be compared without being silently merged.
"""

from __future__ import annotations

from typing import Any
import uuid

import pandas as pd

from .storage import save_normalized_dataset


BRIDGE_DATASET = "shkp_historical_earnings_bridge"
HOTEL_DATASET = "shkp_hotel_segment_series"
MARGIN_DATASET = "shkp_hk_development_margin_history"
BELOW_SEGMENT_DATASET = "shkp_below_segment_decomposition"

# HK-only property-development segment: combined (company + JV/associate)
# recognised revenue and development profit, HKD millions, from the annual
# report segment notes.  This is the frozen development-margin definition:
# HK attributable development profit / HK attributable recognised
# property-sales revenue (combined, including JV share).  It is NOT the
# all-region five-year summary line, which mixes Mainland and Singapore.
_HK_DEVELOPMENT_MARGIN: dict[int, dict[str, int]] = {
    2013: {"revenue_combined": 16322, "profit_combined": 6444},
    2014: {"revenue_combined": 27056, "profit_combined": 7568},
    2015: {"revenue_combined": 11253, "profit_combined": 4571},
    2016: {"revenue_combined": 36446, "profit_combined": 9671},
    2017: {"revenue_combined": 30261, "profit_combined": 9936},
    2018: {"revenue_combined": 35725, "profit_combined": 13936},
    2019: {"revenue_combined": 36541, "profit_combined": 16395},
    2020: {"revenue_combined": 36873, "profit_combined": 16333},
    2021: {"revenue_combined": 34880, "profit_combined": 14571},
    2022: {"revenue_combined": 32878, "profit_combined": 14832},
    2023: {"revenue_combined": 23866, "profit_combined": 8474},
    2024: {"revenue_combined": 24745, "profit_combined": 6513},
    2025: {"revenue_combined": 26139, "profit_combined": 3200},
}

# Official company recognition guidance from the annual reports (HK
# contracted sales yet to be recognised -> expected recognition in the next
# financial year), HKD millions.  This is the issuer's own forward-looking
# anchor, preferred over the model lag kernel where available.
_HK_RECOGNITION_GUIDANCE: dict[int, dict[str, int]] = {
    2024: {"backlog_hk": 24900, "expected_following_fy": 19600},
    2025: {"backlog_hk": 35600, "expected_following_fy": 30100},
}

# Mainland and Singapore segment detail (combined revenue/profit, HKD
# millions) from the annual-report segment notes.  FY2013 mainland
# development row uses a different table layout and is left absent; the
# rest are verified against the source PDFs (2024/25 narrative confirms
# mainland development revenue +214% to 8,417 and profit +281% to 5,090).
_MAINLAND_SINGAPORE_SEGMENT: dict[int, dict[str, int | None]] = {
    2014: {"dev_ml_rev": 9216, "dev_ml_res": 2915, "rent_ml_rev": 3113, "rent_ml_res": 2298, "rent_sg_rev": None, "rent_sg_res": None},
    2015: {"dev_ml_rev": 10451, "dev_ml_res": 2764, "rent_ml_rev": 3319, "rent_ml_res": 2520, "rent_sg_rev": None, "rent_sg_res": None},
    2016: {"dev_ml_rev": 6863, "dev_ml_res": 2008, "rent_ml_rev": 3566, "rent_ml_res": 2737, "rent_sg_rev": None, "rent_sg_res": None},
    2017: {"dev_ml_rev": 8304, "dev_ml_res": 1950, "rent_ml_rev": 3789, "rent_ml_res": 2952, "rent_sg_rev": None, "rent_sg_res": None},
    2018: {"dev_ml_rev": 6195, "dev_ml_res": 2314, "rent_ml_rev": 4457, "rent_ml_res": 3534, "rent_sg_rev": None, "rent_sg_res": None},
    2019: {"dev_ml_rev": 4772, "dev_ml_res": 2302, "rent_ml_rev": 4666, "rent_ml_res": 3746, "rent_sg_rev": None, "rent_sg_res": None},
    2020: {"dev_ml_rev": 4359, "dev_ml_res": 2034, "rent_ml_rev": 4617, "rent_ml_res": 3662, "rent_sg_rev": None, "rent_sg_res": None},
    2021: {"dev_ml_rev": 11137, "dev_ml_res": 6423, "rent_ml_rev": 6122, "rent_ml_res": 5099, "rent_sg_rev": None, "rent_sg_res": None},
    2022: {"dev_ml_rev": 2525, "dev_ml_res": 1015, "rent_ml_rev": 6575, "rent_ml_res": 5515, "rent_sg_rev": None, "rent_sg_res": None},
    2023: {"dev_ml_rev": 5250, "dev_ml_res": 2825, "rent_ml_rev": 5843, "rent_ml_res": 4648, "rent_sg_rev": None, "rent_sg_res": None},
    2024: {"dev_ml_rev": 2677, "dev_ml_res": 1337, "rent_ml_rev": 6305, "rent_ml_res": 5027, "rent_sg_rev": 744, "rent_sg_res": 550},
    2025: {"dev_ml_rev": 8417, "dev_ml_res": 5090, "rent_ml_rev": 6173, "rent_ml_res": 4864, "rent_sg_rev": 757, "rent_sg_res": 572},
}

# SHKP hotel segment: combined revenue (company + JV/associate share) and
# combined result (operating profit after depreciation), HKD millions, from
# the annual-report segment notes.  FY2013-FY2025 available; FY2011-2012
# annual reports used a different segment-table layout (revenue analysis
# table), so those two years are intentionally absent.
_HOTEL_SEGMENT: dict[int, dict[str, int | None]] = {
    2013: {"revenue_combined": 4037, "result_combined": 937},
    2014: {"revenue_combined": 4610, "result_combined": 1252},
    2015: {"revenue_combined": 4838, "result_combined": 1293},
    2016: {"revenue_combined": 4711, "result_combined": 1259},
    2017: {"revenue_combined": 4896, "result_combined": 1325},
    2018: {"revenue_combined": 5333, "result_combined": 1470},
    2019: {"revenue_combined": 5682, "result_combined": 1433},
    2020: {"revenue_combined": 3075, "result_combined": -330},
    2021: {"revenue_combined": 2542, "result_combined": -511},
    2022: {"revenue_combined": 3071, "result_combined": -429},
    2023: {"revenue_combined": 4215, "result_combined": 161},
    2024: {"revenue_combined": 5261, "result_combined": 650},
    2025: {"revenue_combined": 5250, "result_combined": 615},
}


# FY -> (revenue, op_profit_pre_fv, op_profit_post_fv, profit_attributable,
#        underlying_profit, reported_eps, underlying_eps, dps)
# All HKD millions except per-share amounts (HKD).  FY2011-FY2015 from the
# 2014/15 Group Financial Summary; FY2016-FY2020 from the 2019/20 summary;
# FY2021-FY2025 from the 2024/25 Five-Year Financial Summary.  FY2015 and
# FY2020 appear in two summaries and are checked for consistency.
_GROUP_SUMMARY: dict[int, dict[str, float | int | None]] = {
    2011: {"revenue": 62553, "op_profit_pre_fv": 21366, "op_profit_post_fv": 46436, "profit_attributable": 48097, "underlying_profit": 21479, "reported_eps": 18.71, "underlying_eps": 8.36, "dps": 3.35, "fv_effect_derived": 25070},
    2012: {"revenue": 68400, "op_profit_pre_fv": 24988, "op_profit_post_fv": 44470, "profit_attributable": 43080, "underlying_profit": 21678, "reported_eps": 16.63, "underlying_eps": 8.37, "dps": 3.35, "fv_effect_derived": 19482},
    2013: {"revenue": 53793, "op_profit_pre_fv": 19300, "op_profit_post_fv": 38487, "profit_attributable": 40329, "underlying_profit": 18619, "reported_eps": 15.28, "underlying_eps": 7.05, "dps": 3.35, "fv_effect_derived": 19187},
    2014: {"revenue": 75100, "op_profit_pre_fv": 24982, "op_profit_post_fv": 37113, "profit_attributable": 33520, "underlying_profit": 21415, "reported_eps": 12.45, "underlying_eps": 7.95, "dps": 3.35, "fv_effect_derived": 12131},
    2015: {"revenue": 66783, "op_profit_pre_fv": 22778, "op_profit_post_fv": 33765, "profit_attributable": 31082, "underlying_profit": 19825, "reported_eps": 11.09, "underlying_eps": 7.07, "dps": 3.35, "fv_effect_derived": 10987},
    2016: {"revenue": 91184, "op_profit_pre_fv": 28856, "op_profit_post_fv": 37625, "profit_attributable": 32666, "underlying_profit": 24170, "reported_eps": 11.31, "underlying_eps": 8.37, "dps": 3.85, "fv_effect_derived": 8769},
    2017: {"revenue": 78207, "op_profit_pre_fv": 29526, "op_profit_post_fv": 43336, "profit_attributable": 41782, "underlying_profit": 25965, "reported_eps": 14.43, "underlying_eps": 8.97, "dps": 4.10, "fv_effect_derived": 13810},
    2018: {"revenue": 85644, "op_profit_pre_fv": 35453, "op_profit_post_fv": 51225, "profit_attributable": 49951, "underlying_profit": 30398, "reported_eps": 17.24, "underlying_eps": 10.49, "dps": 4.65, "fv_effect_derived": 15772},
    2019: {"revenue": 85302, "op_profit_pre_fv": 37858, "op_profit_post_fv": 50393, "profit_attributable": 44912, "underlying_profit": 32398, "reported_eps": 15.50, "underlying_eps": 11.18, "dps": 4.95, "fv_effect_derived": 12535},
    2020: {"revenue": 82653, "op_profit_pre_fv": 35455, "op_profit_post_fv": 31032, "profit_attributable": 23521, "underlying_profit": 29368, "reported_eps": 8.12, "underlying_eps": 10.13, "dps": 4.95, "fv_effect_derived": -4423},
    2021: {"revenue": 85262, "op_profit_pre_fv": None, "op_profit_post_fv": None, "profit_attributable": 26686, "underlying_profit": 29873, "reported_eps": 9.21, "underlying_eps": 10.31, "dps": 4.95},
    2022: {"revenue": 77747, "op_profit_pre_fv": None, "op_profit_post_fv": None, "profit_attributable": 25560, "underlying_profit": 28729, "reported_eps": 8.82, "underlying_eps": 9.91, "dps": 4.95},
    2023: {"revenue": 71195, "op_profit_pre_fv": None, "op_profit_post_fv": None, "profit_attributable": 23907, "underlying_profit": 23885, "reported_eps": 8.25, "underlying_eps": 8.24, "dps": 4.95},
    2024: {"revenue": 71506, "op_profit_pre_fv": None, "op_profit_post_fv": None, "profit_attributable": 19046, "underlying_profit": 21739, "reported_eps": 6.57, "underlying_eps": 7.50, "dps": 3.75},
    2025: {"revenue": 79721, "op_profit_pre_fv": None, "op_profit_post_fv": None, "profit_attributable": 19277, "underlying_profit": 21855, "reported_eps": 6.65, "underlying_eps": 7.54, "dps": 3.75},
}

# Investment-property fair-value effect (HKD millions) and the segment
# revenue/profit split by business line.  FY2021-FY2025 from the 2024/25
# Five-Year Financial Summary "Key Segment Revenue and Operating Profit".
_SEGMENT_SUMMARY: dict[int, dict[str, float | int | None]] = {
    2021: {
        "fv_effect": -3187,
        "segment_revenue": 97130,
        "segment_profit": 44176,
        "property_sales_revenue": 46017, "property_sales_profit": 20994,
        "property_rental_revenue": 24791, "property_rental_profit": 19149,
        "other_businesses_revenue": 26322, "other_businesses_profit": 4033,
    },
    2022: {
        "fv_effect": -3169,
        "segment_revenue": 88340,
        "segment_profit": 39010,
        "property_sales_revenue": 35403, "property_sales_profit": 15847,
        "property_rental_revenue": 24810, "property_rental_profit": 19250,
        "other_businesses_revenue": 28127, "other_businesses_profit": 3913,
    },
    2023: {
        "fv_effect": 22,
        "segment_revenue": 83381,
        "segment_profit": 34689,
        "property_sales_revenue": 29116, "property_sales_profit": 11299,
        "property_rental_revenue": 24322, "property_rental_profit": 18461,
        "other_businesses_revenue": 29943, "other_businesses_profit": 4929,
    },
    2024: {
        "fv_effect": -2693,
        "segment_revenue": 83636,
        "segment_profit": 32359,
        "property_sales_revenue": 27422, "property_sales_profit": 7850,
        "property_rental_revenue": 24991, "property_rental_profit": 19000,
        "other_businesses_revenue": 31223, "other_businesses_profit": 5509,
    },
    2025: {
        "fv_effect": -2578,
        "segment_revenue": 90119,
        "segment_profit": 32188,
        "property_sales_revenue": 34556, "property_sales_profit": 8290,
        "property_rental_revenue": 24461, "property_rental_profit": 18392,
        "other_businesses_revenue": 31102, "other_businesses_profit": 5506,
    },
}


def build_shkp_historical_earnings_bridge() -> pd.DataFrame:
    """Assemble the 16-year group-level earnings bridge."""
    rows: list[dict[str, Any]] = []
    for fiscal_year in sorted(_GROUP_SUMMARY):
        g = _GROUP_SUMMARY[fiscal_year]
        s = _SEGMENT_SUMMARY.get(fiscal_year, {})
        underlying = float(g["underlying_profit"]) if g["underlying_profit"] is not None else None
        reported = float(g["profit_attributable"]) if g["profit_attributable"] is not None else None
        fv = float(s.get("fv_effect")) if s.get("fv_effect") is not None else None
        if fv is None and g.get("fv_effect_derived") is not None:
            fv = float(g["fv_effect_derived"])
        non_underlying = (reported - underlying) if underlying is not None and reported is not None else None
        rows.append(
            {
                "fiscal_year_end": fiscal_year,
                "fiscal_label": f"FY{fiscal_year - 1}/{str(fiscal_year)[-2:]}",
                "source_vintage": (
                    "ar_2014_15_group_financial_summary" if fiscal_year <= 2015
                    else "ar_2019_20_group_financial_summary" if fiscal_year <= 2020
                    else "ar_2024_25_five_year_financial_summary"
                ),
                "revenue_hkd_m": g["revenue"],
                "op_profit_pre_fv_hkd_m": g["op_profit_pre_fv"],
                "op_profit_post_fv_hkd_m": g["op_profit_post_fv"],
                "underlying_profit_hkd_m": underlying,
                "fv_effect_hkd_m": fv,
                "fv_effect_source": (
                    "five_year_summary_disclosed"
                    if s.get("fv_effect") is not None
                    else "derived_op_profit_pre_post_fv"
                    if g.get("fv_effect_derived") is not None
                    else None
                ),
                "non_underlying_items_hkd_m": non_underlying,
                "profit_attributable_hkd_m": reported,
                "reported_eps_hkd": g["reported_eps"],
                "underlying_eps_hkd": g["underlying_eps"],
                "dps_hkd": g["dps"],
                "segment_revenue_hkd_m": s.get("segment_revenue"),
                "segment_profit_hkd_m": s.get("segment_profit"),
                "property_sales_revenue_hkd_m": s.get("property_sales_revenue"),
                "property_sales_profit_hkd_m": s.get("property_sales_profit"),
                "property_rental_revenue_hkd_m": s.get("property_rental_revenue"),
                "property_rental_profit_hkd_m": s.get("property_rental_profit"),
                "other_businesses_revenue_hkd_m": s.get("other_businesses_revenue"),
                "other_businesses_profit_hkd_m": s.get("other_businesses_profit"),
                "model_use": "whole_company_historical_earnings_bridge",
                "research_only": True,
                "caveat": (
                    "Group financial summary items are all-region (HK + Mainland + Singapore) and are "
                    "the official source for the whole-company nowcast; HK-only segment detail is kept "
                    "in the residential/commercial module datasets. Underlying profit is the nowcast "
                    "target; reported profit is an accounting bridge (underlying + FV + other items). "
                    "Segment split by business line is available from FY2021 onward."
                ),
            }
        )
    return pd.DataFrame(rows)


def run_shkp_earnings_bridge() -> dict[str, Any]:
    """Persist the 16-year earnings bridge dataset."""
    run_id = f"shkp-earnings-bridge-{uuid.uuid4()}"
    bridge = build_shkp_historical_earnings_bridge()
    margin_rows = [
        {
            "fiscal_year_end": year,
            "fiscal_label": f"FY{year - 1}/{str(year)[-2:]}",
            "recognised_revenue_combined_hkd_m": values["revenue_combined"],
            "development_profit_combined_hkd_m": values["profit_combined"],
            "development_margin_pct": round(values["profit_combined"] / values["revenue_combined"] * 100.0, 2),
            "margin_definition": "hk_attributable_combined_development_profit_over_hk_recognised_property_sales",
            "model_use": "whole_company_development_margin_history",
            "research_only": True,
            "caveat": (
                "Frozen margin definition: HK attributable development profit (company + JV/associate "
                "share) / HK recognised property-sales revenue, from the segment note. Not the "
                "all-region five-year summary line. FY2025 profit excludes the Dynasty Court disposal "
                "(separate +2,220 underlying profit at 78% margin, disclosed in the annual report)."
            ),
        }
        for year, values in sorted(_HK_DEVELOPMENT_MARGIN.items())
    ]
    margin_history = pd.DataFrame(margin_rows)
    below_rows = [
        {
            "fiscal_year_end": year,
            "fiscal_label": f"FY{year - 1}/{str(year)[-2:]}",
            "mainland_development_revenue_hkd_m": values["dev_ml_rev"],
            "mainland_development_profit_hkd_m": values["dev_ml_res"],
            "mainland_rental_revenue_hkd_m": values["rent_ml_rev"],
            "mainland_rental_profit_hkd_m": values["rent_ml_res"],
            "singapore_rental_revenue_hkd_m": values["rent_sg_rev"],
            "singapore_rental_profit_hkd_m": values["rent_sg_res"],
            "mainland_singapore_combined_profit_hkd_m": (
                (values["dev_ml_res"] or 0) + (values["rent_ml_res"] or 0) + (values["rent_sg_res"] or 0)
            ),
            "model_use": "below_segment_geography_decomposition",
            "research_only": True,
            "caveat": (
                "Mainland/Singapore segment detail from the segment notes. FY2013 mainland development "
                "row absent (different table layout). These are the components the whole-company skeleton "
                "leaves inside its below-segment residual; explicit here for bridge completeness."
            ),
        }
        for year, values in sorted(_MAINLAND_SINGAPORE_SEGMENT.items())
    ]
    below_segment = pd.DataFrame(below_rows)
    hotel_rows = [
        {
            "fiscal_year_end": year,
            "fiscal_label": f"FY{year - 1}/{str(year)[-2:]}",
            "revenue_combined_hkd_m": values["revenue_combined"],
            "result_combined_hkd_m": values["result_combined"],
            "margin_pct": (
                round(values["result_combined"] / values["revenue_combined"] * 100.0, 2)
                if values["revenue_combined"]
                else None
            ),
            "source_section": "annual_report_segment_information_note",
            "model_use": "whole_company_hotel_segment_series",
            "research_only": True,
            "caveat": (
                "Hotel segment combined revenue/result (company + share of JV and associates). "
                "FY2011-2012 absent (different segment-table layout in those annual reports). "
                "Operating leverage is high: FY2020-22 COVID losses (-330 to -511) vs FY2019 peak "
                "1,433, then recovery to 615 by FY2025."
            ),
        }
        for year, values in sorted(_HOTEL_SEGMENT.items())
    ]
    hotel = pd.DataFrame(hotel_rows)
    lineage = {
        "lineage_type": "official_shkp_group_financial_summary_bridge",
        "run_id": run_id,
        "years": sorted(bridge["fiscal_year_end"].astype(int).tolist()),
        "vintages": sorted(bridge["source_vintage"].unique().tolist()),
        "ownership_promotion": False,
    }
    normalized = {
        BRIDGE_DATASET: save_normalized_dataset(
            BRIDGE_DATASET,
            bridge,
            run_id=run_id,
            source_urls=["https://www.shkp.com/en-US/investor-relations/financial-reports"],
            lineage_metadata={**lineage, "contract_dataset": BRIDGE_DATASET},
        ),
        HOTEL_DATASET: save_normalized_dataset(
            HOTEL_DATASET,
            hotel,
            run_id=run_id,
            source_urls=["https://www.shkp.com/en-US/investor-relations/financial-reports"],
            lineage_metadata={**lineage, "contract_dataset": HOTEL_DATASET},
        ),
        MARGIN_DATASET: save_normalized_dataset(
            MARGIN_DATASET,
            margin_history,
            run_id=run_id,
            source_urls=["https://www.shkp.com/en-US/investor-relations/financial-reports"],
            lineage_metadata={**lineage, "contract_dataset": MARGIN_DATASET},
        ),
        BELOW_SEGMENT_DATASET: save_normalized_dataset(
            BELOW_SEGMENT_DATASET,
            below_segment,
            run_id=run_id,
            source_urls=["https://www.shkp.com/en-US/investor-relations/financial-reports"],
            lineage_metadata={**lineage, "contract_dataset": BELOW_SEGMENT_DATASET},
        ),
    }
    return {
        "mode": "shkp_historical_earnings_bridge",
        "run_id": run_id,
        "rows": int(len(bridge)),
        "hotel_rows": int(len(hotel)),
        "margin_history_rows": int(len(margin_history)),
        "below_segment_rows": int(len(below_segment)),
        "years": sorted(bridge["fiscal_year_end"].astype(int).tolist()),
        "normalized": normalized,
    }
