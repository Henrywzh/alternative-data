"""Monthly traffic data scraper for China's major listed airlines:
1. Air China (中国国航, 601111.SH / 00753.HK)
2. China Southern (中国南方航空, 600029.SH / 01055.HK)
3. China Eastern (中国东方航空, 600115.SH / 00670.HK)
4. Spring Airlines (春秋航空, 601021.SH - LCC Benchmark)

Queries Cninfo API for monthly "运营数据" announcements, downloads PDFs,
caches them locally in data/raw/airline_pdfs/, parses tables using pdfplumber,
and outputs standardized time series to data/processed/airline_traffic/china_airlines_monthly.parquet.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
import pdfplumber

CNINFO_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

# "searchkey" is a tuple: Cninfo's search API filters server-side on this
# value, more narrowly than a plain title substring check -- it does not
# treat "运营数据" and "经营数据" as interchangeable even though both are
# accepted by the client-side title filter below. China Eastern renamed its
# monthly bulletin from "运营数据" to "经营数据" for Dec 2016 - Mar 2019
# (reverting afterward), and a single-searchkey query silently returned zero
# announcements for that whole window -- confirmed by querying Cninfo
# directly with each keyword and diffing the results. Querying every known
# title variant and merging by month closes that gap.
AIRLINES = [
    {"name": "Air China", "name_cn": "中国国航", "code": "601111", "org_id": "9900000441", "searchkey": ("主要运营数据",)},
    {"name": "China Southern", "name_cn": "中国南方航空", "code": "600029", "org_id": "gssh0600029", "searchkey": ("主要运营数据",)},
    {"name": "China Eastern", "name_cn": "中国东方航空", "code": "600115", "org_id": "gssh0600115", "searchkey": ("运营数据", "经营数据")},
    {"name": "Spring Airlines", "name_cn": "春秋航空", "code": "601021", "org_id": "9900023129", "searchkey": ("主要运营数据",)},
]


def _clean_val(val: str) -> float:
    if not val:
        return 0.0
    cleaned = re.sub(r"[^\d.\-]", "", val.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def fetch_announcements(code: str, org_id: str, searchkey: str, start_year: str = "2015-01-01") -> list[dict]:
    """Fetch all monthly operating data announcements from Cninfo with full pagination."""
    ctx = ssl._create_unverified_context()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

    results = []
    seen_months = set()
    page = 1
    has_more = True

    while has_more and page <= 15:
        form_data = {
            "pageNum": page,
            "pageSize": 30,
            "column": "sse",
            "tabName": "fulltext",
            "stock": f"{code},{org_id}",
            "searchkey": searchkey,
            "plate": "sse",
            "startDate": start_year,
            "endDate": dt.date.today().isoformat(),
            "isStock": "true",
        }
        encoded_data = urllib.parse.urlencode(form_data).encode("utf-8")
        req = urllib.request.Request(CNINFO_QUERY_URL, data=encoded_data, headers=HEADERS)

        try:
            with opener.open(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                announcements = data.get("announcements") or []
                has_more = data.get("hasMore", False)

                for ann in announcements:
                    title = re.sub(r"<[^>]+>", "", ann.get("announcementTitle", ""))
                    adj_url = ann.get("adjunctUrl", "")
                    if ("运营数据" in title or "经营数据" in title) and adj_url:
                        pdf_url = f"http://static.cninfo.com.cn/{adj_url}"
                        month_match = re.search(r"(\d{4})年(\d{1,2})月", title)
                        if month_match:
                            yr, mth = month_match.group(1), int(month_match.group(2))
                            month_key = f"{yr}-{mth:02d}"
                            if month_key not in seen_months:
                                seen_months.add(month_key)
                                results.append({
                                    "month": month_key,
                                    "title": title,
                                    "url": pdf_url,
                                })
                page += 1
                time.sleep(0.05)
        except Exception as exc:
            print(f"  Error fetching announcements page {page} for {code}: {exc}")
            break

    return sorted(results, key=lambda x: x["month"])


def download_pdf(url: str, cache_dir: Path) -> bytes | None:
    """Download PDF file with local caching."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = url.rsplit("/", 1)[-1]
    cache_path = cache_dir / filename

    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path.read_bytes()

    ctx = ssl._create_unverified_context()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})

    try:
        with opener.open(req, timeout=20) as resp:
            content = resp.read()
            cache_path.write_bytes(content)
            return content
    except Exception as exc:
        print(f"  Error downloading PDF {url}: {exc}")
        return None


# Every carrier's monthly PDF packs several distinct capacity/traffic metrics
# into one table -- e.g. Air China's has ATK, ASK, AFTK (capacity) and RTK,
# RPK, RFTK, passenger count, cargo tonnage, plus 2-3 load-factor variants
# (traffic), all as sibling header rows. Only ASK / RPK / passengers /
# passenger load factor are wanted here; the rest (ATK, AFTK, RTK, RFTK,
# cargo tonnage, cargo/combined load factor, aircraft-type breakdown tables)
# must never be mistaken for one of those four, since a wrong-but-confident
# label is worse than a gap. Keywords below were verified directly against
# live PDFs from all 4 carriers (2026-07), checked pairwise for substring
# collisions between the target list and every ignore-worthy header seen.
# "可利用客公里" is China Southern's own pre-2019-03 ASK header (座 seat ->
# 客 passenger); it switched to "可利用座公里", matching every other carrier,
# from March 2019 onward. Without it, every China Southern PDF before that
# date silently drops its whole ASK breakdown.
_ASK_KEYWORDS = ("可用座位公里", "可利用座公里", "可用座公里", "可利用客公里")
_RPK_KEYWORDS = ("收入客公里", "客运人公里", "旅客周转量")
_PASSENGERS_KEYWORDS = ("乘客人数", "载客人数", "载运旅客人次", "总载运人次")
_LOAD_FACTOR_KEYWORDS = ("客座利用率", "客座率")

# Generic table column-header row repeated at the top of every page a table
# spans (e.g. Spring Airlines' PDFs run 3 pages; pdfplumber yields a separate
# "table" per page, each starting with this same header row). It carries no
# metric/region information, so unlike a genuine unrecognized metric header
# it must NOT reset the active section -- otherwise a metric whose region
# rows happen to straddle a page break (confirmed: Spring Airlines' ASK
# International/Regional rows landed on the page after this repeat, right
# after Domestic) silently loses its remaining rows.
_TABLE_HEADER_REPEAT_MARKERS = ("指标",)

_REGION_MAP = {
    "国内": "Domestic", "－国内航线": "Domestic", "国内航线": "Domestic",
    "其中: 国内航线": "Domestic", "其中：国内航线": "Domestic",
    "国际": "International", "－国际航线": "International", "国际航线": "International",
    "其中: 国际航线": "International", "其中：国际航线": "International",
    "地区": "Regional", "－地区航线": "Regional", "地区航线": "Regional",
    "其中: 地区航线": "Regional", "其中：地区航线": "Regional",
    "合计": "Total", "小计": "Total", "总计": "Total",
}

# Every carrier's region breakdown always lists rows in this fixed order
# (confirmed across all 4 carriers' live PDFs). Used to positionally infer
# the region of a row whose label cell pdfplumber failed to extract, so a
# single lost label only drops that one row instead of cascading into the
# rows after it (see the blank-first_cell handling in parse_airline_pdf).
_REGION_ORDER = ("Domestic", "International", "Regional")


def _classify_metric_header(first_cell: str) -> str | None:
    """Return the target metric name if `first_cell` is one of the 4 wanted
    metric headers, else None (including for real-but-unwanted headers like
    ATK/AFTK/RTK/RFTK/cargo -- there is no "ignore" list to maintain because
    anything not explicitly a target keyword is treated the same way: not a
    reason to keep the current section active).

    Also checks the cell with internal spaces stripped: China Eastern's PDF
    wraps its passenger-count header across two lines exactly inside the
    keyword ("载运旅客人" + newline + "次（千）"), and the newline-to-space
    cleanup done before this function is called leaves a stray space mid
    keyword ("载运旅客人 次（千）") that breaks a plain substring check.
    """
    candidates = (first_cell, first_cell.replace(" ", ""))
    if any(kw in cell for cell in candidates for kw in _ASK_KEYWORDS):
        return "ask"
    if any(kw in cell for cell in candidates for kw in _RPK_KEYWORDS):
        return "rpk"
    if any(kw in cell for cell in candidates for kw in _PASSENGERS_KEYWORDS):
        return "passengers"
    if any(kw in cell for cell in candidates for kw in _LOAD_FACTOR_KEYWORDS):
        return "passenger_load_factor_pct"
    return None


def _ask_rpk_unit_scale(header_cell: str) -> float:
    """Return the multiplier that converts an ASK/RPK value in
    `header_cell`'s stated unit to a common "million" basis.

    Air China, China Southern, and China Eastern all state ASK/RPK in
    (百万) -- millions. Spring Airlines states its in (万人公里) /
    (万座公里) -- ten-thousands, a unit 100x smaller -- confirmed by
    diffing the raw PDF headers directly. Without this, Spring's ASK/RPK
    get stored ~100x too large relative to the other 3 carriers.

    Also checks the cell with internal spaces stripped: China Eastern's RPK
    header sometimes wraps across three lines exactly inside the "百万"
    unit annotation ("客运人公里\n（RPK）（百\n万）"), and the newline-to-
    space cleanup done before this is called leaves a stray space splitting
    "百万" into "百 万" -- which would otherwise fall through to the "万"
    branch below and wrongly apply Spring's 100x-smaller scale to China
    Eastern's data. Check the space-stripped "百万" first since "百万"
    contains "万" as a substring.
    """
    candidates = (header_cell, header_cell.replace(" ", ""))
    if any("百万" in cell for cell in candidates):
        return 1.0
    if any("万" in cell for cell in candidates):
        return 0.01
    return 1.0


def parse_airline_pdf(pdf_bytes: bytes, airline_code: str, month_key: str) -> list[dict]:
    """Parse tables inside an airline monthly PDF."""
    records = []
    seen: set[tuple[str, str]] = set()  # (metric, region) already recorded in this PDF
    current_section = None
    current_scale = 1.0
    region_idx = 0  # position within _REGION_ORDER for the active section

    def record(region: str, value: float) -> None:
        # A metric's region breakdown should only ever appear once per PDF.
        # A repeat (metric, region) pair showing up again is a pdfplumber
        # page-break artifact -- confirmed on a live Air China PDF where the
        # RPK breakdown's own Domestic/International/Regional rows are
        # correctly extracted on page 1, then a *second*, corrupted set of
        # the same 3 labels reappears as the opening rows of page 2 (values
        # ~100x too small, summing to nothing close to the metric's own
        # printed total). Keep only the first (legitimate) occurrence.
        key = (current_section, region)
        if key in seen:
            return
        seen.add(key)
        records.append({
            "month": month_key,
            "date": f"{month_key}-01",
            "airline_code": airline_code,
            "region": region,
            "metric": current_section,
            "value": value,
        })

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if not row or not any(row):
                            continue
                        clean_row = [str(cell).replace("\n", " ").strip() if cell else "" for cell in row]
                        first_cell = clean_row[0]

                        if not first_cell:
                            # Page-break artifact: pdfplumber sometimes fails
                            # to extract the leading region label for the row
                            # that opens a new page, even though its value
                            # cells parse fine (confirmed on live Air China
                            # PDFs -- the "International" row lands as
                            # [None, value, ...] right after a page break).
                            # An empty cell is never a genuine header, so
                            # don't let it reset current_section. Instead,
                            # infer the region positionally from _REGION_ORDER
                            # -- every carrier lists Domestic/International/
                            # Regional in that fixed order -- so only this one
                            # row's label is lost rather than it (wrongly)
                            # ending the whole section.
                            if current_section and region_idx < len(_REGION_ORDER) and len(clean_row) > 1:
                                region = _REGION_ORDER[region_idx]
                                region_idx += 1
                                val = _clean_val(clean_row[1]) * current_scale
                                if val > 0 or "load_factor" in current_section:
                                    record(region, val)
                            continue

                        if first_cell in _TABLE_HEADER_REPEAT_MARKERS:
                            continue

                        region = _REGION_MAP.get(first_cell)
                        if region is not None:
                            # A region/total data row: use whatever section is
                            # currently active (may be None, in which case
                            # this row is correctly skipped below).
                            if region in _REGION_ORDER:
                                region_idx = _REGION_ORDER.index(region) + 1
                        else:
                            metric = _classify_metric_header(first_cell)
                            # Any header row -- recognized target metric, or
                            # any other real header (ATK/AFTK/RTK/RFTK/cargo/
                            # aircraft-type breakdown/section titles like
                            # "运力"/"载运率") -- resets state. Only a
                            # positively-identified target metric turns
                            # extraction back on; everything else turns it
                            # off, so an unrecognized header can only cause a
                            # gap, never a mislabeled value.
                            #
                            # One further corruption mode (confirmed on a
                            # single China Southern PDF, 2019-06, across all
                            # 8 of its metric blocks): a page-break can merge
                            # the block's own reported Total value into the
                            # header row's second cell (e.g. "(ASK)(百万)\n
                            # 18,597.14"). When that happens, every region
                            # row below is shifted one label off from its
                            # true value -- confirmed by cross-checking
                            # against the PDF's own prose summary and the
                            # arithmetic identity that the 3 regions must sum
                            # to the reported Total, neither of which holds
                            # under the labels as extracted, but both hold
                            # exactly under a one-position shift. Recovering
                            # the true mapping generically (without a prose
                            # paragraph to cross-check against) isn't
                            # reliable, so treat the whole block as unusable
                            # rather than silently mislabel three data
                            # points -- current_section stays None, so every
                            # row below is skipped until the next header.
                            #
                            # Distinguish this from a merely-line-wrapped
                            # number in a header's own (always-discarded)
                            # value cell -- confirmed on a China Eastern PDF
                            # where "10,031.2\n3" is just "10,031.23" split
                            # across lines, no unit-annotation text merged
                            # in, and the region rows below it were correctly
                            # unaffected. The bad case has actual text (the
                            # unit annotation, e.g. "(ASK)(百万)") before the
                            # newline; a pure number wrap has none.
                            second_cell = str(row[1]) if len(row) > 1 and row[1] else ""
                            before_newline = second_cell.split("\n", 1)[0]
                            has_merged_annotation = bool(re.search(r"[^\d,.\-%\s]", before_newline))
                            if metric and has_merged_annotation:
                                current_section = None
                                region_idx = 0
                                continue

                            current_section = metric
                            current_scale = (
                                _ask_rpk_unit_scale(first_cell) if metric in ("ask", "rpk") else 1.0
                            )
                            region_idx = 0
                            continue

                        if region and current_section and len(clean_row) > 1:
                            val_str = clean_row[1]
                            val = _clean_val(val_str) * current_scale
                            if val > 0 or "load_factor" in current_section:
                                record(region, val)
    except Exception as exc:
        print(f"  Error parsing PDF for {airline_code} {month_key}: {exc}")

    return records


def collect_airline_data(cache_dir: Path, start_year: str = "2015-01-01") -> pd.DataFrame:
    """Scrape and parse monthly traffic data for all 4 airlines back to start_year."""
    all_rows = []

    for info in AIRLINES:
        name = info["name"]
        code = info["code"]
        org_id = info["org_id"]

        print(f"\nProcessing {name} ({code})...")
        # Query every known title-keyword variant and merge by month (first
        # keyword's hit wins) -- Cninfo's server-side search treats each
        # variant as a distinct filter, so a carrier that renamed its
        # bulletin mid-history needs all of its historical variants queried,
        # not just its current one.
        by_month: dict[str, dict] = {}
        for searchkey in info["searchkey"]:
            for ann in fetch_announcements(code, org_id, searchkey, start_year=start_year):
                by_month.setdefault(ann["month"], ann)
        announcements = sorted(by_month.values(), key=lambda a: a["month"])
        print(f"  Discovered {len(announcements)} monthly announcements back to {start_year[:4]}")

        for i, ann in enumerate(announcements, 1):
            month_key = ann["month"]
            pdf_bytes = download_pdf(ann["url"], cache_dir / code)
            if pdf_bytes:
                rows = parse_airline_pdf(pdf_bytes, code, month_key)
                all_rows.extend(rows)
            if i % 20 == 0 or i == len(announcements):
                print(f"    Processed {i}/{len(announcements)} PDFs...")
            time.sleep(0.02)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df = df.drop_duplicates(subset=["month", "airline_code", "region", "metric"], keep="last")
    return df.sort_values(["month", "airline_code", "metric", "region"]).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape China airline monthly traffic data.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--start-year", default="2015-01-01", help="Start date for historical announcements (YYYY-MM-DD)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    cache_dir = data_dir / "raw" / "airline_pdfs"
    out_path = data_dir / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"

    print("Scraping Full Historical Aviation Traffic Data (China Big 3 + Spring Airlines)")
    print("=" * 65)

    df = collect_airline_data(cache_dir, start_year=args.start_year)
    if not df.empty:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out_path, index=False)
        print(f"\nSuccessfully wrote {out_path} ({len(df)} records)")
        print("\nSummary of extracted months by airline:")
        summary = df.groupby(["airline_code", "metric"])["month"].nunique().unstack(fill_value=0)
        print(summary)
    else:
        print("No traffic records extracted.")


if __name__ == "__main__":
    main()
