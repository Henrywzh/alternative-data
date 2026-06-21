from __future__ import annotations

from pathlib import Path
import json

import pandas as pd

from taiwan_semiconductor_revenue_data.models import CompanyConfig, Snapshot
from taiwan_semiconductor_revenue_data.pipeline import TaiwanSemiconductorRevenuePipeline
from taiwan_semiconductor_revenue_data.sources.mops import MopsMonthlyRevenueSource
from taiwan_semiconductor_revenue_data.storage import StorageManager


FIXTURES = Path(__file__).parent / "fixtures"


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_source_extracts_twse_and_tpex_rows_from_fixtures() -> None:
    source = MopsMonthlyRevenueSource()
    companies = [
        CompanyConfig(company_code="2330", company_name="TSMC", market="TWSE", industry="Foundry"),
        CompanyConfig(company_code="2303", company_name="UMC", market="TWSE", industry="Foundry"),
        CompanyConfig(company_code="5347", company_name="VIS", market="TPEx", industry="Foundry"),
    ]

    twse_points, twse_failures = source.extract(
        Snapshot(
            name="sii_2025_05",
            source_url="fixture://sii/2025-05",
            body=_read_fixture("tw_monthly_revenue_sii_114_05.html"),
        ),
        companies=companies[:2],
        run_id="run-1",
        scraped_at="2026-06-20T00:00:00Z",
        parser_version="test-parser",
    )
    tpex_points, tpex_failures = source.extract(
        Snapshot(
            name="otc_2025_05",
            source_url="fixture://otc/2025-05",
            body=_read_fixture("tw_monthly_revenue_otc_114_05.html"),
        ),
        companies=companies[2:],
        run_id="run-1",
        scraped_at="2026-06-20T00:00:00Z",
        parser_version="test-parser",
    )

    assert twse_failures == []
    assert tpex_failures == []
    assert len(twse_points) == 2
    assert len(tpex_points) == 1

    tsmc = next(point for point in twse_points if point.company_code == "2330")
    assert tsmc.company_name == "台積電"
    assert tsmc.market == "TWSE"
    assert tsmc.revenue_month == "2025-05"
    assert tsmc.filing_date == "2025-06-10"
    assert tsmc.monthly_revenue_ntd == 416987654.0
    assert tsmc.mom_pct == 1.5
    assert tsmc.yoy_pct == 30.1
    assert tsmc.ytd_revenue_ntd == 1961800000.0
    assert tsmc.ytd_yoy_pct == 30.0
    assert tsmc.raw_monthly_revenue_text == "416,987,654"

    vis = tpex_points[0]
    assert vis.company_code == "5347"
    assert vis.company_name == "世界先進"
    assert vis.market == "TPEx"
    assert vis.revenue_month == "2025-05"
    assert vis.filing_date == "2025-06-10"
    assert vis.monthly_revenue_ntd == 4123456.0
    assert vis.ytd_yoy_pct == 10.4


def test_source_handles_missing_optional_columns() -> None:
    source = MopsMonthlyRevenueSource()
    companies = [CompanyConfig(company_code="2330", company_name="TSMC", market="TWSE", industry="Foundry")]

    points, failures = source.extract(
        Snapshot(
            name="sii_2025_05",
            source_url="fixture://sii/2025-05-missing",
            body=_read_fixture("tw_monthly_revenue_missing_optional.html"),
        ),
        companies=companies,
        run_id="run-1",
        scraped_at="2026-06-20T00:00:00Z",
        parser_version="test-parser",
    )

    assert failures == []
    assert len(points) == 1
    point = points[0]
    assert point.monthly_revenue_ntd == 416987654.0
    assert point.mom_pct is None
    assert point.ytd_revenue_ntd is None
    assert point.ytd_yoy_pct is None


def test_source_extracts_live_api_json_shape() -> None:
    source = MopsMonthlyRevenueSource()
    companies = [CompanyConfig(company_code="2330", company_name="TSMC", market="TWSE", industry="Foundry")]

    points, failures = source.extract(
        Snapshot(
            name="2330_2025_05",
            source_url="fixture://api/2330/2025-05",
            body=json.dumps(
                {
                    "code": 200,
                    "message": "查詢成功",
                    "result": {
                        "data": [
                            ["本月", "416,975,163"],
                            ["去年同期", "320,515,951"],
                            ["增減金額", "96,459,212"],
                            ["增減百分比", "30.09"],
                            ["本年累計", "1,961,803,721"],
                            ["去年累計", "1,509,336,555"],
                            ["增減金額", "452,467,166"],
                            ["增減百分比", "29.98"],
                            ["備註/營收變化原因說明", ""],
                        ],
                        "yymm": "11505",
                        "companyAbbreviation": "台積電",
                        "marketKindName": "上市公司",
                    },
                    "datetime": "115/06/20 23:25:11",
                }
            ),
        ),
        companies=companies,
        run_id="run-1",
        scraped_at="2026-06-20T00:00:00Z",
        parser_version="test-parser",
    )

    assert failures == []
    assert len(points) == 1
    point = points[0]
    assert point.revenue_month == "2026-05"
    assert point.filing_date == "2026-06-20"
    assert point.monthly_revenue_ntd == 416975163.0
    assert point.yoy_pct == 30.09
    assert point.ytd_yoy_pct == 29.98


class _FakeApiResponse:
    def __init__(self, payload: dict) -> None:
        self.text = json.dumps(payload)

    def raise_for_status(self) -> None:
        return None


class _RecordingSession:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def post(self, url: str, headers: dict[str, str], json: dict[str, str], timeout: int) -> _FakeApiResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _FakeApiResponse(
            {
                "code": 200,
                "message": "查詢成功",
                "result": {
                    "data": [
                        ["本月", "1,000"],
                        ["去年同期", "900"],
                        ["增減金額", "100"],
                        ["增減百分比", "11.11"],
                        ["本年累計", "5,000"],
                        ["去年累計", "4,500"],
                        ["增減金額", "500"],
                        ["增減百分比", "11.11"],
                    ],
                    "yymm": "11504",
                    "companyAbbreviation": "台積電",
                    "marketKindName": "上市公司",
                },
                "datetime": "115/06/20 23:29:20",
            }
        )


def test_fetch_snapshots_uses_custom_query_payload_for_specific_months() -> None:
    session = _RecordingSession()
    source = MopsMonthlyRevenueSource(session=session)

    snapshots = source.fetch_snapshots(
        months=["2026-04"],
        companies=[CompanyConfig(company_code="2330", company_name="TSMC", market="TWSE", industry="Foundry")],
    )

    assert len(snapshots) == 1
    assert session.calls[0]["url"] == "https://mops.twse.com.tw/mops/api/t05st10_ifrs"
    assert session.calls[0]["json"] == {
        "companyId": "2330",
        "dataType": "2",
        "month": "4",
        "year": "115",
        "subsidiaryCompanyId": "",
    }


def test_storage_upserts_parquet_only(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    companies = [CompanyConfig(company_code="2330", company_name="TSMC", market="TWSE", industry="Foundry")]
    source = MopsMonthlyRevenueSource()
    points, _ = source.extract(
        Snapshot(
            name="sii_2025_05",
            source_url="fixture://sii/2025-05",
            body=_read_fixture("tw_monthly_revenue_sii_114_05.html"),
        ),
        companies=companies,
        run_id="run-1",
        scraped_at="2026-06-20T00:00:00Z",
        parser_version="test-parser",
    )

    storage.upsert_dataset("tw_monthly_revenue", points)
    storage.upsert_dataset("tw_monthly_revenue", points)

    parquet_path = tmp_path / "data" / "normalized" / "taiwan_semiconductor_revenue" / "tw_monthly_revenue.parquet"
    csv_path = tmp_path / "data" / "normalized" / "taiwan_semiconductor_revenue" / "tw_monthly_revenue.csv"
    written = pd.read_parquet(parquet_path)

    assert parquet_path.exists()
    assert not csv_path.exists()
    assert len(written) == 1
    assert written.iloc[0]["company_code"] == "2330"


class FixtureSource(MopsMonthlyRevenueSource):
    def __init__(self, snapshots_by_month: dict[str, list[Snapshot]]) -> None:
        super().__init__()
        self.snapshots_by_month = snapshots_by_month

    def fetch_snapshots(
        self,
        months: list[str],
        companies: list[CompanyConfig],
    ) -> list[Snapshot]:
        snapshots: list[Snapshot] = []
        for month in months:
            snapshots.extend(self.snapshots_by_month[month])
        return snapshots


def test_pipeline_backfill_then_latest_update(tmp_path: Path) -> None:
    may_twse = Snapshot(
        name="sii_2025_05",
        source_url="fixture://sii/2025-05",
        body=_read_fixture("tw_monthly_revenue_sii_114_05.html"),
    )
    may_tpex = Snapshot(
        name="otc_2025_05",
        source_url="fixture://otc/2025-05",
        body=_read_fixture("tw_monthly_revenue_otc_114_05.html"),
    )
    june_twse = Snapshot(
        name="sii_2025_06",
        source_url="fixture://sii/2025-06",
        body=_read_fixture("tw_monthly_revenue_sii_114_05.html")
        .replace("114/05", "114/06")
        .replace("114/06/10", "114/07/10")
        .replace("416,987,654", "420,000,000")
        .replace("1,961,800,000", "2,381,800,000")
        .replace("18,765,432", "19,100,000")
        .replace("92,345,678", "111,445,678"),
    )
    june_tpex = Snapshot(
        name="otc_2025_06",
        source_url="fixture://otc/2025-06",
        body=_read_fixture("tw_monthly_revenue_otc_114_05.html")
        .replace("114/05", "114/06")
        .replace("114/06/10", "114/07/10")
        .replace("4,123,456", "4,456,789")
        .replace("20,567,890", "25,024,679"),
    )

    source = FixtureSource(
        {
            "2025-05": [may_twse, may_tpex],
            "2025-06": [june_twse, june_tpex],
        }
    )
    pipeline = TaiwanSemiconductorRevenuePipeline(tmp_path, source=source)

    backfill = pipeline.run_backfill(start_month="2025-05", end_month="2025-05")
    latest = pipeline.run_update_latest(revenue_month="2025-06")

    assert backfill.datasets_written["tw_monthly_revenue"] == 3
    assert backfill.dataset_row_deltas["tw_monthly_revenue"] == 3
    assert latest.datasets_written["tw_monthly_revenue"] == 6
    assert latest.dataset_row_deltas["tw_monthly_revenue"] == 3

    dataset = pd.read_parquet(
        tmp_path / "data" / "normalized" / "taiwan_semiconductor_revenue" / "tw_monthly_revenue.parquet"
    )
    assert set(dataset["revenue_month"]) == {"2025-05", "2025-06"}
    assert set(dataset["company_code"]) == {"2330", "2303", "5347"}


def test_pipeline_continues_when_one_company_row_fails(tmp_path: Path) -> None:
    broken_tpex_html = _read_fixture("tw_monthly_revenue_otc_114_05.html").replace("4,123,456", "not-a-number")
    source = FixtureSource(
        {
            "2025-05": [
                Snapshot(
                    name="sii_2025_05",
                    source_url="fixture://sii/2025-05",
                    body=_read_fixture("tw_monthly_revenue_sii_114_05.html"),
                ),
                Snapshot(
                    name="otc_2025_05",
                    source_url="fixture://otc/2025-05",
                    body=broken_tpex_html,
                ),
            ]
        }
    )
    pipeline = TaiwanSemiconductorRevenuePipeline(tmp_path, source=source)

    result = pipeline.run_backfill(start_month="2025-05", end_month="2025-05")

    dataset = pd.read_parquet(
        tmp_path / "data" / "normalized" / "taiwan_semiconductor_revenue" / "tw_monthly_revenue.parquet"
    )
    counts = pipeline.validate()

    assert result.datasets_written["tw_monthly_revenue"] == 2
    assert set(dataset["company_code"]) == {"2330", "2303"}
    assert counts["rows"] == 2
    assert counts["duplicate_keys"] == 0
