"""Cathay Pacific & HKIA Monthly Aviation Traffic Statistics.

Ingests CAD HKIA Monthly Airport Traffic Excel workbook (Stat Webpage.xlsx) and
Cathay Pacific Group monthly traffic figures announcements (PDF, discovered via
Cathay's own investor-relations announcements archive):
- HKIA Aircraft Movements, Passenger Volume, Freight Tonnage
- Cathay Pacific Passengers carried, ASK ('000), RPK ('000), Passenger Load Factor (%)

Cathay traffic source -- archive discovery, not URL guessing:
Cathay's IR announcements page (https://www.cathaypacific.com/cx/en_HK/
investor-relations/announcements.html) is a client-rendered Next.js page, but it
calls a real JSON API under the hood to list announcements:
    https://www.cathaypacific.com/content/api/content-by-path/cx/about-us/
        investor-relations/announcements/en.data-assets.en_HK.pdf-list.
        <page>.<pageSize>.null.all.JSON
(found via the browser's network panel -- confirmed with plain `requests`, no
headless browser needed at runtime). Each page returns 15 announcements with a
title, a real PDF href, and a filed date; `pageTotal` tells us how many pages to
walk. This is the ONLY reliable way to get real per-month Cathay traffic PDF
links: filenames are NOT deterministic across Cathay's history -- verified (real
curl checks) at least 5 different naming conventions across 2013-2026, e.g.
`20130117_CX_Announcement_traffic_figures_en.pdf`, `201312_cxtraffic_en.pdf`,
`201612_traffic_figures_en.pdf`, `202012_cxtraffic_en_locrechk.pdf`, and the
current `202306_cx_traffic_en.pdf` pattern. Guessing any single URL template
(the previous implementation's approach) silently misses real data outside the
narrow window where that one template happens to hold.

The data *month* is parsed from each announcement's title (e.g. "December 2012
Traffic Figures", "Profit Warning and June 2020 Traffic Figures") rather than
inferred from the filing date, since the filing-date-minus-one-month heuristic
breaks whenever an announcement is filed early/late (e.g. the real "December
2024 Traffic Figures" PDF is named `202501_cx_traffic_en.pdf`, not
`202412_cx_traffic_en.pdf` -- the previous implementation's deterministic
pattern silently treated this as a missing month).

Table layout has three real variants across the full 2013-2026 archive
(verified by downloading and parsing a real sample PDF from each era):
- 2013 through Dec-2024 data (most months): two tables per PDF ("CATHAY
  PACIFIC ... TRAFFIC" and "CATHAY PACIFIC ... CAPACITY", region-by-region
  RPK/ASK breakdown ending in "RPK Total (000)" / "ASK Total (000)" rows,
  plus "Passengers carried" / "Passenger load factor" rows).
- Feb-Dec 2021 data: same two-table structure, but pdfplumber's table
  extraction splits the "CATHAY PACIFIC / CATHAY DRAGON" line off the header
  cell, leaving just "AIRLINES COMBINED TRAFFIC" / "... CAPACITY" -- a real
  PDF-layout quirk, not missing data.
- Jan-2025 data onward: a single consolidated "CATHAY PACIFIC" table with
  spelled-out labels ("Available Seat Kilometres (000)", "Revenue Passenger
  Kilometres (000)", "Passengers carried", "Passenger load factor").
`_parse_cathay_pdf` / `_find_metric_tables` below handle all three.

A handful of PDFs (the COVID-era `_locrechk` filenames) sit behind a securities
"Overseas Persons" disclaimer gate that 302-redirects to an interstitial page;
its accept button just sets a 5-second short-lived cookie
(`Fv9mD36PNgrGjPubQYnagwkMZeKfid`, read from that page's own `main.js`) before
redirecting back -- we set the same cookie ourselves so the direct PDF GET
succeeds without a headless browser.

Downloaded PDFs are cached on disk (data/raw/hk_transport/cathay_pdf_cache/)
keyed by URL, since 2013-2024 PDFs never change once published -- this avoids
re-downloading ~130 months of PDFs on every pipeline run. The announcements
index itself (the JSON API) is still walked fresh on every call since it is
cheap (a few dozen small JSON pages) and the newest 1-2 months do change.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
import requests

from ..config import CAD_HKIA_XLSX_URL, DEFAULT_HEADERS, RAW_DIR
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "date",
    "month",
    "hkia_passengers",
    "hkia_aircraft_movements",
    "hkia_freight_tonnes",
    "cathay_passengers",
    "cathay_rpk_thousands",
    "cathay_ask_thousands",
    "cathay_passenger_load_factor_pct",
]

MONTH_MAP = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}

FULL_MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}

CATHAY_DOMAIN = "https://www.cathaypacific.com"

# Real JSON API backing the announcements archive page (found via the browser
# network panel; the archive page itself is client-rendered Next.js and a
# plain GET on it only returns the nav shell). <page> is 1-indexed, <pageSize>
# is fixed at 15 by the site's own frontend.
CATHAY_ANNOUNCEMENTS_API = (
    "https://www.cathaypacific.com/content/api/content-by-path/cx/about-us/"
    "investor-relations/announcements/en.data-assets.en_HK.pdf-list."
    "{page}.{page_size}.null.all.JSON"
)
CATHAY_ANNOUNCEMENTS_PAGE_SIZE = 15
CATHAY_ANNOUNCEMENTS_MAX_PAGES = 60  # hard safety cap; real archive is ~24 pages

# Matches announcement titles like "December 2012 Traffic Figures",
# "Profit Warning and June 2020 Traffic Figures", "December 2022 Traffic
# Figures, Update on 2022 Full-year Performance and 2023 Outlook" -- the data
# month is always stated in the title itself, which is far more reliable than
# inferring it from the filing date (filing dates shift around, e.g. the real
# "December 2024 Traffic Figures" PDF was filed in January 2025).
_TRAFFIC_TITLE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{4})\s+Traffic Figures",
    re.IGNORECASE,
)

# The disclaimer-gated ("_locrechk") PDFs 302-redirect to an "Overseas
# Persons" securities disclaimer interstitial. Its own main.js sets this
# short-lived (5 second) cookie on "Agree" before redirecting back to the
# originally-requested URL -- setting it ourselves lets us fetch those PDFs
# directly without a headless browser.
CATHAY_DISCLAIMER_COOKIE = ("Fv9mD36PNgrGjPubQYnagwkMZeKfid", "3Mjf5SCNMn6kJgHP5375d5hmUAct65")

CATHAY_PDF_CACHE_DIR = RAW_DIR / "cathay_pdf_cache"
CATHAY_PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _clean_number(val: str) -> float:
    cleaned = re.sub(r"[^\d.\-]", "", val or "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _discover_cathay_traffic_pdfs(session: requests.Session) -> list[dict]:
    """Walk Cathay's real announcements JSON API and return one entry per
    real "Traffic Figures" announcement, keyed by the data month stated in
    its title (not guessed from a URL pattern or inferred from filing date).
    """
    entries_by_month: dict[str, dict] = {}
    page = 1
    page_total = None

    while page <= CATHAY_ANNOUNCEMENTS_MAX_PAGES:
        url = CATHAY_ANNOUNCEMENTS_API.format(page=page, page_size=CATHAY_ANNOUNCEMENTS_PAGE_SIZE)
        try:
            resp = session.get(url, headers=DEFAULT_HEADERS, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Cathay announcements archive page %s failed: %s", page, exc)
            break

        if page_total is None:
            try:
                page_total = int(data.get("pageTotal") or 0)
            except (TypeError, ValueError):
                page_total = 0

        for item in data.get("list", []) or []:
            title = (item.get("title") or "").strip()
            href = item.get("url")
            match = _TRAFFIC_TITLE_RE.search(title)
            if not match or not href:
                continue

            month_name, year_str = match.group(1).lower(), match.group(2)
            month_num = FULL_MONTH_MAP.get(month_name)
            if not month_num:
                continue
            month_key = f"{year_str}-{month_num}"

            is_clarification = "clarification" in title.lower()
            existing = entries_by_month.get(month_key)
            if existing is not None:
                # Prefer a primary (non-clarification) traffic-figures entry
                # over a "Clarification Announcement" amendment for the same
                # month; between two entries of the same kind, keep the one
                # already recorded (the API lists newest-first, so that's the
                # most recently filed one).
                if existing.get("is_clarification") and not is_clarification:
                    pass  # replace the clarification with the primary entry
                else:
                    continue

            entries_by_month[month_key] = {
                "month": month_key,
                "title": title,
                "url": urljoin(CATHAY_DOMAIN, href),
                "filed_date": item.get("date"),
                "is_clarification": is_clarification,
            }

        if not page_total or page >= page_total:
            break
        page += 1

    return sorted(entries_by_month.values(), key=lambda e: e["month"])


def _get_cathay_pdf_bytes(session: requests.Session, url: str) -> bytes | None:
    """Fetch a Cathay traffic-figures PDF, using an on-disk cache keyed by URL
    (these PDFs are immutable once published, so once cached we never need to
    re-download them on a later pipeline run)."""
    cache_name = re.sub(r"[^A-Za-z0-9._-]", "_", url.rsplit("/", 1)[-1])
    cache_path = CATHAY_PDF_CACHE_DIR / cache_name

    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path.read_bytes()

    try:
        resp = session.get(url, headers=DEFAULT_HEADERS, timeout=30, allow_redirects=True)
    except requests.RequestException as exc:
        logger.warning("Cathay traffic PDF fetch error for %s: %s", url, exc)
        return None

    if resp.status_code != 200 or not resp.content:
        logger.warning("Cathay traffic PDF fetch for %s returned status %s", url, resp.status_code)
        return None
    if resp.headers.get("content-type", "").lower().startswith("text/html"):
        # The disclaimer interstitial (or any other non-PDF redirect target).
        logger.warning("Cathay traffic PDF fetch for %s returned HTML, not a PDF.", url)
        return None

    cache_path.write_bytes(resp.content)
    return resp.content


def _find_metric_tables(tables: list[list[list[str | None]]]) -> list[list[list[str | None]]]:
    """Return every table on a page whose header cell identifies it as a
    Cathay Pacific traffic/capacity metrics table. Three real header
    variants were found across the 2013-2026 archive (verified against
    actual downloaded PDFs, not assumed):
    - "CATHAY PACIFIC ... TRAFFIC" / "... CAPACITY" (most of 2013-2024,
      region-by-region breakdown ending in Total rows).
    - "CATHAY PACIFIC" alone (2025 onward, single consolidated table).
    - "AIRLINES COMBINED TRAFFIC" / "... CAPACITY" -- a COVID-era layout
      quirk (real PDFs, Feb-Dec 2021 data) where pdfplumber's table
      extraction splits the "CATHAY PACIFIC / CATHAY DRAGON" line off the
      "AIRLINES COMBINED TRAFFIC/CAPACITY" header cell; same row/column
      structure otherwise, so still safe to parse the same way.
    """
    matches = []
    for table in tables:
        if not table or not table[0] or not table[0][0]:
            continue
        header = str(table[0][0]).upper()
        if header.startswith("CATHAY PACIFIC") or (
            "AIRLINES COMBINED" in header and ("TRAFFIC" in header or "CAPACITY" in header)
        ):
            matches.append(table)
    return matches


def _extract_metrics_from_tables(tables: list[list[list[str | None]]]) -> dict[str, float]:
    """Pull the 4 tracked metrics out of a set of already-identified Cathay
    metric tables (as returned by `_find_metric_tables`). Split out from
    `_parse_cathay_pdf` so the label-matching logic can be unit tested
    against synthetic tables without needing a real PDF fixture per era."""
    metrics: dict[str, float] = {}
    for table in tables:
        for row in table[1:]:
            if not row or not row[0]:
                continue
            label = " ".join(row[0].split()).lower()
            value = row[1] if len(row) > 1 else None
            if value is None:
                continue

            if "available seat kilometres" in label or label.startswith("ask total"):
                metrics["cathay_ask_thousands"] = _clean_number(value)
            elif "revenue passenger kilometres" in label or label.startswith("rpk total"):
                metrics["cathay_rpk_thousands"] = _clean_number(value)
            elif "passengers carried" in label:
                metrics["cathay_passengers"] = _clean_number(value)
            elif "passenger load factor" in label:
                metrics["cathay_passenger_load_factor_pct"] = _clean_number(value)
    return metrics


def _parse_cathay_pdf(content: bytes, month_key: str) -> dict | None:
    """Parse a single Cathay traffic-figures PDF into the metrics we track.

    Handles all three real table layouts found across the 2013-2026 archive
    (see module docstring) via `_find_metric_tables` + `_extract_metrics_from_tables`.
    """
    metrics: dict[str, float] = {}

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            tables = _find_metric_tables(page.extract_tables())
            metrics.update(_extract_metrics_from_tables(tables))

    required = {"cathay_ask_thousands", "cathay_rpk_thousands", "cathay_passengers", "cathay_passenger_load_factor_pct"}
    if not required.issubset(metrics.keys()):
        logger.warning("Cathay traffic PDF for %s: missing fields %s", month_key, required - metrics.keys())
        return None

    return metrics


def _fetch_cathay_monthly() -> pd.DataFrame:
    """Fetch Cathay Group monthly traffic figures by discovering real
    per-month PDF links from Cathay's own announcements archive (rather than
    guessing a URL pattern), then downloading and parsing each one."""
    session = requests.Session()
    session.cookies.set(*CATHAY_DISCLAIMER_COOKIE, domain="www.cathaypacific.com", path="/")

    entries = _discover_cathay_traffic_pdfs(session)
    if not entries:
        logger.warning("No Cathay traffic figures announcements discovered from the archive API.")
        return pd.DataFrame(columns=["month", "cathay_passengers", "cathay_rpk_thousands", "cathay_ask_thousands", "cathay_passenger_load_factor_pct"])

    rows: list[dict] = []
    for entry in entries:
        content = _get_cathay_pdf_bytes(session, entry["url"])
        if content is None:
            continue

        metrics = _parse_cathay_pdf(content, entry["month"])
        if metrics is None:
            continue

        rows.append({"month": entry["month"], "source_pdf_url": entry["url"], **metrics})

    if not rows:
        logger.warning("No Cathay traffic figures parsed from any discovered PDF.")
        return pd.DataFrame(columns=["month", "cathay_passengers", "cathay_rpk_thousands", "cathay_ask_thousands", "cathay_passenger_load_factor_pct"])

    df = pd.DataFrame(rows).drop_duplicates(subset=["month"]).sort_values("month").reset_index(drop=True)

    raw_path = save_raw_snapshot(
        "cathay_traffic_pdf",
        df.to_dict(orient="records"),
        file_ext="json",
        source_url=CATHAY_ANNOUNCEMENTS_API,
    )
    df.attrs["raw_snapshot"] = str(raw_path)
    return df


def fetch_cathay_traffic() -> pd.DataFrame:
    """Fetch CAD HKIA monthly airport traffic workbook and join Cathay Group disclosures."""
    resp = requests.get(CAD_HKIA_XLSX_URL, headers=DEFAULT_HEADERS, timeout=15)
    resp.raise_for_status()

    df_raw = pd.read_excel(io.BytesIO(resp.content), sheet_name="Eng")

    rows = []
    current_year = None

    for idx, row in df_raw.iterrows():
        yr_val = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else None
        mth_val = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else None

        # The workbook contains an annual summary table (Year column filled,
        # Month blank, years 1998-2026) BEFORE the monthly breakdown table
        # (which also starts back at 1998). Only treat a Year cell as
        # starting a new year block when it's paired with a real month value
        # in the same row -- that only happens in the monthly table, at the
        # first month of each year. A prior version of this code updated
        # current_year off a fixed whitelist of "2021".."2026" years alone,
        # which meant it picked up "2026" from the annual table's last row
        # before the monthly table even began, then never reset for years
        # 1998-2020 (not in the whitelist) -- silently mislabeling 1998
        # monthly data as 2026 and (via drop_duplicates keeping the first
        # occurrence) clobbering the real, later 2026 rows entirely.
        if yr_val and re.fullmatch(r"(19|20)\d{2}", yr_val) and mth_val in MONTH_MAP:
            current_year = yr_val

        if current_year and mth_val in MONTH_MAP:
            mth = MONTH_MAP[mth_val]
            month_key = f"{current_year}-{mth}"
            date_key = f"{month_key}-01"

            try:
                # Column layout (verified against a live fetch of the workbook):
                # 0 Year, 1 Month, 2 provisional/revised flag, 3 Landing, 4 Take-off,
                # 5 Total (Aircraft), 6 YoY%, 7 Arrival, 8 Departure, 9 Total (Passenger),
                # 10 YoY%, 11 Unloaded, 12 Loaded, 13 Total (Freight, tonnes), 14 YoY%.
                # NOTE: aircraft movements must come from column 5 ("Total"), not
                # column 4 ("Take-off") -- using Take-off alone understates total
                # movements by roughly half.
                movements = float(row.iloc[5]) if pd.notna(row.iloc[5]) else 0.0
                passengers = float(row.iloc[9]) if pd.notna(row.iloc[9]) else 0.0
                freight = float(row.iloc[13]) if pd.notna(row.iloc[13]) else 0.0

                rows.append({
                    "month": month_key,
                    "date": date_key,
                    "hkia_aircraft_movements": movements,
                    "hkia_passengers": passengers,
                    "hkia_freight_tonnes": freight,
                })
            except Exception:
                continue

    hkia_df = pd.DataFrame(rows)
    if hkia_df.empty:
        logger.warning("No CAD HKIA monthly rows parsed from Excel workbook.")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    hkia_df["date"] = pd.to_datetime(hkia_df["date"])
    hkia_df = hkia_df.drop_duplicates(subset=["month"]).sort_values("date").reset_index(drop=True)

    # Attach Cathay disclosures, fetched live from Cathay's own IR-site PDFs.
    c_df = _fetch_cathay_monthly()

    merged = hkia_df.merge(c_df, on="month", how="left")

    for col in ("cathay_passengers", "cathay_rpk_thousands", "cathay_ask_thousands", "cathay_passenger_load_factor_pct"):
        if col not in merged.columns:
            merged[col] = 0.0
        else:
            merged[col] = merged[col].fillna(0.0)

    # Keep only months where we have both HKIA and Cathay data so the trend chart
    # doesn't show fabricated/zero Cathay figures for months we never fetched.
    merged = merged[merged["cathay_passengers"] > 0].reset_index(drop=True)

    if merged.empty:
        logger.warning("No overlapping HKIA/Cathay months after merge.")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    result = merged[SCHEMA_COLUMNS].sort_values("date").reset_index(drop=True)

    raw_path = save_raw_snapshot(
        "cathay_hkia_traffic",
        result.to_dict(orient="records"),
        file_ext="json",
        source_url=CAD_HKIA_XLSX_URL,
    )
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = CAD_HKIA_XLSX_URL
    return result
