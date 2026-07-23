"""Cathay Pacific & HKIA Monthly Aviation Traffic Statistics.

Ingests CAD HKIA Monthly Airport Traffic Excel workbook (Stat Webpage.xlsx) and
Cathay Pacific Group monthly traffic figures announcements (PDF, filed on Cathay's
own investor-relations site under a deterministic URL pattern):
- HKIA Aircraft Movements, Passenger Volume, Freight Tonnage
- Cathay Pacific Passengers carried, ASK ('000), RPK ('000), Passenger Load Factor (%)

Cathay traffic source: Cathay's investor-relations announcements are published each
month at a predictable URL:
    https://www.cathaypacific.com/content/dam/cx/about-us/investor-relations/
        announcements/en/<YYYYMM>_cx_traffic_en.pdf
where <YYYYMM> is the *announcement* month; the traffic figures inside are always
for the *prior* calendar month (e.g. the PDF published as 202607 contains June 2026
data, released ~22 July 2026). This has been verified working (200 OK, correct
content) across multiple months, so no discovery/crawl step is needed -- we just
construct and fetch each candidate month directly. This replaces an earlier
implementation that used a hardcoded, unsourced dict of "historical" Cathay figures
instead of fetching real data.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone

import pandas as pd
import pdfplumber
import requests

from ..config import CAD_HKIA_XLSX_URL, DEFAULT_HEADERS
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

CATHAY_PDF_URL_TEMPLATE = (
    "https://www.cathaypacific.com/content/dam/cx/about-us/investor-relations/"
    "announcements/en/{yyyymm}_cx_traffic_en.pdf"
)

# How many announcement months (going backward from the current month) to probe.
CATHAY_LOOKBACK_MONTHS = 24
# Stop early once this many consecutive 404s have been seen (bounds runtime once
# we've walked back past the start of Cathay's published PDF history).
CATHAY_MAX_CONSECUTIVE_MISSES = 3


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """Shift (year, month) by delta months (delta may be negative)."""
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, idx % 12 + 1


def _clean_number(val: str) -> float:
    cleaned = re.sub(r"[^\d.\-]", "", val or "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _find_metric_table(tables: list[list[list[str | None]]]) -> list[list[str | None]] | None:
    for table in tables:
        if table and table[0] and table[0][0] and "CATHAY PACIFIC" in str(table[0][0]).upper():
            return table
    return None


def _parse_cathay_pdf(content: bytes, month_key: str) -> dict | None:
    """Parse a single Cathay traffic-figures PDF into the metrics we track."""
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        table = None
        for page in pdf.pages:
            tables = page.extract_tables()
            table = _find_metric_table(tables)
            if table:
                break

    if not table:
        logger.warning("Cathay traffic PDF for %s: no CATHAY PACIFIC table found.", month_key)
        return None

    metrics: dict[str, float] = {}
    for row in table[1:]:
        if not row or not row[0]:
            continue
        label = " ".join(row[0].split()).lower()
        value = row[1] if len(row) > 1 else None
        if value is None:
            continue
        if "available seat kilometres" in label:
            metrics["cathay_ask_thousands"] = _clean_number(value)
        elif "revenue passenger kilometres" in label:
            metrics["cathay_rpk_thousands"] = _clean_number(value)
        elif "passengers carried" in label:
            metrics["cathay_passengers"] = _clean_number(value)
        elif "passenger load factor" in label:
            metrics["cathay_passenger_load_factor_pct"] = _clean_number(value)

    required = {"cathay_ask_thousands", "cathay_rpk_thousands", "cathay_passengers", "cathay_passenger_load_factor_pct"}
    if not required.issubset(metrics.keys()):
        logger.warning("Cathay traffic PDF for %s: missing fields %s", month_key, required - metrics.keys())
        return None

    return metrics


def _fetch_cathay_monthly() -> pd.DataFrame:
    """Fetch Cathay Group monthly traffic figures by walking back through the
    deterministic per-month PDF URL pattern until data runs out."""
    now = datetime.now(timezone.utc)
    ann_year, ann_month = now.year, now.month

    rows: list[dict] = []
    consecutive_misses = 0

    for offset in range(CATHAY_LOOKBACK_MONTHS):
        y, m = _add_months(ann_year, ann_month, -offset)
        yyyymm = f"{y:04d}{m:02d}"
        url = CATHAY_PDF_URL_TEMPLATE.format(yyyymm=yyyymm)

        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=20)
        except requests.RequestException as exc:
            logger.warning("Cathay traffic fetch error for %s: %s", yyyymm, exc)
            consecutive_misses += 1
            if rows and consecutive_misses >= CATHAY_MAX_CONSECUTIVE_MISSES:
                break
            continue

        if resp.status_code != 200:
            consecutive_misses += 1
            if rows and consecutive_misses >= CATHAY_MAX_CONSECUTIVE_MISSES:
                break
            continue

        # Traffic figures inside the PDF are for the prior calendar month.
        data_year, data_month = _add_months(y, m, -1)
        month_key = f"{data_year:04d}-{data_month:02d}"

        metrics = _parse_cathay_pdf(resp.content, month_key)
        if metrics is None:
            consecutive_misses += 1
            if rows and consecutive_misses >= CATHAY_MAX_CONSECUTIVE_MISSES:
                break
            continue

        consecutive_misses = 0
        rows.append({"month": month_key, "source_pdf_url": url, **metrics})

    if not rows:
        logger.warning("No Cathay traffic figures parsed from any candidate PDF URL.")
        return pd.DataFrame(columns=["month", "cathay_passengers", "cathay_rpk_thousands", "cathay_ask_thousands", "cathay_passenger_load_factor_pct"])

    df = pd.DataFrame(rows).drop_duplicates(subset=["month"]).sort_values("month").reset_index(drop=True)

    raw_path = save_raw_snapshot(
        "cathay_traffic_pdf",
        df.to_dict(orient="records"),
        file_ext="json",
        source_url=CATHAY_PDF_URL_TEMPLATE,
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
