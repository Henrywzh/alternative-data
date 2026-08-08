"""Point-in-time Cninfo airline rating events from dated public queries."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from ..config import AIRLINE_TICKER_ALIASES, NORMALIZED_DIR
from .airline_financials import A_SHARE_AIRLINES


OUTPUT_PATH = NORMALIZED_DIR / "airline_cninfo_rating_events.csv"
SOURCE_URL = "https://webapi.cninfo.com.cn/#/thematicStatistics?name=%E6%8A%95%E8%B5%84%E8%AF%84%E7%BA%A7"

OUTPUT_COLUMNS = [
    "dataset_id", "ticker", "company", "report_date", "query_date",
    "institution", "analyst", "rating", "rating_change", "previous_rating",
    "is_first_rating", "rating_direction", "target_price_low_native",
    "target_price_high_native", "native_currency", "source_quality", "source_url",
    "history_scope", "source_note", "retrieved_at",
]


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _direction(rating_change: Any) -> str:
    text = str(rating_change or "").strip()
    if text in {"上调", "评级上调"}:
        return "upgrade"
    if text in {"下调", "评级下调"}:
        return "downgrade"
    if text in {"维持", "首次", "首次评级"}:
        return "maintain_or_new"
    return "unknown"


def normalize_cninfo_rating_events(
    frames: Iterable[tuple[str, pd.DataFrame]],
    *,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Normalize dated Cninfo query results, keeping only the airline universe."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    code_to_metadata = {symbol: metadata for symbol, metadata in A_SHARE_AIRLINES.items()}
    rows: list[dict[str, Any]] = []
    for query_date, frame in frames:
        if frame is None or frame.empty:
            continue
        for _, source in frame.iterrows():
            code = str(source.get("证券代码", "")).zfill(6)
            metadata = code_to_metadata.get(code)
            if metadata is None:
                continue
            report_date = pd.to_datetime(source.get("发布日期"), errors="coerce")
            report_date_text = report_date.strftime("%Y-%m-%d") if not pd.isna(report_date) else query_date
            change = source.get("评级变化")
            rows.append({
                "dataset_id": "airline_cninfo_rating_events",
                "ticker": metadata["ticker"],
                "company": metadata["company"],
                "report_date": report_date_text,
                "query_date": str(query_date),
                "institution": source.get("研究机构简称"),
                "analyst": source.get("研究员名称"),
                "rating": source.get("投资评级"),
                "rating_change": change,
                "previous_rating": source.get("前一次投资评级"),
                "is_first_rating": source.get("是否首次评级"),
                "rating_direction": _direction(change),
                "target_price_low_native": _number(source.get("目标价格-下限")),
                "target_price_high_native": _number(source.get("目标价格-上限")),
                "native_currency": "RMB",
                "source_quality": "cninfo_discovery",
                "source_url": SOURCE_URL,
                "history_scope": "queried_public_report_dates",
                "source_note": (
                    "Cninfo dated investment-rating event retrieved through AkShare. "
                    "This is a point-in-time event layer for queried dates, not a complete "
                    "daily rating history or earnings-estimate revision tape."
                ),
                "retrieved_at": retrieved,
            })
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if result.empty:
        return result
    return result.drop_duplicates(
        subset=["ticker", "report_date", "institution", "analyst", "rating", "target_price_low_native", "target_price_high_native"]
    ).sort_values(["ticker", "report_date", "institution"]).reset_index(drop=True)


def _default_query_dates() -> list[str]:
    dates: set[str] = set()
    for filename in (
        "airline_hk_sell_side_forecasts.csv",
        "airline_sell_side_reports_akshare_snapshot.csv",
    ):
        path = NORMALIZED_DIR / filename
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        column = "report_date"
        if column not in frame.columns:
            continue
        parsed = pd.to_datetime(frame[column], errors="coerce").dropna()
        dates.update(parsed.loc[parsed.ge(pd.Timestamp("2025-08-01"))].dt.strftime("%Y-%m-%d"))
    return sorted(dates)


def merge_cninfo_rating_history(prior: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """Append rating events while replacing only an identical event key."""
    result = pd.concat([prior, current], ignore_index=True)
    if result.empty:
        return result
    result["ticker"] = result["ticker"].replace(AIRLINE_TICKER_ALIASES)
    key = ["ticker", "report_date", "institution", "analyst", "rating", "target_price_low_native", "target_price_high_native"]
    result = result.drop_duplicates(key, keep="last")
    return result.sort_values(["ticker", "report_date", "institution"]).reset_index(drop=True)


def fetch_cninfo_rating_events(*, query_dates: Iterable[str] | None = None) -> pd.DataFrame:
    try:
        import akshare as ak
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("akshare is required for the Cninfo rating-event layer") from exc
    dates = list(query_dates or _default_query_dates())
    frames: list[tuple[str, pd.DataFrame]] = []
    for date in dates:
        try:
            frame = ak.stock_rank_forecast_cninfo(date=str(date).replace("-", ""))
        except Exception:
            continue
        frames.append((str(date), frame))
    result = normalize_cninfo_rating_events(frames)
    if OUTPUT_PATH.exists():
        result = merge_cninfo_rating_history(pd.read_csv(OUTPUT_PATH), result)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
