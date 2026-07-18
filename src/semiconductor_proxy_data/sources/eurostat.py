from __future__ import annotations

import json
import time

import requests

from semiconductor_proxy_data.models import OfficialMonthlyPoint, Snapshot, SourceCatalogPoint

USER_AGENT = "alternative-data-semiconductor-proxy/0.2"


class EurostatSource:
    BASE_URL = "https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data/DS-045409"
    PARTNERS = {
        "CN": "China",
        "KR": "South Korea",
        "TW": "Taiwan",
        "US": "USA",
        "WORLD": "World",
    }

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = 45,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.timeout = timeout

    # Eurostat has no documented hard cap on the number of `time` filters per
    # request, but chunking keeps individual requests small and matches the
    # defensive pattern used by the other regional sources in this package.
    MAX_MONTHS_PER_REQUEST = 60

    def fetch_snapshots(
        self,
        months: list[str],
        regions: list[str],
        categories: list[str],
    ) -> list[Snapshot]:
        if "netherlands" not in {r.lower() for r in regions}:
            return []

        if "lithography" not in {c.lower() for c in categories}:
            return []

        if not months:
            return []

        snapshots: list[Snapshot] = []
        for chunk in _chunk_months(months, max_months=self.MAX_MONTHS_PER_REQUEST):
            response = self._fetch_with_retry(chunk)
            period_str = chunk[0] if len(chunk) == 1 else f"{chunk[0]}_to_{chunk[-1]}"
            snapshots.append(
                Snapshot(
                    name=f"official_netherlands_lithography_{period_str}",
                    source_url=response.url,
                    body=response.text,
                )
            )
        return snapshots

    def _fetch_with_retry(self, months: list[str]) -> requests.Response:
        params: list[tuple[str, str]] = [
            ("format", "JSON"),
            ("lang", "EN"),
            ("freq", "M"),
            ("flow", "2"),
            ("reporter", "NL"),
            ("product", "84862000"),
        ]
        for partner in sorted(self.PARTNERS):
            params.append(("partner", partner))
        # Eurostat expects periods in YYYY-MM format
        for month in sorted(months):
            params.append(("time", month))

        retries = 3
        backoff = 2.0
        for attempt in range(retries):
            is_last_attempt = attempt == retries - 1
            try:
                response = self.session.get(
                    self.BASE_URL,
                    params=params,
                    timeout=self.timeout,
                )
            except requests.RequestException:
                if is_last_attempt:
                    raise
                time.sleep(backoff)
                backoff *= 2
                continue

            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and not is_last_attempt:
                time.sleep(backoff)
                backoff *= 2
                continue

            # Non-retryable errors (e.g. 400 Bad Request) raise immediately
            # instead of burning through the retry budget.
            response.raise_for_status()
            return response

        raise RuntimeError("unreachable: retry loop must return or raise")

    def extract(
        self,
        snapshots: list[Snapshot],
        run_id: str,
        scraped_at: str,
    ) -> list[OfficialMonthlyPoint]:
        points: list[OfficialMonthlyPoint] = []
        for snapshot in snapshots:
            if not snapshot.name.startswith("official_netherlands_lithography_"):
                continue

            try:
                data = json.loads(snapshot.body)
            except json.JSONDecodeError:
                continue

            # Validate dimensions and values
            dim = data.get("dimension")
            if not dim:
                continue

            # Ensure partner index mapping is resolved from response
            partner_dim = dim.get("partner", {})
            partner_index = partner_dim.get("category", {}).get("index", {})

            # Ensure indicators index mapping is resolved from response
            indicator_dim = dim.get("indicators", {})
            indicator_index = indicator_dim.get("category", {}).get("index", {})

            # Ensure time index mapping is resolved from response
            time_dim = dim.get("time", {})
            time_index = time_dim.get("category", {}).get("index", {})

            if not time_index or not indicator_index or not partner_index:
                continue

            # The flat-index formula below assumes every dimension other than
            # partner/indicators/time (freq, reporter, product, flow) has
            # exactly one category, since the query always fixes a single
            # reporter/product/flow. If Eurostat ever returns more than one
            # category for those dims, the formula would silently misattribute
            # values, so verify the assumption from the response's own `size`
            # list rather than trust it blindly.
            dim_ids = data.get("id", [])
            dim_sizes = data.get("size", [])
            fixed_dims_are_singular = all(
                size == 1
                for dim_id, size in zip(dim_ids, dim_sizes)
                if dim_id not in {"partner", "indicators", "time"}
            )
            if not dim_ids or not dim_sizes or not fixed_dims_are_singular:
                continue

            n_time = len(time_index)
            values = data.get("value", {})

            # Sort mappings by index value to map correctly
            time_list = sorted(time_index.keys(), key=lambda k: time_index[k])
            partner_list = sorted(partner_index.keys(), key=lambda k: partner_index[k])
            indicator_list = sorted(indicator_index.keys(), key=lambda k: indicator_index[k])

            # Dimensions structure order is: freq, reporter, partner, product, flow, indicators, time
            # Since size of freq=1, reporter=1, product=1, flow=1 (verified above),
            # offsets simplify to:
            # flat_idx = partner_idx * len(indicators) * len(time) + indicator_idx * len(time) + time_idx
            n_ind = len(indicator_list)

            for p_code in partner_list:
                p_idx = partner_index[p_code]
                partner_scope = "world" if p_code == "WORLD" else p_code.lower()

                for t_idx, period in enumerate(time_list):
                    # Extract indicators
                    val_in_euros = None
                    for ind_idx, ind_name in enumerate(indicator_list):
                        flat_idx = str(p_idx * n_ind * n_time + ind_idx * n_time + t_idx)
                        val = values.get(flat_idx)
                        if val is not None:
                            val = float(val)
                        if ind_name == "VALUE_IN_EUROS":
                            val_in_euros = val

                    # We only append records where trade value is present
                    if val_in_euros is not None:
                        points.append(
                            OfficialMonthlyPoint(
                                dataset_id="semiconductor_official_monthly",
                                source_region="netherlands",
                                country_name="Netherlands",
                                metric_type="exports",
                                flow_code="X",
                                partner_scope=partner_scope,
                                period=period,
                                release_date=None,
                                expected_release_window_days=50,
                                lag_days=None,
                                category_id="lithography",
                                category_label="Lithography",
                                classification_system="CN",
                                classification_code="84862000",
                                unit="eur",
                                currency="EUR",
                                value=val_in_euros,
                                yoy_pct=None,
                                mom_pct=None,
                                is_preliminary=False,
                                is_revised=False,
                                is_official_primary=True,
                                comparison_gap_pct=None,
                                source_name="Eurostat Comext DS-045409",
                                source_url=snapshot.source_url,
                                source_run_id=run_id,
                                scraped_at=scraped_at,
                                parser_version="semi-official-eurostat-v1",
                            )
                        )
        return points

    def catalog_points(self, run_id: str, scraped_at: str) -> list[SourceCatalogPoint]:
        return [
            SourceCatalogPoint(
                dataset_id="semiconductor_source_catalog",
                source_region="netherlands",
                country_name="Netherlands",
                source_name="Eurostat Comext DS-045409",
                source_tier="official",
                metric_type="exports",
                category_id="lithography",
                category_label="Lithography",
                coverage_start="1988-01",
                latest_period=None,
                cadence="monthly",
                expected_release_window_days=50,
                default_unit="eur",
                default_currency="EUR",
                is_official_primary=True,
                notes="Netherlands exports of machines and apparatus for the manufacture of semiconductor devices (CN 84862000) to key partners.",
                source_url=self.BASE_URL,
                source_run_id=run_id,
                scraped_at=scraped_at,
            )
        ]


def _chunk_months(months: list[str], *, max_months: int) -> list[list[str]]:
    ordered = sorted(set(months))
    return [ordered[i : i + max_months] for i in range(0, len(ordered), max_months)]
