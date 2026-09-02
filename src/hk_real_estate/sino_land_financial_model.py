"""Issuer-specific Sino Land (0083.HK) financial facts and bridge checks.

This module is deliberately an evidence layer, not a forecast engine.  It
keeps three things separate:

* ``official_facts`` are values transcribed from Sino Land's annual/interim
  reports, with the report page, HKEX/issuer URL, release timestamp and
  accounting scope retained;
* ``financial_data_actuals``/``consensus`` are supplemental rows from the
  sibling ``financial-data`` repository; and
* ``project_reconciliation`` compares the research-only SRPE contract-to-
  handover bridge with reported property-sales facts.  It never promotes
  contract value to accounting revenue.

The company reports operating segments on a Group basis, including the share
of associates and joint ventures.  They are therefore not Hong Kong-only
facts.  The geography and scope columns make that limitation explicit so a
future Hong Kong-only model cannot accidentally use a global segment number.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import uuid

import pandas as pd

from .shkp_financial_model import (
    FINANCIAL_DATA_DB_PATH,
    load_shkp_consensus,
    load_shkp_financial_data_actuals,
)
from .sino_residential_bridge import SCHEDULE_DATASET
from .storage import load_latest_normalized, save_normalized_dataset


SINO_LAND_TICKER = "0083.HK"

SINO_ANNUAL_REPORT_2023_URL = (
    "https://web-media.sino.com/20a53f0a-15c8-0029-b8df-e495023b403f/"
    "4b78aed8-b020-4e92-a612-0d1a5bbc3ed7/E_SL_Annual%20Report%202023.pdf"
)
SINO_ANNUAL_REPORT_2024_URL = (
    "https://www.hkexnews.hk/listedco/listconews/sehk/2024/0926/2024092601281.pdf"
)
SINO_ANNUAL_REPORT_2025_URL = (
    "https://web-media.sino.com/20a53f0a-15c8-0029-b8df-e495023b403f/"
    "c468acfe-1a59-4c93-9131-6eeba511b501/E_SL_Annual%20Report%202025.pdf"
)
SINO_INTERIM_REPORT_2025_26_URL = (
    "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0317/2026031700201.pdf"
)
SINO_HKEX_TITLE_SEARCH_URL = (
    "https://www1.hkexnews.hk/search/titlesearch.xhtml?category=0&lang=EN&"
    "market=SEHK&stockId=137"
)

OFFICIAL_FACT_DATASET = "sino_land_financial_model_official_facts"
ACTUALS_DATASET = "sino_land_financial_model_financial_data_actuals"
CONSENSUS_DATASET = "sino_land_financial_model_consensus"
RECONCILIATION_DATASET = "sino_land_financial_model_project_reconciliation"
QUALITY_DATASET = "sino_land_financial_model_quality"

SINO_OFFICIAL_FACT_COLUMNS = [
    "fact_id",
    "ticker",
    "report_id",
    "fact_group",
    "segment",
    "metric",
    "value",
    "value_operator",
    "unit",
    "currency",
    "period_start",
    "period_end",
    "period_type",
    "geography_scope",
    "attribution_scope",
    "accounting_basis",
    "source_label",
    "source_url",
    "source_page",
    "available_at",
    "availability_quality",
    "evidence_status",
    "model_use",
    "caveat",
]

SINO_PROJECT_RECONCILIATION_COLUMNS = [
    "reconciliation_id",
    "ticker",
    "fiscal_year_end",
    "reported_metric",
    "reported_value_hkd_m",
    "reported_scope",
    "bridge_schedule_rows",
    "bridge_value_low_hkd_m",
    "bridge_value_base_hkd_m",
    "bridge_value_high_hkd_m",
    "bridge_to_reported_base_pct",
    "coverage_status",
    "comparison_status",
    "model_use",
    "research_only",
    "source_datasets",
    "caveat",
]

SINO_QUALITY_COLUMNS = [
    "quality_id",
    "ticker",
    "layer",
    "check_name",
    "metric",
    "period_end",
    "observed_value",
    "threshold",
    "status",
    "model_use",
    "caveat",
]


# Segment figures are the ``Segment revenue`` and ``Segment results`` columns
# in the operating-segment note.  They include the Group's share of associates
# and JVs, so they intentionally differ from consolidated turnover.
_ANNUAL_SEGMENTS_HKD_M: dict[int, dict[str, tuple[float, float]]] = {
    2022: {
        "property_sales": (11282.035957, 5346.428246),
        "property_rental": (3570.608351, 3122.661692),
        "property_management_other_services": (1264.580560, 220.792597),
        "hotel_operations": (582.715120, 92.979553),
        "investments_securities": (26.763582, 26.763582),
        "financing": (68.143728, 68.143728),
    },
    2023: {
        "property_sales": (12058.459844, 3044.499391),
        "property_rental": (3529.420702, 3007.290921),
        "property_management_other_services": (1290.818245, 252.471760),
        "hotel_operations": (1375.531169, 451.784890),
        "investments_securities": (37.877533, 37.877533),
        "financing": (55.606509, 55.606509),
    },
    2024: {
        "property_sales": (9713.0, 802.0),
        "property_rental": (3572.0, 2928.0),
        "property_management_other_services": (1425.0, 239.0),
        "hotel_operations": (1527.0, 487.0),
        "investments_securities": (64.0, 64.0),
        "financing": (88.0, 88.0),
    },
    2025: {
        "property_sales": (10920.0, 1030.0),
        "property_rental": (3508.0, 2799.0),
        "property_management_other_services": (1528.0, 268.0),
        "hotel_operations": (1506.0, 475.0),
        "investments_securities": (68.0, 68.0),
        "financing": (98.0, 98.0),
    },
}

_INTERIM_SEGMENTS_HKD_M: dict[str, dict[str, tuple[float, float]]] = {
    "2025-12-31": {
        "property_sales": (6912.0, 495.0),
        "property_rental": (1718.0, 1364.0),
        "property_management_other_services": (792.0, 141.0),
        "hotel_operations": (822.0, 289.0),
        "investments_securities": (26.0, 26.0),
        "financing": (38.0, 38.0),
    },
    "2024-12-31": {
        "property_sales": (2544.0, 151.0),
        "property_rental": (1759.0, 1385.0),
        "property_management_other_services": (760.0, 143.0),
        "hotel_operations": (794.0, 261.0),
        "investments_securities": (18.0, 18.0),
        "financing": (57.0, 57.0),
    },
}

_ANNUAL_GROUP_SUMMARY_HKD_M: dict[int, dict[str, float]] = {
    2020: {
        "turnover": 5887.0,
        "underlying_profit_attributable": 4557.0,
        "profit_attributable": 1688.0,
        "underlying_eps": 0.65,
        "reported_eps": 0.24,
    },
    2021: {
        "turnover": 24545.0,
        "underlying_profit_attributable": 10316.0,
        "profit_attributable": 9646.0,
        "underlying_eps": 1.42,
        "reported_eps": 1.33,
    },
    2022: {
        "turnover": 15554.0,
        "underlying_profit_attributable": 6531.0,
        "profit_attributable": 5735.0,
        "underlying_eps": 0.86,
        "reported_eps": 0.76,
    },
    2023: {
        "turnover": 11881.0,
        "underlying_profit_attributable": 6088.0,
        "profit_attributable": 5849.0,
        "underlying_eps": 0.76,
        "reported_eps": 0.73,
    },
    2024: {
        "turnover": 8765.0,
        "underlying_profit_attributable": 5171.0,
        "profit_attributable": 4402.0,
        "underlying_eps": 0.61,
        "reported_eps": 0.52,
    },
    2025: {
        "turnover": 8183.0,
        "underlying_profit_attributable": 5118.0,
        "profit_attributable": 4019.0,
        "underlying_eps": 0.58,
        "reported_eps": 0.45,
    },
}

_ANNUAL_SOURCE = {
    # HKEX search evidence confirms the publication date for the 2023 PDF;
    # its exact release time is intentionally not fabricated.
    2022: (
        "sino_ar_2023",
        SINO_ANNUAL_REPORT_2023_URL,
        "2023-09-28",
        "Annual Report 2023",
    ),
    2023: (
        "sino_ar_2023",
        SINO_ANNUAL_REPORT_2023_URL,
        "2023-09-28",
        "Annual Report 2023",
    ),
    2024: (
        "sino_ar_2024",
        SINO_ANNUAL_REPORT_2024_URL,
        "2024-09-26T17:16:00+08:00",
        "Annual Report 2024",
    ),
    2025: (
        "sino_ar_2025",
        SINO_ANNUAL_REPORT_2025_URL,
        "2025-09-25T17:32:00+08:00",
        "Annual Report 2025",
    ),
}

# Annual-report Note 6 geography table.  The issuer combines Mainland China
# with Hong Kong, and Singapore with Australia; these rows are useful scope
# controls but must never be relabelled as Hong Kong-only revenue.
_ANNUAL_GEOGRAPHY_HKD_M: dict[int, dict[str, dict[str, float]]] = {
    2022: {
        "mainland_china_and_hong_kong": {
            "external_revenue_by_geography": 15035.734799,
            "share_of_revenue_from_associates_and_joint_ventures_by_geography": 1167.123966,
            "non_current_assets_by_geography": 84715.804116,
        },
        "singapore_and_australia": {
            "external_revenue_by_geography": 518.439771,
            "share_of_revenue_from_associates_and_joint_ventures_by_geography": 73.548762,
            "non_current_assets_by_geography": 3768.056133,
        },
    },
    2023: {
        "mainland_china_and_hong_kong": {
            "external_revenue_by_geography": 10906.997012,
            "share_of_revenue_from_associates_and_joint_ventures_by_geography": 6279.620901,
            "non_current_assets_by_geography": 87658.164874,
        },
        "singapore_and_australia": {
            "external_revenue_by_geography": 974.288251,
            "share_of_revenue_from_associates_and_joint_ventures_by_geography": 186.807838,
            "non_current_assets_by_geography": 4902.939912,
        },
    },
    2024: {
        "mainland_china_and_hong_kong": {
            "external_revenue_by_geography": 7724.0,
            "share_of_revenue_from_associates_and_joint_ventures_by_geography": 7422.0,
            "non_current_assets_by_geography": 87590.0,
        },
        "singapore_and_australia": {
            "external_revenue_by_geography": 1041.0,
            "share_of_revenue_from_associates_and_joint_ventures_by_geography": 202.0,
            "non_current_assets_by_geography": 4945.0,
        },
    },
    2025: {
        "mainland_china_and_hong_kong": {
            "external_revenue_by_geography": 7147.0,
            "share_of_revenue_from_associates_and_joint_ventures_by_geography": 9263.0,
            "non_current_assets_by_geography": 87460.0,
        },
        "singapore_and_australia": {
            "external_revenue_by_geography": 1036.0,
            "share_of_revenue_from_associates_and_joint_ventures_by_geography": 182.0,
            "non_current_assets_by_geography": 5531.0,
        },
    },
}

_ANNUAL_GEOGRAPHY_PAGE = {2022: "175", 2023: "175", 2024: "171", 2025: "179"}


def _availability_quality(report_id: str) -> str:
    return (
        "hkex_release_date_verified_time_unverified"
        if report_id == "sino_ar_2023"
        else "hkex_release_time_verified"
    )


def _fact_id(*parts: Any) -> str:
    return "sino_land:" + ":".join(
        str(part).strip().lower().replace(" ", "_") for part in parts
    )


def _fact(
    *,
    report_id: str,
    fact_group: str,
    segment: str | None,
    metric: str,
    value: float,
    unit: str,
    period_start: str,
    period_end: str,
    period_type: str,
    geography_scope: str,
    attribution_scope: str,
    accounting_basis: str,
    source_label: str,
    source_url: str,
    source_page: str,
    available_at: str,
    availability_quality: str,
    caveat: str,
    value_operator: str = "=",
    model_use: str = "research_input_pending_reconciliation",
) -> dict[str, Any]:
    return {
        "fact_id": _fact_id(
            report_id, period_end, segment or "group", geography_scope, metric
        ),
        "ticker": SINO_LAND_TICKER,
        "report_id": report_id,
        "fact_group": fact_group,
        "segment": segment,
        "metric": metric,
        "value": value,
        "value_operator": value_operator,
        "unit": unit,
        "currency": "HKD" if unit != "pct" else None,
        "period_start": period_start,
        "period_end": period_end,
        "period_type": period_type,
        "geography_scope": geography_scope,
        "attribution_scope": attribution_scope,
        "accounting_basis": accounting_basis,
        "source_label": source_label,
        "source_url": source_url,
        "source_page": source_page,
        "available_at": available_at,
        "availability_quality": availability_quality,
        "evidence_status": "observed_official_report",
        "model_use": model_use,
        "caveat": caveat,
    }


def _annual_segment_facts(rows: list[dict[str, Any]]) -> None:
    for fiscal_year, segments in _ANNUAL_SEGMENTS_HKD_M.items():
        report_id, url, available_at, label = _ANNUAL_SOURCE[fiscal_year]
        period_start = f"{fiscal_year - 1}-07-01"
        period_end = f"{fiscal_year}-06-30"
        for segment, (revenue, result) in segments.items():
            segment_label = segment.replace("_", " ")
            for metric, value in (
                ("segment_revenue", revenue),
                ("segment_result", result),
            ):
                rows.append(
                    _fact(
                        report_id=report_id,
                        fact_group="operating_segments",
                        segment=segment,
                        metric=metric,
                        value=value,
                        unit="HKD_m",
                        period_start=period_start,
                        period_end=period_end,
                        period_type="annual",
                        geography_scope="group_all_geographies",
                        attribution_scope="company_and_subsidiaries_plus_share_of_associates_and_joint_ventures",
                        accounting_basis="reported_operating_segment",
                        source_label=label,
                        source_url=url,
                        source_page=(
                            "171-172"
                            if fiscal_year == 2022
                            else (
                                "171"
                                if fiscal_year == 2023
                                else "165" if fiscal_year == 2024 else "173"
                            )
                        ),
                        available_at=available_at,
                        availability_quality=_availability_quality(report_id),
                        caveat=(
                            f"Official {segment_label} segment {metric.replace('_', ' ')}; includes associates/JVs and all reported geographies. "
                            "It is not consolidated turnover and is not Hong Kong-only."
                        ),
                    )
                )

        segment_total_revenue = sum(value[0] for value in segments.values())
        segment_total_result = sum(value[1] for value in segments.values())
        for metric, value in (
            ("segment_revenue_total", segment_total_revenue),
            ("segment_result_total", segment_total_result),
        ):
            rows.append(
                _fact(
                    report_id=report_id,
                    fact_group="operating_segments",
                    segment="group_segment_total",
                    metric=metric,
                    value=round(value, 6),
                    unit="HKD_m",
                    period_start=period_start,
                    period_end=period_end,
                    period_type="annual",
                    geography_scope="group_all_geographies",
                    attribution_scope="company_and_subsidiaries_plus_share_of_associates_and_joint_ventures",
                    accounting_basis="reported_operating_segment",
                    source_label=label,
                    source_url=url,
                    source_page=(
                        "171-172"
                        if fiscal_year == 2022
                        else (
                            "171"
                            if fiscal_year == 2023
                            else "165" if fiscal_year == 2024 else "173"
                        )
                    ),
                    available_at=available_at,
                    availability_quality=_availability_quality(report_id),
                    caveat="Sum of the six reported operating segments; do not compare directly with consolidated turnover without accounting-scope adjustment.",
                )
            )


def _annual_group_facts(rows: list[dict[str, Any]]) -> None:
    for fiscal_year, metrics in _ANNUAL_GROUP_SUMMARY_HKD_M.items():
        if fiscal_year >= 2022:
            report_id, url, available_at, label = _ANNUAL_SOURCE[fiscal_year]
        elif fiscal_year == 2020 or fiscal_year == 2021:
            report_id, url, available_at, label = (
                "sino_ar_2024",
                SINO_ANNUAL_REPORT_2024_URL,
                "2024-09-26T17:16:00+08:00",
                "Annual Report 2024",
            )
        period_start = f"{fiscal_year - 1}-07-01"
        period_end = f"{fiscal_year}-06-30"
        for metric, value in metrics.items():
            unit = (
                "HKD_m"
                if metric not in {"underlying_eps", "reported_eps"}
                else "HKD_per_share"
            )
            rows.append(
                _fact(
                    report_id=report_id,
                    fact_group="group_summary",
                    segment=None,
                    metric=metric,
                    value=value,
                    unit=unit,
                    period_start=period_start,
                    period_end=period_end,
                    period_type="annual",
                    geography_scope="group_all_geographies",
                    attribution_scope=(
                        "company_shareholders"
                        if "profit" in metric or "eps" in metric
                        else "consolidated_group"
                    ),
                    accounting_basis="reported_group_summary",
                    source_label=label,
                    source_url=url,
                    source_page="3-4",
                    available_at=available_at,
                    availability_quality=(
                        _availability_quality(report_id)
                        if fiscal_year >= 2022
                        else "current_summary_historical_value"
                    ),
                    caveat=(
                        "Current annual-report five-year summary; it is a historical value, not an original first-available vintage."
                        if fiscal_year < 2022
                        else "Official group financial-summary value."
                    ),
                    model_use="reported_actual_context",
                )
            )


def _annual_narrative_facts(rows: list[dict[str, Any]]) -> None:
    # These numbers are explicitly called out in the Chairman's business
    # review and are intentionally kept separate from the segment-note totals.
    narrative = {
        2022: {
            "reported_property_sales_activity_revenue": 10841.8,
            "gross_rental_revenue": 3546.1,
            "net_rental_income": 3101.6,
            "investment_property_occupancy": 90.8,
            "hotel_revenue_attributable": 582.7,
            "hotel_operating_profit_attributable": 92.9,
        },
        2023: {
            "reported_property_sales_activity_revenue": 11937.3,
            "gross_rental_revenue": 3504.8,
            "net_rental_income": 2985.7,
            "investment_property_occupancy": 91.2,
            "hotel_revenue_attributable": 1375.5,
            "hotel_operating_profit_attributable": 451.7,
        },
        2024: {
            "reported_property_sales_activity_revenue": 8893.0,
            "gross_rental_revenue": 3550.0,
            "net_rental_income": 2910.0,
            "investment_property_occupancy": 90.8,
            "hotel_revenue_attributable": 1527.0,
            "hotel_operating_profit_attributable": 487.0,
        },
        2025: {
            "reported_property_sales_activity_revenue": 10813.0,
            "gross_rental_revenue": 3486.0,
            "net_rental_income": 2782.0,
            "investment_property_occupancy": 92.6,
            "hotel_revenue_attributable": 1506.0,
            "hotel_operating_profit_attributable": 475.0,
        },
    }
    page_by_year = {
        2022: {
            "reported_property_sales_activity_revenue": "8",
            "gross_rental_revenue": "14",
            "net_rental_income": "14",
            "investment_property_occupancy": "14",
            "hotel_revenue_attributable": "15",
            "hotel_operating_profit_attributable": "15",
        },
        2023: {
            "reported_property_sales_activity_revenue": "8",
            "gross_rental_revenue": "14",
            "net_rental_income": "14",
            "investment_property_occupancy": "14",
            "hotel_revenue_attributable": "15",
            "hotel_operating_profit_attributable": "15",
        },
        2024: {
            "reported_property_sales_activity_revenue": "8",
            "gross_rental_revenue": "12",
            "net_rental_income": "12",
            "investment_property_occupancy": "12",
            "hotel_revenue_attributable": "13",
            "hotel_operating_profit_attributable": "13",
        },
        2025: {
            "reported_property_sales_activity_revenue": "8",
            "gross_rental_revenue": "13",
            "net_rental_income": "13",
            "investment_property_occupancy": "13",
            "hotel_revenue_attributable": "14",
            "hotel_operating_profit_attributable": "14",
        },
    }
    for fiscal_year, metrics in narrative.items():
        report_id, url, available_at, label = _ANNUAL_SOURCE[fiscal_year]
        period_start = f"{fiscal_year - 1}-07-01"
        period_end = f"{fiscal_year}-06-30"
        for metric, value in metrics.items():
            unit = "pct" if metric.endswith("occupancy") else "HKD_m"
            rows.append(
                _fact(
                    report_id=report_id,
                    fact_group="business_review_narrative",
                    segment=(
                        "property_sales"
                        if "property_sales" in metric
                        else (
                            "property_rental"
                            if "rental" in metric or "occupancy" in metric
                            else "hotel_operations"
                        )
                    ),
                    metric=metric,
                    value=value,
                    unit=unit,
                    period_start=period_start,
                    period_end=period_end,
                    period_type="annual",
                    geography_scope="group_all_geographies",
                    attribution_scope="attributable_group_including_associates_and_joint_ventures",
                    accounting_basis="chairman_business_review_narrative",
                    source_label=label,
                    source_url=url,
                    source_page=page_by_year[fiscal_year][metric],
                    available_at=available_at,
                    availability_quality=_availability_quality(report_id),
                    caveat=(
                        "Business-review attributable figure across reported geographies; it is intentionally not treated as identical to the operating-segment-note total and is not Hong Kong-only."
                        if metric == "reported_property_sales_activity_revenue"
                        else "Business-review attributable group figure across reported geographies; not Hong Kong-only."
                    ),
                    model_use="reported_actual_context",
                )
            )


def _annual_geographical_facts(rows: list[dict[str, Any]]) -> None:
    """Append Note 6 annual geography rows without implying HK-only scope."""
    for fiscal_year, geographies in _ANNUAL_GEOGRAPHY_HKD_M.items():
        report_id, url, available_at, label = _ANNUAL_SOURCE[fiscal_year]
        period_start = f"{fiscal_year - 1}-07-01"
        period_end = f"{fiscal_year}-06-30"
        for geography, metrics in geographies.items():
            for metric, value in metrics.items():
                attribution_scope = (
                    "consolidated_external_revenue"
                    if metric == "external_revenue_by_geography"
                    else (
                        "share_of_associates_and_joint_ventures_revenue"
                        if metric.startswith("share_of_revenue")
                        else "consolidated_non_current_assets"
                    )
                )
                rows.append(
                    _fact(
                        report_id=report_id,
                        fact_group="geographical_revenue",
                        segment=None,
                        metric=metric,
                        value=value,
                        unit="HKD_m",
                        period_start=period_start,
                        period_end=period_end,
                        period_type="annual",
                        geography_scope=geography,
                        attribution_scope=attribution_scope,
                        accounting_basis="operating_segment_geographical_information",
                        source_label=label,
                        source_url=url,
                        source_page=_ANNUAL_GEOGRAPHY_PAGE[fiscal_year],
                        available_at=available_at,
                        availability_quality=_availability_quality(report_id),
                        caveat=(
                            "Annual geography table combines Mainland China and Hong Kong; it is not a Hong Kong-only measure."
                            if geography == "mainland_china_and_hong_kong"
                            else "Annual geography table combines Singapore and Australia; it is not a standalone country measure."
                        ),
                        model_use="geography_scope_control",
                    )
                )


def _interim_facts(rows: list[dict[str, Any]]) -> None:
    for period_end, segments in _INTERIM_SEGMENTS_HKD_M.items():
        report_id = "sino_ir_2025_26"
        period_start = "2025-07-01" if period_end == "2025-12-31" else "2024-07-01"
        available_at = "2026-03-17T12:11:00+08:00"
        quality = (
            "hkex_release_time_verified"
            if period_end == "2025-12-31"
            else "comparative_in_later_report_not_original_vintage"
        )
        for segment, (revenue, result) in segments.items():
            for metric, value in (
                ("segment_revenue", revenue),
                ("segment_result", result),
            ):
                rows.append(
                    _fact(
                        report_id=report_id,
                        fact_group="operating_segments",
                        segment=segment,
                        metric=metric,
                        value=value,
                        unit="HKD_m",
                        period_start=period_start,
                        period_end=period_end,
                        period_type="interim",
                        geography_scope="group_all_geographies",
                        attribution_scope="company_and_subsidiaries_plus_share_of_associates_and_joint_ventures",
                        accounting_basis="reported_operating_segment",
                        source_label="2025-2026 Interim Report",
                        source_url=SINO_INTERIM_REPORT_2025_26_URL,
                        source_page="33-34",
                        available_at=available_at,
                        availability_quality=quality,
                        caveat="Interim segment fact includes associates/JVs and all reported geographies; not Hong Kong-only.",
                        model_use="reported_actual_context",
                    )
                )

        rows.append(
            _fact(
                report_id=report_id,
                fact_group="group_summary",
                segment=None,
                metric="consolidated_revenue",
                value=5185.0 if period_end == "2025-12-31" else 3854.0,
                unit="HKD_m",
                period_start=period_start,
                period_end=period_end,
                period_type="interim",
                geography_scope="group_all_geographies",
                attribution_scope="consolidated_group",
                accounting_basis="consolidated_revenue_note",
                source_label="2025-2026 Interim Report",
                source_url=SINO_INTERIM_REPORT_2025_26_URL,
                source_page="32",
                available_at=available_at,
                availability_quality=quality,
                caveat="Consolidated external revenue; unlike segment revenue it excludes the Group's share of associates/JVs.",
                model_use="reported_actual_context",
            )
        )
        for metric, value in {
            "sales_of_properties": 2543.0 if period_end == "2025-12-31" else 1212.0,
            "rental_income_operating_leases": (
                1337.0 if period_end == "2025-12-31" else 1378.0
            ),
            "hotel_operations_revenue": 515.0 if period_end == "2025-12-31" else 495.0,
            "underlying_profit_attributable": (
                2220.0 if period_end == "2025-12-31" else 2241.0
            ),
            "profit_attributable": 1533.0 if period_end == "2025-12-31" else 1820.0,
        }.items():
            rows.append(
                _fact(
                    report_id=report_id,
                    fact_group="interim_actuals",
                    segment=(
                        "property_sales"
                        if metric == "sales_of_properties"
                        else (
                            "property_rental"
                            if metric == "rental_income_operating_leases"
                            else (
                                "hotel_operations"
                                if metric == "hotel_operations_revenue"
                                else None
                            )
                        )
                    ),
                    metric=metric,
                    value=value,
                    unit="HKD_m",
                    period_start=period_start,
                    period_end=period_end,
                    period_type="interim",
                    geography_scope="group_all_geographies",
                    attribution_scope=(
                        "consolidated_group"
                        if metric
                        in {
                            "sales_of_properties",
                            "rental_income_operating_leases",
                            "hotel_operations_revenue",
                        }
                        else "company_shareholders"
                    ),
                    accounting_basis="consolidated_interim_statement",
                    source_label="2025-2026 Interim Report",
                    source_url=SINO_INTERIM_REPORT_2025_26_URL,
                    source_page="4,32",
                    available_at=available_at,
                    availability_quality=quality,
                    caveat=(
                        "Consolidated/interim statement fact; do not compare directly with segment revenue that includes associates/JVs."
                        if metric
                        in {
                            "sales_of_properties",
                            "rental_income_operating_leases",
                            "hotel_operations_revenue",
                        }
                        else "Company-reported profit measure."
                    ),
                    model_use="reported_actual_context",
                )
            )
        for geography, value in {
            "hong_kong": 4488.0 if period_end == "2025-12-31" else 3237.0,
            "chinese_mainland": 140.0 if period_end == "2025-12-31" else 80.0,
            "singapore": 557.0 if period_end == "2025-12-31" else 537.0,
        }.items():
            rows.append(
                _fact(
                    report_id=report_id,
                    fact_group="geographical_revenue",
                    segment=None,
                    metric="consolidated_external_revenue_by_geography",
                    value=value,
                    unit="HKD_m",
                    period_start=period_start,
                    period_end=period_end,
                    period_type="interim",
                    geography_scope=geography,
                    attribution_scope="consolidated_external_revenue",
                    accounting_basis="revenue_note_geographical_market",
                    source_label="2025-2026 Interim Report",
                    source_url=SINO_INTERIM_REPORT_2025_26_URL,
                    source_page="32",
                    available_at=available_at,
                    availability_quality=quality,
                    caveat="This is consolidated external revenue by market, not segment revenue and not attributable JV revenue.",
                    model_use="hk_scope_control",
                )
            )


def build_sino_land_financial_facts() -> pd.DataFrame:
    """Return deterministic official Sino Land facts with full provenance."""
    rows: list[dict[str, Any]] = []
    _annual_segment_facts(rows)
    _annual_group_facts(rows)
    _annual_narrative_facts(rows)
    _annual_geographical_facts(rows)
    _interim_facts(rows)
    frame = pd.DataFrame(rows, columns=SINO_OFFICIAL_FACT_COLUMNS)
    if frame.empty:
        return frame
    frame["period_end"] = pd.to_datetime(
        frame["period_end"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    return frame.sort_values(
        ["period_end", "fact_group", "segment", "metric"], na_position="last"
    ).reset_index(drop=True)


def load_sino_land_financial_data_actuals(
    db_path: Path = FINANCIAL_DATA_DB_PATH,
) -> pd.DataFrame:
    """Load normalized 0083 actuals without changing their source semantics."""
    return load_shkp_financial_data_actuals(
        db_path=Path(db_path), ticker=SINO_LAND_TICKER
    )


def load_sino_land_consensus(db_path: Path = FINANCIAL_DATA_DB_PATH) -> pd.DataFrame:
    """Load the current 0083 consensus snapshot; it is not a historical PIT panel."""
    return load_shkp_consensus(db_path=Path(db_path), ticker=SINO_LAND_TICKER)


def _fiscal_year_end(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    year = int(parsed.year) + (1 if int(parsed.month) > 6 else 0)
    return f"{year}-06-30"


def build_sino_land_project_reconciliation(
    bridge_schedule: pd.DataFrame | None,
    official_facts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Compare research bridge cohorts with reported property-sales facts.

    The output is a diagnostic comparison.  A bridge value is a contract
    cohort multiplied by an assumed/observed stake and lag; it is never
    labelled as accounting revenue.  Both the business-review property-sales
    number and the operating-segment-note number are retained because the
    reports themselves present different scopes.
    """
    facts = (
        official_facts.copy()
        if official_facts is not None
        else build_sino_land_financial_facts()
    )
    schedule = bridge_schedule.copy() if bridge_schedule is not None else pd.DataFrame()
    if not facts.empty and "period_end" in facts:
        facts["period_end"] = pd.to_datetime(
            facts["period_end"], errors="coerce"
        ).dt.strftime("%Y-%m-%d")
    reported = facts.loc[
        facts["period_type"].eq("annual")
        & facts["metric"].isin(
            {"reported_property_sales_activity_revenue", "segment_revenue"}
        )
        & facts["segment"].isin({"property_sales"}),
    ].copy()
    if reported.empty:
        return pd.DataFrame(columns=SINO_PROJECT_RECONCILIATION_COLUMNS)
    if schedule.empty:
        schedule = pd.DataFrame(
            columns=[
                "recognized_period_low",
                "recognized_period_base",
                "recognized_period_high",
                "attributable_contract_value_low_hkd",
                "attributable_contract_value_base_hkd",
                "attributable_contract_value_high_hkd",
            ]
        )
    for column in [
        "recognized_period_low",
        "recognized_period_base",
        "recognized_period_high",
    ]:
        if column not in schedule:
            schedule[column] = pd.NaT
        schedule[column] = pd.to_datetime(schedule[column], errors="coerce")
    for column in [
        "attributable_contract_value_low_hkd",
        "attributable_contract_value_base_hkd",
        "attributable_contract_value_high_hkd",
    ]:
        if column not in schedule:
            schedule[column] = 0.0
        schedule[column] = pd.to_numeric(schedule[column], errors="coerce").fillna(0.0)
    scenario_fiscal: dict[str, pd.Series] = {}
    for scenario in ("low", "base", "high"):
        period_col = f"recognized_period_{scenario}"
        value_col = f"attributable_contract_value_{scenario}_hkd"
        if schedule.empty:
            scenario_fiscal[scenario] = pd.Series(dtype=float)
            continue
        temp = schedule[[period_col, value_col]].copy()
        temp["fiscal_year_end"] = temp[period_col].map(_fiscal_year_end)
        scenario_fiscal[scenario] = temp.groupby("fiscal_year_end")[value_col].sum(
            min_count=1
        )

    rows: list[dict[str, Any]] = []
    for _, reported_row in reported.sort_values(["period_end", "metric"]).iterrows():
        fiscal_year_end = str(reported_row["period_end"])
        base_value = float(reported_row["value"])
        bridge_values = {
            scenario: float(series.get(fiscal_year_end, 0.0))
            for scenario, series in scenario_fiscal.items()
        }
        schedule_rows = 0
        if not schedule.empty:
            schedule_rows = int(
                schedule[
                    schedule["recognized_period_base"]
                    .map(_fiscal_year_end)
                    .eq(fiscal_year_end)
                ].shape[0]
            )
        coverage_status = (
            "bridge_observed_for_period"
            if schedule_rows
            else "bridge_not_observed_for_period"
        )
        comparison_status = (
            "diagnostic_only_scope_mismatch_possible"
            if reported_row["metric"] == "reported_property_sales_activity_revenue"
            else "diagnostic_only_segment_scope_includes_jvs"
        )
        rows.append(
            {
                "reconciliation_id": _fact_id(
                    "reconciliation", fiscal_year_end, reported_row["metric"]
                ),
                "ticker": SINO_LAND_TICKER,
                "fiscal_year_end": fiscal_year_end,
                "reported_metric": reported_row["metric"],
                "reported_value_hkd_m": base_value,
                "reported_scope": reported_row.get("attribution_scope"),
                "bridge_schedule_rows": schedule_rows,
                "bridge_value_low_hkd_m": bridge_values["low"] / 1_000_000.0,
                "bridge_value_base_hkd_m": bridge_values["base"] / 1_000_000.0,
                "bridge_value_high_hkd_m": bridge_values["high"] / 1_000_000.0,
                "bridge_to_reported_base_pct": (
                    ((bridge_values["base"] / 1_000_000.0) / base_value * 100.0)
                    if base_value
                    else None
                ),
                "coverage_status": coverage_status,
                "comparison_status": comparison_status,
                "model_use": "research_only_diagnostic_not_accounting_reconciliation",
                "research_only": True,
                "source_datasets": json.dumps(
                    [OFFICIAL_FACT_DATASET, SCHEDULE_DATASET], ensure_ascii=False
                ),
                "caveat": "SRPE contract cohorts and estimated recognition lag/stake are not accounting revenue; differences are coverage/scope diagnostics, not an earnings error.",
            }
        )
    return pd.DataFrame(rows, columns=SINO_PROJECT_RECONCILIATION_COLUMNS)


def build_sino_land_financial_quality(
    official_facts: pd.DataFrame,
    financial_data_actuals: pd.DataFrame | None = None,
    project_reconciliation: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Run explicit, lightweight quality gates for the Sino input contract."""
    facts = (
        official_facts.copy()
        if official_facts is not None
        else pd.DataFrame(columns=SINO_OFFICIAL_FACT_COLUMNS)
    )
    actuals = (
        financial_data_actuals.copy()
        if financial_data_actuals is not None
        else pd.DataFrame()
    )
    recon = (
        project_reconciliation.copy()
        if project_reconciliation is not None
        else pd.DataFrame()
    )
    rows: list[dict[str, Any]] = []

    def add(
        layer: str,
        name: str,
        metric: str,
        value: Any,
        threshold: Any,
        status: str,
        use: str,
        caveat: str,
        period_end: str | None = None,
    ) -> None:
        rows.append(
            {
                "quality_id": _fact_id(
                    "quality", layer, name, metric, period_end or "all"
                ),
                "ticker": SINO_LAND_TICKER,
                "layer": layer,
                "check_name": name,
                "metric": metric,
                "period_end": period_end,
                "observed_value": value,
                "threshold": threshold,
                "status": status,
                "model_use": use,
                "caveat": caveat,
            }
        )

    if facts.empty:
        add(
            "official_facts",
            "non_empty",
            "fact_rows",
            0,
            ">0",
            "fail",
            "do_not_use",
            "No official facts were built.",
        )
    else:
        required = ["source_url", "source_page", "available_at", "period_end", "value"]
        missing_pct = float(facts[required].isna().any(axis=1).mean() * 100.0)
        add(
            "official_facts",
            "provenance_completeness",
            "rows_missing_required_provenance_pct",
            missing_pct,
            "0",
            "pass" if missing_pct == 0 else "warn",
            "source_backed_context_only",
            "Every official row must retain source URL/page/release timestamp; a warning blocks PIT promotion.",
        )
        duplicate_count = int(facts["fact_id"].duplicated().sum())
        add(
            "official_facts",
            "duplicate_fact_ids",
            "duplicate_rows",
            duplicate_count,
            "0",
            "pass" if duplicate_count == 0 else "fail",
            "do_not_use" if duplicate_count else "source_backed_context_only",
            "Duplicate fact IDs make a snapshot ambiguous.",
        )
        numeric = pd.to_numeric(facts["value"], errors="coerce")
        negative_count = int(
            (
                (numeric < 0)
                & ~facts["metric"].isin(
                    {
                        "segment_result",
                        "segment_result_total",
                        "profit_attributable",
                        "underlying_profit_attributable",
                    }
                )
            ).sum()
        )
        add(
            "official_facts",
            "non_negative_revenue_metrics",
            "negative_rows",
            negative_count,
            "0",
            "pass" if negative_count == 0 else "warn",
            "source_backed_context_only",
            "Negative revenue/occupancy rows would indicate a transcription or semantic error.",
        )
        global_scope_count = int(
            facts["geography_scope"].eq("group_all_geographies").sum()
        )
        add(
            "official_facts",
            "hk_scope_guard",
            "global_scope_rows",
            global_scope_count,
            ">=0",
            "warn",
            "do_not_use_as_hk_only",
            "Most Sino segment facts are global. They must not be used as Hong Kong-only drivers without an explicit geography bridge.",
        )

    if actuals.empty:
        add(
            "financial_data_actuals",
            "availability",
            "actual_rows",
            0,
            ">0",
            "warn",
            "no_actual_source",
            "0083 financial-data actuals are unavailable in this environment.",
        )
    else:
        announcement_coverage = (
            float(
                actuals.get("announcement_date", pd.Series(index=actuals.index))
                .notna()
                .mean()
                * 100.0
            )
            if "announcement_date" in actuals
            else 0.0
        )
        add(
            "financial_data_actuals",
            "announcement_date_coverage",
            "announcement_date_pct",
            announcement_coverage,
            "100",
            "pass" if announcement_coverage == 100.0 else "warn",
            "not_pit_clean",
            "Fetched/available timestamps are not original release dates when announcement_date is missing.",
        )
        if {"source", "metric", "period_end", "value"}.issubset(actuals.columns):
            annual = (
                actuals[
                    actuals.get("period_type", pd.Series(index=actuals.index))
                    .astype(str)
                    .str.casefold()
                    .eq("annual")
                ]
                if "period_type" in actuals
                else actuals
            )
            conflicts = 0
            for (metric, period_end), group in annual.groupby(
                ["metric", "period_end"], dropna=False
            ):
                source_values = (
                    group.assign(_value=pd.to_numeric(group["value"], errors="coerce"))
                    .dropna(subset=["_value"])
                    .groupby("source", dropna=False)["_value"]
                    .median()
                )
                if source_values.size >= 2 and float(source_values.max()) != 0:
                    if (
                        abs(
                            float(source_values.max() - source_values.min())
                            / float(source_values.max())
                        )
                        > 0.005
                    ):
                        conflicts += 1
            add(
                "financial_data_actuals",
                "source_overlap_conflicts",
                "metric_period_conflict_groups",
                conflicts,
                "0",
                "pass" if conflicts == 0 else "warn",
                "manual_source_reconciliation_required",
                "Overlapping vendor rows differ; do not sum sources or silently choose one without issuer reconciliation.",
            )

    if recon.empty:
        add(
            "project_reconciliation",
            "bridge_snapshot",
            "reconciliation_rows",
            0,
            ">0",
            "warn",
            "no_bridge_reconciliation",
            "No Sino project bridge snapshot was available; reported facts remain usable as standalone context.",
        )
    else:
        non_research = (
            int((~recon["research_only"].fillna(False).astype(bool)).sum())
            if "research_only" in recon
            else len(recon)
        )
        add(
            "project_reconciliation",
            "research_only_guard",
            "non_research_rows",
            non_research,
            "0",
            "pass" if non_research == 0 else "fail",
            "do_not_use" if non_research else "research_only_diagnostic",
            "Project contract cohorts must never be promoted to accounting revenue.",
        )
        observed = (
            int(recon["coverage_status"].eq("bridge_observed_for_period").sum())
            if "coverage_status" in recon
            else 0
        )
        add(
            "project_reconciliation",
            "bridge_period_coverage",
            "observed_period_rows",
            observed,
            ">=0",
            "pass",
            "research_only_diagnostic",
            "A zero count is an explicit coverage gap, not a zero-sales assertion.",
        )
    return pd.DataFrame(rows, columns=SINO_QUALITY_COLUMNS)


def build_sino_land_financial_model_inputs(
    *,
    db_path: Path = FINANCIAL_DATA_DB_PATH,
    bridge_schedule: pd.DataFrame | None = None,
    load_financial_data: bool = True,
) -> dict[str, pd.DataFrame]:
    """Build facts, optional sibling-repo rows, bridge comparison and QA."""
    official = build_sino_land_financial_facts()
    actuals = pd.DataFrame()
    consensus = pd.DataFrame()
    if load_financial_data:
        actuals = load_sino_land_financial_data_actuals(db_path)
        consensus = load_sino_land_consensus(db_path)
    if bridge_schedule is None:
        bridge_schedule = load_latest_normalized(SCHEDULE_DATASET)
    reconciliation = build_sino_land_project_reconciliation(bridge_schedule, official)
    quality = build_sino_land_financial_quality(official, actuals, reconciliation)
    return {
        "official_facts": official,
        "financial_data_actuals": actuals,
        "consensus": consensus,
        "project_reconciliation": reconciliation,
        "quality": quality,
    }


def run_sino_land_financial_model(
    *,
    db_path: Path = FINANCIAL_DATA_DB_PATH,
    persist: bool = True,
    bridge_schedule: pd.DataFrame | None = None,
    load_financial_data: bool = True,
) -> dict[str, Any]:
    """Build and optionally persist the Sino Land financial input contract."""
    run_id = f"sino-land-financial-model-{uuid.uuid4()}"
    frames = build_sino_land_financial_model_inputs(
        db_path=db_path,
        bridge_schedule=bridge_schedule,
        load_financial_data=load_financial_data,
    )
    normalized: dict[str, Any] = {}
    dataset_frames = {
        OFFICIAL_FACT_DATASET: frames["official_facts"],
        ACTUALS_DATASET: frames["financial_data_actuals"],
        CONSENSUS_DATASET: frames["consensus"],
        RECONCILIATION_DATASET: frames["project_reconciliation"],
        QUALITY_DATASET: frames["quality"],
    }
    if persist:
        official_source_urls = [
            SINO_ANNUAL_REPORT_2023_URL,
            SINO_ANNUAL_REPORT_2024_URL,
            SINO_ANNUAL_REPORT_2025_URL,
            SINO_INTERIM_REPORT_2025_26_URL,
            SINO_HKEX_TITLE_SEARCH_URL,
        ]
        source_urls_by_dataset = {
            OFFICIAL_FACT_DATASET: official_source_urls,
            ACTUALS_DATASET: [],
            CONSENSUS_DATASET: [],
            RECONCILIATION_DATASET: official_source_urls,
            QUALITY_DATASET: official_source_urls,
        }
        for dataset, frame in dataset_frames.items():
            dataset_source_urls = source_urls_by_dataset[dataset]
            lineage = {
                "lineage_type": "sino_land_issuer_financial_input_contract",
                "run_id": run_id,
                "ticker": SINO_LAND_TICKER,
                "source_urls": dataset_source_urls,
                "source_repo": (
                    "sibling financial-data repository"
                    if dataset in {ACTUALS_DATASET, CONSENSUS_DATASET}
                    else None
                ),
                "source_database_path": (
                    str(Path(db_path).resolve())
                    if dataset in {ACTUALS_DATASET, CONSENSUS_DATASET}
                    else None
                ),
                "research_only": dataset in {RECONCILIATION_DATASET, QUALITY_DATASET},
                "source_datasets": (
                    [OFFICIAL_FACT_DATASET, SCHEDULE_DATASET]
                    if dataset == RECONCILIATION_DATASET
                    else []
                ),
            }
            normalized[dataset] = save_normalized_dataset(
                dataset,
                frame,
                run_id=run_id,
                source_urls=dataset_source_urls,
                lineage_metadata=lineage,
            )
    return {
        "run_id": run_id,
        "ticker": SINO_LAND_TICKER,
        "official_fact_rows": int(len(frames["official_facts"])),
        "actual_rows": int(len(frames["financial_data_actuals"])),
        "consensus_rows": int(len(frames["consensus"])),
        "project_reconciliation_rows": int(len(frames["project_reconciliation"])),
        "quality_rows": int(len(frames["quality"])),
        "normalized": normalized,
        "research_only_project_reconciliation": True,
    }
