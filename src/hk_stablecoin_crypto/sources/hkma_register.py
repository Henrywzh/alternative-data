"""HKMA Licensed Stablecoin Issuers Register Source.

Confirmed 2 licensees as of 2026-07-26:
  - Anchorpoint Financial Limited (FRS01, effective 10/04/2026)
    — JV of Standard Chartered + Animoca Brands + HKT, targeting HKD-pegged HKDAP.
  - HSBC (The Hongkong and Shanghai Banking Corporation Limited) (FRS02, effective 10/04/2026)

NAMING COLLISION: "Anchorpoint" (this licensee) ≠ "AnchorX" (Jinyong Investment /
01328.HK, targeting AxCNH pegged to offshore RMB). They are completely different
companies. Do not conflate.

Access: pandas.read_html() works on this page when fetched via requests with a User-Agent.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, HKMA_REGISTER_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = ["issuer", "licence_number", "effective_date", "fetched_at"]


def _pick_col(columns: list[str], hints: list[str], exclude: list[str] | None = None) -> str | None:
    """Return the first column name that contains any hint substring and no excluded substring."""
    exclude = exclude or []
    for col in columns:
        col_lower = col.lower()
        if any(ex in col_lower for ex in exclude):
            continue
        if any(h in col_lower for h in hints):
            return col
    return None


def fetch_licensed_issuers() -> pd.DataFrame:
    """Fetch HKMA register of licensed stablecoin issuers.

    Fetches the page with requests (to send a proper User-Agent), then passes
    the HTML to pandas.read_html() for table extraction.
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

        # Match columns precisely without picking 'licensee' for licence_number
        issuer_col = _pick_col(
            cols,
            ["name of licensee", "licensee", "issuer"],
            exclude=["licence number", "license number", "licence_number"],
        )
        licence_col = _pick_col(
            cols,
            ["licence number", "license number", "frs"],
            exclude=["address", "principal place", "name of licensee"],
        )
        date_col = _pick_col(cols, ["effective date", "effective"])

        # Fallbacks by column index if fuzzy match failed
        if not issuer_col and len(cols) > 0:
            issuer_col = cols[0]
        if not licence_col and len(cols) > 3:
            licence_col = cols[3]
        if not date_col and len(cols) > 4:
            date_col = cols[4]

        if not issuer_col or not licence_col or not date_col:
            logger.warning(
                "HKMA register column mapping failed. Found cols: %s. "
                "issuer=%s, licence=%s, date=%s",
                cols, issuer_col, licence_col, date_col,
            )
            return pd.DataFrame(columns=SCHEMA_COLUMNS)

        # Clean issuer column: strip out inline address string (e.g., 'Anchorpoint ... Address: 6/F ...')
        raw_issuers = df[issuer_col].astype(str)
        clean_issuers = raw_issuers.str.split(r"\s*Address:", regex=True).str[0].str.strip()

        result = pd.DataFrame({
            "issuer": clean_issuers,
            "licence_number": df[licence_col].astype(str).str.strip(),
            "effective_date": df[date_col].astype(str).str.strip(),
            "fetched_at": now_str,
        })

        # Drop any all-NaN/empty rows
        result = result.dropna(subset=["issuer"]).reset_index(drop=True)
        result = result[result["issuer"] != ""]

        if len(result) != 2:
            logger.info(
                "HKMA register now has %d issuers — was 2 as of 2026-07-26.",
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
