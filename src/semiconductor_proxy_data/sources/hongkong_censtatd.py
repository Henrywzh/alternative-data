from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable

import pandas as pd
import requests

from semiconductor_proxy_data.models import OfficialMonthlyPoint, Snapshot, SourceCatalogPoint

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)


class HongKongCenstatdSource:
    API_URL = "https://tradeidds.censtatd.gov.hk/api/get"
    DOCS_URL = "https://data.gov.hk/en-data/dataset/hk-censtatd-trade-idds-trade/resource/25a56a32-7ce2-4aa3-ad4a-b66ced66ff33"
    CATEGORY_CONFIG = {
        "ic_only": {
            "classification_codes": ["8542"],
            "category_label": "IC-only",
        },
        "broad_semiconductor": {
            "classification_codes": ["8541", "8542"],
            "category_label": "Broad Semiconductor",
        },
    }
    TTYPE_CONFIG = {
        "exports": "4",
        "imports": "1",
    }

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = 60,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.timeout = timeout

    def fetch_snapshots(self, months: list[str], regions: list[str], categories: list[str]) -> list[Snapshot]:
        if "hongkong" not in {region.lower() for region in regions}:
            return []

        target_categories = [category for category in categories if category in self.CATEGORY_CONFIG]
        if not target_categories or not months:
            return []

        snapshots: list[Snapshot] = []
        for category_id in target_categories:
            config = self.CATEGORY_CONFIG[category_id]
            for start_month, end_month in _chunk_months(months, max_months=6):
                responses: list[dict[str, object]] = []
                for metric_type, ttype in self.TTYPE_CONFIG.items():
                    for classification_code in config["classification_codes"]:
                        payload = self._fetch_series(
                            classification_code=classification_code,
                            trade_type=ttype,
                            start_month=start_month,
                            end_month=end_month,
                        )
                        responses.append(
                            {
                                "metric_type": metric_type,
                                "classification_code": classification_code,
                                "payload": payload,
                            }
                        )
                snapshots.append(
                    Snapshot(
                        name=f"official_hongkong_{category_id}_{start_month}_{end_month}",
                        source_url=self.API_URL,
                        body=json.dumps(
                            {
                                "source_region": "hongkong",
                                "category_id": category_id,
                                "classification_codes": config["classification_codes"],
                                "responses": responses,
                            }
                        ),
                    )
                )
        return snapshots

    def extract(
        self,
        snapshots: list[Snapshot],
        run_id: str,
        scraped_at: str,
    ) -> list[OfficialMonthlyPoint]:
        points: list[OfficialMonthlyPoint] = []
        for snapshot in snapshots:
            if not snapshot.name.startswith("official_hongkong_"):
                continue
            try:
                payload = json.loads(snapshot.body)
            except json.JSONDecodeError:
                continue

            category_id = str(payload.get("category_id", ""))
            config = self.CATEGORY_CONFIG.get(category_id)
            if not config:
                continue

            parts = snapshot.name.split("_")
            if len(parts) < 5:
                continue
            start_month = parts[-2]
            end_month = parts[-1]

            totals: dict[tuple[str, str], float] = defaultdict(float)
            product_names: set[str] = set()
            latest_period = None

            for response_entry in payload.get("responses", []):
                if not isinstance(response_entry, dict):
                    continue
                metric_type = str(response_entry.get("metric_type", ""))
                response_payload = response_entry.get("payload", {})
                if not isinstance(response_payload, dict):
                    continue
                for record in response_payload.get("dataSet", []):
                    if not isinstance(record, dict):
                        continue
                    period = _normalize_period(str(record.get("period", "")))
                    if not period or period < start_month or period > end_month:
                        continue
                    product_name = str(record.get("codeDescEN", "")).strip()
                    if product_name:
                        product_names.add(product_name)
                    totals[(period, metric_type)] += _to_float(record.get("figure"))
                    latest_period = max(latest_period, period) if latest_period else period

            if not totals:
                continue

            periods = sorted({period for period, _ in totals.keys()})
            for period in periods:
                export_value = totals.get((period, "exports"))
                import_value = totals.get((period, "imports"))
                if export_value is not None:
                    points.append(
                        self._build_point(
                            metric_type="exports",
                            flow_code="X",
                            period=period,
                            value=export_value,
                            category_id=category_id,
                            category_label=config["category_label"],
                            classification_code=",".join(config["classification_codes"]),
                            source_name=_source_name(product_names),
                            source_url=snapshot.source_url,
                            source_run_id=run_id,
                            scraped_at=scraped_at,
                        )
                    )
                if import_value is not None:
                    points.append(
                        self._build_point(
                            metric_type="imports",
                            flow_code="M",
                            period=period,
                            value=import_value,
                            category_id=category_id,
                            category_label=config["category_label"],
                            classification_code=",".join(config["classification_codes"]),
                            source_name=_source_name(product_names),
                            source_url=snapshot.source_url,
                            source_run_id=run_id,
                            scraped_at=scraped_at,
                        )
                    )
                if export_value is not None and import_value is not None:
                    points.append(
                        self._build_point(
                            metric_type="trade_balance",
                            flow_code="B",
                            period=period,
                            value=export_value - import_value,
                            category_id=category_id,
                            category_label=config["category_label"],
                            classification_code=",".join(config["classification_codes"]),
                            source_name=_source_name(product_names),
                            source_url=snapshot.source_url,
                            source_run_id=run_id,
                            scraped_at=scraped_at,
                        )
                    )
        return points

    def catalog_points(self, run_id: str, scraped_at: str) -> list[SourceCatalogPoint]:
        points: list[SourceCatalogPoint] = []
        for category_id, config in self.CATEGORY_CONFIG.items():
            for metric_type in ("exports", "imports", "trade_balance"):
                points.append(
                    SourceCatalogPoint(
                        dataset_id="semiconductor_source_catalog",
                        source_region="hongkong",
                        country_name="Hong Kong",
                        source_name="Hong Kong C&SD Trade IDDS",
                        source_tier="official",
                        metric_type=metric_type,
                        category_id=category_id,
                        category_label=config["category_label"],
                        coverage_start="2015-01",
                        latest_period=None,
                        cadence="monthly",
                        expected_release_window_days=28,
                        default_unit="hkd_thousand",
                        default_currency="HKD",
                        is_official_primary=True,
                        notes=(
                            "Official monthly external merchandise trade from Hong Kong Census and "
                            f"Statistics Department for HKHS {','.join(config['classification_codes'])}."
                        ),
                        source_url=self.DOCS_URL,
                        source_run_id=run_id,
                        scraped_at=scraped_at,
                    )
                )
        return points

    def _fetch_series(
        self,
        *,
        classification_code: str,
        trade_type: str,
        start_month: str,
        end_month: str,
    ) -> dict[str, object]:
        current_end = end_month
        while current_end >= start_month:
            params = {
                "lang": "EN",
                "sv": "VCm",
                "freq": "M",
                "period": f"{start_month.replace('-', '')},{current_end.replace('-', '')}",
                "ttype": trade_type,
                "codeclass": "HKHS4",
                "code": classification_code,
            }
            response = self.session.get(self.API_URL, params=params, timeout=self.timeout, verify=False)
            response.raise_for_status()
            payload = response.json()
            status = payload.get("header", {}).get("status", {})
            if status.get("name") == "Success":
                return payload
            if not _is_undefined_period_error(status.get("message")):
                raise ValueError(f"Hong Kong API error for code {classification_code}: {status.get('message')}")
            current_end = _previous_month(current_end)

        return {"header": {"status": {"name": "Success"}}, "dataSet": []}

    @staticmethod
    def _build_point(
        *,
        metric_type: str,
        flow_code: str,
        period: str,
        value: float,
        category_id: str,
        category_label: str,
        classification_code: str,
        source_name: str,
        source_url: str,
        source_run_id: str,
        scraped_at: str,
    ) -> OfficialMonthlyPoint:
        return OfficialMonthlyPoint(
            dataset_id="semiconductor_official_monthly",
            source_region="hongkong",
            country_name="Hong Kong",
            metric_type=metric_type,
            flow_code=flow_code,
            partner_scope="world",
            period=period,
            release_date=None,
            expected_release_window_days=28,
            lag_days=None,
            category_id=category_id,
            category_label=category_label,
            classification_system="HKHS",
            classification_code=classification_code,
            unit="hkd_thousand",
            currency="HKD",
            value=value,
            yoy_pct=None,
            mom_pct=None,
            is_preliminary=False,
            is_revised=False,
            is_official_primary=True,
            comparison_gap_pct=None,
            source_name=source_name,
            source_url=source_url,
            source_run_id=source_run_id,
            scraped_at=scraped_at,
            parser_version="semi-official-hongkong-v1",
        )


def _chunk_months(months: Iterable[str], *, max_months: int) -> list[tuple[str, str]]:
    ordered = sorted({month for month in months})
    if not ordered:
        return []
    ranges: list[tuple[str, str]] = []
    start = ordered[0]
    end = ordered[0]
    span = 1
    for month in ordered[1:]:
        if span >= max_months:
            ranges.append((start, end))
            start = month
            end = month
            span = 1
            continue
        end = month
        span += 1
    ranges.append((start, end))
    return ranges


def _normalize_period(value: str) -> str | None:
    normalized = value.strip()
    if len(normalized) == 6:
        return f"{normalized[:4]}-{normalized[4:]}"
    return None


def _to_float(value: object) -> float:
    normalized = str(value or "").replace(",", "").strip()
    if not normalized:
        return 0.0
    return float(normalized)


def _source_name(product_names: set[str]) -> str:
    if not product_names:
        return "Hong Kong C&SD Trade IDDS"
    if len(product_names) == 1:
        return f"Hong Kong C&SD Trade IDDS ({next(iter(product_names))})"
    return "Hong Kong C&SD Trade IDDS (Selected Semiconductor Headings)"


def _is_undefined_period_error(message: object) -> bool:
    if isinstance(message, list):
        text = " ".join(str(item) for item in message)
    else:
        text = str(message or "")
    return "Period code" in text and "is not defined" in text


def _previous_month(month: str) -> str:
    return (pd.Period(month, freq="M") - 1).strftime("%Y-%m")
