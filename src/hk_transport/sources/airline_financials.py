"""Free A-share airline actuals, consensus and sell-side discovery layers.

This module deliberately keeps the AkShare/Sina/10jqka/Eastmoney output in a
discovery layer.  The providers expose useful structured history, but the
financial-abstract endpoint does not carry the issuer announcement timestamp
needed for a complete point-in-time backtest.  The normalized rows therefore
retain the provider, retrieval timestamp and caveat instead of being promoted
to the primary issuer evidence layer.
"""

from __future__ import annotations

import re
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import AIRLINE_TICKER_ALIASES, NORMALIZED_DIR

A_SHARE_AIRLINES: dict[str, dict[str, str]] = {
    "600029": {
        "ticker": "01055.HK / 600029.SH",
        "company": "China Southern Airlines",
    },
    "600115": {
        "ticker": "0670.HK / 600115.SH",
        "company": "China Eastern Airlines",
    },
    "601111": {
        "ticker": "0753.HK / 601111.SH",
        "company": "Air China",
    },
    "601021": {
        "ticker": "601021.SH",
        "company": "Spring Airlines",
    },
    "603885": {
        "ticker": "603885.SH",
        "company": "Juneyao Airlines",
    },
    "600221": {
        "ticker": "600221.SH",
        "company": "Hainan Airlines Holdings",
    },
}

ACTUAL_COLUMNS = [
    "dataset_id",
    "ticker",
    "company",
    "statement_period",
    "period_end",
    "metric",
    "provider_metric",
    "value_native",
    "native_unit",
    "native_currency",
    "value_usd",
    "usd_unit",
    "fx_pair",
    "fx_observation_date",
    "fx_value",
    "source_quality",
    "announcement_date_available",
    "source_url",
    "source_note",
    "retrieved_at",
]

CONSENSUS_COLUMNS = [
    "dataset_id",
    "ticker",
    "company",
    "snapshot_date",
    "fiscal_year",
    "metric",
    "value_avg_native",
    "value_low_native",
    "value_high_native",
    "native_unit",
    "native_currency",
    "value_avg_usd_at_snapshot",
    "value_low_usd_at_snapshot",
    "value_high_usd_at_snapshot",
    "forecast_count",
    "industry_average_native",
    "forecast_date_min",
    "forecast_date_max",
    "source_quality",
    "revision_history_available",
    "source_url",
    "source_note",
    "retrieved_at",
]

DETAILED_CONSENSUS_COLUMNS = [
    "dataset_id",
    "ticker",
    "company",
    "snapshot_date",
    "fiscal_year",
    "metric",
    "value_avg_native",
    "native_unit",
    "native_currency",
    "value_avg_usd_at_snapshot",
    "fx_observation_date",
    "fx_value",
    "forecast_date_min",
    "forecast_date_max",
    "source_quality",
    "revision_history_available",
    "source_url",
    "source_note",
    "retrieved_at",
]

REPORT_COLUMNS = [
    "dataset_id",
    "ticker",
    "company",
    "report_date",
    "report_title",
    "institution",
    "rating",
    "eps_2026_native",
    "eps_2027_native",
    "eps_2028_native",
    "pe_2026",
    "pe_2027",
    "pe_2028",
    "report_url",
    "source_quality",
    "source_note",
    "retrieved_at",
]

REVISION_COLUMNS = [
    "dataset_id",
    "ticker",
    "company",
    "institution",
    "fiscal_year",
    "report_date",
    "prior_report_date",
    "eps_native",
    "prior_eps_native",
    "eps_change_native",
    "eps_change_pct",
    "rating",
    "report_title",
    "report_url",
    "source_quality",
    "source_note",
    "retrieved_at",
]

_PERIOD_RE = re.compile(r"^(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})$")


def _call_akshare_with_timeout(
    function: Any,
    *args: Any,
    timeout_seconds: int = 30,
    **kwargs: Any,
) -> Any:
    """Bound an AkShare call whose internal requests omit a timeout.

    AkShare's Ths forecast endpoints can hang during an upstream TLS or
    provider failure.  A bounded call keeps a refresh reproducible: optional
    endpoints can be caught by their existing ``except Exception`` blocks,
    while required endpoint failures abort before any normalized snapshot is
    written.  ``SIGALRM`` is available on the supported Unix environments;
    other platforms fall back to the provider call itself.
    """
    if not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"):
        return function(*args, **kwargs)

    def _timeout_handler(signum: int, frame: Any) -> None:
        raise TimeoutError(f"AkShare call exceeded {timeout_seconds}s")

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        return function(*args, **kwargs)
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)

# The same Sina table repeats several metrics in multiple sections.  The first
# occurrence is the headline value; the explicit provider metric is retained
# to make this choice auditable.
_ACTUAL_METRICS: tuple[tuple[str, tuple[str, ...], str, str, float], ...] = (
    ("attributable_net_income", ("归母净利润",), "RMB million", "RMB", 1_000_000),
    ("total_revenue", ("营业总收入",), "RMB million", "RMB", 1_000_000),
    ("operating_cost", ("营业成本",), "RMB million", "RMB", 1_000_000),
    ("net_income", ("净利润",), "RMB million", "RMB", 1_000_000),
    ("non_gaap_net_income", ("扣非净利润",), "RMB million", "RMB", 1_000_000),
    (
        "operating_cash_flow",
        ("经营现金流量净额",),
        "RMB million",
        "RMB",
        1_000_000,
    ),
    ("basic_eps", ("基本每股收益",), "RMB/share", "RMB", 1),
    ("diluted_eps", ("稀释每股收益",), "RMB/share", "RMB", 1),
    (
        "diluted_eps_latest_shares",
        ("摊薄每股收益_最新股数",),
        "RMB/share",
        "RMB",
        1,
    ),
    ("gross_margin", ("毛利率",), "%", "", 1),
    ("net_margin", ("销售净利率",), "%", "", 1),
    ("roe", ("净资产收益率(ROE)",), "%", "", 1),
    ("debt_to_assets", ("资产负债率",), "%", "", 1),
)


def _retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _period_end_from_column(column: str) -> str | None:
    match = _PERIOD_RE.match(str(column))
    if not match:
        return None
    return f"{match.group('year')}-{match.group('month')}-{match.group('day')}"


def _numeric(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _fx_asof(
    fx_rates: pd.DataFrame | None,
    *,
    pair: str,
    as_of: str,
) -> tuple[str | None, float | None]:
    if fx_rates is None or fx_rates.empty:
        return None, None
    required = {"pair", "observation_date", "value"}
    if not required.issubset(fx_rates.columns):
        return None, None
    frame = fx_rates.loc[fx_rates["pair"].eq(pair)].copy()
    if frame.empty:
        return None, None
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    target = pd.Timestamp(as_of)
    frame = frame.loc[frame["observation_date"].le(target)].dropna(subset=["observation_date", "value"])
    if frame.empty:
        return None, None
    row = frame.sort_values("observation_date").iloc[-1]
    return row["observation_date"].strftime("%Y-%m-%d"), float(row["value"])


def normalize_financial_abstract(
    frame: pd.DataFrame,
    *,
    symbol: str,
    company: str,
    fx_rates: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Normalize key historical actuals from AkShare's Sina abstract table."""
    required = {"指标"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"financial abstract is missing columns: {sorted(missing)}")

    period_columns = [column for column in frame.columns if _period_end_from_column(str(column))]
    if not period_columns:
        raise ValueError("financial abstract contains no YYYYMMDD period columns")
    retrieved = retrieved_at or _retrieved_at()
    rows: list[dict[str, Any]] = []

    for metric, provider_labels, unit, currency, divisor in _ACTUAL_METRICS:
        matches = frame.loc[frame["指标"].isin(provider_labels)]
        if matches.empty:
            continue
        # The first occurrence is the headline section.  This avoids writing
        # repeated provider rows as if they were independent observations.
        source_row = matches.iloc[0]
        provider_metric = str(source_row["指标"])
        for column in period_columns:
            raw_value = _numeric(source_row[column])
            period_end = _period_end_from_column(str(column))
            if raw_value is None or period_end is None:
                continue
            value_native = raw_value / divisor if divisor != 1 else raw_value
            value_usd = None
            fx_pair = None
            fx_date = None
            fx_value = None
            usd_unit = None
            if currency == "RMB":
                fx_pair = "USD_CNY"
                fx_date, fx_value = _fx_asof(fx_rates, pair=fx_pair, as_of=period_end)
                if fx_value is not None:
                    value_usd = value_native / fx_value
                    usd_unit = "USD million" if unit == "RMB million" else "USD/share"

            rows.append(
                {
                    "dataset_id": "airline_financial_actuals_akshare",
                    "ticker": A_SHARE_AIRLINES.get(symbol, {}).get("ticker", symbol),
                    "company": company,
                    "statement_period": f"{period_end[:4]}-{period_end[5:7]}",
                    "period_end": period_end,
                    "metric": metric,
                    "provider_metric": provider_metric,
                    "value_native": value_native,
                    "native_unit": unit,
                    "native_currency": currency or None,
                    "value_usd": value_usd,
                    "usd_unit": usd_unit,
                    "fx_pair": fx_pair,
                    "fx_observation_date": fx_date,
                    "fx_value": fx_value,
                    "source_quality": "akshare_discovery",
                    "announcement_date_available": False,
                    "source_url": (
                        "https://vip.stock.finance.sina.com.cn/corp/go.php/"
                        f"vFD_FinanceSummary/stockid/{symbol}.phtml"
                    ),
                    "source_note": (
                        "AkShare/Sina financial abstract; period and provider value are retained, "
                        "but the endpoint does not expose issuer announcement date. "
                        "Interim values may be year-to-date rather than standalone quarter."
                    ),
                    "retrieved_at": retrieved,
                }
            )

    result = pd.DataFrame(rows, columns=ACTUAL_COLUMNS)
    if result.empty:
        return result
    return result.sort_values(["ticker", "period_end", "metric"]).reset_index(drop=True)


def normalize_profit_forecast(
    frame: pd.DataFrame,
    *,
    symbol: str,
    company: str,
    metric: str,
    fx_rates: pd.DataFrame | None = None,
    snapshot_date: str | None = None,
    forecast_date_min: str | None = None,
    forecast_date_max: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Normalize 10jqka annual EPS and net-profit forecast ranges."""
    required = {"年度", "预测机构数", "最小值", "均值", "最大值", "行业平均数"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"profit forecast is missing columns: {sorted(missing)}")
    snap = snapshot_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    retrieved = retrieved_at or _retrieved_at()
    latest_fx_date, latest_fx = _fx_asof(
        fx_rates,
        pair="USD_CNY",
        as_of=snap,
    )
    rows: list[dict[str, Any]] = []
    if metric not in {"eps", "net_profit"}:
        raise ValueError("metric must be 'eps' or 'net_profit'")
    # THS returns net profit in RMB 100 million (亿元) and EPS in RMB/share.
    for _, source_row in frame.iterrows():
        year = int(source_row["年度"])
        broker_count = _numeric(source_row["预测机构数"])
        unit = "RMB/share" if metric == "eps" else "RMB 100 million"
        value_avg = _numeric(source_row["均值"])
        value_low = _numeric(source_row["最小值"])
        value_high = _numeric(source_row["最大值"])
        industry_average = _numeric(source_row["行业平均数"])
        if value_avg is None and value_low is None and value_high is None:
            continue
        value_avg_usd = value_avg / latest_fx if latest_fx and metric == "net_profit" else None
        value_low_usd = value_low / latest_fx if latest_fx and metric == "net_profit" else None
        value_high_usd = value_high / latest_fx if latest_fx and metric == "net_profit" else None
        rows.append(
            {
                "dataset_id": "airline_consensus_ashare_akshare",
                "ticker": A_SHARE_AIRLINES.get(symbol, {}).get("ticker", symbol),
                "company": company,
                "snapshot_date": snap,
                "fiscal_year": year,
                "metric": metric,
                "value_avg_native": value_avg,
                "value_low_native": value_low,
                "value_high_native": value_high,
                "native_unit": unit,
                "native_currency": "RMB",
                "value_avg_usd_at_snapshot": value_avg_usd,
                "value_low_usd_at_snapshot": value_low_usd,
                "value_high_usd_at_snapshot": value_high_usd,
                "forecast_count": broker_count,
                "industry_average_native": industry_average,
                "forecast_date_min": forecast_date_min,
                "forecast_date_max": forecast_date_max,
                "source_quality": "akshare_discovery",
                "revision_history_available": False,
                "source_url": f"https://basic.10jqka.com.cn/new/{symbol}/worth.html",
                "source_note": (
                    "Static public 10jqka forecast range retrieved through AkShare; "
                    "net profit is RMB 100 million and USD values use the latest "
                    f"available USD/CNY snapshot ({latest_fx_date or 'unavailable'}), "
                    "not a forward FX forecast. No historical revision vintages."
                ),
                "retrieved_at": retrieved,
            }
        )
    result = pd.DataFrame(rows, columns=CONSENSUS_COLUMNS)
    if result.empty:
        return result
    return result.sort_values(["ticker", "fiscal_year", "metric"]).reset_index(drop=True)


def _detailed_forecast_numeric(value: Any) -> float | None:
    """Parse 10jqka's displayed amount/percentage strings."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--", "nan"}:
        return None
    if text.endswith("%"):
        return _numeric(text[:-1])
    if "万亿" in text:
        parsed = _numeric(text.replace("万亿", ""))
        return parsed * 10000 if parsed is not None else None
    if "亿" in text:
        parsed = _numeric(text.replace("亿", ""))
        return parsed if parsed is not None else None
    return _numeric(text)


def normalize_detailed_indicator_forecast(
    frame: pd.DataFrame,
    *,
    symbol: str,
    company: str,
    fx_rates: pd.DataFrame | None = None,
    snapshot_date: str | None = None,
    forecast_date_min: str | None = None,
    forecast_date_max: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Normalize 10jqka's average detailed operating/earnings forecasts.

    This endpoint provides average values only. It is intentionally separate
    from the low/average/high EPS and net-profit range layer because it does
    not expose a comparable low/high range or broker count for each metric.
    """
    required = {"预测指标"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"detailed forecast is missing columns: {sorted(missing)}")
    snap = snapshot_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    retrieved = retrieved_at or _retrieved_at()
    latest_fx_date, latest_fx = _fx_asof(fx_rates, pair="USD_CNY", as_of=snap)
    metric_map = {
        "营业收入(元)": ("revenue", "RMB 100 million", "RMB"),
        "营业收入增长率": ("revenue_growth", "%", None),
        "利润总额(元)": ("profit_before_tax", "RMB 100 million", "RMB"),
        "净利润(元)": ("net_profit_detailed", "RMB 100 million", "RMB"),
        "净利润增长率": ("net_profit_growth", "%", None),
        "净资产收益率": ("roe_detailed", "%", None),
        "净资产收益率(ROE)": ("roe_detailed", "%", None),
    }
    rows: list[dict[str, Any]] = []
    for _, source_row in frame.iterrows():
        source_metric = str(source_row["预测指标"]).strip()
        mapping = metric_map.get(source_metric)
        if mapping is None:
            continue
        metric, unit, currency = mapping
        for column in frame.columns:
            match = re.match(r"预测(?P<year>\d{4})-平均", str(column).strip())
            if not match:
                continue
            value_native = _detailed_forecast_numeric(source_row[column])
            if value_native is None:
                continue
            value_usd = value_native / latest_fx if currency == "RMB" and latest_fx else None
            rows.append({
                "dataset_id": "airline_consensus_ashare_detailed",
                "ticker": A_SHARE_AIRLINES.get(symbol, {}).get("ticker", symbol),
                "company": company,
                "snapshot_date": snap,
                "fiscal_year": int(match.group("year")),
                "metric": metric,
                "value_avg_native": value_native,
                "native_unit": unit,
                "native_currency": currency,
                "value_avg_usd_at_snapshot": value_usd,
                "fx_observation_date": latest_fx_date if currency == "RMB" else None,
                "fx_value": latest_fx if currency == "RMB" else None,
                "forecast_date_min": forecast_date_min,
                "forecast_date_max": forecast_date_max,
                "source_quality": "akshare_discovery",
                "revision_history_available": False,
                "source_url": f"https://basic.10jqka.com.cn/new/{symbol}/worth.html",
                "source_note": (
                    "10jqka detailed-indicator average forecast retrieved through AkShare. "
                    "This layer has no metric-level low/high range or broker count and is not "
                    f"a complete PIT consensus vintage; USD conversion uses the USD/CNY snapshot "
                    f"as of {latest_fx_date or 'unavailable'}."
                ),
                "retrieved_at": retrieved,
            })
    result = pd.DataFrame(rows, columns=DETAILED_CONSENSUS_COLUMNS)
    if result.empty:
        return result
    return result.sort_values(["ticker", "fiscal_year", "metric"]).reset_index(drop=True)


def merge_airline_consensus_history(
    prior: pd.DataFrame,
    current: pd.DataFrame,
    *,
    key_columns: list[str],
) -> pd.DataFrame:
    """Append A-share consensus snapshots while replacing only the same PIT key."""
    result = pd.concat([prior, current], ignore_index=True)
    if result.empty:
        return result
    if "ticker" in result.columns:
        result["ticker"] = result["ticker"].replace(AIRLINE_TICKER_ALIASES)
    result = result.drop_duplicates(subset=key_columns, keep="last")
    sort_columns = [
        column
        for column in ("company", "ticker", "snapshot_date", "fiscal_year", "metric")
        if column in result.columns
    ]
    return (
        result.sort_values(sort_columns).reset_index(drop=True)
        if sort_columns
        else result.reset_index(drop=True)
    )


def _normalize_report_rows(
    frame: pd.DataFrame,
    *,
    symbol: str,
    company: str,
    retrieved_at: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=REPORT_COLUMNS)
    rename_map = {
        "日期": "report_date",
        "报告名称": "report_title",
        "机构": "institution",
        "东财评级": "rating",
        "2026-盈利预测-收益": "eps_2026_native",
        "2027-盈利预测-收益": "eps_2027_native",
        "2028-盈利预测-收益": "eps_2028_native",
        "2026-盈利预测-市盈率": "pe_2026",
        "2027-盈利预测-市盈率": "pe_2027",
        "2028-盈利预测-市盈率": "pe_2028",
        "报告PDF链接": "report_url",
    }
    result = frame.rename(columns=rename_map).copy()
    for column in REPORT_COLUMNS:
        if column not in result.columns:
            result[column] = None
    result["dataset_id"] = "airline_sell_side_reports_akshare"
    result["ticker"] = A_SHARE_AIRLINES.get(symbol, {}).get("ticker", symbol)
    result["company"] = company
    result["source_quality"] = "akshare_discovery"
    result["source_note"] = (
        "Eastmoney public research-report discovery feed; report PDF links and "
        "ratings are retained for manual primary-source review."
    )
    result["retrieved_at"] = retrieved_at
    result = result[REPORT_COLUMNS]
    result["report_date"] = pd.to_datetime(result["report_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return result


def _load_fx_rates() -> pd.DataFrame | None:
    path = NORMALIZED_DIR / "airline_fx_rates.parquet"
    return pd.read_parquet(path) if path.exists() else None


def normalize_sell_side_forecast_revisions(
    frame: pd.DataFrame,
    *,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Create dated broker-EPS revision observations from the discovery feed.

    This is a broker-report history, not a complete institutional consensus
    tape.  A revision is the latest available EPS forecast for one
    ticker/institution/fiscal-year compared with that institution's prior
    dated report in the public feed.
    """
    required = {"ticker", "company", "report_date", "institution"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"sell-side report feed is missing columns: {sorted(missing)}")
    retrieved = retrieved_at or _retrieved_at()
    source = frame.copy()
    source["ticker"] = source["ticker"].replace(AIRLINE_TICKER_ALIASES)
    source["report_date"] = pd.to_datetime(source["report_date"], errors="coerce")
    source = source.dropna(subset=["report_date"]).sort_values(
        ["ticker", "institution", "report_date", "report_title"],
    )
    rows: list[dict[str, Any]] = []
    previous: dict[tuple[str, str, int], tuple[str, float]] = {}
    for _, report in source.iterrows():
        for fiscal_year in (2026, 2027, 2028):
            eps = _numeric(report.get(f"eps_{fiscal_year}_native"))
            if eps is None:
                continue
            key = (str(report["ticker"]), str(report["institution"]), fiscal_year)
            report_date = report["report_date"].strftime("%Y-%m-%d")
            prior_date, prior_eps = previous.get(key, (None, None))
            change = eps - prior_eps if prior_eps is not None else None
            change_pct = None
            if prior_eps not in (None, 0):
                change_pct = 100.0 * change / abs(prior_eps)
            rows.append(
                {
                    "dataset_id": "airline_sell_side_forecast_revisions",
                    "ticker": report["ticker"],
                    "company": report["company"],
                    "institution": report["institution"],
                    "fiscal_year": fiscal_year,
                    "report_date": report_date,
                    "prior_report_date": prior_date,
                    "eps_native": eps,
                    "prior_eps_native": prior_eps,
                    "eps_change_native": change,
                    "eps_change_pct": change_pct,
                    "rating": report.get("rating"),
                    "report_title": report.get("report_title"),
                    "report_url": report.get("report_url"),
                    "source_quality": "akshare_discovery",
                    "source_note": (
                        "Derived from dated Eastmoney research-report discovery rows. "
                        "Prior value is the previous available report by the same institution; "
                        "this is not a complete consensus-revision history."
                    ),
                    "retrieved_at": retrieved,
                }
            )
            previous[key] = (report_date, eps)
    result = pd.DataFrame(rows, columns=REVISION_COLUMNS)
    if result.empty:
        return result
    return result.sort_values(["ticker", "institution", "fiscal_year", "report_date"]).reset_index(drop=True)


def fetch_a_share_airline_financial_layers(
    *,
    symbols: dict[str, dict[str, str]] | None = None,
    snapshot_date: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Fetch A-share actuals, annual forecasts and recent research reports."""
    try:
        import akshare as ak
    except ImportError as exc:  # pragma: no cover - dependency is project-level
        raise RuntimeError("akshare is required for the A-share discovery layer") from exc

    universe = symbols or A_SHARE_AIRLINES
    retrieved = _retrieved_at()
    fx_rates = _load_fx_rates()
    actual_frames: list[pd.DataFrame] = []
    consensus_frames: list[pd.DataFrame] = []
    report_frames: list[pd.DataFrame] = []
    detailed_consensus_frames: list[pd.DataFrame] = []

    for symbol, metadata in universe.items():
        company = metadata["company"]
        abstract = _call_akshare_with_timeout(ak.stock_financial_abstract, symbol=symbol)
        actual_frames.append(
            normalize_financial_abstract(
                abstract,
                symbol=symbol,
                company=company,
                fx_rates=fx_rates,
                retrieved_at=retrieved,
            )
        )

        detail_dates: tuple[str | None, str | None] = (None, None)
        try:
            detail = _call_akshare_with_timeout(
                ak.stock_profit_forecast_ths,
                symbol=symbol,
                indicator="业绩预测详表-机构",
            )
            if not detail.empty and "报告日期" in detail.columns:
                dates = pd.to_datetime(detail["报告日期"], errors="coerce").dropna()
                if not dates.empty:
                    detail_dates = (
                        dates.min().strftime("%Y-%m-%d"),
                        dates.max().strftime("%Y-%m-%d"),
                    )
        except Exception:
            # The summary range is still useful when the institution-detail
            # endpoint is temporarily unavailable.
            pass

        for metric_name, indicator in (
            ("net_profit", "预测年报净利润"),
            ("eps", "预测年报每股收益"),
        ):
            forecast = _call_akshare_with_timeout(
                ak.stock_profit_forecast_ths,
                symbol=symbol,
                indicator=indicator,
            )
            normalized = normalize_profit_forecast(
                forecast,
                symbol=symbol,
                company=company,
                metric=metric_name,
                fx_rates=fx_rates,
                snapshot_date=snapshot_date,
                forecast_date_min=detail_dates[0],
                forecast_date_max=detail_dates[1],
                retrieved_at=retrieved,
            )
            # Record the source indicator in the note without changing the
            # stable schema.
            normalized["source_note"] = normalized["source_note"].str.replace(
                "Static public 10jqka forecast range",
                f"Static public 10jqka {indicator} range",
                regex=False,
            )
            consensus_frames.append(normalized)

        try:
            detailed_forecast = _call_akshare_with_timeout(
                ak.stock_profit_forecast_ths,
                symbol=symbol,
                indicator="业绩预测详表-详细指标预测",
            )
            detailed_consensus_frames.append(
                normalize_detailed_indicator_forecast(
                    detailed_forecast,
                    symbol=symbol,
                    company=company,
                    fx_rates=fx_rates,
                    snapshot_date=snapshot_date,
                    forecast_date_min=detail_dates[0],
                    forecast_date_max=detail_dates[1],
                    retrieved_at=retrieved,
                )
            )
        except Exception:
            # Keep the existing EPS/net-profit ranges usable if this optional
            # detailed endpoint is temporarily unavailable.
            pass

        reports = _call_akshare_with_timeout(ak.stock_research_report_em, symbol=symbol)
        report_frames.append(
            _normalize_report_rows(
                reports,
                symbol=symbol,
                company=company,
                retrieved_at=retrieved,
            )
        )

    actual_frames = [frame for frame in actual_frames if not frame.empty]
    consensus_frames = [frame for frame in consensus_frames if not frame.empty]
    report_frames = [frame for frame in report_frames if not frame.empty]
    actuals = pd.concat(actual_frames, ignore_index=True) if actual_frames else pd.DataFrame(columns=ACTUAL_COLUMNS)
    consensus = pd.concat(consensus_frames, ignore_index=True) if consensus_frames else pd.DataFrame(columns=CONSENSUS_COLUMNS)
    reports = pd.concat(report_frames, ignore_index=True) if report_frames else pd.DataFrame(columns=REPORT_COLUMNS)
    detailed_consensus = (
        pd.concat([frame for frame in detailed_consensus_frames if not frame.empty], ignore_index=True)
        if any(not frame.empty for frame in detailed_consensus_frames)
        else pd.DataFrame(columns=DETAILED_CONSENSUS_COLUMNS)
    )

    actual_path = NORMALIZED_DIR / "airline_financial_actuals_akshare_snapshot.csv"
    consensus_path = NORMALIZED_DIR / "airline_consensus_ashare_snapshot.csv"
    reports_path = NORMALIZED_DIR / "airline_sell_side_reports_akshare_snapshot.csv"
    revisions = normalize_sell_side_forecast_revisions(reports, retrieved_at=retrieved)
    revisions_path = NORMALIZED_DIR / "airline_sell_side_forecast_revisions.csv"
    detailed_consensus_path = NORMALIZED_DIR / "airline_consensus_ashare_detailed.csv"
    actuals.to_csv(actual_path, index=False)
    if consensus_path.exists():
        consensus = merge_airline_consensus_history(
            pd.read_csv(consensus_path),
            consensus,
            key_columns=["ticker", "snapshot_date", "fiscal_year", "metric"],
        )
    consensus.to_csv(consensus_path, index=False)
    reports.to_csv(reports_path, index=False)
    revisions.to_csv(revisions_path, index=False)
    if detailed_consensus_path.exists():
        detailed_consensus = merge_airline_consensus_history(
            pd.read_csv(detailed_consensus_path),
            detailed_consensus,
            key_columns=["ticker", "snapshot_date", "fiscal_year", "metric"],
        )
    detailed_consensus.to_csv(detailed_consensus_path, index=False)
    return {
        "actuals": actuals,
        "consensus": consensus,
        "detailed_consensus": detailed_consensus,
        "reports": reports,
        "revisions": revisions,
    }


def source_paths() -> dict[str, Path]:
    """Return normalized output paths for dashboard/source-registry use."""
    return {
        "actuals": NORMALIZED_DIR / "airline_financial_actuals_akshare_snapshot.csv",
        "consensus": NORMALIZED_DIR / "airline_consensus_ashare_snapshot.csv",
        "detailed_consensus": NORMALIZED_DIR / "airline_consensus_ashare_detailed.csv",
        "reports": NORMALIZED_DIR / "airline_sell_side_reports_akshare_snapshot.csv",
        "revisions": NORMALIZED_DIR / "airline_sell_side_forecast_revisions.csv",
    }
