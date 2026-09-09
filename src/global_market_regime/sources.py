"""Source adapters for FRED macro series and Atlanta Fed MPT."""

from __future__ import annotations

from io import BytesIO
import re
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from fred_macro_data.client import FredMacroClient
from fred_macro_data.config import resolve_api_key

from .config import ATLANTA_MPT_URL, FRED_SERIES, HISTORY_START, REPO_ROOT
from .storage import utc_now


_SENSITIVE_QUERY_VALUE = re.compile(
    r"(?P<prefix>[?&](?:api[_-]?key|access[_-]?token|token|password|secret)=)"
    r"[^&\s]+",
    flags=re.IGNORECASE,
)


def safe_error_message(
    error: BaseException | str,
    *,
    secrets: tuple[str, ...] = (),
    max_length: int = 800,
) -> str:
    """Return a bounded diagnostic with credentials removed."""
    message = str(error).replace("\r", " ").replace("\n", " ")
    for secret in secrets:
        if secret:
            message = message.replace(str(secret), "[REDACTED]")
    message = _SENSITIVE_QUERY_VALUE.sub(
        lambda match: f"{match.group('prefix')}[REDACTED]",
        message,
    )
    return message[:max_length]


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=3,
        read=3,
        status=4,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_fred_observations(
    *,
    api_key: str | None = None,
    start: str = HISTORY_START,
    client: FredMacroClient | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Fetch the V1 FRED panel. Partial success is allowed and recorded."""
    fred = client or FredMacroClient(api_key=api_key or resolve_api_key(REPO_ROOT))
    credential = str(getattr(fred, "api_key", "") or "")
    retrieved_at = utc_now()
    rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for spec in FRED_SERIES:
        series_id = spec["series_id"]
        try:
            observations = fred.get_observations(series_id, observation_start=start)
        except Exception as exc:  # source failure must not abort the rest of the panel
            errors[series_id] = safe_error_message(
                exc,
                secrets=(credential,),
            )
            continue
        for point in observations:
            rows.append(
                {
                    "date": point.date,
                    "series_id": series_id,
                    "indicator_id": spec["indicator_id"],
                    "value": point.value,
                    "unit": spec["unit"],
                    "source": "fred",
                    "retrieved_at": retrieved_at,
                    "realtime_start": point.realtime_start,
                    "realtime_end": point.realtime_end,
                }
            )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date", "value"]).sort_values(["indicator_id", "date"]).reset_index(drop=True)
    return frame, errors


def parse_atlanta_mpt(payload: bytes, *, retrieved_at: str | None = None) -> pd.DataFrame:
    """Parse the official Atlanta Fed long-form Excel into daily window stats."""
    retrieved_at = retrieved_at or utc_now()
    raw = pd.read_excel(BytesIO(payload), sheet_name="DATA")
    required = {"date", "reference_start", "target_range", "field", "value"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Atlanta MPT file missing columns: {sorted(missing)}")
    frame = raw.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["reference_start"] = pd.to_datetime(frame["reference_start"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["date", "reference_start", "field", "value"])
    frame["field"] = frame["field"].astype(str)
    frame["target_range"] = frame["target_range"].astype(str)
    frame["retrieved_at"] = retrieved_at
    frame["source"] = "atlanta_mpt"
    return frame.sort_values(["date", "reference_start", "field"]).reset_index(drop=True)


def fetch_atlanta_mpt(*, url: str = ATLANTA_MPT_URL, timeout: int = 60) -> tuple[pd.DataFrame, bytes]:
    response = _session().get(url, timeout=timeout)
    response.raise_for_status()
    payload = response.content
    if len(payload) < 1024:
        raise ValueError("Atlanta MPT download was unexpectedly small")
    return parse_atlanta_mpt(payload), payload


def nearest_rate_window(mpt: pd.DataFrame, asof: pd.Timestamp | None = None) -> pd.DataFrame:
    """Keep the nearest remaining SOFR reference window as of each observation date.

    Atlanta Fed MPT is a distribution over a three-month average SOFR window,
    not a CME FedWatch meeting-by-meeting tree. The nearest remaining window is
    the honest V1 proxy for "near-term hike probability".
    """
    if mpt is None or mpt.empty:
        return pd.DataFrame()
    frame = mpt.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["reference_start"] = pd.to_datetime(frame["reference_start"], errors="coerce")
    frame = frame.dropna(subset=["date", "reference_start"])
    if asof is not None:
        frame = frame[frame["date"] <= pd.Timestamp(asof)]
    eligible = frame[frame["reference_start"] >= frame["date"]].copy()
    if eligible.empty:
        eligible = frame.copy()
    nearest = eligible.groupby("date", as_index=False)["reference_start"].min()
    return eligible.merge(nearest, on=["date", "reference_start"], how="inner")


def hike_probability_history(mpt: pd.DataFrame) -> pd.DataFrame:
    windowed = nearest_rate_window(mpt)
    if windowed.empty:
        return pd.DataFrame(columns=["date", "value", "reference_start", "target_range", "mean_rate_bps", "cut_prob"])
    hike = windowed[windowed["field"].eq("Prob: hike")][
        ["date", "reference_start", "target_range", "value"]
    ].rename(columns={"value": "value"})
    cut = windowed[windowed["field"].eq("Prob: cut")][
        ["date", "reference_start", "value"]
    ].rename(columns={"value": "cut_prob"})
    mean = windowed[windowed["field"].eq("Rate: mean")][
        ["date", "reference_start", "value"]
    ].rename(columns={"value": "mean_rate_bps"})
    # A missing cut bucket is not evidence of zero cut probability. Keep only
    # dates where the mutually exclusive hike/cut inputs are both observed;
    # hold is the residual of that complete distribution.
    out = hike.merge(cut, on=["date", "reference_start"], how="inner").merge(
        mean, on=["date", "reference_start"], how="left"
    )
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out["cut_prob"] = pd.to_numeric(out["cut_prob"], errors="coerce")
    out = out[
        out["value"].between(0.0, 100.0, inclusive="both")
        & out["cut_prob"].between(0.0, 100.0, inclusive="both")
        & (out["value"] + out["cut_prob"] <= 100.5)
    ].copy()
    out["hold_prob"] = (100.0 - out["value"] - out["cut_prob"]).clip(lower=0)
    out["window_key"] = (
        out["reference_start"].dt.strftime("%Y-%m-%d") + "|" + out["target_range"].astype(str)
    )
    return out.sort_values("date").reset_index(drop=True)
