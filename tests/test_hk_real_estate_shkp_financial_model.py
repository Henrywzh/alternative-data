import pandas as pd
import pytest

from src.hk_real_estate.shkp_financial_model import (
    SHKP_TICKER,
    build_shkp_project_model_bridge,
    build_shkp_disclosed_financial_facts,
    build_shkp_financial_model_derived_metrics,
    build_shkp_recurring_portfolio_facts,
    build_shkp_filing_vintages,
    build_shkp_asset_pipeline_capacity,
    build_shkp_financial_model_inputs,
    build_shkp_capital_input_quality,
    build_shkp_financial_reconciliation,
    build_shkp_vintage_coverage,
    build_shkp_practical_vintage_snapshots,
    load_shkp_consensus,
    load_shkp_dividends,
    load_shkp_financial_data_actuals,
    load_shkp_broker_forecasts,
    load_shkp_consensus_revisions,
    validate_shkp_financial_model_inputs,
)
from conftest import require_local_normalized
from src.hk_real_estate.storage import load_latest_normalized
from src.hk_real_estate.shkp_price import (
    SHKP_PRICE_HISTORY_COLUMNS,
    fetch_shkp_price_history,
    normalize_shkp_price_history,
)
from src.hk_real_estate.sources.shkp import enrich_shkp_corporate_document_release_dates


def test_disclosed_facts_keep_segment_and_contracted_sales_separate():
    frame = build_shkp_disclosed_financial_facts()

    assert len(frame) == 86
    assert set(frame["fact_group"]) >= {
        "segment_financials",
        "consolidated_financials",
        "contracted_sales_backlog",
        "future_growth_pipeline",
    }
    property_sales = frame.loc[
        frame["metric"].eq("property_sales_revenue_including_jv_associates")
        & frame["period_end"].eq("2025-06-30")
    ].iloc[0]
    backlog = frame.loc[
        frame["metric"].eq("hk_contract_sales_yet_to_be_recognized")
        & frame["period_end"].eq("2025-06-30")
    ].iloc[0]
    assert property_sales["value"] == 34556
    assert backlog["value"] == 35600
    assert backlog["fact_group"] == "contracted_sales_backlog"
    assert backlog["metric"] != "property_revenue"
    assert frame["source_url"].astype(str).str.startswith("https://").all()


def test_financial_model_validator_rejects_revenue_labelled_backlog():
    disclosed = build_shkp_disclosed_financial_facts()
    disclosed.loc[disclosed["fact_group"].eq("contracted_sales_backlog"), "metric"] = "property_revenue"
    actuals = pd.DataFrame([{"ticker": SHKP_TICKER}])
    consensus = pd.DataFrame([{"ticker": SHKP_TICKER}])

    result = validate_shkp_financial_model_inputs(
        disclosed_facts=disclosed,
        financial_data_actuals=actuals,
        consensus=consensus,
    )

    assert result["status"] == "invalid"
    assert any("must not be labelled revenue" in error for error in result["errors"])


def _yahoo_history_fixture() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "Open": [90.0, 91.0, 93.0],
            "High": [91.0, 94.0, 95.0],
            "Low": [89.0, 90.0, 92.0],
            "Close": [90.5, 93.0, 94.0],
            "Adj Close": [90.0, 92.0, 93.5],
            "Volume": [100, 110, 120],
            "Dividends": [0.0, 1.0, 0.0],
            "Stock Splits": [0.0, 0.0, 0.0],
        },
        index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
    )
    frame.index.name = "Date"
    return frame


def test_price_contract_preserves_raw_adjusted_and_total_return_fields():
    result = normalize_shkp_price_history(
        _yahoo_history_fixture(),
        fetched_at="2024-01-05T00:00:00Z",
        requested_start="2024-01-01",
        requested_end="2024-01-05",
    )

    assert list(result.columns) == SHKP_PRICE_HISTORY_COLUMNS
    assert result["ticker"].eq(SHKP_TICKER).all()
    assert result["close"].tolist() == [90.5, 93.0, 94.0]
    assert result["adj_close"].tolist() == [90.0, 92.0, 93.5]
    assert result["dividend_per_share"].tolist() == [0.0, 1.0, 0.0]
    assert result["total_return_index"].iloc[0] == pytest.approx(100.0)
    assert result["total_return_index"].iloc[-1] == pytest.approx(93.5 / 90.0 * 100.0)
    assert result["price_adjustment_policy"].iloc[0] == "raw_ohlc_with_yahoo_adjusted_close"


def test_price_contract_rejects_duplicate_dates_and_future_observations():
    duplicate = pd.concat([_yahoo_history_fixture(), _yahoo_history_fixture().iloc[[0]]])
    with pytest.raises(ValueError, match="duplicate trading dates"):
        normalize_shkp_price_history(duplicate, fetched_at="2024-01-05T00:00:00Z")
    with pytest.raises(ValueError, match="after fetched_at"):
        normalize_shkp_price_history(_yahoo_history_fixture(), fetched_at="2024-01-03T00:00:00Z")


def test_price_contract_excludes_only_in_progress_fetch_date_without_close():
    frame = _yahoo_history_fixture()
    frame.loc[pd.Timestamp("2024-01-04"), "Close"] = pd.NA
    result = normalize_shkp_price_history(frame, fetched_at="2024-01-04T10:00:00Z")
    assert result["trading_date"].dt.strftime("%Y-%m-%d").tolist() == ["2024-01-02", "2024-01-03"]
    assert "In-progress fetch-date rows" in result["caveat"].iloc[0]


def test_price_fetcher_passes_unadjusted_daily_contract_options():
    calls = {}

    def fake_fetcher(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return _yahoo_history_fixture()

    result = fetch_shkp_price_history(
        start_date="2024-01-01",
        end_date="2024-01-05",
        fetcher=fake_fetcher,
        fetched_at="2024-01-05T00:00:00Z",
    )
    assert calls["args"] == (SHKP_TICKER,)
    assert calls["kwargs"] == {
        "start": "2024-01-01",
        "end": "2024-01-05",
        "actions": True,
        "auto_adjust": False,
        "progress": False,
        "threads": False,
    }
    assert len(result) == 3


def test_vintage_coverage_does_not_promote_fetch_time_to_point_in_time_date():
    coverage = build_shkp_vintage_coverage(
        disclosed_facts=build_shkp_disclosed_financial_facts(),
        financial_data_actuals=pd.DataFrame([
            {
                "ticker": SHKP_TICKER,
                "period_end": "2024-06-30",
                "available_at": "2026-07-28T00:00:00Z",
                "announcement_date": pd.NA,
                "fetched_at": "2026-07-28T00:00:00Z",
                "point_in_time_quality": "low",
            },
        ]),
        consensus=pd.DataFrame([
            {
                "ticker": SHKP_TICKER,
                "snapshot_date": "2026-07-26",
                "estimate_period_end": pd.NaT,
                "fiscal_year": 2027,
                "fetched_at": "2026-07-26T00:00:00Z",
            },
        ]),
    )
    actuals = coverage.loc[coverage["layer"].eq("financial_data_actuals")].iloc[0]
    consensus = coverage.loc[coverage["layer"].eq("consensus_statistics")].iloc[0]
    assert actuals["status"] == "not_pit_safe_missing_announcement_dates"
    assert actuals["announcement_date_coverage_pct"] == 0
    assert consensus["status"] == "current_snapshot_only"
    assert consensus["estimate_period_end_coverage_pct"] == 0


def test_practical_vintage_builder_keeps_fetch_proxy_and_provider_snapshot_semantics(tmp_path, monkeypatch):
    processed = tmp_path / "financial-data" / "data" / "processed" / "hk_financials"
    actual_dir = processed / "financial_observations" / "source=yfinance"
    consensus_dir = processed / "consensus_statistics" / "source=yfinance"
    broker_dir = processed / "broker_forecasts" / "source=akshare"
    actual_dir.mkdir(parents=True)
    consensus_dir.mkdir(parents=True)
    broker_dir.mkdir(parents=True)
    pd.DataFrame([
        {
            "observation_id": "actual-1",
            "ticker": SHKP_TICKER,
            "statement_type": "income_statement",
            "metric": "revenue",
            "metric_label": "Total Revenue",
            "fiscal_period_end": "2024-06-30",
            "period_type": "annual",
            "value": 100.0,
            "unit": "currency",
            "currency": "HKD",
            "source": "yfinance",
            "announcement_date": pd.NaT,
            "available_at": "2026-07-28T00:00:00Z",
            "fetched_at": "2026-07-28T00:00:00Z",
        }
    ]).to_parquet(actual_dir / "actual.parquet", index=False)
    pd.DataFrame([
        {
            "consensus_statistic_id": "consensus-1",
            "ticker": SHKP_TICKER,
            "metric": "eps",
            "statistic": "mean",
            "value": 8.0,
            "currency": "HKD",
            "snapshot_date": "2026-07-26",
            "source": "yfinance",
            "fetched_at": "2026-07-28T00:00:00Z",
        }
    ]).to_parquet(consensus_dir / "consensus.parquet", index=False)
    pd.DataFrame([
        {
            "forecast_id": "broker-1",
            "ticker": SHKP_TICKER,
            "broker_name": "Broker",
            "forecast_date": "2026-07-21",
            "fiscal_year": 2027,
            "eps": 8.2,
            "net_profit": 22_000_000_000.0,
            "eps_currency": "HKD",
            "net_profit_currency": "HKD",
            "source": "akshare",
            "fetched_at": "2026-07-28T00:00:00Z",
        }
    ]).to_parquet(broker_dir / "broker.parquet", index=False)

    db_path = tmp_path / "financial-data" / "data" / "databases" / "hk_financials.duckdb"
    db_path.parent.mkdir(parents=True)
    # The helper only derives the sibling processed root from the path; no DB
    # connection is needed for this pure snapshot contract.
    result = build_shkp_practical_vintage_snapshots(db_path=db_path)
    assert set(result["layer"]) == {"actual", "consensus", "broker_forecast"}
    actual = result.loc[result["layer"].eq("actual")].iloc[0]
    consensus = result.loc[result["layer"].eq("consensus")].iloc[0]
    forecast = result.loc[result["layer"].eq("broker_forecast")].iloc[0]
    assert actual["vintage_date_semantics"] == "fetched_at_snapshot_proxy"
    assert actual["vintage_quality"] == "fetch_time_proxy_non_pit"
    assert consensus["vintage_date_semantics"] == "provider_snapshot_date"
    assert consensus["statistic"] == "mean"
    assert forecast["vintage_date_semantics"] == "broker_forecast_date"
    net_profit = result.loc[
        result["layer"].eq("broker_forecast") & result["metric"].eq("net_profit")
    ].iloc[0]
    assert net_profit["value"] == pytest.approx(22_000_000_000.0)
    assert net_profit["unit"] == "currency"


def test_corporate_release_metadata_uses_hkex_time_and_leaves_unknown_rows_undated():
    documents = pd.DataFrame([
        {
            "document_type": "annual_report",
            "title": "Annual Report 2024/25",
            "document_url": "https://www.shkp.com/Content/Uploads/FinReports/SHKPAR_EN_2024_25.pdf",
            "published_date": pd.NA,
            "fetched_at": "2026-08-06T00:00:00Z",
        },
        {
            "document_type": "annual_report",
            "title": "Unmapped report",
            "document_url": "https://example.invalid/unmapped.pdf",
            "published_date": pd.NA,
            "fetched_at": "2026-08-06T00:00:00Z",
        },
    ])
    enriched = enrich_shkp_corporate_document_release_dates(documents)

    known = enriched.iloc[0]
    unknown = enriched.iloc[1]
    assert known["document_semantics"] == "annual_report"
    assert known["reporting_period_end"] == "2025-06-30"
    assert known["hkex_release_at"] == "2025-10-08T16:32:00+08:00"
    assert known["release_evidence_type"] == "hkex_long_form_report_release"
    assert pd.isna(unknown["hkex_release_at"])


def test_vintage_coverage_reports_partial_curated_document_release_dates():
    documents = enrich_shkp_corporate_document_release_dates(pd.DataFrame([
        {
            "document_type": "annual_report",
            "title": "Annual Report 2024/25",
            "document_url": "https://www.shkp.com/Content/Uploads/FinReports/SHKPAR_EN_2024_25.pdf",
            "published_date": pd.NA,
            "fetched_at": "2026-08-06T00:00:00Z",
        },
        {
            "document_type": "annual_report",
            "title": "Unmapped report",
            "document_url": "https://example.invalid/unmapped.pdf",
            "published_date": pd.NA,
            "fetched_at": "2026-08-06T00:00:00Z",
        },
    ]))
    coverage = build_shkp_vintage_coverage(
        disclosed_facts=build_shkp_disclosed_financial_facts(),
        financial_data_actuals=pd.DataFrame(),
        consensus=pd.DataFrame(),
        corporate_documents=documents,
    )
    row = coverage.loc[coverage["layer"].eq("corporate_documents")].iloc[0]
    assert row["release_date_coverage_pct"] == 50.0
    assert row["status"] == "filing_catalog_partial_release_dates"
    assert row["snapshot_start"] == "2025-10-08"


def test_filing_vintages_keep_exact_date_only_and_undated_rows_separate():
    documents = enrich_shkp_corporate_document_release_dates(pd.DataFrame([
        {
            "document_type": "annual_report",
            "title": "Annual Report 2024/25",
            "document_url": "https://www.shkp.com/Content/Uploads/FinReports/SHKPAR_EN_2024_25.pdf",
            "source_page_url": "https://www.shkp.com/en-US/investor-relations/financial-results-reports",
            "source_url": "https://www.shkp.com/en-US/investor-relations/financial-results-reports",
            "published_date": pd.NA,
            "fetched_at": "2026-08-06T00:00:00Z",
        },
        {
            "document_type": "quarterly_article",
            "title": "Unmapped quarterly article",
            "document_url": "https://example.invalid/unmapped.pdf",
            "source_page_url": "https://example.invalid/catalog",
            "source_url": "https://example.invalid/catalog",
            "published_date": "2026-01-15",
            "fetched_at": "2026-08-06T00:00:00Z",
        },
        {
            "document_type": "announcement",
            "title": "Undated announcement",
            "document_url": "https://example.invalid/undated.pdf",
            "source_page_url": "https://example.invalid/catalog",
            "source_url": "https://example.invalid/catalog",
            "published_date": pd.NA,
            "fetched_at": "2026-08-06T00:00:00Z",
        },
    ]))

    vintages = build_shkp_filing_vintages(documents)
    assert len(vintages) == 3
    assert vintages["vintage_id"].is_unique

    exact = vintages.loc[vintages["document_url"].str.contains("SHKPAR_EN_2024_25")].iloc[0]
    date_only = vintages.loc[vintages["document_url"].str.contains("unmapped")].iloc[0]
    undated = vintages.loc[vintages["document_url"].str.contains("undated")].iloc[0]
    assert exact["availability_quality"] == "exact_hkex_release_timestamp"
    assert bool(exact["pit_timestamp_usable"])
    assert exact["model_use"] == "historical_pit_anchor"
    assert date_only["availability_quality"] == "issuer_date_only"
    assert bool(date_only["pit_date_usable"])
    assert not bool(date_only["pit_timestamp_usable"])
    assert undated["availability_quality"] == "undated_discovery"
    assert not bool(undated["pit_date_usable"])
    assert undated["model_use"] == "discovery_only"


def test_capital_input_quality_keeps_raw_hkd_and_normalizes_to_hkd_millions():
    capital = pd.DataFrame([
        {
            "ticker": SHKP_TICKER,
            "statement_type": "balance_sheet",
            "metric": "investment_properties",
            "metric_label": "Investment Properties",
            "value": 398_729_000_000,
            "unit": "currency",
            "currency": "HKD",
            "currency_semantics": "reporting_currency",
            "period_type": "annual",
            "period_end": "2022-06-30",
            "source": "yfinance",
            "source_priority": 1,
            "point_in_time_quality": "low",
            "announcement_date": pd.NA,
            "available_at": "2026-07-26T00:00:00Z",
        },
    ])
    quality = build_shkp_capital_input_quality(capital)
    row = quality.iloc[0]
    assert row["raw_unit"] == "currency"
    assert row["raw_value"] == 398_729_000_000
    assert row["normalized_value_hkd_m"] == pytest.approx(398_729)
    assert row["quality_status"] == "scaled_vendor_context_no_announcement_date"


def test_financial_reconciliation_catches_hkd_vs_hkd_million_scale_without_overwriting_raw_value():
    official = pd.DataFrame([
        {
            "fact_id": "official:revenue",
            "ticker": SHKP_TICKER,
            "metric": "group_revenue",
            "value": 77_747,
            "unit": "HKD_m",
            "period_end": "2022-06-30",
            "source_role": "official_company_disclosure",
        },
    ])
    actuals = pd.DataFrame([
        {
            "ticker": SHKP_TICKER,
            "statement_type": "income_statement",
            "metric": "revenue",
            "value": 77_747_000_000,
            "period_end": "2022-06-30",
            "source": "yfinance",
        },
    ])
    result = build_shkp_financial_reconciliation(
        disclosed_facts=official,
        financial_data_actuals=actuals,
    )
    row = result.iloc[0]
    assert row["financial_data_value_raw_hkd"] == 77_747_000_000
    assert row["financial_data_value_hkd_m"] == pytest.approx(77_747)
    assert row["difference_pct"] == pytest.approx(0)
    assert row["status"] == "reconciled_after_unit_normalization"


def test_recurring_portfolio_facts_keep_hotel_rental_and_occupancy_scopes_separate():
    facts = build_shkp_recurring_portfolio_facts()
    assert len(facts) == 46
    assert facts["fact_id"].is_unique
    hotel = facts.loc[
        facts["period_end"].eq("2025-12-31")
        & facts["asset_class"].eq("hotel")
        & facts["metric"].eq("ebitda")
    ].iloc[0]
    assert hotel["value"] == 796
    assert hotel["period_type"] == "interim"
    retail_occ = facts.loc[
        facts["period_end"].eq("2025-12-31")
        & facts["asset_class"].eq("retail")
        & facts["metric"].eq("average_occupancy")
    ].iloc[0]
    assert retail_occ["value"] == 94
    assert retail_occ["unit"] == "percent"
    assert retail_occ["scope"] == "portfolio_statistic_as_stated"


def test_asset_pipeline_capacity_keeps_forward_area_separate_from_income():
    capacity = build_shkp_asset_pipeline_capacity()
    assert len(capacity) == 8
    assert capacity["asset_id"].is_unique
    scramble = capacity.loc[capacity["asset_name"].eq("Scramble Hill")].iloc[0]
    assert scramble["value"] == 500000
    assert scramble["unit"] == "sqft"
    assert scramble["ownership_pct_observed"] == pytest.approx(72.4)
    assert scramble["model_use"] == "capacity_only"
    assert "not a bounded legal/SPV interval" in scramble["caveat"]
    assert set(capacity["metric"]) == {"gross_gfa", "retained_investment_gfa"}


def test_derived_metrics_use_compatible_segment_inputs_only():
    derived = build_shkp_financial_model_derived_metrics()

    rental_margin = derived.loc[
        derived["metric"].eq("property_rental_operating_margin_pct")
        & derived["period_end"].eq("2025-06-30")
    ].iloc[0]
    assert len(derived) == 29
    assert rental_margin["value"] == pytest.approx(18392 / 24461 * 100)
    assert rental_margin["source_role"] == "derived_from_official_disclosed_facts"
    assert "NOI" in rental_margin["caveat"]


def test_project_model_bridge_blocks_unapproved_activity_and_allows_approved_interval():
    activity = pd.DataFrame([
        {
            "srpe_development_id": "9366",
            "project_id": "cullinan-sky-p1",
            "period": "2026-01-01",
            "sales_units_gross": 10,
            "sales_value_gross_hkd": 100_000_000,
            "stock_code": "0016",
        },
        {
            "srpe_development_id": "11005",
            "project_id": "cullinan-sky-p2",
            "period": "2026-01-01",
            "sales_units_gross": 5,
            "sales_value_gross_hkd": 50_000_000,
            "sales_value_attributable_hkd": 50_000_000,
            "stock_code": "0016",
        },
    ])
    registry = pd.DataFrame([
        {
            "srpe_development_id": "9366",
            "ownership_status": "annual_numeric_unreconciled",
            "ownership_attribution_ready": False,
            "ownership_observed_pct": 100,
        },
        {
            "srpe_development_id": "11005",
            "ownership_status": "consistent_numeric",
            "ownership_attribution_ready": True,
            "ownership_observed_pct": 50,
            "ownership_effective_from": "2025-01-01",
            "ownership_effective_to": "2026-12-31",
            "ownership_interval_evidence_type": "approved_phase_attribution_decision",
            "ownership_attribution_decision_id": "decision:11005",
            "ownership_interval_promotion_status": "approved_phase_attribution",
            "decision_status": "approved",
        },
    ])

    bridge = build_shkp_project_model_bridge(activity, registry)

    blocked = bridge.loc[bridge["srpe_development_id"].eq("9366")].iloc[0]
    approved = bridge.loc[bridge["srpe_development_id"].eq("11005")].iloc[0]
    assert blocked["model_use"] == "leading_indicator_only"
    assert pd.isna(blocked["attributable_sales_value_hkd"])
    assert approved["model_use"] == "company_attributable_sales"
    assert approved["attributable_sales_value_hkd"] == 25_000_000


def test_project_model_bridge_accepts_shkp_wide_signal_field_names():
    activity = pd.DataFrame([
        {
            "srpe_development_id": "9366",
            "project_id": "shkp-srpe-9366",
            "period": "2026-01-01",
            "sales_units_gross": 10,
            "sales_value_gross_hkd": 100_000_000,
            "cancelled_units": 1,
            "active_units_eom": 9,
            "published_inventory_units": 500,
        }
    ])
    registry = pd.DataFrame([{
        "srpe_development_id": "9366",
        "ownership_attribution_ready": False,
        "ownership_status": "review_required",
    }])
    bridge = build_shkp_project_model_bridge(activity, registry)
    assert bridge.loc[0, "cumulative_unique_active_units"] == 9
    assert bridge.loc[0, "total_residential_properties"] == 500
    assert bridge.loc[0, "model_use"] == "leading_indicator_only"


def _make_test_database(path):
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(str(path))
    actuals = pd.DataFrame([
        {
            "observation_id": "actual:1",
            "ticker": SHKP_TICKER,
            "statement_type": "income_statement",
            "metric": "revenue",
            "metric_label": "Total Revenue",
            "value": 79721.0,
            "unit": "currency",
            "currency": "HKD",
            "currency_semantics": "reported",
            "period_type": "annual",
            "fiscal_period_end": "2025-06-30",
            "announcement_date": "2025-09-04",
            "available_at": "2025-09-04",
            "point_in_time_quality": "high",
            "source": "test",
            "source_priority": 1,
            "selection_status": "policy_deterministic",
            "fetched_at": "2025-09-05",
            "source_metadata": "{}",
        },
        {
            "observation_id": "actual:ignored",
            "ticker": SHKP_TICKER,
            "statement_type": "income_statement",
            "metric": "revenue",
            "metric_label": "Total Revenue",
            "value": 1.0,
            "unit": "currency",
            "currency": "HKD",
            "currency_semantics": "reported",
            "period_type": "annual",
            "fiscal_period_end": "2025-06-30",
            "announcement_date": "2025-09-04",
            "available_at": "2025-09-04",
            "point_in_time_quality": "high",
            "source": "test",
            "source_priority": 2,
            "selection_status": "conflict_gate",
            "fetched_at": "2025-09-05",
            "source_metadata": "{}",
        },
    ])
    consensus = pd.DataFrame([
        {
            "consensus_statistic_id": "consensus:1",
            "ticker": SHKP_TICKER,
            "metric": "eps",
            "statistic": "mean",
            "value": 8.5,
            "unit": "currency_per_share",
            "currency": "HKD",
            "estimate_period_end": "2026-06-30",
            "fiscal_year": 2026,
            "horizon": "FY1",
            "snapshot_date": "2026-08-01",
            "source": "test",
            "contributor_count": 5,
            "calculation_origin": "test",
            "fetched_at": "2026-08-01",
        },
    ])
    dividends = pd.DataFrame([
        {
            "observation_id": "dividend:1",
            "ticker": SHKP_TICKER,
            "ex_date": "2025-11-01",
            "payment_date": "2025-11-15",
            "amount": 1.5,
            "currency": "HKD",
            "source": "test",
            "fetched_at": "2026-08-01",
        },
    ])
    connection.register("actuals_df", actuals)
    connection.register("consensus_df", consensus)
    connection.register("dividends_df", dividends)
    connection.execute("CREATE TABLE latest_restated_financial_facts AS SELECT * FROM actuals_df")
    connection.execute("CREATE TABLE consensus_statistics_history AS SELECT * FROM consensus_df")
    connection.execute("CREATE TABLE dividend_observations AS SELECT * FROM dividends_df")
    connection.close()


def test_financial_data_bridge_filters_conflicts_and_preserves_vintages(tmp_path):
    db_path = tmp_path / "financials.duckdb"
    _make_test_database(db_path)

    actuals = load_shkp_financial_data_actuals(db_path)
    consensus = load_shkp_consensus(db_path)
    dividends = load_shkp_dividends(db_path)

    assert len(actuals) == 1
    assert actuals.iloc[0]["metric"] == "revenue"
    assert actuals.iloc[0]["model_use"] == "selected_actual"
    assert consensus.iloc[0]["snapshot_date"] == "2026-08-01"
    assert dividends.iloc[0]["amount"] == 1.5


def test_financial_model_inputs_build_from_a_reviewed_duckdb_snapshot(tmp_path):
    db_path = tmp_path / "financials.duckdb"
    _make_test_database(db_path)

    inputs = build_shkp_financial_model_inputs(db_path)

    assert inputs["validation"]["status"] == "valid"
    assert len(inputs["disclosed_facts"]) == 86
    assert len(inputs["financial_data_actuals"]) == 1
    assert len(inputs["capital_inputs"]) == 1
    assert len(inputs["consensus"]) == 1
    assert len(inputs["dividends"]) == 1
    assert len(inputs["asset_pipeline_capacity"]) == 8
    assert inputs["filing_vintages"]["vintage_id"].is_unique


def test_hk_property_sales_segment_history_13_years():
    """13-year HK-only segment revenue panel must be complete and internally consistent."""
    from src.hk_real_estate.shkp_financial_model import (
        _HK_PROPERTY_SALES_SEGMENT_REVENUE_HKD_M,
        build_shkp_hk_property_sales_segment_history,
    )
    assert len(_HK_PROPERTY_SALES_SEGMENT_REVENUE_HKD_M) == 13
    assert min(_HK_PROPERTY_SALES_SEGMENT_REVENUE_HKD_M) == 2013
    assert max(_HK_PROPERTY_SALES_SEGMENT_REVENUE_HKD_M) == 2025
    # verified from annual report segment notes (both current and prior-year tables)
    spot = {2014: 27056, 2017: 30261, 2020: 36873, 2023: 23866, 2025: 26139}
    for year, expected in spot.items():
        assert _HK_PROPERTY_SALES_SEGMENT_REVENUE_HKD_M[year] == expected, f"FY{year}"
    panel = build_shkp_hk_property_sales_segment_history()
    assert len(panel) == 13
    assert panel["segment"].eq("property_sales_hong_kong").all()
    assert panel["revenue_hkd"].eq(panel["revenue_hkd_m"] * 1_000_000.0).all()
    assert panel["data_status"].eq("verified_from_annual_report_pdf").all()


def test_historical_reconciliation_uses_hk_only_segment_revenue():
    """The multi-year panel must prefer the HK-only segment revenue anchor over the all-region summary line."""
    from src.hk_real_estate.shkp_indicative_sales_model import build_shkp_indicative_sales_model_historical_reconciliation
    months = pd.date_range("2019-07-01", "2026-08-01", freq="MS")
    monthly = pd.DataFrame(
        {
            "period": months,
            "estimated_total_low_sales_value_hkd": 1e9,
            "estimated_total_base_sales_value_hkd": 2e9,
            "estimated_total_high_sales_value_hkd": 3e9,
            "estimated_total_base_sales_units": 100.0,
            "covered_phase_count": 50,
        }
    )
    hk_segment = pd.DataFrame(
        [
            {
                "fiscal_year_end": 2024,
                "period_start": "2023-07-01",
                "period_end": "2024-06-30",
                "revenue_hkd": 24_745_000_000.0,
                "revenue_hkd_m": 24745,
                "caveat": "hk only",
            }
        ]
    )
    # An all-region disclosed fact that must NOT be used when HK segment exists
    facts = pd.DataFrame(
        [
            {
                "metric": "property_sales_revenue_including_jv_associates",
                "value": 27422.0,
                "period_start": "2023-07-01",
                "period_end": "2024-06-30",
                "period_type": "annual",
                "available_at": "2024-09-05",
                "source_url": "https://example.com",
                "source_label": "summary",
                "caveat": "all region",
            }
        ]
    )
    signals = pd.DataFrame({"phase_id": [str(i) for i in range(230)], "period": ["2024-01-01"] * 230})
    panel = build_shkp_indicative_sales_model_historical_reconciliation(
        monthly,
        disclosed_facts=facts,
        quarterly_facts=pd.DataFrame(),
        signals=signals,
        hk_segment_history=hk_segment,
    )
    assert len(panel) == 1
    row = panel.iloc[0]
    assert row["anchor_scope"] == "property_sales_revenue_hong_kong_combined"
    assert row["reported_sales_value_hkd"] == 24_745_000_000.0


def test_historical_earnings_bridge_15_years():
    """The 15-year earnings bridge must be complete and internally consistent."""
    from src.hk_real_estate.shkp_earnings_bridge import build_shkp_historical_earnings_bridge
    bridge = build_shkp_historical_earnings_bridge()
    assert len(bridge) == 15
    years = sorted(bridge["fiscal_year_end"].astype(int).tolist())
    assert years == list(range(2011, 2026))
    # FY2025 values verified from the 2024/25 five-year summary
    fy25 = bridge[bridge["fiscal_year_end"].eq(2025)].iloc[0]
    assert fy25["underlying_profit_hkd_m"] == 21855
    assert fy25["underlying_eps_hkd"] == 7.54
    assert fy25["reported_eps_hkd"] == 6.65
    # FY2021-25 have segment split
    seg = bridge[bridge["fiscal_year_end"].ge(2021)]
    assert seg["property_sales_profit_hkd_m"].notna().all()
    assert seg["property_rental_profit_hkd_m"].notna().all()
    # FV effect present for all years (derived pre-FY2021)
    assert bridge["fv_effect_hkd_m"].notna().all()
    # underlying + non-underlying reconciles to reported
    rec = bridge.dropna(subset=["underlying_profit_hkd_m", "profit_attributable_hkd_m"])
    assert ((rec["underlying_profit_hkd_m"] + rec["non_underlying_items_hkd_m"] - rec["profit_attributable_hkd_m"]).abs() < 1.0).all()


def test_hotel_segment_series_13_years():
    """Hotel segment series must cover FY2013-2025 with verified COVID leverage."""
    require_local_normalized("shkp_hotel_segment_series")
    from src.hk_real_estate.shkp_earnings_bridge import _HOTEL_SEGMENT, build_shkp_historical_earnings_bridge
    from src.hk_real_estate.storage import load_latest_normalized
    assert len(_HOTEL_SEGMENT) == 13
    assert min(_HOTEL_SEGMENT) == 2013 and max(_HOTEL_SEGMENT) == 2025
    # COVID: FY2019 peak positive, FY2020-22 losses, partial recovery
    assert _HOTEL_SEGMENT[2019]["result_combined"] == 1433
    assert _HOTEL_SEGMENT[2020]["result_combined"] == -330
    assert _HOTEL_SEGMENT[2021]["result_combined"] == -511
    assert _HOTEL_SEGMENT[2025]["result_combined"] == 615
    # persisted dataset loads and reconciles
    h = load_latest_normalized("shkp_hotel_segment_series")
    assert len(h) == 13
    expected = (h["result_combined_hkd_m"] / h["revenue_combined_hkd_m"] * 100).round(2)
    assert (h["margin_pct"] - expected).abs().max() < 0.01


def test_whole_company_skeleton_base_scenario():
    """Skeleton base scenario must produce a sane underlying EPS near consensus."""
    require_local_normalized(
        "shkp_historical_earnings_bridge",
        "shkp_hotel_segment_series",
        "shkp_financial_model_consensus",
    )
    from src.hk_real_estate.shkp_whole_company_model import build_shkp_whole_company_skeleton
    bridge = load_latest_normalized("shkp_historical_earnings_bridge")
    hotel = load_latest_normalized("shkp_hotel_segment_series")
    consensus = load_latest_normalized("shkp_financial_model_consensus")
    out = build_shkp_whole_company_skeleton(earnings_bridge=bridge, hotel_series=hotel, consensus=consensus)
    skeleton = out["skeleton"]
    assert len(skeleton) == 18  # 3x3 matrix x 2 fiscal years (FY2026/27)
    base = skeleton[skeleton["scenario_is_base"]].iloc[0]
    assert 5.0 < base["underlying_eps_hkd"] < 12.0  # sane EPS range
    assert base["below_segment_run_rate_hkd_m"] < 0  # FY2025 residual is negative
    # hotel profit between revenue x bear and bull margins
    assert 500 < base["hotel_profit_hkd_m"] < 800
    # consensus comparison has FY2027 row with both model and consensus EPS
    comp = out["consensus_comparison"]
    fy27 = comp[comp["fiscal_year"].eq(2027)]
    assert not fy27.empty
    assert fy27["consensus_median_eps"].iloc[0] > 8.0
    assert fy27["model_base_underlying_eps"].iloc[0] > 0


def test_project_model_bridge_preserves_not_covered_as_a_gap():
    activity = pd.DataFrame(
        [
            {
                "srpe_development_id": "p1",
                "project_id": "p1",
                "period": "2026-08-01",
                "month_status": "not_covered",
                "sales_units_gross": pd.NA,
                "sales_value_gross_hkd": pd.NA,
                "cancelled_units": pd.NA,
                "active_units_eom": pd.NA,
                "published_inventory_units": pd.NA,
                "stock_code": "0016",
            }
        ]
    )
    registry = pd.DataFrame([{"srpe_development_id": "p1"}])
    bridge = build_shkp_project_model_bridge(activity, registry)
    row = bridge.iloc[0]
    assert row["sales_activity_status"] == "not_covered"
    assert pd.isna(row["sales_value_gross_hkd"])
    assert pd.isna(row["sales_units_gross"])
    assert row["model_use"] == "coverage_gap_only"


def test_whole_company_skeleton_defaults_do_not_require_hotel_frame():
    from src.hk_real_estate.shkp_whole_company_model import build_shkp_whole_company_skeleton

    output = build_shkp_whole_company_skeleton()
    assert set(output) == {"skeleton", "consensus_comparison"}
    assert len(output["skeleton"]) == 18


def test_handover_lag_distribution_and_recognition():
    """Lag distribution from paired phases must be complete with sane weights."""
    require_local_normalized("shkp_sales_handover_revenue_bridge", "shkp_historical_phase_roster")
    from src.hk_real_estate.shkp_handover_lag import (
        build_shkp_handover_lag_distribution,
        build_shkp_residential_recognition_schedule,
    )
    bridge = load_latest_normalized("shkp_sales_handover_revenue_bridge")
    roster = load_latest_normalized("shkp_historical_phase_roster")
    lag = build_shkp_handover_lag_distribution(bridge, roster)
    weights = lag.attrs.get("lag_weights") or {}
    assert weights.get("n_phases", 0) >= 15
    w0 = weights.get("lag_0_weight", 0.0)
    w1 = weights.get("lag_1_weight", 0.0)
    w2 = weights.get("lag_2_weight", 0.0)
    assert abs((w0 + w1 + w2) - 1.0) < 1e-9
    assert 0.2 < w1 < 0.7  # modal lag is 1 year
    rec = build_shkp_residential_recognition_schedule(
        lag,
        contract_activity_hkd={2025: 100.0, 2026: 200.0, 2027: 300.0},
        target_fiscal_years=[2027],
    )
    row = rec.iloc[0]
    assert row["recognised_residential_revenue_hkd"] == pytest.approx(w0 * 300 + w1 * 200 + w2 * 100)


def test_project_margin_model_weighted_fy27():
    """Project-mix weighted margin must be close to consensus-implied ~29.6%."""
    require_local_normalized(
        "shkp_residential_recognition_schedule",
        "shkp_indicative_project_month_signals_all_history",
        "shkp_historical_phase_roster",
    )
    from src.hk_real_estate.shkp_project_margin_model import (
        build_shkp_fy27_weighted_margin,
        build_shkp_project_margin_model,
    )
    recognition = load_latest_normalized("shkp_residential_recognition_schedule")
    signals = load_latest_normalized("shkp_indicative_project_month_signals_all_history")
    roster = load_latest_normalized("shkp_historical_phase_roster")
    projects = build_shkp_project_margin_model(recognition, signals=signals, phase_roster=roster)
    assert not projects.empty
    assert {"margin_bucket", "margin_point", "recognised_revenue_hkd"}.issubset(projects.columns)
    weighted = build_shkp_fy27_weighted_margin(projects)
    row = weighted.iloc[0]
    assert 0.20 < row["weighted_margin_point"] < 0.40
    assert row["weighted_margin_low"] < row["weighted_margin_point"] < row["weighted_margin_high"]
    # revenue weights sum to ~100%
    # weights sum to 100 within each fiscal year
    for fy, group in projects.groupby("fiscal_year"):
        assert abs(group["recognised_weight_pct"].sum() - 100.0) < 1.0


def test_margin_variant_group_sensitivity_and_consensus_required():
    """Group sensitivity + consensus-required feasibility must be coherent."""
    require_local_normalized("shkp_project_margin_model")
    from src.hk_real_estate.shkp_margin_variant import (
        build_shkp_margin_consensus_required,
        build_shkp_margin_group_sensitivity,
    )
    projects = load_latest_normalized("shkp_project_margin_model")
    groups = build_shkp_margin_group_sensitivity(projects)
    assert len(groups) >= 8
    # revenue weights sum to 100
    assert abs(groups["revenue_weight_pct"].sum() - 100.0) < 1.0
    # Sierra Sea and Other are the two largest groups with high EPS sensitivity
    top2 = groups.sort_values("eps_per_1pp_margin", ascending=False).head(2)
    assert set(top2["group"]) >= {"Sierra Sea", "Other"}
    assert top2["eps_per_1pp_margin"].min() > 0.02
    required = build_shkp_margin_consensus_required(groups)
    assert len(required) == len(groups)
    # at least the two largest groups are feasible
    assert required["feasible_within_bucket_plus_2pp"].sum() >= 2
    # single-group required margin is a delta from model point
    assert (required["consensus_required_margin"] - required["model_margin_point"]).abs().max() < 0.15


def test_below_segment_decomposition_mainland():
    """Mainland/Singapore decomposition must exist and expose the FY2025 elevation."""
    from src.hk_real_estate.shkp_earnings_bridge import _MAINLAND_SINGAPORE_SEGMENT
    assert len(_MAINLAND_SINGAPORE_SEGMENT) == 12
    fy25 = _MAINLAND_SINGAPORE_SEGMENT[2025]
    assert fy25["dev_ml_rev"] == 8417 and fy25["dev_ml_res"] == 5090
    assert fy25["rent_ml_rev"] == 6173 and fy25["rent_ml_res"] == 4864
    # FY2025 total is well above the 12-year mean (the variant signal)
    totals = [
        (v["dev_ml_res"] or 0) + (v["rent_ml_res"] or 0) + (v["rent_sg_res"] or 0)
        for v in _MAINLAND_SINGAPORE_SEGMENT.values()
    ]
    mean = sum(totals) / len(totals)
    assert totals[-1] > 1.4 * mean  # FY2025 elevation


def test_skeleton_backtest_converges():
    """Backtest (vintage margin default) must converge to single-digit MAE."""
    require_local_normalized(
        "shkp_historical_earnings_bridge",
        "shkp_hk_development_margin_history",
        "shkp_indicative_project_month_signals_all_history",
    )
    from src.hk_real_estate.shkp_skeleton_backtest import build_shkp_skeleton_backtest
    bridge = load_latest_normalized("shkp_historical_earnings_bridge")
    margin_history = load_latest_normalized("shkp_hk_development_margin_history")
    signals = load_latest_normalized("shkp_indicative_project_month_signals_all_history")
    bt = build_shkp_skeleton_backtest(bridge, margin_history, signals)
    assert len(bt) == 9  # FY2017-2025
    assert set(bt["margin_mode"]) == {"vintage"}  # default is the launch-cohort calibration
    # vintage moves the systematic early-year under-estimate to single digits
    assert bt["underlying_error_pct"].abs().mean() < 10
    # EPS error sign follows underlying error
    assert (bt["eps_error"] * bt["underlying_error_pct"] > 0).all()
    # legacy static bucket must still be reproducible and more conservative
    bt_bucket = build_shkp_skeleton_backtest(bridge, margin_history, signals, margin_mode="bucket")
    assert bt_bucket["underlying_error_pct"].abs().mean() > bt["underlying_error_pct"].abs().mean()


def test_skeleton_margin_decomposition_attributes_error():
    """Margin-vs-data attribution must exist and isolate the bucket conservatism."""
    require_local_normalized(
        "shkp_historical_earnings_bridge",
        "shkp_hk_development_margin_history",
        "shkp_indicative_project_month_signals_all_history",
    )
    from src.hk_real_estate.shkp_skeleton_backtest import build_shkp_skeleton_margin_decomposition
    bridge = load_latest_normalized("shkp_historical_earnings_bridge")
    margin_history = load_latest_normalized("shkp_hk_development_margin_history")
    signals = load_latest_normalized("shkp_indicative_project_month_signals_all_history")
    dc = build_shkp_skeleton_margin_decomposition(bridge, margin_history, signals)
    assert len(dc) == 9 * 4  # FY2017-2025 x 4 margin modes
    assert set(dc["margin_mode"]) == {"bucket", "vintage", "rolling_actual", "actual"}
    mae = dc.groupby("margin_mode")["underlying_error_pct"].apply(lambda s: s.abs().mean())
    # vintage (launch-cohort calibration) must beat the frozen static bucket
    assert mae["vintage"] < mae["bucket"]
    # bucket must still be systematically conservative pre-2022 (the documented regime effect)
    early_bucket = dc[(dc["margin_mode"] == "bucket") & (dc["fiscal_year_end"].le(2022))]["underlying_error_pct"]
    assert early_bucket.mean() < -10


def test_v1_full_chain_invariants():
    """v1.0 freeze gate: unit consistency + accounting identities across the chain."""
    require_local_normalized(
        "shkp_residential_recognition_schedule",
        "shkp_fy27_weighted_development_margin",
        "shkp_whole_company_earnings_skeleton",
    )
    rec = load_latest_normalized("shkp_residential_recognition_schedule")
    wm = load_latest_normalized("shkp_fy27_weighted_development_margin")
    sk = load_latest_normalized("shkp_whole_company_earnings_skeleton")
    base = sk[sk["scenario_is_base"]]
    # unit scales
    for fy, row in wm.iterrows():
        assert 0.2 < row["weighted_margin_point"] < 0.4
    for _, r in base.iterrows():
        assert 5 < r["underlying_eps_hkd"] < 12
        assert 15000 < r["underlying_profit_hkd_m"] < 35000
        # accounting identities
        assert abs(r["underlying_profit_hkd_m"] - (r["modelled_segment_profit_hkd_m"] + r["below_segment_run_rate_hkd_m"])) < 0.5
        assert abs(r["reported_profit_hkd_m"] - (r["underlying_profit_hkd_m"] + r["fv_run_rate_hkd_m"])) < 0.5
        assert abs(r["underlying_eps_hkd"] - r["underlying_profit_hkd_m"] / 2896.0) < 0.02
    # version: skeleton margin = weighted margin (not legacy 24%)
    for fy in (2026, 2027):
        wm_row = wm[wm["fiscal_year"].eq(fy)].iloc[0]
        sk_row = base[base["fiscal_year"].eq(fy)].iloc[0]
        recog = rec[rec["fiscal_year_end"].eq(fy)]["recognised_residential_revenue_hkd"].iloc[0]
        implied = sk_row["residential_development_profit_hkd_m"] / (recog / 1e6)
        assert abs(implied - wm_row["weighted_margin_point"]) < 0.005
