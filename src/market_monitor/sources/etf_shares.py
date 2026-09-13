"""Official exchange ETF share-count observations.

The Eastmoney ETF spot endpoint has a ``最新份额`` field, but it is a current
snapshot and its source timestamp is not a published observation date.  This
module uses the exchange feeds instead:

* SSE ``fund_etf_scale_sse`` returns all ETF shares for one requested date;
* SZSE ``fund_scale_daily_szse`` returns daily ETF shares over a bounded range.

Only the tracked A-share wrappers are retained before the frame leaves the
source layer.  The adapter returns the source date it actually received; an
empty response for a future requested date is never stamped as today's data.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from ..config import (
    ETF_ACTIVITY_BOOTSTRAP_DAYS,
    ETF_ACTIVITY_REFRESH_TAIL_DAYS,
    ETF_ACTIVITY_SSE_BOOTSTRAP_SESSIONS,
    ETF_ACTIVITY_SSE_REFRESH_SESSIONS,
)
from ..freshness import isoformat_utc


SHARE_COLUMNS = (
    "observation_date",
    "fund_id",
    "venue",
    "shares_outstanding",
    "fund_name",
    "source",
    "source_observed_date",
    "retrieved_at_utc",
    "observation_type",
)

SOURCE_SSE = "sse:fund_etf_scale_sse"
SOURCE_SZSE = "szse:fund_scale_daily_szse"


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=SHARE_COLUMNS)


def _normalise_ids(values: pd.Series) -> pd.Series:
    return values.astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)


def _first_present(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    lookup = {str(column).strip(): column for column in frame.columns}
    for name in names:
        if name in lookup:
            return lookup[name]
    return None


def _rename_share_columns(frame: pd.DataFrame, mapping: dict[str, tuple[str, ...]]) -> pd.DataFrame:
    """Map vendor column aliases without requiring a frozen schema."""
    renamed = {}
    for target, aliases in mapping.items():
        source = _first_present(frame, aliases)
        if source is not None:
            renamed[source] = target
    return frame.rename(columns=renamed).copy()


def _normalise_sse(frame: pd.DataFrame, *, retrieved_at_utc: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return _empty()
    source = _rename_share_columns(
        frame,
        {
            "fund_id": ("基金代码", "代码", "证券代码", "fund_id"),
            "fund_name": ("基金简称", "证券简称", "名称", "fund_name"),
            "shares_outstanding": ("基金份额", "份额", "最新份额", "shares_outstanding"),
            "observation_date": ("统计日期", "日期", "数据日期", "observation_date"),
        },
    )
    required = {"fund_id", "fund_name", "shares_outstanding", "observation_date"}
    if not required.issubset(source.columns):
        return _empty()
    source["fund_id"] = _normalise_ids(source["fund_id"])
    source["observation_date"] = pd.to_datetime(
        source["observation_date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    source["shares_outstanding"] = pd.to_numeric(
        source["shares_outstanding"], errors="coerce"
    )
    source = source.dropna(subset=["fund_id", "observation_date", "shares_outstanding"])
    source["venue"] = "SH"
    source["source"] = SOURCE_SSE
    source["source_observed_date"] = source["observation_date"]
    source["retrieved_at_utc"] = retrieved_at_utc
    source["observation_type"] = "published_share_count"
    return source[list(SHARE_COLUMNS)].drop_duplicates(
        subset=["fund_id", "observation_date"], keep="last"
    )


def _normalise_szse(frame: pd.DataFrame, *, retrieved_at_utc: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return _empty()
    source = _rename_share_columns(
        frame,
        {
            "fund_id": ("基金代码", "代码", "证券代码", "fund_id"),
            "fund_name": ("基金简称", "证券简称", "名称", "fund_name"),
            "shares_outstanding": ("基金份额", "份额", "最新份额", "shares_outstanding"),
            "observation_date": ("日期", "统计日期", "数据日期", "observation_date"),
        },
    )
    required = {"fund_id", "fund_name", "shares_outstanding", "observation_date"}
    if not required.issubset(source.columns):
        return _empty()
    source["fund_id"] = _normalise_ids(source["fund_id"])
    source["observation_date"] = pd.to_datetime(
        source["observation_date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    source["shares_outstanding"] = pd.to_numeric(
        source["shares_outstanding"], errors="coerce"
    )
    source = source.dropna(subset=["fund_id", "observation_date", "shares_outstanding"])
    source["venue"] = "SZ"
    source["source"] = SOURCE_SZSE
    source["source_observed_date"] = source["observation_date"]
    source["retrieved_at_utc"] = retrieved_at_utc
    source["observation_type"] = "published_share_count"
    return source[list(SHARE_COLUMNS)].drop_duplicates(
        subset=["fund_id", "observation_date"], keep="last"
    )


def _session_dates(values: Any, *, end_date: date) -> list[str]:
    if values is None:
        return []
    parsed = pd.to_datetime(pd.Series(list(values)), errors="coerce").dropna()
    parsed = parsed[parsed.dt.date <= end_date]
    return sorted(parsed.dt.strftime("%Y-%m-%d").unique().tolist())


def _keep_known_observation_dates(
    frame: pd.DataFrame,
    *,
    allowed_dates: set[str],
) -> tuple[pd.DataFrame, int]:
    """Keep only dates backed by the ETF close-session contract.

    Exchange endpoints are queried with a date/range, but a provider may
    return a nearest available date, a cached future row, or a wider range
    than requested.  The source date is retained only when it is one of the
    already validated ETF close sessions (which are also bounded by
    ``as_of_date`` before this function is called).
    """
    if frame.empty:
        return frame, 0
    valid = frame["observation_date"].isin(allowed_dates)
    return frame.loc[valid].copy(), int((~valid).sum())


def _date_window(
    session_dates: list[str],
    previous: pd.DataFrame | None,
    *,
    end_date: date,
) -> tuple[str, str]:
    end = end_date
    if previous is not None and not previous.empty and "observation_date" in previous.columns:
        prior_dates = pd.to_datetime(previous["observation_date"], errors="coerce").dropna()
        if not prior_dates.empty:
            start = prior_dates.max().date() - timedelta(days=ETF_ACTIVITY_REFRESH_TAIL_DAYS)
            return start.isoformat(), end.isoformat()
    if session_dates:
        latest = pd.Timestamp(session_dates[-1]).date()
        start = latest - timedelta(days=ETF_ACTIVITY_BOOTSTRAP_DAYS)
    else:
        start = end - timedelta(days=ETF_ACTIVITY_BOOTSTRAP_DAYS)
    return start.isoformat(), end.isoformat()


def fetch_etf_share_history(
    metadata: pd.DataFrame,
    session_dates: Any,
    *,
    previous: pd.DataFrame | None = None,
    as_of_date: str | date | None = None,
    ak_module: Any | None = None,
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    """Fetch tracked ETF share observations and source-level errors.

    ``session_dates`` should come from the already fetched ETF close series.
    That keeps the share data on actual ETF trading sessions and avoids asking
    SSE for weekends or for a future market date.  The first run uses a
    bounded bootstrap; subsequent runs refresh only a small overlap.
    """
    if metadata is None or metadata.empty or "fund_id" not in metadata.columns:
        return _empty(), []
    tracked = metadata.copy()
    tracked["fund_id"] = _normalise_ids(tracked["fund_id"])
    tracked = tracked[tracked["venue"].isin(["SH", "SZ"])] if "venue" in tracked.columns else tracked
    tracked_ids = set(tracked["fund_id"])
    if not tracked_ids:
        return _empty(), []

    end_value = pd.Timestamp(as_of_date if as_of_date is not None else date.today())
    if pd.isna(end_value):
        return _empty(), [
            {
                "dataset": "etf_share_daily",
                "severity": "optional",
                "error": "invalid as_of_date",
            }
        ]
    end_date = end_value.date()
    sessions = _session_dates(session_dates, end_date=end_date)
    if not sessions:
        return _empty(), [
            {
                "dataset": "etf_share_daily",
                "severity": "optional",
                "error": "no validated ETF close sessions available for share lookup",
            }
        ]
    start_date, end_date_text = _date_window(sessions, previous, end_date=end_date)
    prior_exists = previous is not None and not previous.empty
    sse_limit = ETF_ACTIVITY_SSE_REFRESH_SESSIONS if prior_exists else ETF_ACTIVITY_SSE_BOOTSTRAP_SESSIONS
    sse_dates = [value for value in sessions if value >= start_date]
    sse_dates = sse_dates[-sse_limit:]

    ak = ak_module
    if ak is None:
        import akshare as ak

    retrieved_at_utc = isoformat_utc()
    frames: list[pd.DataFrame] = []
    errors: list[dict[str, str]] = []

    if "SH" in set(tracked.get("venue", pd.Series(dtype=str))):
        empty_sse_requests: list[str] = []
        rejected_sse_rows = 0
        for requested in sse_dates:
            try:
                raw = ak.fund_etf_scale_sse(date=requested.replace("-", ""))
                normalised = _normalise_sse(raw, retrieved_at_utc=retrieved_at_utc)
                if normalised.empty and raw is not None and not getattr(raw, "empty", True):
                    raise KeyError(
                        "SSE share-count columns were not recognised: "
                        + ", ".join(map(str, list(raw.columns)))
                    )
                if not normalised.empty:
                    normalised, rejected = _keep_known_observation_dates(
                        normalised,
                        allowed_dates={requested},
                    )
                    rejected_sse_rows += rejected
                    normalised = normalised[normalised["fund_id"].isin(tracked_ids)]
                    if not normalised.empty:
                        frames.append(normalised)
                    else:
                        empty_sse_requests.append(requested)
                else:
                    empty_sse_requests.append(requested)
            except Exception as exc:  # noqa: BLE001 - SZSE can still succeed
                errors.append(
                    {
                        "dataset": "etf_share_daily",
                        "severity": "optional",
                        "source": SOURCE_SSE,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        if empty_sse_requests or rejected_sse_rows:
            errors.append(
                {
                    "dataset": "etf_share_daily",
                    "severity": "optional",
                    "source": SOURCE_SSE,
                    "error": (
                        f"SSE returned no accepted tracked observations for "
                        f"{len(empty_sse_requests)} of {len(sse_dates)} requested session(s); "
                        f"rejected {rejected_sse_rows} row(s) outside the requested source date."
                    ),
                }
            )

    if "SZ" in set(tracked.get("venue", pd.Series(dtype=str))):
        rejected_szse_rows = 0
        szse_empty = False
        try:
            raw = ak.fund_scale_daily_szse(
                start_date=start_date.replace("-", ""),
                end_date=end_date_text.replace("-", ""),
                symbol="ETF",
            )
            normalised = _normalise_szse(raw, retrieved_at_utc=retrieved_at_utc)
            if normalised.empty and raw is not None and not getattr(raw, "empty", True):
                raise KeyError(
                    "SZSE share-count columns were not recognised: "
                    + ", ".join(map(str, list(raw.columns)))
                )
            if not normalised.empty:
                allowed_szse_dates = {
                    value for value in sessions if start_date <= value <= end_date_text
                }
                normalised, rejected_szse_rows = _keep_known_observation_dates(
                    normalised,
                    allowed_dates=allowed_szse_dates,
                )
                normalised = normalised[normalised["fund_id"].isin(tracked_ids)]
                if not normalised.empty:
                    frames.append(normalised)
                else:
                    szse_empty = True
            else:
                szse_empty = True
        except Exception as exc:  # noqa: BLE001 - optional source is observable
            errors.append(
                {
                    "dataset": "etf_share_daily",
                    "severity": "optional",
                    "source": SOURCE_SZSE,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        if szse_empty or rejected_szse_rows:
            errors.append(
                {
                    "dataset": "etf_share_daily",
                    "severity": "optional",
                    "source": SOURCE_SZSE,
                    "error": (
                        "SZSE returned no accepted tracked observations for the requested "
                        f"window; rejected {rejected_szse_rows} row(s) outside known ETF sessions."
                    ),
                }
            )

    if not frames:
        return _empty(), errors
    result = pd.concat(frames, ignore_index=True)
    result = result[result["fund_id"].isin(tracked_ids)]
    result = result.drop_duplicates(subset=["fund_id", "observation_date"], keep="last")
    return result.sort_values(["fund_id", "observation_date"]).reset_index(drop=True), errors
