"""SFC Licensed VATP Register Source.

As of 2026-07-26, 14 licensed VATPs including OSL (15/12/2020) and HashKey (09/11/2022).

IMPORTANT REGULATORY DISTINCTION:
  - "Licensed exchange operators" (appear on the SFC VATP list): OSL, HashKey.
  - "Licensed to deal in virtual assets" (brokerage-side): Guotai Junan International,
    Victory Securities — these do NOT appear on the VATP list; it's a different,
    lesser regulatory status. Do not conflate them.

Access: The SFC page returns HTTP 403 to bare urllib / pandas.read_html() without
a User-Agent header. We fetch with requests first, then pass the HTML to read_html.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, SFC_VATP_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

STATUS_TABLE_ORDER = ["licensed", "pending", "withdrawn", "forced_closure"]
SCHEMA_COLUMNS = ["platform_name", "status", "licensed_date", "fetched_at"]

# Junk/header artifact strings in HTML tables
INVALID_PLATFORM_NAMES = {
    "nan",
    "english",
    "chinese",
    "- -",
    "-",
    "",
    "company_name_of_virtual_asset_trading_platform_operator",
    "ce_reference",
}


def fetch_vatp_register() -> pd.DataFrame:
    """Fetch SFC VATP register (all 4 status tables).

    The SFC page blocks bare urllib with HTTP 403. We fetch with requests
    (which sends a proper User-Agent) then pass the HTML to pandas.read_html().
    """
    now_str = datetime.now(timezone.utc).isoformat()

    try:
        resp = requests.get(SFC_VATP_URL, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        html = resp.text

        save_raw_snapshot("sfc_vatp_register_html", html.encode(), file_ext="html", source_url=SFC_VATP_URL)

        tables = pd.read_html(io.StringIO(html))
    except Exception:
        logger.exception("Failed to fetch SFC VATP register")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    if len(tables) < 1:
        logger.warning("SFC VATP register: no tables found.")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    if len(tables) < 4:
        logger.warning("SFC VATP register: expected ≥4 tables, found %d. Proceeding with what's available.", len(tables))

    dfs = []
    for i, status in enumerate(STATUS_TABLE_ORDER):
        if i >= len(tables):
            break

        df = tables[i].copy()

        # Flatten MultiIndex if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [" ".join(str(v) for v in col if str(v) != "nan").strip() for col in df.columns]

        df.columns = df.columns.str.lower().str.strip().str.replace(r"\s+", "_", regex=True)

        # Find the platform name column (longest name-like column)
        platform_col = next(
            (c for c in df.columns if any(kw in c for kw in ["platform", "operator", "company"])),
            df.columns[0] if len(df.columns) > 0 else None,
        )
        if platform_col is None:
            logger.warning("SFC VATP: could not find platform name column in '%s' table. Cols: %s", status, list(df.columns))
            continue

        df = df.rename(columns={platform_col: "platform_name"})

        date_col = next((c for c in df.columns if "date" in c and c != "platform_name"), None)
        if date_col:
            df = df.rename(columns={date_col: "licensed_date"})
        else:
            df["licensed_date"] = None

        df["status"] = status
        df["fetched_at"] = now_str

        # Clean platform_name string and filter out header/placeholder artifacts
        names_str = df["platform_name"].astype(str).str.strip()
        names_lower = names_str.str.lower()

        valid_mask = (
            ~names_lower.isin(INVALID_PLATFORM_NAMES)
            & ~names_lower.str.startswith("company name")
            & ~names_lower.str.startswith("ce reference")
        )
        df = df[valid_mask].copy()

        for col in SCHEMA_COLUMNS:
            if col not in df.columns:
                df[col] = None

        if not df.empty:
            dfs.append(df[SCHEMA_COLUMNS])

    if not dfs:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    result = pd.concat(dfs, ignore_index=True)

    save_raw_snapshot(
        "sfc_vatp_register",
        result.to_dict(orient="records"),
        file_ext="json",
        source_url=SFC_VATP_URL,
    )
    return result
