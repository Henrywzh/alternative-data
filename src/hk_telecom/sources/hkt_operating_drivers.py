"""HKT Trust & HKT Limited (6823.HK) Key Operating Drivers & ARPU.

Fetches HKT's own semi-annual results announcements (interim + annual) and
extracts the real "Key Operating Drivers" table plus the postpaid exit ARPU
figure, which HKT discloses only in narrative prose (e.g. "Post-paid exit
ARPU for December 2025 rose by 1% to HK$195, up from HK$193 for December
2024"), not as a table field:
- Mobile Postpaid & Prepaid Subscribers ('000s)
- Consumer Broadband Access Lines ('000s)
- Pay-TV Installed Base ('000s)
- Mobile Postpaid Exit ARPU (HK$) -- narrative-text regex extraction
- FTTH connections ('000s) & FTTH share (%) -- also narrative-only

Discovery: HKT's investor-relations "Financial Results" page embeds a Next.js
__NEXT_DATA__ JSON blob listing every historical results announcement PDF by
year. We fetch the English variant of that page and pull the most recent
Annual Results Announcement and Interim Results Announcement links from it,
rather than hardcoding a dated PDF URL (which goes stale every reporting
period -- confirmed dead by testing the URL recorded in an earlier research
pass: it 302-redirected instead of serving the PDF).

This replaces a prior implementation that returned a fully hardcoded,
unsourced Python list dressed up as a "fetch" -- no HTTP request was made at
all. That fabricated-data bug is exactly the failure mode this pipeline must
avoid.
"""

from __future__ import annotations

import io
import json
import logging
import re

import pandas as pd
import pdfplumber
import requests

from ..config import DEFAULT_HEADERS, HKT_IR_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

HKT_FINANCIAL_RESULTS_URL = "https://www.hkt.com/en/about-hkt/investor-relations/financial-results/"
HKT_ASSET_BASE_URL = "https://www.hkt.com/api-service/assets/"

SCHEMA_COLUMNS = [
    "period",
    "date",
    "mobile_postpaid_subscribers_thousands",
    "mobile_prepaid_subscribers_thousands",
    "total_mobile_subscribers_thousands",
    "consumer_broadband_lines_thousands",
    "ftth_connections_thousands",
    "ftth_share_pct",
    "pay_tv_installed_base_thousands",
    "mobile_postpaid_arpu_hkd",
]


def _discover_latest_filings() -> list[tuple[str, str]]:
    """Return [(label, pdf_url), ...] for the most recent Annual and Interim
    Results Announcements, parsed out of HKT's own financial-results index
    page (not hardcoded)."""
    resp = requests.get(HKT_FINANCIAL_RESULTS_URL, headers=DEFAULT_HEADERS, timeout=20)
    resp.raise_for_status()
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.S)
    if not match:
        raise RuntimeError("HKT financial-results page: __NEXT_DATA__ block not found.")
    data = json.loads(match.group(1))
    groups = data["props"]["pageProps"]["pageData"]["c04Content"]

    filings: list[tuple[str, str]] = []
    # groups[0] is the most recent year-range bucket; its first two `content`
    # entries are the latest Annual and Interim results periods.
    for period_group in groups[0]["content"][:2]:
        label = period_group.get("title", "")
        for item in period_group.get("items", []):
            title = item.get("title", "")
            href = item.get("href", "")
            if "Results Announcement" in title and "Webcast" not in title and href.endswith(".pdf"):
                filings.append((f"{label} / {title}", HKT_ASSET_BASE_URL + href))
                break
    return filings


def _extract_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def _parse_key_operating_drivers(text: str) -> dict[str, dict[str, float]]:
    """Parse the 'KEY OPERATING DRIVERS' table. Handles both the interim
    layout (3 date columns: prior-year H1, prior-year H2, current H1/H2) and
    the annual layout (4 columns: H1/H2 x 2 years). Returns
    {period_label: {field: value}}."""
    idx = text.find("KEY OPERATING DRIVERS")
    if idx == -1:
        return {}
    block = text[idx: idx + 2500]
    lines = block.splitlines()

    # Header lines: either "30 Jun 31 Dec 30 Jun ..." + "2024 2024 2025 ..."
    # (interim) or "2024 2025 Better/" + "H1 H2 H1 H2 y-o-y" (annual).
    periods: list[str] = []
    header_lines = lines[1:4]
    joined_header = " ".join(header_lines)
    day_month_matches = re.findall(r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", joined_header)
    year_matches = re.findall(r"\b(20\d{2})\b", joined_header)
    h1h2_matches = re.findall(r"\bH1\b|\bH2\b", joined_header)

    month_abbr_to_num = {
        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
        "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
    }
    if day_month_matches and year_matches and len(year_matches) >= len(day_month_matches):
        for (day, mon), yr in zip(day_month_matches, year_matches):
            periods.append(f"{yr}-{month_abbr_to_num[mon]}-{day.zfill(2)}")
    elif h1h2_matches and year_matches:
        # annual layout: years listed once each, H1/H2 listed per year
        expanded_years = []
        for yr in year_matches:
            expanded_years.extend([yr, yr])
        for half, yr in zip(h1h2_matches, expanded_years):
            month_day = "06-30" if half == "H1" else "12-31"
            periods.append(f"{yr}-{month_day}")

    if not periods:
        return {}

    label_to_field = {
        "retail consumer broadband access lines": "consumer_broadband_lines_thousands",
        "mobile subscribers": "total_mobile_subscribers_thousands",
        "post-paid subscribers": "mobile_postpaid_subscribers_thousands",
        "prepaid subscribers": "mobile_prepaid_subscribers_thousands",
        "pay tv installed base": "pay_tv_installed_base_thousands",
    }

    result: dict[str, dict[str, float]] = {p: {} for p in periods}
    for line in lines:
        low = line.lower()
        field = None
        for label, mapped in label_to_field.items():
            if label in low:
                field = mapped
                break
        if field is None:
            continue
        # Strip the "(’000)" / "('000)" unit marker first -- its literal
        # "000" digits would otherwise be picked up as a spurious leading
        # value token and shift every real column by one.
        tail = re.sub(r"\(.?000\)", "", line)
        tokens = re.findall(r"\(?-?[\d,]+\.?\d*\)?%?", tail)
        values = []
        for tok in tokens:
            if "%" in tok:
                continue
            neg = tok.startswith("(") and tok.endswith(")")
            num = tok.strip("()").replace(",", "")
            try:
                v = float(num)
            except ValueError:
                continue
            values.append(-v if neg else v)
        for period, value in zip(periods, values):
            result[period][field] = value

    return result


def _parse_arpu_narrative(text: str) -> dict[str, float]:
    """Extract postpaid exit ARPU figures from narrative prose, e.g.
    'Post-paid exit ARPU for December 2025 rose by 1% to HK$195, up from
    HK$193 for December 2024.' Returns {YYYY-MM-DD: arpu_hkd}."""
    out: dict[str, float] = {}
    pattern = re.compile(
        r"Post-paid exit ARPU for (\w+ \d{4})[^.]*?to HK\$([\d.]+),\s*up from HK\$([\d.]+) for (\w+ \d{4})",
        re.I,
    )
    month_num = {m: f"{i+1:02d}" for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"])}

    def _to_date(month_year: str) -> str | None:
        parts = month_year.split()
        if len(parts) != 2:
            return None
        mon, yr = parts
        mon_key = mon.capitalize()
        if mon_key not in month_num:
            return None
        day = "30" if month_num[mon_key] == "06" else "31"
        return f"{yr}-{month_num[mon_key]}-{day}"

    for m in pattern.finditer(text):
        cur_period, cur_val, prior_val, prior_period = m.groups()
        cur_date = _to_date(cur_period)
        prior_date = _to_date(prior_period)
        if cur_date:
            out[cur_date] = float(cur_val)
        if prior_date:
            out[prior_date] = float(prior_val)
    return out


def _parse_ftth_narrative(text: str) -> dict[str, tuple[float, float]]:
    """Extract FTTH connections ('000, i.e. millions*1000) and FTTH share (%)
    from narrative prose. Returns {YYYY-MM-DD: (ftth_thousands, share_pct)}."""
    out: dict[str, tuple[float, float]] = {}
    conn_pattern = re.compile(
        r"FTTH.{0,20}connections\s+reached\s+([\d.]+)\s+million\s+at\s+the\s+end\s+of\s+(\w+\s+\d{4})",
        re.I,
    )
    share_pattern = re.compile(
        r"FTTH\s*connections\s+(?:represented|accounted for)\s+(\d+)%\s+of", re.I,
    )
    month_num = {m: f"{i+1:02d}" for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"])}

    conn_match = conn_pattern.search(text)
    share_match = share_pattern.search(text)
    if conn_match:
        millions, month_year = conn_match.groups()
        mon, yr = month_year.split()
        mon_key = mon.capitalize()
        if mon_key in month_num:
            day = "30" if month_num[mon_key] == "06" else "31"
            date_key = f"{yr}-{month_num[mon_key]}-{day}"
            share_pct = float(share_match.group(1)) if share_match else None
            out[date_key] = (float(millions) * 1000.0, share_pct)
    return out


def fetch_hkt_operating_drivers() -> pd.DataFrame:
    """Fetch and normalize HKT key operating drivers and ARPU from HKT's own
    live results announcements (discovered dynamically, not hardcoded)."""
    filings = _discover_latest_filings()
    if not filings:
        raise RuntimeError("Could not discover any HKT results announcement filings.")

    merged: dict[str, dict[str, float]] = {}
    fetched_urls = []
    for label, url in filings:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
        resp.raise_for_status()
        fetched_urls.append(url)
        text = _extract_text(resp.content)

        drivers = _parse_key_operating_drivers(text)
        for period, fields in drivers.items():
            merged.setdefault(period, {}).update(fields)

        arpu = _parse_arpu_narrative(text)
        for period, value in arpu.items():
            merged.setdefault(period, {})["mobile_postpaid_arpu_hkd"] = value

        ftth = _parse_ftth_narrative(text)
        for period, (thousands, share_pct) in ftth.items():
            merged.setdefault(period, {})["ftth_connections_thousands"] = thousands
            if share_pct is not None:
                merged[period]["ftth_share_pct"] = share_pct

    if not merged:
        raise RuntimeError(
            "Fetched HKT results announcement(s) but could not parse any Key "
            "Operating Drivers or ARPU figures -- filing structure may have changed."
        )

    rows = []
    for period, fields in sorted(merged.items()):
        row = {"period": period, "date": period, **fields}
        rows.append(row)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for col in SCHEMA_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    raw_path = save_raw_snapshot(
        "hkt_operating_drivers",
        df.to_dict(orient="records"),
        file_ext="json",
        source_url=", ".join(fetched_urls) or HKT_IR_URL,
    )

    result = df[SCHEMA_COLUMNS].sort_values("date").reset_index(drop=True)
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = fetched_urls[0] if fetched_urls else HKT_IR_URL
    return result
