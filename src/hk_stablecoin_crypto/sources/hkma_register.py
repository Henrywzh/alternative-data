"""HKMA Licensed Stablecoin Issuers Register Source.

Confirmed 2 licensees as of 2026-07-26:
  - Anchorpoint Financial Limited (FRS01, effective 10/04/2026)
    — JV of Standard Chartered + Animoca Brands + HKT, targeting HKD-pegged HKDAP.
  - HSBC (The Hongkong and Shanghai Banking Corporation Limited) (FRS02, effective 10/04/2026)

NAMING COLLISION: "Anchorpoint" (this licensee) ≠ "AnchorX" (Jinyong Investment /
01328.HK, targeting AxCNH pegged to offshore RMB). They are completely different
companies. Do not conflate.

Access: pandas.read_html() works on this page. However, the page must be fetched
via requests with a User-Agent header first — bare urllib gets a different response
shape that may fail. We fetch with requests then pass the HTML to read_html.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, HKMA_REGISTER_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = ["issuer", "licence_number", "effective_date", "fetched_at"]

# Substring patterns to detect each logical column from the actual (long) table headers.
# HKMA's table uses verbose merged header cells that render as long strings after read_html.
_ISSUER_HINTS = ["licensee", "name", "company"]
_LICENCE_HINTS = ["licence", "license", "number", "frs"]
_DATE_HINTS = ["effective", "date"]


def _pick_col(columns: list[str], hints: list[str]) -> str | None:
    """Return the first column name that contains any of the hint substrings."""
    cols_lower = [c.lower() for c in columns]
    for col, col_lower in zip(columns, cols_lower):
        if any(h in col_lower for h in hints):
            return col
    return None


def fetch_licensed_issuers() -> pd.DataFrame:
    """Fetch HKMA register of licensed stablecoin issuers.

    Fetches the page with requests (to send a proper User-Agent), then passes
    the HTML to pandas.read_html() for table extraction. Column names use fuzzy
    matching because HKMA's table headers are long descriptive strings.
    """
    now_str = datetime.now(timezone.utc).isoformat()

    try:
        resp = requests.get(HKMA_REGISTER_URL, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        html = resp.text

        save_raw_snapshot("hkma_register_html", html.encode(), file_ext="html", source_url=HKMA_REGISTER_URL)

        tables = pd.read_html(io.StringIO(html))
        if not tables:
            logger.warning("No tables found on HKMA register page.")
            return pd.DataFrame(columns=SCHEMA_COLUMNS)

        df = tables[0].copy()

        # Flatten any MultiIndex columns from merged headers
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [" ".join(str(v) for v in col if str(v) != "nan").strip() for col in df.columns]

        cols = list(df.columns)

        issuer_col = _pick_col(cols, _ISSUER_HINTS)
        licence_col = _pick_col(cols, _LICENCE_HINTS)
        date_col = _pick_col(cols, _DATE_HINTS)

        if not issuer_col or not licence_col or not date_col:
            logger.warning(
                "HKMA register column mapping failed. Found cols: %s. "
                "issuer=%s, licence=%s, date=%s",
                cols, issuer_col, licence_col, date_col,
            )
            return pd.DataFrame(columns=SCHEMA_COLUMNS)

        result = pd.DataFrame({
            "issuer": df[issuer_col],
            "licence_number": df[licence_col],
            "effective_date": df[date_col],
            "fetched_at": now_str,
        })

        # Drop any all-NaN rows (can appear from merged header rows)
        result = result.dropna(subset=["issuer"]).reset_index(drop=True)

        if len(result) != 2:
            logger.info(
                "HKMA register now has %d issuers — was 2 as of 2026-07-26. "
                "Update expected_count if this is a real new licensee.",
                len(result),
            )

        save_raw_snapshot(
            "hkma_register",
            result.to_dict(orient="records"),
            file_ext="json",
            source_url=HKMA_REGISTER_URL,
        )
        return result[SCHEMA_COLUMNS]

    except Exception:
        logger.exception("Failed to fetch HKMA register.")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
