"""Wikimedia Pageviews attention signals for the stablecoin and crypto sector."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pandas as pd
import requests

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    NORMALIZED_DIR,
    WIKIMEDIA_CRYPTO_PAGES,
    WIKIMEDIA_PAGEVIEWS_AGENTS,
    WIKIMEDIA_PAGEVIEWS_API_BASE,
    WIKIMEDIA_PAGEVIEWS_PROJECT,
    WIKIMEDIA_PAGEVIEWS_REQUEST_DELAY_SECONDS,
    WIKIMEDIA_PAGEVIEWS_START_DATE,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

DAILY_SCHEMA_COLUMNS = [
    "page_id",
    "page_title",
    "page_label",
    "topic_group",
    "project",
    "access",
    "agent",
    "date",
    "views",
    "fetched_at",
    "source_url",
]
AGENT_WEEKLY_COLUMNS = ["week", "agent", "views", "fetched_at"]
USER_PAGE_MONTHLY_COLUMNS = ["month", "page_id", "page_label", "topic_group", "views", "fetched_at"]
LATEST_PAGE_COLUMNS = [
    "page_id",
    "page_label",
    "topic_group",
    "latest_month",
    "latest_views",
    "trailing_12m_views",
    "fetched_at",
]

WEEKLY_NORMALIZED_PATH = NORMALIZED_DIR / "wikimedia_crypto_pageviews_weekly.jsonl"
WEEKLY_MANIFEST_PATH = NORMALIZED_DIR / "wikimedia_crypto_pageviews_weekly_manifest.json"
MONTHLY_NORMALIZED_PATH = NORMALIZED_DIR / "wikimedia_crypto_pageviews_user_monthly.jsonl"
MONTHLY_MANIFEST_PATH = NORMALIZED_DIR / "wikimedia_crypto_pageviews_user_monthly_manifest.json"


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _previous_day_anchor() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).strftime("%Y%m%d")


def _page_url(title: str, *, agent: str, start_date: str, end_date: str) -> str:
    encoded_title = quote(title.replace(" ", "_"), safe="")
    return (
        f"{WIKIMEDIA_PAGEVIEWS_API_BASE}/{WIKIMEDIA_PAGEVIEWS_PROJECT}/"
        f"all-access/{agent}/{encoded_title}/daily/{start_date}/{end_date}"
    )


def _parse_items(payload: dict, page: dict, *, agent: str, fetched_at: str, source_url: str) -> list[dict]:
    rows = []
    for item in payload.get("items", []):
        timestamp = str(item.get("timestamp", ""))
        day = timestamp[:8]
        if len(day) != 8 or not day.isdigit():
            continue
        views = pd.to_numeric(item.get("views"), errors="coerce")
        if pd.isna(views):
            continue
        rows.append({
            "page_id": page["page_id"],
            "page_title": str(item.get("article") or page["title"]),
            "page_label": page["label"],
            "topic_group": page["topic_group"],
            "project": str(item.get("project") or WIKIMEDIA_PAGEVIEWS_PROJECT.replace(".org", "")),
            "access": str(item.get("access") or "all-access"),
            "agent": str(item.get("agent") or agent),
            "date": f"{day[:4]}-{day[4:6]}-{day[6:8]}",
            "views": int(views),
            "fetched_at": fetched_at,
            "source_url": source_url,
        })
    return rows


def _load_weekly_cache() -> pd.DataFrame:
    if not WEEKLY_NORMALIZED_PATH.exists():
        return _empty_frame(AGENT_WEEKLY_COLUMNS)
    rows = []
    for line in WEEKLY_NORMALIZED_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("Skipping malformed crypto Wikimedia weekly row")
    return pd.DataFrame(rows, columns=AGENT_WEEKLY_COLUMNS)


def _load_monthly_cache() -> pd.DataFrame:
    if not MONTHLY_NORMALIZED_PATH.exists():
        return _empty_frame(USER_PAGE_MONTHLY_COLUMNS)
    rows = []
    for line in MONTHLY_NORMALIZED_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("Skipping malformed crypto Wikimedia monthly row")
    return pd.DataFrame(rows, columns=USER_PAGE_MONTHLY_COLUMNS)


def _persist_weekly(frame: pd.DataFrame, *, fetched_at: str, source: str) -> None:
    if frame.empty:
        return
    WEEKLY_NORMALIZED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with WEEKLY_NORMALIZED_PATH.open("w", encoding="utf-8") as handle:
        for row in frame.to_dict(orient="records"):
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    manifest = {
        "dataset": "wikimedia_crypto_pageviews_weekly",
        "source": "Wikimedia Pageviews API",
        "source_url": WIKIMEDIA_PAGEVIEWS_API_BASE,
        "project": WIKIMEDIA_PAGEVIEWS_PROJECT,
        "pages": [page["title"] for page in WIKIMEDIA_CRYPTO_PAGES],
        "agents": list(WIKIMEDIA_PAGEVIEWS_AGENTS),
        "grain": "Curated crypto Wikipedia page basket × agent × complete Monday-Sunday week",
        "history_start": str(frame["week"].min()),
        "history_end": str(frame["week"].max()),
        "records": int(len(frame)),
        "source_status": source,
        "source_granularity": "daily",
        "caveat": "Wikipedia pageviews are page loads, not unique people, trading activity, or Hong Kong adoption.",
        "fetched_at": fetched_at,
    }
    WEEKLY_MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _persist_monthly(frame: pd.DataFrame, *, fetched_at: str, source: str) -> None:
    if frame.empty:
        return
    MONTHLY_NORMALIZED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MONTHLY_NORMALIZED_PATH.open("w", encoding="utf-8") as handle:
        for row in frame.to_dict(orient="records"):
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    manifest = {
        "dataset": "wikimedia_crypto_pageviews_user_monthly",
        "source": "Wikimedia Pageviews API",
        "source_url": WIKIMEDIA_PAGEVIEWS_API_BASE,
        "project": WIKIMEDIA_PAGEVIEWS_PROJECT,
        "pages": [page["title"] for page in WIKIMEDIA_CRYPTO_PAGES],
        "agent": "user",
        "grain": "Curated crypto Wikipedia page × complete calendar month",
        "history_start": str(frame["month"].min()),
        "history_end": str(frame["month"].max()),
        "records": int(len(frame)),
        "source_status": source,
        "source_granularity": "daily",
        "caveat": "Monthly user totals are Wikipedia page loads, not unique people, trading activity, or Hong Kong adoption.",
        "fetched_at": fetched_at,
    }
    MONTHLY_MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_agent_weekly_summary(frame: pd.DataFrame, *, lookback_weeks: int | None = 520) -> pd.DataFrame:
    """Aggregate daily pageviews across the basket into complete Monday-Sunday weeks."""
    if frame.empty:
        return _empty_frame(AGENT_WEEKLY_COLUMNS)
    work = frame.copy()
    work["date_value"] = pd.to_datetime(work["date"], errors="coerce")
    work = work[work["date_value"].notna()]
    if work.empty:
        return _empty_frame(AGENT_WEEKLY_COLUMNS)
    work["week_period"] = work["date_value"].dt.to_period("W-SUN")
    latest_period = work["week_period"].max()
    if latest_period.end_time.date() > work["date_value"].max().date():
        latest_period -= 1
    first_period = latest_period - (lookback_weeks - 1) if lookback_weeks else work["week_period"].min()
    work = work[work["week_period"].between(first_period, latest_period)]
    if work.empty:
        return _empty_frame(AGENT_WEEKLY_COLUMNS)
    grouped = work.groupby(["week_period", "agent"], as_index=False)["views"].sum()
    grouped["week"] = grouped["week_period"].map(lambda value: value.start_time.strftime("%Y-%m-%d"))
    weeks = pd.period_range(first_period, latest_period, freq="W-SUN")
    grid = pd.MultiIndex.from_product(
        [weeks.astype(str).tolist(), list(WIKIMEDIA_PAGEVIEWS_AGENTS)],
        names=["week_period", "agent"],
    ).to_frame(index=False)
    grid["week"] = pd.PeriodIndex(grid["week_period"], freq="W-SUN").map(
        lambda value: value.start_time.strftime("%Y-%m-%d")
    )
    result = grid[["week", "agent"]].merge(
        grouped[["week", "agent", "views"]], on=["week", "agent"], how="left"
    )
    result["views"] = result["views"].fillna(0).astype(int)
    result["fetched_at"] = frame["fetched_at"].dropna().iloc[-1] if frame["fetched_at"].notna().any() else None
    return result[AGENT_WEEKLY_COLUMNS]


def build_user_page_monthly_summary(frame: pd.DataFrame, *, lookback_months: int = 120) -> pd.DataFrame:
    """Build monthly user pageviews by page for a compact future Streamlit view."""
    if frame.empty:
        return _empty_frame(USER_PAGE_MONTHLY_COLUMNS)
    work = frame[frame["agent"] == "user"].copy()
    work["date_value"] = pd.to_datetime(work["date"], errors="coerce")
    work = work[work["date_value"].notna()]
    if work.empty:
        return _empty_frame(USER_PAGE_MONTHLY_COLUMNS)
    work["month_period"] = work["date_value"].dt.to_period("M")
    latest_month = work["month_period"].max()
    if latest_month.end_time.date() > work["date_value"].max().date():
        latest_month -= 1
    first_month = max(work["month_period"].min(), latest_month - (lookback_months - 1))
    work = work[work["month_period"].between(first_month, latest_month)]
    grouped = work.groupby(["month_period", "page_id"], as_index=False)["views"].sum()
    grouped["month"] = grouped["month_period"].astype(str)
    pages = pd.DataFrame(WIKIMEDIA_CRYPTO_PAGES).rename(columns={"label": "page_label"})
    months = pd.period_range(first_month, latest_month, freq="M").astype(str).tolist()
    grid = pd.MultiIndex.from_product(
        [months, pages["page_id"].tolist()], names=["month", "page_id"]
    ).to_frame(index=False)
    result = grid.merge(grouped[["month", "page_id", "views"]], on=["month", "page_id"], how="left")
    result = result.merge(pages[["page_id", "page_label", "topic_group"]], on="page_id", how="left")
    result["views"] = result["views"].fillna(0).astype(int)
    result["fetched_at"] = frame["fetched_at"].dropna().iloc[-1] if frame["fetched_at"].notna().any() else None
    return result[USER_PAGE_MONTHLY_COLUMNS]


def build_latest_page_summary(monthly_frame: pd.DataFrame) -> pd.DataFrame:
    if monthly_frame.empty:
        return _empty_frame(LATEST_PAGE_COLUMNS)
    latest_month = str(monthly_frame["month"].max())
    trailing_months = sorted(monthly_frame["month"].unique())[-12:]
    latest = monthly_frame[monthly_frame["month"] == latest_month].rename(columns={"views": "latest_views"})
    trailing = (
        monthly_frame[monthly_frame["month"].isin(trailing_months)]
        .groupby(["page_id"], as_index=False)["views"]
        .sum()
        .rename(columns={"views": "trailing_12m_views"})
    )
    result = latest[["page_id", "page_label", "topic_group", "latest_views", "fetched_at"]].merge(
        trailing, on="page_id", how="left"
    )
    result["latest_month"] = latest_month
    result["trailing_12m_views"] = result["trailing_12m_views"].fillna(0).astype(int)
    return result[LATEST_PAGE_COLUMNS].sort_values("page_id").reset_index(drop=True)


def fetch_wikipedia_crypto_pageviews_daily(
    *, start_date: str = WIKIMEDIA_PAGEVIEWS_START_DATE, end_date: str | None = None
) -> pd.DataFrame:
    """Fetch daily crypto Pageviews and persist a complete-week aggregate."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    end_date = end_date or _previous_day_anchor()
    cached_weekly = _load_weekly_cache()
    cached_monthly = _load_monthly_cache()
    request_start_date = start_date
    if not cached_weekly.empty:
        latest_week = pd.Timestamp(cached_weekly["week"].max())
        request_start_date = (latest_week - pd.Timedelta(days=14)).strftime("%Y%m%d")
    if not cached_monthly.empty:
        latest_month = pd.Period(str(cached_monthly["month"].max()), freq="M")
        monthly_refresh_start = (latest_month - 1).start_time.strftime("%Y%m%d")
        request_start_date = min(request_start_date, monthly_refresh_start)

    rows: list[dict] = []
    failures: list[str] = []
    raw_payloads: list[dict] = []
    last_request_at = 0.0
    for page in WIKIMEDIA_CRYPTO_PAGES:
        for agent in WIKIMEDIA_PAGEVIEWS_AGENTS:
            source_url = _page_url(page["title"], agent=agent, start_date=request_start_date, end_date=end_date)
            try:
                wait = WIKIMEDIA_PAGEVIEWS_REQUEST_DELAY_SECONDS - (time.monotonic() - last_request_at)
                if wait > 0:
                    time.sleep(wait)
                response = requests.get(
                    source_url,
                    headers={**DEFAULT_HEADERS, "User-Agent": "AsiaMarketsData/1.0 Wikimedia crypto pageviews"},
                    timeout=DEFAULT_TIMEOUT * 3,
                )
                last_request_at = time.monotonic()
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    retry_seconds = float(retry_after) if retry_after and retry_after.isdigit() else 5.0
                    time.sleep(min(max(retry_seconds, 5.0), 60.0))
                    response = requests.get(
                        source_url,
                        headers={**DEFAULT_HEADERS, "User-Agent": "AsiaMarketsData/1.0 Wikimedia crypto pageviews"},
                        timeout=DEFAULT_TIMEOUT * 3,
                    )
                    last_request_at = time.monotonic()
                response.raise_for_status()
                payload = response.json()
                rows.extend(_parse_items(payload, page, agent=agent, fetched_at=fetched_at, source_url=source_url))
                raw_payloads.append({"page_id": page["page_id"], "agent": agent, "items": payload.get("items", [])})
            except Exception as exc:
                failures.append(f"{page['page_id']}:{agent}:{exc}")
                logger.warning("Crypto Wikimedia fetch failed for %s/%s: %s", page["title"], agent, exc)

    live = pd.DataFrame(rows, columns=DAILY_SCHEMA_COLUMNS)
    source = "unavailable"
    if not live.empty:
        source = "live" if not failures else "partial"
        live = live.drop_duplicates(["page_id", "agent", "date"], keep="last").sort_values(
            ["date", "page_id", "agent"], kind="stable"
        ).reset_index(drop=True)
        try:
            save_raw_snapshot(
                "wikimedia_crypto_pageviews_daily",
                {"requests": raw_payloads, "failures": failures},
                source_url=WIKIMEDIA_PAGEVIEWS_API_BASE,
            )
        except Exception as exc:
            logger.warning("Failed to save crypto Wikimedia raw snapshot: %s", exc)

    if source == "live" or (source == "partial" and cached_weekly.empty):
        weekly = build_agent_weekly_summary(live, lookback_weeks=None)
        monthly = build_user_page_monthly_summary(live)
        if not cached_weekly.empty:
            replace_keys = set(map(tuple, weekly[["week", "agent"]].to_records(index=False)))
            cached_weekly = cached_weekly[
                ~cached_weekly[["week", "agent"]].apply(tuple, axis=1).isin(replace_keys)
            ]
            weekly = pd.concat([cached_weekly, weekly], ignore_index=True)
        if not cached_monthly.empty:
            replace_keys = set(map(tuple, monthly[["month", "page_id"]].to_records(index=False)))
            cached_monthly = cached_monthly[
                ~cached_monthly[["month", "page_id"]].apply(tuple, axis=1).isin(replace_keys)
            ]
            monthly = pd.concat([cached_monthly, monthly], ignore_index=True)
        weekly = weekly.drop_duplicates(["week", "agent"], keep="last").copy()
        weekly["_agent_order"] = pd.Categorical(
            weekly["agent"], categories=list(WIKIMEDIA_PAGEVIEWS_AGENTS), ordered=True
        )
        weekly = weekly.sort_values(["week", "_agent_order"], kind="stable").drop(
            columns="_agent_order"
        ).reset_index(drop=True)
        monthly = monthly.drop_duplicates(["month", "page_id"], keep="last").sort_values(
            ["month", "page_id"], kind="stable"
        ).reset_index(drop=True)
        _persist_weekly(weekly, fetched_at=fetched_at, source=source)
        _persist_monthly(monthly, fetched_at=fetched_at, source=source)
    elif not cached_weekly.empty:
        source = "cache"
        weekly = cached_weekly
        monthly = cached_monthly
    else:
        weekly = _empty_frame(AGENT_WEEKLY_COLUMNS)
        monthly = _empty_frame(USER_PAGE_MONTHLY_COLUMNS)

    live.attrs.update({
        "source": source,
        "fetched_at": fetched_at,
        "source_url": WIKIMEDIA_PAGEVIEWS_API_BASE,
        "failures": failures,
        "weekly_summary": weekly.reset_index(drop=True),
        "user_monthly_summary": monthly.reset_index(drop=True),
    })
    return live


def load_agent_weekly_summary() -> pd.DataFrame:
    return _load_weekly_cache()


def load_user_page_monthly_summary() -> pd.DataFrame:
    return _load_monthly_cache()
