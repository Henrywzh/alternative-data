"""Published fee schedule per fund, from Eastmoney.

The wrapper registry carried hand-typed fees, and an audit against this
endpoint found 16 of 23 wrong -- mostly a placeholder 0.50% standing in for a
real 0.15%, a 3.3x overstatement. Worse than the error was its uniformity:
the three CSI 300 wrappers all carried the same wrong number, so the fee
component of the hold score could not differentiate them at all while holding
weight 2.0 and claiming to.

Holding cost is management + custody. Both are published here.
"""

from __future__ import annotations

import concurrent.futures
import re

import pandas as pd


# akshare's fund_fee_em builds its own request and exposes no timeout, so a
# connection the server holds open blocks forever. That is fine for a notebook
# and unacceptable here: this is a reconciliation check, and a check must
# never be able to stall the run it is checking. Twenty-one minutes of a
# daily pipeline were spent inside one such call before this bound existed.
_CALL_TIMEOUT_SECONDS = 15.0
_UNKNOWN: dict[str, float | None] = {"management_fee": None, "custody_fee": None}


_PERCENT = re.compile(r"([\d.]+)\s*%")


def _percent(value: object) -> float | None:
    match = _PERCENT.search(str(value))
    return float(match.group(1)) / 100.0 if match else None


def fetch_fund_fees(
    fund_id: str,
    *,
    timeout: float = _CALL_TIMEOUT_SECONDS,
) -> dict[str, float | None]:
    """Annual management and custody fee for one fund, as decimals.

    Returns None for a fee the page does not state rather than a zero: a fund
    with an unknown fee must score as unmeasured, not as free. A call that
    outruns ``timeout`` returns unknown too -- the worker thread is abandoned
    rather than waited on, because the point of the bound is not to wait.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_fetch_fund_fees_blocking, str(fund_id).zfill(6))
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return dict(_UNKNOWN)
        finally:
            # Do not let the pool's own shutdown re-join the stuck worker.
            pool._threads.clear()  # noqa: SLF001
            concurrent.futures.thread._threads_queues.clear()  # noqa: SLF001


def _fetch_fund_fees_blocking(fund_id: str) -> dict[str, float | None]:
    import akshare as ak

    frame = ak.fund_fee_em(symbol=fund_id, indicator="运作费用")
    if frame is None or frame.empty:
        return dict(_UNKNOWN)
    # The table arrives as label/value pairs across a single row rather than
    # as named columns, so read it by matching the label text.
    fees: dict[str, float | None] = {"management_fee": None, "custody_fee": None}
    values = [str(v) for v in frame.iloc[0].tolist()]
    for label, value in zip(values, values[1:]):
        if "管理费" in label:
            fees["management_fee"] = _percent(value)
        elif "托管费" in label:
            fees["custody_fee"] = _percent(value)
    return fees


def reconcile_fees(metadata: pd.DataFrame, observed: dict[str, dict]) -> list[dict[str, str]]:
    """Registry rows whose stated management fee the issuer contradicts.

    A fee the endpoint did not return is not a contradiction -- it is an
    absence -- and is skipped.
    """
    problems: list[dict[str, str]] = []
    for row in metadata.itertuples():
        fund_id = str(row.fund_id).zfill(6)
        published = (observed.get(fund_id) or {}).get("management_fee")
        if published is None:
            continue
        stated = getattr(row, "management_fee", None)
        if stated is None or pd.isna(stated):
            problems.append(
                {"fund_id": fund_id, "stated": "none", "published": f"{published:.4%}"}
            )
            continue
        if abs(float(stated) - float(published)) > 1e-9:
            problems.append(
                {"fund_id": fund_id, "stated": f"{float(stated):.4%}", "published": f"{published:.4%}"}
            )
    return problems
