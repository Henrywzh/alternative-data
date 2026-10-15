import json
from pathlib import Path
import sys

import pandas as pd
import pytest

from china_macro.artifact import build_artifacts, coverage
from china_macro.normalize import clean, derive, observation, missing_months
from china_macro.sources import eastmoney
from china_macro.pbc import parse_afre, pbc_period, ordered_months
from china_macro.press import parse_release, parse_release_html
from china_macro.pipeline import run_pipeline, needs_history_backfill
from china_macro.storage import load_current, save_current

NOW = "2026-10-12T01:00:00Z"


def test_injected_partial_jobs_cannot_publish_production():
    with pytest.raises(ValueError, match="partial jobs"):
        run_pipeline(jobs={"fixture": lambda: clean([])})


def row(metric, date, value, captured=NOW):
    return observation(metric, date, value, "fixture", "https://example.com", captured)


def manifest(run_id="20261012T010000-test", refreshed=None):
    return dict(run_id=run_id, created_at=NOW, source_results=[], refreshed_metrics=refreshed or ["pmi"], scope="full")


def test_missing_infinite_and_future_values_are_not_observations():
    assert row("pmi", "2026-09-01", 0)["value"] == 0
    assert row("pmi", "2026-09-01", None) is None
    assert row("pmi", "2026-09-01", float("inf")) is None
    assert row("pmi", "2026-11-01", 50) is None


def test_archival_numeric_boundary_whitespace_is_not_missing_data():
    assert row("household_loan_balance", "2022-01-01", "719427.70\u00a0")["value"] == 719427.7
    assert row("tsf_rmb_loans", "2022-01-01", "\u00a0-552.00\u00a0")["value"] == -552
    assert row("tsf_rmb_loans", "2022-01-01", "0\u00a0")["value"] == 0
    assert row("tsf_rmb_loans", "2022-01-01", "\u00a0") is None
    assert row("tsf_rmb_loans", "2022-01-01", "1 2") is None


def test_internal_credit_gaps_trigger_annual_archive_retry():
    history = clean([row("household_loan_balance", date, 100) for date in ["2022-01-01", "2022-03-01"]])
    assert needs_history_backfill(history, ["household_loan_balance"])
    assert needs_history_backfill(history, ["corporate_loan_balance"])
    complete = clean([row("household_loan_balance", date, 100) for date in ["2022-01-01", "2022-02-01"]])
    assert not needs_history_backfill(complete, ["household_loan_balance"])


def test_monthly_grain_and_revision_deduplication():
    result = clean([row("pmi", "2026-09-01", 49), row("pmi", "2026-09-30", 50)])
    assert len(result) == 1
    assert result.iloc[0]["value"] == 50
    assert result.iloc[0]["date"] == "2026-09-01"


def test_january_february_and_gdp_scope_are_explicit():
    result = clean([row("industrial_yoy", "2026-02-01", 5), row("gdp_yoy", "2026-06-01", 4.7)])
    industry = result[result.metric == "industrial_yoy"].iloc[0]
    assert industry["scope"] == "jan_feb"
    assert industry["period_start"] == "2026-01-01"
    assert industry["period_end"] == "2026-02-28"
    gdp = result[result.metric == "gdp_yoy"].iloc[0]
    assert gdp["period_end"] == "2026-06-30"
    assert gdp["period_start"] == "2026-01-01"


def test_combined_period_begins_in_2012_and_only_january_is_exempt():
    history = clean([row("retail_yoy", date, 3) for date in ["2011-12-01", "2012-02-01", "2012-04-01"]])
    assert history.loc[history.date.eq("2012-02-01"), "scope"].item() == "jan_feb"
    assert missing_months(history, "retail_yoy") == ["2012-03"]
    assert missing_months(clean([row("pmi", "2025-12-01", 50), row("pmi", "2026-02-01", 50)]), "pmi") == ["2026-01"]


def test_eastmoney_combined_fields_never_replace_ordinary_months():
    class Response:
        def json(self):
            return {"result": {"pages": 1, "data": [
                {"REPORT_DATE": "2026-02-01", "RETAIL_TOTAL": None, "RETAIL_TOTAL_SAME": None,
                 "RETAIL_TOTAL_ACCUMULATE": 86078.9, "RETAIL_ACCUMULATE_SAME": 2.8},
                {"REPORT_DATE": "2026-03-01", "RETAIL_TOTAL": 41616, "RETAIL_TOTAL_SAME": 0,
                 "RETAIL_TOTAL_ACCUMULATE": 127694.9, "RETAIL_ACCUMULATE_SAME": 2.4}]}}
    class Fetch:
        def get(self, *args, **kwargs):
            return Response()
    result = eastmoney(Fetch(), "RPT_ECONOMY_TOTAL_RETAIL", NOW)
    assert result[(result.metric == "retail") & (result.date == "2026-02-01")]["value"].item() == pytest.approx(8607.89)
    assert result[(result.metric == "retail_yoy") & (result.date == "2026-03-01")]["value"].item() == 0
    assert result[(result.metric == "retail") & (result.date == "2026-03-01")]["scope"].item() == "month"


@pytest.mark.parametrize("headline, date", [("2025年全国固定资产投资基本情况", "2025-12-01"), ("2023年上半年全国固定资产投资增长3.8%", "2023-06-01")])
def test_annual_and_half_year_releases_ignore_prior_year_revision_table(headline, date):
    text = headline + "基础设施投资（不含电力、热力、燃气及水生产和供应业）比上年下降2.2%。附注：2024年12月环比修订。"
    result = parse_release(text, "https://stats.gov.cn/202601/t20260119_1.html", NOW)
    assert result.date.item() == date
    assert result.value.item() == -2.2


def test_infrastructure_definitions_are_not_spliced():
    result = parse_release("2026年1—4月份全国固定资产投资基本情况 基础设施投资（口径详见附注1）同比增长4.3%。", "https://stats.gov.cn/202605/t20260518_1.html", NOW)
    assert result.metric.item() == "infrastructure_investment_incl_utilities_yoy"
    migrated = clean([row("infrastructure_investment_yoy", "2026-02-01", 11.4)])
    assert migrated.metric.item() == "infrastructure_investment_incl_utilities_yoy"


def test_information_disclosure_headline_not_comparison_year_or_publication_month():
    html = '<title>国家统计局信息公开</title><h2 class="xxgkNbXqTitle">2021年1—2月份全国固定资产投资</h2><div class="TRS_Editor">比2019年1—2月份增长；基础设施投资（不含电力、热力、燃气及水生产和供应业）同比增长36.6%。</div>成文日期2021年03月15日'
    result = parse_release_html(html, "https://stats.gov.cn/202302/t20230203_1.html", NOW)
    assert result.date.item() == "2021-02-01"
    assert result.release_date.item() == "2021-03-15"


def test_derived_series_use_same_dates_and_oldest_capture():
    result = derive(clean([row("pmi_new_orders", "2026-09-01", 51), row("pmi_inventory", "2026-09-01", 46, "2026-10-01T00:00:00Z"), row("pmi_inventory", "2026-08-01", 40)]), NOW)
    assert len(result) == 1
    assert result.iloc[0]["value"] == 5
    assert result.iloc[0]["retrieved_at"] == "2026-10-01T00:00:00Z"


def test_three_month_mean_does_not_bridge_missing_month():
    result = derive(clean([row("exports_yoy", date, 10) for date in ["2026-06-01", "2026-08-01", "2026-09-01"]]), NOW)
    assert result.empty
    result = derive(clean([row("exports_yoy", f"2026-{month:02}-01", month) for month in [7, 8, 9]]), NOW)
    assert result.iloc[0]["value"] == 8


def test_legacy_m1_cannot_enter_comparable_spread():
    result = derive(clean([row("m1_legacy_yoy", "2024-12-01", -1.4), row("m2_yoy", "2024-12-01", 7.3)]), NOW)
    assert result.empty


def test_afre_flow_units_negative_values_and_blank_future():
    table = pd.DataFrame([["社会融资规模增量统计表", None, None, None], ["月份", "社会融资规模增量", "人民币贷款", "政府债券"], ["2026.08", 16577, -552, 10097], ["2026.09", None, None, None]])
    result = parse_afre(table, "https://pbc.gov.cn/fixture.xlsx", NOW)
    assert len(result) == 3
    assert result[result.metric == "tsf_flow"].iloc[0]["value"] == 1657.7
    assert result[result.metric == "tsf_rmb_loans"].iloc[0]["value"] == -55.2


def test_afre_stock_units():
    table = pd.DataFrame([["社会融资规模存量统计表", None, None], ["单位：万亿元人民币", None, None], [None, "2026.08", None], ["项目", "存量", "增速（%）"], ["社会融资规模存量", 464.8, 7.2]])
    result = parse_afre(table, "https://pbc.gov.cn/fixture.xlsx", NOW)
    assert result[result.metric == "tsf_stock"].iloc[0]["value"] == 464800
    assert result[result.metric == "tsf_stock_yoy"].iloc[0]["value"] == 7.2


def test_afre_embedded_percentage_tables_cannot_overwrite_amounts():
    title = ["社会融资规模增量统计表", None, None]
    header = ["月份", "社会融资规模增量", "人民币贷款"]
    amounts = [[float(f"2019.{month:02}"), month * 1000, month * 500] for month in range(1, 13)]
    table = pd.DataFrame([title, header, *amounts,
                          ["表2：各月社会融资规模增量占比数据", None, None],
                          ["单位：%", None, None], header,
                          [2019.01, 100, 60], [2019.1, 100, 60]])
    result = parse_afre(table, "https://pbc.gov.cn/fixture.xls", NOW)
    assert len(result) == 24
    assert result[(result.metric == "tsf_flow") & (result.date == "2019-01-01")]["value"].item() == 100
    assert result[(result.metric == "tsf_flow") & (result.date == "2019-10-01")]["value"].item() == 1000


def test_october_string_does_not_become_january():
    assert pbc_period("2026.10") == "2026-10-01"
    assert pbc_period("2026年12月") == "2026-12-01"
    assert ordered_months([float(f"2026.{month:02}") for month in range(1, 13)])[9] == "2026-10-01"


def test_core_cpi_rising_or_falling_growth_is_not_negative_inflation():
    for text in ["2026年8月份：核心CPI同比涨幅回升至1.0%。", "2026年8月份：核心CPI同比涨幅回落至1.0%。"]:
        assert parse_release(text, "https://stats.gov.cn/202609/t20260909_1.html", NOW).iloc[0]["value"] == 1


def test_official_calendar_does_not_expect_september_cpi_before_release():
    frame = clean([row("cpi_yoy", "2026-08-01", .8)])
    run = manifest(refreshed=["cpi_yoy"])
    run["publication_calendar"] = [dict(family="prices", reference_date="2026-08-01", release_date="2026-09-09"), dict(family="prices", reference_date="2026-09-01", release_date="2026-10-14")]
    health = {r["metric"]: r for r in coverage(frame, run, NOW)}
    assert health["cpi_yoy"]["status"] == "Available"
    assert health["cpi_yoy"]["expected_reference"] == "2026-08-01"
    health = {r["metric"]: r for r in coverage(frame, run, "2026-10-15T01:00:00Z")}
    assert health["cpi_yoy"]["status"] == "Stale"


def test_loan_balance_change_is_not_a_new_lending_series_and_cannot_bridge_gap():
    result = derive(clean([row("household_loan_balance", "2026-06-01", 100), row("household_loan_balance", "2026-08-01", 120), row("household_loan_balance", "2026-09-01", 125)]), NOW)
    assert len(result) == 1
    assert result.iloc[0]["value"] == 5
    assert "not official new lending" in result.iloc[0]["definition"]


def test_empty_snapshot_cannot_replace_current(tmp_path):
    save_current(clean([row("pmi", "2026-09-01", 50)]), clean([]), manifest(), tmp_path)
    with pytest.raises(ValueError, match="empty"):
        save_current(clean([]), clean([]), manifest("20261012T010001-test"), tmp_path)
    assert load_current(tmp_path)[2]["run_id"] == "20261012T010000-test"


def test_corrupt_dataset_fails_closed(tmp_path):
    save_current(clean([row("pmi", "2026-09-01", 50)]), clean([]), manifest(), tmp_path)
    path = tmp_path / "runs/20261012T010000-test/observations.parquet"
    path.write_bytes(b"broken")
    with pytest.raises(ValueError, match="integrity"):
        load_current(tmp_path)


def test_failed_fetch_retains_prior_without_recapture(tmp_path):
    save_current(clean([row("pmi", "2026-09-01", 50, "2026-10-01T00:00:00Z")]), clean([]), manifest(), tmp_path)
    def fail():
        raise ValueError("unavailable")
    observations, _, run = run_pipeline(root=tmp_path, jobs={"pmi": fail, "cpi": lambda: clean([row("cpi_yoy", "2026-08-01", .8)])})
    assert observations[observations.metric == "pmi"].iloc[0]["retrieved_at"] == "2026-10-01T00:00:00Z"
    assert run["refreshed_metrics"] == ["cpi_yoy"]


def test_reparsed_pbc_workbook_removes_old_supplementary_ratio_rows(tmp_path):
    url = "https://www.pbc.gov.cn/annual.xls"
    def pbc_row(metric, date, value):
        return observation(metric, date, value, "People's Bank of China", url, NOW)
    old = clean([pbc_row("tsf_flow", "2019-01-01", 10),
                 pbc_row("tsf_government", "2017-01-01", 3.13)])
    save_current(old, clean([]), manifest(), tmp_path)
    fresh = clean([pbc_row("tsf_flow", "2019-01-01", 4604)])
    observations, _, run = run_pipeline(root=tmp_path, jobs={"pbc:afre": lambda: fresh})
    assert len(observations) == 1
    assert observations.value.item() == 4604
    assert run["replaced_pbc_archival_rows"] == 2


def test_all_failed_fetches_do_not_publish(tmp_path):
    save_current(clean([row("pmi", "2026-09-01", 50)]), clean([]), manifest(), tmp_path)
    with pytest.raises(RuntimeError, match="All China"):
        run_pipeline(root=tmp_path, jobs={"empty": lambda: clean([])})
    assert load_current(tmp_path)[2]["run_id"] == "20261012T010000-test"


def test_bilingual_artifacts_same_run_and_numbers(tmp_path):
    root, output = tmp_path / "data", tmp_path / "artifact"
    save_current(clean([row("pmi", "2026-09-01", 50)]), clean([]), manifest(), root)
    build_artifacts(root, output)
    en = json.loads((output / "china-macro-artifact.json").read_text())
    zh = json.loads((output / "china-macro-artifact-zh.json").read_text())
    assert en["run_id"] == zh["run_id"]
    assert en["snapshot"]["datasets"] == zh["snapshot"]["datasets"]
    assert len(en["snapshot"]["datasets"]["source_health"]) > 50


@pytest.mark.parametrize("language", ["en", "zh"])
def test_china_page_apptest(language):
    from streamlit.testing.v1 import AppTest
    app_dir = Path(__file__).resolve().parents[2] / "apps/asia-markets-streamlit"
    script = f"import sys\nsys.path.insert(0, {str(app_dir)!r})\nfrom am.china_macro import render_china_macro\nrender_china_macro({language!r}, '10 years')"
    app = AppTest.from_string(script, default_timeout=40).run()
    assert not app.exception
    assert len(app.get("plotly_chart")) >= 20
    for select in app.multiselect:
        assert len(select.value) == len(select.options)
    app.radio[0].set_value("monthly").run()
    assert not app.exception
    app.radio[0].set_value("weekly").run()
    assert not app.exception
