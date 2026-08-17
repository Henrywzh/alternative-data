"""NBS monthly demand-side controls for the airline v3 model.

The National Bureau of Statistics publishes free monthly national-economy
press releases.  The monthly 经济运行情况 release (typically around the 15th)
carries retail sales of consumer goods, the services production index, and
transport/telecom consumption context; the PMI release (last day of the
month) carries manufacturing/services purchasing-managers indexes.  These are
aggregate macro demand regimes that can inform leisure/business travel
scenarios, not airline RPK or revenue, so this module keeps them in an
explicit dated panel and never interpolates them into company traffic.

The layer preserves the article publication date (release-date-safe), the
reference period, raw values and YoY rates as published.  NBS publishes in
Chinese; metric labels are normalized to stable English keys with the
Chinese source label retained.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    NBS_PRESS_INDEX_PAGE_TEMPLATE,
    NBS_PRESS_INDEX_URL,
    NORMALIZED_DIR,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_nbs_demand.csv"
DATASET_ID = "airline_nbs_demand"

OUTPUT_COLUMNS = [
    "dataset_id",
    "release_id",
    "source_organization",
    "release_family",
    "release_title",
    "reference_period",
    "source_url",
    "metric",
    "metric_cn",
    "value",
    "unit",
    "yoy_pct",
    "scope",
    "source_release_date",
    "source_release_date_status",
    "point_in_time_status",
    "source_quality",
    "source_note",
    "raw_snapshot_path",
    "retrieved_at",
]

INDEX_MAX_PAGES = 12  # ~12 months of releases at ~10 items per page

# Metric keys extracted from the monthly economy release.  Each entry maps a
# normalized key to the Chinese labels that identify the metric and its unit.
METRIC_SPECS: tuple[dict[str, Any], ...] = (
    {
        "metric": "retail_sales_consumer_goods",
        "metric_cn": "社会消费品零售总额",
        "label_re": r"社会消费品零售总额",
        "unit": "亿元",
    },
    {
        "metric": "services_production_index",
        "metric_cn": "服务业生产指数",
        "label_re": r"服务业生产指数",
        "unit": "同比%",
    },
    {
        "metric": "service_retail_sales",
        "metric_cn": "服务零售额",
        "label_re": r"服务零售额",
        "unit": "同比%",
    },
    {
        "metric": "catering_income",
        "metric_cn": "餐饮收入",
        "label_re": r"餐饮收入",
        "unit": "亿元",
    },
)


def _get(url: str) -> requests.Response:
    response = requests.get(
        url,
        headers=DEFAULT_HEADERS,
        timeout=max(DEFAULT_TIMEOUT, 30),
    )
    response.raise_for_status()
    return response


def _article_text(payload: bytes) -> str:
    soup = BeautifulSoup(payload, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    # NBS HTML puts numbers and CJK labels in separate inline elements, so
    # the joined text contains spaces between tokens ("6 月份，社会消费品
    # 零售总额 42691 亿元").  Remove spaces between CJK and digits/percent
    # signs, and between digits and en-dashes (range "1 — 2月份"), so the
    # metric regexes match the published wording.
    text = re.sub(r"(?<=[\u4e00-\u9fff0-9%]) (?=[\u4e00-\u9fff0-9%])", "", text)
    text = re.sub(r"(?<=\d) (?=[—\-])", "", text)
    text = re.sub(r"(?<=[—\-]) (?=\d)", "", text)
    return text


def _discover_releases(max_pages: int = INDEX_MAX_PAGES) -> list[dict[str, str]]:
    """Walk the NBS press-release index and collect dated release links."""
    releases: dict[str, dict[str, str]] = {}
    for page in range(1, max_pages + 1):
        url = (
            NBS_PRESS_INDEX_URL
            if page == 1
            else NBS_PRESS_INDEX_PAGE_TEMPLATE.format(page=page)
        )
        try:
            response = _get(url)
        except Exception as exc:
            logger.warning("NBS index page %s failed: %s", page, exc)
            continue
        if "index" in url and page == 1:
            raw = save_raw_snapshot(
                "airline_nbs_index",
                response.content,
                file_ext="html",
                source_url=url,
            )
        soup = BeautifulSoup(response.content, "html.parser")
        for anchor in soup.find_all("a", href=True):
            title = anchor.get("title") or anchor.get_text(" ", strip=True)
            if not title:
                continue
            href = anchor["href"]
            # NBS release URLs look like ./202607/t20260715_1964127.html
            match = re.search(r"(\d{6})/t(\d{8})_\d+\.html?$", href)
            if not match:
                continue
            release_id = f"{match.group(1)}_{match.group(2)}"
            if release_id in releases:
                continue
            if not re.search(r"运行情况|采购经理指数|消费品零售总额", title):
                continue
            url_path = href if href.startswith("http") else (
                "https://www.stats.gov.cn/sj/zxfb/" + href.lstrip("./")
            )
            releases[release_id] = {
                "release_id": release_id,
                "title": title,
                "url": url_path,
                "reference_period": _title_reference_period(title),
                "date": (
                    f"{match.group(2)[:4]}-{match.group(2)[4:6]}-"
                    f"{match.group(2)[6:8]}"
                ),
            }
    return sorted(releases.values(), key=lambda r: r["release_id"])


def _title_reference_period(title: str) -> str:
    """Extract the data reference period from an NBS release title.

    PMI titles name the reference month ("2026年7月中国采购经理指数运行情况"
    -> 2026-07); retail-sales titles name the covered period ("2026年上半年
    社会消费品零售总额增长1.3%" -> 2026-H1, "2026年1—2月份..." -> 2026-01-02,
    "2025年12月份..." -> 2025-12).  Unmatched titles fall back to empty.
    """
    year = re.search(r"(20\d{2})年", title)
    if not year:
        return ""
    y = year.group(1)
    month = re.search(r"(\d{1,2})月", title)
    half = re.search(r"上半年|下半年", title)
    jan_feb = re.search(r"1\s*—\s*2月份|1-2月份", title)
    jan_mar = re.search(r"1\s*—\s*3月份|1-3月份", title)
    jan_apr = re.search(r"1\s*—\s*4月份|1-4月份", title)
    jan_may = re.search(r"1\s*—\s*5月份|1-5月份", title)
    if jan_feb:
        return f"{y}-01-02"
    if jan_mar:
        return f"{y}-01-03"
    if jan_apr:
        return f"{y}-01-04"
    if jan_may:
        return f"{y}-01-05"
    if half:
        return f"{y}-H1" if half.group(0) == "上半年" else f"{y}-H2"
    if month:
        return f"{y}-{int(month.group(1)):02d}"
    return ""


def _parse_release(
    release: dict[str, str],
    *,
    payload: bytes,
    raw_path: str | None,
    retrieved: str,
) -> list[dict[str, Any]]:
    text = _article_text(payload)
    rows: list[dict[str, Any]] = []
    is_pmi = "采购经理指数" in release["title"]
    family = "pmi" if is_pmi else "monthly_economy"
    if is_pmi:
        rows.extend(_parse_pmi(release, text, raw_path, retrieved))
    else:
        rows.extend(_parse_monthly_economy(release, text, raw_path, retrieved))
    return rows


def _parse_pmi(
    release: dict[str, str],
    text: str,
    raw_path: str | None,
    retrieved: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # PMI release prose: "制造业采购经理指数为49.5%，比上月上升0.3个百分点"
    patterns = (
        (
            "manufacturing_pmi",
            "制造业采购经理指数",
            r"制造业采购经理指数[^0-9\-]{0,20}(?P<value>[\d.]+)%",
            "pct",
        ),
        (
            "non_manufacturing_pmi",
            "非制造业商务活动指数",
            r"非制造业商务活动指数[^0-9\-]{0,20}(?P<value>[\d.]+)%",
            "pct",
        ),
        (
            "services_business_activity_index",
            "服务业商务活动指数",
            r"服务业商务活动指数[^0-9\-]{0,20}(?P<value>[\d.]+)%",
            "pct",
        ),
    )
    for key, label, pattern, unit in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        rows.append(
            _row(
                release,
                family="pmi",
                metric=key,
                metric_cn=label,
                value=float(match.group("value")),
                unit=unit,
                yoy=None,
                scope="national",
                raw_path=raw_path,
                retrieved=retrieved,
            )
        )
    return rows


def _parse_monthly_economy(
    release: dict[str, str],
    text: str,
    raw_path: str | None,
    retrieved: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # Single-month retail sales line:
    # "6月份，社会消费品零售总额42691亿元，同比增长1.0%"
    # The negative lookbehind prevents matching the tail of a cumulative
    # range such as "1—4月份" (which would otherwise parse as month 4).
    retail = re.search(
        r"(?<![\d—])(?P<month>\d+)月份，社会消费品零售总额"
        r"(?P<value>[\d,]+)亿元，同比(?P<direction>增长|下降)(?P<yoy>[\d.\-]+)%",
        text,
    )
    if retail:
        yoy = float(retail.group("yoy"))
        if retail.group("direction") == "下降":
            yoy = -yoy
        rows.append(
            _row(
                release,
                family="monthly_economy",
                metric="retail_sales_consumer_goods",
                metric_cn="社会消费品零售总额",
                value=float(retail.group("value").replace(",", "")),
                unit="亿元",
                yoy=yoy,
                scope=f"month_{retail.group('month')}",
                raw_path=raw_path,
                retrieved=retrieved,
            )
        )
    # Cumulative-period retail line (published in Jan-Feb / Jan-Apr / Jan-May
    # / H1 releases): "1—2月份，社会消费品零售总额86079亿元，同比增长2.8%"
    # or "上半年，社会消费品零售总额248722亿元，同比增长1.3%".  The value is
    # the year-to-date total, not a single month, and the scope records that.
    cumulative = re.search(
        r"(?P<period>1—2月份|1—3月份|1—4月份|1—5月份|上半年|全年)，社会消费品零售总额"
        r"(?P<value>[\d,]+)亿元，同比(?P<direction>增长|下降)(?P<yoy>[\d.\-]+)%",
        text,
    )
    if cumulative:
        period = cumulative.group("period")
        scope = {
            "1—2月份": "ytd_jan_feb",
            "1—3月份": "ytd_jan_mar",
            "1—4月份": "ytd_jan_apr",
            "1—5月份": "ytd_jan_may",
            "上半年": "ytd_h1",
            "全年": "ytd_fy",
        }[period]
        rows.append(
            _row(
                release,
                family="monthly_economy",
                metric="retail_sales_consumer_goods",
                metric_cn="社会消费品零售总额",
                value=float(cumulative.group("value").replace(",", "")),
                unit="亿元",
                yoy=(
                    -float(cumulative.group("yoy"))
                    if cumulative.group("direction") == "下降"
                    else float(cumulative.group("yoy"))
                ),
                scope=scope,
                raw_path=raw_path,
                retrieved=retrieved,
            )
        )
    # Services production index: "6月份，全国服务业生产指数同比增长4.7%"
    spi = re.search(
        r"(?P<month>\d+)月份，全国服务业生产指数同比增长(?P<yoy>[\d.\-]+)%",
        text,
    )
    if spi:
        rows.append(
            _row(
                release,
                family="monthly_economy",
                metric="services_production_index",
                metric_cn="服务业生产指数",
                value=float(spi.group("yoy")),
                unit="同比%",
                yoy=float(spi.group("yoy")),
                scope=f"month_{spi.group('month')}",
                raw_path=raw_path,
                retrieved=retrieved,
            )
        )
    # Service retail sales: "其中服务零售额增长5.3%"
    srs = re.search(r"服务零售额增长(?P<yoy>[\d.\-]+)%", text)
    if srs:
        rows.append(
            _row(
                release,
                family="monthly_economy",
                metric="service_retail_sales",
                metric_cn="服务零售额",
                value=float(srs.group("yoy")),
                unit="同比%",
                yoy=float(srs.group("yoy")),
                scope="period",
                raw_path=raw_path,
                retrieved=retrieved,
            )
        )
    return rows


def _row(
    release: dict[str, str],
    *,
    family: str,
    metric: str,
    metric_cn: str,
    value: float,
    unit: str,
    yoy: float | None,
    scope: str,
    raw_path: str | None,
    retrieved: str,
) -> dict[str, Any]:
    return {
        "dataset_id": DATASET_ID,
        "release_id": release["release_id"],
        "source_organization": "National Bureau of Statistics",
        "release_family": family,
        "release_title": release["title"],
        "reference_period": release.get("reference_period") or "",
        "source_url": release["url"],
        "metric": metric,
        "metric_cn": metric_cn,
        "value": value,
        "unit": unit,
        "yoy_pct": yoy,
        "scope": scope,
        "source_release_date": release["date"],
        "source_release_date_status": "official_page_date",
        "point_in_time_status": "release_date_safe_observation",
        "source_quality": "nbs_primary_official_release",
        "source_note": (
            "NBS monthly national-economy press release; aggregate macro "
            "demand regime context, not airline RPK/revenue.  Chinese-source "
            "labels retained; values as published."
        ),
        "raw_snapshot_path": raw_path,
        "retrieved_at": retrieved,
    }


def fetch_airline_nbs_demand(
    max_pages: int = INDEX_MAX_PAGES,
) -> pd.DataFrame:
    """Fetch NBS demand-side releases and persist the dated panel."""
    retrieved = datetime.now(timezone.utc).isoformat()
    releases = _discover_releases(max_pages=max_pages)
    if not releases:
        raise ValueError("No NBS releases discovered from the press index")
    rows: list[dict[str, Any]] = []
    for release in releases:
        try:
            response = _get(release["url"])
        except Exception as exc:
            logger.warning("NBS release %s failed: %s", release["release_id"], exc)
            continue
        raw_path = save_raw_snapshot(
            f"airline_nbs_{release['release_id']}",
            response.content,
            file_ext="html",
            source_url=release["url"],
        )
        rows.extend(
            _parse_release(
                release,
                payload=response.content,
                raw_path=str(raw_path),
                retrieved=retrieved,
            )
        )
    if not rows:
        raise ValueError("No NBS metrics parsed from any release")
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if OUTPUT_PATH.exists():
        prior = pd.read_csv(OUTPUT_PATH)
        result = pd.DataFrame(
            [*prior.to_dict("records"), *result.to_dict("records")],
            columns=OUTPUT_COLUMNS,
        )
    result = result.drop_duplicates(
        subset=["release_id", "metric", "scope"], keep="last"
    ).reindex(columns=OUTPUT_COLUMNS)
    result = result.sort_values(
        ["source_release_date", "metric", "scope"]
    ).reset_index(drop=True)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "fetch_airline_nbs_demand",
    "source_path",
]
