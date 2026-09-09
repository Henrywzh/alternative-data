"""CFTC Commitments of Traders adapters.

Financial futures use Traders in Financial Futures leveraged-money positions.
Commodities use the disaggregated managed-money category. Those two reports
are not interchangeable, so the contract registry keeps them separate.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import requests

from .config import CFTC_DISAGG_CONTRACTS, CFTC_DISAGG_URL, CFTC_TFF_CONTRACTS, CFTC_TFF_URL
from .storage import utc_now


def _int(value: Any) -> int | None:
    if value in (None, "", "."):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _percentile(history: pd.Series, value: float) -> float | None:
    clean = pd.to_numeric(history, errors="coerce").dropna()
    if clean.empty or pd.isna(value):
        return None
    return float((clean <= value).mean() * 100.0)


def _label(percentile: float | None, weekly_change: int | None) -> str:
    if percentile is None:
        return "Unknown"
    if percentile >= 97:
        return "Historical high"
    if percentile <= 3:
        return "Extreme"
    if weekly_change is None:
        return "Range"
    if weekly_change > 0:
        return "Rising"
    if weekly_change < 0:
        return "Falling"
    return "Range"


def fetch_cftc_table(url: str, names: list[str], *, limit: int = 8000, start: str = "2015-01-01") -> pd.DataFrame:
    quoted = ",".join("'" + name.replace("'", "''") + "'" for name in names)
    params = {
        "$limit": str(limit),
        "$order": "report_date_as_yyyy_mm_dd ASC",
        "$where": (
            f"market_and_exchange_names in ({quoted}) "
            f"AND report_date_as_yyyy_mm_dd >= '{start}T00:00:00.000'"
        ),
    }
    response = requests.get(url, params=params, timeout=40)
    response.raise_for_status()
    payload = response.json()
    return pd.DataFrame(payload)


def normalize_tff(raw: pd.DataFrame, *, retrieved_at: str | None = None) -> pd.DataFrame:
    retrieved_at = retrieved_at or utc_now()
    if raw is None or raw.empty:
        return pd.DataFrame()
    lookup = {row["market_and_exchange_names"]: row for row in CFTC_TFF_CONTRACTS}
    rows: list[dict[str, Any]] = []
    for record in raw.to_dict("records"):
        spec = lookup.get(str(record.get("market_and_exchange_names") or ""))
        if spec is None:
            continue
        long_pos = _int(record.get("lev_money_positions_long"))
        short_pos = _int(record.get("lev_money_positions_short"))
        long_chg = _int(record.get("change_in_lev_money_long"))
        short_chg = _int(record.get("change_in_lev_money_short"))
        if long_pos is None or short_pos is None:
            continue
        net = long_pos - short_pos
        weekly = None if long_chg is None or short_chg is None else long_chg - short_chg
        rows.append(
            {
                "date": str(record.get("report_date_as_yyyy_mm_dd") or "")[:10],
                "contract_id": spec["contract_id"],
                "label_en": spec["label_en"],
                "label_zh": spec["label_zh"],
                "group": spec["group"],
                "report": "tff_leveraged_money",
                "market_and_exchange_names": spec["market_and_exchange_names"],
                "open_interest": _int(record.get("open_interest_all")),
                "long_pos": long_pos,
                "short_pos": short_pos,
                "net": net,
                "weekly_change": weekly,
                "retrieved_at": retrieved_at,
                "source": "cftc_tff",
            }
        )
    return pd.DataFrame(rows)


def normalize_disagg(raw: pd.DataFrame, *, retrieved_at: str | None = None) -> pd.DataFrame:
    retrieved_at = retrieved_at or utc_now()
    if raw is None or raw.empty:
        return pd.DataFrame()
    lookup = {row["market_and_exchange_names"]: row for row in CFTC_DISAGG_CONTRACTS}
    rows: list[dict[str, Any]] = []
    for record in raw.to_dict("records"):
        spec = lookup.get(str(record.get("market_and_exchange_names") or ""))
        if spec is None:
            continue
        long_pos = _int(record.get("m_money_positions_long_all"))
        short_pos = _int(record.get("m_money_positions_short_all"))
        long_chg = _int(record.get("change_in_m_money_long_all"))
        short_chg = _int(record.get("change_in_m_money_short_all"))
        if long_pos is None or short_pos is None:
            continue
        net = long_pos - short_pos
        weekly = None if long_chg is None or short_chg is None else long_chg - short_chg
        rows.append(
            {
                "date": str(record.get("report_date_as_yyyy_mm_dd") or "")[:10],
                "contract_id": spec["contract_id"],
                "label_en": spec["label_en"],
                "label_zh": spec["label_zh"],
                "group": spec["group"],
                "report": "disagg_managed_money",
                "market_and_exchange_names": spec["market_and_exchange_names"],
                "open_interest": _int(record.get("open_interest_all")),
                "long_pos": long_pos,
                "short_pos": short_pos,
                "net": net,
                "weekly_change": weekly,
                "retrieved_at": retrieved_at,
                "source": "cftc_disagg",
            }
        )
    return pd.DataFrame(rows)


def add_history_features(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date", "net"]).sort_values(["contract_id", "date"]).reset_index(drop=True)
    parts: list[pd.DataFrame] = []
    for _, group in out.groupby("contract_id", sort=False):
        group = group.copy()
        nets = pd.to_numeric(group["net"], errors="coerce")
        percentiles = []
        labels = []
        for i, value in enumerate(nets.tolist()):
            pct = _percentile(nets.iloc[: i + 1], float(value))
            percentiles.append(pct)
            labels.append(_label(pct, group.iloc[i].get("weekly_change")))
        group["percentile"] = percentiles
        group["position_label"] = labels
        parts.append(group)
    return pd.concat(parts, ignore_index=True) if parts else out


def latest_cot_snapshot(history: pd.DataFrame) -> pd.DataFrame:
    if history is None or history.empty:
        return pd.DataFrame()
    frame = history.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    latest = frame.sort_values("date").groupby("contract_id", as_index=False).tail(1)
    return latest.sort_values(["group", "contract_id"]).reset_index(drop=True)


def fetch_cot_panel() -> pd.DataFrame:
    retrieved_at = utc_now()
    tff_raw = fetch_cftc_table(CFTC_TFF_URL, [row["market_and_exchange_names"] for row in CFTC_TFF_CONTRACTS])
    disagg_raw = fetch_cftc_table(CFTC_DISAGG_URL, [row["market_and_exchange_names"] for row in CFTC_DISAGG_CONTRACTS])
    combined = pd.concat(
        [
            normalize_tff(tff_raw, retrieved_at=retrieved_at),
            normalize_disagg(disagg_raw, retrieved_at=retrieved_at),
        ],
        ignore_index=True,
        sort=False,
    )
    return add_history_features(combined)
