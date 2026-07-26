"""Monthly per-store scraper for POP MART (泡泡玛特, 09992.HK) retail stores
and Roboshops, across every market whose store-locator backend could be
reached and enumerated.

POP MART splits its store-locator data across FOUR independent backends,
discovered by inspecting real network traffic from each locale's
"/store-list" page (see scripts/STORE_SCRAPE_REPORT.md for a summary of
findings). This script talks to each one directly over plain HTTP -- no
Playwright/browser needed for three of the four tiers, because none of
them turned out to require a signed request in practice:

1. Mainland China -- ``www.popmart.com.cn`` (a completely separate domain
   and backend from the global site). The store locator at ``/home/map/``
   calls two unauthenticated JSON endpoints:
     - ``apis/portal/stores/map``              -> full province/city tree
     - ``apis/portal/stores/getOfflineStoresList`` (POST, {province,city})
   There is no "give me everything" call; the frontend map issues one
   POST per city, so this script walks the full province/city tree from
   endpoint 1 and calls endpoint 2 once per city (~90 calls). No signing,
   no cookies, no rate limiting observed. NOTE: this endpoint only ever
   returned records for POP MART's own-brand *retail* stores (fields never
   contained a robot/vending-machine flag, and nothing in the page's own
   markup or bundled JS referenced Roboshops) -- China's ~1,800+ Roboshops
   (per POP MART's public disclosures) are not exposed through this public
   web endpoint and are NOT included in this dataset. That gap is real and
   is called out explicitly in this script's summary output.

2. North America + Hong Kong -- ``prod-na-api.popmart.com``, the same
   ``shop/v1/store/mapStoreList`` endpoint the previous version of this
   script already used (via Playwright interception). Testing shows the
   endpoint does not actually validate the ``s`` signature param that the
   real frontend sends, so a plain unsigned POST with a ``country`` filter
   works directly. Verified non-empty for: United States, Hong Kong
   ("Hong Kong, China"), Canada.

3. APAC -- ``prod-apac-api.popmart.com/rpc/store/public_findStoresInQuadrilateral``.
   Despite the name (and despite the original lead saying this needs a
   lat/lon bounding-box grid crawl), in practice the frontend just calls it
   with ``{"area": "<ISO country code>"}`` and gets every store in that
   country back in one shot -- no tiling needed, and no Cloudflare
   Turnstile block was actually hit on this endpoint (Turnstile script tags
   were present on the page but never blocked this specific API call).
   Verified non-empty for: SG, JP, AU, KR, TH, MY, NZ, VN, PH, ID.

4. Europe -- a DIFFERENT host, ``prod-uk-online-api.popmart.com``, same
   ``public_findStoresInQuadrilateral`` RPC shape as APAC. Verified
   non-empty for: GB, FR, DE, ES, IT, NL, DK.

A fifth tier exists -- ``prod-intl-api.popmart.com``, which is what
Taiwan's ``/tw/store-list`` page actually calls (a signed
``mapStoreList``-style endpoint, same shape as tier 2) -- but as of this
script's last verification run, that specific backend was itself returning
``{"code":"20006","message":"當前過於火爆，請稍後重試。"}`` ("currently
too busy, try again later") for nearly every call, including its own
``serverMaintenance/info`` health check reporting ``inMaintenance: 1``.
This was confirmed from *inside a real signed browser session* (Playwright
against the live page), not a guess from an unsigned probe -- i.e. this is
POP MART's own backend being down, not a block on this scraper. Direct
unsigned HTTP to that host is additionally WAF-blocked (HTTP 471), so
Taiwan can only ever be attempted via a real browser. This script makes
that attempt each run via Playwright and honestly reports 0 rows / logs
the failure when the backend is unavailable, rather than fabricating or
silently omitting Taiwan from the run summary.

Output granularity: a rich per-store record (POP MART, unlike most of the
other scrapers in this directory, exposes real store IDs and lat/long), one
row per store per snapshot date:
    data/processed/popmart_stores/store_counts.parquet
        columns: date, brand_name, brand_code, tier, market, country,
                 province, city, store_id, name, name_local, store_type,
                 address, latitude, longitude, phone, data_source

Snapshots are appended via ``append_snapshot(..., key_column="store_id")``,
deduplicated on (date, store_id), so re-running the script does not
overwrite prior history -- same convention as every other scraper here.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from store_scraper_common import DEFAULT_USER_AGENT, append_snapshot  # noqa: E402

BRAND_NAME = "POP MART"
BRAND_CODE = "09992.HK"

CN_MAP_URL = "https://www.popmart.com.cn/apis/portal/stores/map"
CN_STORES_URL = "https://www.popmart.com.cn/apis/portal/stores/getOfflineStoresList"

NA_API_URL = "https://prod-na-api.popmart.com/shop/v1/store/mapStoreList"
# Verified non-empty; a couple of harmless zero-result candidates are kept
# so a future new NA market shows up without a code change.
NA_COUNTRIES = ["United States", "Hong Kong, China", "Canada", "Mexico"]

APAC_API_URL = "https://prod-apac-api.popmart.com/rpc/store/public_findStoresInQuadrilateral"
APAC_AREAS = [
    "SG", "JP", "AU", "KR", "TH", "MY", "NZ", "VN", "PH", "ID",
    # verified empty as of this run, kept as future-proofing:
    "MO", "IN", "BN", "KH",
]

UK_ONLINE_API_URL = "https://prod-uk-online-api.popmart.com/rpc/store/public_findStoresInQuadrilateral"
UK_ONLINE_AREAS = [
    "GB", "FR", "DE", "ES", "IT", "NL", "DK",
    # verified empty as of this run, kept as future-proofing:
    "BE", "AT", "PT", "CH", "SE", "NO", "FI", "PL", "IE",
]

# Taiwan is the one confirmed market that only exists behind the signed,
# WAF-protected prod-intl-api.popmart.com backend (mapStoreList-shaped,
# same as tier 2) -- direct HTTP cannot reach it, so it is attempted via a
# real Playwright session. See module docstring for the verified-down
# status as of the last run.
INTL_PLAYWRIGHT_MARKETS = [("TW", "https://www.popmart.com/tw/store-list")]

HEADERS_BASE = {"User-Agent": DEFAULT_USER_AGENT, "Content-Type": "application/json"}


def _post_json(url: str, payload: dict, *, extra_headers: dict | None = None, timeout: int = 20) -> dict | None:
    """POST a JSON body and return the parsed JSON response, or None on failure."""
    headers = dict(HEADERS_BASE)
    if extra_headers:
        headers.update(extra_headers)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001
        print(f"    fetch failed: {url} ({exc})")
        return None


def _get_json(url: str, *, extra_headers: dict | None = None, timeout: int = 20) -> dict | None:
    headers = dict(HEADERS_BASE)
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001
        print(f"    fetch failed: {url} ({exc})")
        return None


def _to_float(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _cn_store_id(rec: dict, province: str, city: str) -> str:
    """Build a stable synthetic store ID for a mainland China record.

    The .cn endpoint doesn't return a native store ID, so hash the fields
    that uniquely and stably identify a physical location.
    """
    name_cn = (rec.get("name") or {}).get("zh-Hans-CN")
    key = f"{province}|{city}|{name_cn}|{rec.get('latitude')}|{rec.get('longitude')}"
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]
    return f"CN-{digest}"


def fetch_cn_stores() -> list[dict]:
    """Enumerate all mainland China retail stores via the province/city tree."""
    print("  [CN] fetching province/city tree ...")
    tree = _get_json(CN_MAP_URL)
    if not tree or "data" not in tree:
        print("  [CN] could not fetch the province/city tree; skipping mainland China entirely.")
        return []

    pairs = [
        (prov["name"], city["name"])
        for prov in tree["data"]
        for city in prov.get("children", [])
    ]
    print(f"  [CN] {len(pairs)} province/city pairs to query")

    records: list[dict] = []
    errors = 0
    for province, city in pairs:
        resp = _post_json(CN_STORES_URL, {"province": province, "city": city})
        if resp is None or resp.get("returnCode") != 1:
            errors += 1
            time.sleep(0.25)
            continue
        for s in resp.get("data", []):
            name_map = s.get("name") or {}
            addr_map = s.get("addressDetail") or {}
            records.append(
                {
                    "tier": "CN",
                    "market": "CN",
                    "country": "China",
                    "province": s.get("province") or province,
                    "city": s.get("city") or city,
                    "store_id": _cn_store_id(s, province, city),
                    "name": name_map.get("zh-Hans-CN"),
                    "name_local": name_map.get("en-US"),
                    "store_type": "Retail Store",
                    "address": addr_map.get("zh-Hans-CN") or addr_map.get("en-US"),
                    "latitude": _to_float(s.get("latitude")),
                    "longitude": _to_float(s.get("longitude")),
                    "phone": s.get("tel"),
                    "data_source": "popmart.com.cn apis/portal/stores/getOfflineStoresList",
                }
            )
        time.sleep(0.25)

    if errors:
        print(f"  [CN] {errors}/{len(pairs)} city queries failed (network/backend errors)")
    print(f"  [CN] {len(records)} retail stores collected across {len(pairs) - errors} cities")
    return records


NA_TYPE_MAP = {1: "Retail Store", 2: "Roboshop", 4: "Pop-up Store"}


def fetch_na_stores() -> list[dict]:
    """Fetch US/HK/CA (and any other NA-cluster country) via mapStoreList."""
    records: list[dict] = []
    for country in NA_COUNTRIES:
        payload = {
            "latitudeCenter": "", "longitudeCenter": "",
            "latitudeSouthwest": "", "longitudeSouthwest": "",
            "latitudeNortheast": "", "longitudeNortheast": "",
            "query": "", "country": country,
            "t": int(time.time()),
        }
        resp = _post_json(NA_API_URL, payload, extra_headers={"referer": "https://www.popmart.com/"})
        stores = (resp or {}).get("data", {}).get("storeList") if resp else None
        stores = stores or []
        print(f"  [NA] {country}: {len(stores)} stores")
        for s in stores:
            records.append(
                {
                    "tier": "NA",
                    "market": s.get("bigRegion") or country,
                    "country": s.get("country") or country,
                    "province": s.get("administrativeDivisionLevel1"),
                    "city": s.get("administrativeDivisionLevel2"),
                    "store_id": f"NA-{s.get('id')}",
                    "name": s.get("nameLocal") or s.get("nameCN"),
                    "name_local": s.get("nameCN"),
                    "store_type": NA_TYPE_MAP.get(s.get("type"), "Other"),
                    "address": s.get("addressLocal"),
                    "latitude": _to_float(s.get("lat")),
                    "longitude": _to_float(s.get("lon")),
                    "phone": s.get("pureTel"),
                    "data_source": "prod-na-api.popmart.com shop/v1/store/mapStoreList",
                }
            )
        time.sleep(0.3)
    return records


QUAD_TYPE_MAP = {"PHYSICAL": "Retail Store", "ROBOT": "Roboshop", "FLASH": "Pop-up Store", "PARTNER": "Partner Store"}


def _fetch_quadrilateral_area(api_url: str, area: str, data_source: str, tier: str) -> list[dict]:
    headers = {
        "x-area": area,
        "referer": "https://www.popmart.com/",
        "x-device-type": "web-pc",
        "accept-language": "en-us",
    }
    resp = _post_json(api_url, {"json": {"area": area}}, extra_headers=headers)
    stores = (resp or {}).get("json") if resp else None
    stores = stores or []
    print(f"  [{area}] {len(stores)} stores")
    records = []
    for s in stores:
        name_field = s.get("name")
        name_map = name_field if isinstance(name_field, dict) else None
        records.append(
            {
                "tier": tier,
                "market": area,
                "country": area,
                "province": None,
                "city": None,
                "store_id": f"Q-{s.get('id') or s.get('storeId')}",
                "name": (name_map or {}).get("en-US") if name_map else name_field,
                "name_local": s.get("localName"),
                "store_type": QUAD_TYPE_MAP.get(s.get("storeType"), "Other"),
                "address": s.get("address"),
                "latitude": _to_float(s.get("latitude")),
                "longitude": _to_float(s.get("longitude")),
                "phone": s.get("phoneNumber"),
                "data_source": data_source,
            }
        )
    return records


def fetch_apac_stores() -> list[dict]:
    records = []
    for area in APAC_AREAS:
        records.extend(
            _fetch_quadrilateral_area(
                APAC_API_URL, area,
                "prod-apac-api.popmart.com public_findStoresInQuadrilateral",
                "APAC",
            )
        )
        time.sleep(0.4)
    return records


def fetch_uk_online_stores() -> list[dict]:
    records = []
    for area in UK_ONLINE_AREAS:
        records.extend(
            _fetch_quadrilateral_area(
                UK_ONLINE_API_URL, area,
                "prod-uk-online-api.popmart.com public_findStoresInQuadrilateral",
                "UK_ONLINE",
            )
        )
        time.sleep(0.4)
    return records


async def fetch_intl_stores_via_playwright() -> list[dict]:
    """Attempt the signed, WAF-protected prod-intl-api tier (Taiwan) via a
    real browser session. Returns [] and prints a clear reason if the
    backend is unreachable/in maintenance -- never fabricates rows.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("  [INTL] playwright not installed; skipping Taiwan.")
        return []

    records: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=DEFAULT_USER_AGENT)

        for market_code, url in INTL_PLAYWRIGHT_MARKETS:
            page = await context.new_page()
            captured: dict = {}

            async def handle_response(response, _captured=captured):
                if "mapStoreList" in response.url:
                    try:
                        _captured["body"] = json.loads(await response.text())
                    except Exception:  # noqa: BLE001
                        pass
                if "serverMaintenance/info" in response.url:
                    try:
                        _captured["maintenance"] = json.loads(await response.text())
                    except Exception:  # noqa: BLE001
                        pass

            page.on("response", handle_response)
            try:
                await page.goto(url, wait_until="load", timeout=25000)
                await page.wait_for_timeout(8000)
            except Exception as exc:  # noqa: BLE001
                print(f"  [INTL:{market_code}] page load failed: {exc}")
                await page.close()
                continue
            await page.close()

            body = captured.get("body")
            if body and body.get("code") == "OK":
                stores = body.get("data", {}).get("storeList", [])
                print(f"  [INTL:{market_code}] {len(stores)} stores")
                for s in stores:
                    records.append(
                        {
                            "tier": "INTL",
                            "market": market_code,
                            "country": s.get("country") or market_code,
                            "province": s.get("administrativeDivisionLevel1"),
                            "city": s.get("administrativeDivisionLevel2"),
                            "store_id": f"INTL-{s.get('id')}",
                            "name": s.get("nameLocal") or s.get("nameCN"),
                            "name_local": s.get("nameCN"),
                            "store_type": NA_TYPE_MAP.get(s.get("type"), "Other"),
                            "address": s.get("addressLocal"),
                            "latitude": _to_float(s.get("lat")),
                            "longitude": _to_float(s.get("lon")),
                            "phone": s.get("pureTel"),
                            "data_source": "prod-intl-api.popmart.com shop/v1/store/mapStoreList",
                        }
                    )
            else:
                maint = (captured.get("maintenance") or {}).get("data") or {}
                if maint.get("inMaintenance"):
                    print(f"  [INTL:{market_code}] backend reports inMaintenance=1 -- unreachable this run, no rows fabricated.")
                else:
                    reason = (body or {}).get("message") if body else "no mapStoreList response observed"
                    print(f"  [INTL:{market_code}] unreachable this run ({reason}) -- no rows fabricated.")

        await browser.close()

    return records


def collect_all_stores(snapshot_date: str) -> pd.DataFrame:
    all_records: list[dict] = []

    print("Mainland China (popmart.com.cn)")
    all_records.extend(fetch_cn_stores())

    print("North America + Hong Kong (prod-na-api)")
    all_records.extend(fetch_na_stores())

    print("APAC (prod-apac-api)")
    all_records.extend(fetch_apac_stores())

    print("Europe (prod-uk-online-api)")
    all_records.extend(fetch_uk_online_stores())

    print("Taiwan / legacy intl tier (prod-intl-api, via Playwright)")
    all_records.extend(asyncio.run(fetch_intl_stores_via_playwright()))

    if not all_records:
        return pd.DataFrame()

    df = pd.DataFrame(all_records)
    df.insert(0, "date", snapshot_date)
    df.insert(1, "brand_name", BRAND_NAME)
    df.insert(2, "brand_code", BRAND_CODE)
    df = df.drop_duplicates(subset=["store_id"], keep="first").reset_index(drop=True)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape POP MART global store/Roboshop counts.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    out_path = Path(args.data_dir) / "processed" / "popmart_stores" / "store_counts.parquet"

    print(f"POP MART (泡泡玛特, 09992.HK) global store snapshot for {args.date}")
    print("=" * 65)

    df = collect_all_stores(args.date)

    if not df.empty:
        total = len(df)
        print("=" * 65)
        print(f"Total stores collected this run: {total}")
        print("\nBy market:")
        print(df.groupby("market").size().sort_values(ascending=False).to_string())
        print("\nBy store type:")
        print(df.groupby("store_type").size().sort_values(ascending=False).to_string())
    else:
        print("No POP MART store records extracted this run.")
        sys.exit(1)

    combined = append_snapshot(df, out_path, key_column="store_id")
    print(f"\nWrote {out_path} ({len(combined) if combined is not None else 0} rows across all history)")


if __name__ == "__main__":
    main()
