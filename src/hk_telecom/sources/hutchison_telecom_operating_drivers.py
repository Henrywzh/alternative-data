"""Hutchison Telecommunications Hong Kong Holdings Limited (0215.HK, "3 HK")
Key Performance Indicators.

HTHKH is still separately HKEX-listed (66.09% owned by CK Hutchison, not
privatised) and is the operating entity for the "3"/"3 HK" mobile brand. Its
semi-annual (interim/annual) results announcements disclose a materially
richer KPI table than HKT's: postpaid/prepaid customer counts, postpaid
share of total base, monthly postpaid churn rate, postpaid **gross and
net** ARPU, postpaid net AMPU, and 5G penetration rate (the last one is
narrative-only, e.g. "the Group's 5G penetration rate deepened by 6% points
to 57%").

Discovery: HTHKH's own investor-relations results index page lists the
announcement PDFs (hosted on doc.irasia.com) with the most recent filing
first in page order -- we scrape that index rather than hardcoding a dated
filename, since the URL includes an internal HKEX-style document ID that is
not derivable from the period alone.
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd
import pdfplumber
import requests

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

HTHKH_IR_RESULTS_INDEX_URL = "https://www.hthkh.com/en/ir/fin_results.php"

SCHEMA_COLUMNS = [
    "period",
    "date",
    "postpaid_customers_thousands",
    "prepaid_customers_thousands",
    "total_customers_thousands",
    "postpaid_churn_rate_pct",
    "postpaid_gross_arpu_hkd",
    "postpaid_net_arpu_hkd",
    "postpaid_net_ampu_hkd",
    "penetration_5g_pct",
]

_LABEL_TO_FIELD = {
    "number of postpaid customers": "postpaid_customers_thousands",
    "number of prepaid customers": "prepaid_customers_thousands",
    "total customers": "total_customers_thousands",
    "monthly churn rate of postpaid customers": "postpaid_churn_rate_pct",
    "postpaid gross arpu": "postpaid_gross_arpu_hkd",
    "postpaid net arpu": "postpaid_net_arpu_hkd",
    "postpaid net ampu": "postpaid_net_ampu_hkd",
}


def _discover_result_pdf_urls(max_count: int = 4) -> list[str]:
    """Return the most recent results-announcement PDF URLs listed on
    HTHKH's own IR results index page (first-listed = most recent)."""
    resp = requests.get(HTHKH_IR_RESULTS_INDEX_URL, headers=DEFAULT_HEADERS, timeout=20)
    resp.raise_for_status()
    urls = re.findall(r'href="(https://doc\.irasia\.com/listco/hk/hthkh/announcement/[^"]+\.pdf)"', resp.text)
    seen = []
    for u in urls:
        if u not in seen:
            seen.append(u)
        if len(seen) >= max_count:
            break
    return seen


def _extract_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def _parse_kpi_table(text: str) -> dict[str, dict[str, float]]:
    idx = text.find("Key Performance Indicators")
    if idx == -1:
        return {}
    block = text[idx: idx + 1400]
    lines = block.splitlines()
    header = lines[1] if len(lines) > 1 else ""

    periods: list[str] = []
    h1_match = re.findall(r"1H\s*(\d{4})", header)
    if h1_match:
        periods = [f"{yr}-06-30" for yr in h1_match]
    else:
        years = re.findall(r"\b(20\d{2})\b", header)
        periods = [f"{yr}-12-31" for yr in years]

    if not periods:
        return {}

    result: dict[str, dict[str, float]] = {p: {} for p in periods}
    for line in lines:
        low = line.lower()
        field = None
        for label, mapped in _LABEL_TO_FIELD.items():
            if low.startswith(label) or f" {label}" in low[:len(label) + 2]:
                field = mapped
                break
        if field is None:
            continue
        tail = re.sub(r"\(.?000\)|\(HK\$\)|\(%\)", "", line)
        if field == "postpaid_churn_rate_pct":
            # Value columns are unsigned percentages ("0.9%"); the
            # trailing change column is signed ("+0.1% point") -- keep
            # only the unsigned ones, in order.
            values = [float(v) for v in re.findall(r"(?<![+\-])\b(\d+\.\d+)%", tail)]
        else:
            tokens = re.findall(r"-?[\d,]+\.?\d*%?", tail)
            values = []
            for tok in tokens:
                if "%" in tok:
                    continue
                num = tok.replace(",", "")
                try:
                    values.append(float(num))
                except ValueError:
                    continue
        for period, value in zip(periods, values):
            result[period][field] = value

    return result


def _parse_5g_penetration(text: str, periods: list[str]) -> dict[str, float]:
    """Extract 5G penetration rate from narrative prose, e.g. '5G
    penetration\\nrate deepened by 6% points to 57%' (PDF text extraction
    frequently wraps mid-phrase, so whitespace between words is matched
    loosely). The narrative always describes the *current* (most recent)
    reporting period, so the value is attached to max(periods)."""
    out: dict[str, float] = {}
    if not periods:
        return out
    m = re.search(
        r"5G\s+penetration\s+rate\s+\w+\s+(?:by\s+)?[\d.]+%\s*points?\s+to\s+([\d.]+)%",
        text, re.I,
    )
    if not m:
        return out
    current_period = max(periods)
    out[current_period] = float(m.group(1))
    return out


def fetch_hutchison_telecom_operating_drivers() -> pd.DataFrame:
    """Fetch and normalize Hutchison Telecom HK Holdings (0215.HK) KPIs from
    its own live results announcements."""
    urls = _discover_result_pdf_urls()
    if not urls:
        raise RuntimeError("Could not discover any HTHKH results announcement filings.")

    merged: dict[str, dict] = {}
    fetched_urls = []
    for url in urls:
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("HTHKH filing fetch failed for %s: %s", url, exc)
            continue

        text = _extract_text(resp.content)
        kpis = _parse_kpi_table(text)
        if not kpis:
            continue
        fetched_urls.append(url)
        for period, fields in kpis.items():
            merged.setdefault(period, {}).update(fields)

        penetration = _parse_5g_penetration(text, list(kpis.keys()))
        for period, value in penetration.items():
            merged.setdefault(period, {})["penetration_5g_pct"] = value

    if not merged:
        raise RuntimeError(
            "Fetched HTHKH filing(s) but could not parse any Key Performance "
            "Indicators -- filing structure may have changed."
        )

    rows = [{"period": p, "date": p, **fields} for p, fields in sorted(merged.items())]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for col in SCHEMA_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    raw_path = save_raw_snapshot(
        "hutchison_telecom_operating_drivers",
        df.to_dict(orient="records"),
        file_ext="json",
        source_url=", ".join(fetched_urls),
    )

    result = df[SCHEMA_COLUMNS].sort_values("date").reset_index(drop=True)
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = fetched_urls[0] if fetched_urls else HTHKH_IR_RESULTS_INDEX_URL
    return result
