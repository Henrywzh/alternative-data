"""Scrape daily tungsten and molybdenum product prices from news.chinatungsten.com.

Parses tungsten and molybdenum sub-series out of the English article prose,
falling back to local Tesseract OCR on table images when text updates are incomplete,
dedupes by date/URL into incremental raw CSVs, and emits normalized snapshots.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.parse
import subprocess
from datetime import datetime, timedelta
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
MOLY_PROCESSED_DATASET = "molybdenum_price_daily"

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

MOLY_PRICE_FIELDS = [
    "molybdenum_concentrate",
    "ferromolybdenum",
    "ammonium_heptamolybdate",
    "ammonium_tetramolybdate",
]
MOLY_CSV_HEADERS = [
    "date",
    *MOLY_PRICE_FIELDS,
    "title",
    "url",
    "table_image_local",
    "trend_image_local",
]

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

MOLY_PRICE_BOUNDS = {
    "molybdenum_concentrate": (4000.0, 7000.0),
    "ferromolybdenum": (200000.0, 450000.0),
    "ammonium_heptamolybdate": (200000.0, 450000.0),
    "ammonium_tetramolybdate": (200000.0, 450000.0),
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
    val_str = str(val_str).lower().strip()
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


MOLY_PRODUCT_ALIASES = {
    "molybdenum_concentrate": [r"molybdenum\s+concentrate"],
    "ferromolybdenum": [r"ferro\s*-?\s*molybdenum", r"ferromolybdenum"],
    "ammonium_heptamolybdate": [
        r"ammonium\s+hepta\s*-?\s*molybdate",
        r"ammonium\s+heptamolybdate",
    ],
    "ammonium_tetramolybdate": [
        r"ammonium\s+tetra\s*-?\s*molybdate",
        r"ammonium\s+tetramolybdate",
    ],
}

MOLY_RMB_PRICE_RE = re.compile(
    r"rmb\s*([\d,\.]+)\s*(?:/|per)\s*(ton-degree|ton)\b",
    re.IGNORECASE,
)

MOLY_CHANGE_CONTEXT_RE = re.compile(
    r"\b(?:rose|risen|rise|increased?|decreased?|declined?|fell|fallen|dropped|reduced)\s+by\b",
    re.IGNORECASE,
)


def _normalize_moly_text(text: str) -> str:
    text = BeautifulSoup(text, "html.parser").get_text(" ") if "<" in text and ">" in text else str(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[\u2010-\u2015]", "-", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _valid_moly_value(field: str, value: float | str) -> bool:
    if value == "":
        return False
    low, high = MOLY_PRICE_BOUNDS[field]
    return low <= float(value) <= high


def _moly_product_mentions(text: str) -> list[tuple[int, str]]:
    mentions: list[tuple[int, str]] = []
    for field, aliases in MOLY_PRODUCT_ALIASES.items():
        for alias in aliases:
            match = re.search(alias, text, re.IGNORECASE)
            if match:
                mentions.append((match.start(), field))
                break
    return sorted(mentions)


def _nearby_text_has_change_context(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - 80) : min(len(text), end + 80)]
    return bool(MOLY_CHANGE_CONTEXT_RE.search(window))


def _assign_moly_value(extracted: dict, field: str, val_str: str) -> None:
    value = clean_value(val_str)
    if value != "" and _valid_moly_value(field, value):
        extracted[field] = value


def _extract_moly_direct_pairs(text: str) -> dict:
    extracted = {k: "" for k in MOLY_PRICE_FIELDS}
    for field, aliases in MOLY_PRODUCT_ALIASES.items():
        for alias in aliases:
            pattern = re.compile(
                rf"{alias}.{{0,120}}?"
                r"rmb\s*([\d,\.]+)\s*(?:/|per)\s*(ton-degree|ton)\b",
                re.IGNORECASE,
            )
            match = pattern.search(text)
            if not match:
                continue
            if _nearby_text_has_change_context(text, match.start(), match.end()):
                continue
            _assign_moly_value(extracted, field, match.group(1))
            if extracted[field] != "":
                break
    return extracted


def _extract_moly_respectively(text: str) -> dict:
    extracted = {k: "" for k in MOLY_PRICE_FIELDS}
    clauses = re.split(r"(?<=[\.;])\s+", text)
    for clause in clauses:
        if "respectively" not in clause.lower() or "rmb" not in clause.lower():
            continue
        product_mentions = _moly_product_mentions(clause)
        price_matches = list(MOLY_RMB_PRICE_RE.finditer(clause))
        if len(product_mentions) != len(price_matches):
            continue
        for (_, field), price_match in zip(product_mentions, price_matches):
            if _nearby_text_has_change_context(clause, price_match.start(), price_match.end()):
                continue
            _assign_moly_value(extracted, field, price_match.group(1))
    return extracted


def _extract_moly_concentrate_fallback(text: str) -> dict:
    extracted = {k: "" for k in MOLY_PRICE_FIELDS}
    if "molybdenum concentrate" not in text.lower():
        return extracted
    for match in MOLY_RMB_PRICE_RE.finditer(text):
        if match.group(2).lower() != "ton-degree":
            continue
        if _nearby_text_has_change_context(text, match.start(), match.end()):
            continue
        _assign_moly_value(extracted, "molybdenum_concentrate", match.group(1))
        break
    return extracted


def _merge_moly_prices(base: dict, update: dict) -> dict:
    for field in MOLY_PRICE_FIELDS:
        if base.get(field) in ("", None) and update.get(field) not in ("", None):
            base[field] = update[field]
    return base


def extract_molybdenum_prices_from_body(html_text: str) -> dict:
    text = _normalize_moly_text(html_text)
    extracted = {k: "" for k in MOLY_PRICE_FIELDS}
    for strategy in (
        _extract_moly_respectively,
        _extract_moly_direct_pairs,
        _extract_moly_concentrate_fallback,
    ):
        _merge_moly_prices(extracted, strategy(text))
    return extracted


def _clean_ocr_number(val_str: str) -> float | None:
    val_str = re.sub(r"[^\d\.]", "", val_str)
    if not val_str:
        return None
    try:
        return float(val_str)
    except ValueError:
        return None


def _correct_value(val: float | None, field: str) -> float | None:
    if val is None:
        return None
        
    if field == "molybdenum_concentrate":
        if val > 10000:
            val = val / 100.0
        elif val > 1000:
            val = val / 10.0
        
        rmb_val = val * 6.80
        if MOLY_PRICE_BOUNDS[field][0] <= rmb_val <= MOLY_PRICE_BOUNDS[field][1]:
            return round(rmb_val, -1)
        return None
        
    elif field in ("ferromolybdenum", "ammonium_heptamolybdate", "ammonium_tetramolybdate"):
        if val < 10000:
            val = val * 10.0
        elif val > 1000000:
            val = val / 100.0
        elif val > 100000:
            val = val / 10.0
            
        rmb_val = val * 6.80
        if MOLY_PRICE_BOUNDS[field][0] <= rmb_val <= MOLY_PRICE_BOUNDS[field][1]:
            return round(rmb_val, -3)
        return None
        
    return val


def _parse_ocr_text(text: str) -> dict:
    extracted = {}
    lines = text.splitlines()
    
    patterns = {
        "ferromolybdenum": r"ferro.*?\s+([\d,\.]+)\s+(?:usd|usdi)",
        "molybdenum_concentrate": r"concentrate.*?\s+([\d,\.]+)\s+(?:usd|usdi)",
        "ammonium_heptamolybdate": r"hept.*?\s+([\d,\.]+)\s+(?:usd|usdi)",
        "ammonium_tetramolybdate": r"tetr.*?\s+([\d,\.]+)\s+(?:usd|usdi)",
    }
    
    for field, regex in patterns.items():
        extracted[field] = None
        for line in lines:
            match = re.search(regex, line, re.IGNORECASE)
            if match:
                raw_val = _clean_ocr_number(match.group(1))
                corrected = _correct_value(raw_val, field)
                if corrected:
                    extracted[field] = corrected
                break
    return extracted


def _run_tesseract_ocr(image_path: Path) -> dict:
    try:
        txt_base = image_path.with_suffix("")
        txt_file = image_path.with_suffix(".txt")
        if txt_file.exists():
            txt_file.unlink()
            
        result = subprocess.run(
            ["tesseract", str(image_path), str(txt_base), "--psm", "3"],
            capture_output=True,
            text=True,
            errors="replace",
            check=False
        )
        if result.returncode == 0 and txt_file.exists():
            ocr_text = txt_file.read_text(encoding="utf-8", errors="replace")
            txt_file.unlink()
            return _parse_ocr_text(ocr_text)
    except Exception as exc:
        _log(f"  Tesseract OCR execution failed: {exc}")
    return {}


def _find_molybdenum_price_image_url(body: BeautifulSoup) -> str | None:
    """Prefer daily price-table images and avoid trend/average charts."""
    best: tuple[int, str] | None = None
    for img in body.find_all("img"):
        src = img.get("src", "")
        alt = img.get("alt", "")
        img_title = img.get("title", "")
        haystack = " ".join([src, alt, img_title]).lower()
        if "molybdenum" not in haystack or "price" not in haystack:
            continue
        if any(blocked in haystack for blocked in ("trend", "chart", "average", "wechat")):
            continue
        score = 1
        if "price-picture" in haystack or "price picture" in haystack:
            score += 4
        if "picture" in haystack:
            score += 1
        full_url = urllib.parse.urljoin(BASE_URL, src)
        if best is None or score > best[0]:
            best = (score, full_url)
    return best[1] if best else None


def _flag_suspicious_moly_prices(prices: dict, *, context: str) -> None:
    missing = [field for field in MOLY_PRICE_FIELDS if prices.get(field) in ("", None)]
    if missing:
        _log(f"  [{context}] no moly value parsed for: {', '.join(missing)}")
    for field, (low, high) in MOLY_PRICE_BOUNDS.items():
        value = prices.get(field)
        if isinstance(value, (int, float)) and value != "" and not (low <= value <= high):
            _log(f"  [{context}] suspicious moly {field}={value} (outside {low}-{high})")


def _flag_suspicious_prices(prices: dict, *, context: str) -> None:
    missing = [field for field in PRICE_FIELDS if prices.get(field) in ("", None)]
    if missing:
        _log(f"  [{context}] no value parsed for: {', '.join(missing)}")
    for field, (low, high) in PRICE_BOUNDS.items():
        value = prices.get(field)
        if isinstance(value, (int, float)) and value != "" and not (low <= value <= high):
            _log(f"  [{context}] suspicious {field}={value} (outside {low}-{high})")


def parse_date_from_article(soup, title: str) -> str:
    pub_tag = soup.find("dd", class_="published")
    if pub_tag:
        span = pub_tag.find("span")
        date_text = span.text.strip() if span else pub_tag.text.replace("Published on", "").strip()
        try:
            return datetime.strptime(date_text, "%A, %d %B %Y %H:%M").strftime("%Y-%m-%d")
        except ValueError:
            pass
        try:
            # Handle formats like "Thursday, 25 June 2026 16:36"
            cleaned_text = re.sub(r'^[a-zA-Z]+,\s*', '', date_text)
            cleaned_text = re.sub(r'\s+\d+:\d+$', '', cleaned_text)
            return datetime.strptime(cleaned_text, "%d %B %Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
        try:
            return datetime.strptime(date_text, "%d %B %Y").strftime("%Y-%m-%d")
        except ValueError:
            pass

    if title:
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
    except Exception as exc:  # noqa: BLE001
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

        is_moly = "molybdenum" in title.lower()

        if is_moly:
            prices = extract_molybdenum_prices_from_body(body.get_text())
            moly_missing = any(prices.get(f) in ("", None) for f in MOLY_PRICE_FIELDS)
            image_url = _find_molybdenum_price_image_url(body)
                    
            if moly_missing and image_url and image_dir is not None:
                temp_img_name = f"temp_moly_ocr_{date_str}.jpg"
                _log(f"  [{date_str}] Missing text prices. Running local Tesseract OCR on: {image_url}")
                ocr_img_local = download_image(session, image_url, image_dir, temp_img_name)
                if ocr_img_local:
                    ocr_prices = _run_tesseract_ocr(Path(ocr_img_local))
                    for k, v in ocr_prices.items():
                        if v and prices.get(k) in ("", None):
                            prices[k] = v
                    try:
                        Path(ocr_img_local).unlink()
                    except Exception:
                        pass
            _flag_suspicious_moly_prices(prices, context=date_str)
        else:
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
                prefix = "molybdenum" if is_moly else "tungsten"
                if "trend" in filename or "trend" in alt.lower() or "trend" in img_title.lower():
                    trend_img_local = download_image(
                        session, full_src_url, image_dir, f"{prefix}_trend_{date_str}.jpg"
                    )
                elif "price" in filename or "price" in alt.lower() or "price" in img_title.lower():
                    table_img_local = download_image(
                        session, full_src_url, image_dir, f"{prefix}_price_table_{date_str}.jpg"
                    )

        prices["date"] = date_str
        prices["title"] = title
        prices["url"] = url
        prices["table_image_local"] = table_img_local
        prices["trend_image_local"] = trend_img_local
        return prices
    except Exception as exc:  # noqa: BLE001
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


def write_processed_snapshot(base_dir: Path, csv_path: Path, dataset_name: str, fields: list[str]) -> Path | None:
    """Write a normalized, dashboard-friendly snapshot to the `latest` partition."""
    if not csv_path.exists():
        return None
    frame = pd.read_csv(csv_path)
    if frame.empty:
        return None
    keep = ["date", *fields, "title", "url"]
    frame = frame[[c for c in keep if c in frame.columns]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    storage = MineralsSignalStorage(base_dir)
    return storage.write_dataset(dataset_name, frame, run_label="latest")


def _resolve_since_date(since_date: str | None = None, since_days: int | None = None) -> datetime | None:
    if since_date and since_days is not None:
        raise ValueError("Use either since_date or since_days, not both")
    if since_date:
        return datetime.strptime(since_date, "%Y-%m-%d")
    if since_days is not None:
        if since_days < 0:
            raise ValueError("since_days must be non-negative")
        return datetime.utcnow() - timedelta(days=since_days)
    return None


def _is_older_than_cutoff(date_str: str, cutoff: datetime | None) -> bool:
    if cutoff is None or not date_str:
        return False
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date() < cutoff.date()
    except ValueError:
        return False


def _is_daily_price_article_title(title: str, mineral_type: str) -> bool:
    title = title.lower()
    if "news" in title or "video" in title:
        return False
    if mineral_type == "molybdenum" and any(blocked in title for blocked in ("price trend", "trends", "average")):
        return False
    return True


def scrape_range(
    base_dir: str | Path = ".",
    *,
    max_pages: int = 3,
    with_images: bool = False,
    session: requests.Session | None = None,
    since_date: str | None = None,
    since_days: int | None = None,
) -> int:
    """Scrape category pages, append new dated rows, and refresh the processed snapshots."""
    base_dir = Path(base_dir)
    data_dir = base_dir / "data" / "raw" / "minerals_signal_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    tungsten_csv_path = data_dir / "tungsten_chinatungsten.csv"
    moly_csv_path = data_dir / "molybdenum_chinatungsten.csv"
    image_dir = data_dir / "images"
    session = session or build_session()
    cutoff = _resolve_since_date(since_date=since_date, since_days=since_days)

    cutoff_msg = f", since={cutoff.date()}" if cutoff is not None else ""
    _log(f"Scraping up to {max_pages} category pages (images={'on' if with_images else 'off'}{cutoff_msg})...")
    existing_tungsten_dates, existing_tungsten_urls = _load_existing(tungsten_csv_path)
    existing_moly_dates, existing_moly_urls = _load_existing(moly_csv_path)

    if not tungsten_csv_path.exists():
        with tungsten_csv_path.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=CSV_HEADERS).writeheader()
    if not moly_csv_path.exists():
        with moly_csv_path.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=MOLY_CSV_HEADERS).writeheader()

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
            article_links: list[tuple[str, str]] = []
            for art in articles:
                heading = art.find("h2", class_="contentheading") if art.name != "h2" else art
                if not heading:
                    continue
                a_tag = heading.find("a")
                if not a_tag:
                    continue
                title = a_tag.text.strip().lower()
                href = a_tag.get("href", "")
                
                is_tungsten = ("tungsten" in title or "apt" in title) and _is_daily_price_article_title(
                    title, "tungsten"
                )
                is_moly = "molybdenum" in title and _is_daily_price_article_title(title, "molybdenum")
                
                full_url = urllib.parse.urljoin(BASE_URL, href)
                if is_tungsten:
                    article_links.append((full_url, "tungsten"))
                elif is_moly:
                    article_links.append((full_url, "molybdenum"))

            if not article_links:
                _log("No matching articles found on this page.")
                continue

            page_new_tungsten: list[dict] = []
            page_new_moly: list[dict] = []

            for link, mineral_type in article_links:
                if mineral_type == "tungsten":
                    if link in existing_tungsten_urls:
                        continue
                    data = parse_article_page(session, link, image_dir=image_dir, with_images=with_images)
                    existing_tungsten_urls.add(link)
                    if not data:
                        continue
                    date_str = data["date"]
                    if _is_older_than_cutoff(date_str, cutoff):
                        _log(f"Skipping {date_str}: older than cutoff")
                        continue
                    if date_str in existing_tungsten_dates:
                        continue
                    _log(f"Scraped {date_str}: APT={data['apt']}")
                    page_new_tungsten.append(data)
                    existing_tungsten_dates.add(date_str)
                elif mineral_type == "molybdenum":
                    if link in existing_moly_urls:
                        continue
                    data = parse_article_page(session, link, image_dir=image_dir, with_images=with_images)
                    existing_moly_urls.add(link)
                    if not data:
                        continue
                    date_str = data["date"]
                    if _is_older_than_cutoff(date_str, cutoff):
                        _log(f"Skipping Moly {date_str}: older than cutoff")
                        continue
                    if date_str in existing_moly_dates:
                        continue
                    _log(f"Scraped Moly {date_str}: Conc={data['molybdenum_concentrate']}")
                    page_new_moly.append(data)
                    existing_moly_dates.add(date_str)
                
                time.sleep(0.2)

            if page_new_tungsten:
                page_new_tungsten.sort(key=lambda row: row["date"])
                with tungsten_csv_path.open("a", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
                    for row in page_new_tungsten:
                        writer.writerow({k: row.get(k, "") for k in CSV_HEADERS})
                new_count += len(page_new_tungsten)
                _log(f"Wrote {len(page_new_tungsten)} new tungsten records from page {page + 1}.")

            if page_new_moly:
                page_new_moly.sort(key=lambda row: row["date"])
                with moly_csv_path.open("a", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=MOLY_CSV_HEADERS)
                    for row in page_new_moly:
                        writer.writerow({k: row.get(k, "") for k in MOLY_CSV_HEADERS})
                new_count += len(page_new_moly)
                _log(f"Wrote {len(page_new_moly)} new molybdenum records from page {page + 1}.")

        except Exception as exc:  # noqa: BLE001
            _log(f"Error scraping category page: {exc}")
            break

    t_snapshot = write_processed_snapshot(base_dir, tungsten_csv_path, PROCESSED_DATASET, PRICE_FIELDS)
    m_snapshot = write_processed_snapshot(base_dir, moly_csv_path, MOLY_PROCESSED_DATASET, MOLY_PRICE_FIELDS)
    if t_snapshot is not None:
        _log(f"Processed Tungsten snapshot: {t_snapshot}")
    if m_snapshot is not None:
        _log(f"Processed Molybdenum snapshot: {m_snapshot}")

    _log(f"Done. {new_count} new record(s).")
    return new_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape Chinatungsten daily tungsten/molybdenum prices.")
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes")
    parser.add_argument("--max-pages", type=int, default=3, help="Max category pages to scrape")
    parser.add_argument("--since-date", help="Only write articles on/after this YYYY-MM-DD date")
    parser.add_argument("--since-days", type=int, help="Only write articles from the last N days")
    parser.add_argument(
        "--with-images",
        action="store_true",
        help="Also download price-table/trend images (local only; not committed)",
    )
    args = parser.parse_args()
    scrape_range(
        args.base_dir,
        max_pages=args.max_pages,
        with_images=args.with_images,
        since_date=args.since_date,
        since_days=args.since_days,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
