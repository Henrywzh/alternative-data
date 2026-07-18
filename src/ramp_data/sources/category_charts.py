"""Ramp Category Charts source.

Scrapes the interactive Datawrapper charts embedded in each category page.
Each category has:
- A primary chart (Adoption Over Time), e.g., b3D7f
- Toggles to switch to "Share of Spend" and "Adoption YoY" which link to other charts.

We dynamically fetch the category pages, parse the Datawrapper chart IDs, download
the CSV datasets, and extract long-format records.
"""
from __future__ import annotations

import csv
import datetime
import io
import json
import re
import time
from typing import Any

import requests

from ramp_data.models import GenericRecord, RunContext, Snapshot
from ramp_data.sources import rsc
from ramp_data.sources.base import SourceExtractor

BASE_URL = "https://ramp.com"
CATEGORY_PREFIX = "/vendors/categories/"

_IFRAME_RE = re.compile(r'<iframe[^>]*src="([^"]*datawrapper[^"]*)"', re.IGNORECASE)
_DW_ID_RE = re.compile(r'dwcdn\.net/([a-zA-Z0-9]{5})')
_LINK_RE = re.compile(r'<a[^>]*href="([^"]*datawrapper\.dwcdn\.net/([a-zA-Z0-9]{5})[^"]*)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)


def _parse_month_year(col_name: str) -> str | None:
    for fmt in ("%b %Y", "%B %Y", "%Y-%m-%d"):
        try:
            dt = datetime.datetime.strptime(col_name.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


class RampCategoryChartsSource(SourceExtractor):
    name = "ramp_category_charts"

    def __init__(self, timeout: int = 20, delay_seconds: float = 0.4, max_retries: int = 3) -> None:
        self.timeout = timeout
        self.delay_seconds = delay_seconds
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def _get(self, url: str) -> str | None:
        for attempt in range(1, self.max_retries + 1):
            time.sleep(self.delay_seconds)
            try:
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(f"status {response.status_code}")
                response.raise_for_status()
                return response.text
            except Exception as exc:
                if attempt == self.max_retries:
                    print(f"Warning: giving up on {url} after {attempt} attempts: {exc}")
                    return None
                backoff = self.delay_seconds * (2 ** attempt)
                time.sleep(backoff)
        return None

    def fetch_snapshots(self) -> list[Snapshot]:
        print("Discovering categories from /vendors...")
        index_html = self._get(f"{BASE_URL}/vendors")
        if not index_html:
            return []

        # Find category links
        index_payload = rsc.decode_payload(index_html)
        categories: dict[str, str] = {}
        for obj in rsc.objects_containing(index_payload, CATEGORY_PREFIX, {"name", "pathname"}):
            pathname = obj.get("pathname")
            name = obj.get("name")
            if isinstance(pathname, str) and isinstance(name, str):
                slug = pathname[len(CATEGORY_PREFIX):].strip("/")
                if slug and "/" not in slug:
                    categories[slug] = name

        print(f"Found {len(categories)} categories. Scraping Datawrapper chart metadata...")
        snapshots: list[Snapshot] = []

        # Save category list as metadata snapshot
        snapshots.append(Snapshot(name="category_list", source_url=f"{BASE_URL}/vendors", body=json.dumps(categories)))

        for slug, name in categories.items():
            cat_url = f"{BASE_URL}/vendors/categories/{slug}"
            print(f"Fetching category page: {slug}")
            cat_html = self._get(cat_url)
            if not cat_html:
                continue

            # Look for primary Datawrapper iframe
            iframe_match = _IFRAME_RE.search(cat_html)
            if not iframe_match:
                print(f"  No Datawrapper iframe found for category: {slug}")
                continue

            iframe_url = iframe_match.group(1)
            dw_id_match = _DW_ID_RE.search(iframe_url)
            if not dw_id_match:
                print(f"  Could not parse Datawrapper chart ID from URL: {iframe_url}")
                continue

            primary_dw_id = dw_id_match.group(1)

            # Fetch primary chart HTML to find other toggles
            primary_chart_url = f"https://datawrapper.dwcdn.net/{primary_dw_id}/1/"
            primary_chart_html = self._get(primary_chart_url)
            if not primary_chart_html:
                continue

            # Resolve secondary chart IDs from links inside the chart
            chart_mapping = {
                "adoption_monthly": primary_dw_id,
                "spend_share_quarterly": None,
                "adoption_yoy_comparison": None
            }

            links = _LINK_RE.findall(primary_chart_html)
            for href, dw_id, link_text in links:
                link_text_clean = re.sub(r'<[^>]+>', '', link_text).strip().lower()
                if "spend" in link_text_clean:
                    chart_mapping["spend_share_quarterly"] = dw_id
                elif "yoy" in link_text_clean:
                    chart_mapping["adoption_yoy_comparison"] = dw_id

            # Save the chart metadata mapping as a snapshot
            snapshots.append(
                Snapshot(
                    name=f"meta__{slug}",
                    source_url=cat_url,
                    body=json.dumps(chart_mapping)
                )
            )

            # Download CSV for each available chart ID
            for key, dw_id in chart_mapping.items():
                if not dw_id:
                    continue
                csv_url = f"https://datawrapper.dwcdn.net/{dw_id}/1/dataset.csv"
                print(f"  Downloading CSV for {key}: {dw_id}")
                csv_text = self._get(csv_url)
                if csv_text:
                    snapshots.append(
                        Snapshot(
                            name=f"csv__{slug}__{key}",
                            source_url=csv_url,
                            body=csv_text
                        )
                    )

        return snapshots

    def extract(
        self,
        snapshots: list[Snapshot],
        context: RunContext,
    ) -> dict[str, list[GenericRecord]]:
        extracted: dict[str, list[GenericRecord]] = {
            "ramp_category_adoption_monthly": [],
            "ramp_category_spend_share_quarterly": [],
            "ramp_category_adoption_yoy_comparison": [],
        }

        # Resolve category names from categories snapshot
        cat_list_snap = next((s for s in snapshots if s.name == "category_list"), None)
        categories: dict[str, str] = json.loads(cat_list_snap.body) if cat_list_snap else {}

        for snapshot in snapshots:
            if not snapshot.name.startswith("csv__"):
                continue

            parts = snapshot.name.split("__")
            if len(parts) != 3:
                continue

            _, slug, key = parts
            cat_name = categories.get(slug, slug)

            reader = csv.DictReader(io.StringIO(snapshot.body.strip()))

            if key == "adoption_monthly":
                for row in reader:
                    spend_month = row.get("SPEND_MONTH")
                    if not spend_month:
                        continue
                    # Pivot columns representing vendors (excluding SPEND_MONTH)
                    for col, val in row.items():
                        if col == "SPEND_MONTH" or not val:
                            continue
                        try:
                            rate = float(val) / 100.0
                        except ValueError:
                            continue
                        extracted["ramp_category_adoption_monthly"].append(
                            GenericRecord(
                                dataset_id="ramp_category_adoption_monthly",
                                source_url=snapshot.source_url,
                                source_run_id=context.run_id,
                                scraped_at=context.scraped_at_iso,
                                payload={
                                    "category_slug": slug,
                                    "spend_month": spend_month,
                                    "vendor_name": col,
                                    "adoption_rate": rate,
                                }
                            )
                        )

            elif key == "spend_share_quarterly":
                for row in reader:
                    quarter = row.get("QUARTER")
                    if not quarter:
                        continue
                    # Pivot columns representing vendors (excluding QUARTER)
                    for col, val in row.items():
                        if col == "QUARTER" or not val:
                            continue
                        try:
                            share = float(val) / 100.0
                        except ValueError:
                            continue
                        extracted["ramp_category_spend_share_quarterly"].append(
                            GenericRecord(
                                dataset_id="ramp_category_spend_share_quarterly",
                                source_url=snapshot.source_url,
                                source_run_id=context.run_id,
                                scraped_at=context.scraped_at_iso,
                                payload={
                                    "category_slug": slug,
                                    "quarter": quarter,
                                    "vendor_name": col,
                                    "spend_share": share,
                                }
                            )
                        )

            elif key == "adoption_yoy_comparison":
                # Find columns that look like date headers (e.g. Jun 2025, Jun 2026)
                date_cols: dict[str, str] = {}
                for col in reader.fieldnames or []:
                    parsed_date = _parse_month_year(col)
                    if parsed_date:
                        date_cols[col] = parsed_date

                for row in reader:
                    vendor_name = row.get("DISPLAY_NAME")
                    if not vendor_name:
                        continue
                    for col, parsed_date in date_cols.items():
                        val = row.get(col)
                        if not val:
                            continue
                        try:
                            rate = float(val) / 100.0
                        except ValueError:
                            continue
                        extracted["ramp_category_adoption_yoy_comparison"].append(
                            GenericRecord(
                                dataset_id="ramp_category_adoption_yoy_comparison",
                                source_url=snapshot.source_url,
                                source_run_id=context.run_id,
                                scraped_at=context.scraped_at_iso,
                                payload={
                                    "category_slug": slug,
                                    "vendor_name": vendor_name,
                                    "date_month": parsed_date,
                                    "adoption_rate": rate,
                                }
                            )
                        )

        return extracted
