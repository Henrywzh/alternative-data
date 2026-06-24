"""Weekly store-count scraper for Action (action.com).

Counts the number of Action stores per country directly from the public
per-locale ``store-sitemap.xml`` files. The number of store URLs in a
sitemap *is* the store count, so no per-store page fetches are needed.

The set of locales is discovered from ``robots.txt`` on every run, so when
Action launches a new country the new market is picked up automatically (and
logged as a NEW COUNTRY alert). Each run appends one dated snapshot per
country (plus a ``TOTAL`` row) to a long-format parquet time series.

Output: data/processed/action_stores/store_counts.parquet
    columns: date, country_code, country_name, store_count

Run:
    python scripts/scrape_action_stores.py
    python scripts/scrape_action_stores.py --data-dir data --date 2026-06-24
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

ROBOTS_URL = "https://www.action.com/robots.txt"
SITEMAP_NS = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# ISO 3166-1 alpha-2 -> display name. Used for readability only; an unknown
# code (i.e. a brand-new market) still records fine using the code itself.
COUNTRY_NAMES = {
    "AT": "Austria", "BE": "Belgium", "CH": "Switzerland", "CZ": "Czech Republic",
    "DE": "Germany", "ES": "Spain", "FR": "France", "HR": "Croatia",
    "IT": "Italy", "LU": "Luxembourg", "NL": "Netherlands", "PL": "Poland",
    "PT": "Portugal", "RO": "Romania", "SK": "Slovakia",
}


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def discover_locales() -> list[str]:
    """Parse robots.txt for the live list of locales (e.g. 'nl-nl', 'fr-be')."""
    text = _get(ROBOTS_URL).decode("utf-8", errors="ignore")
    locales: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.lower().startswith("sitemap:"):
            continue
        path = urllib.parse.urlparse(line.split(":", 1)[1].strip()).path
        m = re.match(r"^/([a-z]{2}-[a-z]{2})/", path)
        if m and m.group(1) not in locales:
            locales.append(m.group(1))
    return locales


def count_stores_for_locale(locale: str) -> set[str]:
    """Return the set of unique store slugs in a locale's store sitemap.

    Store pages have the form ``/{locale}/{winkels-keyword}/{store-slug}``.
    Location *list* pages contain a ``/l/`` segment and are excluded.
    """
    url = f"https://www.action.com/{locale}/store-sitemap.xml"
    try:
        root = ET.fromstring(_get(url))
    except Exception as exc:  # noqa: BLE001 - log and skip a flaky locale
        print(f"  ! {locale}: failed to load sitemap ({exc})")
        return set()

    slugs: set[str] = set()
    for url_el in root.findall("ns:url", SITEMAP_NS):
        loc_el = url_el.find("ns:loc", SITEMAP_NS)
        if loc_el is None or not loc_el.text:
            continue
        parts = [p for p in urllib.parse.urlparse(loc_el.text).path.strip("/").split("/") if p]
        if len(parts) >= 3 and parts[2] != "l":
            slugs.add(parts[-1])
    return slugs


def collect_counts(snapshot_date: str) -> pd.DataFrame:
    """Scrape all locales and return a long-format counts frame for one date."""
    locales = discover_locales()
    print(f"Discovered {len(locales)} locales from robots.txt: {', '.join(locales)}")

    # country_code -> set of unique store slugs (dedupes multilingual locales
    # such as BE fr/nl and CH de/fr/it that share the same physical stores).
    by_country: dict[str, set[str]] = {}
    for locale in locales:
        cc = locale.split("-")[1].upper()
        slugs = count_stores_for_locale(locale)
        print(f"  {locale} -> {cc}: {len(slugs)} stores")
        by_country.setdefault(cc, set()).update(slugs)

    rows = [
        {
            "date": snapshot_date,
            "country_code": cc,
            "country_name": COUNTRY_NAMES.get(cc, cc),
            "store_count": len(slugs),
        }
        for cc, slugs in sorted(by_country.items())
    ]
    rows.append(
        {
            "date": snapshot_date,
            "country_code": "TOTAL",
            "country_name": "All countries",
            "store_count": sum(len(s) for s in by_country.values()),
        }
    )
    return pd.DataFrame(rows)


def alert_new_countries(new: pd.DataFrame, existing: pd.DataFrame | None) -> None:
    """Print a loud alert for any country code not seen in prior snapshots."""
    known = set(existing["country_code"]) if existing is not None else set()
    for cc in sorted(set(new["country_code"]) - known - {"TOTAL"}):
        name = COUNTRY_NAMES.get(cc, "UNKNOWN — add to COUNTRY_NAMES")
        print(f"  *** NEW COUNTRY: {cc} ({name}) — first appearance in this dataset ***")


def append_snapshot(df: pd.DataFrame, out_path: Path) -> pd.DataFrame:
    """Append today's snapshot, idempotent on (date, country_code)."""
    existing = pd.read_parquet(out_path) if out_path.exists() else None
    alert_new_countries(df, existing)

    combined = df if existing is None else pd.concat([existing, df], ignore_index=True)
    combined = (
        combined.drop_duplicates(subset=["date", "country_code"], keep="last")
        .sort_values(["date", "country_code"])
        .reset_index(drop=True)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(out_path, index=False)
    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Action store counts per country.")
    parser.add_argument("--data-dir", default="data", help="Repository data directory.")
    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="Snapshot date (YYYY-MM-DD); defaults to today (UTC runner date).",
    )
    args = parser.parse_args()

    out_path = Path(args.data_dir) / "processed" / "action_stores" / "store_counts.parquet"

    print("=" * 60)
    print(f"Action store-count snapshot for {args.date}")
    print("=" * 60)

    df = collect_counts(args.date)
    combined = append_snapshot(df, out_path)

    total = int(df.loc[df["country_code"] == "TOTAL", "store_count"].iloc[0])
    n_countries = (df["country_code"] != "TOTAL").sum()
    print("-" * 60)
    print(f"Total stores: {total} across {n_countries} countries")
    print(f"Wrote {out_path} ({len(combined)} rows, {combined['date'].nunique()} snapshots)")


if __name__ == "__main__":
    main()
