from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from semiconductor_proxy_data.models import BackupCheckPoint, OfficialMonthlyPoint, Snapshot, SourceCatalogPoint
from semiconductor_proxy_data.pipeline import SemiconductorProxyPipeline
from semiconductor_proxy_data.sources.comtrade import ComtradeSource
from semiconductor_proxy_data.sources.hongkong_censtatd import HongKongCenstatdSource
from semiconductor_proxy_data.sources.japan_customs import JapanCustomsSource
from semiconductor_proxy_data.sources.korea_customs import KoreaCustomsSource
from semiconductor_proxy_data.sources.nbs import NbsSource
from semiconductor_proxy_data.storage import StorageManager


class MockResponse:
    def __init__(self, text: str, status_code: int = 200, url: str = "http://mocked") -> None:
        self.text = text
        self.status_code = status_code
        self.url = url

    def json(self) -> dict:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code != 200:
            raise Exception("Mocked request failure")


def test_comtrade_source_extraction() -> None:
    source = ComtradeSource()
    body = {
        "elapsedTime": "0.1 secs",
        "count": 1,
        "data": [
            {
                "typeCode": "C",
                "freqCode": "M",
                "period": "202503",
                "reporterCode": 410,
                "reporterDesc": "Korea, Rep.",
                "flowCode": "X",
                "partnerCode": 0,
                "partnerDesc": "World",
                "cmdCode": "8542",
                "primaryValue": 12500000000.0,
                "netWeight": 1500000.0,
            }
        ],
    }
    snapshot = Snapshot(
        name="test_comtrade",
        source_url="http://mocked/comtrade",
        body=json.dumps(body),
    )

    points = source.extract([snapshot], run_id="test-run", scraped_at="2026-06-20T00:00:00Z")
    assert len(points) == 1
    p = points[0]
    assert p.period == "2025-03"
    assert p.source_region == "korea"
    assert p.country_name == "South Korea"
    assert p.partner_scope == "world"
    assert p.flow_code == "X"
    assert p.classification_code == "8542"
    assert p.value == 12500000000.0


def test_nbs_source_extraction() -> None:
    source = NbsSource()
    body = {
        "returncode": 200,
        "returndata": {
            "datanodes": [
                {
                    "code": "zb.A02092C_sj.202503",
                    "wds": [
                        {"wdcode": "zb", "valuecode": "A02092C"},
                        {"wdcode": "sj", "valuecode": "202503"},
                    ],
                    "data": {
                        "hasdata": True,
                        "data": 350.5,
                    },
                }
            ]
        },
    }
    snapshot = Snapshot(
        name="test_nbs",
        source_url="http://mocked/nbs",
        body=json.dumps(body),
    )

    points = source.extract([snapshot], run_id="test-run", scraped_at="2026-06-20T00:00:00Z")
    assert len(points) == 1
    p = points[0]
    assert p.period == "2025-03"
    assert p.metric_type == "production"
    assert p.classification_code == "A02092C"
    assert p.value == 350.5


def test_nbs_source_skips_non_china_requests() -> None:
    source = NbsSource()
    snapshots = source.fetch_snapshots(months=["2025-03"], regions=["japan"], categories=["ic_only"])
    assert snapshots == []


def test_japan_customs_source_extraction() -> None:
    source = JapanCustomsSource()
    body = """
<html>
<body>
<p>The latest Trade Statistics data which has been made public so far is April, 2026.</p>
<table class="value">
  <tr>
    <th>YEAR / MONTH</th><th>UNIT</th><th>QUANTITY</th><th>VALUE</th><th>QUANTITY</th><th>VALUE</th>
  </tr>
  <tr>
    <td class="left_Meisai">2024/01</td>
    <td class="left_Meisai">NO</td>
    <td class="Meisai">5210347507</td>
    <td class="Meisai">329367542</td>
    <td class="Meisai">5210347507</td>
    <td class="Meisai">329367542</td>
  </tr>
  <tr>
    <td class="left_Meisai">2024/02</td>
    <td class="left_Meisai">NO</td>
    <td class="Meisai">5975861427</td>
    <td class="Meisai">324999611</td>
    <td class="Meisai">11186208934</td>
    <td class="Meisai">654367153</td>
  </tr>
</table>
</body>
</html>
"""
    snapshot = Snapshot(
        name="official_japan_ic_only_2024-01_2024-02",
        source_url="https://www.customs.go.jp/JCWSV20/servlet/JCWSV20",
        body=body,
    )

    points = source.extract([snapshot], run_id="test-run", scraped_at="2026-06-21T00:00:00Z")
    assert len(points) == 2
    january = points[0]
    assert january.source_region == "japan"
    assert january.metric_type == "exports"
    assert january.period == "2024-01"
    assert january.classification_code == "7032305"
    assert january.value == 329367542.0
    assert january.unit == "jpy_thousand"
    assert january.currency == "JPY"
    assert january.release_date == "2026-04"
    assert january.partner_scope == "world"


def test_korea_customs_source_extraction_and_broad_aggregation() -> None:
    source = KoreaCustomsSource()
    snapshot = Snapshot(
        name="official_korea_broad_semiconductor_2026-04_2026-05",
        source_url="https://tradedata.go.kr/cts/hmpg/retrieveTrade.do",
        body=json.dumps(
            {
                "category_id": "broad_semiconductor",
                "responses": [
                    {
                        "classification_code": "8541",
                        "payload": {
                            "items": [
                                {
                                    "priodTitle": "총계",
                                    "expUsdAmt": "999",
                                    "impUsdAmt": "999",
                                    "cmtrBlncAmt": "0",
                                },
                                {
                                    "priodTitle": "2026.04",
                                    "korePrlstNm": "반도체디바이스",
                                    "expUsdAmt": "1,000",
                                    "impUsdAmt": "500",
                                    "cmtrBlncAmt": "500",
                                },
                                {
                                    "priodTitle": "2026.05",
                                    "korePrlstNm": "반도체디바이스",
                                    "expUsdAmt": "1,100",
                                    "impUsdAmt": "550",
                                    "cmtrBlncAmt": "550",
                                },
                            ]
                        },
                    },
                    {
                        "classification_code": "8542",
                        "payload": {
                            "items": [
                                {
                                    "priodTitle": "2026.04",
                                    "korePrlstNm": "전자집적회로",
                                    "expUsdAmt": "2,000",
                                    "impUsdAmt": "700",
                                    "cmtrBlncAmt": "1,300",
                                },
                                {
                                    "priodTitle": "2026.05",
                                    "korePrlstNm": "전자집적회로",
                                    "expUsdAmt": "2,200",
                                    "impUsdAmt": "800",
                                    "cmtrBlncAmt": "1,400",
                                },
                            ]
                        },
                    },
                ],
            }
        ),
    )

    points = source.extract([snapshot], run_id="test-run", scraped_at="2026-06-21T00:00:00Z")
    assert len(points) == 6

    exports = [point for point in points if point.metric_type == "exports"]
    april_export = next(point for point in exports if point.period == "2026-04")
    may_export = next(point for point in exports if point.period == "2026-05")

    assert april_export.source_region == "korea"
    assert april_export.country_name == "South Korea"
    assert april_export.category_id == "broad_semiconductor"
    assert april_export.classification_code == "8541,8542"
    assert april_export.unit == "usd"
    assert april_export.currency == "USD"
    assert april_export.value == 3000.0
    assert may_export.value == 3300.0

    imports = [point for point in points if point.metric_type == "imports"]
    assert next(point for point in imports if point.period == "2026-04").value == 1200.0

    balances = [point for point in points if point.metric_type == "trade_balance"]
    assert next(point for point in balances if point.period == "2026-05").value == 1950.0


def test_hongkong_censtatd_source_extraction() -> None:
    source = HongKongCenstatdSource()
    snapshot = Snapshot(
        name="official_hongkong_ic_only_2025-01_2025-02",
        source_url="https://tradeidds.censtatd.gov.hk/api/get",
        body=json.dumps(
            {
                "category_id": "ic_only",
                "responses": [
                    {
                        "metric_type": "exports",
                        "classification_code": "8542",
                        "payload": {
                            "dataSet": [
                                {
                                    "period": "202501",
                                    "codeDescEN": "ELECTRONIC INTEGRATED CIRCUITS AND MICROASSEMBLIES",
                                    "figure": "141590694",
                                },
                                {
                                    "period": "202502",
                                    "codeDescEN": "ELECTRONIC INTEGRATED CIRCUITS AND MICROASSEMBLIES",
                                    "figure": "126037552",
                                },
                            ]
                        },
                    },
                    {
                        "metric_type": "imports",
                        "classification_code": "8542",
                        "payload": {
                            "dataSet": [
                                {
                                    "period": "202501",
                                    "codeDescEN": "ELECTRONIC INTEGRATED CIRCUITS AND MICROASSEMBLIES",
                                    "figure": "136485489",
                                },
                                {
                                    "period": "202502",
                                    "codeDescEN": "ELECTRONIC INTEGRATED CIRCUITS AND MICROASSEMBLIES",
                                    "figure": "121042000",
                                },
                            ]
                        },
                    },
                ],
            }
        ),
    )

    points = source.extract([snapshot], run_id="test-run", scraped_at="2026-06-21T00:00:00Z")
    assert len(points) == 6

    export_point = next(point for point in points if point.metric_type == "exports" and point.period == "2025-01")
    import_point = next(point for point in points if point.metric_type == "imports" and point.period == "2025-01")
    balance_point = next(point for point in points if point.metric_type == "trade_balance" and point.period == "2025-01")

    assert export_point.source_region == "hongkong"
    assert export_point.country_name == "Hong Kong"
    assert export_point.classification_system == "HKHS"
    assert export_point.classification_code == "8542"
    assert export_point.unit == "hkd_thousand"
    assert export_point.currency == "HKD"
    assert export_point.value == 141590694.0
    assert import_point.value == 136485489.0
    assert balance_point.value == 5105205.0


def test_hongkong_censtatd_trims_undefined_latest_month() -> None:
    class StubResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self._payload

    class StubSession:
        def __init__(self) -> None:
            self.headers = {}
            self.periods: list[str] = []

        def get(self, url: str, params: dict[str, str], timeout: int, verify: bool) -> StubResponse:
            period = params["period"]
            self.periods.append(period)
            if period == "202601,202606":
                return StubResponse(
                    {
                        "header": {
                            "status": {
                                "name": "Fail",
                                "message": ["Period code (202606) is not defined"],
                            }
                        }
                    }
                )
            if period == "202601,202605":
                return StubResponse(
                    {
                        "header": {
                            "status": {
                                "name": "Fail",
                                "message": ["Period code (202605) is not defined"],
                            }
                        }
                    }
                )
            return StubResponse(
                {
                    "header": {"status": {"name": "Success"}},
                    "dataSet": [{"period": "202604", "figure": "123"}],
                }
            )

    session = StubSession()
    source = HongKongCenstatdSource(session=session)

    payload = source._fetch_series(
        classification_code="8542",
        trade_type="4",
        start_month="2026-01",
        end_month="2026-06",
    )

    assert session.periods == ["202601,202606", "202601,202605", "202601,202604"]
    assert payload["dataSet"] == [{"period": "202604", "figure": "123"}]


class FakeOfficialSource:
    def __init__(self) -> None:
        self.catalog = [
            SourceCatalogPoint(
                dataset_id="semiconductor_source_catalog",
                source_region="korea",
                country_name="South Korea",
                source_name="Korea Customs Service",
                source_tier="official",
                metric_type="exports",
                category_id="ic_only",
                category_label="IC-only",
                coverage_start="2025-01",
                latest_period="2025-03",
                cadence="monthly",
                expected_release_window_days=21,
                default_unit="usd",
                default_currency="USD",
                is_official_primary=True,
                notes="Fixture-backed official source for tests.",
                source_url="https://example.com/korea-official",
                source_run_id="catalog-run",
                scraped_at="2026-06-20T00:00:00Z",
            )
        ]

    def fetch_snapshots(self, months: list[str], regions: list[str], categories: list[str]) -> list[Snapshot]:
        return [Snapshot(name="official_korea_202503", source_url="https://example.com/korea-official", body="{}")]

    def extract(
        self,
        snapshots: list[Snapshot],
        run_id: str,
        scraped_at: str,
    ) -> list[OfficialMonthlyPoint]:
        return [
            OfficialMonthlyPoint(
                dataset_id="semiconductor_official_monthly",
                source_region="korea",
                country_name="South Korea",
                metric_type="exports",
                flow_code="X",
                partner_scope="world",
                period="2025-03",
                release_date="2025-04-15",
                expected_release_window_days=21,
                lag_days=15,
                category_id="ic_only",
                category_label="IC-only",
                classification_system="HS",
                classification_code="8542",
                unit="usd",
                currency="USD",
                value=1100000000.0,
                yoy_pct=12.5,
                mom_pct=4.0,
                is_preliminary=False,
                is_revised=False,
                is_official_primary=True,
                comparison_gap_pct=None,
                source_name="Korea Customs Service",
                source_url="https://example.com/korea-official",
                source_run_id=run_id,
                scraped_at=scraped_at,
                parser_version="test-official-v1",
            )
        ]

    def catalog_points(self, run_id: str, scraped_at: str) -> list[SourceCatalogPoint]:
        points: list[SourceCatalogPoint] = []
        for point in self.catalog:
            cloned = point.to_dict()
            cloned["source_run_id"] = run_id
            cloned["scraped_at"] = scraped_at
            points.append(SourceCatalogPoint(**cloned))
        return points


class FakeBackupSource:
    def fetch_snapshots(
        self,
        months: list[str],
        regions: list[str],
        flow_codes: list[str] | None = None,
        cmd_codes: list[str] | None = None,
    ) -> list[Snapshot]:
        return [Snapshot(name="comtrade_korea_202503", source_url="https://example.com/comtrade", body="{}")]

    def extract(
        self,
        snapshots: list[Snapshot],
        run_id: str,
        scraped_at: str,
        **_: object,
    ) -> list[BackupCheckPoint]:
        return [
            BackupCheckPoint(
                dataset_id="semiconductor_backup_check_monthly",
                source_region="korea",
                country_name="South Korea",
                metric_type="exports",
                flow_code="X",
                partner_scope="world",
                period="2025-03",
                release_date="2025-04-30",
                expected_release_window_days=45,
                lag_days=30,
                category_id="ic_only",
                category_label="IC-only",
                classification_system="HS",
                classification_code="8542",
                unit="usd",
                currency="USD",
                value=1000000000.0,
                yoy_pct=None,
                mom_pct=None,
                is_preliminary=True,
                is_revised=False,
                is_official_primary=False,
                comparison_gap_pct=None,
                source_name="UN Comtrade",
                source_url="https://example.com/comtrade",
                source_run_id=run_id,
                scraped_at=scraped_at,
                parser_version="test-backup-v1",
            )
        ]


def test_storage_manager_writes_parquet_only_for_tiered_datasets(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)

    storage.upsert_dataset(
        "semiconductor_official_monthly",
        [
            OfficialMonthlyPoint(
                dataset_id="semiconductor_official_monthly",
                source_region="korea",
                country_name="South Korea",
                metric_type="exports",
                flow_code="X",
                partner_scope="world",
                period="2025-03",
                release_date="2025-04-15",
                expected_release_window_days=21,
                lag_days=15,
                category_id="ic_only",
                category_label="IC-only",
                classification_system="HS",
                classification_code="8542",
                unit="usd",
                currency="USD",
                value=123.0,
                yoy_pct=None,
                mom_pct=None,
                is_preliminary=False,
                is_revised=False,
                is_official_primary=True,
                comparison_gap_pct=None,
                source_name="KCS",
                source_url="https://example.com",
                source_run_id="test-run",
                scraped_at="2026-06-20T00:00:00Z",
                parser_version="test-v1",
            )
        ],
    )

    parquet_path = tmp_path / "data" / "normalized" / "semiconductor_proxies" / "semiconductor_official_monthly.parquet"
    csv_path = tmp_path / "data" / "normalized" / "semiconductor_proxies" / "semiconductor_official_monthly.csv"

    assert parquet_path.exists()
    assert not csv_path.exists()


def test_pipeline_execution_writes_official_backup_and_catalog(tmp_path: Path) -> None:
    pipeline = SemiconductorProxyPipeline(
        tmp_path,
        official_sources=[FakeOfficialSource()],
        backup_source=FakeBackupSource(),
    )

    result = pipeline.run_backfill(
        start_month="2025-03",
        end_month="2025-03",
        regions=["korea"],
        categories=["ic_only"],
        sources="all",
    )

    assert result.datasets_written["semiconductor_official_monthly"] == 1
    assert result.datasets_written["semiconductor_backup_check_monthly"] == 1
    assert result.datasets_written["semiconductor_source_catalog"] == 1

    storage = StorageManager(tmp_path)
    official_df = storage.load_dataset("semiconductor_official_monthly")
    backup_df = storage.load_dataset("semiconductor_backup_check_monthly")
    catalog_df = storage.load_dataset("semiconductor_source_catalog")

    assert len(official_df) == 1
    assert len(backup_df) == 1
    assert len(catalog_df) == 1
    assert float(official_df.loc[0, "comparison_gap_pct"]) == pytest.approx(9.0909090909)
    assert float(backup_df.loc[0, "comparison_gap_pct"]) == pytest.approx(9.0909090909)
    assert catalog_df.loc[0, "source_tier"] == "official"

    validation = pipeline.validate()
    assert validation["official_rows"] == 1
    assert validation["backup_rows"] == 1
    assert validation["catalog_rows"] == 1
    assert validation["official_latest_period"] == "2025-03"
    assert validation["backup_latest_period"] == "2025-03"
    assert catalog_df.loc[0, "latest_period"] == "2025-03"


def test_custom_csv_import(tmp_path: Path) -> None:
    csv_content = """기간,수출액,상대국
2026.01,"12,500,000",미국
2026.02,"13,200,000",중국
2026.03,"14,000,000",합계
"""
    csv_file = tmp_path / "korea_exports_mock.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    pipeline = SemiconductorProxyPipeline(tmp_path)
    result = pipeline.import_custom_csv(
        csv_file,
        region="korea",
        category_id="ic_only",
        metric_type="exports",
        flow_code="X",
        scale_thousand=True,
    )

    assert result.datasets_written["semiconductor_official_monthly"] == 3
    
    storage = StorageManager(tmp_path)
    df = storage.load_dataset("semiconductor_official_monthly")
    assert len(df) == 3
    
    r1 = df[df["period"] == "2026-01"].iloc[0]
    assert r1["value"] == 12500000000.0
    assert r1["partner_scope"] == "usa"

    r2 = df[df["period"] == "2026-02"].iloc[0]
    assert r2["value"] == 13200000000.0
    assert r2["partner_scope"] == "china"

    r3 = df[df["period"] == "2026-03"].iloc[0]
    assert r3["value"] == 14000000000.0
    assert r3["partner_scope"] == "world"
