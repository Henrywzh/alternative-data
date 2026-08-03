"""Monthly traffic data scraper for China's major listed airlines:
1. Air China (中国国航, 601111.SH / 00753.HK)
2. China Southern (中国南方航空, 600029.SH / 01055.HK)
3. China Eastern (中国东方航空, 600115.SH / 00670.HK)
4. Spring Airlines (春秋航空, 601021.SH - LCC Benchmark)
5. Hainan Airlines Holdings (海南航空控股, 600221.SH / 900945.SH)
6. Juneyao Airlines (吉祥航空, 603885.SH)

Queries Cninfo API for monthly "运营数据" announcements, downloads PDFs,
caches them locally in data/raw/airline_pdfs/, parses tables using pdfplumber,
and outputs standardized time series to data/processed/airline_traffic/china_airlines_monthly.parquet.
Fleet changes and route announcements are written separately to
data/processed/airline_traffic/china_airlines_operating_events.parquet.
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
    {"name": "Hainan Airlines Holdings", "name_cn": "海南航空控股", "code": "600221", "org_id": "gssh0600221", "searchkey": ("主要运营数据",)},
    {"name": "Juneyao Airlines", "name_cn": "吉祥航空", "code": "603885", "org_id": "9900023633", "searchkey": ("主要运营数据",)},
]

AIRLINE_EVENT_COLUMNS = [
    "month", "date", "airline_code", "event_type", "value", "detail",
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
# into one table -- e.g. ATK, ASK, AFTK (capacity) and RTK, RPK, RFTK,
# passenger count, cargo tonnage, plus 2-3 load-factor variants. The parser
# keeps the original four passenger metrics and now also captures the stable
# total/region cargo metrics needed for the airline dashboard. It still
# ignores aircraft-type breakdowns and prose events (fleet additions and new
# routes), which need a separate event schema rather than fake numeric rows.
# "可利用客公里" is China Southern's own pre-2019-03 ASK header (座 seat ->
# 客 passenger); it switched to "可利用座公里", matching every other carrier,
# from March 2019 onward. Without it, every China Southern PDF before that
# date silently drops its whole ASK breakdown.
_ASK_KEYWORDS = ("可用座位公里", "可利用座公里", "可用座公里", "可利用客公里")
_RPK_KEYWORDS = ("收入客公里", "客运人公里", "旅客周转量")
_PASSENGERS_KEYWORDS = ("乘客人数", "载客人数", "载运旅客人次", "总载运人次")
_LOAD_FACTOR_KEYWORDS = ("客座利用率", "客座率")
_AFTK_KEYWORDS = (
    "可用货运吨公里", "可用货邮吨公里", "可用货邮吨公里数",
    "可利用货邮吨公里", "可利用吨公里——货邮运", "可利用吨公里—货邮运",
    "可利用吨公里-货邮运",
)
_RFTK_KEYWORDS = (
    "收入货运吨公里", "收入货邮吨公里", "收入吨公里——货邮运",
    "收入吨公里—货邮运", "收入吨公里-货邮运", "货邮载运吨公里", "货邮周转量",
)
_CARGO_TONNES_KEYWORDS = (
    "货运及邮运量", "货物及邮件数量", "货物及邮件", "货邮载运量", "货邮载重量",
)
_FREIGHT_LOAD_FACTOR_KEYWORDS = ("货物及邮件载运率", "货邮载运率")
_OVERALL_LOAD_FACTOR_KEYWORDS = ("综合载运率", "总体载运率")
_ATK_KEYWORDS = ("可利用吨公里", "可用吨公里数", "可用吨公里")
_RTK_KEYWORDS = ("收入吨公里", "运输周转量")
_AUXILIARY_METRICS = {
    "aftk", "rftk", "cargo_tonnes", "freight_load_factor_pct",
    "overall_load_factor_pct", "atk", "rtk",
}

# Generic table column-header row repeated at the top of every page a table
# spans (e.g. Spring Airlines' PDFs run 3 pages; pdfplumber yields a separate
# "table" per page, each starting with this same header row). It carries no
# metric/region information, so unlike a genuine unrecognized metric header
# it must NOT reset the active section -- otherwise a metric whose region
# rows happen to straddle a page break (confirmed: Spring Airlines' ASK
# International/Regional rows landed on the page after this repeat, right
# after Domestic) silently loses its remaining rows.
_TABLE_HEADER_REPEAT_MARKERS = ("指标",)

# A few issuers split a metric header across a page boundary.  For example,
# Juneyao's 2017-04 PDF puts "收入货运吨公里" and "(RFTK)(万吨公里)" on
# consecutive pages.  The first row carries the value, while the second row
# carries the unit; the parser must keep the header state long enough to join
# them before applying a scale.
_UNIT_CONTINUATION_RE = re.compile(
    r"^[（(].*(?:百万|万座公里|万人公里|万吨公里|千吨|吨|公斤|千克|公里|％|%)"
)

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
_PASSENGER_HEADER_CONTINUATIONS = {"次）", "次)"}
_EXPLICIT_ZERO_MARKERS = {"-", "—", "–", "－", "0", "0.0", "0.00"}


def _classify_metric_header(first_cell: str) -> str | None:
    """Return a normalized metric name for a recognized operating-data header.

    Also checks the cell with internal spaces stripped: China Eastern's PDF
    wraps its passenger-count header across two lines exactly inside the
    keyword ("载运旅客人" + newline + "次（千）"), and the newline-to-space
    cleanup done before this function is called leaves a stray space mid
    keyword ("载运旅客人 次（千）") that breaks a plain substring check.
    """
    candidates = (first_cell, first_cell.replace(" ", ""))
    # Check the freight-specific variants before generic ATK/RTK. Several
    # issuers name AFTK/RFTK as "可利用吨公里—货邮运" / "收入吨公里—货邮运",
    # which would otherwise be swallowed by the generic keyword.
    if any(kw in cell for cell in candidates for kw in _AFTK_KEYWORDS):
        return "aftk"
    if any(kw in cell for cell in candidates for kw in _RFTK_KEYWORDS):
        return "rftk"
    if any(kw in cell for cell in candidates for kw in _FREIGHT_LOAD_FACTOR_KEYWORDS):
        return "freight_load_factor_pct"
    if any(kw in cell for cell in candidates for kw in _OVERALL_LOAD_FACTOR_KEYWORDS):
        return "overall_load_factor_pct"
    if any(kw in cell for cell in candidates for kw in _CARGO_TONNES_KEYWORDS):
        return "cargo_tonnes"
    if any(kw in cell for cell in candidates for kw in _ATK_KEYWORDS):
        return "atk"
    if any(kw in cell for cell in candidates for kw in _RTK_KEYWORDS):
        return "rtk"
    if any(kw in cell for cell in candidates for kw in _ASK_KEYWORDS):
        return "ask"
    if any(kw in cell for cell in candidates for kw in _RPK_KEYWORDS):
        return "rpk"
    if any(kw in cell for cell in candidates for kw in _PASSENGERS_KEYWORDS):
        return "passengers"
    if any(kw in cell for cell in candidates for kw in _LOAD_FACTOR_KEYWORDS):
        return "passenger_load_factor_pct"
    return None


def _metric_unit_scale(header_cell: str, metric: str) -> float:
    """Convert an issuer's displayed unit into the normalized parquet unit.

    ASK/RPK and tonne-kilometre metrics are stored in millions. Cargo weight
    is stored in tonnes. The source PDFs mix millions, ten-thousands, thousand
    tonnes and million kilograms, so the unit must be inferred from the
    metric header rather than from the magnitude of the value.
    """
    candidates = (header_cell, header_cell.replace(" ", ""))
    if metric in ("ask", "rpk"):
        return _ask_rpk_unit_scale(header_cell)
    if metric in {"aftk", "rftk", "atk", "rtk"}:
        if any("百万" in cell for cell in candidates):
            return 1.0
        if any("万" in cell for cell in candidates):
            return 0.01
        return 1.0
    if metric == "cargo_tonnes":
        if any("千吨" in cell for cell in candidates):
            return 1000.0
        if any("百万" in cell and ("公斤" in cell or "千克" in cell) for cell in candidates):
            return 1000.0
        return 1.0
    return 1.0


def _is_unit_continuation(cell: str) -> bool:
    """Return whether a cell is a wrapped metric-unit continuation row."""
    compact = cell.replace(" ", "")
    return bool(_UNIT_CONTINUATION_RE.match(compact))


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
    pending_auxiliary_header: tuple[str, str, str] | None = None

    def should_record(raw_value: str, value: float) -> bool:
        """Keep positive observations and explicit source zero markers.

        A dash in an issuer table means that the disclosed slice had no
        activity.  It is different from an empty cell, which means the source
        did not provide a usable observation.  The old ``value > 0`` gate
        collapsed both cases into a missing row, hiding zero regional traffic
        during COVID-era months.
        """
        marker = raw_value.replace(" ", "").strip()
        return (
            value > 0
            or "load_factor" in (current_section or "")
            or marker in _EXPLICIT_ZERO_MARKERS
        )

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

    # A region-breakdown row (Domestic/International/Regional) that happens to
    # fall as the very first line of text on a new page is sometimes dropped
    # by pdfplumber's extract_tables() entirely -- not merged, not blanked,
    # just absent from the table structure, unlike the blank-first-cell
    # artifact handled below. Confirmed on multiple live Air China PDFs (e.g.
    # 2016-01: the page-2-opening "国际航线 1100.9 ..." passengers row is
    # missing from extract_tables()'s page-2 table entirely, even though the
    # very next row, "地区航线 384.7 ...", is extracted correctly; 2016-03:
    # the page-2-opening "地区航线 363.7 ..." passengers row is dropped the
    # same way). page.extract_text() always contains the row even when the
    # table structure drops it, so recover it from there: if the page's very
    # first text line is a "<region label> <number>..." row -- or, in PDFs
    # that line-wrap the label and its numbers onto separate lines (confirmed
    # on 2016-09/2016-10: page 2 opens with a lone "地区航线" line, numbers
    # only appearing on the line after), a bare region label followed by a
    # numeric-only next line -- and a target metric section is still active
    # from the previous page, treat it as the missing row for that region.
    # Restricting to the page's first 1-2 lines only (not a general scan)
    # avoids picking up one of this same label's many other occurrences later
    # on the page for a different metric.
    _ORPHAN_ROW_RE = re.compile(r"^(国内航线|国际航线|地区航线)\s+([\d,.\-]+)")
    _ORPHAN_LABEL_ONLY_RE = re.compile(r"^(国内航线|国际航线|地区航线)$")
    _LEADING_NUMBER_RE = re.compile(r"^([\d,.\-]+)")

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()

                if current_section:
                    page_text = page.extract_text() or ""
                    page_lines = page_text.split("\n") if page_text else []
                    first_line = page_lines[0].strip() if page_lines else ""
                    orphan_match = _ORPHAN_ROW_RE.match(first_line)
                    orphan_region_label = None
                    orphan_value_str = None
                    if orphan_match:
                        orphan_region_label = orphan_match.group(1)
                        orphan_value_str = orphan_match.group(2)
                    elif _ORPHAN_LABEL_ONLY_RE.match(first_line) and len(page_lines) > 1:
                        second_line = page_lines[1].strip()
                        number_match = _LEADING_NUMBER_RE.match(second_line)
                        if number_match:
                            orphan_region_label = first_line
                            orphan_value_str = number_match.group(1)

                    if orphan_region_label is not None:
                        region = _REGION_MAP.get(orphan_region_label)
                        if region in _REGION_ORDER:
                            val = _clean_val(orphan_value_str) * current_scale
                            if should_record(orphan_value_str, val):
                                record(region, val)
                                region_idx = _REGION_ORDER.index(region) + 1

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
                                if should_record(clean_row[1], val):
                                    record(region, val)
                            continue

                        # Some PDFs put an auxiliary metric's unit on a
                        # separate row/page immediately after the header row.
                        # Resolve the deferred header value before treating the
                        # continuation as an unrelated header; otherwise a
                        # value stated in 万吨公里 is stored as if it were in
                        # millions, creating a 100x RFTK spike.
                        if pending_auxiliary_header and _is_unit_continuation(first_cell):
                            pending_metric, pending_value, pending_header = pending_auxiliary_header
                            current_scale = _metric_unit_scale(
                                f"{pending_header} {first_cell}", pending_metric
                            )
                            header_value = _clean_val(pending_value) * current_scale
                            if header_value > 0:
                                record("Total", header_value)
                            pending_auxiliary_header = None
                            continue
                        if pending_auxiliary_header:
                            pending_metric, pending_value, pending_header = pending_auxiliary_header
                            header_value = _clean_val(pending_value) * _metric_unit_scale(
                                pending_header, pending_metric
                            )
                            if header_value > 0:
                                record("Total", header_value)
                            pending_auxiliary_header = None

                        if first_cell in _TABLE_HEADER_REPEAT_MARKERS:
                            continue

                        # Juneyao's 2023-04, 2023-07, 2024-04 and 2024-11
                        # PDFs split ``乘客人数（千人/次）`` across a page
                        # boundary.  The continuation cell is not a new
                        # metric header; preserve the passenger section so
                        # the Domestic/International/Regional rows that
                        # follow it are still attached to passengers.
                        if (
                            current_section == "passengers"
                            and first_cell in _PASSENGER_HEADER_CONTINUATIONS
                        ):
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
                            current_scale = _metric_unit_scale(first_cell, metric) if metric else 1.0
                            # Air China, China Eastern, Spring Airlines and
                            # Juneyao often put the month's all-operation
                            # value on the metric-header row itself instead
                            # of publishing a separate "合计" row. Capture
                            # that value only for the auxiliary metrics; the
                            # passenger metrics retain their long-standing
                            # region-row behavior and derived-total logic.
                            if metric in _AUXILIARY_METRICS and len(clean_row) > 1:
                                header_value = _clean_val(clean_row[1]) * current_scale
                                # Blank header cells are common when the
                                # issuer prints a separate region/Total row;
                                # do not turn that blank into a reported 0.0
                                # and then block the real Total row via the
                                # first-wins de-duplication rule. A genuine
                                # zero load factor is not needed for these
                                # operating tables and can be reconstructed
                                # from the underlying numerator/denominator.
                                if header_value > 0:
                                    # If the header has no unit annotation,
                                    # defer recording until the next row/page:
                                    # it may be the wrapped unit continuation.
                                    # A normal region row will flush this with
                                    # the default scale on the next iteration.
                                    if _metric_unit_scale(first_cell, metric) == 1.0:
                                        pending_auxiliary_header = (
                                            metric, clean_row[1], first_cell
                                        )
                                    else:
                                        record("Total", header_value)
                            region_idx = 0
                            continue

                        if region and current_section and len(clean_row) > 1:
                            val_str = clean_row[1]
                            val = _clean_val(val_str) * current_scale
                            if should_record(val_str, val):
                                record(region, val)
    except Exception as exc:
        print(f"  Error parsing PDF for {airline_code} {month_key}: {exc}")

    return records


def _pdf_text(pdf_bytes: bytes) -> str:
    """Extract all visible text once for the prose-event parser."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception:
        return ""


def _aircraft_count(segment: str) -> int:
    """Sum aircraft counts in a phrase such as ``3 架 A320、2 架 B737``."""
    # Several issuers write both a headline total and a parenthetical model
    # breakdown (e.g. "引进8架飞机（包含3架...）"). The breakdown is the
    # auditable non-duplicated representation; do not add the headline to it.
    breakdown = re.search(r"(?:包括|包含)(?P<body>.*)", segment, flags=re.S)
    if breakdown:
        segment = breakdown.group("body")
    return int(sum(float(value) for value in re.findall(r"(\d+)\s*架", segment)))


def parse_airline_event_text(text: str, airline_code: str, month_key: str) -> list[dict]:
    """Parse auditable fleet/route events from an issuer's PDF prose.

    The event layer is deliberately sparse: an absent event row means the
    announcement did not expose a matching event, not that the value was
    backfilled as zero. Fleet additions/retirements may contain several
    aircraft types in one sentence, so their values are summed from every
    ``N 架`` fragment in that sentence. Route events retain a short source
    phrase for later review instead of pretending that a route count is a
    continuous KPI.
    """
    if not text:
        return []

    # PDF extraction often wraps a single fleet sentence across several
    # visual lines (especially inside the parenthetical model breakdown), so
    # collapse all whitespace before applying punctuation-based boundaries.
    normalized = re.sub(r"\s+", " ", text).strip()
    normalized = re.sub(
        r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", normalized
    )
    rows: list[dict] = []

    def add_event(event_type: str, value: int, detail: str) -> None:
        detail = re.split(r"(?:（[一二三四五六七八九十]+）|\([一二三四五六七八九十]+\))", detail, maxsplit=1)[0]
        rows.append(
            {
                "month": month_key,
                "date": f"{month_key}-01",
                "airline_code": airline_code,
                "event_type": event_type,
                "value": int(value),
                "detail": re.sub(r"\s+", " ", detail).strip(),
            }
        )

    added_pattern = re.compile(
        r"(?:引进|新增)(?P<body>.*?)(?=(?:退出|退役|退租|月末|截至|合计运营)|[。；\n]|$)",
        flags=re.S,
    )
    for added_match in added_pattern.finditer(normalized):
        body = added_match.group("body")
        if "架" in body:
            add_event("fleet_added_aircraft", _aircraft_count(body), f"{added_match.group(0)}")
            break

    retired_pattern = re.compile(
        r"(?:退出|退役(?!的)|退租)(?P<body>.*?)(?=(?:月末|截至|合计运营)|[。；\n]|$)",
        flags=re.S,
    )
    for retired_match in retired_pattern.finditer(normalized):
        body = retired_match.group("body")
        if "架" in body:
            add_event("fleet_retired_aircraft", _aircraft_count(body), retired_match.group(0))
            break

    fleet_total: int | None = None
    fleet_detail = ""
    # Early China Eastern bulletins and several fleet tables disclose the
    # total as a row rather than in the prose, e.g. "合 计 215 224 132
    # 571".  Restrict these patterns to the fleet section and exclude
    # "客机合计"/"货机合计" subtotals; the latter was the source of the
    # spurious two-aircraft China Eastern observations.  This table-first
    # order also preserves the consolidated Juneyao + Jiuyuan total (130)
    # when the prose separately states the parent company's 93 aircraft.
    fleet_markers = ("飞机机队", "机队情况", "机队规模", "机队具体情况", "运力情况")
    marker_positions = [normalized.find(marker) for marker in fleet_markers if normalized.find(marker) >= 0]
    fleet_section = normalized[min(marker_positions):] if marker_positions else ""
    fleet_table_patterns = (
        r"(?:客货(?:运)?飞机)合计\s+(?:[-\d,.]+\s+){3}(\d{1,4})",
        r"(?<!客机)(?<!货机)(?<!飞机)合计\s+(?:[-\d,.]+\s+){3}(\d{1,4})",
        r"(?<!客机)(?<!货机)(?<!飞机)合计\s*[—\-]+\s*(\d{1,4})",
    )
    for pattern in fleet_table_patterns:
        match = re.search(pattern, fleet_section)
        if match:
            fleet_total = int(match.group(1))
            fleet_detail = match.group(0)
            break
    if fleet_total is None:
        total_patterns = (
            r"(?:合计运营|合计运营飞机)\s*[:：]?\s*(\d{1,4})\s*架",
            r"月末(?:合计)?\s*(\d{1,4})\s*架",
            r"(?:公司|本公司|本集团)?(?:共)?运营\s*(\d{1,4})\s*架",
        )
        for pattern in total_patterns:
            match = re.search(pattern, normalized)
            if match:
                fleet_total = int(match.group(1))
                fleet_detail = match.group(0)
                break
    if fleet_total is not None:
        add_event("fleet_total_aircraft", fleet_total, fleet_detail)

    # Record an explicit no-new-route disclosure as zero.  This keeps the
    # chart honest: zero means the issuer explicitly said none, while an
    # absent row still means the bulletin did not disclose route activity.
    no_route_match = re.search(
        r"(?:未|无|暂无|没有|均未)(?:新增|新开|开通)(?:主要|定期)?航线", normalized
    )

    route_matches: list[str] = []
    for route_pattern in (
        # The route marker must appear close to the action verb. This avoids
        # consuming headings such as “新开、复航、加密航线情况如下” and then
        # counting the heading itself as an additional route.
        r"(?:(?:新开|新增)(?!主要航线情况|以下定期航线)[^。；\n]{0,24}(?:=|＝|—|－|-)[^。；\n]{0,100})",
    ):
        route_matches.extend(re.findall(route_pattern, normalized))
    route_matches.extend(
        "新增" + body
        for body in re.findall(
            r"新增主要航线情况(?:如下)?\s*[:：](?P<body>[^。；]{0,240})",
            normalized,
        )
    )
    # The two patterns intentionally cover issuers that do or do not repeat
    # the word 航线, so the same route can be found once in short form and
    # once with its frequency suffix. Keep the longest overlapping phrase.
    unique_routes: list[str] = []
    for phrase in sorted(set(route_matches), key=len, reverse=True):
        if not any(phrase in existing or existing in phrase for existing in unique_routes):
            unique_routes.append(phrase)
    route_matches = sorted(unique_routes)
    route_matches = [
        phrase.strip()
        for phrase in route_matches
        if any(token in phrase for token in ("=", "＝", "—", "－", "往返", "每周", "-"))
    ]
    numeric_route_matches = list(re.finditer(
        r"(?:新开|新增)(?P<body>[^。；]{0,160}?)(?P<count>\d{1,2})\s*条[^。；]{0,20}?航线",
        normalized,
    ))
    if route_matches or numeric_route_matches:
        route_count = 0
        for phrase in route_matches:
            route_parts = re.split(r"[、，,]", phrase)
            detailed_parts = [
                part for part in route_parts
                if any(token in part for token in ("=", "＝", "—", "－", "往返", "每周", "-"))
            ]
            route_count += max(1, len(detailed_parts))
        route_count += sum(int(match.group("count")) for match in numeric_route_matches)
        details = route_matches + [
            f"{match.group(0)}" for match in numeric_route_matches
        ]
        add_event("new_route_event_count", route_count, "；".join(details))
    elif no_route_match:
        add_event("new_route_event_count", 0, no_route_match.group(0))

    return rows


def parse_airline_events(pdf_bytes: bytes, airline_code: str, month_key: str) -> list[dict]:
    """Parse fleet/route event rows from a monthly operating-data PDF."""
    return parse_airline_event_text(_pdf_text(pdf_bytes), airline_code, month_key)


def collect_airline_data(
    cache_dir: Path,
    start_year: str = "2015-01-01",
    events_out: list[dict] | None = None,
) -> pd.DataFrame:
    """Scrape and parse monthly operating data for all six airlines."""
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
                if events_out is not None:
                    events_out.extend(parse_airline_events(pdf_bytes, code, month_key))
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
    event_path = data_dir / "processed" / "airline_traffic" / "china_airlines_operating_events.parquet"

    print("Scraping Full Historical Aviation Traffic Data (six listed Chinese airlines)")
    print("=" * 65)

    event_rows: list[dict] = []
    df = collect_airline_data(cache_dir, start_year=args.start_year, events_out=event_rows)
    if not df.empty:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out_path, index=False)
        print(f"\nSuccessfully wrote {out_path} ({len(df)} records)")
        print("\nSummary of extracted months by airline:")
        summary = df.groupby(["airline_code", "metric"])["month"].nunique().unstack(fill_value=0)
        print(summary)
        if event_rows:
            events = pd.DataFrame(event_rows)
            events = events.drop_duplicates(subset=["month", "airline_code", "event_type"], keep="last")
            events = events[AIRLINE_EVENT_COLUMNS].sort_values(
                ["month", "airline_code", "event_type"]
            ).reset_index(drop=True)
            event_path.parent.mkdir(parents=True, exist_ok=True)
            events.to_parquet(event_path, index=False)
            print(f"\nSuccessfully wrote {event_path} ({len(events)} event rows)")
            print(events.groupby(["airline_code", "event_type"]).size().unstack(fill_value=0))
    else:
        print("No traffic records extracted.")


if __name__ == "__main__":
    main()
