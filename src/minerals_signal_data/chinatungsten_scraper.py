"""Scrape daily tungsten product prices from news.chinatungsten.com.

Parses 9 tungsten sub-series (APT, wolframite/scheelite concentrate, tungsten /
carbide powder, ferrotungsten, cobalt powder, scrap carbide, European APT) out of
the English "tungsten product news" article prose, dedupes by date/URL into an
incremental raw CSV, and emits a normalized snapshot for the dashboard.

Network access is centralized in a retrying ``requests.Session``; image download is
opt-in. Importing this module has no side effects (no filesystem writes), so the
pure parsing helpers are unit-testable without network.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from minerals_signal_data.storage import MineralsSignalStorage

BASE_URL = "http://news.chinatungsten.com"
CATEGORY_URL = f"{BASE_URL}/en/tungsten-product-news.html"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)
REQUEST_TIMEOUT = 15
PROCESSED_DATASET = "tungsten_price_daily"

PRICE_FIELDS = [
    "wolframite_concentrate",
    "scheelite_concentrate",
    "apt",
    "european_apt",
    "tungsten_powder",
    "tungsten_carbide_powder",
    "ferrotungsten",
    "cobalt_powder",
    "scrap_carbide_rod",
]
CSV_HEADERS = [
    "date",
    *PRICE_FIELDS,
    "title",
    "url",
    "table_image_local",
    "trend_image_local",
]

# Generous plausibility bands per series — used only to *flag* suspicious
# extractions (e.g. a stray year parsed as a price), never to silently drop data.
PRICE_BOUNDS = {
    "wolframite_concentrate": (50_000, 5_000_000),
    "scheelite_concentrate": (50_000, 5_000_000),
    "apt": (50_000, 5_000_000),
    "ferrotungsten": (50_000, 5_000_000),
    "european_apt": (50, 100_000),
    "tungsten_powder": (50, 100_000),
    "tungsten_carbide_powder": (50, 100_000),
    "cobalt_powder": (10, 100_000),
    "scrap_carbide_rod": (10, 100_000),
}


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def clean_value(val_str):
    if not val_str:
        return ""
    val_str = val_str.lower().strip()
    is_million = "million" in val_str

    # handle dot separator (e.g. 1.480,000 -> 1480,000)
    val_str = re.sub(r"\.(\d{3}),", r"\1,", val_str)

    # remove commas, dollar signs, spaces, etc.
    val_str = val_str.replace(",", "").replace("$", "").replace("million", "").strip()
    match = re.search(r"(\d+\.?\d*)", val_str)
    if match:
        val = float(match.group(1))
        if is_million:
            val *= 1000000
        return val
    return ""


def parse_price(text, pattern):
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def extract_prices_from_body(html_text):
    # Patterns handle 'is/was RMB ...', 'price: RMB ...', 'priced at RMB ...', 'rose/fell to RMB...'
    trans = r"(?:\s*:\s*|[^\d]{1,50})?"
    patterns = {
        "wolframite_concentrate": rf"65%\s+(?:wolframite|black\s+tungsten)\s+concentrate(?:\s+price)?{trans}(?:RMB|USD)\s*([\d,\.\-\$]+(?:\s*million)?)",
        "scheelite_concentrate": rf"65%\s+scheelite\s+concentrate(?:\s+price)?{trans}(?:RMB|USD)\s*([\d,\.\-\$]+(?:\s*million)?)",
        "apt": rf"(?:Ammonium\s+paratungstate\s*\(APT\)|China's\s+APT|APT)(?:\s+price)?{trans}(?:RMB|USD)\s*([\d,\.\-\$]+(?:\s*million)?)",
        "european_apt": rf"European\s+APT(?:\s+price)?{trans}(?:RMB|USD)?\s*([\d,\.\-\$]+(?:\s*million)?)\s*/\s*mtu",
        "tungsten_powder": rf"Tungsten\s+powder(?:\s+price)?{trans}(?:RMB|USD)\s*([\d,\.\-\$]+(?:\s*million)?)",
        "tungsten_carbide_powder": rf"Tungsten\s+carbide\s+powder(?:\s+price)?{trans}(?:RMB|USD)\s*([\d,\.\-\$]+(?:\s*million)?)",
        "ferrotungsten": rf"(?:70%?\s+)?ferrotungsten(?:\s+price)?{trans}(?:RMB|USD)\s*([\d,\.\-\$]+(?:\s*million)?)",
        "cobalt_powder": rf"Cobalt\s+powder(?:\s+price)?{trans}(?:RMB|USD)\s*([\d,\.\-\$]+(?:\s*million)?)",
        "scrap_carbide_rod": rf"(?:Tungsten\s+)?scrap\s+(?:tungsten\s+)?(?:carbide\s+)?(?:rod|drill\s+bit|waste)(?:\s+price)?{trans}(?:RMB|USD)\s*([\d,\.\-\$]+(?:\s*million)?)",
    }
    extracted = {}
    for key, pattern in patterns.items():
        val_str = parse_price(html_text, pattern)
        extracted[key] = clean_value(val_str)
    return extracted


def _flag_suspicious_prices(prices: dict, *, context: str) -> None:
    """Log series that extracted nothing or land outside their plausibility band."""
    missing = [field for field in PRICE_FIELDS if prices.get(field) in ("", None)]
    if missing:
        _log(f"  [{context}] no value parsed for: {', '.join(missing)}")
    for field, (low, high) in PRICE_BOUNDS.items():
        value = prices.get(field)
        if isinstance(value, (int, float)) and value != "" and not (low <= value <= high):
            _log(f"  [{context}] suspicious {field}={value} (outside {low}-{high})")


def parse_date_from_article(soup, title: str) -> str:
    """Resolve the article date from the published meta, falling back to the title."""
    pub_tag = soup.find("dd", class_="published")
    if pub_tag:
        span = pub_tag.find("span")
        date_text = span.text.strip() if span else pub_tag.text.replace("Published on", "").strip()
        try:
            return datetime.strptime(date_text, "%A, %d %B %Y %H:%M").strftime("%Y-%m-%d")
        except ValueError:
            pass

    if title:
        # "June 25, 2026" or "June. 25, 2026"
        match = re.search(r"([a-zA-Z]+)\.?\s+(\d+),\s+(\d{4})", title)
        if match:
            try:
                return datetime.strptime(match.group(0).replace(".", ""), "%B %d, %Y").strftime("%Y-%m-%d")
            except ValueError:
                pass
    return ""


def download_image(session: requests.Session, url: str, image_dir: Path, filename: str) -> str:
    try:
        image_dir.mkdir(parents=True, exist_ok=True)
        filepath = image_dir / filename
        if filepath.exists() and filepath.stat().st_size > 0:
            return str(filepath)
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            filepath.write_bytes(response.content)
            return str(filepath)
    except Exception as exc:  # noqa: BLE001 - best-effort, never fatal
        _log(f"Error downloading image {url}: {exc}")
    return ""


def parse_article_page(
    session: requests.Session,
    url: str,
    *,
    image_dir: Path | None = None,
    with_images: bool = False,
) -> dict | None:
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            _log(f"Article {url} returned status {response.status_code}")
            return None
        soup = BeautifulSoup(response.text, "html.parser")

        title_tag = soup.find("h2", class_="contentheading")
        title = title_tag.text.strip() if title_tag else ""

        date_str = parse_date_from_article(soup, title)
        if not date_str:
            _log(f"Could not resolve a date for {url}; skipping")
            return None

        body = soup.find("div", class_="item-page") or soup.find("div", class_="contentpaneopen")
        if not body:
            _log(f"No article body found for {url}; skipping")
            return None

        prices = extract_prices_from_body(body.get_text())
        _flag_suspicious_prices(prices, context=date_str)

        table_img_local = ""
        trend_img_local = ""
        if with_images and image_dir is not None:
            for img in body.find_all("img"):
                src = img.get("src", "")
                alt = img.get("alt", "")
                img_title = img.get("title", "")
                full_src_url = urllib.parse.urljoin(BASE_URL, src)
                filename = src.split("/")[-1]
                if "trend" in filename or "trend" in alt.lower() or "trend" in img_title.lower():
                    trend_img_local = download_image(
                        session, full_src_url, image_dir, f"tungsten_trend_{date_str}.jpg"
                    )
                elif "price" in filename or "price" in alt.lower() or "price" in img_title.lower():
                    table_img_local = download_image(
                        session, full_src_url, image_dir, f"tungsten_price_table_{date_str}.jpg"
                    )

        prices["date"] = date_str
        prices["title"] = title
        prices["url"] = url
        prices["table_image_local"] = table_img_local
        prices["trend_image_local"] = trend_img_local
        return prices
    except Exception as exc:  # noqa: BLE001 - one bad article must not abort the run
        _log(f"Error parsing article {url}: {exc}")
        return None


def _load_existing(csv_path: Path) -> tuple[set[str], set[str]]:
    existing_dates: set[str] = set()
    existing_urls: set[str] = set()
    if csv_path.exists():
        with csv_path.open("r", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("date"):
                    existing_dates.add(row["date"])
                if row.get("url"):
                    existing_urls.add(row["url"])
    return existing_dates, existing_urls


def write_processed_snapshot(base_dir: Path, csv_path: Path) -> Path | None:
    """Write a normalized, dashboard-friendly snapshot to the `latest` partition."""
    if not csv_path.exists():
        return None
    frame = pd.read_csv(csv_path)
    if frame.empty:
        return None
    keep = ["date", *PRICE_FIELDS, "title", "url"]
    frame = frame[[c for c in keep if c in frame.columns]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    storage = MineralsSignalStorage(base_dir)
    return storage.write_dataset(PROCESSED_DATASET, frame, run_label="latest")


def scrape_range(
    base_dir: str | Path = ".",
    *,
    max_pages: int = 3,
    with_images: bool = False,
    session: requests.Session | None = None,
) -> int:
    """Scrape category pages, append new dated rows, and refresh the processed snapshot.

    Returns the number of new records written.
    """
    base_dir = Path(base_dir)
    data_dir = base_dir / "data" / "raw" / "minerals_signal_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / "tungsten_chinatungsten.csv"
    image_dir = data_dir / "images"
    session = session or build_session()

    _log(f"Scraping up to {max_pages} category pages (images={'on' if with_images else 'off'})...")
    existing_dates, existing_urls = _load_existing(csv_path)

    if not csv_path.exists():
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=CSV_HEADERS).writeheader()

    new_count = 0
    for page in range(max_pages):
        start = page * 10
        url = f"{CATEGORY_URL}?start={start}" if start > 0 else CATEGORY_URL
        _log(f"Fetching category page {page + 1}: {url}")
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            if response.status_code != 200:
                _log(f"Failed to fetch {url}, status {response.status_code}")
                break
            soup = BeautifulSoup(response.text, "html.parser")

            articles = soup.find_all("div", class_="contentpaneopen") or soup.find_all(
                "h2", class_="contentheading"
            )
            article_links: list[str] = []
            for art in articles:
                heading = art.find("h2", class_="contentheading") if art.name != "h2" else art
                if not heading:
                    continue
                a_tag = heading.find("a")
                if not a_tag:
                    continue
                title = a_tag.text.strip().lower()
                href = a_tag.get("href", "")
                if ("tungsten" in title or "apt" in title) and "news" not in title and "video" not in title:
                    article_links.append(urllib.parse.urljoin(BASE_URL, href))

            if not article_links:
                _log("No matching articles found on this page.")
                continue

            page_new_data: list[dict] = []
            for link in article_links:
                if link in existing_urls:
                    continue
                data = parse_article_page(session, link, image_dir=image_dir, with_images=with_images)
                existing_urls.add(link)
                if not data:
                    continue
                date_str = data["date"]
                if date_str in existing_dates:
                    continue
                _log(f"Scraped {date_str}: APT={data['apt']}")
                page_new_data.append(data)
                existing_dates.add(date_str)
                time.sleep(0.2)

            if page_new_data:
                page_new_data.sort(key=lambda row: row["date"])
                with csv_path.open("a", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
                    for row in page_new_data:
                        writer.writerow({k: row.get(k, "") for k in CSV_HEADERS})
                new_count += len(page_new_data)
                _log(f"Wrote {len(page_new_data)} new records from page {page + 1}.")
        except Exception as exc:  # noqa: BLE001 - keep partial progress, refresh snapshot below
            _log(f"Error scraping category page: {exc}")
            break

    snapshot = write_processed_snapshot(base_dir, csv_path)
    if snapshot is not None:
        _log(f"Processed snapshot: {snapshot}")
    _log(f"Done. {new_count} new record(s).")
    return new_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape Chinatungsten daily tungsten prices.")
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes")
    parser.add_argument("--max-pages", type=int, default=3, help="Max category pages to scrape")
    parser.add_argument(
        "--with-images",
        action="store_true",
        help="Also download price-table/trend images (local only; not committed)",
    )
    args = parser.parse_args()
    scrape_range(args.base_dir, max_pages=args.max_pages, with_images=args.with_images)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
