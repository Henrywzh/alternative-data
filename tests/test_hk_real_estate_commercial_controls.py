import pandas as pd

from src.hk_real_estate.shkp_commercial import (
    build_shkp_commercial_asset_master,
    build_shkp_quarterly_events,
)
from src.hk_real_estate.sources.commercial_controls import (
    _parse_rvd_district_snapshot,
    _parse_rvd_forecast,
    _parse_rvd_office_vacancy,
    _parse_monthly_columns,
)
from src.hk_real_estate.sources.shkp_quarterly import _extract_quarterly_facts_from_text


def test_shkp_quarterly_events_keep_date_semantics_and_classify_property_headline():
    source = pd.DataFrame([
        {
            "document_type": "quarterly_article",
            "title": "Lime Spark records strong sales",
            "document_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2026q2/tc/PDF/event.pdf",
            "source_page_url": "https://www.shkp.com/en-US/investor-relations/shkp-quarterly",
            "source_url": "https://www.shkp.com/en-US/investor-relations/shkp-quarterly",
            "published_date": None,
        },
        {
            "document_type": "quarterly_article",
            "title": "The Group supports a charity programme",
            "document_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2026q2/tc/PDF/other.pdf",
            "source_page_url": "https://www.shkp.com/en-US/investor-relations/shkp-quarterly",
            "source_url": "https://www.shkp.com/en-US/investor-relations/shkp-quarterly",
            "published_date": None,
        },
    ])
    result = build_shkp_quarterly_events(source)
    assert len(result) == 2
    sales = result.loc[result["title"].str.contains("Lime Spark")].iloc[0]
    assert sales["event_type"] == "sales_response"
    assert sales["property_relevance"] == "property"
    assert sales["event_date"] == "2026-06-30"
    assert sales["event_date_semantics"] == "quarter_end_label_proxy"
    assert sales["project_label"] == "Lime Spark"


def test_commercial_asset_master_keeps_source_layers_separate():
    catalog = pd.DataFrame([
        {
            "asset_type": "office",
            "marketing_name": "Example Tower",
            "district": "Central",
            "source_record_id": "directory:1",
            "source_page_url": "directory",
            "source_url": "directory-api",
            "fetched_at": "2026-08-08",
        }
    ])
    completed = pd.DataFrame([
        {
            "completed_property_id": "completed:1",
            "project_label_raw": "Example Tower",
            "location_raw": "Central",
            "geography": "Hong Kong Island",
            "group_interest_raw": "50",
            "group_interest_pct": 50,
            "office_gfa_sqft": 100000,
            "total_gfa_sqft": 100000,
            "report_period_end": "2025-06-30",
            "source_url": "annual-report",
        }
    ])
    result = build_shkp_commercial_asset_master(
        property_catalog=catalog,
        completed_properties=completed,
        completion_schedule=pd.DataFrame(),
    )
    assert len(result) == 2
    assert set(result["source_layer"]) == {"issuer_current_directory", "issuer_annual_report_completed"}
    assert result["asset_id"].nunique() == 1
    assert result.loc[result["source_layer"].eq("issuer_annual_report_completed"), "group_interest_pct"].iloc[0] == 50


def test_commercial_control_parsers_preserve_annual_and_monthly_grain():
    vacancy = _parse_rvd_office_vacancy(
        b"TITLE,,,,\nYear,Grade A (Vacancy) - Area,Grade A (Vacancy) - %,Total (Vacancy) - Area,Total (Vacancy) - %\n2024,100,0.1,200,0.2",
        "rvd-vacancy",
    )
    assert set(vacancy["metric"]) == {"vacancy_area_sqft", "vacancy_pct"}
    assert set(vacancy["frequency"]) == {"annual"}

    district = _parse_rvd_district_snapshot(
        b"TITLE,,,,\nDistrict,Stock at 2023 year-end,Completions in 2024,Stock at 2024 year-end,Amount Vacant at 2024 year-end,% Vacant\nHONG KONG,100,10,105,5,4.8",
        "rvd-district",
        geography="hong_kong",
        table_kind="private_commercial",
    )
    assert set(district["metric"]) == {"stock", "completions", "vacancy_area_sqft", "vacancy_pct"}

    forecast = _parse_rvd_forecast(
        b"TITLE,,,\nDistrict,Completions in 2024,Forecast Completions in 2025\nHONG KONG,10,12",
        "rvd-forecast",
    )
    assert set(forecast["metric"]) == {"completions", "forecast_completions"}

    tourism = _parse_monthly_columns(
        b"Year-Month,High tariff,Medium tariff\n202401,80,70\n202402,81,71",
        metric="hotel_occupancy",
        unit="percent",
    )
    assert len(tourism) == 4
    assert tourism["date"].min() == "2024-01-01"


def test_shkp_quarterly_fact_parser_keeps_explicit_units_and_drops_pdf_footnote_fragments():
    event = {
        "event_id": "evt-1",
        "quarter_label": "2026Q2",
        "quarter_end": "2026-06-30",
        "event_date": "2026-06-30",
        "event_type": "sales_response",
        "asset_class": "residential",
        "geography": "hong_kong",
        "project_label": "Lime Spark",
        "title": "Lime Spark records strong sales",
    }
    rows = _extract_quarterly_facts_from_text(
        "Lime Spark offers 462 units with saleable areas ranging from 271 to 594 square feet. "
        "The project received 90% take-up under a 10-year lease. A PDF footnote leaves 18 square feet.",
        event=event,
        source_url="https://example.test/event.pdf",
        source_page_url="https://example.test/quarterly",
        page_number=1,
    )
    assert {(row["fact_type"], row["value"]) for row in rows} >= {
        ("unit_count", 462.0),
        ("area_sqft", 594.0),
        ("property_rate_pct", 90.0),
        ("lease_term_years", 10.0),
    }
    assert not any(row["fact_type"] == "area_sqft" and row["value"] < 100 for row in rows)
