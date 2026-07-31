#!/usr/bin/env python3
"""
Production Scraper: HK Transport Department Passenger Journeys (Table 2.1)
Source: Hong Kong Transport Department Monthly Traffic and Transport Digest
Output: data/processed/transport/hk_passenger_journeys_monthly.parquet

Table 2.1 spans two sheets (T2.1(a): franchised buses + rail; T2.1(b): public
light buses + ferries + taxis + MTR feeder buses + the true grand total), and
every group of columns is stored as merged Excel cells, so a naive
`row.iloc[N]` read hits an empty continuation cell roughly as often as it
hits real data -- and when it does hit data, a one-column shift silently
attaches the wrong operator's numbers to the wrong label. An earlier version
of this script did exactly that: every output column held a different
operator's data than its own name claimed (confirmed against a fresh fetch:
the column named MTR heavy rail held KMB's bus figures, "total" held
Citybus's own subtotal, two columns were entirely empty). See the arithmetic
validation at the bottom of parse_sheet() and merge_sheets() for how this is
now caught rather than silently repeated: every subtotal TD publishes is
independently recomputed from its stated parts and compared, and the two
sheets' own six-way sum is checked against TD's own grand total. A future
column-layout change that isn't caught by the header-keyword check would
still be caught here, because a shifted column cannot coincidentally
reproduce five independent sum identities across both sheets.
"""

from __future__ import annotations

import io
import os
import re
import ssl
import sys
import urllib.request

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "transport")
os.makedirs(DATA_DIR, exist_ok=True)
OUTPUT_PARQUET = os.path.join(DATA_DIR, "hk_passenger_journeys_monthly.parquet")

DIGEST_INDEX_URL = (
    "https://www.td.gov.hk/en/transport_in_hong_kong/transport_figures/"
    "monthly_traffic_and_transport_digest/index.html"
)
FALLBACK_TABLE21_URL = "https://www.td.gov.hk/filemanager/en/content_5404/table21.xls"

# column index -> (output field, required header keyword). The keyword is
# searched across every populated cell in that column's header block (rows
# 0-9), so it is robust to which exact row a wrapped label lands in, but it
# still pins the label to an absolute column index -- a shifted layout fails
# this check rather than silently mapping to the wrong field.
SHEET_A_COLUMNS = {
    2: ("kmb_k", "KMB"),
    4: ("citybus_franchise_hk_xht_unt_k", "Citybus"),
    6: ("citybus_franchise_airport_nlantau_k", "N. Lantau"),
    8: ("citybus_subtotal_k", "小計"),  # 小計 = subtotal (not 總計/grand total)
    10: ("nwfb_k", "NWFB"),
    12: ("lwb_k", "LWB"),
    14: ("nlb_k", "NLB"),
    16: ("bus_subtotal_k", "小計"),
    18: ("mtr_heavy_rail_k", "MTR Lines"),
    20: ("airport_express_k", "AEL"),
    22: ("light_rail_k", "Light Rail"),
    24: ("tramways_k", "Tramways"),
    26: ("rail_subtotal_k", "小計"),
}
SHEET_B_COLUMNS = {
    2: ("gmb_k", "GMB"),
    4: ("rmb_k", "RMB"),
    6: ("plb_subtotal_k", "小計"),
    8: ("sun_ferry_k", "Sun Ferry"),
    10: ("star_ferry_k", "Ferry"),
    12: ("other_ferry_k", "Other Licensed"),
    14: ("ferry_subtotal_k", "小計"),
    16: ("taxis_k", "Taxis"),
    18: ("residents_services_k", "Residents"),
    20: ("mtr_buses_k", "MTR Buses"),
    22: ("total_k", "總計"),  # 總計 = grand total (distinct from 小計/subtotal)
    24: ("avg_daily_k", "Average"),
}

TOLERANCE = 0.5  # thousands of journeys; source rows are given to 3 decimals


def _fetch(opener, url: str, headers: dict) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=20) as resp:
        return resp.read()


def _header_text(df: pd.DataFrame, col: int, nrows: int = 10) -> str:
    if col >= df.shape[1]:
        return ""
    return " ".join(str(v).replace("\n", " ") for v in df.iloc[0:nrows, col] if pd.notnull(v))


def _validate_headers(df: pd.DataFrame, expected: dict[int, tuple[str, str]], sheet_label: str) -> None:
    missing = []
    for col, (_field, keyword) in expected.items():
        if keyword not in _header_text(df, col):
            missing.append(f"col {col} (expected {keyword!r})")
    if missing:
        raise RuntimeError(
            f"{sheet_label}: header layout no longer matches the expected column "
            f"positions -- {'; '.join(missing)}. Re-derive SHEET_*_COLUMNS from a "
            f"fresh fetch before trusting this data."
        )


def _safe_float(v) -> float | None:
    if pd.isnull(v):
        return None
    text = str(v).replace(",", "").strip()
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        print(f"  warning: could not parse numeric value {v!r}", file=sys.stderr)
        return None


def parse_sheet(df_raw: pd.DataFrame, columns: dict[int, tuple[str, str]]) -> pd.DataFrame:
    records = []
    current_year = None
    for _, row in df_raw.iterrows():
        val0 = str(row.iloc[0]).strip() if pd.notnull(row.iloc[0]) else ""
        val1 = str(row.iloc[1]).strip() if pd.notnull(row.iloc[1]) else ""

        if val0.isdigit() and len(val0) == 4:
            current_year = int(val0)
            month_str = val1
        elif current_year and (val1.isdigit() or val0.isdigit()):
            month_str = val1 if val1.isdigit() else val0
        else:
            continue

        if not month_str.isdigit():
            continue
        month_num = int(month_str)
        if not 1 <= month_num <= 12:
            continue

        rec = {"date": f"{current_year}-{month_num:02d}", "year": current_year, "month": month_num}
        for col, (field, _keyword) in columns.items():
            rec[field] = _safe_float(row.iloc[col]) if col < len(row) else None
        records.append(rec)

    return pd.DataFrame(records).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)


def _check_identity(df: pd.DataFrame, parts: list[str], total: str, label: str) -> None:
    """Recompute a TD-published subtotal from its own stated parts.

    NWFB folded into Citybus partway through the series and reports "-"
    (None) from then on; treated as 0 here only for this arithmetic check,
    never written to the output, since "no longer separately reported" and
    "reported zero passengers" are not the same fact.
    """
    computed = df[parts].astype(float).fillna(0.0).sum(axis=1)
    reported = df[total]
    bad = df[(reported.notna()) & ((computed - reported).abs() > TOLERANCE)]
    if not bad.empty:
        raise RuntimeError(
            f"{label} does not reconcile with its own parts on {len(bad)} row(s) "
            f"(tolerance {TOLERANCE}); this is the arithmetic guard tripping, which "
            f"means a column has drifted from what SHEET_*_COLUMNS assumes:\n"
            f"{bad[['date', total] + parts].to_string(index=False)}"
        )


def merge_sheets(df_a: pd.DataFrame, df_b: pd.DataFrame) -> pd.DataFrame:
    merged = df_a.merge(df_b.drop(columns=["year", "month"]), on="date", how="inner")

    _check_identity(merged, ["citybus_franchise_hk_xht_unt_k", "citybus_franchise_airport_nlantau_k"],
                     "citybus_subtotal_k", "Citybus subtotal")
    _check_identity(merged, ["kmb_k", "citybus_subtotal_k", "lwb_k", "nlb_k", "nwfb_k"],
                     "bus_subtotal_k", "Franchised-bus subtotal")
    _check_identity(merged, ["mtr_heavy_rail_k", "airport_express_k", "light_rail_k", "tramways_k"],
                     "rail_subtotal_k", "Rail subtotal")
    _check_identity(merged, ["gmb_k", "rmb_k"], "plb_subtotal_k", "Public-light-bus subtotal")
    _check_identity(merged, ["sun_ferry_k", "star_ferry_k", "other_ferry_k"], "ferry_subtotal_k", "Ferry subtotal")
    # The cross-sheet identity: TD's own grand total (sheet b) must equal the
    # sum of every mode reported across both sheets. This is the strongest
    # check here, since a column shift in either sheet independently would
    # have to coincidentally preserve this six-way sum to slip past it.
    _check_identity(
        merged,
        ["bus_subtotal_k", "rail_subtotal_k", "plb_subtotal_k", "ferry_subtotal_k",
         "taxis_k", "residents_services_k", "mtr_buses_k"],
        "total_k", "Grand total (cross-sheet)",
    )
    return merged


def main() -> int:
    print("=========================================================================")
    print("  SCRAPING HK TRANSPORT DEPT: PASSENGER JOURNEYS (TABLE 2.1)           ")
    print("=========================================================================")

    ctx = ssl._create_unverified_context()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

    try:
        html = _fetch(opener, DIGEST_INDEX_URL, headers).decode("utf-8", errors="ignore")
        months = sorted(re.findall(r"/monthly_traffic_and_transport_digest/(\d{4}/\d{6})/index\.html", html))
        month_url = (
            f"https://www.td.gov.hk/en/transport_in_hong_kong/transport_figures/"
            f"monthly_traffic_and_transport_digest/{months[-1]}/index.html"
        )
        m_html = _fetch(opener, month_url, headers).decode("utf-8", errors="ignore")
        t21_links = re.findall(r'href="([^"]*table21\.xls)"', m_html, re.I)
        t21_url = t21_links[0] if t21_links else FALLBACK_TABLE21_URL
        if not t21_url.startswith("http"):
            t21_url = "https://www.td.gov.hk" + t21_url
    except Exception as exc:
        print(f"  digest-page discovery failed ({exc}); using fallback URL", file=sys.stderr)
        t21_url = FALLBACK_TABLE21_URL

    print(f"Downloading Table 2.1: {t21_url}")
    content = _fetch(opener, t21_url, headers)
    xl = pd.ExcelFile(io.BytesIO(content))
    if len(xl.sheet_names) != 2:
        raise RuntimeError(
            f"Table 2.1 workbook has {len(xl.sheet_names)} sheets ({xl.sheet_names}); "
            f"expected exactly 2 (franchised-bus/rail, then everything else)."
        )
    sheet_a_name, sheet_b_name = xl.sheet_names[0], xl.sheet_names[1]

    df_a_raw = xl.parse(sheet_a_name, header=None)
    df_b_raw = xl.parse(sheet_b_name, header=None)
    _validate_headers(df_a_raw, SHEET_A_COLUMNS, sheet_a_name)
    _validate_headers(df_b_raw, SHEET_B_COLUMNS, sheet_b_name)

    df_a = parse_sheet(df_a_raw, SHEET_A_COLUMNS)
    df_b = parse_sheet(df_b_raw, SHEET_B_COLUMNS)
    df_out = merge_sheets(df_a, df_b)

    print(f"\nExtracted {len(df_out)} monthly passenger journey records (all identities reconciled).")
    print("Date Range:", df_out["date"].min(), "->", df_out["date"].max())
    print("\nSample Data:")
    print(df_out[["date", "kmb_k", "mtr_heavy_rail_k", "light_rail_k", "total_k"]].tail(10))

    df_out.to_parquet(OUTPUT_PARQUET, index=False)
    print(f"\nSaved output to: {OUTPUT_PARQUET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
