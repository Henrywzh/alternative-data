from __future__ import annotations

import json
import os
import time
from typing import Any

import requests

from semiconductor_proxy_data.models import BackupCheckPoint, Snapshot

M49_MAP = {
    410: "South Korea",
    156: "China",
    344: "Hong Kong",
    392: "Japan",
    842: "USA",
    0: "World",
}

REGION_REPORTER_CODES = {
    "korea": 410,
    "china": 156,
    "hongkong": 344,
    "japan": 392,
}

USER_AGENT = "alternative-data-semiconductor-proxy/0.1"


class ComtradeSource:
    PREVIEW_URL = "https://comtradeapi.un.org/public/v1/preview/C/M/HS"
    PREMIUM_URL = "https://comtradeapi.un.org/data/v1/get/C/M/HS"

    def __init__(
        self,
        api_key: str | None = None,
        session: requests.Session | None = None,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key or os.environ.get("COMTRADE_API_KEY", "")
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.timeout = timeout

    def fetch_snapshots(
        self,
        months: list[str],
        regions: list[str],
        flow_codes: list[str] | None = None,
        cmd_codes: list[str] | None = None,
    ) -> list[Snapshot]:
        """
        months format: ["YYYY-MM", ...]
        regions: ["korea", "china", "hongkong", "japan"]
        """
        flows = flow_codes or ["X", "M"]
        cmds = cmd_codes or ["8542"]
        snapshots: list[Snapshot] = []

        # Convert months from "YYYY-MM" to "YYYYMM"
        periods = [m.replace("-", "") for m in months]
        if not periods:
            return []

        flow_query = ",".join(flows)
        cmd_query = ",".join(cmds)

        # Chunk periods into groups of 5 to avoid 400 Bad Request errors due to period limit constraints
        period_chunks = [periods[i:i + 5] for i in range(0, len(periods), 5)]

        for region in regions:
            reporter_code = REGION_REPORTER_CODES.get(region.lower())
            if not reporter_code:
                raise ValueError(f"Unsupported region for Comtrade: {region}")

            for chunk in period_chunks:
                period_query = ",".join(chunk)
                params = {
                    "reporterCode": reporter_code,
                    "period": period_query,
                    "flowCode": flow_query,
                    "cmdCode": cmd_query,
                    "partnerCode": "0,156,842,344,392,410",  # World, China, USA, HK, Japan, Korea
                }

                url = self.PREMIUM_URL if self.api_key else self.PREVIEW_URL
                headers = {}
                if self.api_key:
                    headers["Ocp-Apim-Subscription-Key"] = self.api_key

                retries = 3
                backoff = 2.0
                response = None
                for attempt in range(retries):
                    response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
                    if response.status_code == 429:
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                    break

                if response is not None:
                    response.raise_for_status()

                    snapshots.append(
                        Snapshot(
                            name=f"comtrade_{region}_{period_query}",
                            source_url=response.url,
                            body=response.text,
                        )
                    )
                # Sleep slightly between requests to respect rate limits
                time.sleep(1.0)

        return snapshots

    def extract(
        self,
        snapshots: list[Snapshot],
        run_id: str,
        scraped_at: str,
        *,
        category_id: str = "ic_only",
        category_label: str = "IC-only",
        metric_type: str = "exports",
    ) -> list[BackupCheckPoint]:
        points: list[BackupCheckPoint] = []
        for snapshot in snapshots:
            try:
                payload = json.loads(snapshot.body)
            except json.JSONDecodeError:
                continue

            for record in payload.get("data", []):
                # Parse period (e.g. 202503 -> 2025-03)
                raw_period = str(record.get("period", ""))
                if len(raw_period) == 6:
                    period = f"{raw_period[:4]}-{raw_period[4:]}"
                else:
                    period = raw_period

                rep_code = record.get("reporterCode")
                part_code = record.get("partnerCode")

                reporter_name = M49_MAP.get(rep_code, record.get("reporterDesc") or f"M49:{rep_code}")
                partner_name = M49_MAP.get(part_code, record.get("partnerDesc") or f"M49:{part_code}")

                # Trade value is typically in USD
                trade_value = record.get("primaryValue")
                if trade_value is not None:
                    trade_value = float(trade_value)

                points.append(
                    BackupCheckPoint(
                        dataset_id="semiconductor_backup_check_monthly",
                        source_region=_region_slug_for_reporter(rep_code),
                        country_name=reporter_name,
                        metric_type=metric_type,
                        flow_code=str(record.get("flowCode", "")),
                        partner_scope=_partner_scope(part_code, partner_name),
                        period=period,
                        release_date=None,
                        expected_release_window_days=45,
                        lag_days=None,
                        category_id=category_id,
                        category_label=category_label,
                        classification_system="HS",
                        classification_code=str(record.get("cmdCode", "")),
                        unit="usd",
                        currency="USD",
                        value=trade_value,
                        yoy_pct=None,
                        mom_pct=None,
                        is_preliminary=True,
                        is_revised=False,
                        is_official_primary=False,
                        comparison_gap_pct=None,
                        source_name="UN Comtrade",
                        source_url=snapshot.source_url,
                        source_run_id=run_id,
                        scraped_at=scraped_at,
                        parser_version="semi-backup-comtrade-v2",
                    )
                )
        return points


def _region_slug_for_reporter(reporter_code: int | None) -> str:
    mapping = {
        410: "korea",
        156: "china",
        344: "hongkong",
        392: "japan",
    }
    return mapping.get(int(reporter_code) if reporter_code is not None else -1, "unknown")


def _partner_scope(partner_code: int | None, partner_name: str) -> str:
    normalized = partner_name.strip().lower().replace(" ", "_")
    if partner_code == 0:
        return "world"
    if normalized in {"united_states", "usa"}:
        return "usa"
    if normalized in {"hong_kong", "hong_kong,_china"}:
        return "hongkong"
    if normalized in {"korea,_rep.", "south_korea"}:
        return "korea"
    return normalized
