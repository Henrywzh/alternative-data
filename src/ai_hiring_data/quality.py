from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd


def validate_indeed(rows: list[dict[str, object]], *, production: bool = True) -> None:
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("Indeed AI tracker extracted no rows")
    if frame[["date", "jobcountry"]].isna().any().any() or frame.duplicated(["date", "jobcountry"]).any():
        raise ValueError("Indeed AI tracker has null or duplicate natural keys")
    shares = pd.to_numeric(frame["ai_share_pct"], errors="coerce")
    if shares.isna().any() or (~shares.between(0, 100)).any():
        raise ValueError("Indeed AI posting shares must be populated percentages in [0, 100]")
    dates = pd.to_datetime(frame["date"], errors="coerce", utc=True)
    if dates.isna().any():
        raise ValueError("Indeed AI tracker contains invalid dates")
    if production:
        if len(frame) < 20_000:
            raise ValueError(f"Indeed AI tracker has only {len(frame)} rows; expected at least 20,000")
        if frame["jobcountry"].nunique() < 8:
            raise ValueError("Indeed AI tracker covers fewer than eight countries")
        freshness_days = (datetime.now(timezone.utc) - dates.max().to_pydatetime()).days
        if freshness_days > 120:
            raise ValueError(f"Indeed AI tracker is unexpectedly stale by {freshness_days} days")


def validate_board(rows: list[dict[str, object]], *, company_id: str, production: bool = True) -> None:
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError(f"{company_id} board extracted no listed jobs")
    keys = ["company_id", "source_job_id"]
    if frame[keys].isna().any().any() or frame.duplicated(keys).any():
        raise ValueError(f"{company_id} board has null or duplicate posting keys")
    if frame["title"].astype(str).str.strip().eq("").any():
        raise ValueError(f"{company_id} board contains blank titles")
    if (~frame["job_url"].astype(str).str.startswith(("https://", "http://"))).any():
        raise ValueError(f"{company_id} board contains invalid job URLs")
    if production and len(frame) < 3:
        raise ValueError(f"{company_id} board has only {len(frame)} jobs; expected at least three")


def count_collapsed(current: int, previous_good: object, *, ratio: float = 0.5) -> bool:
    previous = pd.to_numeric(previous_good, errors="coerce")
    if pd.isna(previous):
        return False
    return bool((previous >= 5 and current == 0) or (previous >= 10 and current < previous * ratio))
