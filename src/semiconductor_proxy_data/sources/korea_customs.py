from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable

import requests

from semiconductor_proxy_data.models import OfficialMonthlyPoint, Snapshot, SourceCatalogPoint

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)


class KoreaCustomsSource:
    HOME_URL = "https://tradedata.go.kr/cts/index.do"
    TRADE_URL = "https://tradedata.go.kr/cts/hmpg/retrieveTrade.do"
    TRADE_KIND = "ETS_MNK_1020000A"
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

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = 60,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Referer": self.HOME_URL,
            "X-Requested-With": "XMLHttpRequest",
            "isAjax": "true",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        })
        self.timeout = timeout
        self._bootstrapped = False

    def fetch_snapshots(self, months: list[str], regions: list[str], categories: list[str]) -> list[Snapshot]:
        if "korea" not in {region.lower() for region in regions}:
            return []

        target_categories = [category for category in categories if category in self.CATEGORY_CONFIG]
        if not target_categories or not months:
            return []

        self._bootstrap()

        snapshots: list[Snapshot] = []
        for category in target_categories:
            config = self.CATEGORY_CONFIG[category]
            for start_month, end_month in _chunk_months(months, max_months=36):
                responses: list[dict[str, object]] = []
                for classification_code in config["classification_codes"]:
                    payload = self._post_trade_query(
                        classification_code=classification_code,
                        start_month=start_month,
                        end_month=end_month,
                    )
                    responses.append({
                        "classification_code": classification_code,
                        "payload": payload,
                    })
                snapshots.append(
                    Snapshot(
                        name=f"official_korea_{category}_{start_month}_{end_month}",
                        source_url=self.TRADE_URL,
                        body=json.dumps(
                            {
                                "source_region": "korea",
                                "category_id": category,
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
            if not snapshot.name.startswith("official_korea_"):
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

            metric_totals: dict[tuple[str, str], float] = defaultdict(float)
            product_names: set[str] = set()
            response_entries = payload.get("responses", [])
            if not isinstance(response_entries, list):
                continue

            for response_entry in response_entries:
                if not isinstance(response_entry, dict):
                    continue
                classification_code = str(response_entry.get("classification_code", ""))
                response_payload = response_entry.get("payload", {})
                if not isinstance(response_payload, dict):
                    continue
                for item in response_payload.get("items", []):
                    if not isinstance(item, dict):
                        continue
                    period = _normalize_period(str(item.get("priodTitle", "")))
                    if not period or period < start_month or period > end_month:
                        continue
                    product_name = str(item.get("korePrlstNm", "")).strip()
                    if product_name:
                        product_names.add(product_name)
                    metric_totals[(period, "exports")] += _to_float(item.get("expUsdAmt"))
                    metric_totals[(period, "imports")] += _to_float(item.get("impUsdAmt"))
                    metric_totals[(period, "trade_balance")] += _to_float(item.get("cmtrBlncAmt"))

            if not metric_totals:
                continue

            product_label = " + ".join(sorted(product_names)) if product_names else config["category_label"]
            classification_code = ",".join(config["classification_codes"])

            for (period, metric_type), value in sorted(metric_totals.items()):
                flow_code = {"exports": "X", "imports": "M", "trade_balance": "B"}.get(metric_type, "")
                points.append(
                    OfficialMonthlyPoint(
                        dataset_id="semiconductor_official_monthly",
                        source_region="korea",
                        country_name="South Korea",
                        metric_type=metric_type,
                        flow_code=flow_code,
                        partner_scope="world",
                        period=period,
                        release_date=None,
                        expected_release_window_days=20,
                        lag_days=None,
                        category_id=category_id,
                        category_label=config["category_label"],
                        classification_system="HS",
                        classification_code=classification_code,
                        unit="usd",
                        currency="USD",
                        value=value,
                        yoy_pct=None,
                        mom_pct=None,
                        is_preliminary=False,
                        is_revised=False,
                        is_official_primary=True,
                        comparison_gap_pct=None,
                        source_name=f"Korea Customs Service Trade Statistics ({product_label})",
                        source_url=snapshot.source_url,
                        source_run_id=run_id,
                        scraped_at=scraped_at,
                        parser_version="semi-official-korea-v1",
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
                        source_region="korea",
                        country_name="South Korea",
                        source_name="Korea Customs Service Trade Statistics",
                        source_tier="official",
                        metric_type=metric_type,
                        category_id=category_id,
                        category_label=config["category_label"],
                        coverage_start="2000-01",
                        latest_period=None,
                        cadence="monthly",
                        expected_release_window_days=20,
                        default_unit="usd",
                        default_currency="USD",
                        is_official_primary=True,
                        notes=(
                            "Official monthly trade statistics from Korea Customs Service "
                            f"for HS {','.join(config['classification_codes'])}."
                        ),
                        source_url=self.HOME_URL,
                        source_run_id=run_id,
                        scraped_at=scraped_at,
                    )
                )
        return points

    def _bootstrap(self) -> None:
        if self._bootstrapped:
            return
        response = self.session.get(self.HOME_URL, timeout=self.timeout, verify=False)
        response.raise_for_status()
        self._bootstrapped = True

    def _post_trade_query(
        self,
        *,
        classification_code: str,
        start_month: str,
        end_month: str,
    ) -> dict[str, object]:
        request_body = {
            "tradeKind": self.TRADE_KIND,
            "priodKind": "MON",
            "priodFr": start_month.replace("-", "") + " ",
            "priodTo": end_month.replace("-", "") + " ",
            "statsBase": "acptDd",
            "ttwgTpcd": "1000",
            "showPagingLine": "15",
            "sortColumn": "",
            "sortOrder": "",
            "hsSgnGrpCol": "HS4_SGN",
            "hsSgnWhrCol": "HS4_SGN",
            "hsSgn": classification_code,
        }
        merged_payload: dict[str, object] | None = None
        merged_items: list[dict[str, object]] = []
        page = 1

        while True:
            paged_body = dict(request_body)
            paged_body["selectPaging"] = str(page)
            response = self.session.post(
                self.TRADE_URL,
                data=paged_body,
                timeout=self.timeout,
                verify=False,
            )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items", [])
            if not isinstance(items, list) or not items:
                break

            if merged_payload is None:
                merged_payload = payload
                merged_items.extend(items)
            else:
                merged_items.extend(items)

            if len(items) < int(request_body["showPagingLine"]):
                break
            page += 1

        if merged_payload is None:
            return {"count": 0, "items": []}

        merged_payload["items"] = merged_items
        return merged_payload


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
    if len(normalized) == 7 and normalized[4] == ".":
        return normalized.replace(".", "-")
    return None


def _to_float(value: object) -> float:
    normalized = str(value or "").replace(",", "").strip()
    if not normalized:
        return 0.0
    return float(normalized)
