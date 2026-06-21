from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from semiconductor_proxy_data.models import OfficialMonthlyPoint, Snapshot, SourceCatalogPoint

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class NbsSource:
    EASYQUERY_URL = "https://data.stats.gov.cn/easyquery.htm"

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = 30,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Referer": "https://data.stats.gov.cn/easyquery.htm",
        })
        self.timeout = timeout

    def fetch_snapshots(
        self,
        months: list[str] | None = None,
        regions: list[str] | None = None,
        categories: list[str] | None = None,
    ) -> list[Snapshot]:
        """
        Fetches the monthly Integrated Circuits production volume (A02092C).
        Since easyquery returns a historical series in a single call, we don't
        need to pass months in the request params.
        """
        region_set = {region.lower() for region in (regions or [])}
        if region_set and "china" not in region_set:
            return []

        category_set = {category.lower() for category in (categories or [])}
        if category_set and "ic_only" not in category_set:
            return []

        params = {
            "m": "QueryData",
            "dbcode": "hgyd",
            "rowcode": "zb",
            "colcode": "sj",
            "wds": "[]",
            "dfwds": '[{"wdcode":"zb","valuecode":"A02092C"}]',
            "k1": str(int(time.time() * 1000)),
        }

        try:
            # verify=False is used in some corporate/testing setups because stats.gov.cn
            # frequently has SSL certificate validation issues.
            response = self.session.get(
                self.EASYQUERY_URL,
                params=params,
                timeout=self.timeout,
                verify=False,
            )
            if response.status_code == 200:
                return [
                    Snapshot(
                        name="nbs_china_ic_production",
                        source_url=response.url,
                        body=response.text,
                    )
                ]
            else:
                logger.warning(
                    f"NBS query failed with status code {response.status_code}. "
                    "Skipping production indicators."
                )
                return []
        except Exception as e:
            logger.warning(
                f"NBS query failed due to exception: {e}. Skipping production indicators."
            )
            return []

    def extract(
        self,
        snapshots: list[Snapshot],
        run_id: str,
        scraped_at: str,
    ) -> list[OfficialMonthlyPoint]:
        points: list[OfficialMonthlyPoint] = []
        for snapshot in snapshots:
            try:
                payload = json.loads(snapshot.body)
            except json.JSONDecodeError:
                continue

            datanodes = payload.get("returndata", {}).get("datanodes", [])
            for node in datanodes:
                wds = node.get("wds", [])
                period_val = ""
                for wd in wds:
                    if wd.get("wdcode") == "sj":
                        period_val = str(wd.get("valuecode", ""))
                        break

                if not period_val:
                    continue

                if len(period_val) == 6:
                    period = f"{period_val[:4]}-{period_val[4:]}"
                else:
                    period = period_val

                data_info = node.get("data", {})
                if not data_info.get("hasdata", False):
                    continue

                val = data_info.get("data")
                if val is not None:
                    val = float(val)

                points.append(
                    OfficialMonthlyPoint(
                        dataset_id="semiconductor_official_monthly",
                        source_region="china",
                        country_name="China",
                        metric_type="production",
                        flow_code="",
                        partner_scope="domestic",
                        period=period,
                        release_date=None,
                        expected_release_window_days=20,
                        lag_days=None,
                        category_id="ic_only",
                        category_label="IC-only",
                        classification_system="NBS",
                        classification_code="A02092C",
                        unit="100m_pieces",
                        currency="",
                        value=val,
                        yoy_pct=None,
                        mom_pct=None,
                        is_preliminary=False,
                        is_revised=False,
                        is_official_primary=True,
                        comparison_gap_pct=None,
                        source_name="National Bureau of Statistics of China",
                        source_url=snapshot.source_url,
                        source_run_id=run_id,
                        scraped_at=scraped_at,
                        parser_version="semi-official-nbs-v2",
                    )
                )
        return points

    def catalog_points(self, run_id: str, scraped_at: str) -> list[SourceCatalogPoint]:
        return [
            SourceCatalogPoint(
                dataset_id="semiconductor_source_catalog",
                source_region="china",
                country_name="China",
                source_name="National Bureau of Statistics of China",
                source_tier="official",
                metric_type="production",
                category_id="ic_only",
                category_label="IC-only",
                coverage_start=None,
                latest_period=None,
                cadence="monthly",
                expected_release_window_days=20,
                default_unit="100m_pieces",
                default_currency="",
                is_official_primary=True,
                notes="Integrated circuits production volume from NBS.",
                source_url="https://data.stats.gov.cn/easyquery.htm",
                source_run_id=run_id,
                scraped_at=scraped_at,
            )
        ]
