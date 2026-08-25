"""Vendor financial-statement overlay for Control Tower company pages.

This is not the official earnings-actuals mart. Official actuals stay on the
HKEX/SEC disclosure path. These rows are a labelled, fail-closed read of the
sibling financial-data observation store, optionally materialised into a local
Control Tower mart:

* yfinance income-statement / cash-flow line items
* akshare Eastmoney HK financial indicators

They are marked PROVIDER_UNVERIFIED. There is no announcement timestamp, no
IFRS vs Non-IFRS split, and no segment mix. The company page must render them
separately from official issuer actuals.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd

VENDOR_SOURCE_QUALITY = "provider_unverified"
VENDOR_METRIC_BASIS = "PROVIDER_UNVERIFIED"
VENDOR_ACCOUNTING_BASIS = "Vendor reported (unverified)"
VENDOR_PIT_CLASS = "vendor_historical_replay"
VENDOR_LICENSE_CLASS = "personal_use_terms_unverified"
MIN_SNAPSHOT_BYTES = 100_000
SNAPSHOT_DATE_RE = re.compile(r"snapshot_date=(\d{4}-\d{2}-\d{2})")
FILENAME_TS_RE = re.compile(r"(20\d{6}T\d{6}Z)")

YF_METRIC_MAP: dict[tuple[str, str], str] = {
    ("income_statement", "revenue"): "revenue_total",
    ("income_statement", "operating_income"): "operating_profit",
    ("income_statement", "net_income_attributable"): "net_profit_attributable",
    ("income_statement", "net_income"): "net_profit_attributable",
    ("income_statement", "diluted_eps"): "diluted_eps",
    ("income_statement", "gross_profit"): "gross_profit",
    ("cash_flow", "free_cash_flow"): "free_cash_flow",
    ("cash_flow", "capital_expenditure"): "capex",
}
AK_METRIC_MAP: dict[str, str] = {
    "akshare_revenue": "revenue_total",
    "net_income_attributable": "net_profit_attributable",
    "diluted_eps": "diluted_eps",
    "gross_profit": "gross_profit",
    "gross_profit_ratio": "gross_margin_pct",
}
SCALE_SAFE_METRICS = {
    "revenue_total",
    "operating_profit",
    "net_profit_attributable",
    "gross_profit",
    "free_cash_flow",
    "capex",
}

VENDOR_COLUMNS = [
    "entity_id",
    "listing_id",
    "canonical_ticker",
    "provider",
    "source_id",
    "source_label",
    "metric",
    "source_metric",
    "source_metric_label",
    "period_type",
    "period_label",
    "period_end",
    "reported_value",
    "currency",
    "currency_semantics",
    "unit",
    "interim_is_ytd",
    "accounting_basis",
    "metric_basis",
    "source_quality",
    "pit_class",
    "source_license_class",
    "announcement_date",
    "retrieved_at_utc",
    "source_path",
    "source_note",
]


@dataclass(frozen=True)
class VendorLoadResult:
    frame: pd.DataFrame
    status: str
    detail: str
    source_kind: str


def _observations_root(path: Path) -> Path:
    return path / "data" / "processed" / "hk_financials" / "financial_observations"


def financial_data_root(explicit: Path | None = None) -> Path | None:
    """Resolve the sibling financial-data repository without inventing a path.

    An explicit argument or FINANCIAL_DATA_ROOT is fail-closed: if that path
    has no observation store, we do not silently fall back to another clone.
    Default discovery only runs when neither override is set.
    """

    if explicit is not None:
        path = Path(explicit)
        return path if _observations_root(path).is_dir() else None
    env = os.environ.get("FINANCIAL_DATA_ROOT", "").strip()
    if env:
        path = Path(env)
        return path if _observations_root(path).is_dir() else None
    home = Path.home()
    candidates = [
        home / "Desktop" / "Quant" / "financial-data",
        home / "Quant" / "financial-data",
        Path(__file__).resolve().parents[2].parent / "financial-data",
    ]
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if _observations_root(path).is_dir():
            return path
    return None


def default_local_mart_path(repo_root: Path | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    return root / "data" / "normalized" / "marts" / "vendor_financials_v1.parquet"


def _snapshot_date_token(path: Path) -> str:
    for part in path.parts:
        match = SNAPSHOT_DATE_RE.fullmatch(part) if False else SNAPSHOT_DATE_RE.search(part)
        if match:
            return match.group(1)
    match = FILENAME_TS_RE.search(path.name)
    if match:
        token = match.group(1)
        return f"{token[0:4]}-{token[4:6]}-{token[6:8]}"
    return ""


def _latest_observation_file(root: Path, source: str) -> Path | None:
    """Pick the newest *complete* observation snapshot, not pipeline manifests.

    Later snapshot_date directories in financial-data can contain tiny run
    manifests. Those must not win over a multi-megabyte observation file.
    """

    folder = _observations_root(root) / f"source={source}"
    if not folder.is_dir():
        return None
    files = list(folder.rglob("*.parquet"))
    usable = [path for path in files if path.stat().st_size >= MIN_SNAPSHOT_BYTES]
    if not usable:
        return None
    return max(usable, key=lambda path: (_snapshot_date_token(path), path.stat().st_mtime_ns))


def _period_label(period_end: object, period_type: str) -> str:
    parsed = pd.Timestamp(period_end)
    if pd.isna(parsed):
        return ""
    kind = str(period_type or "").strip().lower()
    if kind == "annual":
        return f"FY{parsed.year}"
    return f"period ended {parsed.date().isoformat()}"


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=VENDOR_COLUMNS)


def _canonical_tickers(listings: pd.DataFrame, listing_id: str | None) -> list[str]:
    if listings is None or listings.empty:
        return []
    frame = listings.copy()
    if listing_id:
        scoped = frame.loc[frame["listing_id"].astype("string").eq(str(listing_id))]
        if not scoped.empty:
            frame = scoped
    tickers: list[str] = []
    for _, row in frame.iterrows():
        canonical = str(row.get("canonical_ticker") or "").strip()
        native = str(row.get("native_ticker") or "").strip()
        if canonical:
            tickers.append(canonical)
        if native and "." not in native:
            tickers.append(f"{native}.HK")
        elif native:
            tickers.append(native)
    out: list[str] = []
    seen: set[str] = set()
    for ticker in tickers:
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


def _period_key(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["_period_key"] = (
        out["ticker"].astype("string")
        + chr(0x1F)
        + out["fiscal_period_end"].astype("string")
        + chr(0x1F)
        + out["period_type"].astype("string")
    )
    return out


def _prefer_total_revenue(frame: pd.DataFrame) -> pd.DataFrame:
    revenue = frame["metric"].eq("revenue") & frame["statement_type"].eq("income_statement")
    if not revenue.any():
        return frame
    labels = frame.get("metric_label", pd.Series("", index=frame.index, dtype="string")).astype("string")
    total = revenue & labels.str.casefold().eq("total revenue")
    operating = revenue & labels.str.casefold().eq("operating revenue")
    if not total.any():
        return frame
    keyed = _period_key(frame)
    total_keys = set(keyed.loc[total, "_period_key"])
    drop = operating & keyed["_period_key"].isin(total_keys)
    return frame.loc[~drop].copy()


def _prefer_attributable_income(frame: pd.DataFrame) -> pd.DataFrame:
    attributable = frame["metric"].eq("net_income_attributable") & frame["statement_type"].eq(
        "income_statement"
    )
    net = frame["metric"].eq("net_income") & frame["statement_type"].eq("income_statement")
    if not attributable.any() or not net.any():
        return frame
    keyed = _period_key(frame)
    keep_keys = set(keyed.loc[attributable, "_period_key"])
    drop = net & keyed["_period_key"].isin(keep_keys)
    return frame.loc[~drop].copy()


def _row(
    *,
    entity_id: str,
    listing_id: str,
    ticker: str,
    provider: str,
    canonical: str,
    source_metric: str,
    source_metric_label: str,
    period_type: str,
    period_end: pd.Timestamp,
    value: float,
    currency: str,
    currency_semantics: str,
    unit: str,
    interim_is_ytd: bool,
    retrieved_at_utc: object,
    source_path: Path,
    source_note: str,
) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "listing_id": listing_id,
        "canonical_ticker": ticker,
        "provider": provider,
        "source_id": f"financial_data:{provider}:financial_observations",
        "source_label": (
            "yfinance via financial-data"
            if provider == "yfinance"
            else "akshare / Eastmoney via financial-data"
        ),
        "metric": canonical,
        "source_metric": source_metric,
        "source_metric_label": source_metric_label,
        "period_type": period_type,
        "period_label": _period_label(period_end, period_type),
        "period_end": period_end.tz_localize(None) if getattr(period_end, "tzinfo", None) else period_end,
        "reported_value": value,
        "currency": currency,
        "currency_semantics": currency_semantics,
        "unit": unit,
        "interim_is_ytd": bool(interim_is_ytd),
        "accounting_basis": VENDOR_ACCOUNTING_BASIS,
        "metric_basis": VENDOR_METRIC_BASIS,
        "source_quality": VENDOR_SOURCE_QUALITY,
        "pit_class": VENDOR_PIT_CLASS,
        "source_license_class": VENDOR_LICENSE_CLASS,
        "announcement_date": pd.NaT,
        "retrieved_at_utc": pd.to_datetime(retrieved_at_utc, errors="coerce", utc=True),
        "source_path": str(source_path),
        "source_note": source_note,
    }


def _map_yfinance(frame: pd.DataFrame, *, entity_id: str, listing_id: str, source_path: Path) -> pd.DataFrame:
    if frame.empty:
        return _empty()
    working = frame.copy()
    working["metric"] = working["metric"].astype("string")
    working["statement_type"] = working["statement_type"].astype("string")
    working = _prefer_total_revenue(working)
    working = _prefer_attributable_income(working)
    rows: list[dict[str, Any]] = []
    for _, item in working.iterrows():
        canonical = YF_METRIC_MAP.get((str(item.get("statement_type") or ""), str(item.get("metric") or "")))
        if not canonical:
            continue
        period_end = pd.to_datetime(item.get("fiscal_period_end"), errors="coerce")
        if pd.isna(period_end):
            continue
        value = pd.to_numeric(pd.Series([item.get("value")]), errors="coerce").iloc[0]
        if pd.isna(value):
            continue
        rows.append(
            _row(
                entity_id=entity_id,
                listing_id=listing_id,
                ticker=str(item.get("ticker") or ""),
                provider="yfinance",
                canonical=canonical,
                source_metric=str(item.get("metric") or ""),
                source_metric_label=str(item.get("metric_label") or item.get("metric") or ""),
                period_type=str(item.get("period_type") or ""),
                period_end=period_end,
                value=float(value),
                currency=str(item.get("currency") or ""),
                currency_semantics=str(item.get("currency_semantics") or "reporting_currency"),
                unit=str(item.get("unit") or ""),
                interim_is_ytd=False,
                retrieved_at_utc=item.get("fetched_at"),
                source_path=source_path,
                source_note=(
                    "Sibling financial-data yfinance statement observation. "
                    "Not official issuer disclosure; no announcement timestamp; "
                    "Yahoo may keep both Total Revenue and Operating Revenue."
                ),
            )
        )
    return pd.DataFrame(rows, columns=VENDOR_COLUMNS)


def _map_akshare(frame: pd.DataFrame, *, entity_id: str, listing_id: str, source_path: Path) -> pd.DataFrame:
    if frame.empty:
        return _empty()
    rows: list[dict[str, Any]] = []
    for _, item in frame.iterrows():
        canonical = AK_METRIC_MAP.get(str(item.get("metric") or ""))
        if not canonical:
            continue
        period_end = pd.to_datetime(item.get("fiscal_period_end"), errors="coerce")
        if pd.isna(period_end):
            continue
        value = pd.to_numeric(pd.Series([item.get("value")]), errors="coerce").iloc[0]
        if pd.isna(value):
            continue
        period_type = str(item.get("period_type") or "")
        rows.append(
            _row(
                entity_id=entity_id,
                listing_id=listing_id,
                ticker=str(item.get("ticker") or ""),
                provider="akshare",
                canonical=canonical,
                source_metric=str(item.get("metric") or ""),
                source_metric_label=str(item.get("metric_label") or item.get("metric") or ""),
                period_type=period_type,
                period_end=period_end,
                value=float(value),
                currency=str(item.get("currency") or ""),
                currency_semantics=str(item.get("currency_semantics") or "source_reported_unverified"),
                unit=str(item.get("unit") or ""),
                interim_is_ytd=period_type.strip().lower() == "interim",
                retrieved_at_utc=item.get("fetched_at"),
                source_path=source_path,
                source_note=(
                    "Sibling financial-data akshare indicator observation. "
                    "Not official issuer disclosure; currency labels are source-reported "
                    "and unverified; interim rows are year-to-date cumulatives, not single quarters."
                ),
            )
        )
    return pd.DataFrame(rows, columns=VENDOR_COLUMNS)


def _collect_from_sibling(
    *,
    entity_id: str,
    listing_id: str | None,
    listings: pd.DataFrame,
    financial_data_root_path: Path | None = None,
) -> VendorLoadResult:
    root = financial_data_root(financial_data_root_path)
    if root is None:
        return VendorLoadResult(_empty(), "unavailable", "sibling financial-data observation store not found", "sibling_store")
    tickers = _canonical_tickers(listings, listing_id)
    if not tickers:
        return VendorLoadResult(_empty(), "unavailable", "no canonical ticker on the selected listing", "sibling_store")
    frames: list[pd.DataFrame] = []
    notes: list[str] = []
    yf_path = _latest_observation_file(root, "yfinance")
    if yf_path is None:
        notes.append("yfinance complete snapshot missing")
    else:
        raw = pd.read_parquet(yf_path)
        ticker_col = raw.get("ticker", pd.Series(dtype="string")).astype("string")
        frames.append(
            _map_yfinance(
                raw.loc[ticker_col.isin(tickers)],
                entity_id=entity_id,
                listing_id=str(listing_id or ""),
                source_path=yf_path,
            )
        )
    ak_path = _latest_observation_file(root, "akshare")
    if ak_path is None:
        notes.append("akshare complete snapshot missing")
    else:
        raw = pd.read_parquet(ak_path)
        ticker_col = raw.get("ticker", pd.Series(dtype="string")).astype("string")
        frames.append(
            _map_akshare(
                raw.loc[ticker_col.isin(tickers)],
                entity_id=entity_id,
                listing_id=str(listing_id or ""),
                source_path=ak_path,
            )
        )
    if not frames:
        return VendorLoadResult(_empty(), "unavailable", "; ".join(notes) or "no vendor snapshots", "sibling_store")
    out = pd.concat(frames, ignore_index=True)
    if out.empty:
        detail = "; ".join(notes) if notes else "no matching vendor rows for this listing"
        return VendorLoadResult(_empty(), "unavailable", detail, "sibling_store")
    out["period_end"] = pd.to_datetime(out["period_end"], errors="coerce")
    out = out.sort_values(["provider", "metric", "period_end", "period_type"], na_position="last").reset_index(drop=True)
    detail = f"sibling financial-data store · {len(out)} labelled vendor rows"
    if notes:
        detail = f"{detail}; {'; '.join(notes)}"
    return VendorLoadResult(out, "available", detail, "sibling_store")


def _normalize_local_mart(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in VENDOR_COLUMNS:
        if column not in out.columns:
            out[column] = pd.NA
    if "interim_is_ytd" in out.columns:
        out["interim_is_ytd"] = out["interim_is_ytd"].fillna(False).astype(bool)
    out["period_end"] = pd.to_datetime(out["period_end"], errors="coerce")
    return out.loc[:, VENDOR_COLUMNS]


def load_local_vendor_mart(path: Path | None = None) -> VendorLoadResult:
    mart = Path(path) if path is not None else default_local_mart_path()
    if not mart.is_file():
        return VendorLoadResult(_empty(), "unavailable", f"local vendor mart missing: {mart}", "local_mart")
    try:
        frame = _normalize_local_mart(pd.read_parquet(mart))
    except (OSError, ValueError) as exc:
        return VendorLoadResult(_empty(), "error", f"local vendor mart unreadable: {mart} ({exc})", "local_mart")
    if frame.empty:
        return VendorLoadResult(_empty(), "unavailable", f"local vendor mart is empty: {mart}", "local_mart")
    return VendorLoadResult(frame, "available", f"local vendor mart {mart.name} · {len(frame)} rows", "local_mart")


def load_vendor_financials(
    *,
    entity_id: str,
    listing_id: str | None,
    listings: pd.DataFrame,
    financial_data_root_path: Path | None = None,
    local_mart_path: Path | None = None,
    allow_sibling_fallback: bool = True,
) -> VendorLoadResult:
    """Load labelled vendor financials for one Control Tower entity.

    Prefers the local Control Tower mart. Sibling-store fallback is local-only
    and never writes into official earnings_actuals.
    """

    local = load_local_vendor_mart(local_mart_path)
    if local.status == "available":
        frame = local.frame
        if "entity_id" in frame.columns:
            frame = frame.loc[frame["entity_id"].astype("string").eq(str(entity_id))].copy()
        if listing_id and "listing_id" in frame.columns:
            listing = frame["listing_id"].astype("string")
            frame = frame.loc[listing.eq("") | listing.eq(str(listing_id))].copy()
        if frame.empty:
            return VendorLoadResult(
                _empty(),
                "unavailable",
                f"local vendor mart has no rows for {entity_id}/{listing_id or 'entity'}",
                "local_mart",
            )
        return VendorLoadResult(frame.reset_index(drop=True), "available", local.detail, "local_mart")
    if local.status == "error":
        return local
    if not allow_sibling_fallback:
        return local
    try:
        return _collect_from_sibling(
            entity_id=entity_id,
            listing_id=listing_id,
            listings=listings,
            financial_data_root_path=financial_data_root_path,
        )
    except (OSError, ValueError) as exc:
        return VendorLoadResult(_empty(), "error", f"sibling vendor store failed: {exc}", "sibling_store")


def materialize_vendor_financials(
    listings: pd.DataFrame,
    *,
    output_path: Path | None = None,
    financial_data_root_path: Path | None = None,
) -> VendorLoadResult:
    """Collect vendor rows for every supplied listing into a local mart."""

    if listings is None or listings.empty:
        return VendorLoadResult(_empty(), "unavailable", "no listings supplied", "local_mart")
    frames: list[pd.DataFrame] = []
    notes: list[str] = []
    for _, listing in listings.iterrows():
        entity_id = str(listing.get("entity_id") or "").strip()
        listing_id = str(listing.get("listing_id") or "").strip()
        if not entity_id or not listing_id:
            continue
        result = _collect_from_sibling(
            entity_id=entity_id,
            listing_id=listing_id,
            listings=pd.DataFrame([listing]),
            financial_data_root_path=financial_data_root_path,
        )
        if result.status == "available" and not result.frame.empty:
            frames.append(result.frame)
        else:
            notes.append(f"{listing_id}: {result.detail}")
    if not frames:
        return VendorLoadResult(_empty(), "unavailable", "; ".join(notes) or "no vendor rows collected", "local_mart")
    out = pd.concat(frames, ignore_index=True)
    path = Path(output_path) if output_path is not None else default_local_mart_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    detail = f"wrote {len(out)} vendor rows to {path}"
    if notes:
        detail = f"{detail}; skipped {len(notes)} listings"
    return VendorLoadResult(out, "available", detail, "local_mart")


def vendor_source_caption(result: VendorLoadResult | pd.DataFrame) -> str:
    if isinstance(result, VendorLoadResult):
        frame = result.frame
        if result.status != "available" or frame is None or frame.empty:
            prefix = "Not official issuer disclosure. "
            return prefix + (result.detail or "Vendor financials overlay unavailable.")
    else:
        frame = result
        if frame is None or frame.empty:
            return (
                "Not official issuer disclosure. No vendor financials overlay is available; "
                "the sibling financial-data yfinance/akshare store had no matching rows."
            )
    providers = sorted({str(value) for value in frame["provider"].dropna().unique()})
    paths = sorted({Path(str(value)).name for value in frame["source_path"].dropna().unique()})
    retrieved = pd.to_datetime(frame["retrieved_at_utc"], errors="coerce", utc=True).dropna()
    as_of = retrieved.max().strftime("%Y-%m-%d") if not retrieved.empty else "date unavailable"
    provider_text = " and ".join(providers) if providers else "vendor"
    source_kind = result.source_kind if isinstance(result, VendorLoadResult) else "vendor store"
    return (
        f"Not official issuer disclosure. {provider_text} observations from the "
        f"sibling financial-data repository via {source_kind}, fetched {as_of}. "
        f"Files: {', '.join(paths) or 'unavailable'}. "
        "No announcement timestamp, no IFRS/Non-IFRS split, no segment mix. "
        "AkShare interim rows are year-to-date cumulatives. "
        "Currencies are source-reported and not FX-aligned. "
        "Do not treat as PIT official actuals."
    )
