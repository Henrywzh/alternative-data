"""Read-only GitHub-runner probe for the tracked Eastmoney ETF quote batch.

This deliberately bypasses AkShare and the full-market pagination fallback so
we can isolate whether the targeted quote endpoint is reachable from a runner.
It does not persist data, build artifacts, or send email.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from market_monitor.metadata import ETF_REGISTRY
from market_monitor.sources.akshare_etf import _fetch_etf_spot_for_tracked_wrappers


def main() -> int:
    retrieved_at_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    frame = _fetch_etf_spot_for_tracked_wrappers()
    expected = len(ETF_REGISTRY)
    price_column = "最新价"
    premium_column = "基金折价率"

    valid_prices = 0
    valid_premiums = 0
    if price_column in frame:
        prices = pd.to_numeric(frame[price_column], errors="coerce")
        valid_prices = int((prices.notna() & prices.gt(0)).sum())
    if premium_column in frame:
        premiums = pd.to_numeric(frame[premium_column], errors="coerce")
        valid_premiums = int(premiums.notna().sum())

    summary = {
        "status": (
            "ok"
            if len(frame) == expected
            and valid_prices == expected
            and valid_premiums == expected
            else "failed"
        ),
        "retrieved_at_utc": retrieved_at_utc,
        "source_observation_timestamp": "not_provided_by_endpoint",
        "expected_wrappers": expected,
        "returned_rows": len(frame),
        "valid_price_rows": valid_prices,
        "valid_premium_rows": valid_premiums,
        "writes_data": False,
        "sends_email": False,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
