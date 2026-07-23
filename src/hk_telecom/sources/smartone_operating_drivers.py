"""SmarTone Telecommunications Holdings Limited (0315.HK) Operating Drivers.

SmarTone is separately HKEX-listed (not privatised) and discloses its own
mobile postpaid subscriber count and postpaid ARPU trend, plus a 5G-vs-4G
ARPU ratio, in its semi-annual Interim/Annual Results Presentation slide
decks. SmarTone's fiscal year ends 30 June, so the "interim" period covers
the six months ended 31 December.

Discovery: SmarTone's own investor-relations results index lists each
period's presentation PDF at a deterministic URL:
    https://www.smartoneholdings.com/about/investor/results/english/
        <calendar_year>_interim_present.pdf   (six months ended 31 Dec)
        <calendar_year>_annual_present.pdf    (year ended 30 Jun)
Verified working for both the current and prior fiscal year. We probe the
current and previous 1-2 calendar years for both interim/annual variants
rather than hardcoding a single dated filename, since a new filing appears
under a new URL every reporting period.

Note: SmarTone's disclosure does not include an explicit "5G penetration
rate" percentage in its most recent decks (unlike the FY25 interim deck an
earlier research pass had reviewed) -- that field is intentionally omitted
here rather than carried forward from a stale filing or fabricated.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone

import pandas as pd
import pdfplumber
import requests

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SMARTONE_RESULTS_BASE_URL = "https://www.smartoneholdings.com/about/investor/results/english/"

SCHEMA_COLUMNS = [
    "period",
    "date",
    "postpaid_subscribers_thousands",
    "postpaid_arpu_hkd",
    "arpu_5g_to_4g_ratio",
]

_PERIOD_RE = re.compile(r"(Jun|Dec)-(\d{2})")


def _period_label_to_date(mon: str, yy: str) -> str:
    year = 2000 + int(yy)
    return f"{year}-06-30" if mon == "Jun" else f"{year}-12-31"


def _candidate_urls() -> list[str]:
    now = datetime.now(timezone.utc)
    years = [now.year, now.year - 1, now.year + 1]
    urls = []
    for y in years:
        urls.append(f"{SMARTONE_RESULTS_BASE_URL}{y}_interim_present.pdf")
        urls.append(f"{SMARTONE_RESULTS_BASE_URL}{y}_annual_present.pdf")
    return urls


def _extract_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def _parse_presentation(text: str) -> list[dict]:
    rows: dict[str, dict] = {}

    arpu_idx = text.find("Mobile Postpaid ARPU")
    if arpu_idx != -1:
        window = text[arpu_idx: arpu_idx + 400]
        arpu_values = re.findall(r"\$([\d,]+)", window)
        periods = _PERIOD_RE.findall(window)
        for (mon, yy), val in zip(periods, arpu_values):
            date_key = _period_label_to_date(mon, yy)
            rows.setdefault(date_key, {})["postpaid_arpu_hkd"] = float(val.replace(",", ""))

        ratio_match = re.search(r"(\d+)x[\s\S]{0,80}?4G ARPU", window)
        ratio = float(ratio_match.group(1)) if ratio_match else None
    else:
        ratio = None

    cust_idx = text.find("Customer Number")
    if cust_idx != -1:
        window = text[cust_idx: cust_idx + 400]
        cust_values = re.findall(r"\b(\d{1,3}(?:,\d{3})+)\b", window)
        periods = _PERIOD_RE.findall(window)
        for (mon, yy), val in zip(periods, cust_values):
            date_key = _period_label_to_date(mon, yy)
            rows.setdefault(date_key, {})["postpaid_subscribers_thousands"] = float(val.replace(",", ""))

    if ratio is not None:
        # apply the ratio to the latest (most recent) period found
        if rows:
            latest = max(rows.keys())
            rows[latest]["arpu_5g_to_4g_ratio"] = ratio

    return [{"period": k, "date": k, **v} for k, v in rows.items()]


def fetch_smartone_operating_drivers() -> pd.DataFrame:
    """Fetch and normalize SmarTone (0315.HK) postpaid subscriber/ARPU KPIs
    from its own live results presentation PDFs."""
    merged: dict[str, dict] = {}
    fetched_urls: list[str] = []

    for url in _candidate_urls():
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
        except requests.RequestException as exc:
            logger.info("SmarTone candidate URL failed: %s (%s)", url, exc)
            continue
        if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
            continue

        try:
            text = _extract_text(resp.content)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("SmarTone PDF at %s failed to parse: %s", url, exc)
            continue

        parsed_rows = _parse_presentation(text)
        if not parsed_rows:
            continue

        fetched_urls.append(url)
        for row in parsed_rows:
            merged.setdefault(row["period"], {}).update(row)

    if not merged:
        raise RuntimeError(
            "Could not fetch/parse any SmarTone results presentation from the "
            "candidate URL set -- check SmarTone's investor-relations results "
            "page for a URL pattern change."
        )

    rows = sorted(merged.values(), key=lambda r: r["period"])
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for col in SCHEMA_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    raw_path = save_raw_snapshot(
        "smartone_operating_drivers",
        df.to_dict(orient="records"),
        file_ext="json",
        source_url=", ".join(fetched_urls),
    )

    result = df[SCHEMA_COLUMNS].sort_values("date").reset_index(drop=True)
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = fetched_urls[0] if fetched_urls else SMARTONE_RESULTS_BASE_URL
    return result
