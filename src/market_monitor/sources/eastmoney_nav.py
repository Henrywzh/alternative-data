"""Published daily NAV per ETF, from Eastmoney's fund disclosure endpoint.

Why this exists: the live spot feed gives IOPV, which yields today's premium
and nothing else, so premium history could only grow one observation per run
-- a fresh deployment showed a flat line and called it "30D". Published NAV
goes back years, so premium = close / NAV - 1 reconstructs the whole series
at once.

The two measures agree where they overlap: on 2026-08-18 513500's NAV was
2.4683 against an IOPV of 2.469, 0.03% apart. They are not identical by
construction, though -- IOPV is an intraday estimate, NAV is the fund's own
end-of-day valuation, and for a QDII the NAV reflects a US close the domestic
session had not yet seen. Rows carry which basis produced them.

akshare's fund_etf_fund_info_em wraps this same endpoint but is broken against
the current upstream schema (it assigns 13 column names to 14 columns), so
this calls the endpoint directly.
"""

from __future__ import annotations

import time

import pandas as pd
import requests


_ENDPOINT = "https://api.fund.eastmoney.com/f10/lsjz"
# The endpoint silently caps the page at 20 rows however large pageSize is,
# so the page count -- not the page size -- is what has to be walked.
_PAGE_SIZE = 20
_MAX_PAGES = 400
_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    # Eastmoney's f10 host rejects requests without a matching referer.
    "Referer": "https://fundf10.eastmoney.com/",
}


def fetch_nav_history(
    fund_id: str,
    start_date: str,
    end_date: str,
    *,
    session: requests.Session | None = None,
    pause: float = 0.15,
) -> pd.DataFrame:
    """Daily published NAV for one fund, as ``fund_id`` / ``date`` / ``nav``.

    ``start_date`` and ``end_date`` are ISO dates. An empty frame means the
    endpoint reported no rows in the window, which for a fund listed after
    ``start_date`` is the correct answer rather than an error.
    """
    client = session or requests.Session()
    rows: list[dict[str, object]] = []
    retried = False
    page = 0
    while page < _MAX_PAGES:
        page += 1
        response = client.get(
            _ENDPOINT,
            params={
                "fundCode": str(fund_id).zfill(6),
                "pageIndex": page,
                "pageSize": _PAGE_SIZE,
                "startDate": start_date,
                "endDate": end_date,
                "_": str(int(time.time() * 1000)),
            },
            headers=_HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        batch = (payload.get("Data") or {}).get("LSJZList") or []
        if not batch:
            # An empty first page is ambiguous: the endpoint answers 200 with
            # no rows both for "this fund has no NAV in the window" and for
            # "you are asking too fast". One retry separates them; without it
            # a throttled fund silently loses its whole history, which is how
            # 588080 came back with two days while every other fund had 485.
            if page == 1 and not retried:
                retried = True
                time.sleep(max(pause, 1.0) * 3)
                continue
            break
        rows.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
        if pause:
            time.sleep(pause)
    if not rows:
        return pd.DataFrame(columns=["fund_id", "date", "nav"])
    frame = pd.DataFrame(rows)
    out = pd.DataFrame(
        {
            "fund_id": str(fund_id).zfill(6),
            "date": pd.to_datetime(frame["FSRQ"], errors="coerce").dt.strftime("%Y-%m-%d"),
            "nav": pd.to_numeric(frame["DWJZ"], errors="coerce"),
        }
    )
    # A suspended or pre-listing day comes back with an empty NAV string; it
    # is an absence, not a zero, and a zero would render as a -100% premium.
    return out.dropna(subset=["date", "nav"]).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)


def premium_from_nav(prices: pd.DataFrame, nav: pd.DataFrame) -> pd.DataFrame:
    """Join closes to NAV on the same day and price the wrapper's premium.

    Inner join on purpose: a close without a NAV cannot be turned into a
    premium, and carrying the row with an empty premium would put gaps in a
    series that is meant to be continuous.
    """
    if prices.empty or nav.empty:
        return pd.DataFrame(columns=["date", "fund_id", "premium_pct", "basis"])
    left = prices[["date", "fund_id", "close"]].copy()
    left["fund_id"] = left["fund_id"].astype(str).str.zfill(6)
    left["date"] = left["date"].astype(str)
    right = nav.copy()
    right["fund_id"] = right["fund_id"].astype(str).str.zfill(6)
    right["date"] = right["date"].astype(str)
    merged = left.merge(right, on=["date", "fund_id"], how="inner")
    merged = merged[pd.to_numeric(merged["nav"], errors="coerce") > 0]
    if merged.empty:
        return pd.DataFrame(columns=["date", "fund_id", "premium_pct", "basis"])
    merged["premium_pct"] = (merged["close"] / merged["nav"] - 1.0) * 100.0
    merged["basis"] = "nav"
    merged = merged.sort_values(["fund_id", "date"])
    merged = merged[~_misprinted_nav(merged)]
    return merged[["date", "fund_id", "premium_pct", "basis"]].sort_values(["date", "fund_id"]).reset_index(drop=True)


# How far a single day's premium may sit from its own local level before it is
# read as a misprinted NAV rather than an observation. Calibrated against two
# years of real data: genuine QDII premiums top out near 14% and move
# smoothly, while the two bad points found -- 159922 at +149.7% on 2024-11-29
# and 513660 at +98.6% on 2026-04-20 -- were single days sandwiched between
# normal ones (0.09 -> 149.7 -> 0.00). Nothing real sits between 14% and 98%.
_NAV_SPIKE_TOLERANCE_PP = 20.0
_NAV_SPIKE_WINDOW = 11


def _misprinted_nav(frame: pd.DataFrame) -> pd.Series:
    """Rows whose premium departs from its own neighbourhood and returns.

    A local median rather than a fixed cap, so a fund that genuinely trades at
    a sustained 13% premium keeps every one of those days while a one-day jump
    to 149% is dropped.
    """
    local = (
        frame.groupby("fund_id")["premium_pct"]
        .transform(lambda s: s.rolling(_NAV_SPIKE_WINDOW, center=True, min_periods=3).median())
    )
    return (frame["premium_pct"] - local).abs().gt(_NAV_SPIKE_TOLERANCE_PP).fillna(False)
