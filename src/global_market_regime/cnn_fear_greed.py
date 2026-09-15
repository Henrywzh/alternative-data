"""CNN Business equity Fear & Greed adapter.

This is the US-equity sentiment gauge, not Alternative.me crypto Fear & Greed.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .config import (
    CNN_FEAR_GREED_PAGE,
    CNN_FEAR_GREED_SERIES_ID,
    CNN_FEAR_GREED_SOURCE,
    CNN_FEAR_GREED_URL,
)
from .sources import _session, safe_error_message
from .storage import utc_now


CNN_FEAR_GREED_COMPONENTS = (
    ("fear_and_greed_historical", "composite", "CNN Fear & Greed", "CNN恐惧与贪婪"),
    ("market_momentum_sp500", "momentum", "Market momentum", "市场动量"),
    ("stock_price_strength", "strength", "Stock price strength", "股价强度"),
    ("stock_price_breadth", "breadth", "Stock price breadth", "股价广度"),
    ("put_call_options", "put_call", "Put/call options", "看跌／看涨期权"),
    ("market_volatility_vix", "vix", "Market volatility (VIX)", "市场波动率（VIX）"),
    ("junk_bond_demand", "junk_bond", "Junk bond demand", "垃圾债需求"),
    ("safe_haven_demand", "safe_haven", "Safe-haven demand", "避险需求"),
)


def cnn_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Referer": CNN_FEAR_GREED_PAGE,
        "Origin": "https://www.cnn.com",
    }


def _unix_ms_to_date(value: Any) -> pd.Timestamp | None:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        return None
    stamp = pd.to_datetime(float(number), unit="ms", utc=True, errors="coerce")
    if pd.isna(stamp):
        return None
    return pd.Timestamp(stamp.date())


def parse_cnn_fear_greed(payload: dict[str, Any], *, retrieved_at: str | None = None) -> pd.DataFrame:
    """Parse CNN graphdata JSON into a daily composite/component panel.

    Composite history uses the published 0-100 score. Component history keeps
    the raw input series; the current 0-100 component score is attached only
    to the latest observation because CNN does not publish a historical score
    series for those components.
    """
    retrieved_at = retrieved_at or utc_now()
    if not isinstance(payload, dict):
        raise ValueError("CNN Fear & Greed payload must be an object")

    rows: list[dict[str, Any]] = []
    for source_key, component_id, label_en, label_zh in CNN_FEAR_GREED_COMPONENTS:
        block = payload.get(source_key)
        if not isinstance(block, dict):
            continue
        points = block.get("data")
        if not isinstance(points, list):
            continue
        for point in points:
            if not isinstance(point, dict):
                continue
            date = _unix_ms_to_date(point.get("x"))
            if date is None:
                continue
            raw_value = pd.to_numeric(pd.Series([point.get("y")]), errors="coerce").iloc[0]
            score = pd.to_numeric(pd.Series([point.get("score")]), errors="coerce").iloc[0]
            if component_id == "composite":
                if pd.isna(score):
                    score = raw_value
                if pd.isna(score):
                    continue
                raw_value = score
            rows.append(
                {
                    "date": date,
                    "component_id": component_id,
                    "label_en": label_en,
                    "label_zh": label_zh,
                    "score": None if pd.isna(score) else float(score),
                    "raw_value": None if pd.isna(raw_value) else float(raw_value),
                    "rating": str(point.get("rating") or "").strip() or None,
                    "source": "cnn_fear_greed",
                    "retrieved_at": retrieved_at,
                    "series_id": CNN_FEAR_GREED_SERIES_ID,
                    "source_name": CNN_FEAR_GREED_SOURCE,
                }
            )

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("CNN Fear & Greed payload contained no usable history")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = (
        frame.dropna(subset=["date", "component_id"])
        .sort_values(["component_id", "date"], kind="mergesort")
        .drop_duplicates(["component_id", "date"], keep="last")
        .reset_index(drop=True)
    )

    snapshot = payload.get("fear_and_greed")
    if isinstance(snapshot, dict):
        snapshot_score = pd.to_numeric(pd.Series([snapshot.get("score")]), errors="coerce").iloc[0]
        snapshot_rating = str(snapshot.get("rating") or "").strip() or None
        snapshot_date = pd.to_datetime(snapshot.get("timestamp"), utc=True, errors="coerce")
        if pd.notna(snapshot_date) and not pd.isna(snapshot_score):
            snapshot_date = pd.Timestamp(snapshot_date.date())
            extra = pd.DataFrame(
                [
                    {
                        "date": snapshot_date,
                        "component_id": "composite",
                        "label_en": "CNN Fear & Greed",
                        "label_zh": "CNN恐惧与贪婪",
                        "score": float(snapshot_score),
                        "raw_value": float(snapshot_score),
                        "rating": snapshot_rating,
                        "source": "cnn_fear_greed",
                        "retrieved_at": retrieved_at,
                        "series_id": CNN_FEAR_GREED_SERIES_ID,
                        "source_name": CNN_FEAR_GREED_SOURCE,
                    }
                ]
            )
            frame = pd.concat([frame, extra], ignore_index=True)
            frame = (
                frame.sort_values(["component_id", "date"], kind="mergesort")
                .drop_duplicates(["component_id", "date"], keep="last")
                .reset_index(drop=True)
            )

    for source_key, component_id, _label_en, _label_zh in CNN_FEAR_GREED_COMPONENTS:
        if component_id == "composite":
            continue
        block = payload.get(source_key)
        if not isinstance(block, dict):
            continue
        score = pd.to_numeric(pd.Series([block.get("score")]), errors="coerce").iloc[0]
        rating = str(block.get("rating") or "").strip() or None
        stamp = _unix_ms_to_date(block.get("timestamp"))
        subset = frame[frame["component_id"].eq(component_id)]
        if subset.empty or pd.isna(score):
            continue
        latest_idx = subset["date"].idxmax()
        frame.loc[latest_idx, "score"] = float(score)
        if rating:
            frame.loc[latest_idx, "rating"] = rating
        if stamp is not None and stamp > subset["date"].max():
            latest_row = frame.loc[latest_idx].to_dict()
            latest_row["date"] = stamp
            latest_row["score"] = float(score)
            latest_row["rating"] = rating
            frame = pd.concat([frame, pd.DataFrame([latest_row])], ignore_index=True)

    return (
        frame.sort_values(["component_id", "date"], kind="mergesort")
        .drop_duplicates(["component_id", "date"], keep="last")
        .reset_index(drop=True)
    )


def fetch_cnn_fear_greed(*, url: str = CNN_FEAR_GREED_URL, timeout: int = 30) -> tuple[pd.DataFrame, dict[str, Any]]:
    response = _session().get(url, headers=cnn_headers(), timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("CNN Fear & Greed response was not a JSON object")
    return parse_cnn_fear_greed(payload), payload


def cnn_fear_greed_error(error: BaseException | str) -> str:
    return safe_error_message(error)
