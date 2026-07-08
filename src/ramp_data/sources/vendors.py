"""Ramp vendor-intelligence source.

Ramp publishes per-vendor and per-category adoption data at ``ramp.com/vendors``.
There is no public API, so the data is crawled from the RSC payload embedded in
each page:

1. ``/vendors``                         -> discover category slugs + names
2. ``/vendors/categories/<slug>``       -> vendors in each category (+ current
                                           adoption keyStats)
3. ``/vendors/<slug>``                  -> monthly ``historicalData`` per vendor

Two datasets fall out:

* ``ramp_category_vendors``        — category membership snapshot (current)
* ``ramp_vendor_adoption_monthly`` — monthly adoption time series (history)

Unlike the original one-shot script, this re-crawls every run (the vendor pages
carry ~24 months of history, so upsert-by-``spend_month`` keeps accumulating new
months) and fails loudly instead of silently writing empty data.
"""
from __future__ import annotations

import json
import time
from typing import Any

import requests

from ramp_data.models import DatasetRecord, RunContext, Snapshot
from ramp_data.sources.base import SourceExtractor
from ramp_data.sources import rsc

BASE_URL = "https://ramp.com"

CATEGORY_PREFIX = "/vendors/categories/"
VENDOR_PREFIX = "/vendors/"

# Snapshot name prefixes; extract() dispatches on these.
INDEX_SNAPSHOT = "index"
CATEGORY_PREFIX_NAME = "category__"
VENDOR_PREFIX_NAME = "vendor__"


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _vendor_slug_from_pathname(pathname: str) -> str | None:
    """``/vendors/cursor`` -> ``cursor``; rejects category / nested paths."""
    if not pathname.startswith(VENDOR_PREFIX):
        return None
    remainder = pathname[len(VENDOR_PREFIX):]
    if not remainder or "/" in remainder:
        return None
    return remainder


class RampVendorsSource(SourceExtractor):
    name = "ramp_vendors"

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

    # ------------------------------------------------------------------ fetch

    def _fetch_payload(self, url: str) -> str | None:
        """GET ``url`` with polite delay + exponential backoff; decode RSC.

        Returns the decoded payload string, or None if the page never loaded.
        """
        for attempt in range(1, self.max_retries + 1):
            time.sleep(self.delay_seconds)
            try:
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(f"status {response.status_code}")
                response.raise_for_status()
                return rsc.decode_payload(response.text)
            except Exception as exc:  # noqa: BLE001 - retry any transport error
                if attempt == self.max_retries:
                    print(f"Warning: giving up on {url} after {attempt} attempts: {exc}")
                    return None
                backoff = self.delay_seconds * (2 ** attempt)
                print(f"Warning: fetch {url} failed ({exc}); retrying in {backoff:.1f}s")
                time.sleep(backoff)
        return None

    def _discover_categories(self, index_payload: str) -> dict[str, str]:
        """slug -> display name for every category linked from the index."""
        categories: dict[str, str] = {}
        # Anchor on the pathname *value* substring rather than `"pathname":"…`,
        # so extraction is insensitive to key/colon spacing in the payload.
        for obj in rsc.objects_containing(index_payload, CATEGORY_PREFIX, {"name", "pathname"}):
            pathname = obj.get("pathname")
            name = obj.get("name")
            if not isinstance(pathname, str) or not isinstance(name, str):
                continue
            if pathname.startswith(CATEGORY_PREFIX):
                slug = pathname[len(CATEGORY_PREFIX):].strip("/")
                if slug and "/" not in slug:
                    categories.setdefault(slug, name)
        return categories

    def _vendor_cards(self, payload: str) -> list[dict[str, Any]]:
        """Vendor card objects on a category page (each carries adoption keyStats)."""
        return rsc.objects_containing(payload, '"cleanDomain":', {"cleanDomain", "name", "pathname"})

    def fetch_snapshots(self) -> list[Snapshot]:
        snapshots: list[Snapshot] = []

        index_url = f"{BASE_URL}/vendors"
        index_payload = self._fetch_payload(index_url)
        if not index_payload:
            print("Warning: failed to load Ramp vendors index; no snapshots produced")
            return snapshots
        snapshots.append(Snapshot(name=INDEX_SNAPSHOT, source_url=index_url, body=index_payload))

        categories = self._discover_categories(index_payload)
        print(f"Discovered {len(categories)} categories")

        # Category pages -> vendor membership, and the union of vendor slugs.
        vendor_slugs: set[str] = set()
        for slug in sorted(categories):
            url = f"{BASE_URL}{CATEGORY_PREFIX}{slug}"
            payload = self._fetch_payload(url)
            if not payload:
                continue
            snapshots.append(Snapshot(name=f"{CATEGORY_PREFIX_NAME}{slug}", source_url=url, body=payload))
            for obj in self._vendor_cards(payload):
                v_slug = _vendor_slug_from_pathname(str(obj.get("pathname", "")))
                if v_slug:
                    vendor_slugs.add(v_slug)

        print(f"Discovered {len(vendor_slugs)} vendors across categories")

        # Vendor pages -> historicalData. Stored as compact JSON (not the full
        # decoded payload) so per-run raw capture stays small.
        for v_slug in sorted(vendor_slugs):
            url = f"{BASE_URL}{VENDOR_PREFIX}{v_slug}"
            payload = self._fetch_payload(url)
            if not payload:
                continue
            historical = rsc.extract_array_after_key(payload, "historicalData")
            snapshots.append(
                Snapshot(
                    name=f"{VENDOR_PREFIX_NAME}{v_slug}",
                    source_url=url,
                    body=json.dumps(historical),
                )
            )

        return snapshots

    # ---------------------------------------------------------------- extract

    def extract(
        self,
        snapshots: list[Snapshot],
        context: RunContext,
    ) -> dict[str, list[DatasetRecord]]:
        extracted: dict[str, list[DatasetRecord]] = {
            "ramp_category_vendors": [],
            "ramp_vendor_adoption_monthly": [],
        }

        index_payload = next((s.body for s in snapshots if s.name == INDEX_SNAPSHOT), "")
        categories = self._discover_categories(index_payload) if index_payload else {}

        # Vendor identity (name/domain) discovered from category cards, keyed by
        # slug — attached to the monthly rows, which carry only metrics.
        vendor_identity: dict[str, tuple[str | None, str | None]] = {}

        for snapshot in snapshots:
            if not snapshot.name.startswith(CATEGORY_PREFIX_NAME):
                continue
            cat_slug = snapshot.name[len(CATEGORY_PREFIX_NAME):]
            cat_name = categories.get(cat_slug, cat_slug)
            for obj in self._vendor_cards(snapshot.body):
                v_slug = _vendor_slug_from_pathname(str(obj.get("pathname", "")))
                if not v_slug:
                    continue
                v_name = obj.get("name") if isinstance(obj.get("name"), str) else None
                v_domain = obj.get("cleanDomain") if isinstance(obj.get("cleanDomain"), str) else None
                vendor_identity.setdefault(v_slug, (v_name, v_domain))

                key_stats = obj.get("keyStats") if isinstance(obj.get("keyStats"), dict) else {}
                extracted["ramp_category_vendors"].append(
                    DatasetRecord(
                        dataset_id="ramp_category_vendors",
                        source_url=snapshot.source_url,
                        source_run_id=context.run_id,
                        scraped_at=context.scraped_at_iso,
                        category_slug=cat_slug,
                        category_name=cat_name,
                        vendor_slug=v_slug,
                        vendor_name=v_name,
                        vendor_domain=v_domain,
                        adoption_rate=_to_float(key_stats.get("adoptionRateValue")),
                        adoption_rate_yoy=_to_float(key_stats.get("adoptionRateYoyChange")),
                    )
                )

        for snapshot in snapshots:
            if not snapshot.name.startswith(VENDOR_PREFIX_NAME):
                continue
            v_slug = snapshot.name[len(VENDOR_PREFIX_NAME):]
            v_name, v_domain = vendor_identity.get(v_slug, (None, None))
            try:
                historical = json.loads(snapshot.body)
            except json.JSONDecodeError as exc:
                print(f"Warning: bad historicalData JSON for {v_slug}: {exc}")
                continue
            if not isinstance(historical, list):
                continue
            for row in historical:
                if not isinstance(row, dict):
                    continue
                spend_month = row.get("spendMonth")
                if not isinstance(spend_month, str) or not spend_month:
                    continue
                rank = row.get("adoptionRank") if isinstance(row.get("adoptionRank"), dict) else {}
                rate = row.get("adoptionRate") if isinstance(row.get("adoptionRate"), dict) else {}
                extracted["ramp_vendor_adoption_monthly"].append(
                    DatasetRecord(
                        dataset_id="ramp_vendor_adoption_monthly",
                        source_url=snapshot.source_url,
                        source_run_id=context.run_id,
                        scraped_at=context.scraped_at_iso,
                        vendor_slug=v_slug,
                        vendor_name=v_name,
                        vendor_domain=v_domain,
                        spend_month=spend_month,
                        adoption_rate=_to_float(rate.get("value")),
                        adoption_rate_yoy=_to_float(rate.get("yoyChange")),
                        adoption_rank=_to_int(rank.get("value")),
                        adoption_rank_mom=_to_int(rank.get("momChange")),
                        adoption_rate_ent=_to_float(row.get("adoptionRateEnt")),
                        adoption_rate_mm=_to_float(row.get("adoptionRateMm")),
                        adoption_rate_smb=_to_float(row.get("adoptionRateSmb")),
                        adoption_rate_growth_delta_mom=_to_float(row.get("adoptionRateGrowthDeltaMoM")),
                        adoption_rate_growth_rank_mom=_to_int(row.get("adoptionRateGrowthRankMoM")),
                        competitor_switch_rate=_to_float(row.get("competitorSwitchRate")),
                        new_adopter_share=_to_float(row.get("newAdopterShare")),
                        dominant_fte_segment=(
                            row.get("dominantFteSegment")
                            if isinstance(row.get("dominantFteSegment"), str)
                            else None
                        ),
                        dominant_fte_segment_pct=_to_float(row.get("dominantFteSegmentPct")),
                    )
                )

        return extracted
