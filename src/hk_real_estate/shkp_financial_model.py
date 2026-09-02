"""First-stage SHKP financial-model inputs.

This module deliberately keeps three evidence layers separate:

* ``disclosed_facts`` are curated, source-linked facts from SHKP's official
  financial-summary and results announcements (segment economics, backlog and
  disclosed pipeline capacity);
* ``financial_data_actuals`` are the point-in-time, source-selected 0016.HK
  observations from the sibling ``financial-data`` DuckDB; and
* ``consensus`` / ``dividends`` are supplemental market-facing inputs.

The output is an input contract, not a forecast.  In particular, contracted
sales are never renamed to revenue, and project activity is not converted into
SHKP-attributable sales without the existing phase-specific ownership gate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
import uuid

import pandas as pd

from .storage import load_latest_normalized, save_normalized_dataset
from .shkp_price import (
    DEFAULT_PRICE_HISTORY_START,
    PRICE_HISTORY_DATASET,
    SHKP_PRICE_HISTORY_COLUMNS,
    YAHOO_HISTORY_URL,
    fetch_shkp_price_history,
)
from .sources.shkp import (
    SHKP_COMPLETED_PROPERTY_COLUMNS,
    _record_has_phase_specific_effective_interval,
    enrich_shkp_corporate_document_release_dates,
)


SHKP_TICKER = "0016.HK"


def _discover_financial_data_db_path() -> Path:
    """Find the sibling DuckDB across the supported local checkout layouts.

    The two repositories are commonly checked out either side-by-side under
    ``~/Quant`` or under ``~/Desktop/Quant``.  CI and other machines can set
    ``FINANCIAL_DATA_DB_PATH`` explicitly; otherwise choose the first existing
    database and retain the side-by-side default for a useful error message.
    """
    override = os.environ.get("FINANCIAL_DATA_DB_PATH")
    module_path = Path(__file__).resolve()
    home = Path.home()
    repo_roots = [
        module_path.parents[3],
        home / "Desktop" / "Quant",
    ]
    if override:
        # An explicit path is authoritative, even when it is missing, so a
        # typo cannot silently select a different database.
        return Path(override).expanduser()
    candidates: list[Path] = []
    candidates.extend(
        root / "financial-data" / "data" / "databases" / "hk_financials.duckdb"
        for root in repo_roots
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return (
        candidates[0]
        if candidates
        else Path("financial-data/data/databases/hk_financials.duckdb")
    )


FINANCIAL_DATA_DB_PATH = _discover_financial_data_db_path()

SHKP_FINANCIAL_SUMMARY_URL = "https://www.shkp.com/en-US/investor-relations/financial-summary"
SHKP_ANNUAL_RESULTS_2024_25_URL = (
    "https://www.shkp.com/en-US/media/press-releases/"
    "sun-hung-kai-properties-202425-annual-results-announcement"
)
SHKP_ANNUAL_RESULTS_2023_24_URL = (
    "https://www.shkp.com/en-US/media/press-releases/"
    "sun-hung-kai-properties-202324-annual-results-announcement"
)
SHKP_INTERIM_RESULTS_2025_26_URL = (
    "https://www.shkp.com/en-US/media/press-releases/"
    "sun-hung-kai-properties-202526-interim-results-announcement"
)


SHKP_DISCLOSED_FACT_COLUMNS = [
    "fact_id",
    "ticker",
    "fact_group",
    "metric",
    "value",
    "value_operator",
    "unit",
    "currency",
    "period_start",
    "period_end",
    "target_period_end",
    "period_type",
    "observation_date",
    "available_at",
    "availability_quality",
    "attribution_scope",
    "source_label",
    "source_url",
    "source_role",
    "evidence_status",
    "caveat",
]

SHKP_RECURRING_PORTFOLIO_COLUMNS = [
    "fact_id",
    "ticker",
    "report_id",
    "period_start",
    "period_end",
    "period_type",
    "geography",
    "segment",
    "asset_class",
    "metric",
    "value",
    "value_operator",
    "unit",
    "currency",
    "scope",
    "availability_date",
    "source_label",
    "source_url",
    "source_page",
    "disclosure_precision",
    "source_role",
    "evidence_status",
    "caveat",
]

SHKP_ASSET_PIPELINE_COLUMNS = [
    "asset_id",
    "ticker",
    "report_id",
    "report_period_end",
    "asset_name",
    "asset_class",
    "geography",
    "metric",
    "value",
    "unit",
    "value_operator",
    "event_window",
    "ownership_pct_observed",
    "ownership_semantics",
    "observation_date",
    "availability_date",
    "source_label",
    "source_url",
    "source_page",
    "evidence_status",
    "model_use",
    "caveat",
]


SHKP_FINANCIAL_DATA_FACT_COLUMNS = [
    "fact_id",
    "ticker",
    "fact_group",
    "statement_type",
    "metric",
    "metric_label",
    "value",
    "unit",
    "currency",
    "currency_semantics",
    "period_type",
    "period_end",
    "announcement_date",
    "available_at",
    "point_in_time_quality",
    "source",
    "source_priority",
    "selection_status",
    "fetched_at",
    "source_metadata",
    "model_use",
    "caveat",
]


SHKP_CONSENSUS_COLUMNS = [
    "fact_id",
    "ticker",
    "fact_group",
    "metric",
    "value",
    "unit",
    "currency",
    "estimate_period_end",
    "fiscal_year",
    "horizon",
    "snapshot_date",
    "source",
    "contributor_count",
    "calculation_origin",
    "fetched_at",
    "caveat",
]

SHKP_BROKER_FORECAST_COLUMNS = [
    "forecast_id",
    "ticker",
    "broker_name",
    "forecast_date",
    "fiscal_year",
    "eps",
    "target_price",
    "rating",
    "eps_currency",
    "target_price_currency",
    "net_profit",
    "net_profit_currency",
    "dividend",
    "dividend_currency",
    "currency",
    "source",
    "fetched_at",
    "caveat",
]

SHKP_CONSENSUS_REVISION_COLUMNS = [
    "consensus_id",
    "ticker",
    "snapshot_date",
    "fiscal_year",
    "eps_avg",
    "eps_low",
    "eps_high",
    "revenue_avg",
    "revenue_low",
    "revenue_high",
    "target_price_avg",
    "target_price_median",
    "horizon",
    "num_analysts",
    "source",
    "previous_eps_avg",
    "previous_revenue_avg",
    "previous_target_price_avg",
    "eps_avg_revision",
    "revenue_avg_revision",
    "target_price_avg_revision",
    "fetched_at",
    "caveat",
]

# Practical, append-only snapshot history assembled from the sibling
# financial-data processed partitions.  This is intentionally less strict
# than legal PIT: a fetched_at date is a useful observation snapshot but is
# not rewritten as an original announcement date.  The row-level contract
# keeps the distinction visible for rough model/backtest work.
SHKP_PRACTICAL_VINTAGE_COLUMNS = [
    "vintage_id",
    "ticker",
    "layer",
    "statement_type",
    "metric",
    "metric_label",
    "statistic",
    "period_end",
    "period_type",
    "estimate_period_end",
    "fiscal_year",
    "horizon",
    "value",
    "unit",
    "currency",
    "source",
    "snapshot_date",
    "vintage_date",
    "vintage_date_semantics",
    "announcement_date",
    "available_at",
    "forecast_date",
    "fetched_at",
    "contributor_count",
    "broker_name",
    "source_row_id",
    "source_partition",
    "vintage_quality",
    "model_use",
    "caveat",
]

SHKP_VINTAGE_COVERAGE_COLUMNS = [
    "coverage_id",
    "ticker",
    "layer",
    "source",
    "row_count",
    "distinct_snapshot_count",
    "distinct_period_count",
    "period_start",
    "period_end",
    "snapshot_start",
    "snapshot_end",
    "fetched_at_distinct_count",
    "announcement_date_coverage_pct",
    "release_date_coverage_pct",
    "estimate_period_end_coverage_pct",
    "revision_signal_rows",
    "point_in_time_quality",
    "status",
    "model_use",
    "caveat",
]

# Row-level filing availability contract.  ``shkp_financial_model_vintage_coverage``
# is a compact layer summary; this table keeps the document-level evidence and
# makes it impossible to confuse an undated issuer catalogue row with a
# point-in-time release anchor.
SHKP_FILING_VINTAGE_COLUMNS = [
    "vintage_id",
    "ticker",
    "document_type",
    "document_semantics",
    "title",
    "document_url",
    "source_page_url",
    "source_url",
    "reporting_period_end",
    "issuer_published_date",
    "issuer_release_date",
    "hkex_release_at",
    "availability_at",
    "availability_quality",
    "pit_date_usable",
    "pit_timestamp_usable",
    "model_use",
    "release_evidence_type",
    "release_source_url",
    "fetched_at",
    "source_role",
    "caveat",
]

SHKP_CAPITAL_INPUT_QUALITY_COLUMNS = [
    "quality_id",
    "ticker",
    "statement_type",
    "metric",
    "metric_label",
    "period_end",
    "period_type",
    "raw_value",
    "raw_unit",
    "currency",
    "currency_semantics",
    "normalized_value_hkd_m",
    "normalization_policy",
    "source",
    "source_priority",
    "point_in_time_quality",
    "announcement_date",
    "available_at",
    "quality_status",
    "model_use",
    "caveat",
]

SHKP_FINANCIAL_RECONCILIATION_COLUMNS = [
    "reconciliation_id",
    "ticker",
    "metric",
    "period_end",
    "official_value_hkd_m",
    "financial_data_value_raw_hkd",
    "financial_data_value_hkd_m",
    "difference_pct",
    "official_source_role",
    "financial_data_source",
    "status",
    "caveat",
]


SHKP_DIVIDEND_COLUMNS = [
    "observation_id",
    "ticker",
    "ex_date",
    "payment_date",
    "amount",
    "currency",
    "source",
    "fetched_at",
]

SHKP_MARKET_SNAPSHOT_COLUMNS = [
    "metadata_id",
    "ticker",
    "as_of_date",
    "currency",
    "market_cap",
    "enterprise_value",
    "shares_outstanding",
    "current_price",
    "book_value_per_share",
    "trailing_eps",
    "forward_eps",
    "source",
    "fetched_at",
    "snapshot_quality",
    "caveat",
]

_CAPITAL_MODEL_METRICS = {
    "balance_sheet": {
        "cash_cash_equivalents_and_short_term_investments",
        "cash_and_cash_equivalents",
        "current_debt",
        "investment_properties",
        "investmentsin_associatesat_cost",
        "investmentsin_joint_venturesat_cost",
        "inventory",
        "construction_in_progress",
        "long_term_debt",
        "net_debt",
        "stockholders_equity",
        "total_assets",
        "total_debt",
    },
    "cash_flow": {
        "capital_expenditure",
        "cash_dividends_paid",
        "changes_in_cash",
        "free_cash_flow",
        "issuance_of_debt",
        "operating_cash_flow",
        "purchase_of_investment_properties",
        "purchase_of_ppe",
        "repayment_of_debt",
    },
    "income_statement": {
        "interest_expense",
        "interest_income",
        "net_income_attributable",
        "operating_income",
        "revenue",
        "tax_provision",
    },
}

SHKP_PROJECT_MODEL_BRIDGE_COLUMNS = [
    "srpe_development_id",
    "project_id",
    "period",
    "sales_units_gross",
    "sales_value_gross_hkd",
    "cancelled_units",
    "cumulative_unique_active_units",
    "total_residential_properties",
    "sales_activity_status",
    "ownership_status",
    "ownership_attribution_ready",
    "ownership_pct_used",
    "ownership_effective_from",
    "ownership_effective_to",
    "model_attribution_status",
    "attributable_sales_value_hkd",
    "model_use",
    "source_project_stock_code",
    "caveat",
]

SHKP_DERIVED_MODEL_METRIC_COLUMNS = [
    "metric_id",
    "ticker",
    "period_end",
    "period_type",
    "metric",
    "value",
    "unit",
    "currency",
    "formula",
    "input_fact_ids",
    "source_role",
    "caveat",
]

SHKP_PRICE_HISTORY_DATASET = PRICE_HISTORY_DATASET

SHKP_FINANCIAL_MODEL_DATASETS = (
    "shkp_financial_model_disclosed_facts",
    "shkp_financial_model_recurring_portfolio_facts",
    "shkp_financial_model_asset_pipeline_capacity",
    "shkp_financial_model_completed_properties",
    "shkp_financial_model_derived_metrics",
    "shkp_financial_model_financial_data_actuals",
    "shkp_financial_model_capital_inputs",
    "shkp_financial_model_capital_input_quality",
    "shkp_financial_model_financial_reconciliation",
    "shkp_financial_model_consensus",
    "shkp_financial_model_broker_forecasts",
    "shkp_financial_model_consensus_revisions",
    "shkp_financial_model_practical_vintages",
    "shkp_financial_model_dividends",
    "shkp_financial_model_project_bridge",
    "shkp_financial_model_market_snapshot",
    "shkp_financial_model_price_history",
    "shkp_financial_model_vintage_coverage",
    "shkp_financial_model_filing_vintages",
    "shkp_financial_model_coverage",
)


_ANNUAL_SUMMARY = {
    2021: {
        "segment_revenue": 97130,
        "property_sales_revenue": 46017,
        "property_rental_revenue": 24791,
        "other_business_revenue": 26322,
        "segment_operating_profit": 44176,
        "property_sales_operating_profit": 20994,
        "property_rental_operating_profit": 19149,
        "other_business_operating_profit": 4033,
        "group_revenue": 85262,
        "underlying_profit_attributable": 29873,
        "profit_attributable": 26686,
        "dividends_attributable": 14344,
        "investment_properties": 395879,
        "associates_and_joint_ventures": 101481,
    },
    2022: {
        "segment_revenue": 88340,
        "property_sales_revenue": 35403,
        "property_rental_revenue": 24810,
        "other_business_revenue": 28127,
        "segment_operating_profit": 39010,
        "property_sales_operating_profit": 15847,
        "property_rental_operating_profit": 19250,
        "other_business_operating_profit": 3913,
        "group_revenue": 77747,
        "underlying_profit_attributable": 28729,
        "profit_attributable": 25560,
        "dividends_attributable": 14344,
        "investment_properties": 398729,
        "associates_and_joint_ventures": 101392,
    },
    2023: {
        "segment_revenue": 83381,
        "property_sales_revenue": 29116,
        "property_rental_revenue": 24322,
        "other_business_revenue": 29943,
        "segment_operating_profit": 34689,
        "property_sales_operating_profit": 11299,
        "property_rental_operating_profit": 18461,
        "other_business_operating_profit": 4929,
        "group_revenue": 71195,
        "underlying_profit_attributable": 23885,
        "profit_attributable": 23907,
        "dividends_attributable": 14344,
        "investment_properties": 403559,
        "associates_and_joint_ventures": 101354,
    },
    2024: {
        "segment_revenue": 83636,
        "property_sales_revenue": 27422,
        "property_rental_revenue": 24991,
        "other_business_revenue": 31223,
        "segment_operating_profit": 32359,
        "property_sales_operating_profit": 7850,
        "property_rental_operating_profit": 19000,
        "other_business_operating_profit": 5509,
        "group_revenue": 71506,
        "underlying_profit_attributable": 21739,
        "profit_attributable": 19046,
        "dividends_attributable": 10867,
        "investment_properties": 408424,
        "associates_and_joint_ventures": 101055,
    },
    2025: {
        "segment_revenue": 90119,
        "property_sales_revenue": 34556,
        "property_rental_revenue": 24461,
        "other_business_revenue": 31102,
        "segment_operating_profit": 32188,
        "property_sales_operating_profit": 8290,
        "property_rental_operating_profit": 18392,
        "other_business_operating_profit": 5506,
        "group_revenue": 79721,
        "underlying_profit_attributable": 21855,
        "profit_attributable": 19277,
        "dividends_attributable": 10867,
        "investment_properties": 417045,
        "associates_and_joint_ventures": 104687,
    },
}


_ANNUAL_METRIC_METADATA = {
    "segment_revenue": ("segment_financials", "segment_revenue_including_jv_associates", "HKD_m"),
    "property_sales_revenue": ("segment_financials", "property_sales_revenue_including_jv_associates", "HKD_m"),
    "property_rental_revenue": ("segment_financials", "property_rental_revenue_including_jv_associates", "HKD_m"),
    "other_business_revenue": ("segment_financials", "other_business_revenue_including_jv_associates", "HKD_m"),
    "segment_operating_profit": ("segment_financials", "segment_operating_profit_including_jv_associates", "HKD_m"),
    "property_sales_operating_profit": ("segment_financials", "property_sales_operating_profit_including_jv_associates", "HKD_m"),
    "property_rental_operating_profit": ("segment_financials", "property_rental_operating_profit_including_jv_associates", "HKD_m"),
    "other_business_operating_profit": ("segment_financials", "other_business_operating_profit_including_jv_associates", "HKD_m"),
    "group_revenue": ("consolidated_financials", "group_revenue", "HKD_m"),
    "underlying_profit_attributable": ("consolidated_financials", "underlying_profit_attributable", "HKD_m"),
    "profit_attributable": ("consolidated_financials", "profit_attributable_to_company_shareholders", "HKD_m"),
    "dividends_attributable": ("capital_allocation", "dividends_attributable_to_company_shareholders", "HKD_m"),
    "investment_properties": ("nav_inputs", "investment_properties", "HKD_m"),
    "associates_and_joint_ventures": ("nav_inputs", "associates_and_joint_ventures", "HKD_m"),
}


def _fact_id(*parts: Any) -> str:
    return "shkp:" + ":".join(str(part).strip().lower().replace(" ", "_") for part in parts)


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        # Non-scalar objects are not valid date/text evidence; stringify them
        # only after the scalar missingness check below.
        pass
    text = str(value).strip()
    # CSV/JSON adapters sometimes materialise missing timestamps as literal
    # sentinel strings. Never let those become a fake HKEX release timestamp.
    return None if not text or text.casefold() in {"nan", "nat", "none", "null"} else text


def _base_disclosed_fact(
    *,
    fact_id: str,
    fact_group: str,
    metric: str,
    value: float | int | None,
    unit: str,
    currency: str | None,
    period_start: str | None,
    period_end: str | None,
    target_period_end: str | None,
    period_type: str,
    observation_date: str | None,
    available_at: str | None,
    availability_quality: str,
    attribution_scope: str,
    source_label: str,
    source_url: str,
    caveat: str,
    value_operator: str = "=",
) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "ticker": SHKP_TICKER,
        "fact_group": fact_group,
        "metric": metric,
        "value": value,
        "value_operator": value_operator,
        "unit": unit,
        "currency": currency,
        "period_start": period_start,
        "period_end": period_end,
        "target_period_end": target_period_end,
        "period_type": period_type,
        "observation_date": observation_date,
        "available_at": available_at,
        "availability_quality": availability_quality,
        "attribution_scope": attribution_scope,
        "source_label": source_label,
        "source_url": source_url,
        "source_role": "official_company_disclosure",
        "evidence_status": "observed",
        "caveat": caveat,
    }


# Hong Kong-only property-sales segment revenue by fiscal year, extracted
# from the Segment Information note of each annual report (HK row of the
# property-sales/property-development section, combined revenue = company and
# subsidiaries + share of associates and joint ventures).  Values are HKD
# millions.  The five-year summary's "Property sales" line is NOT used here
# because it mixes Hong Kong, Mainland and Singapore.
_HK_PROPERTY_SALES_SEGMENT_REVENUE_HKD_M: dict[int, int] = {
    2013: 16322,
    2014: 27056,
    2015: 11253,
    2016: 36446,
    2017: 30261,
    2018: 35725,
    2019: 36541,
    2020: 36873,
    2021: 34880,
    2022: 32878,
    2023: 23866,
    2024: 24745,
    2025: 26139,
}


def build_shkp_disclosed_financial_facts() -> pd.DataFrame:
    """Build the first curated SHKP financial/backlog/pipeline fact layer."""
    rows: list[dict[str, Any]] = []
    for fiscal_year, values in _ANNUAL_SUMMARY.items():
        period_end = f"{fiscal_year}-06-30"
        for raw_metric, value in values.items():
            fact_group, metric, unit = _ANNUAL_METRIC_METADATA[raw_metric]
            rows.append(
                _base_disclosed_fact(
                    fact_id=_fact_id("fy", fiscal_year, metric),
                    fact_group=fact_group,
                    metric=metric,
                    value=value,
                    unit=unit,
                    currency="HKD",
                    period_start=f"{fiscal_year - 1}-07-01",
                    period_end=period_end,
                    target_period_end=None,
                    period_type="annual",
                    observation_date=period_end,
                    available_at="2025-09-04",
                    availability_quality="current_five_year_summary",
                    attribution_scope="company_reported_group_or_segment",
                    source_label="SHKP five-year financial summary",
                    source_url=SHKP_FINANCIAL_SUMMARY_URL,
                    caveat=(
                        "Segment revenue and operating profit include the Group's share of joint ventures and associates; "
                        "do not add them to consolidated group revenue."
                        if fact_group == "segment_financials"
                        else "Historical value is presented in the current five-year summary; it is not a first-available vintage."
                    ),
                )
            )

    backlog = [
        ("2024-06-30", "hk_contract_sales_yet_to_be_recognized", 24900, "HKD", None, SHKP_ANNUAL_RESULTS_2023_24_URL, "2024-09-05T16:35:00+08:00"),
        ("2024-06-30", "hk_contract_sales_expected_recognition", 19600, "HKD", "2025-06-30", SHKP_ANNUAL_RESULTS_2023_24_URL, "2024-09-05T16:35:00+08:00"),
        ("2024-06-30", "mainland_contract_sales_yet_to_be_recognized", 12600, "RMB", None, SHKP_ANNUAL_RESULTS_2023_24_URL, "2024-09-05T16:35:00+08:00"),
        ("2024-06-30", "mainland_contract_sales_expected_recognition", 8000, "RMB", "2025-06-30", SHKP_ANNUAL_RESULTS_2023_24_URL, "2024-09-05T16:35:00+08:00"),
        ("2025-06-30", "hk_contract_sales_yet_to_be_recognized", 35600, "HKD", None, SHKP_ANNUAL_RESULTS_2024_25_URL, "2025-09-04T16:30:00+08:00"),
        ("2025-06-30", "hk_contract_sales_expected_recognition", 30100, "HKD", "2026-06-30", SHKP_ANNUAL_RESULTS_2024_25_URL, "2025-09-04T16:30:00+08:00"),
        ("2025-06-30", "mainland_contract_sales_yet_to_be_recognized", 8100, "RMB", None, SHKP_ANNUAL_RESULTS_2024_25_URL, "2025-09-04T16:30:00+08:00"),
    ]
    for period_end, metric, value, currency, target_period_end, url, available_at in backlog:
        rows.append(
            _base_disclosed_fact(
                fact_id=_fact_id("backlog", period_end, metric),
                fact_group="contracted_sales_backlog",
                metric=metric,
                value=value,
                unit=f"{currency}_m",
                currency=currency,
                period_start=None,
                period_end=period_end,
                target_period_end=target_period_end,
                period_type="point_in_time_backlog",
                observation_date=period_end,
                available_at=available_at,
                availability_quality="official_results_announcement",
                attribution_scope="company_reported_attributable",
                source_label="SHKP annual results announcement",
                source_url=url,
                caveat="Contracted sales/backlog is not revenue recognized in the same period.",
            )
        )

    interim_facts = [
        ("contracted_sales_hk_period", 17400, "HKD", "HKD_m", "=", "Attributable Hong Kong contracted sales during 2025/26 interim period."),
        ("sierra_sea_contracted_sales_period", 9000, "HKD", "HKD_m", ">", "Sierra Sea contracted sales exceeded this amount; source is not an exact point estimate."),
        ("planned_launch_project_count", 6, None, "projects", "=", "Six projects were planned for launch over the following ten months."),
        ("northern_metropolis_projects_under_development", 8, None, "projects", "=", "Company-disclosed project count; not a phase-level attributable unit forecast."),
        ("northern_metropolis_planned_units", 10000, None, "units", "~", "Company-disclosed approximate unit capacity."),
        ("northern_metropolis_planned_gfa", 4500000, None, "sqft", ">", "Company-disclosed total GFA is over this level."),
        ("kwu_tung_project_planned_units", 2700, None, "units", ">", "Company-disclosed approximate unit capacity after lease modification."),
        ("kwu_tung_project_planned_gfa", 1200000, None, "sqft", "~", "Company-disclosed approximate GFA after lease modification."),
        ("future_launch_window_months", 10, None, "months", "=", "Relative window from the 2025/26 interim announcement; not a project-level launch date."),
    ]
    for metric, value, currency, unit, operator, caveat in interim_facts:
        rows.append(
            _base_disclosed_fact(
                fact_id=_fact_id("interim", "2025-12-31", metric),
                fact_group="future_growth_pipeline" if "planned" in metric or "project" in metric or "window" in metric else "contracted_sales_flow",
                metric=metric,
                value=value,
                value_operator=operator,
                unit=unit,
                currency=currency,
                period_start="2025-07-01",
                period_end="2025-12-31",
                target_period_end=None,
                period_type="interim",
                observation_date="2025-12-31",
                available_at="2026-02-26T16:30:00+08:00",
                availability_quality="official_interim_results_announcement",
                attribution_scope="company_reported_attributable" if currency else "company_disclosed_pipeline",
                source_label="SHKP 2025/26 interim results announcement",
                source_url=SHKP_INTERIM_RESULTS_2025_26_URL,
                caveat=caveat,
            )
        )
    return pd.DataFrame(rows, columns=SHKP_DISCLOSED_FACT_COLUMNS)


def build_shkp_hk_property_sales_segment_history() -> pd.DataFrame:
    """Build the 13-year Hong Kong-only property-sales segment revenue panel.

    Each row is the Hong Kong row of the annual-report Segment Information
    note (property-sales/property-development section).  ``combined`` revenue
    adds the company-and-subsidiaries revenue to the Group's share of
    associates and joint ventures, which is the same attribution convention
    the indicative sales model uses.  The five-year summary's all-region
    property-sales line is deliberately not used for HK reconciliation.
    """
    rows: list[dict[str, Any]] = []
    for fiscal_year, combined_hkd_m in sorted(_HK_PROPERTY_SALES_SEGMENT_REVENUE_HKD_M.items()):
        period_start = f"{fiscal_year - 1}-07-01"
        period_end = f"{fiscal_year}-06-30"
        rows.append(
            {
                "fiscal_year_end": fiscal_year,
                "fiscal_label": f"FY{fiscal_year - 1}/{str(fiscal_year)[-2:]}",
                "period_start": period_start,
                "period_end": period_end,
                "segment": "property_sales_hong_kong",
                "revenue_hkd_m": combined_hkd_m,
                "revenue_hkd": float(combined_hkd_m) * 1_000_000.0,
                "revenue_scope": "hong_kong_combined_including_jv_associates",
                "source_section": "annual_report_segment_information_note",
                "source_basis": "hk_row_of_property_sales_development_segment",
                "data_status": "verified_from_annual_report_pdf",
                "caveat": (
                    "Hong Kong-only combined segment revenue (company and subsidiaries plus share of "
                    "associates and joint ventures). Distinct from the five-year summary property-sales "
                    "line, which includes Mainland and Singapore."
                ),
            }
        )
    return pd.DataFrame(rows)


def _recurring_fact(
    *,
    fact_id: str,
    report_id: str,
    period_start: str,
    period_end: str,
    period_type: str,
    geography: str,
    segment: str,
    asset_class: str,
    metric: str,
    value: float | int | None,
    unit: str,
    currency: str | None,
    scope: str,
    availability_date: str,
    source_label: str,
    source_url: str,
    source_page: str,
    caveat: str,
    value_operator: str = "=",
    disclosure_precision: str = "exact",
) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "ticker": SHKP_TICKER,
        "report_id": report_id,
        "period_start": period_start,
        "period_end": period_end,
        "period_type": period_type,
        "geography": geography,
        "segment": segment,
        "asset_class": asset_class,
        "metric": metric,
        "value": value,
        "value_operator": value_operator,
        "unit": unit,
        "currency": currency,
        "scope": scope,
        "availability_date": availability_date,
        "source_label": source_label,
        "source_url": source_url,
        "source_page": source_page,
        "disclosure_precision": disclosure_precision,
        "source_role": "official_company_disclosure",
        "evidence_status": "observed",
        "caveat": caveat,
    }


def build_shkp_recurring_portfolio_facts() -> pd.DataFrame:
    """Normalize the first official rental/hotel/occupancy fact tranche.

    This is deliberately a period-fact layer, not an asset master.  All
    revenue/profit rows include the Group's share of JVs/associates where the
    report says so; HKD and RMB are kept as separate observations.  Qualitative
    language without a numeric value is not converted into a fake percentage.
    """
    annual_url = "https://www.shkp.com/Content/Uploads/FinReports/SHKPAR_EN_2024_25.pdf"
    interim_url = "https://www.shkp.com/Content/Uploads/FinReports/E_IR_2025_26.pdf"
    annual_label = "SHKP Annual Report 2024/25"
    interim_label = "SHKP Interim Report 2025/26"
    annual_scope = "including_group_share_of_joint_ventures_and_associates"
    rows: list[dict[str, Any]] = []

    def annual(metric: str, value: float, *, geography: str = "group", segment: str = "property_rental", asset_class: str = "portfolio", unit: str = "HKD_m", currency: str | None = "HKD", scope: str = annual_scope, page: str = "94", caveat: str = "Annual segment fact includes the Group's share of joint ventures and associates; it is not consolidated revenue.", value_operator: str = "=", disclosure_precision: str = "exact") -> None:
        rows.append(_recurring_fact(
            fact_id=_fact_id("recurring", "fy2025", geography, asset_class, metric, unit),
            report_id="shkp_ar_2024_25",
            period_start="2024-07-01",
            period_end="2025-06-30",
            period_type="annual",
            geography=geography,
            segment=segment,
            asset_class=asset_class,
            metric=metric,
            value=value,
            unit=unit,
            currency=currency,
            scope=scope,
            availability_date="2025-09-04",
            source_label=annual_label,
            source_url=annual_url,
            source_page=page,
            caveat=caveat,
            value_operator=value_operator,
            disclosure_precision=disclosure_precision,
        ))

    annual("gross_rental_income", 24461)
    annual("net_rental_income", 18392)
    annual("gross_rental_income", 17531, geography="hong_kong", asset_class="property_investment", page="28", caveat="Hong Kong rental portfolio gross income; includes JV/associate contributions and is not asset-level rent roll.")
    annual("gross_rental_income", 5713, geography="mainland", asset_class="property_investment", unit="RMB_m", currency="RMB", page="74", caveat="Mainland rental portfolio reported in RMB; do not add to HKD rows without an explicit FX convention.")
    annual("gross_rental_income", 6173, geography="mainland", asset_class="property_investment", page="94", caveat="Mainland rental portfolio translated/reported in HKD; keep separate from the RMB observation to avoid double counting.")
    annual("net_rental_income", 4864, geography="mainland", asset_class="property_investment", page="94", caveat="Mainland net rental income in HKD; includes JV/associate contributions.")
    annual("gross_rental_income", 757, geography="singapore", asset_class="property_investment", page="94", caveat="Singapore rental portfolio; included in the group segment total.")
    annual("revenue", 5679, geography="hong_kong", asset_class="office", page="95", caveat="Hong Kong office portfolio revenue; includes JV/associate contributions and is not an occupancy-weighted rent roll.")
    annual("revenue", 9085, geography="hong_kong", asset_class="retail", page="95", caveat="Hong Kong retail portfolio revenue; includes turnover-rent effects and JV/associate contributions.")
    annual("revenue", 1743, geography="mainland", asset_class="office", page="95", caveat="Mainland office portfolio revenue translated/reported in HKD.")
    annual("revenue", 4079, geography="mainland", asset_class="retail", page="95", caveat="Mainland retail portfolio revenue translated/reported in HKD.")
    annual("revenue", 5250, asset_class="hotel", segment="hotel_operations", page="95", caveat="Hotel segment revenue includes JV/associate contributions; no hotel-by-hotel occupancy or RevPAR is supplied here.")
    annual("operating_profit", 615, asset_class="hotel", segment="hotel_operations", page="95", caveat="Hotel segment operating profit after depreciation; do not substitute for EBITDA.")
    annual("average_occupancy", 90, geography="hong_kong", asset_class="hotel", unit="percent", currency=None, scope="hotel_portfolio_as_stated", page="95", caveat="Average occupancy for Hong Kong hotels; portfolio-level, not hotel-by-hotel.")
    annual("average_occupancy", 95, geography="hong_kong", asset_class="retail", unit="percent", currency=None, scope="portfolio_statistic_as_stated", page="11", value_operator="~", disclosure_precision="approximate", caveat="Diversified Hong Kong retail portfolio occupancy; approximate portfolio statistic.")
    annual("average_occupancy", 90, geography="hong_kong", asset_class="office", unit="percent", currency=None, scope="portfolio_statistic_as_stated", page="12", value_operator="~", disclosure_precision="approximate", caveat="Hong Kong office portfolio average occupancy; approximate portfolio statistic.")
    annual("average_occupancy", 92, geography="hong_kong", asset_class="office_landmark", unit="percent", currency=None, scope="named_assets_ifc_icc_as_stated", page="12", value_operator="~", disclosure_precision="approximate", caveat="IFC and ICC combined/mentioned occupancy; not the whole office portfolio.")
    annual("completed_gfa", 37.7, geography="hong_kong", asset_class="completed_property", unit="million_sqft", currency=None, scope="attributable_land_bank", page="4", caveat="Attributable Hong Kong completed land bank; mostly rental/long-term investment but not a pure stabilized-rent denominator.")
    annual("under_development_gfa", 19.7, geography="hong_kong", asset_class="development_pipeline", unit="million_sqft", currency=None, scope="attributable_land_bank", page="4", caveat="Attributable Hong Kong properties under development; do not treat as current recurring GFA.")
    annual("total_land_bank_gfa", 57.4, geography="hong_kong", asset_class="land_bank", unit="million_sqft", currency=None, scope="attributable_land_bank", page="4", caveat="Attributable Hong Kong land bank total; component scopes mix completed and under-development properties.")
    annual("completed_gfa", 21.1, geography="mainland", asset_class="completed_property", unit="million_sqft", currency=None, scope="attributable_land_bank", page="4", caveat="Attributable Mainland completed land bank; mostly rental/long-term investment but not a pure stabilized-rent denominator.")
    annual("under_development_gfa", 44.2, geography="mainland", asset_class="development_pipeline", unit="million_sqft", currency=None, scope="attributable_land_bank", page="4", caveat="Attributable Mainland properties under development; do not treat as current recurring GFA.")
    annual("total_land_bank_gfa", 65.3, geography="mainland", asset_class="land_bank", unit="million_sqft", currency=None, scope="attributable_land_bank", page="4", caveat="Attributable Mainland land bank total; component scopes mix completed and under-development properties.")

    def interim(metric: str, value: float, *, geography: str = "group", segment: str = "property_rental", asset_class: str = "portfolio", unit: str = "HKD_m", currency: str | None = "HKD", scope: str = annual_scope, page: str = "43", caveat: str = "Interim segment fact includes the Group's share of joint ventures and associates; do not annualize without seasonality assumptions.", value_operator: str = "=", disclosure_precision: str = "exact") -> None:
        rows.append(_recurring_fact(
            fact_id=_fact_id("recurring", "h1fy2026", geography, asset_class, metric, unit),
            report_id="shkp_ir_2025_26",
            period_start="2025-07-01",
            period_end="2025-12-31",
            period_type="interim",
            geography=geography,
            segment=segment,
            asset_class=asset_class,
            metric=metric,
            value=value,
            unit=unit,
            currency=currency,
            scope=scope,
            availability_date="2026-02-26",
            source_label=interim_label,
            source_url=interim_url,
            source_page=page,
            caveat=caveat,
            value_operator=value_operator,
            disclosure_precision=disclosure_precision,
        ))

    interim("gross_rental_income", 12285)
    interim("net_rental_income", 8950)
    interim("gross_rental_income", 8797, geography="hong_kong", asset_class="property_investment", page="43", caveat="Hong Kong rental portfolio gross income; includes JV/associate contributions; six-month period.")
    interim("net_rental_income", 6265, geography="hong_kong", asset_class="property_investment", page="43", caveat="Hong Kong net rental income; includes JV/associate contributions; six-month period.")
    interim("gross_rental_income", 3098, geography="mainland", asset_class="property_investment", page="43", caveat="Mainland rental portfolio translated/reported in HKD; six-month period.")
    interim("gross_rental_income", 2825, geography="mainland", asset_class="property_investment", unit="RMB_m", currency="RMB", page="44", caveat="Mainland rental portfolio reported in RMB; keep separate from the HKD translation.")
    interim("net_rental_income", 2400, geography="mainland", asset_class="property_investment", page="43", caveat="Mainland net rental income; six-month period.")
    interim("gross_rental_income", 390, geography="singapore", asset_class="property_investment", page="43", caveat="Singapore rental portfolio; six-month period.")
    interim("net_rental_income", 285, geography="singapore", asset_class="property_investment", page="43", caveat="Singapore net rental income; six-month period.")
    interim("revenue", 2834, geography="hong_kong", asset_class="office", page="44", caveat="Hong Kong office portfolio revenue; six-month period.")
    interim("revenue", 4535, geography="hong_kong", asset_class="retail", page="44", caveat="Hong Kong retail portfolio revenue; six-month period.")
    interim("revenue", 814, geography="mainland", asset_class="office", page="44", caveat="Mainland office portfolio revenue; six-month period.")
    interim("revenue", 2100, geography="mainland", asset_class="retail", page="44", caveat="Mainland retail portfolio revenue; six-month period.")
    interim("revenue", 2779, asset_class="hotel", segment="hotel_operations", page="43", caveat="Hotel segment revenue includes JV/associate contributions; six-month period.")
    interim("ebitda", 796, asset_class="hotel", segment="hotel_operations", page="44", caveat="Hotel segment EBITDA; six-month period.")
    interim("operating_profit", 428, asset_class="hotel", segment="hotel_operations", page="44", caveat="Hotel segment operating profit after depreciation; six-month period.")
    interim("average_occupancy", 94, geography="hong_kong", asset_class="retail", unit="percent", currency=None, scope="portfolio_statistic_as_stated", page="6", caveat="Hong Kong retail portfolio average occupancy; portfolio statistic for the six-month period.")
    interim("occupancy", 98, geography="hong_kong", asset_class="office_landmark_ifc", unit="percent", currency=None, scope="named_asset_ifc", page="7", caveat="IFC occupancy; named-asset statistic, not the whole office portfolio.")
    interim("occupancy", 91, geography="hong_kong", asset_class="office_landmark_icc", unit="percent", currency=None, scope="named_asset_icc", page="7", caveat="ICC occupancy; named-asset statistic, not the whole office portfolio.")
    interim("investment_gfa", 1.2, geography="hong_kong", asset_class="office_pipeline_igc", unit="million_sqft", currency=None, scope="group_long_term_investment_area", page="8", value_operator="~", disclosure_precision="approximate", caveat="IGC office area held as long-term investment; project is newly handed over and not a stabilized historical rent denominator.")
    interim("planned_gfa", 0.603, geography="hong_kong", asset_class="retail_pipeline_igc", unit="million_sqft", currency=None, scope="group_owned_pipeline_area", page="8", value_operator="~", disclosure_precision="approximate", caveat="IGC podium mall planned/owned area; future recurring-income capacity, not current revenue.")
    interim("planned_gfa", 0.5, geography="hong_kong", asset_class="retail_pipeline_scramble_hill", unit="million_sqft", currency=None, scope="group_project_scale_as_stated", page="7", value_operator="~", disclosure_precision="approximate", caveat="Scramble Hill mall scale; future/early-opening capacity, not a stabilized rent denominator.")
    interim("planned_gfa", 0.22, geography="hong_kong", asset_class="retail_pipeline_cullinan_sky_mall", unit="million_sqft", currency=None, scope="group_project_scale_as_stated", page="7", value_operator="~", disclosure_precision="approximate", caveat="Cullinan Sky Mall scale; phased opening and future recurring-income capacity.")
    return pd.DataFrame(rows, columns=SHKP_RECURRING_PORTFOLIO_COLUMNS)


def build_shkp_asset_pipeline_capacity() -> pd.DataFrame:
    """Normalize named commercial projects disclosed as future capacity.

    These rows are deliberately capacity-only.  They support a completion and
    recurring-income runway view, but do not infer rent, NOI, fair value or a
    continuous legal ownership interval from a project-stake snapshot.
    """
    source_url = "https://www.shkp.com/Content/Uploads/FinReports/SHKPAR_EN_2024_25.pdf"
    rows = [
        {
            "asset_id": "shkp:asset_pipeline:scramble_hill:retail",
            "asset_name": "Scramble Hill",
            "asset_class": "retail",
            "metric": "gross_gfa",
            "value": 500000,
            "unit": "sqft",
            "value_operator": "=",
            "event_window": "phased opening from 2025-H2",
            "ownership_pct_observed": 72.4,
            "ownership_semantics": "project_stake_snapshot_as_stated",
            "source_page": "50",
            "caveat": "Annual report states a 72.4% project stake; this is not a bounded legal/SPV interval and the area is future capacity, not rent or NOI.",
        },
        {
            "asset_id": "shkp:asset_pipeline:cullinan_sky_mall:retail",
            "asset_name": "Cullinan Sky Mall",
            "asset_class": "retail",
            "metric": "gross_gfa",
            "value": 220000,
            "unit": "sqft",
            "value_operator": "=",
            "event_window": "phased opening from 2025-Q4",
            "ownership_pct_observed": None,
            "ownership_semantics": "not_numeric_in_this_disclosure",
            "source_page": "50",
            "caveat": "Podium-mall scale and opening window only; no asset-level rent/NOI or phase-specific economic percentage is inferred.",
        },
        {
            "asset_id": "shkp:asset_pipeline:igc:office_gross",
            "asset_name": "International Gateway Centre (IGC)",
            "asset_class": "office",
            "metric": "gross_gfa",
            "value": 2600000,
            "unit": "sqft",
            "value_operator": "~",
            "event_window": "handover in early 2026",
            "ownership_pct_observed": None,
            "ownership_semantics": "not_numeric_in_this_disclosure",
            "source_page": "50",
            "caveat": "Gross office scale; the report separately states retained area and does not provide a stabilized rent denominator.",
        },
        {
            "asset_id": "shkp:asset_pipeline:igc:office_retained",
            "asset_name": "International Gateway Centre (IGC)",
            "asset_class": "office",
            "metric": "retained_investment_gfa",
            "value": 1200000,
            "unit": "sqft",
            "value_operator": "~",
            "event_window": "handover in early 2026",
            "ownership_pct_observed": None,
            "ownership_semantics": "group_retained_area_as_stated",
            "source_page": "50",
            "caveat": "Long-term investment area as stated by SHKP; no rent, occupancy or valuation is inferred.",
        },
        {
            "asset_id": "shkp:asset_pipeline:igc:retail_retained",
            "asset_name": "International Gateway Centre (IGC) podium mall",
            "asset_class": "retail",
            "metric": "retained_investment_gfa",
            "value": 603000,
            "unit": "sqft",
            "value_operator": "~",
            "event_window": "handover in early 2026",
            "ownership_pct_observed": None,
            "ownership_semantics": "group_retained_area_as_stated",
            "source_page": "50",
            "caveat": "Entire retail portion stated as retained; future capacity only, not stabilized rental income.",
        },
        {
            "asset_id": "shkp:asset_pipeline:artist_square:office",
            "asset_name": "Artist Square Towers Project",
            "asset_class": "office",
            "metric": "gross_gfa",
            "value": 672000,
            "unit": "sqft",
            "value_operator": "~",
            "event_window": "completion in 2027-H1",
            "ownership_pct_observed": None,
            "ownership_semantics": "not_numeric_in_this_disclosure",
            "source_page": "51",
            "caveat": "Planned office capacity; completion timing can move and no rent/NOI is inferred.",
        },
        {
            "asset_id": "shkp:asset_pipeline:artist_square:retail",
            "asset_name": "Artist Square Towers Project",
            "asset_class": "retail",
            "metric": "gross_gfa",
            "value": 27000,
            "unit": "sqft",
            "value_operator": "~",
            "event_window": "completion in 2027-H1",
            "ownership_pct_observed": None,
            "ownership_semantics": "not_numeric_in_this_disclosure",
            "source_page": "51",
            "caveat": "Planned retail capacity; completion timing can move and no rent/NOI is inferred.",
        },
        {
            "asset_id": "shkp:asset_pipeline:mong_kok_commercial:retail",
            "asset_name": "Mong Kok commercial complex",
            "asset_class": "retail",
            "metric": "gross_gfa",
            "value": 170000,
            "unit": "sqft",
            "value_operator": "~",
            "event_window": "completion in 2030 or beyond",
            "ownership_pct_observed": None,
            "ownership_semantics": "not_numeric_in_this_disclosure",
            "source_page": "51",
            "caveat": "Retail-podium scale only; commercial-tower area is not disclosed in this row and no rent/NOI is inferred.",
        },
    ]
    result = pd.DataFrame(rows)
    result.insert(1, "ticker", SHKP_TICKER)
    result.insert(2, "report_id", "shkp_ar_2024_25")
    result.insert(3, "report_period_end", "2025-06-30")
    result.insert(14, "observation_date", "2025-06-30")
    result.insert(15, "availability_date", "2025-09-04")
    result.insert(16, "source_label", "SHKP Annual Report 2024/25")
    result.insert(17, "source_url", source_url)
    result.insert(19, "evidence_status", "observed_official_named_asset_capacity")
    result.insert(20, "model_use", "capacity_only")
    return result.reindex(columns=SHKP_ASSET_PIPELINE_COLUMNS)


def build_shkp_financial_model_derived_metrics(
    disclosed_facts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Derive model ratios only from compatible official disclosed facts."""
    facts = disclosed_facts if disclosed_facts is not None else build_shkp_disclosed_financial_facts()
    annual = facts.loc[
        facts["fact_group"].eq("segment_financials")
        | facts["fact_group"].eq("consolidated_financials")
        | facts["fact_group"].eq("nav_inputs")
    ].copy()
    if annual.empty:
        return pd.DataFrame(columns=SHKP_DERIVED_MODEL_METRIC_COLUMNS)
    annual["value"] = pd.to_numeric(annual["value"], errors="coerce")
    lookup = {
        (row["period_end"], row["metric"]): row
        for row in annual.to_dict("records")
        if pd.notna(row.get("value"))
    }
    rows: list[dict[str, Any]] = []

    def add_ratio(
        period_end: str,
        metric: str,
        numerator_metric: str,
        denominator_metric: str,
        formula: str,
        caveat: str,
    ) -> None:
        numerator = lookup.get((period_end, numerator_metric))
        denominator = lookup.get((period_end, denominator_metric))
        if not numerator or not denominator:
            return
        denominator_value = float(denominator["value"])
        if denominator_value == 0:
            return
        value = float(numerator["value"]) / denominator_value * 100.0
        rows.append({
            "metric_id": _fact_id("derived", period_end, metric),
            "ticker": SHKP_TICKER,
            "period_end": period_end,
            "period_type": "annual",
            "metric": metric,
            "value": value,
            "unit": "percent",
            "currency": None,
            "formula": formula,
            "input_fact_ids": f"{numerator['fact_id']}|{denominator['fact_id']}",
            "source_role": "derived_from_official_disclosed_facts",
            "caveat": caveat,
        })

    periods = sorted({str(value) for value in annual["period_end"].dropna()})
    for period_end in periods:
        add_ratio(
            period_end,
            "segment_operating_margin_pct",
            "segment_operating_profit_including_jv_associates",
            "segment_revenue_including_jv_associates",
            "segment_operating_profit_including_jv_associates / segment_revenue_including_jv_associates * 100",
            "Segment view includes the Group's share of joint ventures and associates.",
        )
        add_ratio(
            period_end,
            "property_sales_operating_margin_pct",
            "property_sales_operating_profit_including_jv_associates",
            "property_sales_revenue_including_jv_associates",
            "property_sales_operating_profit_including_jv_associates / property_sales_revenue_including_jv_associates * 100",
            "This is a segment operating margin, not a project gross margin.",
        )
        add_ratio(
            period_end,
            "property_rental_operating_margin_pct",
            "property_rental_operating_profit_including_jv_associates",
            "property_rental_revenue_including_jv_associates",
            "property_rental_operating_profit_including_jv_associates / property_rental_revenue_including_jv_associates * 100",
            "This is a segment operating margin, not asset-level NOI margin.",
        )
        add_ratio(
            period_end,
            "other_business_operating_margin_pct",
            "other_business_operating_profit_including_jv_associates",
            "other_business_revenue_including_jv_associates",
            "other_business_operating_profit_including_jv_associates / other_business_revenue_including_jv_associates * 100",
            "Other businesses are heterogeneous and should not be valued as property sales.",
        )
        add_ratio(
            period_end,
            "property_rental_profit_share_of_segment_pct",
            "property_rental_operating_profit_including_jv_associates",
            "segment_operating_profit_including_jv_associates",
            "property_rental_operating_profit_including_jv_associates / segment_operating_profit_including_jv_associates * 100",
            "Descriptive profit mix only; it is not a standalone valuation weight.",
        )

    investment_properties = {
        str(row["period_end"]): row
        for row in annual.to_dict("records")
        if row.get("metric") == "investment_properties"
    }
    for previous, current in zip(sorted(investment_properties), sorted(investment_properties)[1:]):
        previous_value = pd.to_numeric(investment_properties[previous]["value"], errors="coerce")
        current_value = pd.to_numeric(investment_properties[current]["value"], errors="coerce")
        if pd.isna(previous_value) or previous_value == 0 or pd.isna(current_value):
            continue
        rows.append({
            "metric_id": _fact_id("derived", current, "investment_properties_yoy"),
            "ticker": SHKP_TICKER,
            "period_end": current,
            "period_type": "annual",
            "metric": "investment_properties_yoy_pct",
            "value": (float(current_value) / float(previous_value) - 1.0) * 100.0,
            "unit": "percent",
            "currency": None,
            "formula": "investment_properties_current / investment_properties_previous - 1",
            "input_fact_ids": f"{investment_properties[previous]['fact_id']}|{investment_properties[current]['fact_id']}",
            "source_role": "derived_from_official_disclosed_facts",
            "caveat": "Year-over-year change mixes valuation movement, acquisitions, disposals and FX; it is not pure rental growth.",
        })
    return pd.DataFrame(rows, columns=SHKP_DERIVED_MODEL_METRIC_COLUMNS)


def _require_duckdb():
    try:
        import duckdb  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "DuckDB is required to read the sibling financial-data database; "
            "install duckdb>=1.1,<2 or provide a reviewed Parquet snapshot."
        ) from exc
    return duckdb


def load_shkp_financial_data_actuals(
    db_path: Path = FINANCIAL_DATA_DB_PATH,
    *,
    ticker: str = SHKP_TICKER,
) -> pd.DataFrame:
    """Read source-selected SHKP facts without copying the sibling database."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"financial-data DuckDB not found: {path}")
    duckdb = _require_duckdb()
    query = """
        SELECT
            observation_id AS fact_id,
            ticker,
            statement_type,
            metric,
            metric_label,
            value,
            unit,
            currency,
            currency_semantics,
            period_type,
            fiscal_period_end AS period_end,
            announcement_date,
            available_at,
            point_in_time_quality,
            source,
            source_priority,
            selection_status,
            fetched_at,
            source_metadata
        FROM latest_restated_financial_facts
        WHERE ticker = ?
          AND selection_status = 'policy_deterministic'
          AND value IS NOT NULL
        ORDER BY fiscal_period_end, statement_type, metric
    """
    with duckdb.connect(str(path), read_only=True) as connection:
        frame = connection.execute(query, [ticker]).df()
    if frame.empty:
        raise ValueError(f"financial-data contains no deterministic facts for {ticker}")
    group_map = {
        "income_statement": "income_statement",
        "balance_sheet": "balance_sheet",
        "cash_flow": "cash_flow",
        "financial_indicators": "financial_indicators",
    }
    frame["fact_group"] = frame["statement_type"].map(group_map).fillna("other_financial_data")
    frame["model_use"] = frame.apply(
        lambda row: "selected_actual"
        if row["statement_type"] in group_map
        else "review_only",
        axis=1,
    )
    frame["caveat"] = (
        "Source-selected financial-data observation; use source metadata and conflict gates before forecast calculations."
    )
    return frame.reindex(columns=SHKP_FINANCIAL_DATA_FACT_COLUMNS)


def load_shkp_consensus(
    db_path: Path = FINANCIAL_DATA_DB_PATH,
    *,
    ticker: str = SHKP_TICKER,
) -> pd.DataFrame:
    """Load consensus statistics with snapshot/vintage fields preserved."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"financial-data DuckDB not found: {path}")
    duckdb = _require_duckdb()
    query = """
        SELECT
            consensus_statistic_id AS fact_id,
            ticker,
            metric,
            statistic,
            value,
            unit,
            currency,
            estimate_period_end,
            fiscal_year,
            horizon,
            snapshot_date,
            source,
            contributor_count,
            calculation_origin,
            fetched_at
        FROM consensus_statistics_history
        WHERE ticker = ?
          AND value IS NOT NULL
        ORDER BY snapshot_date, estimate_period_end, metric, statistic
    """
    with duckdb.connect(str(path), read_only=True) as connection:
        frame = connection.execute(query, [ticker]).df()
    if frame.empty:
        raise ValueError(f"financial-data contains no consensus statistics for {ticker}")
    frame["fact_group"] = "consensus"
    frame["caveat"] = (
        "Consensus is a dated market-expectation snapshot, not issuer guidance or an audited actual."
    )
    return frame.reindex(columns=SHKP_CONSENSUS_COLUMNS)


def load_shkp_broker_forecasts(
    db_path: Path = FINANCIAL_DATA_DB_PATH,
    *,
    ticker: str = SHKP_TICKER,
) -> pd.DataFrame:
    """Load broker-level forecasts while preserving their forecast dates.

    These rows are useful for a current cross-sectional scenario range.  The
    provider fetch timestamp can be later than ``forecast_date`` and therefore
    does not by itself establish a historical point-in-time revision trail.
    """
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"financial-data DuckDB not found: {path}")
    duckdb = _require_duckdb()
    try:
        with duckdb.connect(str(path), read_only=True) as connection:
            frame = connection.execute(
                """
                SELECT forecast_id, ticker, broker_name, forecast_date,
                       fiscal_year, eps, target_price, rating,
                       eps_currency, target_price_currency, net_profit,
                       net_profit_currency, dividend, dividend_currency,
                       currency, source, fetched_at
                FROM broker_forecasts
                WHERE ticker = ?
                ORDER BY forecast_date, broker_name, fiscal_year
                """,
                [ticker],
            ).df()
    except Exception as exc:
        if "broker_forecasts" in str(exc).lower() or "catalog" in str(exc).lower():
            return pd.DataFrame(columns=SHKP_BROKER_FORECAST_COLUMNS)
        raise
    if frame.empty:
        return pd.DataFrame(columns=SHKP_BROKER_FORECAST_COLUMNS)
    frame["caveat"] = (
        "Broker forecast date is preserved, but the provider fetch timestamp may be later; "
        "do not treat this as a complete historical estimate-vintage series."
    )
    return frame.reindex(columns=SHKP_BROKER_FORECAST_COLUMNS)


def load_shkp_consensus_revisions(
    db_path: Path = FINANCIAL_DATA_DB_PATH,
    *,
    ticker: str = SHKP_TICKER,
) -> pd.DataFrame:
    """Load provider revision diagnostics without implying a full revision history."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"financial-data DuckDB not found: {path}")
    duckdb = _require_duckdb()
    try:
        with duckdb.connect(str(path), read_only=True) as connection:
            frame = connection.execute(
                """
                SELECT consensus_id, ticker, snapshot_date, fiscal_year,
                       eps_avg, eps_low, eps_high, revenue_avg, revenue_low,
                       revenue_high, target_price_avg, target_price_median,
                       horizon, num_analysts, source, previous_eps_avg,
                       previous_revenue_avg, previous_target_price_avg,
                       eps_avg_revision, revenue_avg_revision,
                       target_price_avg_revision, fetched_at
                FROM consensus_revisions
                WHERE ticker = ?
                ORDER BY snapshot_date, fiscal_year, horizon
                """,
                [ticker],
            ).df()
    except Exception as exc:
        if "consensus_revisions" in str(exc).lower() or "catalog" in str(exc).lower():
            return pd.DataFrame(columns=SHKP_CONSENSUS_REVISION_COLUMNS)
        raise
    if frame.empty:
        return pd.DataFrame(columns=SHKP_CONSENSUS_REVISION_COLUMNS)
    frame["caveat"] = (
        "Revision fields are provider diagnostics from the available snapshot; "
        "they do not establish multiple historical consensus vintages."
    )
    return frame.reindex(columns=SHKP_CONSENSUS_REVISION_COLUMNS)


def _financial_data_processed_root(db_path: Path = FINANCIAL_DATA_DB_PATH) -> Path:
    """Return the sibling processed root without importing its runtime."""
    # ``.../financial-data/data/databases/hk_financials.duckdb`` ->
    # ``.../financial-data/data/processed/hk_financials``.
    return Path(db_path).resolve().parents[1] / "processed" / "hk_financials"


def _read_sibling_processed_history(
    dataset: str,
    *,
    db_path: Path = FINANCIAL_DATA_DB_PATH,
    ticker: str = SHKP_TICKER,
) -> pd.DataFrame:
    """Read all ticker rows from sibling processed parquet partitions.

    The canonical DuckDB views intentionally expose the latest deterministic
    facts.  For a practical, non-PIT vintage lane we need the append-only
    source partitions as well, so each observed ``fetched_at`` snapshot can be
    retained.  Read errors are collected as an empty result rather than
    blocking the normal financial model; the coverage row will expose the
    missing layer.
    """
    root = _financial_data_processed_root(db_path) / dataset
    files = sorted(root.rglob("*.parquet")) if root.exists() else []
    frames: list[pd.DataFrame] = []
    for path in files:
        try:
            frame = pd.read_parquet(path)
        except (OSError, ValueError, ImportError):
            continue
        if "ticker" in frame.columns:
            frame = frame.loc[frame["ticker"].astype(str).eq(ticker)].copy()
        if not frame.empty:
            frame["source_partition"] = str(path)
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def _practical_vintage_date(
    *,
    announcement_date: Any = None,
    snapshot_date: Any = None,
    forecast_date: Any = None,
    fetched_at: Any = None,
) -> tuple[str | None, str, str]:
    """Resolve a date and its semantics without claiming strict PIT."""
    for value, semantics, quality in (
        (announcement_date, "announcement_date", "announcement_date_observed"),
        (snapshot_date, "provider_snapshot_date", "provider_snapshot_observed"),
        (forecast_date, "broker_forecast_date", "broker_forecast_date_observed"),
        (fetched_at, "fetched_at_snapshot_proxy", "fetch_time_proxy_non_pit"),
    ):
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
        if pd.notna(parsed):
            return pd.Timestamp(parsed).strftime("%Y-%m-%d"), semantics, quality
    return None, "missing_vintage_date", "undated_discovery"


def build_shkp_practical_vintage_snapshots(
    db_path: Path = FINANCIAL_DATA_DB_PATH,
    *,
    ticker: str = SHKP_TICKER,
) -> pd.DataFrame:
    """Build an append-only actual/consensus/forecast snapshot table.

    Three source lanes are retained:

    * actual financial observations use ``announcement_date`` when present,
      otherwise ``fetched_at`` as an explicitly labelled snapshot proxy;
    * consensus statistics use provider ``snapshot_date``;
    * broker rows use ``forecast_date`` while retaining the later fetch time.

    This does not reconstruct missing historical analyst vintages.  It makes
    all recoverable snapshots available to rough trend/backtest work and gives
    the model a measurable gap instead of silently presenting one current
    snapshot as a history.
    """
    rows: list[dict[str, Any]] = []

    def add_row(
        *,
        layer: str,
        source_row_id: Any,
        source_partition: Any,
        metric: Any = None,
        metric_label: Any = None,
        statistic: Any = None,
        statement_type: Any = None,
        period_end: Any = None,
        period_type: Any = None,
        estimate_period_end: Any = None,
        fiscal_year: Any = None,
        horizon: Any = None,
        value: Any = None,
        unit: Any = None,
        currency: Any = None,
        source: Any = None,
        snapshot_date: Any = None,
        announcement_date: Any = None,
        available_at: Any = None,
        forecast_date: Any = None,
        fetched_at: Any = None,
        contributor_count: Any = None,
        broker_name: Any = None,
        caveat: str = "",
    ) -> None:
        vintage_date, semantics, quality = _practical_vintage_date(
            announcement_date=announcement_date,
            snapshot_date=snapshot_date,
            forecast_date=forecast_date,
            fetched_at=fetched_at,
        )
        source_id = _text_or_none(source_row_id) or "unknown"
        vintage_id = _fact_id("practical_vintage", layer, source_id, vintage_date or "undated", source or "unknown")
        rows.append(
            {
                "vintage_id": vintage_id,
                "ticker": ticker,
                "layer": layer,
                "statement_type": _text_or_none(statement_type),
                "metric": _text_or_none(metric),
                "metric_label": _text_or_none(metric_label),
                "statistic": _text_or_none(statistic),
                "period_end": _coverage_date(period_end),
                "period_type": _text_or_none(period_type),
                "estimate_period_end": _coverage_date(estimate_period_end),
                "fiscal_year": fiscal_year,
                "horizon": _text_or_none(horizon),
                "value": pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0],
                "unit": _text_or_none(unit),
                "currency": _text_or_none(currency),
                "source": _text_or_none(source),
                "snapshot_date": _coverage_date(snapshot_date),
                "vintage_date": vintage_date,
                "vintage_date_semantics": semantics,
                "announcement_date": _coverage_date(announcement_date),
                "available_at": _text_or_none(available_at),
                "forecast_date": _coverage_date(forecast_date),
                "fetched_at": _text_or_none(fetched_at),
                "contributor_count": contributor_count,
                "broker_name": _text_or_none(broker_name),
                "source_row_id": source_id,
                "source_partition": _text_or_none(source_partition),
                "vintage_quality": quality,
                "model_use": (
                    "rough_snapshot_history"
                    if quality != "undated_discovery"
                    else "discovery_only"
                ),
                "caveat": caveat,
            }
        )

    actuals = _read_sibling_processed_history("financial_observations", db_path=db_path, ticker=ticker)
    for record in actuals.to_dict("records"):
        add_row(
            layer="actual",
            source_row_id=record.get("observation_id"),
            source_partition=record.get("source_partition"),
            statement_type=record.get("statement_type"),
            metric=record.get("metric"),
            metric_label=record.get("metric_label"),
            period_end=record.get("fiscal_period_end"),
            period_type=record.get("period_type"),
            value=record.get("value"),
            unit=record.get("unit"),
            currency=record.get("currency"),
            source=record.get("source"),
            announcement_date=record.get("announcement_date"),
            available_at=record.get("available_at"),
            fetched_at=record.get("fetched_at"),
            caveat=(
                "Actual observation from sibling processed partition. Original announcement date is used when present; "
                "otherwise fetched_at is only a snapshot proxy and is not a strict PIT release date."
            ),
        )

    consensus = _read_sibling_processed_history("consensus_statistics", db_path=db_path, ticker=ticker)
    for record in consensus.to_dict("records"):
        add_row(
            layer="consensus",
            source_row_id=record.get("consensus_statistic_id"),
            source_partition=record.get("source_partition"),
            metric=record.get("metric"),
            statistic=record.get("statistic"),
            period_end=record.get("estimate_period_end"),
            estimate_period_end=record.get("estimate_period_end"),
            fiscal_year=record.get("fiscal_year"),
            horizon=record.get("horizon"),
            value=record.get("value"),
            unit=record.get("unit"),
            currency=record.get("currency"),
            source=record.get("source"),
            snapshot_date=record.get("snapshot_date"),
            fetched_at=record.get("fetched_at"),
            contributor_count=record.get("contributor_count"),
            caveat=(
                "Provider consensus snapshot. Snapshot date is retained, but this lane cannot fill missing historical "
                "consensus vintages or infer an analyst estimate before that date."
            ),
        )

    brokers = _read_sibling_processed_history("broker_forecasts", db_path=db_path, ticker=ticker)
    for record in brokers.to_dict("records"):
        for metric, value, currency in (
            ("eps", record.get("eps"), record.get("eps_currency")),
            ("net_profit", record.get("net_profit"), record.get("net_profit_currency")),
            ("dividend", record.get("dividend"), record.get("dividend_currency")),
            ("target_price", record.get("target_price"), record.get("target_price_currency")),
        ):
            if pd.isna(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]):
                continue
            add_row(
                layer="broker_forecast",
                source_row_id=f"{record.get('forecast_id')}:{metric}",
                source_partition=record.get("source_partition"),
                metric=metric,
                fiscal_year=record.get("fiscal_year"),
                value=value,
                # Broker net_profit is stored by the sibling provider as an
                # absolute currency amount (typically HKD), not HKD millions.
                # Keep the raw magnitude and make the unit explicit.
                unit="per_share" if metric in {"eps", "dividend", "target_price"} else "currency",
                currency=currency or record.get("currency"),
                source=record.get("source"),
                forecast_date=record.get("forecast_date"),
                fetched_at=record.get("fetched_at"),
                broker_name=record.get("broker_name"),
                caveat=(
                    "Broker forecast date is retained as the practical vintage label; fetched_at may be later, so this "
                    "is not a complete historical analyst-information set."
                ),
            )

    frame = pd.DataFrame(rows, columns=SHKP_PRACTICAL_VINTAGE_COLUMNS)
    if frame.empty:
        return frame
    frame = frame.drop_duplicates(subset=["vintage_id"], keep="last").sort_values(
        ["vintage_date", "layer", "period_end", "metric"], na_position="last"
    ).reset_index(drop=True)
    frame.attrs["lineage_metadata"] = {
        "lineage_type": "derived_shkp_practical_financial_vintages",
        "source_datasets": ["financial_observations", "consensus_statistics", "broker_forecasts"],
        "canonical_financial_data_repo": str(Path(db_path).resolve()),
        "pit_policy": "practical_snapshot_history_not_strict_pit",
        "mainland_included": False,
    }
    return frame


def _coverage_date(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).strftime("%Y-%m-%d")


def _coverage_row(**values: Any) -> dict[str, Any]:
    row = {column: None for column in SHKP_VINTAGE_COVERAGE_COLUMNS}
    row.update(values)
    return row


def build_shkp_filing_vintages(
    corporate_documents: pd.DataFrame | None,
) -> pd.DataFrame:
    """Materialise document-level PIT availability without guessing dates.

    The issuer catalogue is useful for discovery, but most rows do not carry
    a publication timestamp.  Only the curated HKEX release timestamp is an
    exact PIT anchor.  An issuer-page date is retained as a date-only
    candidate, while undated rows remain discovery-only.  This table is
    intentionally evidence metadata rather than extracted financial facts.
    """
    documents = enrich_shkp_corporate_document_release_dates(
        corporate_documents if corporate_documents is not None else pd.DataFrame()
    )
    if documents.empty:
        return pd.DataFrame(columns=SHKP_FILING_VINTAGE_COLUMNS)

    rows: list[dict[str, Any]] = []
    for raw in documents.to_dict("records"):
        document_url = _text_or_none(raw.get("document_url"))
        title = _text_or_none(raw.get("title"))
        hkex_release_at = _text_or_none(raw.get("hkex_release_at"))
        issuer_release_date = _text_or_none(raw.get("issuer_release_date"))
        issuer_published_date = _text_or_none(raw.get("published_date"))

        # Prefer the exact HKEX timestamp.  The issuer release date is a
        # fallback only for daily/date-level analyses and is never promoted to
        # an exact release time.
        if hkex_release_at:
            availability_at = hkex_release_at
            availability_quality = "exact_hkex_release_timestamp"
            pit_date_usable = True
            pit_timestamp_usable = True
            model_use = "historical_pit_anchor"
            caveat = (
                "Exact HKEX publication timestamp is retained as the PIT anchor; "
                "the document content is available no earlier than this release."
            )
        elif issuer_release_date or issuer_published_date:
            availability_at = issuer_release_date or issuer_published_date
            availability_quality = "issuer_date_only"
            pit_date_usable = True
            pit_timestamp_usable = False
            model_use = "date_only_pit_candidate"
            caveat = (
                "Issuer catalogue date is retained for date-level review, but no "
                "exact public release timestamp was recovered; do not use for "
                "same-day event windows."
            )
        else:
            availability_at = None
            availability_quality = "undated_discovery"
            pit_date_usable = False
            pit_timestamp_usable = False
            model_use = "discovery_only"
            caveat = (
                "Document URL/type is available from the issuer catalogue, but no "
                "publication date or timestamp is known; it is not PIT-safe."
            )

        rows.append(
            {
                "vintage_id": _fact_id("filing_vintage", document_url or title or "unknown"),
                "ticker": SHKP_TICKER,
                "document_type": raw.get("document_type"),
                "document_semantics": raw.get("document_semantics"),
                "title": title,
                "document_url": document_url,
                "source_page_url": raw.get("source_page_url"),
                "source_url": raw.get("source_url") or raw.get("source_page_url"),
                "reporting_period_end": raw.get("reporting_period_end"),
                "issuer_published_date": issuer_published_date,
                "issuer_release_date": issuer_release_date,
                "hkex_release_at": hkex_release_at,
                "availability_at": availability_at,
                "availability_quality": availability_quality,
                "pit_date_usable": pit_date_usable,
                "pit_timestamp_usable": pit_timestamp_usable,
                "model_use": model_use,
                "release_evidence_type": raw.get("release_evidence_type"),
                "release_source_url": raw.get("release_source_url"),
                "fetched_at": raw.get("fetched_at"),
                "source_role": "official_company_document_catalog",
                "caveat": caveat,
            }
        )

    frame = pd.DataFrame(rows, columns=SHKP_FILING_VINTAGE_COLUMNS)
    if frame["vintage_id"].duplicated().any():
        raise ValueError("SHKP filing-vintage ids must be unique")
    return frame


def build_shkp_vintage_coverage(
    *,
    disclosed_facts: pd.DataFrame,
    financial_data_actuals: pd.DataFrame,
    consensus: pd.DataFrame,
    broker_forecasts: pd.DataFrame | None = None,
    consensus_revisions: pd.DataFrame | None = None,
    practical_vintages: pd.DataFrame | None = None,
    corporate_documents: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Summarize which model layers are actually safe for point-in-time use.

    This is intentionally a coverage contract rather than a score.  A layer
    may have useful historical period labels while still being unsuitable for
    a historical backtest when the original announcement/vintage date is
    absent.
    """
    rows: list[dict[str, Any]] = []
    actuals = financial_data_actuals.copy() if financial_data_actuals is not None else pd.DataFrame()
    actual_periods = pd.to_datetime(actuals.get("period_end"), errors="coerce") if not actuals.empty else pd.Series(dtype="datetime64[ns]")
    actual_available = pd.to_datetime(actuals.get("available_at"), errors="coerce", utc=True) if not actuals.empty else pd.Series(dtype="datetime64[ns, UTC]")
    actual_announcement = pd.to_datetime(actuals.get("announcement_date"), errors="coerce") if not actuals.empty else pd.Series(dtype="datetime64[ns]")
    actuals_ann_pct = float(actual_announcement.notna().mean() * 100.0) if not actuals.empty else 0.0
    rows.append(_coverage_row(
        coverage_id=_fact_id("vintage", "financial_data_actuals"),
        ticker=SHKP_TICKER,
        layer="financial_data_actuals",
        source="financial-data.latest_restated_financial_facts",
        row_count=int(len(actuals)),
        distinct_snapshot_count=int(actual_available.dt.date.nunique()) if not actual_available.empty else 0,
        distinct_period_count=int(actual_periods.dt.date.nunique()) if not actual_periods.empty else 0,
        period_start=_coverage_date(actual_periods.min()) if not actual_periods.empty else None,
        period_end=_coverage_date(actual_periods.max()) if not actual_periods.empty else None,
        snapshot_start=_coverage_date(actual_available.min()) if not actual_available.empty else None,
        snapshot_end=_coverage_date(actual_available.max()) if not actual_available.empty else None,
        fetched_at_distinct_count=int(pd.to_datetime(actuals.get("fetched_at"), errors="coerce", utc=True).dt.date.nunique()) if not actuals.empty else 0,
        announcement_date_coverage_pct=actuals_ann_pct,
        point_in_time_quality="low_missing_announcement_date" if actuals_ann_pct < 100 else "source_labelled",
        status="not_pit_safe_missing_announcement_dates" if actuals_ann_pct < 100 else "review_required",
        model_use="historical_context_only",
        caveat="Fiscal period labels and fetch-time availability are present, but original announcement dates are absent in the current sibling snapshot; do not use as if known on each historical date.",
    ))

    consensus_frame = consensus.copy() if consensus is not None else pd.DataFrame()
    consensus_snapshots = pd.to_datetime(consensus_frame.get("snapshot_date"), errors="coerce") if not consensus_frame.empty else pd.Series(dtype="datetime64[ns]")
    consensus_periods = pd.to_datetime(consensus_frame.get("estimate_period_end"), errors="coerce") if not consensus_frame.empty else pd.Series(dtype="datetime64[ns]")
    consensus_fy = consensus_frame.get("fiscal_year", pd.Series(dtype="Int64")) if not consensus_frame.empty else pd.Series(dtype="Int64")
    estimate_pct = float(consensus_periods.notna().mean() * 100.0) if not consensus_frame.empty else 0.0
    rows.append(_coverage_row(
        coverage_id=_fact_id("vintage", "consensus_statistics"),
        ticker=SHKP_TICKER,
        layer="consensus_statistics",
        source="financial-data.consensus_statistics_history",
        row_count=int(len(consensus_frame)),
        distinct_snapshot_count=int(consensus_snapshots.dt.date.nunique()) if not consensus_snapshots.empty else 0,
        distinct_period_count=int(consensus_fy.dropna().nunique()) if not consensus_frame.empty else 0,
        period_start=_coverage_date(consensus_periods.min()) if consensus_periods.notna().any() else None,
        period_end=_coverage_date(consensus_periods.max()) if consensus_periods.notna().any() else None,
        snapshot_start=_coverage_date(consensus_snapshots.min()) if not consensus_snapshots.empty else None,
        snapshot_end=_coverage_date(consensus_snapshots.max()) if not consensus_snapshots.empty else None,
        fetched_at_distinct_count=int(pd.to_datetime(consensus_frame.get("fetched_at"), errors="coerce", utc=True).dt.date.nunique()) if not consensus_frame.empty else 0,
        estimate_period_end_coverage_pct=estimate_pct,
        point_in_time_quality="single_snapshot_period_end_missing" if consensus_snapshots.dt.date.nunique() <= 1 or estimate_pct < 100 else "dated_snapshot",
        status="current_snapshot_only" if consensus_snapshots.dt.date.nunique() <= 1 else "revision_history_partial",
        model_use="current_scenario_input_only",
        caveat="The current non-null statistics are a single 2026-07-26 snapshot; fiscal_year is retained but estimate_period_end is missing, so this is not a backtestable historical consensus series.",
    ))

    broker = broker_forecasts.copy() if broker_forecasts is not None else pd.DataFrame()
    broker_dates = pd.to_datetime(broker.get("forecast_date"), errors="coerce") if not broker.empty else pd.Series(dtype="datetime64[ns]")
    broker_fetched = pd.to_datetime(broker.get("fetched_at"), errors="coerce", utc=True) if not broker.empty else pd.Series(dtype="datetime64[ns, UTC]")
    rows.append(_coverage_row(
        coverage_id=_fact_id("vintage", "broker_forecasts"),
        ticker=SHKP_TICKER,
        layer="broker_forecasts",
        source="financial-data.broker_forecasts",
        row_count=int(len(broker)),
        distinct_snapshot_count=int(broker_dates.dt.date.nunique()) if not broker_dates.empty else 0,
        distinct_period_count=int(broker.get("fiscal_year", pd.Series(dtype="Int64")).dropna().nunique()) if not broker.empty else 0,
        period_start=_coverage_date(broker_dates.min()) if not broker_dates.empty else None,
        period_end=_coverage_date(broker_dates.max()) if not broker_dates.empty else None,
        snapshot_start=_coverage_date(broker_dates.min()) if not broker_dates.empty else None,
        snapshot_end=_coverage_date(broker_dates.max()) if not broker_dates.empty else None,
        fetched_at_distinct_count=int(broker_fetched.dt.date.nunique()) if not broker_fetched.empty else 0,
        point_in_time_quality="forecast_date_with_later_fetch_time" if not broker.empty else "not_available",
        status="dated_rows_not_full_revision_history" if not broker.empty else "not_available",
        model_use="cross_sectional_scenario_input_only",
        caveat="Broker rows carry forecast_date and fiscal_year, but the current extraction was fetched in one batch and does not prove what was known at each forecast date.",
    ))

    revisions = consensus_revisions.copy() if consensus_revisions is not None else pd.DataFrame()
    revision_dates = pd.to_datetime(revisions.get("snapshot_date"), errors="coerce") if not revisions.empty else pd.Series(dtype="datetime64[ns]")
    revision_fields = ["eps_avg_revision", "revenue_avg_revision", "target_price_avg_revision"]
    revision_signal_rows = int(revisions[revision_fields].notna().any(axis=1).sum()) if not revisions.empty and set(revision_fields).issubset(revisions.columns) else 0
    rows.append(_coverage_row(
        coverage_id=_fact_id("vintage", "consensus_revisions"),
        ticker=SHKP_TICKER,
        layer="consensus_revisions",
        source="financial-data.consensus_revisions",
        row_count=int(len(revisions)),
        distinct_snapshot_count=int(revision_dates.dt.date.nunique()) if not revision_dates.empty else 0,
        distinct_period_count=int(revisions.get("fiscal_year", pd.Series(dtype="Int64")).dropna().nunique()) if not revisions.empty else 0,
        snapshot_start=_coverage_date(revision_dates.min()) if not revision_dates.empty else None,
        snapshot_end=_coverage_date(revision_dates.max()) if not revision_dates.empty else None,
        fetched_at_distinct_count=int(pd.to_datetime(revisions.get("fetched_at"), errors="coerce", utc=True).dt.date.nunique()) if not revisions.empty else 0,
        revision_signal_rows=revision_signal_rows,
        point_in_time_quality="single_snapshot_diagnostic" if not revisions.empty else "not_available",
        status="single_snapshot_diagnostic_only" if not revisions.empty else "not_available",
        model_use="diagnostic_only",
        caveat="Revision columns are provider diagnostics within the available snapshot, not a sequence of dated consensus vintages.",
    ))

    practical = practical_vintages.copy() if practical_vintages is not None else pd.DataFrame()
    practical_dates = pd.to_datetime(practical.get("vintage_date"), errors="coerce") if not practical.empty else pd.Series(dtype="datetime64[ns]")
    practical_layers = practical.get("layer", pd.Series(dtype="string")) if not practical.empty else pd.Series(dtype="string")
    practical_quality = practical.get("vintage_quality", pd.Series(dtype="string")) if not practical.empty else pd.Series(dtype="string")
    rows.append(_coverage_row(
        coverage_id=_fact_id("vintage", "practical_snapshot_vintages"),
        ticker=SHKP_TICKER,
        layer="practical_snapshot_vintages",
        source="financial-data.processed append-only partitions",
        row_count=int(len(practical)),
        distinct_snapshot_count=int(practical_dates.dt.date.nunique()) if not practical_dates.empty else 0,
        distinct_period_count=int(pd.to_datetime(practical.get("period_end"), errors="coerce").dt.date.nunique()) if not practical.empty and "period_end" in practical.columns else 0,
        period_start=_coverage_date(pd.to_datetime(practical.get("period_end"), errors="coerce").min()) if not practical.empty and "period_end" in practical.columns else None,
        period_end=_coverage_date(pd.to_datetime(practical.get("period_end"), errors="coerce").max()) if not practical.empty and "period_end" in practical.columns else None,
        snapshot_start=_coverage_date(practical_dates.min()) if not practical_dates.empty else None,
        snapshot_end=_coverage_date(practical_dates.max()) if not practical_dates.empty else None,
        fetched_at_distinct_count=int(pd.to_datetime(practical.get("fetched_at"), errors="coerce", utc=True).dt.date.nunique()) if not practical.empty and "fetched_at" in practical.columns else 0,
        announcement_date_coverage_pct=float(pd.to_datetime(practical.get("announcement_date"), errors="coerce").notna().mean() * 100.0) if not practical.empty and "announcement_date" in practical.columns else 0.0,
        estimate_period_end_coverage_pct=float(pd.to_datetime(practical.get("estimate_period_end"), errors="coerce").notna().mean() * 100.0) if not practical.empty and "estimate_period_end" in practical.columns else 0.0,
        point_in_time_quality=(
            "mixed_announcement_provider_and_fetch_snapshot_dates"
            if practical_quality.astype(str).isin({"announcement_date_observed", "provider_snapshot_observed"}).any()
            else "fetch_snapshot_proxy_only"
            if not practical.empty
            else "not_available"
        ),
        status=(
            "usable_snapshot_history_not_strict_pit"
            if not practical.empty and practical_dates.notna().any()
            else "not_available"
        ),
        model_use="rough_snapshot_history_and_non_pit_backtest_context" if not practical.empty else "not_available",
        caveat=(
            "Append-only practical snapshot layer. It preserves recoverable announcement/provider/forecast dates and "
            "uses fetched_at only as a labelled fallback; it does not reconstruct missing historical consensus vintages "
            "or claim strict PIT availability."
            if not practical.empty
            else "No sibling processed snapshot partitions were available."
        ),
    ))

    disclosed = disclosed_facts.copy() if disclosed_facts is not None else pd.DataFrame()
    disclosed_available = pd.to_datetime(disclosed.get("available_at"), errors="coerce") if not disclosed.empty else pd.Series(dtype="datetime64[ns]")
    disclosed_periods = pd.to_datetime(disclosed.get("period_end"), errors="coerce") if not disclosed.empty else pd.Series(dtype="datetime64[ns]")
    rows.append(_coverage_row(
        coverage_id=_fact_id("vintage", "official_disclosed_facts"),
        ticker=SHKP_TICKER,
        layer="official_disclosed_facts",
        source="SHKP official investor-relations disclosures",
        row_count=int(len(disclosed)),
        distinct_snapshot_count=int(disclosed_available.dt.date.nunique()) if not disclosed_available.empty else 0,
        distinct_period_count=int(disclosed_periods.dt.date.nunique()) if not disclosed_periods.empty else 0,
        period_start=_coverage_date(disclosed_periods.min()) if not disclosed_periods.empty else None,
        period_end=_coverage_date(disclosed_periods.max()) if not disclosed_periods.empty else None,
        snapshot_start=_coverage_date(disclosed_available.min()) if not disclosed_available.empty else None,
        snapshot_end=_coverage_date(disclosed_available.max()) if not disclosed_available.empty else None,
        point_in_time_quality="mixed_official_disclosure_dates",
        status="official_facts_with_static_summary_vintage_gap",
        model_use="historical_context_and_forecast_anchor",
        caveat="Official source URLs and availability dates are retained, but the five-year summary rows are not first-available historical vintages.",
    ))

    documents = enrich_shkp_corporate_document_release_dates(
        corporate_documents if corporate_documents is not None else pd.DataFrame()
    )
    published_dates = pd.to_datetime(documents.get("published_date"), errors="coerce") if not documents.empty else pd.Series(dtype="datetime64[ns]")
    release_dates = pd.to_datetime(documents.get("hkex_release_at"), errors="coerce", utc=True) if not documents.empty else pd.Series(dtype="datetime64[ns, UTC]")
    release_date_pct = float(release_dates.notna().mean() * 100.0) if not documents.empty else 0.0
    availability_dates = release_dates.where(release_dates.notna(), pd.to_datetime(documents.get("published_date"), errors="coerce", utc=True)) if not documents.empty else pd.Series(dtype="datetime64[ns, UTC]")
    document_fetched = pd.to_datetime(documents.get("fetched_at"), errors="coerce", utc=True) if not documents.empty else pd.Series(dtype="datetime64[ns, UTC]")
    published_pct = float(published_dates.notna().mean() * 100.0) if not documents.empty else 0.0
    rows.append(_coverage_row(
        coverage_id=_fact_id("vintage", "corporate_documents"),
        ticker=SHKP_TICKER,
        layer="corporate_documents",
        source="SHKP official investor-relations document catalogue",
        row_count=int(len(documents)),
        distinct_snapshot_count=int(availability_dates.dt.date.nunique()) if not availability_dates.empty else 0,
        distinct_period_count=int(documents.get("document_type", pd.Series(dtype="string")).dropna().nunique()) if not documents.empty else 0,
        fetched_at_distinct_count=int(document_fetched.dt.date.nunique()) if not document_fetched.empty else 0,
        announcement_date_coverage_pct=published_pct,
        release_date_coverage_pct=release_date_pct,
        snapshot_start=_coverage_date(availability_dates.min()) if not availability_dates.empty else None,
        snapshot_end=_coverage_date(availability_dates.max()) if not availability_dates.empty else None,
        point_in_time_quality=(
            "curated_hkex_release_dates_partial"
            if release_date_pct > 0
            else "document_catalog_published_date_missing"
            if published_pct < 100
            else "document_catalog_dated"
        ),
        status=(
            "filing_catalog_partial_release_dates"
            if release_date_pct > 0 and release_date_pct < 100
            else "filing_catalog_release_dated"
            if release_date_pct == 100
            else "filing_discovery_only_missing_publication_dates"
            if published_pct < 100
            else "filing_catalog_dated"
        ),
        model_use="filing_release_date_anchor_for_matched_documents" if release_date_pct > 0 else "filing_discovery_only",
        caveat=(
            f"Curated HKEX release timestamps cover {release_date_pct:.1f}% of catalogue rows; matched results/annual/interim documents can use hkex_release_at as PIT availability, while unknown rows remain discovery-only."
            if release_date_pct > 0
            else "The official catalogue contains document URLs and document types, but the current rows have no populated published_date; publication timing must be recovered from the issuer page/PDF metadata before use as a release-date vintage."
        ),
    ))
    return pd.DataFrame(rows, columns=SHKP_VINTAGE_COVERAGE_COLUMNS)


def build_shkp_capital_inputs(
    financial_data_actuals: pd.DataFrame,
) -> pd.DataFrame:
    """Select debt, cash, capex, property and interest inputs for NAV/FCF."""
    if financial_data_actuals is None or financial_data_actuals.empty:
        return pd.DataFrame(columns=SHKP_FINANCIAL_DATA_FACT_COLUMNS)
    mask = pd.Series(False, index=financial_data_actuals.index)
    for statement_type, metrics in _CAPITAL_MODEL_METRICS.items():
        mask |= (
            financial_data_actuals["statement_type"].eq(statement_type)
            & financial_data_actuals["metric"].isin(metrics)
        )
    frame = financial_data_actuals.loc[mask].copy()
    frame["model_use"] = "capital_nav_cashflow_input"
    frame["caveat"] = frame.apply(
        lambda row: (
            "Source-selected balance-sheet/cash-flow fact; check currency semantics and period type before valuation."
            if row["statement_type"] in {"balance_sheet", "cash_flow"}
            else "Interest/tax income-statement input; do not mix with segment operating profit."
        ),
        axis=1,
    )
    return frame.reindex(columns=SHKP_FINANCIAL_DATA_FACT_COLUMNS)


def build_shkp_capital_input_quality(
    capital_inputs: pd.DataFrame,
) -> pd.DataFrame:
    """Make financial-data unit/quality semantics explicit for NAV/FCF use.

    The sibling database reports monetary values with ``unit='currency'`` and
    HKD absolute amounts (e.g. 398,729,000,000), while the curated SHKP
    disclosure layer uses ``HKD_m`` (e.g. 398,729).  Preserve the raw value and
    add a non-destructive HKD-million view so cross-source checks cannot fail
    silently by a factor of one million.
    """
    if capital_inputs is None or capital_inputs.empty:
        return pd.DataFrame(columns=SHKP_CAPITAL_INPUT_QUALITY_COLUMNS)
    frame = capital_inputs.copy()
    frame["raw_value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["raw_unit"] = frame["unit"]
    frame["normalized_value_hkd_m"] = pd.NA
    frame["normalization_policy"] = "not_normalized"
    hkd_absolute = frame["currency"].astype("string").eq("HKD") & frame["unit"].astype("string").eq("currency")
    frame.loc[hkd_absolute, "normalized_value_hkd_m"] = frame.loc[hkd_absolute, "raw_value"] / 1_000_000.0
    frame.loc[hkd_absolute, "normalization_policy"] = "HKD_absolute_currency_divided_by_1e6"
    frame["quality_status"] = "scaled_vendor_context_only"
    frame.loc[frame["raw_value"].isna(), "quality_status"] = "invalid_numeric_value"
    frame.loc[frame["announcement_date"].isna(), "quality_status"] = "scaled_vendor_context_no_announcement_date"
    frame["model_use"] = "normalized_context_only_until_official_reconciliation"
    frame["caveat"] = (
        "Raw financial-data value is preserved. normalized_value_hkd_m is a unit conversion only; "
        "source rows are yfinance/low point-in-time quality and lack original announcement dates."
    )
    # Keep ``value`` in the source frame only as an input; the output contract
    # exposes the explicitly named ``raw_value`` column.
    return frame.reindex(columns=SHKP_CAPITAL_INPUT_QUALITY_COLUMNS).assign(
        quality_id=lambda value: value.apply(
            lambda row: _fact_id("capital_quality", row["metric"], row["period_end"]), axis=1
        ),
        ticker=SHKP_TICKER,
    )


def build_shkp_financial_reconciliation(
    *,
    disclosed_facts: pd.DataFrame,
    financial_data_actuals: pd.DataFrame,
) -> pd.DataFrame:
    """Reconcile overlapping official HKD-million facts after unit conversion."""
    mappings = {
        "group_revenue": ("income_statement", "revenue"),
        "investment_properties": ("balance_sheet", "investment_properties"),
    }
    official = disclosed_facts.copy() if disclosed_facts is not None else pd.DataFrame()
    actuals = financial_data_actuals.copy() if financial_data_actuals is not None else pd.DataFrame()
    if official.empty or actuals.empty:
        return pd.DataFrame(columns=SHKP_FINANCIAL_RECONCILIATION_COLUMNS)
    official["period_end"] = pd.to_datetime(official["period_end"], errors="coerce").dt.strftime("%Y-%m-%d")
    actuals["period_end"] = pd.to_datetime(actuals["period_end"], errors="coerce").dt.strftime("%Y-%m-%d")
    actuals["value"] = pd.to_numeric(actuals["value"], errors="coerce")
    rows: list[dict[str, Any]] = []
    for official_metric, (statement_type, actual_metric) in mappings.items():
        official_rows = official.loc[official["metric"].eq(official_metric)].copy()
        actual_rows = actuals.loc[
            actuals["statement_type"].eq(statement_type) & actuals["metric"].eq(actual_metric)
        ].copy()
        if official_rows.empty or actual_rows.empty:
            continue
        for _, official_row in official_rows.iterrows():
            matches = actual_rows.loc[actual_rows["period_end"].eq(official_row["period_end"])]
            if matches.empty:
                continue
            if "source_priority" in matches.columns:
                matches = matches.assign(
                    _source_priority_num=pd.to_numeric(matches["source_priority"], errors="coerce")
                ).sort_values("_source_priority_num", na_position="last")
            actual_row = matches.iloc[0]
            official_value = pd.to_numeric(pd.Series([official_row["value"]]), errors="coerce").iloc[0]
            raw_value = actual_row["value"]
            if pd.isna(official_value) or pd.isna(raw_value):
                continue
            actual_unit = str(actual_row.get("unit") or "").strip().lower()
            actual_currency = str(actual_row.get("currency") or "").strip().upper()
            if actual_currency == "HKD" and actual_unit == "currency":
                actual_hkd_m = float(raw_value) / 1_000_000.0
                unit_status = "unit_normalized"
            elif actual_currency == "HKD" and actual_unit in {"hkd_m", "hkd_million", "million_hkd"}:
                actual_hkd_m = float(raw_value)
                unit_status = "unit_already_hkd_m"
            elif not actual_unit and actual_currency in {"", "HKD"}:
                # Preserve compatibility with older normalized snapshots that
                # omitted the vendor unit metadata.  This remains an explicit
                # assumption and should be replaced when the source unit is
                # available.
                actual_hkd_m = float(raw_value) / 1_000_000.0
                unit_status = "unit_missing_legacy_assumption"
            else:
                actual_hkd_m = None
                unit_status = "unit_review_required"
            diff_pct = (
                (actual_hkd_m / float(official_value) - 1.0) * 100.0
                if actual_hkd_m is not None and float(official_value)
                else None
            )
            status = (
                "reconciled_after_unit_normalization"
                if unit_status != "unit_review_required" and diff_pct is not None and abs(diff_pct) <= 0.5
                else unit_status
                if unit_status == "unit_review_required"
                else "difference_review"
            )
            rows.append({
                "reconciliation_id": _fact_id("reconciliation", official_metric, official_row["period_end"]),
                "ticker": SHKP_TICKER,
                "metric": official_metric,
                "period_end": official_row["period_end"],
                "official_value_hkd_m": float(official_value),
                "financial_data_value_raw_hkd": float(raw_value),
                "financial_data_value_hkd_m": actual_hkd_m,
                "difference_pct": diff_pct,
                "official_source_role": official_row.get("source_role"),
                "financial_data_source": actual_row.get("source"),
                "status": status,
                "caveat": "Reconciliation is arithmetic/unit validation only; financial-data rows still lack original announcement dates and are not promoted to official PIT facts.",
            })
    return pd.DataFrame(rows, columns=SHKP_FINANCIAL_RECONCILIATION_COLUMNS)


def load_shkp_dividends(
    db_path: Path = FINANCIAL_DATA_DB_PATH,
    *,
    ticker: str = SHKP_TICKER,
) -> pd.DataFrame:
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"financial-data DuckDB not found: {path}")
    duckdb = _require_duckdb()
    with duckdb.connect(str(path), read_only=True) as connection:
        frame = connection.execute(
            """
            SELECT observation_id, ticker, ex_date, payment_date, amount,
                   currency, source, fetched_at
            FROM dividend_observations
            WHERE ticker = ?
            ORDER BY ex_date
            """,
            [ticker],
        ).df()
    return frame.reindex(columns=SHKP_DIVIDEND_COLUMNS)


def load_shkp_market_snapshot(
    db_path: Path = FINANCIAL_DATA_DB_PATH,
    *,
    ticker: str = SHKP_TICKER,
) -> pd.DataFrame:
    """Extract the latest market snapshot without treating it as price history."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"financial-data DuckDB not found: {path}")
    duckdb = _require_duckdb()
    try:
        with duckdb.connect(str(path), read_only=True) as connection:
            frame = connection.execute(
                """
                SELECT metadata_id, ticker, as_of_date, currency, market_cap,
                       shares_outstanding, source, fetched_at, raw_json
                FROM company_metadata
                WHERE ticker = ?
                ORDER BY as_of_date DESC, fetched_at DESC
                LIMIT 1
                """,
                [ticker],
            ).df()
    except Exception as exc:
        # A reviewed financial-data snapshot may omit the optional metadata
        # table; do not fabricate market values in that case.
        if "company_metadata" in str(exc).lower() or "catalog" in str(exc).lower():
            return pd.DataFrame(columns=SHKP_MARKET_SNAPSHOT_COLUMNS)
        raise
    if frame.empty:
        return pd.DataFrame(columns=SHKP_MARKET_SNAPSHOT_COLUMNS)
    raw: dict[str, Any] = {}
    try:
        raw = json.loads(str(frame.iloc[0].get("raw_json") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        raw = {}
    row = frame.iloc[0].to_dict()
    result = {
        "metadata_id": row.get("metadata_id"),
        "ticker": row.get("ticker"),
        "as_of_date": row.get("as_of_date"),
        "currency": row.get("currency"),
        "market_cap": row.get("market_cap"),
        "enterprise_value": raw.get("enterpriseValue"),
        "shares_outstanding": row.get("shares_outstanding") or raw.get("sharesOutstanding"),
        "current_price": raw.get("currentPrice") or raw.get("regularMarketPrice"),
        "book_value_per_share": raw.get("bookValue"),
        "trailing_eps": raw.get("trailingEps"),
        "forward_eps": raw.get("forwardEps"),
        "source": row.get("source"),
        "fetched_at": row.get("fetched_at"),
        "snapshot_quality": "current_market_snapshot",
        "caveat": "Snapshot only; financial-data does not own a historical daily-price series.",
    }
    return pd.DataFrame([result], columns=SHKP_MARKET_SNAPSHOT_COLUMNS)


def load_shkp_price_history() -> pd.DataFrame:
    """Load the latest non-empty persisted price history, if one exists.

    This function never performs a network fetch.  A model run that needs a
    fresh vendor series must call ``run_shkp_price_history`` (or pass
    ``include_price_history=True`` to ``run_shkp_financial_model``).
    """
    frame = load_latest_normalized(SHKP_PRICE_HISTORY_DATASET)
    if frame.empty:
        return pd.DataFrame(columns=SHKP_PRICE_HISTORY_COLUMNS)
    missing = sorted(set(SHKP_PRICE_HISTORY_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(
            f"Persisted SHKP price history is missing contract columns: {', '.join(missing)}"
        )
    return frame.reindex(columns=SHKP_PRICE_HISTORY_COLUMNS)


def validate_shkp_financial_model_inputs(
    *,
    disclosed_facts: pd.DataFrame,
    financial_data_actuals: pd.DataFrame,
    consensus: pd.DataFrame,
    price_history: pd.DataFrame | None = None,
    recurring_portfolio: pd.DataFrame | None = None,
    require_financial_data: bool = True,
) -> dict[str, Any]:
    """Validate the first-stage model boundary without calculating forecasts."""
    errors: list[str] = []
    warnings: list[str] = []
    if disclosed_facts.empty:
        errors.append("disclosed_facts is empty")
    required_groups = {"segment_financials", "consolidated_financials", "contracted_sales_backlog", "future_growth_pipeline"}
    missing_groups = sorted(required_groups - set(disclosed_facts.get("fact_group", pd.Series(dtype=str))))
    if missing_groups:
        errors.append("disclosed_facts missing groups: " + ", ".join(missing_groups))
    if not disclosed_facts.empty:
        if disclosed_facts.duplicated(["fact_id"]).any():
            errors.append("disclosed_facts contains duplicate fact_id values")
        if disclosed_facts["source_url"].astype("string").str.strip().eq("").any():
            errors.append("disclosed_facts contains a row without source_url")
        invalid_periods = pd.to_datetime(disclosed_facts["period_end"], errors="coerce").isna()
        if invalid_periods.any():
            errors.append("disclosed_facts contains invalid period_end")
        backlog = disclosed_facts["fact_group"].eq("contracted_sales_backlog")
        if disclosed_facts.loc[backlog, "metric"].astype("string").str.contains("revenue", case=False).any():
            errors.append("contracted sales backlog must not be labelled revenue")
    if financial_data_actuals.empty:
        (errors if require_financial_data else warnings).append(
            "financial_data_actuals is empty"
            if require_financial_data
            else "financial_data_actuals was not loaded; official-only model inputs are not a complete financial-data refresh"
        )
    if not financial_data_actuals.empty and financial_data_actuals["ticker"].astype(str).ne(SHKP_TICKER).any():
        errors.append("financial_data_actuals contains a non-SHKP ticker")
    if not financial_data_actuals.empty and "announcement_date" in financial_data_actuals.columns:
        announcement_dates = pd.to_datetime(financial_data_actuals["announcement_date"], errors="coerce")
        if announcement_dates.isna().all():
            warnings.append(
                "financial_data_actuals has no original announcement_date; available_at is fetch-time metadata, not a PIT release date"
            )
    if (
        not financial_data_actuals.empty
        and "fact_id" in financial_data_actuals.columns
        and financial_data_actuals.duplicated(["fact_id"]).any()
    ):
        errors.append("financial_data_actuals contains duplicate fact_id values")
    if consensus.empty:
        (errors if require_financial_data else warnings).append(
            "consensus is empty"
            if require_financial_data
            else "consensus was not loaded; official-only model inputs cannot support a consensus comparison"
        )
    if not consensus.empty:
        consensus_key = ["ticker", "snapshot_date", "fiscal_year", "horizon", "metric", "statistic", "source"]
        if set(consensus_key).issubset(consensus.columns) and consensus.duplicated(consensus_key).any():
            errors.append("consensus contains duplicate snapshot/metric keys")
        if "estimate_period_end" in consensus.columns and consensus["estimate_period_end"].isna().any():
            warnings.append(
                f"{int(consensus['estimate_period_end'].isna().sum())} consensus rows lack estimate_period_end; fiscal_year is the only period anchor"
            )
        if "snapshot_date" in consensus.columns and consensus["snapshot_date"].nunique(dropna=True) <= 1:
            warnings.append(
                "consensus contains only one snapshot date; it is suitable for current scenarios, not historical revision backtests"
            )
    price_rows = int(len(price_history)) if price_history is not None else 0
    if price_rows == 0:
        warnings.append(
            "price_history is not materialized; market_snapshot is current-only and cannot support an equity backtest"
        )
    elif price_history is not None:
        required_price = set(SHKP_PRICE_HISTORY_COLUMNS)
        missing_price = sorted(required_price - set(price_history.columns))
        if missing_price:
            errors.append("price_history missing contract columns: " + ", ".join(missing_price))
        else:
            if price_history["ticker"].astype(str).ne(SHKP_TICKER).any():
                errors.append("price_history contains a non-SHKP ticker")
            if price_history.duplicated(["ticker", "trading_date"]).any():
                errors.append("price_history contains duplicate ticker/trading_date keys")
            trading_dates = pd.to_datetime(price_history["trading_date"], errors="coerce", utc=True)
            fetched_dates = pd.to_datetime(price_history["fetched_at"], errors="coerce", utc=True)
            if trading_dates.isna().any():
                errors.append("price_history contains invalid trading_date")
            if fetched_dates.isna().any():
                errors.append("price_history contains invalid fetched_at")
            if "adj_close" in price_history and price_history["adj_close"].isna().any():
                errors.append("price_history contains null adj_close")
            if "total_return_index" in price_history and price_history["total_return_index"].isna().any():
                errors.append("price_history contains null total_return_index")
            if not trading_dates.isna().any() and not fetched_dates.isna().any():
                fetched_days = fetched_dates.dt.tz_localize(None).dt.normalize()
                trading_days = trading_dates.dt.tz_localize(None).dt.normalize()
                if (trading_days > fetched_days).any():
                    errors.append("price_history contains a trading_date after its fetched_at")
    recurring_rows = int(len(recurring_portfolio)) if recurring_portfolio is not None else 0
    if recurring_portfolio is not None and not recurring_portfolio.empty:
        missing_recurring = sorted(set(SHKP_RECURRING_PORTFOLIO_COLUMNS) - set(recurring_portfolio.columns))
        if missing_recurring:
            errors.append("recurring_portfolio missing contract columns: " + ", ".join(missing_recurring))
        else:
            if recurring_portfolio.duplicated(["fact_id"]).any():
                errors.append("recurring_portfolio contains duplicate fact_id values")
            if recurring_portfolio["source_url"].astype("string").str.strip().eq("").any():
                errors.append("recurring_portfolio contains a row without source_url")
            if pd.to_datetime(recurring_portfolio["period_end"], errors="coerce").isna().any():
                errors.append("recurring_portfolio contains invalid period_end")
            currencies = set(recurring_portfolio["currency"].dropna().astype(str))
            if "HKD" in currencies and "RMB" in currencies:
                warnings.append("recurring_portfolio contains both HKD and RMB rows; keep currencies separate in aggregation")
    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "disclosed_rows": int(len(disclosed_facts)),
        "financial_data_actual_rows": int(len(financial_data_actuals)),
        "consensus_rows": int(len(consensus)),
        "price_history_rows": price_rows,
        "recurring_portfolio_rows": recurring_rows,
        "financial_data_required": bool(require_financial_data),
        "ticker": SHKP_TICKER,
        "ownership_policy": "project activity remains non-attributable until an approved phase-specific effective interval exists",
    }


def build_shkp_project_model_bridge(
    project_activity: pd.DataFrame,
    project_registry: pd.DataFrame,
) -> pd.DataFrame:
    """Join project-month activity to SHKP model gates without over-attribution.

    ``project_activity`` may contain the pilot's legacy
    ``sales_value_attributable_hkd`` column.  It is intentionally ignored: only
    the registry's approved phase-specific interval can create
    ``attributable_sales_value_hkd``.  All other activity remains a leading
    indicator and can be compared to company-disclosed contracted sales, but
    cannot enter SHKP revenue/cash-flow totals.
    """
    if project_activity is None or project_activity.empty:
        return pd.DataFrame(columns=SHKP_PROJECT_MODEL_BRIDGE_COLUMNS)
    required = {"srpe_development_id", "period", "sales_value_gross_hkd"}
    missing = sorted(required - set(project_activity.columns))
    if missing:
        raise ValueError("project_activity missing required columns: " + ", ".join(missing))
    registry = project_registry.copy() if project_registry is not None else pd.DataFrame()
    if registry.empty or "srpe_development_id" not in registry.columns:
        raise ValueError("project_registry must contain a non-empty srpe_development_id column")

    activity = project_activity.copy()
    activity["srpe_development_id"] = activity["srpe_development_id"].astype("string").str.strip()
    activity["period"] = activity["period"].astype("string").str.strip()
    activity["sales_value_gross_hkd"] = pd.to_numeric(activity["sales_value_gross_hkd"], errors="coerce")
    # The SHKP-wide signal contract uses explicit month-end names.  Preserve
    # the older pilot names as an input compatibility layer so the financial
    # bridge can consume either contract without changing attribution policy.
    if "cumulative_unique_active_units" not in activity.columns and "active_units_eom" in activity.columns:
        activity["cumulative_unique_active_units"] = activity["active_units_eom"]
    if "total_residential_properties" not in activity.columns and "published_inventory_units" in activity.columns:
        activity["total_residential_properties"] = activity["published_inventory_units"]
    for column in ("sales_units_gross", "cancelled_units", "cumulative_unique_active_units", "total_residential_properties"):
        if column not in activity.columns:
            activity[column] = pd.NA
        activity[column] = pd.to_numeric(activity[column], errors="coerce")
    if "project_id" not in activity.columns:
        activity["project_id"] = pd.NA
    if "stock_code" not in activity.columns:
        activity["stock_code"] = pd.NA
    if "month_status" not in activity.columns:
        activity["month_status"] = "observed_project_activity"
    activity["month_status"] = activity["month_status"].fillna("").astype(str).str.strip()
    activity["_coverage_not_covered"] = activity["month_status"].eq("not_covered")
    group_columns = ["srpe_development_id", "project_id", "period", "stock_code"]
    activity = (
        activity.groupby(group_columns, dropna=False, as_index=False)
        .agg(
            sales_units_gross=("sales_units_gross", lambda values: values.sum(min_count=1)),
            sales_value_gross_hkd=("sales_value_gross_hkd", lambda values: values.sum(min_count=1)),
            cancelled_units=("cancelled_units", lambda values: values.sum(min_count=1)),
            cumulative_unique_active_units=("cumulative_unique_active_units", "max"),
            total_residential_properties=("total_residential_properties", "max"),
            coverage_not_covered=("_coverage_not_covered", "all"),
            coverage_has_covered=("_coverage_not_covered", lambda values: (~values).any()),
        )
    )
    registry["srpe_development_id"] = registry["srpe_development_id"].astype("string").str.strip()
    registry = registry.drop_duplicates("srpe_development_id", keep="last")
    join_columns = [
        "srpe_development_id",
        "ownership_status",
        "ownership_attribution_ready",
        "ownership_effective_from",
        "ownership_effective_to",
        "ownership_observed_pct",
        "curated_registry_ownership_pct",
        "annual_group_interest_pct",
        "ownership_interval_evidence_type",
        "ownership_attribution_decision_id",
        "ownership_interval_promotion_status",
        "decision_status",
    ]
    for column in join_columns:
        if column not in registry.columns:
            registry[column] = pd.NA
    merged = activity.merge(registry[join_columns], on="srpe_development_id", how="left")

    def _ownership_pct(row: pd.Series) -> float | None:
        for column in ("ownership_observed_pct", "curated_registry_ownership_pct", "annual_group_interest_pct"):
            value = pd.to_numeric(pd.Series([row.get(column)]), errors="coerce").iloc[0]
            if pd.notna(value) and 0 <= float(value) <= 100:
                return float(value)
        return None

    merged["ownership_pct_used"] = merged.apply(_ownership_pct, axis=1)
    merged["ownership_attribution_ready"] = merged.apply(
        _record_has_phase_specific_effective_interval,
        axis=1,
    )
    merged["sales_activity_status"] = "observed_project_activity"
    merged.loc[merged["coverage_not_covered"], "sales_activity_status"] = "not_covered"
    zero_activity = (
        merged["coverage_has_covered"]
        & merged["sales_units_gross"].fillna(0).eq(0)
        & merged["sales_value_gross_hkd"].fillna(0).eq(0)
    )
    merged.loc[zero_activity, "sales_activity_status"] = "observed_zero_activity"
    merged["model_attribution_status"] = "blocked_ownership_interval"
    merged["model_use"] = "leading_indicator_only"
    merged.loc[merged["sales_activity_status"].eq("not_covered"), "model_use"] = "coverage_gap_only"
    merged["attributable_sales_value_hkd"] = pd.NA
    ready = (
        merged["sales_activity_status"].ne("not_covered")
        & merged["ownership_attribution_ready"]
        & merged["ownership_pct_used"].notna()
    )
    merged.loc[ready, "model_attribution_status"] = "approved_phase_attributable_sales"
    merged.loc[ready, "model_use"] = "company_attributable_sales"
    merged.loc[ready, "attributable_sales_value_hkd"] = (
        merged.loc[ready, "sales_value_gross_hkd"] * merged.loc[ready, "ownership_pct_used"] / 100.0
    )
    merged["caveat"] = merged.apply(
        lambda row: (
            "Approved phase-specific interval; attributable amount is a project-activity measure, not recognized revenue."
            if row["model_attribution_status"] == "approved_phase_attributable_sales"
            else "Ownership interval is unresolved; retain gross project activity only and exclude from SHKP-attributable sales."
        ),
        axis=1,
    )
    return merged.drop(
        columns=["coverage_not_covered", "coverage_has_covered"], errors="ignore"
    ).rename(columns={"stock_code": "source_project_stock_code"}).reindex(
        columns=SHKP_PROJECT_MODEL_BRIDGE_COLUMNS
    )


def build_shkp_financial_model_inputs(
    db_path: Path = FINANCIAL_DATA_DB_PATH,
    *,
    ticker: str = SHKP_TICKER,
    load_financial_data: bool = True,
) -> dict[str, pd.DataFrame | dict[str, Any]]:
    """Build first-stage inputs from official disclosures and optionally sibling DB.

    ``load_financial_data=False`` is the explicit official-only lane used by
    CI environments that cannot access the private sibling repository.  It
    preserves empty, schema-correct supplemental frames and labels the
    validation result with warnings; it never substitutes a stale or
    fabricated actual/consensus value.
    """
    disclosed = build_shkp_disclosed_financial_facts()
    recurring_portfolio = build_shkp_recurring_portfolio_facts()
    asset_pipeline_capacity = build_shkp_asset_pipeline_capacity()
    if load_financial_data:
        actuals = load_shkp_financial_data_actuals(db_path, ticker=ticker)
        consensus = load_shkp_consensus(db_path, ticker=ticker)
        dividends = load_shkp_dividends(db_path, ticker=ticker)
        market_snapshot = load_shkp_market_snapshot(db_path, ticker=ticker)
        broker_forecasts = load_shkp_broker_forecasts(db_path, ticker=ticker)
        consensus_revisions = load_shkp_consensus_revisions(db_path, ticker=ticker)
        practical_vintages = build_shkp_practical_vintage_snapshots(db_path, ticker=ticker)
    else:
        actuals = pd.DataFrame(columns=SHKP_FINANCIAL_DATA_FACT_COLUMNS)
        consensus = pd.DataFrame(columns=SHKP_CONSENSUS_COLUMNS)
        dividends = pd.DataFrame(columns=SHKP_DIVIDEND_COLUMNS)
        market_snapshot = pd.DataFrame(columns=SHKP_MARKET_SNAPSHOT_COLUMNS)
        broker_forecasts = pd.DataFrame(columns=SHKP_BROKER_FORECAST_COLUMNS)
        consensus_revisions = pd.DataFrame(columns=SHKP_CONSENSUS_REVISION_COLUMNS)
        practical_vintages = pd.DataFrame(columns=SHKP_PRACTICAL_VINTAGE_COLUMNS)
    capital_inputs = build_shkp_capital_inputs(actuals)
    capital_input_quality = build_shkp_capital_input_quality(capital_inputs)
    financial_reconciliation = build_shkp_financial_reconciliation(
        disclosed_facts=disclosed,
        financial_data_actuals=actuals,
    )
    price_history = load_shkp_price_history()
    corporate_documents = enrich_shkp_corporate_document_release_dates(
        load_latest_normalized("shkp_corporate_documents")
    )
    filing_vintages = build_shkp_filing_vintages(corporate_documents)
    completed_properties = load_latest_normalized("shkp_completed_properties")
    if completed_properties.empty:
        completed_properties = pd.DataFrame(columns=SHKP_COMPLETED_PROPERTY_COLUMNS)
    vintage_coverage = build_shkp_vintage_coverage(
        disclosed_facts=disclosed,
        financial_data_actuals=actuals,
        consensus=consensus,
        broker_forecasts=broker_forecasts,
        consensus_revisions=consensus_revisions,
        practical_vintages=practical_vintages,
        corporate_documents=corporate_documents,
    )
    validation = validate_shkp_financial_model_inputs(
        disclosed_facts=disclosed,
        financial_data_actuals=actuals,
        consensus=consensus,
        price_history=price_history,
        recurring_portfolio=recurring_portfolio,
        require_financial_data=load_financial_data,
    )
    return {
        "disclosed_facts": disclosed,
        "recurring_portfolio": recurring_portfolio,
        "asset_pipeline_capacity": asset_pipeline_capacity,
        "completed_properties": completed_properties,
        "financial_data_actuals": actuals,
        "capital_inputs": capital_inputs,
        "capital_input_quality": capital_input_quality,
        "financial_reconciliation": financial_reconciliation,
        "consensus": consensus,
        "dividends": dividends,
        "market_snapshot": market_snapshot,
        "price_history": price_history,
        "broker_forecasts": broker_forecasts,
        "consensus_revisions": consensus_revisions,
        "practical_vintages": practical_vintages,
        "corporate_documents": corporate_documents,
        "filing_vintages": filing_vintages,
        "vintage_coverage": vintage_coverage,
        "validation": validation,
        "financial_data_loaded": bool(load_financial_data),
    }


def run_shkp_financial_model(
    db_path: Path = FINANCIAL_DATA_DB_PATH,
    *,
    run_id: str | None = None,
    include_price_history: bool = False,
    price_start_date: str | None = DEFAULT_PRICE_HISTORY_START,
    price_end_date: str | None = None,
    load_financial_data: bool = True,
) -> dict[str, Any]:
    """Build and persist the first-stage SHKP model input snapshots.

    The sibling DuckDB is read-only.  Only the small, ticker-scoped model
    inputs are materialised under this repository, so the financial-data repo
    remains the canonical source database rather than being copied here.
    """
    model_run_id = run_id or f"shkp-financial-model-{uuid.uuid4()}"
    inputs = build_shkp_financial_model_inputs(
        db_path,
        load_financial_data=load_financial_data,
    )
    validation = inputs["validation"]
    if not isinstance(validation, dict) or validation.get("status") != "valid":
        raise ValueError(f"SHKP financial model input validation failed: {validation}")
    disclosed = inputs["disclosed_facts"]
    recurring_portfolio = inputs["recurring_portfolio"]
    asset_pipeline_capacity = inputs["asset_pipeline_capacity"]
    completed_properties = inputs["completed_properties"]
    derived_metrics = build_shkp_financial_model_derived_metrics(disclosed)
    actuals = inputs["financial_data_actuals"]
    capital_inputs = inputs["capital_inputs"]
    capital_input_quality = inputs["capital_input_quality"]
    financial_reconciliation = inputs["financial_reconciliation"]
    consensus = inputs["consensus"]
    broker_forecasts = inputs["broker_forecasts"]
    consensus_revisions = inputs["consensus_revisions"]
    practical_vintages = inputs["practical_vintages"]
    filing_vintages = inputs["filing_vintages"]
    vintage_coverage = inputs["vintage_coverage"]
    dividends = inputs["dividends"]
    market_snapshot = inputs["market_snapshot"]
    price_history = inputs["price_history"]
    if include_price_history:
        price_history = fetch_shkp_price_history(
            start_date=price_start_date,
            end_date=price_end_date,
            ticker=SHKP_TICKER,
        )
        # The dedicated price contract is saved under the same model run so
        # the coverage row and all inputs can be traced together.
        price_history_source = "fresh_yfinance_fetch"
    else:
        price_history_source = "latest_normalized_snapshot" if not price_history.empty else "not_materialized"
    validation = validate_shkp_financial_model_inputs(
        disclosed_facts=disclosed,
        financial_data_actuals=actuals,
        consensus=consensus,
        price_history=price_history,
        recurring_portfolio=recurring_portfolio,
        require_financial_data=load_financial_data,
    )
    if validation.get("status") != "valid":
        raise ValueError(f"SHKP financial model input validation failed: {validation}")
    project_activity = load_latest_normalized("shkp_srpe_project_month_signals")
    if project_activity.empty:
        project_activity = load_latest_normalized("srpe_pilot_developer_monthly_signals")
    project_registry = load_latest_normalized("shkp_project_registry")
    project_bridge = (
        build_shkp_project_model_bridge(project_activity, project_registry)
        if not project_activity.empty and not project_registry.empty
        else pd.DataFrame(columns=SHKP_PROJECT_MODEL_BRIDGE_COLUMNS)
    )
    coverage = pd.DataFrame([{
        "model_run_id": model_run_id,
        "ticker": SHKP_TICKER,
        "financial_data_db_path": str(Path(db_path)),
        "disclosed_rows": int(len(disclosed)),
        "recurring_portfolio_rows": int(len(recurring_portfolio)),
        "asset_pipeline_capacity_rows": int(len(asset_pipeline_capacity)),
        "completed_property_rows": int(len(completed_properties)),
        "derived_metric_rows": int(len(derived_metrics)),
        "financial_data_actual_rows": int(len(actuals)),
        "financial_data_load_status": "loaded" if load_financial_data else "not_loaded_official_only",
        "capital_input_rows": int(len(capital_inputs)),
        "capital_input_quality_rows": int(len(capital_input_quality)),
        "financial_reconciliation_rows": int(len(financial_reconciliation)),
        "consensus_rows": int(len(consensus)),
        "broker_forecast_rows": int(len(broker_forecasts)),
        "consensus_revision_rows": int(len(consensus_revisions)),
        "practical_vintage_rows": int(len(practical_vintages)),
        "filing_vintage_rows": int(len(filing_vintages)),
        "vintage_coverage_rows": int(len(vintage_coverage)),
        "dividend_rows": int(len(dividends)),
        "market_snapshot_rows": int(len(market_snapshot)),
        "price_history_rows": int(len(price_history)),
        "price_history_source": price_history_source,
        "price_history_first_date": (
            price_history["trading_date"].min().strftime("%Y-%m-%d")
            if not price_history.empty
            else None
        ),
        "price_history_last_date": (
            price_history["trading_date"].max().strftime("%Y-%m-%d")
            if not price_history.empty
            else None
        ),
        "project_bridge_rows": int(len(project_bridge)),
        "project_bridge_attributable_rows": int(
            project_bridge.get("model_attribution_status", pd.Series(dtype="string"))
            .eq("approved_phase_attributable_sales")
            .sum()
        ),
        "validation_status": validation.get("status"),
        "validation_warnings": " | ".join(validation.get("warnings") or []),
        "ownership_policy": validation.get("ownership_policy"),
        "last_verified_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }])
    frames = {
        "shkp_financial_model_disclosed_facts": disclosed,
        "shkp_financial_model_hk_property_sales_segment_history": build_shkp_hk_property_sales_segment_history(),
        "shkp_financial_model_recurring_portfolio_facts": recurring_portfolio,
        "shkp_financial_model_asset_pipeline_capacity": asset_pipeline_capacity,
        "shkp_financial_model_completed_properties": completed_properties,
        "shkp_financial_model_derived_metrics": derived_metrics,
        "shkp_financial_model_financial_data_actuals": actuals,
        "shkp_financial_model_capital_inputs": capital_inputs,
        "shkp_financial_model_capital_input_quality": capital_input_quality,
        "shkp_financial_model_financial_reconciliation": financial_reconciliation,
        "shkp_financial_model_consensus": consensus,
        "shkp_financial_model_broker_forecasts": broker_forecasts,
        "shkp_financial_model_consensus_revisions": consensus_revisions,
        "shkp_financial_model_practical_vintages": practical_vintages,
        "shkp_financial_model_dividends": dividends,
        "shkp_financial_model_project_bridge": project_bridge,
        "shkp_financial_model_market_snapshot": market_snapshot,
        "shkp_financial_model_price_history": price_history,
        "shkp_financial_model_vintage_coverage": vintage_coverage,
        "shkp_financial_model_filing_vintages": filing_vintages,
        "shkp_financial_model_coverage": coverage,
    }
    source_urls = sorted({
        str(value).strip()
        for value in disclosed["source_url"].tolist()
        if value and str(value).strip()
    })
    official_datasets = {
        "shkp_financial_model_disclosed_facts",
        "shkp_financial_model_derived_metrics",
        "shkp_financial_model_recurring_portfolio_facts",
        "shkp_financial_model_asset_pipeline_capacity",
        "shkp_financial_model_completed_properties",
        "shkp_financial_model_filing_vintages",
    }
    financial_data_datasets = {
        "shkp_financial_model_financial_data_actuals",
        "shkp_financial_model_capital_inputs",
        "shkp_financial_model_capital_input_quality",
        "shkp_financial_model_consensus",
        "shkp_financial_model_broker_forecasts",
        "shkp_financial_model_consensus_revisions",
        "shkp_financial_model_practical_vintages",
        "shkp_financial_model_dividends",
        "shkp_financial_model_market_snapshot",
    }
    dataset_source_urls = {
        dataset_name: source_urls if dataset_name in official_datasets else []
        for dataset_name in frames
    }
    dataset_source_urls["shkp_financial_model_recurring_portfolio_facts"] = sorted({
        str(value).strip()
        for value in recurring_portfolio["source_url"].dropna().tolist()
        if str(value).strip()
    })
    dataset_source_urls["shkp_financial_model_asset_pipeline_capacity"] = sorted({
        str(value).strip()
        for value in asset_pipeline_capacity.get("source_url", pd.Series(dtype="string")).dropna().tolist()
        if str(value).strip()
    })
    dataset_source_urls["shkp_financial_model_completed_properties"] = sorted({
        str(value).strip()
        for value in completed_properties.get("source_url", pd.Series(dtype="string")).dropna().tolist()
        if str(value).strip()
    })
    dataset_source_urls["shkp_financial_model_filing_vintages"] = sorted({
        str(value).strip()
        for column in ("document_url", "release_source_url", "source_url")
        for value in filing_vintages.get(column, pd.Series(dtype="string")).dropna().tolist()
        if str(value).strip()
    })
    dataset_source_urls["shkp_financial_model_price_history"] = [YAHOO_HISTORY_URL]
    normalized: dict[str, Any] = {}
    for dataset_name, frame in frames.items():
        normalized[dataset_name] = save_normalized_dataset(
            dataset_name,
            frame,
            run_id=model_run_id,
            source_urls=dataset_source_urls.get(dataset_name, source_urls),
            lineage_metadata={
                "lineage_type": "shkp_financial_model_input",
                "model_run_id": model_run_id,
                "canonical_financial_data_repo": str(Path(db_path)),
                "ownership_attribution": "blocked_without_approved_phase_specific_interval",
                "source_contract": (
                    "yfinance_daily_ohlcv_adjusted_close"
                    if dataset_name == "shkp_financial_model_price_history"
                    else "official_company_disclosure"
                    if dataset_name in official_datasets
                    else "official_only_financial_data_not_loaded"
                    if not load_financial_data and dataset_name in financial_data_datasets
                    else "financial_data_sibling_duckdb_read_only"
                    if dataset_name in financial_data_datasets
                    else "derived_model_join_or_validation"
                ),
                "financial_data_load_status": "loaded" if load_financial_data else "not_loaded_official_only",
            },
        )
    return {
        "mode": "shkp_financial_model",
        "run_id": model_run_id,
        "ticker": SHKP_TICKER,
        "dataset_counts": {name: int(len(frame)) for name, frame in frames.items()},
        "normalized": normalized,
        "validation": validation,
        "ownership_policy": validation.get("ownership_policy"),
    }
