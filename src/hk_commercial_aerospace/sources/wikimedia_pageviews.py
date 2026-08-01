"""Wikimedia Wikipedia pageview attention signals for commercial aerospace.

The production contract is a curated English Wikipedia page basket with the
four Wikimedia agent classes kept separate. This measures Wikipedia attention,
not unique people, search volume, revenue or mainland-China domestic demand.
Massviews remains a discovery tool; it is intentionally not used as the
scheduled production basket because categories are noisy and can change.
"""

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
    WIKIMEDIA_AEROSPACE_PAGES,
    WIKIMEDIA_PAGEVIEWS_AGENTS,
    WIKIMEDIA_PAGEVIEWS_API_BASE,
    WIKIMEDIA_PAGEVIEWS_PROJECT,
    WIKIMEDIA_PAGEVIEWS_REQUEST_DELAY_SECONDS,
    WIKIMEDIA_PAGEVIEWS_START_DATE,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "page_id",
    "page_title",
    "page_label",
    "topic_group",
    "project",
    "access",
    "agent",
    "month",
    "views",
    "fetched_at",
    "source_url",
]
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
AGENT_MONTHLY_COLUMNS = ["month", "agent", "views", "fetched_at"]
AGENT_WEEKLY_COLUMNS = ["week", "agent", "views", "fetched_at"]
USER_PAGE_MONTHLY_COLUMNS = ["month", "page_id", "page_label", "topic_group", "views", "fetched_at"]
LATEST_PAGE_AGENT_COLUMNS = [
    "page_id",
    "page_label",
    "topic_group",
    "agent",
    "latest_month",
    "latest_views",
    "trailing_12m_views",
    "fetched_at",
]

NORMALIZED_PATH = NORMALIZED_DIR / "wikimedia_aerospace_pageviews_monthly.jsonl"
MANIFEST_PATH = NORMALIZED_DIR / "wikimedia_aerospace_pageviews_manifest.json"
WEEKLY_NORMALIZED_PATH = NORMALIZED_DIR / "wikimedia_aerospace_pageviews_weekly.jsonl"
WEEKLY_MANIFEST_PATH = NORMALIZED_DIR / "wikimedia_aerospace_pageviews_weekly_manifest.json"


def _empty_frame(columns: list[str] = SCHEMA_COLUMNS) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _previous_month_anchor() -> str:
    """Return the first day of the current month as the API end anchor."""
    today = datetime.now(timezone.utc).date()
    return today.replace(day=1).strftime("%Y%m%d")


def _previous_day_anchor() -> str:
    """Return yesterday's UTC date so the current partial day is excluded."""
    today = datetime.now(timezone.utc).date()
    return (today - timedelta(days=1)).strftime("%Y%m%d")


def _page_url(title: str, *, agent: str, start_date: str, end_date: str) -> str:
    encoded_title = quote(title.replace(" ", "_"), safe="")
    return (
        f"{WIKIMEDIA_PAGEVIEWS_API_BASE}/{WIKIMEDIA_PAGEVIEWS_PROJECT}/"
        f"all-access/{agent}/{encoded_title}/monthly/{start_date}/{end_date}"
    )


def _daily_page_url(title: str, *, agent: str, start_date: str, end_date: str) -> str:
    encoded_title = quote(title.replace(" ", "_"), safe="")
    return (
        f"{WIKIMEDIA_PAGEVIEWS_API_BASE}/{WIKIMEDIA_PAGEVIEWS_PROJECT}/"
        f"all-access/{agent}/{encoded_title}/daily/{start_date}/{end_date}"
    )


def _parse_items(
    payload: dict,
    page: dict,
    *,
    agent: str,
    fetched_at: str,
    source_url: str,
) -> list[dict]:
    rows = []
    for item in payload.get("items", []):
        timestamp = str(item.get("timestamp", ""))
        month = timestamp[:6]
        if len(month) != 6 or not month.isdigit():
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
            "month": f"{month[:4]}-{month[4:6]}",
            "views": int(views),
            "fetched_at": fetched_at,
            "source_url": source_url,
        })
    return rows


def _parse_daily_items(
    payload: dict,
    page: dict,
    *,
    agent: str,
    fetched_at: str,
    source_url: str,
) -> list[dict]:
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


def _load_normalized() -> pd.DataFrame:
    if not NORMALIZED_PATH.exists():
        return _empty_frame()
    rows = []
    for line in NORMALIZED_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("Skipping malformed Wikimedia pageviews row")
    return pd.DataFrame(rows, columns=SCHEMA_COLUMNS)


def _load_weekly_normalized() -> pd.DataFrame:
    if not WEEKLY_NORMALIZED_PATH.exists():
        return pd.DataFrame(columns=AGENT_WEEKLY_COLUMNS)
    rows = []
    for line in WEEKLY_NORMALIZED_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("Skipping malformed Wikimedia weekly pageviews row")
    return pd.DataFrame(rows, columns=AGENT_WEEKLY_COLUMNS)


def _persist_normalized(frame: pd.DataFrame, *, fetched_at: str, source: str) -> None:
    if frame.empty:
        return
    NORMALIZED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with NORMALIZED_PATH.open("w", encoding="utf-8") as handle:
        for row in frame.to_dict(orient="records"):
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    manifest = {
        "dataset": "wikimedia_aerospace_pageviews_monthly",
        "source": "Wikimedia Pageviews API",
        "source_url": WIKIMEDIA_PAGEVIEWS_API_BASE,
        "project": WIKIMEDIA_PAGEVIEWS_PROJECT,
        "pages": [page["title"] for page in WIKIMEDIA_AEROSPACE_PAGES],
        "agents": list(WIKIMEDIA_PAGEVIEWS_AGENTS),
        "grain": "Wikipedia page × agent × month",
        "history_start": str(frame["month"].min()),
        "history_end": str(frame["month"].max()),
        "records": int(len(frame)),
        "source_status": source,
        "caveat": "Wikipedia pageviews are page loads, not unique people or domestic mainland-China demand.",
        "fetched_at": fetched_at,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _persist_weekly_normalized(frame: pd.DataFrame, *, fetched_at: str, source: str) -> None:
    if frame.empty:
        return
    WEEKLY_NORMALIZED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with WEEKLY_NORMALIZED_PATH.open("w", encoding="utf-8") as handle:
        for row in frame.to_dict(orient="records"):
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    manifest = {
        "dataset": "wikimedia_aerospace_pageviews_weekly",
        "source": "Wikimedia Pageviews API",
        "source_url": WIKIMEDIA_PAGEVIEWS_API_BASE,
        "project": WIKIMEDIA_PAGEVIEWS_PROJECT,
        "pages": [page["title"] for page in WIKIMEDIA_AEROSPACE_PAGES],
        "agents": list(WIKIMEDIA_PAGEVIEWS_AGENTS),
        "grain": "Curated Wikipedia aerospace page basket × agent × complete Monday-Sunday week",
        "history_start": str(frame["week"].min()),
        "history_end": str(frame["week"].max()),
        "records": int(len(frame)),
        "source_status": source,
        "source_granularity": "daily",
        "caveat": "Weekly totals are derived from daily page loads; they are not unique people or domestic mainland-China demand.",
        "fetched_at": fetched_at,
    }
    WEEKLY_MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_wikipedia_aerospace_pageviews(
    *,
    start_date: str = WIKIMEDIA_PAGEVIEWS_START_DATE,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Fetch monthly Pageviews for the curated page basket and all agents.

    A partial fetch is returned as ``source='partial'``. If all requests fail,
    the previous normalized snapshot is used as ``source='cache'`` when it is
    available; a missing source is never presented as live.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    end_date = end_date or _previous_month_anchor()
    cached = _load_normalized()
    request_start_date = start_date
    expected_combinations = {
        (page["page_id"], agent)
        for page in WIKIMEDIA_AEROSPACE_PAGES
        for agent in WIKIMEDIA_PAGEVIEWS_AGENTS
    }
    cached_combinations = (
        set(map(tuple, cached[["page_id", "agent"]].drop_duplicates().to_records(index=False)))
        if not cached.empty
        else set()
    )
    if not cached.empty and cached_combinations == expected_combinations:
        cached_last_month = pd.PeriodIndex(cached["month"], freq="M").max()
        refresh_month = cached_last_month - 1
        request_start_date = f"{refresh_month.year:04d}{refresh_month.month:02d}01"
    rows: list[dict] = []
    failures: list[str] = []
    raw_payloads: list[dict] = []
    last_request_at = 0.0

    for page in WIKIMEDIA_AEROSPACE_PAGES:
        for agent in WIKIMEDIA_PAGEVIEWS_AGENTS:
            source_url = _page_url(page["title"], agent=agent, start_date=request_start_date, end_date=end_date)
            try:
                wait = WIKIMEDIA_PAGEVIEWS_REQUEST_DELAY_SECONDS - (time.monotonic() - last_request_at)
                if wait > 0:
                    time.sleep(wait)
                response = requests.get(
                    source_url,
                    headers={**DEFAULT_HEADERS, "User-Agent": "AsiaMarketsData/1.0 Wikimedia pageviews"},
                    timeout=DEFAULT_TIMEOUT * 3,
                )
                last_request_at = time.monotonic()
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    retry_seconds = float(retry_after) if retry_after and retry_after.isdigit() else 5.0
                    time.sleep(min(max(retry_seconds, 5.0), 60.0))
                    response = requests.get(
                        source_url,
                        headers={**DEFAULT_HEADERS, "User-Agent": "AsiaMarketsData/1.0 Wikimedia pageviews"},
                        timeout=DEFAULT_TIMEOUT * 3,
                    )
                    last_request_at = time.monotonic()
                response.raise_for_status()
                payload = response.json()
                parsed = _parse_items(
                    payload,
                    page,
                    agent=agent,
                    fetched_at=fetched_at,
                    source_url=source_url,
                )
                rows.extend(parsed)
                raw_payloads.append({"page_id": page["page_id"], "agent": agent, "items": payload.get("items", [])})
            except Exception as exc:
                failures.append(f"{page['page_id']}:{agent}:{exc}")
                logger.warning("Wikimedia pageviews fetch failed for %s/%s: %s", page["title"], agent, exc)

    live = pd.DataFrame(rows, columns=SCHEMA_COLUMNS)
    if not live.empty and not cached.empty:
        keys = ["page_id", "agent", "month"]
        live_keys = set(map(tuple, live[keys].to_records(index=False)))
        cached = cached[~cached[keys].apply(tuple, axis=1).isin(live_keys)]
        live = pd.concat([cached, live], ignore_index=True)
    elif live.empty and not cached.empty:
        live = cached.copy()

    if live.empty:
        result = _empty_frame()
        result.attrs.update({"source": "unavailable", "fetched_at": fetched_at, "failures": failures})
        return result

    live = (
        live.drop_duplicates(["page_id", "agent", "month"], keep="last")
        .sort_values(["month", "page_id", "agent"], kind="stable")
        .reset_index(drop=True)
    )
    if rows:
        source = "live" if not failures else "partial"
        try:
            save_raw_snapshot(
                "wikimedia_aerospace_pageviews",
                {"requests": raw_payloads, "failures": failures},
                source_url=WIKIMEDIA_PAGEVIEWS_API_BASE,
            )
        except Exception as exc:
            logger.warning("Failed to persist Wikimedia pageviews raw snapshot: %s", exc)
    else:
        source = "cache"
    _persist_normalized(live, fetched_at=fetched_at, source=source)
    live.attrs.update({
        "source": source,
        "fetched_at": fetched_at,
        "source_url": WIKIMEDIA_PAGEVIEWS_API_BASE,
        "failures": failures,
    })
    return live


def fetch_wikipedia_aerospace_pageviews_daily(
    *,
    start_date: str = WIKIMEDIA_PAGEVIEWS_START_DATE,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Fetch daily Pageviews and persist a compact complete-week aggregate.

    Wikimedia exposes daily and monthly per-page history, but not a native
    weekly endpoint. The daily rows are therefore the source grain and the
    persisted weekly file is derived only from complete Monday-Sunday weeks.
    After the first backfill, only a short overlap around the latest cached
    week is requested so recent revisions are picked up without repeatedly
    downloading the full history.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    end_date = end_date or _previous_day_anchor()
    cached_weekly = _load_weekly_normalized()
    request_start_date = start_date
    if not cached_weekly.empty:
        latest_week = pd.Timestamp(cached_weekly["week"].max())
        request_start_date = (latest_week - pd.Timedelta(days=14)).strftime("%Y%m%d")

    rows: list[dict] = []
    failures: list[str] = []
    raw_payloads: list[dict] = []
    last_request_at = 0.0
    for page in WIKIMEDIA_AEROSPACE_PAGES:
        for agent in WIKIMEDIA_PAGEVIEWS_AGENTS:
            source_url = _daily_page_url(page["title"], agent=agent, start_date=request_start_date, end_date=end_date)
            try:
                wait = WIKIMEDIA_PAGEVIEWS_REQUEST_DELAY_SECONDS - (time.monotonic() - last_request_at)
                if wait > 0:
                    time.sleep(wait)
                response = requests.get(
                    source_url,
                    headers={**DEFAULT_HEADERS, "User-Agent": "AsiaMarketsData/1.0 Wikimedia pageviews"},
                    timeout=DEFAULT_TIMEOUT * 3,
                )
                last_request_at = time.monotonic()
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    retry_seconds = float(retry_after) if retry_after and retry_after.isdigit() else 5.0
                    time.sleep(min(max(retry_seconds, 5.0), 60.0))
                    response = requests.get(
                        source_url,
                        headers={**DEFAULT_HEADERS, "User-Agent": "AsiaMarketsData/1.0 Wikimedia pageviews"},
                        timeout=DEFAULT_TIMEOUT * 3,
                    )
                    last_request_at = time.monotonic()
                response.raise_for_status()
                payload = response.json()
                parsed = _parse_daily_items(
                    payload,
                    page,
                    agent=agent,
                    fetched_at=fetched_at,
                    source_url=source_url,
                )
                rows.extend(parsed)
                raw_payloads.append({"page_id": page["page_id"], "agent": agent, "items": payload.get("items", [])})
            except Exception as exc:
                failures.append(f"{page['page_id']}:{agent}:{exc}")
                logger.warning("Wikimedia daily pageviews fetch failed for %s/%s: %s", page["title"], agent, exc)

    live = pd.DataFrame(rows, columns=DAILY_SCHEMA_COLUMNS)
    source = "unavailable"
    if not live.empty:
        source = "live" if not failures else "partial"
        live = (
            live.drop_duplicates(["page_id", "agent", "date"], keep="last")
            .sort_values(["date", "page_id", "agent"], kind="stable")
            .reset_index(drop=True)
        )
        try:
            save_raw_snapshot(
                "wikimedia_aerospace_pageviews_daily",
                {"requests": raw_payloads, "failures": failures},
                source_url=WIKIMEDIA_PAGEVIEWS_API_BASE,
            )
        except Exception as exc:
            logger.warning("Failed to persist Wikimedia daily pageviews raw snapshot: %s", exc)

    weekly = pd.DataFrame(columns=AGENT_WEEKLY_COLUMNS)
    if source == "live" or (source == "partial" and cached_weekly.empty):
        weekly = build_agent_weekly_summary(live, lookback_weeks=None)
        if not cached_weekly.empty:
            replace_keys = set(map(tuple, weekly[["week", "agent"]].to_records(index=False)))
            cached_weekly = cached_weekly[
                ~cached_weekly[["week", "agent"]].apply(tuple, axis=1).isin(replace_keys)
            ]
            weekly = pd.concat([cached_weekly, weekly], ignore_index=True)
        weekly = weekly.drop_duplicates(["week", "agent"], keep="last").copy()
        weekly["_agent_order"] = pd.Categorical(
            weekly["agent"], categories=list(WIKIMEDIA_PAGEVIEWS_AGENTS), ordered=True
        )
        weekly = (
            weekly.sort_values(["week", "_agent_order"], kind="stable")
            .drop(columns="_agent_order")
            .reset_index(drop=True)
        )
        _persist_weekly_normalized(weekly, fetched_at=fetched_at, source=source)
    elif not cached_weekly.empty:
        source = "cache"
        weekly = cached_weekly

    live.attrs.update({
        "source": source,
        "fetched_at": fetched_at,
        "source_url": WIKIMEDIA_PAGEVIEWS_API_BASE,
        "failures": failures,
        "weekly_summary": weekly.reset_index(drop=True),
    })
    return live


def build_agent_monthly_summary(frame: pd.DataFrame, *, lookback_months: int = 120) -> pd.DataFrame:
    """Build a compact all-page monthly total by Wikimedia agent."""
    if frame.empty:
        return pd.DataFrame(columns=AGENT_MONTHLY_COLUMNS)
    work = frame.copy()
    work["month_period"] = pd.PeriodIndex(work["month"], freq="M")
    last_month = work["month_period"].max()
    first_month = max(work["month_period"].min(), last_month - (lookback_months - 1))
    work = work[work["month_period"].between(first_month, last_month)]
    grouped = work.groupby(["month", "agent"], as_index=False)["views"].sum()
    months = pd.period_range(first_month, last_month, freq="M").astype(str).tolist()
    grid = pd.MultiIndex.from_product([months, list(WIKIMEDIA_PAGEVIEWS_AGENTS)], names=["month", "agent"]).to_frame(index=False)
    result = grid.merge(grouped, on=["month", "agent"], how="left")
    result["views"] = result["views"].fillna(0).astype(int)
    result["fetched_at"] = frame["fetched_at"].dropna().iloc[-1] if frame["fetched_at"].notna().any() else None
    return result[AGENT_MONTHLY_COLUMNS]


def build_agent_weekly_summary(frame: pd.DataFrame, *, lookback_weeks: int | None = 520) -> pd.DataFrame:
    """Build all-page weekly totals from daily rows, Monday through Sunday."""
    if frame.empty:
        return pd.DataFrame(columns=AGENT_WEEKLY_COLUMNS)
    work = frame.copy()
    work["date_value"] = pd.to_datetime(work["date"], errors="coerce")
    work = work[work["date_value"].notna()]
    if work.empty:
        return pd.DataFrame(columns=AGENT_WEEKLY_COLUMNS)
    work["week_period"] = work["date_value"].dt.to_period("W-SUN")
    latest_period = work["week_period"].max()
    if latest_period.end_time.date() > work["date_value"].max().date():
        latest_period = latest_period - 1
    first_period = latest_period - (lookback_weeks - 1) if lookback_weeks else work["week_period"].min()
    work = work[work["week_period"].between(first_period, latest_period)]
    if work.empty:
        return pd.DataFrame(columns=AGENT_WEEKLY_COLUMNS)
    grouped = work.groupby(["week_period", "agent"], as_index=False)["views"].sum()
    grouped["week"] = grouped["week_period"].map(lambda value: value.start_time.strftime("%Y-%m-%d"))
    weeks = pd.period_range(first_period, latest_period, freq="W-SUN")
    grid = pd.MultiIndex.from_product(
        [weeks.astype(str).tolist(), list(WIKIMEDIA_PAGEVIEWS_AGENTS)],
        names=["week_period", "agent"],
    ).to_frame(index=False)
    grid["week"] = pd.PeriodIndex(grid["week_period"], freq="W-SUN").map(lambda value: value.start_time.strftime("%Y-%m-%d"))
    result = grid[["week", "agent"]].merge(grouped[["week", "agent", "views"]], on=["week", "agent"], how="left")
    result["views"] = result["views"].fillna(0).astype(int)
    result["fetched_at"] = frame["fetched_at"].dropna().iloc[-1] if frame["fetched_at"].notna().any() else None
    return result[AGENT_WEEKLY_COLUMNS]


def load_agent_weekly_summary() -> pd.DataFrame:
    """Load the persisted weekly aggregate for artifact fallback or inspection."""
    return _load_weekly_normalized()


def build_user_page_monthly_summary(frame: pd.DataFrame, *, lookback_months: int = 120) -> pd.DataFrame:
    """Build the page-level user-view history used by the long chart."""
    if frame.empty:
        return pd.DataFrame(columns=USER_PAGE_MONTHLY_COLUMNS)
    work = frame[frame["agent"] == "user"].copy()
    if work.empty:
        return pd.DataFrame(columns=USER_PAGE_MONTHLY_COLUMNS)
    work["month_period"] = pd.PeriodIndex(work["month"], freq="M")
    last_month = work["month_period"].max()
    first_month = max(work["month_period"].min(), last_month - (lookback_months - 1))
    work = work[work["month_period"].between(first_month, last_month)]
    grouped = work.groupby(["month", "page_id"], as_index=False)["views"].sum()
    months = pd.period_range(first_month, last_month, freq="M").astype(str).tolist()
    pages = pd.DataFrame(WIKIMEDIA_AEROSPACE_PAGES).rename(columns={"label": "page_label"})
    grid = pd.MultiIndex.from_product(
        [months, pages["page_id"].tolist()], names=["month", "page_id"]
    ).to_frame(index=False)
    result = grid.merge(grouped, on=["month", "page_id"], how="left")
    result = result.merge(pages[["page_id", "page_label", "topic_group"]], on="page_id", how="left")
    result["views"] = result["views"].fillna(0).astype(int)
    result = result.sort_values(["month", "page_id"], kind="stable").reset_index(drop=True)
    result["fetched_at"] = frame["fetched_at"].dropna().iloc[-1] if frame["fetched_at"].notna().any() else None
    return result[USER_PAGE_MONTHLY_COLUMNS]


def build_latest_page_agent_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Build a latest-month and trailing-12-month audit table."""
    if frame.empty:
        return pd.DataFrame(columns=LATEST_PAGE_AGENT_COLUMNS)
    work = frame.copy()
    work["month_period"] = pd.PeriodIndex(work["month"], freq="M")
    latest_month = work["month_period"].max()
    trailing_start = latest_month - 11
    trailing = work[work["month_period"].between(trailing_start, latest_month)]
    latest = work[work["month_period"] == latest_month].groupby(
        ["page_id", "page_label", "topic_group", "agent"], as_index=False
    )["views"].sum().rename(columns={"views": "latest_views"})
    trailing_sum = trailing.groupby(["page_id", "agent"], as_index=False)["views"].sum().rename(
        columns={"views": "trailing_12m_views"}
    )
    grid = pd.MultiIndex.from_product(
        [
            [page["page_id"] for page in WIKIMEDIA_AEROSPACE_PAGES],
            list(WIKIMEDIA_PAGEVIEWS_AGENTS),
        ],
        names=["page_id", "agent"],
    ).to_frame(index=False)
    metadata = pd.DataFrame(WIKIMEDIA_AEROSPACE_PAGES).rename(columns={"label": "page_label"})
    result = grid.merge(metadata[["page_id", "page_label", "topic_group"]], on="page_id", how="left")
    result = result.merge(latest, on=["page_id", "page_label", "topic_group", "agent"], how="left")
    result = result.merge(trailing_sum, on=["page_id", "agent"], how="left")
    result["latest_views"] = result["latest_views"].fillna(0).astype(int)
    result["trailing_12m_views"] = result["trailing_12m_views"].fillna(0).astype(int)
    result["latest_month"] = str(latest_month)
    result["fetched_at"] = frame["fetched_at"].dropna().iloc[-1] if frame["fetched_at"].notna().any() else None
    return result[LATEST_PAGE_AGENT_COLUMNS].sort_values(["page_id", "agent"], kind="stable").reset_index(drop=True)
