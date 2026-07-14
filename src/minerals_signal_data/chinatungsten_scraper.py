"""Scrape daily tungsten, molybdenum, and rare-earth product prices from news.chinatungsten.com.

Parses tungsten and molybdenum sub-series out of the English article prose,
falling back to local Tesseract OCR on table images when text updates are incomplete,
dedupes by date/URL into incremental raw CSVs, and emits normalized snapshots.

Rare-earth coverage is a thin, text-only extractor (no OCR yet): the "Rare Earth
News" category is new on the site (first observed articles: June 2026) and each
article's prose only names 2-3 of ~12 tracked oxides per day (the rest live in a
price-table image), so per-day coverage is intentionally sparse.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.parse
import subprocess
import hashlib
import json
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
# Rare-earth articles only appear in the general tungsten-product-news listing
# briefly (they scroll off within a day or two); the dedicated category page is
# the reliable source and has ~daily history going back several weeks.
REE_CATEGORY_URL = f"{BASE_URL}/en/tungsten-news/rare-earth-news.html"
USER_AGENT = (
    "MineralsPriceResearch/1.0 "
    "(+https://github.com/henrywzh/alternative-data; public research data collector)"
)
REQUEST_TIMEOUT = 15
CTIA_MIN_REQUEST_INTERVAL_SECONDS = 15.0
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
    "source",
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
    "source",
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

REE_PROCESSED_DATASET = "rare_earth_price_daily"

REE_PRICE_FIELDS = [
    "lanthanum_oxide",
    "cerium_oxide",
    "praseodymium_oxide",
    "neodymium_oxide",
    "samarium_oxide",
    "europium_oxide",
    "gadolinium_oxide",
    "terbium_oxide",
    "dysprosium_oxide",
    "holmium_oxide",
    "erbium_oxide",
    "yttrium_oxide",
]
REE_CSV_HEADERS = [
    "date",
    *REE_PRICE_FIELDS,
    "source",
    "title",
    "url",
    "table_image_local",
    "trend_image_local",
]

# Light rare earths (lanthanum, cerium) trade roughly two orders of magnitude
# cheaper than the mid/heavy oxides in the Chinese domestic market; a single shared
# band would let a light-REE-sized mis-parse (e.g. a light-oxide figure or unrelated
# number) slip through as a bogus price for a heavy oxide field, or vice versa.
_REE_LIGHT_FIELDS = {"lanthanum_oxide", "cerium_oxide"}
REE_PRICE_BOUNDS = {
    field: (1_000.0, 100_000.0) if field in _REE_LIGHT_FIELDS else (100_000.0, 5_000_000.0)
    for field in REE_PRICE_FIELDS
}


def _log(message: str) -> None:
    print(message, file=sys.stderr)


class CTIAFetchError(RuntimeError):
    """Raised when CTIA declines a request so the run stops without retrying."""


def build_session(*, retries: int = 4) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=retries,
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


REE_PRODUCT_ALIASES = {
    "lanthanum_oxide": [r"lanthanum\s+oxide"],
    "cerium_oxide": [r"cerium\s+oxide"],
    "praseodymium_oxide": [r"praseodymium\s+oxide"],
    "neodymium_oxide": [r"neodymium\s+oxide"],
    "samarium_oxide": [r"samarium\s+oxide"],
    "europium_oxide": [r"europium\s+oxide"],
    "gadolinium_oxide": [r"gadolinium\s+oxide"],
    "terbium_oxide": [r"terbium\s+oxide"],
    "dysprosium_oxide": [r"dysprosium\s+oxide"],
    "holmium_oxide": [r"holmium\s+oxide"],
    "erbium_oxide": [r"erbium\s+oxide"],
    "yttrium_oxide": [r"yttrium\s+oxide"],
}

REE_RMB_PRICE_RE = re.compile(r"rmb\s*([\d,\.]+)\s*(?:/|per)\s*ton\b", re.IGNORECASE)


def _valid_ree_value(field: str, value: float | str) -> bool:
    if value == "":
        return False
    low, high = REE_PRICE_BOUNDS[field]
    return low <= float(value) <= high


def _assign_ree_value(extracted: dict, field: str, val_str: str) -> None:
    value = clean_value(val_str)
    if value != "" and _valid_ree_value(field, value):
        extracted[field] = value


def _ree_product_mentions(text: str) -> list[tuple[int, str]]:
    mentions: list[tuple[int, str]] = []
    for field, aliases in REE_PRODUCT_ALIASES.items():
        for alias in aliases:
            match = re.search(alias, text, re.IGNORECASE)
            if match:
                mentions.append((match.start(), field))
                break
    return sorted(mentions)


def _extract_ree_respectively(text: str) -> dict:
    """Parse the common 'the prices of X oxide, Y oxide, ... are approximately
    RMB A, RMB B, ..., respectively' sentence. Only 2-3 of the 12 tracked oxides
    are typically named per article, so most fields stay unset most days."""
    extracted = {k: "" for k in REE_PRICE_FIELDS}
    clauses = re.split(r"(?<=[\.;])\s+", text)
    for clause in clauses:
        if "respectively" not in clause.lower() or "rmb" not in clause.lower():
            continue
        product_mentions = _ree_product_mentions(clause)
        price_matches = list(REE_RMB_PRICE_RE.finditer(clause))
        if not product_mentions or len(product_mentions) != len(price_matches):
            continue
        for (_, field), price_match in zip(product_mentions, price_matches):
            if _nearby_text_has_change_context(clause, price_match.start(), price_match.end()):
                continue
            _assign_ree_value(extracted, field, price_match.group(1))
    return extracted


def _extract_ree_direct_pairs(text: str) -> dict:
    """Fallback for a single oxide mentioned outside a 'respectively' list,
    e.g. 'Neodymium oxide price is RMB 450,000/ton today.'"""
    extracted = {k: "" for k in REE_PRICE_FIELDS}
    for field, aliases in REE_PRODUCT_ALIASES.items():
        for alias in aliases:
            pattern = re.compile(rf"{alias}.{{0,120}}?rmb\s*([\d,\.]+)\s*(?:/|per)\s*ton\b", re.IGNORECASE)
            match = pattern.search(text)
            if not match:
                continue
            if _nearby_text_has_change_context(text, match.start(), match.end()):
                continue
            _assign_ree_value(extracted, field, match.group(1))
            if extracted[field] != "":
                break
    return extracted


def _merge_ree_prices(base: dict, update: dict) -> dict:
    for field in REE_PRICE_FIELDS:
        if base.get(field) in ("", None) and update.get(field) not in ("", None):
            base[field] = update[field]
    return base


def extract_rare_earth_prices_from_body(html_text: str) -> dict:
    # _normalize_moly_text is a generic HTML/whitespace normalizer despite its name;
    # shared across the tungsten/moly/REE extractors.
    text = _normalize_moly_text(html_text)
    extracted = {k: "" for k in REE_PRICE_FIELDS}
    for strategy in (_extract_ree_respectively, _extract_ree_direct_pairs):
        _merge_ree_prices(extracted, strategy(text))
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
        image_path = Path(image_path).resolve()
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


def _flag_suspicious_ree_prices(prices: dict, *, context: str) -> None:
    # Sparse coverage is expected for REE (2-3 of 12 oxides/day, text-only), so this
    # logs a summary rather than warning on every missing field like tungsten/moly.
    populated = [field for field in REE_PRICE_FIELDS if prices.get(field) not in ("", None)]
    _log(f"  [{context}] rare earth: {len(populated)}/{len(REE_PRICE_FIELDS)} oxides parsed ({', '.join(populated) or 'none'})")
    for field, (low, high) in REE_PRICE_BOUNDS.items():
        value = prices.get(field)
        if isinstance(value, (int, float)) and value != "" and not (low <= value <= high):
            _log(f"  [{context}] suspicious rare earth {field}={value} (outside {low}-{high})")



def _wait_for_ctia_request(session: requests.Session) -> None:
    """Keep CTIA traffic deliberately slow across API and image requests."""
    previous_request = getattr(session, "_ctia_last_request_at", None)
    if previous_request is not None:
        remaining = CTIA_MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - previous_request)
        if remaining > 0:
            time.sleep(remaining)


def _ctia_get(session: requests.Session, url: str) -> requests.Response:
    """Make exactly one CTIA request and fail the entire run on refusal."""
    _wait_for_ctia_request(session)
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise CTIAFetchError(f"CTIA request failed for {url}: {exc}") from exc
    finally:
        session._ctia_last_request_at = time.monotonic()

    if response.status_code != 200:
        raise CTIAFetchError(f"CTIA returned HTTP {response.status_code} for {url}")
    return response


def _get_ctia_url(
    session: requests.Session,
    url: str,
    cache_dir: Path = Path("/tmp/ctia_cache"),
) -> list | dict:
    """Fetch a short-lived cached CTIA API response without retrying refused traffic."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
    cache_path = cache_dir / f"{url_hash}.json"

    if cache_path.exists():
        mtime = cache_path.stat().st_mtime
        is_fresh = (time.time() - mtime) < 3600  # 1 hour
        if is_fresh:
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    response = _ctia_get(session, url)
    try:
        data = response.json()
    except ValueError as exc:
        raise CTIAFetchError(f"CTIA returned invalid JSON for {url}") from exc
    cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def _download_ctia_image(session: requests.Session, url: str, image_dir: Path, filename: str) -> str:
    """Download one explicitly requested CTIA image under the same request limit."""
    image_dir.mkdir(parents=True, exist_ok=True)
    filepath = image_dir / filename
    response = _ctia_get(session, url)
    filepath.write_bytes(response.content)
    return str(filepath)


def clean_chinese_val(val_str: str, unit: str) -> float | str:
    val_str = val_str.replace(",", "").strip()
    match = re.search(r"(\d+\.?\d*)", val_str)
    if not match:
        return ""
    val = float(match.group(1))
    if "万元" in unit:
        val *= 10000
    return val


def extract_tungsten_chinese(html_text: str) -> dict:
    text = BeautifulSoup(html_text, "html.parser").get_text("\n")
    patterns = {
        "wolframite_concentrate": r"65%黑钨精矿价格([\d,.]+)\s*(万元/标吨|元/吨|元/吨度)",
        "scheelite_concentrate": r"65%白钨精矿价格([\d,.]+)\s*(万元/标吨|元/吨|元/吨度)",
        "apt": r"仲钨酸铵.*?价格([\d,.]+)\s*(万元/吨|元/吨)",
        "european_apt": r"欧洲APT价格([\d,.-]+)\s*(美元/吨度|美元/mtu)",
        "tungsten_powder": r"钨粉价格([\d,.]+)\s*(元/千克|元/kg|元/吨)",
        "tungsten_carbide_powder": r"碳化钨粉价格([\d,.]+)\s*(元/千克|元/kg|元/吨)",
        "ferrotungsten": r"(?:70%?|70)?钨铁价格([\d,.]+)\s*(万元/吨|元/吨)",
        "cobalt_powder": r"钴粉价格([\d,.]+)\s*(元/千克|元/kg|元/吨)",
        "scrap_carbide_rod": r"废钨棒材价格([\d,.]+)\s*(元/千克|元/kg|元/吨)"
    }
    extracted = {}
    for field, regex in patterns.items():
        match = re.search(regex, text)
        if match:
            extracted[field] = clean_chinese_val(match.group(1), match.group(2))
        else:
            extracted[field] = ""
    return extracted


def extract_molybdenum_chinese(html_text: str) -> dict:
    text = _normalize_moly_text(html_text)
    extracted = {k: "" for k in MOLY_PRICE_FIELDS}

    moly_products = {
        "molybdenum_concentrate": ["钼精矿"],
        "ferromolybdenum": ["钼铁"],
        "ammonium_heptamolybdate": ["七钼酸铵"],
        "ammonium_tetramolybdate": ["四钼酸铵"]
    }

    clauses = re.split(r"[。；\n]", text)
    for clause in clauses:
        if "分别" not in clause:
            continue
        mentions = []
        for field, keywords in moly_products.items():
            for kw in keywords:
                idx = clause.find(kw)
                if idx != -1:
                    mentions.append((idx, field))
                    break
        mentions.sort()

        price_pattern = re.compile(r"([\d,.]+)\s*(元/吨度|元/吨|元/千克|元/kg)")
        matches = list(price_pattern.finditer(clause))

        if len(mentions) == len(matches) and len(mentions) > 0:
            for (_, field), match in zip(mentions, matches):
                val = clean_chinese_val(match.group(1), match.group(2))
                if val != "" and _valid_moly_value(field, float(val)):
                    extracted[field] = val

    direct_patterns = {
        "molybdenum_concentrate": r"钼精矿.*?报价在?([\d,.]+)\s*(元/吨度|元/吨)",
        "ferromolybdenum": r"钼铁.*?报价在?([\d,.]+)\s*(元/吨|元/千克)",
        "ammonium_heptamolybdate": r"七钼酸铵.*?报价在?([\d,.]+)\s*(元/吨|元/千克)",
        "ammonium_tetramolybdate": r"四钼酸铵.*?报价在?([\d,.]+)\s*(元/吨|元/千克)"
    }
    for field, regex in direct_patterns.items():
        if extracted[field] == "":
            match = re.search(regex, text)
            if match:
                val = clean_chinese_val(match.group(1), match.group(2))
                if val != "" and _valid_moly_value(field, float(val)):
                    extracted[field] = val

    return extracted


def _parse_chinese_moly_ocr(text: str) -> dict:
    extracted = {}
    lines = text.splitlines()

    patterns = {
        "molybdenum_concentrate": (r"(?:40-45%|钼精矿)", (3000.0, 7000.0)),
        "ferromolybdenum": (r"(?:Mo60|钼铁)", (150000.0, 450000.0)),
        "ammonium_heptamolybdate": (r"(?:hept|七钼|CHER|CHR)", (150000.0, 450000.0)),
        "ammonium_tetramolybdate": (r"(?:tetr|四钼|DOHB|DOHBSER)", (150000.0, 450000.0))
    }

    for field, (regex, bounds) in patterns.items():
        extracted[field] = ""
        for line in lines:
            line_no_spaces = line.replace(" ", "")
            match = re.search(regex, line_no_spaces, re.IGNORECASE)
            if not match:
                match = re.search(regex, line, re.IGNORECASE)
            if match:
                num_matches = re.findall(r"[\d,.]+", line)
                found = False
                for num_str in reversed(num_matches):
                    raw_val = _clean_ocr_number(num_str)
                    if raw_val is not None:
                        low, high = bounds
                        if low <= raw_val <= high:
                            extracted[field] = raw_val
                            found = True
                            break
                if found:
                    break
    return extracted


def _run_tesseract_ocr_moly_china(image_path: Path) -> dict:
    try:
        image_path = Path(image_path).resolve()
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
            return _parse_chinese_moly_ocr(ocr_text)
    except Exception as exc:
        _log(f"  Tesseract OCR execution failed (Moly China): {exc}")
    return {}


def _parse_rare_earth_ocr(text: str) -> dict:
    extracted = {}
    lines = text.splitlines()

    patterns = {
        "lanthanum_oxide": (r"(?:La2O3|LaQ03|La203|氧化镧)", (1_000.0, 100_000.0)),
        "cerium_oxide": (r"(?:Ce2O3|Ce203|氧化铈)", (1_000.0, 100_000.0)),
        "praseodymium_oxide": (r"(?:Pr6O11|Pr6011|氧化镨)", (100_000.0, 5_000_000.0)),
        "neodymium_oxide": (r"(?:Nd2O3|Nd203|氧化钕)", (100_000.0, 5_000_000.0)),
        "samarium_oxide": (r"(?:Sm2O3|Sm203|氧化钐)", (100_000.0, 5_000_000.0)),
        "europium_oxide": (r"(?:Eu2O3|Eu203|氧化铕)", (100_000.0, 5_000_000.0)),
        "gadolinium_oxide": (r"(?:Gd2O3|Gd203|氧化钆)", (100_000.0, 5_000_000.0)),
        "terbium_oxide": (r"(?:Tb4O7|Tb407|氧化铽)", (100_000.0, 15_000_000.0)),
        "dysprosium_oxide": (r"(?:Dy2O3|Dy203|氧化镝)", (100_000.0, 5_000_000.0)),
        "holmium_oxide": (r"(?:Ho2O3|Ho203|氧化钬)", (100_000.0, 5_000_000.0)),
        "erbium_oxide": (r"(?:Er2O3|Er203|Ex203|氧化铒)", (100_000.0, 5_000_000.0)),
        # Word boundaries prevent Y203 from matching inside dysprosium's Dy203.
        "yttrium_oxide": (r"(?:\bY2O3\b|\bY203\b|氧化钇)", (100_000.0, 5_000_000.0)),
    }

    for field, (regex, bounds) in patterns.items():
        extracted[field] = ""
        for line in lines:
            line_no_spaces = line.replace(" ", "")
            match = re.search(regex, line_no_spaces, re.IGNORECASE)
            if not match:
                match = re.search(regex, line, re.IGNORECASE)
            if match:
                num_matches = re.findall(r"[\d,.]+", line)
                found = False
                for num_str in reversed(num_matches):
                    raw_val = _clean_ocr_number(num_str)
                    if raw_val is not None:
                        low, high = bounds
                        if raw_val * 1000.0 >= low and raw_val * 1000.0 <= high:
                            raw_val *= 1000.0
                        if low <= raw_val <= high:
                            extracted[field] = raw_val
                            found = True
                            break
                if found:
                    break
    return extracted


def _run_tesseract_ocr_ree(image_path: Path) -> dict:
    try:
        image_path = Path(image_path).resolve()
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
            return _parse_rare_earth_ocr(ocr_text)
    except Exception as exc:
        _log(f"  Tesseract OCR execution failed (REE): {exc}")
    return {}


def _find_ctia_price_image_url(body_html: str, keywords: list[str]) -> str | None:
    soup = BeautifulSoup(body_html, "html.parser")
    for img in soup.find_all("img"):
        src = img.get("src", "")
        alt = img.get("alt", "")
        img_title = img.get("title", "")
        haystack = " ".join([src, alt, img_title]).lower()
        if any(kw in haystack for kw in keywords):
            if any(blocked in haystack for blocked in ("trend", "chart", "average", "wechat")):
                continue
            return src
    return None


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

        title_lower = title.lower()
        is_moly = "molybdenum" in title_lower
        is_ree = "rare earth" in title_lower

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
        elif is_ree:
            # Thin version: text-only, no OCR fallback yet (see module docstring).
            prices = extract_rare_earth_prices_from_body(body.get_text())
            _flag_suspicious_ree_prices(prices, context=date_str)
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
                prefix = "molybdenum" if is_moly else ("rare_earth" if is_ree else "tungsten")
                if "trend" in filename or "trend" in alt.lower() or "trend" in img_title.lower():
                    trend_img_local = download_image(
                        session, full_src_url, image_dir, f"{prefix}_trend_{date_str}.jpg"
                    )
                elif "price" in filename or "price" in alt.lower() or "price" in img_title.lower():
                    table_img_local = download_image(
                        session, full_src_url, image_dir, f"{prefix}_price_table_{date_str}.jpg"
                    )

        prices["date"] = date_str
        prices["source"] = "chinatungsten"
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


def _source_from_url(url: str | None) -> str:
    host = urllib.parse.urlparse(url or "").netloc.lower()
    if host == "www.ctia.com.cn":
        return "ctia"
    if host == "news.chinatungsten.com":
        return "chinatungsten"
    return ""


def _ensure_raw_csv_schema(csv_path: Path, headers: list[str]) -> None:
    """Add explicit source provenance to legacy raw files without losing rows."""
    if not csv_path.exists():
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=headers).writeheader()
        return

    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        existing_headers = reader.fieldnames or []
        rows = list(reader)
    if existing_headers == headers:
        return

    temp_path = csv_path.with_suffix(".tmp")
    with temp_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            normalized = {column: row.get(column, "") for column in headers}
            normalized["source"] = row.get("source") or _source_from_url(row.get("url"))
            writer.writerow(normalized)
    temp_path.replace(csv_path)


def _has_price_values(row: dict, fields: list[str]) -> bool:
    return any(row.get(field) not in ("", None) for field in fields)


def write_processed_snapshot(base_dir: Path, csv_path: Path, dataset_name: str, fields: list[str]) -> Path | None:
    """Write a normalized, dashboard-friendly snapshot to the `latest` partition."""
    if not csv_path.exists():
        return None
    frame = pd.read_csv(csv_path)
    if frame.empty:
        return None
    keep = ["date", *fields, "source", "title", "url"]
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
    if mineral_type in ("molybdenum", "rare_earth") and any(
        blocked in title for blocked in ("price trend", "trends", "average")
    ):
        return False
    return True


def _classify_article_link(a_tag) -> tuple[str, str] | None:
    """Classify a listing <a> tag as (full_url, mineral_type), or None if not a
    daily price article we track."""
    title = a_tag.text.strip().lower()
    href = a_tag.get("href", "")

    is_ree = "rare earth" in title and _is_daily_price_article_title(title, "rare_earth")
    is_tungsten = (
        not is_ree
        and ("tungsten" in title or "apt" in title)
        and _is_daily_price_article_title(title, "tungsten")
    )
    is_moly = not is_ree and "molybdenum" in title and _is_daily_price_article_title(title, "molybdenum")

    full_url = urllib.parse.urljoin(BASE_URL, href)
    if is_ree:
        return (full_url, "rare_earth")
    if is_tungsten:
        return (full_url, "tungsten")
    if is_moly:
        return (full_url, "molybdenum")
    return None


def _fetch_category_article_links(
    session: requests.Session, category_url: str, page: int
) -> list[tuple[str, str]] | None:
    """Fetch one listing page and return classified (url, mineral_type) links.

    Returns None (rather than []) on an HTTP failure, so callers can distinguish
    "stop paginating" from "this page had no matching articles"."""
    start = page * 10
    url = f"{category_url}?start={start}" if start > 0 else category_url
    _log(f"Fetching category page {page + 1}: {url}")
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        _log(f"Failed to fetch {url}, status {response.status_code}")
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    articles = soup.find_all("div", class_="contentpaneopen") or soup.find_all("h2", class_="contentheading")
    links: list[tuple[str, str]] = []
    for art in articles:
        heading = art.find("h2", class_="contentheading") if art.name != "h2" else art
        if not heading:
            continue
        a_tag = heading.find("a")
        if not a_tag:
            continue
        classified = _classify_article_link(a_tag)
        if classified is not None:
            links.append(classified)
    return links


def scrape_ctia_range(
    base_dir: str | Path = ".",
    *,
    max_pages: int = 3,
    with_images: bool = False,
    session: requests.Session | None = None,
    since_date: str | None = None,
    since_days: int | None = None,
) -> int:
    base_dir = Path(base_dir)
    data_dir = base_dir / "data" / "raw" / "minerals_signal_data"
    data_dir.mkdir(parents=True, exist_ok=True)

    tungsten_csv_path = data_dir / "tungsten_chinatungsten.csv"
    moly_csv_path = data_dir / "molybdenum_chinatungsten.csv"
    ree_csv_path = data_dir / "rare_earth_chinatungsten.csv"
    image_dir = data_dir / "images"
    # CTIA refusals must end the run rather than trigger transparent retries.
    session = session or build_session(retries=0)
    cutoff = _resolve_since_date(since_date=since_date, since_days=since_days)

    cutoff_msg = f", since={cutoff.date()}" if cutoff is not None else ""
    _log(f"Scraping CTIA WP REST API (max_pages={max_pages}{cutoff_msg})...")

    existing_tungsten_dates, existing_tungsten_urls = _load_existing(tungsten_csv_path)
    existing_moly_dates, existing_moly_urls = _load_existing(moly_csv_path)
    existing_ree_dates, existing_ree_urls = _load_existing(ree_csv_path)

    _ensure_raw_csv_schema(tungsten_csv_path, CSV_HEADERS)
    _ensure_raw_csv_schema(moly_csv_path, MOLY_CSV_HEADERS)
    _ensure_raw_csv_schema(ree_csv_path, REE_CSV_HEADERS)

    categories = [
        (17, "tungsten", tungsten_csv_path, CSV_HEADERS, existing_tungsten_dates, existing_tungsten_urls),
        (18, "molybdenum", moly_csv_path, MOLY_CSV_HEADERS, existing_moly_dates, existing_moly_urls),
        (54, "rare_earth", ree_csv_path, REE_CSV_HEADERS, existing_ree_dates, existing_ree_urls)
    ]

    new_count = 0
    pending_batches: list[tuple[Path, list[str], str, list[dict]]] = []
    # Determine page size based on cutoff to be efficient
    per_page = 100 if cutoff is not None else 10

    for cat_id, mineral_type, csv_path, headers, existing_dates, existing_urls in categories:
        _log(f"Processing category {mineral_type} (ID: {cat_id})...")
        category_new_rows = []
        stop_category = False

        for page in range(1, max_pages + 1):
            if stop_category:
                break
            url = f"https://www.ctia.com.cn/wp-json/wp/v2/posts?categories={cat_id}&per_page={per_page}&page={page}"
            _log(f"Fetching: {url}")
            posts = _get_ctia_url(session, url)
            if not posts:
                _log(f"No posts found for category {mineral_type} page {page}.")
                break

            for post in posts:
                date_str = post["date"][:10]  # Format: YYYY-MM-DD
                link = post["link"]

                # Check cutoff
                if _is_older_than_cutoff(date_str, cutoff):
                    _log(f"Skipping {date_str}: older than cutoff")
                    stop_category = True
                    break

                if link in existing_urls or date_str in existing_dates:
                    continue

                title = post["title"]["rendered"]
                content_html = post["content"]["rendered"]

                # Parse content first, then require at least one valid price value.
                # This avoids treating price commentary and corporate news as prices.
                if not _is_daily_price_article_title(title, mineral_type):
                    continue

                row_data = {h: "" for h in headers}
                row_data["date"] = date_str
                row_data["source"] = "ctia"
                row_data["title"] = title
                row_data["url"] = link

                if mineral_type == "tungsten":
                    extracted = extract_tungsten_chinese(content_html)
                    row_data.update(extracted)
                    _log(f"  Parsed Tungsten {date_str}: APT={row_data.get('apt')}")
                elif mineral_type == "molybdenum":
                    extracted = extract_molybdenum_chinese(content_html)
                    row_data.update(extracted)

                    moly_missing = any(row_data.get(f) in ("", None) for f in MOLY_PRICE_FIELDS)
                    if with_images and moly_missing:
                        img_url = _find_ctia_price_image_url(content_html, ["molybdenum-price", "钼价"])
                        if img_url:
                            _log(f"  [{date_str}] Core moly values missing in text. Downloading image for OCR: {img_url}")
                            ocr_img_local = _download_ctia_image(
                                session, img_url, image_dir, f"temp_moly_ocr_{date_str}.jpg"
                            )
                            if ocr_img_local:
                                ocr_prices = _run_tesseract_ocr_moly_china(Path(ocr_img_local))
                                for k, v in ocr_prices.items():
                                    if v and row_data.get(k) in ("", None):
                                        row_data[k] = v
                                try:
                                    Path(ocr_img_local).unlink()
                                except Exception:
                                    pass
                    _log(f"  Parsed Molybdenum {date_str}: Conc={row_data.get('molybdenum_concentrate')}")
                elif mineral_type == "rare_earth":
                    extracted_text = extract_rare_earth_prices_from_body(content_html)
                    row_data.update(extracted_text)

                    img_url = _find_ctia_price_image_url(content_html, ["rare-earth-price", "稀土价格", "稀土价"])
                    if with_images and img_url:
                        _log(f"  [{date_str}] Downloading Rare Earth price image for OCR: {img_url}")
                        ocr_img_local = _download_ctia_image(
                            session, img_url, image_dir, f"temp_ree_ocr_{date_str}.jpg"
                        )
                        if ocr_img_local:
                            ocr_prices = _run_tesseract_ocr_ree(Path(ocr_img_local))
                            for k, v in ocr_prices.items():
                                if v and row_data.get(k) in ("", None):
                                    row_data[k] = v
                            try:
                                Path(ocr_img_local).unlink()
                            except Exception:
                                pass
                    _log(f"  Parsed Rare Earth {date_str}: Lanthanum={row_data.get('lanthanum_oxide')}, Neodymium={row_data.get('neodymium_oxide')}")

                if not _has_price_values(row_data, [h for h in headers if h not in {"date", "source", "title", "url", "table_image_local", "trend_image_local"}]):
                    _log(f"  Skipping {mineral_type} {date_str}: no validated price fields")
                    continue

                category_new_rows.append(row_data)
                existing_dates.add(date_str)
                existing_urls.add(link)

        if category_new_rows:
            category_new_rows.sort(key=lambda r: r["date"])
            pending_batches.append((csv_path, headers, mineral_type, category_new_rows))

    # Commit raw rows only after every requested CTIA category completed. A refusal
    # therefore leaves historical data untouched instead of publishing a partial run.
    for csv_path, headers, mineral_type, rows in pending_batches:
        with csv_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in headers})
        new_count += len(rows)
        _log(f"Wrote {len(rows)} new {mineral_type} records.")

    write_processed_snapshot(base_dir, tungsten_csv_path, PROCESSED_DATASET, PRICE_FIELDS)
    write_processed_snapshot(base_dir, moly_csv_path, MOLY_PROCESSED_DATASET, MOLY_PRICE_FIELDS)
    write_processed_snapshot(base_dir, ree_csv_path, REE_PROCESSED_DATASET, REE_PRICE_FIELDS)

    _log(f"Done. {new_count} new record(s).")
    return new_count


def scrape_range(
    base_dir: str | Path = ".",
    *,
    max_pages: int = 3,
    with_images: bool = False,
    session: requests.Session | None = None,
    since_date: str | None = None,
    since_days: int | None = None,
    source: str = "chinatungsten",
) -> int:
    if source == "ctia":
        return scrape_ctia_range(
            base_dir=base_dir,
            max_pages=max_pages,
            with_images=with_images,
            session=session,
            since_date=since_date,
            since_days=since_days,
        )
    """Scrape category pages, append new dated rows, and refresh the processed snapshots."""
    base_dir = Path(base_dir)
    data_dir = base_dir / "data" / "raw" / "minerals_signal_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    tungsten_csv_path = data_dir / "tungsten_chinatungsten.csv"
    moly_csv_path = data_dir / "molybdenum_chinatungsten.csv"
    ree_csv_path = data_dir / "rare_earth_chinatungsten.csv"
    image_dir = data_dir / "images"
    session = session or build_session()
    cutoff = _resolve_since_date(since_date=since_date, since_days=since_days)

    cutoff_msg = f", since={cutoff.date()}" if cutoff is not None else ""
    _log(f"Scraping up to {max_pages} category pages (images={'on' if with_images else 'off'}{cutoff_msg})...")
    existing_tungsten_dates, existing_tungsten_urls = _load_existing(tungsten_csv_path)
    existing_moly_dates, existing_moly_urls = _load_existing(moly_csv_path)
    existing_ree_dates, existing_ree_urls = _load_existing(ree_csv_path)

    _ensure_raw_csv_schema(tungsten_csv_path, CSV_HEADERS)
    _ensure_raw_csv_schema(moly_csv_path, MOLY_CSV_HEADERS)
    _ensure_raw_csv_schema(ree_csv_path, REE_CSV_HEADERS)

    new_count = 0
    # Two independent listings: the general product-news page (tungsten + molybdenum,
    # and occasionally rare-earth for a day or two) and the dedicated rare-earth-news
    # category (the reliable source for REE history/backfill).
    for category_url in (CATEGORY_URL, REE_CATEGORY_URL):
        for page in range(max_pages):
            try:
                article_links = _fetch_category_article_links(session, category_url, page)
                if article_links is None:
                    break

                if not article_links:
                    _log("No matching articles found on this page.")
                    continue

                page_new_tungsten: list[dict] = []
                page_new_moly: list[dict] = []
                page_new_ree: list[dict] = []

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
                        if not _has_price_values(data, PRICE_FIELDS):
                            _log(f"Skipping Tungsten {date_str}: no validated price fields")
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
                        if not _has_price_values(data, MOLY_PRICE_FIELDS):
                            _log(f"Skipping Moly {date_str}: no validated price fields")
                            continue
                        _log(f"Scraped Moly {date_str}: Conc={data['molybdenum_concentrate']}")
                        page_new_moly.append(data)
                        existing_moly_dates.add(date_str)
                    elif mineral_type == "rare_earth":
                        if link in existing_ree_urls:
                            continue
                        data = parse_article_page(session, link, image_dir=image_dir, with_images=with_images)
                        existing_ree_urls.add(link)
                        if not data:
                            continue
                        date_str = data["date"]
                        if _is_older_than_cutoff(date_str, cutoff):
                            _log(f"Skipping Rare Earth {date_str}: older than cutoff")
                            continue
                        if date_str in existing_ree_dates:
                            continue
                        if not _has_price_values(data, REE_PRICE_FIELDS):
                            _log(f"Skipping Rare Earth {date_str}: no validated price fields")
                            continue
                        populated = [f for f in REE_PRICE_FIELDS if data.get(f) not in ("", None)]
                        _log(f"Scraped Rare Earth {date_str}: {len(populated)} oxide(s)")
                        page_new_ree.append(data)
                        existing_ree_dates.add(date_str)

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

                if page_new_ree:
                    page_new_ree.sort(key=lambda row: row["date"])
                    with ree_csv_path.open("a", newline="", encoding="utf-8") as handle:
                        writer = csv.DictWriter(handle, fieldnames=REE_CSV_HEADERS)
                        for row in page_new_ree:
                            writer.writerow({k: row.get(k, "") for k in REE_CSV_HEADERS})
                    new_count += len(page_new_ree)
                    _log(f"Wrote {len(page_new_ree)} new rare earth records from page {page + 1}.")

            except Exception as exc:  # noqa: BLE001
                _log(f"Error scraping category page: {exc}")
                break

    t_snapshot = write_processed_snapshot(base_dir, tungsten_csv_path, PROCESSED_DATASET, PRICE_FIELDS)
    m_snapshot = write_processed_snapshot(base_dir, moly_csv_path, MOLY_PROCESSED_DATASET, MOLY_PRICE_FIELDS)
    r_snapshot = write_processed_snapshot(base_dir, ree_csv_path, REE_PROCESSED_DATASET, REE_PRICE_FIELDS)
    if t_snapshot is not None:
        _log(f"Processed Tungsten snapshot: {t_snapshot}")
    if m_snapshot is not None:
        _log(f"Processed Molybdenum snapshot: {m_snapshot}")
    if r_snapshot is not None:
        _log(f"Processed Rare Earth snapshot: {r_snapshot}")

    _log(f"Done. {new_count} new record(s).")
    return new_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape Chinatungsten daily tungsten/molybdenum/rare-earth prices.")
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
