import pandas as pd

from src.hk_real_estate.sources.shkp_quarterly import (
    _extract_quarterly_facts_from_text,
)


def _event(title: str = "SHKP announces 2021/22 interim results") -> dict:
    return {
        "event_id": "event-1",
        "quarter_label": "2022Q1",
        "quarter_end": "2022-03-31",
        "event_date": "2022-03-31",
        "title": title,
        "event_type": "corporate_update",
        "asset_class": None,
        "geography": "unknown",
        "project_label": None,
    }


def test_extracts_attributable_contract_sales_and_reporting_interval():
    text = (
        "The Group announces 2021/22 interim results. Contracted sales during "
        "the period totalled approximately HK$23,000 million in attributable terms."
    )
    facts = _extract_quarterly_facts_from_text(
        text,
        event=_event(),
        source_url="https://example.test/results.pdf",
        source_page_url="https://example.test",
        page_number=1,
    )
    sales = [row for row in facts if row["fact_type"] == "contracted_sales_attributable_hkd_m"]
    assert len(sales) == 1
    assert sales[0]["value"] == 23000.0
    assert sales[0]["unit"] == "HKD_m"
    assert sales[0]["reporting_period_start"] == "2021-07-01"
    assert sales[0]["reporting_period_end"] == "2021-12-31"
    assert sales[0]["reporting_period_type"] == "interim_title_inferred"
    assert sales[0]["model_use"] == "sales_model_calibration"


def test_billion_scale_and_annual_interval_are_normalized():
    text = (
        "During the year ended 30 June 2025, contracted sales reached about "
        "HK$42.3 billion in attributable terms."
    )
    facts = _extract_quarterly_facts_from_text(
        text,
        event=_event("SHKP announces 2024/25 annual results"),
        source_url="https://example.test/results.pdf",
        source_page_url="https://example.test",
        page_number=1,
    )
    sales = [row for row in facts if row["fact_type"] == "contracted_sales_attributable_hkd_m"]
    assert len(sales) == 1
    assert sales[0]["value"] == 42300.0
    assert sales[0]["reporting_period_start"] == "2024-07-01"
    assert sales[0]["reporting_period_end"] == "2025-06-30"
    assert sales[0]["reporting_period_type"] == "annual_title_inferred"
