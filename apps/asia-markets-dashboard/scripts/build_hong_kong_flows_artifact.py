"""Build the compact Hong Kong institutional-data context artifact.

The source packages and scheduled workflows own acquisition.  This builder is
read-only and consumes their canonical normalized parquet files.  In
particular, it deliberately does *not* copy ``southbound_market_flow``: that
dataset and its primary chart remain owned by the ETF Monitor artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.global_market_regime.storage import atomic_write_texts


HKMA_SOURCE_URL = (
    "https://api.hkma.gov.hk/public/market-data-and-statistics/"
    "daily-monetary-statistics/daily-figures-interbank-liquidity"
)
HKEX_SOURCE_URL = "https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Statistics/Short-Selling?sc_lang=en"
MSCI_SOURCE_URL = "https://www.msci.com/eqb/gimi/stdindex/index_review.html"
EASTMONEY_SOURCE_URL = "https://data.eastmoney.com/hsgt/hsgtV2.html"

HKMA_SERIES: dict[str, tuple[str, str]] = {
    "HKMA_HIBOR_ON": ("Overnight HIBOR", "隔夜HIBOR"),
    "HKMA_HIBOR_1M": ("1-month HIBOR", "1个月HIBOR"),
    "HKMA_AGGREGATE_BALANCE": ("Aggregate Balance", "总结余"),
    "HKMA_TWI": ("Trade-weighted index", "贸易加权指数"),
}
HKMA_HISTORY_YEARS = 5
MSCI_REVIEW_CYCLES = 8
MSCI_COUNTRIES = {"HK", "CN"}

NORMALIZED = ROOT / "data" / "normalized"
HKMA_PATH = NORMALIZED / "hkma_macro" / "hkma_observations.parquet"
HKEX_PATH = NORMALIZED / "hkex_market_flow" / "hkex_market_flow_daily.parquet"
MSCI_PATH = NORMALIZED / "msci_reviews" / "msci_rebalance_events.parquet"
SOUTHBOUND_PATH = NORMALIZED / "marts" / "southbound_market_flow.parquet"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_parquet(path: Path) -> pd.DataFrame:
    """Return an empty frame for an unavailable optional upstream snapshot."""
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _records(
    frame: pd.DataFrame,
    columns: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    out = frame.copy()
    if columns:
        out = out[[column for column in columns if column in out.columns]]
    for column in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[column]):
            out[column] = out[column].dt.strftime("%Y-%m-%d")
    for column in out.columns:
        if pd.api.types.is_float_dtype(out[column]):
            out[column] = out[column].round(4)
    return json.loads(
        out.to_json(orient="records", date_format="iso", default_handler=str)
    )


def _date_bounds(frame: pd.DataFrame, column: str) -> tuple[str | None, str | None]:
    if frame.empty or column not in frame.columns:
        return None, None
    dates = pd.to_datetime(frame[column], errors="coerce").dropna()
    if dates.empty:
        return None, None
    return dates.min().date().isoformat(), dates.max().date().isoformat()


def _health_row(
    *,
    source: str,
    series_id: str,
    frame: pd.DataFrame,
    date_column: str,
    source_url: str,
    note: str,
    status_override: str | None = None,
    records: int | None = None,
) -> dict[str, Any]:
    start, end = _date_bounds(frame, date_column)
    status = status_override or ("Healthy" if end else "Unavailable")
    return {
        "source": source,
        "series_id": series_id,
        "status": status,
        "latest_observation": end,
        "coverage_start": start,
        "records": int(len(frame) if records is None else records),
        "notes": note,
        "source_url": source_url,
    }


def _prepare_hkma(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "series_id", "value", "source_tier", "source_url", "fetched_at"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()
    out = frame.loc[frame["series_id"].isin(HKMA_SERIES)].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out = out.dropna(subset=["date", "value"])
    if out.empty:
        return out
    latest = out["date"].max()
    out = out[out["date"] >= latest - pd.DateOffset(years=HKMA_HISTORY_YEARS)].copy()
    out["series_label_en"] = out["series_id"].map(lambda value: HKMA_SERIES[str(value)][0])
    out["series_label_zh"] = out["series_id"].map(lambda value: HKMA_SERIES[str(value)][1])
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out.sort_values(["series_id", "date"]).reset_index(drop=True)


def _prepare_hkex(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "trade_date",
        "short_selling_security_count",
        "short_selling_shares_available",
        "fetched_at",
    }
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()
    out = frame.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce")
    for column in (
        "short_selling_security_count",
        "short_selling_shares_available",
    ):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    usable = out[
        ["short_selling_security_count", "short_selling_shares_available"]
    ].notna().any(axis=1)
    out = out[out["trade_date"].notna() & usable].copy()
    if out.empty:
        return out
    out["trade_date"] = out["trade_date"].dt.strftime("%Y-%m-%d")
    out["source_id"] = "hkex_market_flow_data"
    out["source_url"] = HKEX_SOURCE_URL
    return out.sort_values("trade_date").reset_index(drop=True)


def _prepare_msci(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {
        "review_cycle",
        "announcement_date",
        "effective_date",
        "action",
        "index_name",
        "country",
        "security_name",
        "size_segment",
        "source_url",
    }
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame(), pd.DataFrame()
    out = frame.loc[frame["country"].isin(MSCI_COUNTRIES)].copy()
    out["announcement_date"] = pd.to_datetime(out["announcement_date"], errors="coerce")
    out["effective_date"] = pd.to_datetime(out["effective_date"], errors="coerce")
    out = out.dropna(subset=["announcement_date"])
    if out.empty:
        return out, pd.DataFrame()
    cycle_dates = (
        out.groupby("review_cycle", dropna=False, as_index=False)["announcement_date"]
        .min()
        .sort_values("announcement_date")
    )
    cycles = cycle_dates.tail(MSCI_REVIEW_CYCLES)["review_cycle"].tolist()
    out = out[out["review_cycle"].isin(cycles)].copy()
    out["announcement_date"] = out["announcement_date"].dt.strftime("%Y-%m-%d")
    out["effective_date"] = out["effective_date"].dt.strftime("%Y-%m-%d")
    out["link_status"] = "Unlinked — public list has no usable security identifier"
    event_columns = (
        "review_cycle",
        "announcement_date",
        "effective_date",
        "action",
        "index_name",
        "country",
        "security_name",
        "size_segment",
        "link_status",
        "source_url",
    )
    events = out[[column for column in event_columns if column in out.columns]].sort_values(
        ["effective_date", "index_name", "action", "security_name"]
    )
    summary = (
        out.groupby("review_cycle", as_index=False)
        .agg(
            announcement_date=("announcement_date", "min"),
            effective_date=("effective_date", "min"),
            event_count=("security_name", "size"),
            index_count=("index_name", "nunique"),
            country_count=("country", "nunique"),
            additions=("action", lambda values: int(values.astype(str).eq("ADD").sum())),
            deletions=("action", lambda values: int(values.astype(str).eq("DELETE").sum())),
        )
        .sort_values("effective_date")
    )
    return events.reset_index(drop=True), summary.reset_index(drop=True)


def _build_artifact() -> tuple[dict[str, Any], dict[str, Any]]:
    now = _utc_now()
    generated_at = now.isoformat().replace("+00:00", "Z")

    hkma_raw = _read_parquet(HKMA_PATH)
    hkex_raw = _read_parquet(HKEX_PATH)
    msci_raw = _read_parquet(MSCI_PATH)
    southbound_raw = _read_parquet(SOUTHBOUND_PATH)

    hkma = _prepare_hkma(hkma_raw)
    hkex = _prepare_hkex(hkex_raw)
    msci_events, msci_cycles = _prepare_msci(msci_raw)

    southbound_start, southbound_end = _date_bounds(southbound_raw, "trade_date")
    source_health = [
        _health_row(
            source="HKMA Interbank Liquidity",
            series_id="hkma_liquidity",
            frame=hkma_raw,
            date_column="date",
            source_url=HKMA_SOURCE_URL,
            note="Selected HIBOR, Aggregate Balance and TWI series; the page shows the last five years and preserves source tier.",
        ),
        _health_row(
            source="HKEX Short Selling Statistics",
            series_id="hkex_short_inventory",
            frame=hkex,
            date_column="trade_date",
            source_url=HKEX_SOURCE_URL,
            note="Official daily security count and shares-available inventory. Short-selling value and ratio are not published because their normalized fields are empty or unreliable.",
        ),
        _health_row(
            source="MSCI Index Reviews",
            series_id="msci_index_events",
            frame=msci_raw,
            date_column="announcement_date",
            source_url=MSCI_SOURCE_URL,
            note="HK/CN events from the latest review cycles; names are shown as unlinked index events because public identifiers are not populated.",
        ),
        {
            "source": "Eastmoney Stock Connect",
            "series_id": "southbound_market_flow",
            "status": "Reference",
            "latest_observation": southbound_end,
            "coverage_start": southbound_start,
            "records": int(len(southbound_raw)),
            "notes": "Canonical Southbound flow remains in ETF Monitor. This artifact intentionally does not re-emit or re-render it.",
            "source_url": EASTMONEY_SOURCE_URL,
        },
    ]

    datasets = {
        "hkma_liquidity_daily": _records(
            hkma,
            (
                "date",
                "series_id",
                "series_label_en",
                "series_label_zh",
                "value",
                "source_tier",
                "source_url",
                "fetched_at",
            ),
        ),
        "hkex_short_inventory_daily": _records(
            hkex,
            (
                "trade_date",
                "short_selling_security_count",
                "short_selling_shares_available",
                "source_id",
                "source_url",
                "fetched_at",
            ),
        ),
        "msci_index_events": _records(
            msci_events,
            (
                "review_cycle",
                "announcement_date",
                "effective_date",
                "action",
                "index_name",
                "country",
                "security_name",
                "size_segment",
                "link_status",
                "source_url",
            ),
        ),
        "msci_review_cycles": _records(
            msci_cycles,
            (
                "review_cycle",
                "announcement_date",
                "effective_date",
                "event_count",
                "index_count",
                "country_count",
                "additions",
                "deletions",
            ),
        ),
        "source_health": source_health,
    }
    available_main_sources = sum(
        bool(frame is not None and not frame.empty)
        for frame in (hkma, hkex, msci_events)
    )
    overall_status = "Healthy" if available_main_sources == 3 else (
        "Partial" if available_main_sources else "Unavailable"
    )
    data_as_of_candidates = [
        pd.to_datetime(value, errors="coerce")
        for value in (
            _date_bounds(hkma_raw, "date")[1],
            _date_bounds(hkex, "trade_date")[1],
            _date_bounds(msci_raw, "announcement_date")[1],
        )
    ]
    valid_as_of = [value for value in data_as_of_candidates if pd.notna(value)]
    data_as_of = max(valid_as_of).date().isoformat() if valid_as_of else None
    snapshot_id = hashlib.sha256(
        json.dumps(datasets, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]

    sources = [
        {
            "id": "hkma_liquidity",
            "label": "HKMA Interbank Liquidity",
            "href": HKMA_SOURCE_URL,
            "query": {
                "engine": "existing normalized HKMA macro lane",
                "description": "Selected daily HIBOR, Aggregate Balance and TWI series; no runtime fetch.",
            },
        },
        {
            "id": "hkex_short_inventory",
            "label": "HKEX Short Selling Statistics",
            "href": HKEX_SOURCE_URL,
            "query": {
                "engine": "existing normalized HKEX market-flow lane",
                "description": "Daily security count and shares available; short value/ratio are excluded by the measured data contract.",
            },
        },
        {
            "id": "msci_index_events",
            "label": "MSCI Index Reviews",
            "href": MSCI_SOURCE_URL,
            "query": {
                "engine": "existing normalized MSCI review lane",
                "description": "Latest HK/CN review cycles as name-only, unlinked index events.",
            },
        },
        {
            "id": "southbound_market_flow",
            "label": "Eastmoney Stock Connect · canonical in ETF Monitor",
            "href": EASTMONEY_SOURCE_URL,
            "query": {
                "engine": "existing market-monitor artifact",
                "description": "Reference only. The Southbound dataset is intentionally not duplicated in this artifact.",
            },
        },
    ]
    artifact = {
        "manifest": {
            "version": 1,
            "generatedAt": generated_at,
            "title": "Hong Kong Flows & Liquidity",
            "description": "Institutional context for HKEX short inventory, HKMA liquidity and MSCI HK/CN index-review events. Southbound Stock Connect remains canonical in ETF Monitor.",
            "sector": "hong-kong-flows",
            "cards": [],
            "charts": [],
            "tables": [
                {
                    "id": "hkex_short_inventory_table",
                    "title": "HKEX short inventory",
                    "dataset": "hkex_short_inventory_daily",
                },
                {
                    "id": "msci_review_cycles_table",
                    "title": "MSCI HK/CN review cycles",
                    "dataset": "msci_review_cycles",
                },
                {
                    "id": "msci_index_events_table",
                    "title": "MSCI index events",
                    "dataset": "msci_index_events",
                },
            ],
            "blocks": [],
            "sources": [source["id"] for source in sources],
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready" if overall_status == "Healthy" else "partial",
            "datasets": datasets,
        },
        "sources": sources,
        "package_info": {
            "snapshotId": snapshot_id,
            "dataAsOf": data_as_of,
            "runConsistent": True,
            "southboundCanonicalPage": "/etf-monitor",
        },
    }
    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": data_as_of,
        "overall_status": overall_status,
        "live_sources": available_main_sources,
        "sources": source_health,
    }
    return artifact, status


def _localized_zh_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    localized = json.loads(json.dumps(artifact, ensure_ascii=False, default=str))
    localized["manifest"]["title"] = "香港资金流与流动性"
    localized["manifest"]["description"] = (
        "HKEX卖空库存、HKMA流动性与MSCI港中指数审议事件的机构数据背景。"
        "南下资金仍以ETF监控为唯一主视图。"
    )
    source_labels = {
        "HKMA Interbank Liquidity": "HKMA银行间流动性",
        "HKEX Short Selling Statistics": "HKEX卖空统计",
        "MSCI Index Reviews": "MSCI指数审议",
        "Eastmoney Stock Connect · canonical in ETF Monitor": "东方财富沪深港通 · ETF监控中的主视图",
    }
    for row in localized.get("snapshot", {}).get("datasets", {}).get("source_health", []):
        source = str(row.get("source") or "")
        row["source"] = source_labels.get(source, source)
    for source in localized.get("sources", []):
        source["label"] = source_labels.get(str(source.get("label") or ""), source.get("label"))
    table_titles = {
        "hkex_short_inventory_table": "HKEX卖空库存",
        "msci_review_cycles_table": "MSCI港中审议周期",
        "msci_index_events_table": "MSCI指数事件",
    }
    for table in localized.get("manifest", {}).get("tables", []):
        table["title"] = table_titles.get(str(table.get("id")), table.get("title"))
    return localized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--status-output", type=Path, default=None)
    args = parser.parse_args()

    artifact, status = _build_artifact()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    zh_path = args.output.with_name(
        args.output.name.replace("-artifact.json", "-artifact-zh.json")
    )
    payload = json.dumps(artifact, separators=(",", ":"), ensure_ascii=False, default=str)
    zh_payload = json.dumps(
        _localized_zh_artifact(artifact),
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    outputs = {args.output: payload, zh_path: zh_payload}
    if args.status_output is not None:
        outputs[args.status_output] = json.dumps(
            {
                **status,
                "attachment_filename": "hong-kong-flows.html",
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
    atomic_write_texts(outputs)
    print(json.dumps({"ok": True, **status}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
