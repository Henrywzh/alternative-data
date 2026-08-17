"""Run a small, read-only HKEX event study with yfinance bars.

This is an experiment, not a production market-data pipeline.  It reads the
canonical announcement events from the sibling ``financial-data`` DuckDB,
downloads only yfinance 5-minute and 1-hour bars, and writes compact CSV/JSON
outputs under ``outputs/``.  It never writes to the financial-data repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

import pandas as pd


HK_TZ = "Asia/Hong_Kong"
BENCHMARK = "^HSI"
HORIZONS = {"5m": 1, "30m": 6, "1h": 12}
MAX_OVERNIGHT_ENTRY_DAYS = 4
EVIDENCE_CONTRACT_VERSION = "hkex_event_study_evidence.v1"
MIN_SIGNAL_CLUSTERS = 30
MIN_SIGNAL_DATES = 10
MIN_SIGNAL_T_STAT = 1.96
MIN_MEDIAN_MEAN_RATIO = 0.4
EVENT_TYPE_PRIORITY = {
    "INTERIM_RESULTS": 1,
    "FINAL_RESULTS": 1,
    "ANNUAL_RESULTS": 1,
    "INSIDE_INFORMATION_EARNINGS": 1,
    "EARNINGS_WARNING": 2,
    "INSIDE_INFORMATION": 3,
    "TRADING_UPDATE": 4,
    "BUSINESS_UPDATE": 4,
    "BOARD_MEETING_DATE": 5,
}
EXPLORATORY_CANDIDATE_FAMILIES = frozenset(
    {
        "business_update",
        "capital_action",
        "director_change",
        "dividend",
        "governance",
        "inside_information",
        "results",
        "trading_update",
    }
)
POSITIVE_TITLE = re.compile(
    r"(?:\bpositive profit alert\b|estimated profit increase|"
    r"increase in operating results|estimated increase in the profit|"
    r"profit pre[- ]increase|profit increase|盈喜|业绩预增|净利润增加|扭亏为盈)",
    re.IGNORECASE,
)
NEGATIVE_TITLE = re.compile(
    r"(?:\bnegative profit alert\b|\bprofit warning\b|"
    r"estimated profit decrease|decrease in operating results|"
    r"profit pre[- ]decrease|estimated loss|profit decline|"
    r"盈警|业绩预亏|亏损扩大|净利润减少)",
    re.IGNORECASE,
)


def derive_primary_event_type(event_types: Iterable[object]) -> str:
    values = [str(value) for value in event_types if pd.notna(value)]
    if not values:
        return "UNKNOWN"
    return min(values, key=lambda value: EVENT_TYPE_PRIORITY.get(value, 99))


def derive_impact_direction(title_en: object, title_zh: object) -> str:
    return _impact_direction_match(title_en, title_zh)[0]


def resolve_impact_direction(raw_direction: object, derived_direction: object) -> tuple[str, str]:
    """Resolve a dashboard display direction without hiding parser conflicts."""
    raw = "unknown" if raw_direction is None or pd.isna(raw_direction) else str(raw_direction).lower()
    derived = (
        "neutral_unknown"
        if derived_direction is None or pd.isna(derived_direction)
        else str(derived_direction).lower()
    )
    valid = {"positive", "negative", "mixed"}
    if raw in valid:
        if raw == derived:
            return raw, "raw_and_title_agree"
        if derived in valid:
            return "review_required", "raw_derived_conflict"
        return raw, "raw_only_title_neutral"
    if derived in valid:
        return derived, "title_only"
    return "unknown", "insufficient_direction_evidence"


def reconcile_impact_direction(
    raw_direction: object,
    derived_direction: object,
    primary_event_type: object,
) -> tuple[str, str]:
    """Apply one narrow, auditable correction to a generic earnings category.

    HKEX's broad ``EARNINGS_WARNING`` category can contain both positive and
    negative profit pre-announcements.  Preserve the source parser label, but
    allow an unambiguous title direction to override a conflicting generic
    category label.  All other conflicts remain review-only.
    """
    raw = "unknown" if raw_direction is None or pd.isna(raw_direction) else str(raw_direction).lower()
    derived = (
        "neutral_unknown"
        if derived_direction is None or pd.isna(derived_direction)
        else str(derived_direction).lower()
    )
    event_type = "" if primary_event_type is None or pd.isna(primary_event_type) else str(primary_event_type)
    if (
        event_type == "EARNINGS_WARNING"
        and raw in {"positive", "negative", "mixed"}
        and derived in {"positive", "negative"}
        and raw != derived
    ):
        return derived, "category_generic_title_override"
    return raw, "source_parser_raw"


def _impact_direction_match(title_en: object, title_zh: object) -> tuple[str, str]:
    text = " ".join(
        "" if value is None or pd.isna(value) else str(value)
        for value in (title_en, title_zh)
    )
    positive = bool(POSITIVE_TITLE.search(text))
    negative = bool(NEGATIVE_TITLE.search(text))
    if positive and negative:
        return "mixed", "title_conflicting_high_precision_matches"
    if positive:
        return "positive", "title_high_precision_positive_match"
    if negative:
        return "negative", "title_high_precision_negative_match"
    return "neutral_unknown", "no_high_precision_title_match"


def derive_evidence_fields(events: pd.DataFrame) -> pd.DataFrame:
    events = events.copy()
    for column, default in {
        "content_hash": None,
        "source_url": None,
        "title_en": "",
        "title_zh": "",
        "availability_basis": "unknown",
        "impact_direction": "unknown",
        "impact_confidence": "unknown",
        "review_status": "unknown",
        "is_inferred": False,
        "parser_version": None,
        "source": None,
        "fetched_at": None,
        "effective_at": None,
        "announcement_at": events["available_at"],
    }.items():
        if column not in events:
            events[column] = default
    events["document_key"] = events["ticker"].astype(str) + "|" + events["content_hash"].fillna(
        events["source_url"]
    ).fillna(events["event_id"])
    primary_by_document = events.groupby("document_key")["event_type"].transform(
        lambda values: derive_primary_event_type(values)
    )
    events["primary_event_type"] = primary_by_document
    events["derived_impact_direction"] = [
        derive_impact_direction(title_en, title_zh)
        for title_en, title_zh in zip(
            events["title_en"], events["title_zh"], strict=False
        )
    ]
    events["impact_direction_basis"] = [
        _impact_direction_match(title_en, title_zh)[1]
        for title_en, title_zh in zip(
            events["title_en"], events["title_zh"], strict=False
        )
    ]
    reconciled = [
        reconcile_impact_direction(raw, derived, primary_type)
        for raw, derived, primary_type in zip(
            events["impact_direction"],
            events["derived_impact_direction"],
            events["primary_event_type"],
            strict=False,
        )
    ]
    events["impact_direction_reconciled"] = [value[0] for value in reconciled]
    events["impact_direction_reconciliation_basis"] = [value[1] for value in reconciled]
    resolved: list[tuple[str, str]] = []
    for reconciled_direction, reconciliation_basis, derived in zip(
        events["impact_direction_reconciled"],
        events["impact_direction_reconciliation_basis"],
        events["derived_impact_direction"],
        strict=False,
    ):
        direction, resolution_basis = resolve_impact_direction(reconciled_direction, derived)
        if (
            reconciliation_basis != "source_parser_raw"
            and direction in {"positive", "negative"}
            and direction == derived
        ):
            resolution_basis = reconciliation_basis
        resolved.append((direction, resolution_basis))
    events["resolved_impact_direction"] = [value[0] for value in resolved]
    events["resolved_impact_direction_basis"] = [value[1] for value in resolved]
    events["display_title"] = [
        next(
            (
                str(value).strip()
                for value in (title_zh, title_en)
                if value is not None and not pd.isna(value) and str(value).strip()
            ),
            "",
        )
        for title_zh, title_en in zip(events["title_zh"], events["title_en"], strict=False)
    ]
    for column in ("announcement_at", "available_at"):
        events[column] = pd.to_datetime(events[column], errors="coerce", utc=True)
    events["source_delay_minutes"] = (
        events["available_at"] - events["announcement_at"]
    ).dt.total_seconds() / 60.0
    events["is_document_representative"] = ~events.duplicated("document_key")
    return events


def default_financial_db() -> Path:
    return Path(__file__).resolve().parents[2] / "financial-data" / "data" / "databases" / "hk_financials.duckdb"


def load_archive_audit(snapshot_root: Path) -> dict[str, object] | None:
    """Load only an archive audit tied to the current manifest fingerprint."""
    audit_path = snapshot_root / "archive_audit.json"
    if not audit_path.exists():
        return None
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid archive audit JSON: {audit_path}") from exc
    manifest_path = snapshot_root / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"archive audit exists but manifest is missing: {manifest_path}")
    current_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if audit.get("manifest_sha256") != current_hash:
        raise ValueError(
            "archive audit is stale for the current manifest; rerun "
            "capture_yfinance_intraday.py --audit"
        )
    return audit


def load_events(
    db_path: Path,
    *,
    top_tickers: int,
    candidate_inventory: Path | None = None,
    candidate_tickers: set[str] | None = None,
) -> pd.DataFrame:
    import duckdb

    with duckdb.connect(str(db_path), read_only=True) as connection:
        events = connection.execute(
            """
            SELECT event_id, ticker, security_id, event_type, event_family,
                   source_category, title_en, title_zh, announcement_at,
                   collected_at, available_at, availability_basis,
                   effective_at, impact_direction, impact_confidence,
                   structured_payload_json, is_inferred, review_status,
                   parser_version, source, fetched_at, source_url, content_hash
            FROM hkex_announcement_events
            WHERE announcement_at IS NOT NULL
              AND available_at IS NOT NULL
            ORDER BY available_at, ticker, event_id
            """
        ).fetchdf()
    if events.empty:
        raise ValueError("hkex_announcement_events is empty")
    if candidate_inventory is not None:
        candidates = load_candidate_events(
            candidate_inventory,
            allowed_tickers=candidate_tickers,
        )
        if not candidates.empty:
            events = pd.concat([events, candidates], ignore_index=True, sort=False)
    if top_tickers > 0:
        counts = events.groupby("ticker").size().sort_values(ascending=False)
        selected = counts.head(top_tickers).index
        events = events.loc[events["ticker"].isin(selected)].copy()
    for column in ("announcement_at", "collected_at", "available_at"):
        events[column] = pd.to_datetime(events[column], errors="coerce", utc=True)
    events = events.dropna(subset=["available_at"]).reset_index(drop=True)
    return derive_evidence_fields(events)


def load_candidate_events(
    inventory_path: Path,
    *,
    allowed_tickers: set[str] | None = None,
) -> pd.DataFrame:
    """Load only PIT-complete, non-composite named filing families.

    This is an explicitly exploratory sidecar input.  It never writes back to
    the canonical DuckDB and excludes ``other``/``transaction`` families,
    composite categories, missing-PIT rows, and already-canonical filings.
    """
    inventory = pd.read_csv(inventory_path)
    required = {
        "filing_id", "ticker", "announcement_at", "available_at", "availability_basis",
        "title_en", "title_zh", "category", "document_url", "candidate_family",
        "category_is_composite", "candidate_status", "event_study_eligible",
    }
    missing = sorted(required.difference(inventory.columns))
    if missing:
        raise ValueError(f"candidate inventory missing required columns: {missing}")
    candidates = inventory.loc[
        inventory["candidate_status"].eq("discovery_candidate")
        & inventory["event_study_eligible"].astype(str).str.lower().isin({"true", "1", "yes"})
        & ~inventory["category_is_composite"].astype(bool)
        & inventory["candidate_family"].isin(EXPLORATORY_CANDIDATE_FAMILIES)
        & inventory["available_at"].notna()
    ].copy()
    if allowed_tickers is not None:
        candidates = candidates.loc[candidates["ticker"].isin(allowed_tickers)].copy()
    if candidates.empty:
        return pd.DataFrame()
    candidates["event_id"] = "filing:" + candidates["filing_id"].astype(str)
    candidates["security_id"] = None
    candidates["event_type"] = candidates["candidate_family"].astype(str).str.upper()
    candidates["event_family"] = candidates["candidate_family"]
    candidates["source_category"] = candidates["category"]
    candidates["effective_at"] = None
    candidates["impact_direction"] = "unknown"
    candidates["impact_confidence"] = "unknown"
    candidates["structured_payload_json"] = None
    candidates["is_inferred"] = False
    candidates["review_status"] = "candidate_inventory"
    candidates["parser_version"] = "hkex-filing-candidate-v1"
    candidates["source"] = "hkex_filings_candidate"
    candidates["fetched_at"] = None
    candidates["content_hash"] = "filing:" + candidates["filing_id"].astype(str)
    candidates["announcement_at"] = pd.to_datetime(candidates["announcement_at"], errors="coerce", utc=True)
    candidates["available_at"] = pd.to_datetime(candidates["available_at"], errors="coerce", utc=True)
    return derive_evidence_fields(candidates)


def archive_manifest_symbols(snapshot_root: Path, interval: str) -> set[str]:
    """Return symbols present in any manifest-backed capture for an interval."""
    manifest_path = snapshot_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    symbols: set[str] = set()
    for capture in manifest.get("captures", []):
        info = capture.get("intervals", {}).get(interval, {})
        symbols.update(str(symbol) for symbol in info.get("symbols", []) or [])
        symbols.update(str(symbol) for symbol in (info.get("symbol_coverage", {}) or {}).keys())
    return symbols


def resolve_candidate_tickers(
    inventory_path: Path,
    base_tickers: set[str],
    snapshot_root: Path | None,
) -> set[str]:
    """Expand the canonical ticker set with all eligible candidate tickers.

    Interval availability is audited after loading bars so a candidate with a
    missing 5m or 1h file remains visible as an explicit market-data gap rather
    than disappearing from sample coverage.
    """
    resolved = set(base_tickers)
    candidates = load_candidate_events(inventory_path)
    if candidates.empty or snapshot_root is None:
        return resolved
    candidate_tickers = set(candidates["ticker"].astype(str))
    resolved.update(candidate_tickers)
    return resolved


def download_bars(tickers: Iterable[str], *, period: str, interval: str) -> pd.DataFrame:
    import yfinance as yf

    symbols = list(dict.fromkeys(tickers))
    return yf.download(
        symbols,
        period=period,
        interval=interval,
        auto_adjust=False,
        actions=False,
        group_by="ticker",
        multi_level_index=True,
        prepost=False,
        progress=False,
        threads=False,
        timeout=30,
    )


def load_archived_bars(
    snapshot_root: Path,
    *,
    interval: str,
    symbols: Iterable[str],
    require_all: bool = True,
    capture_id: str | None = None,
) -> pd.DataFrame:
    """Load normalized bars from the append-only yfinance archive.

    Archive mode is explicit and strict: all requested symbols must be present
    in the manifest-backed files.  This prevents a partial local archive from
    silently changing coverage or being mistaken for a complete backtest.
    """
    manifest_path = snapshot_root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"snapshot manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != "yfinance_snapshot_archive.v1":
        raise ValueError(f"unsupported snapshot manifest version: {manifest.get('version')}")
    files: list[Path] = []
    file_metadata: dict[Path, dict[str, object]] = {}
    captures = manifest.get("captures", [])
    if capture_id is not None:
        captures = [capture for capture in captures if capture.get("capture_id") == capture_id]
        if not captures:
            raise ValueError(f"capture_id not found in archive manifest: {capture_id}")
    for capture in captures:
        interval_info = capture.get("intervals", {}).get(interval)
        if not interval_info:
            continue
        path = snapshot_root / interval_info["path"]
        if path.exists():
            files.append(path)
            file_metadata[path] = interval_info
    if not files:
        raise FileNotFoundError(f"no archived {interval} bars found under {snapshot_root}")
    frames: list[pd.DataFrame] = []
    for path in files:
        metadata = file_metadata[path]
        expected_hash = metadata.get("sha256")
        if expected_hash:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != expected_hash:
                raise ValueError(f"archive sha256 mismatch: {path}")
        frame = pd.read_parquet(path)
        expected_rows = metadata.get("rows")
        if expected_rows is not None and int(expected_rows) != len(frame):
            raise ValueError(f"archive row-count mismatch: {path}")
        frames.append(frame)
    archived = pd.concat(frames, ignore_index=True)
    required = {"ticker", "interval", "timestamp_utc", "open", "close", "captured_at"}
    missing = required.difference(archived.columns)
    if missing:
        raise ValueError(f"archived bars missing columns: {sorted(missing)}")
    requested = list(dict.fromkeys(str(symbol) for symbol in symbols))
    archived["timestamp_utc"] = pd.to_datetime(archived["timestamp_utc"], errors="coerce", utc=True)
    archived["captured_at"] = pd.to_datetime(archived["captured_at"], errors="coerce", utc=True)
    archived = archived.loc[archived["ticker"].isin(requested) & archived["interval"].eq(interval)].copy()
    available = set(archived["ticker"].dropna().astype(str))
    missing_symbols = sorted(set(requested).difference(available))
    if missing_symbols and require_all:
        raise ValueError(f"archive missing requested symbols for {interval}: {missing_symbols}")
    archived = archived.sort_values(["ticker", "timestamp_utc", "captured_at"])
    key_columns = ["ticker", "interval", "timestamp_utc"]
    duplicate_rows = int(archived.duplicated(key_columns, keep=False).sum())
    value_columns = [column for column in ("open", "high", "low", "close", "adj_close", "volume") if column in archived]
    conflict_keys = int(
        archived.groupby(key_columns, dropna=False)[value_columns]
        .nunique(dropna=False)
        .max(axis=1)
        .gt(1)
        .sum()
    ) if value_columns else 0
    archived = archived.drop_duplicates(key_columns, keep="last")
    fields = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "adj_close": "Adj Close", "volume": "Volume"}
    pieces: list[pd.DataFrame] = []
    for ticker in requested:
        group = archived.loc[archived["ticker"].eq(ticker)].set_index("timestamp_utc")
        columns: dict[tuple[str, str], pd.Series] = {}
        for source, target in fields.items():
            if source in group:
                columns[(ticker, target)] = pd.to_numeric(group[source], errors="coerce")
        if columns:
            piece = pd.DataFrame(columns)
            piece.columns = pd.MultiIndex.from_tuples(piece.columns)
            pieces.append(piece)
    if not pieces:
        return pd.DataFrame()
    result = pd.concat(pieces, axis=1).sort_index()
    result.attrs["archive_file_count"] = len(files)
    result.attrs["archive_duplicate_rows"] = duplicate_rows
    result.attrs["archive_conflict_keys"] = conflict_keys
    result.attrs["archive_capture_id"] = capture_id
    result.attrs["archive_symbols"] = sorted(available)
    result.attrs["archive_missing_symbols"] = missing_symbols
    result.attrs["archive_symbol_earliest_utc"] = {
        ticker: group["timestamp_utc"].min().isoformat()
        for ticker, group in archived.groupby("ticker", sort=True)
    }
    result.attrs["archive_symbol_latest_utc"] = {
        ticker: group["timestamp_utc"].max().isoformat()
        for ticker, group in archived.groupby("ticker", sort=True)
    }
    return result


def load_canonical_daily_bars(
    tickers: Iterable[str],
    *,
    start_date: object = None,
    end_date: object = None,
    fallback_snapshot_root: Path | None = None,
) -> pd.DataFrame:
    """Load daily bars from the canonical financial-data DuckDB.

    Daily OHLCV is consolidated in the sibling repository
    (``financial-data`` ``market_data_bars``, 1,190k rows / 933 tickers /
    2016-01-04+).  This is the preferred daily input for the long-horizon
    event-study lane; the legacy local 1d snapshot archive is used only as an
    offline fallback when the DuckDB is missing.
    """
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - local env only
        raise RuntimeError("duckdb is required for canonical daily bars") from exc

    db_path = (
        Path(__file__).resolve().parents[1]
        / ".."
        / "financial-data"
        / "data"
        / "databases"
        / "hk_financials.duckdb"
    ).resolve()
    if db_path.exists():
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            clause = ""
            params: list[object] = []
            if tickers:
                clause = " WHERE ticker IN (SELECT UNNEST(?)::VARCHAR)"
                params.append(sorted(set(tickers)))
            if start_date is not None:
                clause += " AND " if clause else "WHERE "
                clause += "timestamp_utc >= ?"
                params.append(pd.Timestamp(start_date).date())
            if end_date is not None:
                clause += " AND " if clause else "WHERE "
                clause += "timestamp_utc <= ?"
                params.append(pd.Timestamp(end_date).date())
            frame = con.execute(
                "SELECT ticker, interval, timestamp_utc, open, high, low, "
                "close, adj_close, volume "
                f"FROM market_data_bars{clause} ORDER BY ticker, timestamp_utc",
                params,
            ).df()
        finally:
            con.close()
        if not frame.empty:
            frame["timestamp_utc"] = pd.to_datetime(
                frame["timestamp_utc"], errors="coerce"
            ).dt.tz_localize("UTC")
            return frame
    if fallback_snapshot_root is not None:
        return load_archived_bars(
            fallback_snapshot_root,
            interval="1d",
            symbols=list(tickers),
            require_all=False,
        )
    raise FileNotFoundError(
        "canonical daily bars unavailable: DuckDB missing and no fallback "
        "snapshot root supplied"
    )


def mark_pending_market_cutoff_events(
    result: pd.DataFrame,
    reference_latest_bar_utc: object | None,
) -> tuple[pd.DataFrame, int]:
    """Label missing events whose PIT time is newer than the archive cutoff."""
    output = result.copy()
    if output.empty or reference_latest_bar_utc is None:
        return output, 0
    cutoff = pd.to_datetime(reference_latest_bar_utc, errors="coerce", utc=True)
    if pd.isna(cutoff):
        return output, 0
    available = pd.to_datetime(output["available_at"], errors="coerce", utc=True)
    pending = output["market_data_status"].eq("missing") & available.gt(cutoff)
    output.loc[pending, "data_gap_reason"] = "awaiting_next_market_cutoff"
    return output, int(pending.sum())


def merge_bar_frames(archive: pd.DataFrame, live: pd.DataFrame) -> pd.DataFrame:
    """Merge wide bar frames without dropping symbols or timestamps.

    Existing archive values win on overlapping `(timestamp, ticker, field)`
    cells; live values only fill missing archive cells or new timestamps.
    """
    if archive.empty:
        return live.copy()
    if live.empty:
        return archive.copy()
    index = archive.index.union(live.index)
    columns = archive.columns.union(live.columns)
    archived = archive.reindex(index=index, columns=columns)
    live = live.reindex(index=index, columns=columns)
    return archived.combine_first(live).sort_index()


def _last_bar_at(frame: pd.DataFrame, ticker: str) -> pd.Timestamp | None:
    if frame.empty or not isinstance(frame.columns, pd.MultiIndex):
        return None
    if ticker not in frame.columns.get_level_values(0):
        return None
    series = _close_or_open(frame, ticker, "Open")
    return None if series.empty else series.index.max()


def _needs_live_fallback(
    events: pd.DataFrame,
    symbols: Iterable[str],
    bars_5m: pd.DataFrame,
    bars_1h: pd.DataFrame,
) -> set[str]:
    """Identify symbols whose archive cannot safely cover the current events."""
    event_max = events.groupby("ticker")["available_at"].max().to_dict()
    global_event_max = pd.Timestamp(events["available_at"].max())
    required_horizon = pd.Timedelta(hours=2)
    missing: set[str] = set()
    for ticker in symbols:
        required = event_max.get(ticker, global_event_max)
        if any(
            _last_bar_at(frame, ticker) is None
            or required >= _last_bar_at(frame, ticker) - required_horizon
            for frame in (bars_5m, bars_1h)
        ):
            missing.add(ticker)
    return missing


def _close_or_open(frame: pd.DataFrame, ticker: str, field: str) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype="float64")
    if isinstance(frame.columns, pd.MultiIndex):
        if ticker not in frame.columns.get_level_values(0):
            return pd.Series(dtype="float64")
        candidates = ((ticker, field), (field, ticker))
        column = next((candidate for candidate in candidates if candidate in frame.columns), None)
        if column is None:
            return pd.Series(dtype="float64")
        series = frame[column]
    else:
        if field not in frame.columns:
            return pd.Series(dtype="float64")
        series = frame[field]
    series = pd.to_numeric(series, errors="coerce").dropna()
    index = pd.to_datetime(series.index, errors="coerce", utc=True)
    series.index = index
    return series[~series.index.isna()].groupby(level=0).last().sort_index()


def _hkt_time(timestamp: pd.Timestamp) -> pd.Timestamp:
    return timestamp.tz_convert(HK_TZ)


def classify_session(timestamp: pd.Timestamp) -> str:
    local = _hkt_time(timestamp)
    time = local.time()
    if time < pd.Timestamp("09:30").time():
        return "OVERNIGHT_PRE"
    if time < pd.Timestamp("12:00").time():
        return "INTRADAY"
    if time < pd.Timestamp("13:00").time():
        return "LUNCH_BREAK"
    # Treat the final 5-minute interval as post-close for an event timestamp:
    # a 15:55 bar has already opened by 15:56, so the next actionable price is
    # the following session's open.
    if time < pd.Timestamp("15:55").time():
        return "INTRADAY"
    return "OVERNIGHT_POST"


def _eligible_bar_index(
    bars: pd.Series,
    available_at: pd.Timestamp,
) -> int | None:
    """Return the first bar that starts after information is usable.

    yfinance bars are labelled by bar start.  For an event during a bar, use
    the next bar's open.  For lunch/overnight events, explicitly require the
    next calendar trading session rather than accidentally selecting the
    same-day close or a bar labelled at 16:00.
    """
    if bars.empty:
        return None
    local = _hkt_time(available_at)
    candidates = bars.index
    if local.time() >= pd.Timestamp("16:00").time():
        candidates = candidates[candidates.tz_convert(HK_TZ).date > local.date()]
    elif local.time() < pd.Timestamp("09:30").time():
        candidates = candidates[candidates.tz_convert(HK_TZ).date >= local.date()]
    else:
        # An event timestamp equal to a bar label is not allowed to consume
        # that bar's opening price: the information is only usable after the
        # bar has started.  Use the next bar to stay conservative at 09:30,
        # 13:00, and other exact bar boundaries.
        candidates = candidates[candidates > available_at]
    if len(candidates) == 0:
        return None
    first = candidates[0]
    return int(bars.index.get_indexer([first])[0])


def _bar_table(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    opens = _close_or_open(frame, ticker, "Open")
    closes = _close_or_open(frame, ticker, "Close")
    if opens.empty or closes.empty:
        return pd.DataFrame(columns=["open", "close"])
    volumes = _close_or_open(frame, ticker, "Volume")
    columns = [opens.rename("open"), closes.rename("close")]
    if not volumes.empty:
        columns.append(volumes.rename("volume"))
    table = pd.concat(columns, axis=1).dropna(subset=["open", "close"])
    if "volume" not in table:
        table["volume"] = pd.NA
    local = table.index.tz_convert(HK_TZ)
    clock = local.time
    regular = (
        ((clock >= pd.Timestamp("09:30").time()) & (clock < pd.Timestamp("12:00").time()))
        | ((clock >= pd.Timestamp("13:00").time()) & (clock < pd.Timestamp("16:00").time()))
    )
    return table.loc[regular].sort_index()


def _price_at_position(table: pd.DataFrame, position: int, offset: int, column: str = "open") -> float | None:
    target = position + offset
    if target < 0 or target >= len(table):
        return None
    value = table.iloc[target][column]
    return None if pd.isna(value) else float(value)


def _return(table: pd.DataFrame, position: int, bars_forward: int) -> float | None:
    entry = _price_at_position(table, position, 0, "open")
    exit_ = _price_at_position(table, position, bars_forward, "open")
    if entry in (None, 0) or exit_ is None:
        return None
    return exit_ / entry - 1.0


def _bar_hole_reason(
    table: pd.DataFrame,
    position: int,
    bars_forward: int,
    interval_minutes: int,
) -> str | None:
    """Detect an unexpected same-session timestamp gap inside a return window.

    Cross-session jumps and the HKEX lunch break are expected.  An unexpected
    same-session jump means a positional offset would silently extend the
    holding period, so callers should treat that horizon as missing.
    """
    end = position + bars_forward
    if position < 0 or end >= len(table):
        return None
    index = table.index[position : end + 1].tz_convert(HK_TZ)
    for current, following in zip(index[:-1], index[1:], strict=False):
        if current.date() != following.date():
            continue
        delta_minutes = int((following - current).total_seconds() // 60)
        if delta_minutes == interval_minutes:
            continue
        expected_last_morning = pd.Timestamp("12:00") - pd.Timedelta(
            minutes=interval_minutes / 2
        )
        is_lunch_transition = (
            current.time() == expected_last_morning.time()
            and following.time() >= pd.Timestamp("13:00").time()
        )
        if not is_lunch_transition:
            return (
                f"unexpected {delta_minutes}m gap between "
                f"{current.isoformat()} and {following.isoformat()}"
            )
    return None


def _previous_close(table: pd.DataFrame, position: int) -> float | None:
    if position <= 0:
        return None
    value = table.iloc[position - 1]["close"]
    return None if pd.isna(value) else float(value)


def _event_eligible_position(table: pd.DataFrame, available_at: pd.Timestamp) -> int | None:
    """Find a strictly-later bar that is in the same or next valid HKEX session."""
    if table.empty:
        return None
    position = _eligible_bar_index(table["open"], available_at)
    if position is None:
        return None
    candidate_local = table.index[position].tz_convert(HK_TZ)
    available_local = available_at.tz_convert(HK_TZ)
    calendar_gap = (candidate_local.date() - available_local.date()).days
    session = classify_session(available_at)
    same_session = session in {"INTRADAY", "LUNCH_BREAK"} and calendar_gap == 0
    next_session = (
        (session == "OVERNIGHT_PRE" and 0 <= calendar_gap <= MAX_OVERNIGHT_ENTRY_DAYS)
        or (session == "OVERNIGHT_POST" and 0 < calendar_gap <= MAX_OVERNIGHT_ENTRY_DAYS)
    )
    return position if same_session or next_session else None


def calculate_event_returns(
    events: pd.DataFrame,
    bars_5m: pd.DataFrame,
    bars_1h: pd.DataFrame,
) -> pd.DataFrame:
    events = events.copy()
    if "primary_event_type" not in events:
        events = derive_evidence_fields(events)
    event_rows: list[dict[str, object]] = []
    bar_cache_5m = {ticker: _bar_table(bars_5m, ticker) for ticker in events["ticker"].unique()}
    bar_cache_1h = {ticker: _bar_table(bars_1h, ticker) for ticker in events["ticker"].unique()}
    benchmark_5m = _bar_table(bars_5m, BENCHMARK)
    benchmark_1h = _bar_table(bars_1h, BENCHMARK)

    for row in events.to_dict(orient="records"):
        ticker = str(row["ticker"])
        available_at = pd.Timestamp(row["available_at"])
        table_5m = bar_cache_5m.get(ticker, pd.DataFrame())
        table_1h = bar_cache_1h.get(ticker, pd.DataFrame())
        position_5m = _eligible_bar_index(table_5m["open"], available_at)
        entry_time = None
        session = classify_session(available_at)
        market_data_status = "missing"
        data_gap_reason = None
        if position_5m is not None:
            candidate_entry_time = table_5m.index[position_5m]
            candidate_local = candidate_entry_time.tz_convert(HK_TZ)
            available_local = available_at.tz_convert(HK_TZ)
            calendar_gap = (candidate_local.date() - available_local.date()).days
            same_session = session in {"INTRADAY", "LUNCH_BREAK"} and calendar_gap == 0
            next_session = (
                (session == "OVERNIGHT_PRE" and 0 <= calendar_gap <= MAX_OVERNIGHT_ENTRY_DAYS)
                or (session == "OVERNIGHT_POST" and 0 < calendar_gap <= MAX_OVERNIGHT_ENTRY_DAYS)
            )
            if same_session or next_session:
                entry_time = candidate_entry_time
                market_data_status = "covered"
            else:
                data_gap_reason = (
                    f"first eligible bar is {candidate_local.date().isoformat()} "
                    f"for event date {available_local.date().isoformat()}"
                )
                position_5m = None
        if position_5m is None and data_gap_reason is None:
            data_gap_reason = "no eligible 5m bar in downloaded window"
        row_out = dict(row)
        row_out.update(
            {
                "available_at_hkt": available_at.tz_convert(HK_TZ).isoformat(),
                "session": session,
                "market_data_status": market_data_status,
                "data_gap_reason": data_gap_reason,
                "entry_bar_at": entry_time,
                "entry_bar_at_hkt": None if entry_time is None else entry_time.tz_convert(HK_TZ).isoformat(),
                "cluster_key": None if entry_time is None else f"{ticker}|{entry_time.isoformat()}",
                "gap_return": None,
                "opening_gap_benchmark_return": None,
                "opening_gap_abnormal_return": None,
                "zero_volume_bars_1h": None,
                "volume_observation_bars_1h": None,
                "zero_volume_ratio_1h": None,
                "native_1h_entry_bar_at": None,
                "native_1h_return": None,
                "native_1h_abnormal_return": None,
                "native_1h_status": "missing",
                "native_1h_bar_hole_reason": None,
                "bar_hole_horizons": [],
            }
        )
        benchmark_position_5m = -1
        if position_5m is not None:
            entry_at = table_5m.index[position_5m]
            benchmark_position_5m = benchmark_5m.index.get_indexer([entry_at])[0]
            if session != "INTRADAY":
                previous = _previous_close(table_5m, position_5m)
                opening = _price_at_position(table_5m, position_5m, 0, "open")
                row_out["gap_return"] = (
                    None if previous in (None, 0) or opening is None else opening / previous - 1.0
                )
                if benchmark_position_5m >= 0:
                    benchmark_previous = _previous_close(benchmark_5m, benchmark_position_5m)
                    benchmark_opening = _price_at_position(
                        benchmark_5m, benchmark_position_5m, 0, "open"
                    )
                    row_out["opening_gap_benchmark_return"] = (
                        None
                        if benchmark_previous in (None, 0) or benchmark_opening is None
                        else benchmark_opening / benchmark_previous - 1.0
                    )
                if (
                    row_out["gap_return"] is not None
                    and row_out["opening_gap_benchmark_return"] is not None
                ):
                    row_out["opening_gap_abnormal_return"] = (
                        row_out["gap_return"] - row_out["opening_gap_benchmark_return"]
                    )
        if position_5m is not None and "volume" in table_5m:
            volume_window = pd.to_numeric(
                table_5m.iloc[position_5m : position_5m + HORIZONS["1h"] + 1]["volume"],
                errors="coerce",
            ).dropna()
            if not volume_window.empty:
                row_out["zero_volume_bars_1h"] = int(volume_window.eq(0).sum())
                row_out["volume_observation_bars_1h"] = int(volume_window.size)
                row_out["zero_volume_ratio_1h"] = float(volume_window.eq(0).mean())
        for label, offset in HORIZONS.items():
            # Use 5m bars for every active-trading horizon.  This makes 1h
            # mean 12 five-minute bars, not 12 one-hour bars.
            stock_table = table_5m
            benchmark_table = benchmark_5m
            position = position_5m
            if position is None:
                stock_return = None
                benchmark_return = None
            else:
                stock_hole = _bar_hole_reason(stock_table, position, offset, 5)
                stock_return = None if stock_hole else _return(stock_table, position, offset)
                entry_at = stock_table.index[position]
                benchmark_position = benchmark_position_5m
                benchmark_hole = (
                    None
                    if benchmark_position < 0
                    else _bar_hole_reason(benchmark_table, benchmark_position, offset, 5)
                )
                if stock_hole or benchmark_hole:
                    row_out["bar_hole_horizons"].append(label)
                benchmark_return = (
                    None
                    if benchmark_position < 0 or benchmark_hole
                    else _return(benchmark_table, benchmark_position, offset)
                )
            row_out[f"{label}_return"] = stock_return
            row_out[f"{label}_abnormal_return"] = (
                None
                if stock_return is None or benchmark_return is None
                else stock_return - benchmark_return
            )
            row_out[f"{label}_benchmark_drift_return"] = benchmark_return
            # Explicit aliases make the dashboard semantics unambiguous:
            # these are post-entry open-to-open drifts, not gap-inclusive
            # event returns.  Keep the shorter legacy names for compatibility.
            row_out[f"{label}_drift_return"] = stock_return
            row_out[f"{label}_abnormal_drift_return"] = row_out[f"{label}_abnormal_return"]
            stock_gap_component = (
                0.0 if session == "INTRADAY" else row_out["gap_return"]
            )
            benchmark_gap_component = (
                0.0
                if session == "INTRADAY"
                else row_out["opening_gap_benchmark_return"]
            )
            row_out[f"total_{label}_return"] = (
                None
                if stock_gap_component is None or stock_return is None
                else (1.0 + stock_gap_component) * (1.0 + stock_return) - 1.0
            )
            if (
                stock_gap_component is not None
                and benchmark_gap_component is not None
                and stock_return is not None
                and benchmark_return is not None
            ):
                benchmark_total = (1.0 + benchmark_gap_component) * (1.0 + benchmark_return) - 1.0
                row_out[f"total_{label}_abnormal_return"] = (
                    row_out[f"total_{label}_return"] - benchmark_total
                )
            else:
                row_out[f"total_{label}_abnormal_return"] = None
            resolved_direction = row_out.get("resolved_impact_direction", "unknown")
            abnormal = row_out[f"{label}_abnormal_return"]
            total_abnormal = row_out[f"total_{label}_abnormal_return"]
            row_out[f"signed_{label}_abnormal_return"] = (
                abnormal
                if resolved_direction == "positive" and abnormal is not None
                else -abnormal
                if resolved_direction == "negative" and abnormal is not None
                else None
            )
            row_out[f"signed_total_{label}_abnormal_return"] = (
                total_abnormal
                if resolved_direction == "positive" and total_abnormal is not None
                else -total_abnormal
                if resolved_direction == "negative" and total_abnormal is not None
                else None
            )
        row_out["opening_gap_return"] = row_out["gap_return"]
        native_position = _event_eligible_position(table_1h, available_at)
        if native_position is not None:
            native_entry_at = table_1h.index[native_position]
            benchmark_native_position = benchmark_1h.index.get_indexer([native_entry_at])[0]
            native_stock_hole = _bar_hole_reason(table_1h, native_position, 1, 60)
            native_benchmark_hole = (
                None
                if benchmark_native_position < 0
                else _bar_hole_reason(benchmark_1h, benchmark_native_position, 1, 60)
            )
            native_stock_return = (
                None if native_stock_hole or native_benchmark_hole else _return(table_1h, native_position, 1)
            )
            native_benchmark_return = (
                None
                if benchmark_native_position < 0 or native_benchmark_hole
                else _return(benchmark_1h, benchmark_native_position, 1)
            )
            row_out["native_1h_entry_bar_at"] = native_entry_at
            row_out["native_1h_bar_hole_reason"] = native_stock_hole or native_benchmark_hole
            if native_stock_return is not None:
                row_out["native_1h_return"] = native_stock_return
                row_out["native_1h_abnormal_return"] = (
                    None
                    if native_benchmark_return is None
                    else native_stock_return - native_benchmark_return
                )
                row_out["native_1h_status"] = (
                    "covered" if native_benchmark_return is not None else "benchmark_missing"
                )
            elif native_stock_hole or native_benchmark_hole:
                row_out["native_1h_status"] = "bar_hole"
        row_out["bar_hole_horizons"] = ",".join(row_out["bar_hole_horizons"])
        event_rows.append(row_out)

    result = pd.DataFrame(event_rows)
    if result.empty:
        return result
    result["cluster_size"] = result.groupby("cluster_key", dropna=False)["event_id"].transform("size")
    actual_clusters = result.loc[result["cluster_key"].notna()].groupby("cluster_key", sort=False)
    cluster_document_counts = actual_clusters["document_key"].nunique()
    cluster_type_labels = actual_clusters["primary_event_type"].agg(
        lambda values: ",".join(sorted({str(value) for value in values if pd.notna(value)}))
    )
    result["cluster_document_count"] = (
        result["cluster_key"].map(cluster_document_counts).fillna(0).astype(int)
    )
    result["cluster_co_occurring_types"] = result["cluster_key"].map(cluster_type_labels)
    result["is_multi_document_cluster"] = result["cluster_document_count"].gt(1)
    result["is_pure_event_type"] = (
        result["cluster_key"].notna()
        & result["cluster_co_occurring_types"].notna()
        & ~result["cluster_co_occurring_types"].fillna("").astype("string").str.contains(",", regex=False)
    )
    result["is_cluster_representative"] = (
        result["cluster_key"].notna() & ~result.duplicated("cluster_key")
    )
    result["is_type_cluster_representative"] = (
        result["cluster_key"].notna()
        & ~result.duplicated(["cluster_key", "primary_event_type"])
    )
    return result


def summarize(result: pd.DataFrame) -> pd.DataFrame:
    if result.empty:
        return pd.DataFrame()
    representative = result.loc[result["is_type_cluster_representative"]].copy()
    rows: list[dict[str, object]] = []
    for event_type, group in representative.groupby("primary_event_type", dropna=False):
        row: dict[str, object] = {
            "primary_event_type": event_type,
            "event_clusters": int(len(group)),
            "document_rows": int(
                result.loc[result["primary_event_type"].eq(event_type), "document_key"].nunique()
            ),
            "event_rows": int(result["primary_event_type"].eq(event_type).sum()),
        }
        for label in ("5m", "30m", "1h"):
            values = pd.to_numeric(group[f"{label}_abnormal_return"], errors="coerce").dropna()
            row[f"{label}_coverage"] = int(values.size)
            row[f"{label}_mean_abnormal_return"] = None if values.empty else float(values.mean())
            row[f"{label}_median_abnormal_return"] = None if values.empty else float(values.median())
            row[f"{label}_positive_rate"] = None if values.empty else float((values > 0).mean())
        rows.append(row)
    return pd.DataFrame(rows).sort_values("event_clusters", ascending=False).reset_index(drop=True)


def _t_statistic(values: pd.Series) -> float | None:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if len(values) < 2:
        return None
    standard_error = values.std(ddof=1) / (len(values) ** 0.5)
    return None if standard_error == 0 else float(values.mean() / standard_error)


def _numeric_summary(values: pd.Series) -> dict[str, float | int | None]:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return {"count": 0, "mean": None, "median": None, "p90": None, "max_abs": None}
    return {
        "count": int(values.size),
        "mean": float(values.mean()),
        "median": float(values.median()),
        "p90": float(values.quantile(0.90)),
        "max_abs": float(values.abs().max()),
    }


def _direction_column(frame: pd.DataFrame) -> str:
    """Prefer the conservative dashboard direction, with legacy fallback."""
    return "resolved_impact_direction" if "resolved_impact_direction" in frame else "derived_impact_direction"


def _directional_values(
    group: pd.DataFrame,
    value_column: str,
    direction_column: str | None = None,
) -> pd.Series:
    direction_column = direction_column or _direction_column(group)
    values = pd.to_numeric(group[value_column], errors="coerce")
    directions = group[direction_column].fillna("unknown").astype(str).str.lower()
    valid = values.notna() & directions.isin({"positive", "negative"})
    signed = values.loc[valid].copy()
    signed.loc[directions.loc[valid].eq("negative")] *= -1.0
    return signed


def robustness_summary(result: pd.DataFrame) -> pd.DataFrame:
    """Return compact sensitivity diagnostics for dashboard review.

    Rows are type-cluster representatives, so repeated documents sharing a
    market reaction are not treated as independent observations.  The 15/30
    bps deductions are scenario sensitivities, not observed bid-ask spreads.
    """
    if result.empty:
        return pd.DataFrame()
    representative = result.loc[
        result["is_type_cluster_representative"]
        & result["market_data_status"].eq("covered")
    ].copy()
    if representative.empty:
        return pd.DataFrame()
    if "availability_basis" not in representative:
        representative["availability_basis"] = "unknown"
    rows: list[dict[str, object]] = []
    direction_column = _direction_column(representative)
    group_columns = ["primary_event_type", direction_column]
    for (event_type, direction), group in representative.groupby(group_columns, dropna=False):
        hkt_dates = pd.to_datetime(group["available_at"], errors="coerce", utc=True).dt.tz_convert(HK_TZ).dt.date
        for label in ("5m", "30m", "1h"):
            values = pd.to_numeric(group[f"{label}_abnormal_return"], errors="coerce").dropna()
            if values.empty:
                continue
            total_values = pd.to_numeric(
                group[f"total_{label}_abnormal_return"], errors="coerce"
            ).dropna()
            directional_values = _directional_values(
                group, f"{label}_abnormal_return", direction_column
            )
            total_directional_values = _directional_values(
                group, f"total_{label}_abnormal_return", direction_column
            )
            lower, upper = values.quantile([0.01, 0.99])
            winsorized = values.clip(lower=lower, upper=upper)
            daily_means = values.groupby(hkt_dates.loc[values.index]).mean()
            rows.append(
                {
                    "primary_event_type": event_type,
                    "resolved_impact_direction": direction,
                    "horizon": label,
                    "n_type_clusters": int(values.size),
                    "n_announcement_dates": int(daily_means.size),
                    "observed_availability_rows": int(
                        group["availability_basis"].eq("observed_collection").sum()
                    ),
                    "proxy_availability_rows": int(
                        group["availability_basis"].eq("source_timestamp_proxy").sum()
                    ),
                    "pit_observed_share": float(
                        group["availability_basis"].eq("observed_collection").mean()
                    ),
                    "mean_abnormal_return": float(values.mean()),
                    "median_abnormal_return": float(values.median()),
                    "winsorized_1pct_mean": float(winsorized.mean()),
                    "mean_after_15bps_scenario": float(values.mean() - 0.0015),
                    "mean_after_30bps_scenario": float(values.mean() - 0.0030),
                    "event_level_t_stat": _t_statistic(values),
                    "announcement_date_cluster_t_stat": _t_statistic(daily_means),
                    "max_absolute_return": float(values.abs().max()),
                    "total_return_rows": int(total_values.size),
                    "mean_total_abnormal_return": (
                        None if total_values.empty else float(total_values.mean())
                    ),
                    "median_total_abnormal_return": (
                        None if total_values.empty else float(total_values.median())
                    ),
                    "directional_return_rows": int(directional_values.size),
                    "directional_win_rate": (
                        None
                        if directional_values.empty
                        else float((directional_values > 0).mean())
                    ),
                    "directional_mean_signed_abnormal_return": (
                        None if directional_values.empty else float(directional_values.mean())
                    ),
                    "total_directional_return_rows": int(total_directional_values.size),
                    "total_directional_win_rate": (
                        None
                        if total_directional_values.empty
                        else float((total_directional_values > 0).mean())
                    ),
                    "total_directional_mean_signed_abnormal_return": (
                        None
                        if total_directional_values.empty
                        else float(total_directional_values.mean())
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["horizon", "n_type_clusters", "primary_event_type", "resolved_impact_direction"],
        ascending=[True, False, True, True],
    ).reset_index(drop=True)


def stratified_event_summary(result: pd.DataFrame) -> pd.DataFrame:
    """Summarize returns by PIT basis, market status, and liquidity bucket."""
    columns = [
        "availability_basis", "market_data_status", "liquidity_bucket",
        "primary_event_type", "resolved_impact_direction", "horizon",
        "event_rows", "type_cluster_rows", "return_rows", "return_coverage_rate",
        "n_announcement_dates", "mean_abnormal_return", "median_abnormal_return",
        "positive_rate",
    ]
    if result.empty:
        return pd.DataFrame(columns=columns)
    enriched = result.copy()
    enriched["availability_basis"] = enriched["availability_basis"].fillna("unknown")
    enriched["liquidity_bucket"] = enriched.apply(
        lambda row: (
            "not_available"
            if row["market_data_status"] != "covered"
            else (
                "volume_missing"
                if pd.isna(row["zero_volume_ratio_1h"])
                else ("zero_volume" if row["zero_volume_ratio_1h"] > 0 else "zero_volume_free")
            )
        ),
        axis=1,
    )
    direction_column = _direction_column(enriched)
    group_columns = [
        "availability_basis", "market_data_status", "liquidity_bucket",
        "primary_event_type", direction_column,
    ]
    rows: list[dict[str, object]] = []
    for keys, group in enriched.groupby(group_columns, dropna=False):
        key_values = dict(zip(group_columns, keys, strict=True))
        if direction_column != "resolved_impact_direction":
            key_values["resolved_impact_direction"] = key_values.pop(direction_column)
        for label in HORIZONS:
            values = pd.to_numeric(group[f"{label}_abnormal_return"], errors="coerce").dropna()
            type_cluster_rows = int(group["is_type_cluster_representative"].sum())
            dates = pd.to_datetime(group.loc[values.index, "available_at"], errors="coerce", utc=True)
            rows.append(
                {
                    **key_values,
                    "horizon": label,
                    "event_rows": int(len(group)),
                    "type_cluster_rows": type_cluster_rows,
                    "return_rows": int(values.size),
                    "return_coverage_rate": None if type_cluster_rows == 0 else float(values.size / type_cluster_rows),
                    "n_announcement_dates": int(dates.dt.tz_convert(HK_TZ).dt.date.nunique()),
                    "mean_abnormal_return": None if values.empty else float(values.mean()),
                    "median_abnormal_return": None if values.empty else float(values.median()),
                    "positive_rate": None if values.empty else float((values > 0).mean()),
                }
            )
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["horizon", "availability_basis", "market_data_status", "primary_event_type", "liquidity_bucket", "resolved_impact_direction"]
    ).reset_index(drop=True)


def gap_drift_summary(result: pd.DataFrame) -> pd.DataFrame:
    """Keep opening-gap and post-entry drift effects separate by evidence grain."""
    columns = [
        "availability_basis", "primary_event_type", "resolved_impact_direction", "horizon",
        "n_type_clusters", "n_announcement_dates", "n_gap_observations",
        "mean_opening_gap_return", "median_opening_gap_return", "opening_gap_positive_rate",
        "n_drift_observations", "mean_drift_return", "median_drift_return",
        "mean_abnormal_drift_return", "median_abnormal_drift_return", "drift_positive_rate",
    ]
    if result.empty:
        return pd.DataFrame(columns=columns)
    representative = result.loc[
        result["is_type_cluster_representative"]
        & result["market_data_status"].eq("covered")
    ].copy()
    if representative.empty:
        return pd.DataFrame(columns=columns)
    representative["availability_basis"] = representative["availability_basis"].fillna("unknown")
    direction_column = _direction_column(representative)
    group_columns = ["availability_basis", "primary_event_type", direction_column]
    rows: list[dict[str, object]] = []
    for keys, group in representative.groupby(group_columns, dropna=False):
        key_values = dict(zip(group_columns, keys, strict=True))
        if direction_column != "resolved_impact_direction":
            key_values["resolved_impact_direction"] = key_values.pop(direction_column)
        dates = pd.to_datetime(group["available_at"], errors="coerce", utc=True).dt.tz_convert(HK_TZ).dt.date
        for label in HORIZONS:
            gaps = pd.to_numeric(group["opening_gap_return"], errors="coerce").dropna()
            drifts = pd.to_numeric(group[f"{label}_drift_return"], errors="coerce").dropna()
            abnormal = pd.to_numeric(group[f"{label}_abnormal_drift_return"], errors="coerce").dropna()
            rows.append(
                {
                    **key_values,
                    "horizon": label,
                    "n_type_clusters": int(len(group)),
                    "n_announcement_dates": int(dates.nunique()),
                    "n_gap_observations": int(gaps.size),
                    "mean_opening_gap_return": None if gaps.empty else float(gaps.mean()),
                    "median_opening_gap_return": None if gaps.empty else float(gaps.median()),
                    "opening_gap_positive_rate": None if gaps.empty else float((gaps > 0).mean()),
                    "n_drift_observations": int(drifts.size),
                    "mean_drift_return": None if drifts.empty else float(drifts.mean()),
                    "median_drift_return": None if drifts.empty else float(drifts.median()),
                    "mean_abnormal_drift_return": None if abnormal.empty else float(abnormal.mean()),
                    "median_abnormal_drift_return": None if abnormal.empty else float(abnormal.median()),
                    "drift_positive_rate": None if abnormal.empty else float((abnormal > 0).mean()),
                }
            )
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["horizon", "availability_basis", "primary_event_type", "resolved_impact_direction"]
    ).reset_index(drop=True)


def direction_conflict_frame(result: pd.DataFrame) -> pd.DataFrame:
    """Return unresolved row-level raw-versus-derived direction conflicts."""
    columns = [
        "event_id", "ticker", "event_type", "primary_event_type", "title_en", "title_zh",
        "announcement_at", "available_at", "availability_basis", "source_url",
        "impact_direction", "raw_impact_direction_normalized", "impact_confidence",
        "review_status", "parser_version", "derived_impact_direction", "impact_direction_basis",
        "impact_direction_reconciled", "impact_direction_reconciliation_basis",
        "resolved_impact_direction", "resolved_impact_direction_basis",
    ]
    if result.empty:
        return pd.DataFrame(columns=columns)
    raw = result["impact_direction"].fillna("unknown").astype(str).str.lower()
    derived = result["derived_impact_direction"].fillna("neutral_unknown").astype(str)
    mask = raw.isin({"positive", "negative", "mixed"}) & derived.isin(
        {"positive", "negative", "mixed"}
    ) & raw.ne(derived)
    if "resolved_impact_direction_basis" in result:
        mask &= result["resolved_impact_direction_basis"].eq("raw_derived_conflict")
    conflicts = result.loc[mask].copy()
    if conflicts.empty:
        return pd.DataFrame(columns=columns)
    conflicts["raw_impact_direction_normalized"] = raw.loc[mask]
    for column in columns:
        if column not in conflicts:
            conflicts[column] = None
    return conflicts[columns].sort_values(["available_at", "ticker", "event_id"]).reset_index(drop=True)


def native_1h_sensitivity(result: pd.DataFrame) -> pd.DataFrame:
    """Compare native 1h abnormal returns with the 5m-derived 1h result."""
    columns = [
        "session", "primary_event_type", "resolved_impact_direction", "n_type_clusters",
        "n_native_1h_rows", "n_comparable_rows", "native_1h_coverage_rate",
        "mean_native_1h_abnormal_return", "mean_5m_derived_1h_abnormal_return",
        "mean_return_difference", "directional_agreement_rate",
    ]
    if result.empty:
        return pd.DataFrame(columns=columns)
    representative = result.loc[result["is_type_cluster_representative"]].copy()
    if representative.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    direction_column = _direction_column(representative)
    for keys, group in representative.groupby(
        ["session", "primary_event_type", direction_column], dropna=False
    ):
        native = pd.to_numeric(group["native_1h_abnormal_return"], errors="coerce")
        derived = pd.to_numeric(group["1h_abnormal_return"], errors="coerce")
        comparable = pd.DataFrame({"native": native, "derived": derived}).dropna()
        agreement = None
        if not comparable.empty:
            agreement = float(
                (
                    (comparable["native"] == 0) & (comparable["derived"] == 0)
                    | (comparable["native"] * comparable["derived"] > 0)
                ).mean()
            )
        rows.append(
            {
                "session": keys[0],
                "primary_event_type": keys[1],
                "resolved_impact_direction": keys[2],
                "n_type_clusters": int(len(group)),
                "n_native_1h_rows": int(native.notna().sum()),
                "n_comparable_rows": int(len(comparable)),
                "native_1h_coverage_rate": float(native.notna().mean()),
                "mean_native_1h_abnormal_return": None if native.dropna().empty else float(native.mean()),
                "mean_5m_derived_1h_abnormal_return": None if derived.dropna().empty else float(derived.mean()),
                "mean_return_difference": None if comparable.empty else float((comparable["native"] - comparable["derived"]).mean()),
                "directional_agreement_rate": agreement,
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["session", "n_type_clusters", "primary_event_type", "resolved_impact_direction"],
        ascending=[True, False, True, True],
    ).reset_index(drop=True)


def build_signal_registration_gate(
    archive_audit: dict[str, object] | None,
    evidence: dict[str, int] | None = None,
) -> dict[str, object]:
    evidence = evidence or {}
    covered_event_rows = int(evidence.get("covered_event_rows", 0))
    covered_observed_event_rows = int(evidence.get("covered_observed_event_rows", 0))
    covered_proxy_event_rows = int(evidence.get("covered_proxy_event_rows", 0))
    direction_conflict_rows = int(evidence.get("direction_conflict_rows", 0))
    bar_hole_event_rows = int(evidence.get("bar_hole_event_rows", 0))
    if archive_audit is None:
        gate = {
            "status": "blocked",
            "reasons": ["archive_audit_missing"],
            "distinct_market_cutoff_count_5m": None,
            "distinct_market_cutoff_count_1h": None,
        }
        gate.update(
            {
                "covered_event_rows": covered_event_rows,
                "covered_observed_event_rows": covered_observed_event_rows,
                "covered_proxy_event_rows": covered_proxy_event_rows,
                "direction_conflict_rows": direction_conflict_rows,
                "bar_hole_event_rows": bar_hole_event_rows,
            }
        )
        return gate
    distinct_5m = int(archive_audit.get("intervals", {}).get("5m", {}).get("distinct_market_cutoff_count", 0))
    distinct_1h = int(archive_audit.get("intervals", {}).get("1h", {}).get("distinct_market_cutoff_count", 0))
    reasons: list[str] = []
    if any(
        archive_audit.get("intervals", {}).get(interval, {}).get("status") != "ok"
        for interval in ("5m", "1h")
    ):
        reasons.append("archive_quality_degraded")
    if min(distinct_5m, distinct_1h) < 2:
        reasons.append("insufficient_distinct_market_cutoffs")
    if covered_event_rows > 0 and covered_observed_event_rows == 0:
        reasons.append("covered_sample_proxy_only")
    if direction_conflict_rows > 0:
        reasons.append("direction_conflicts_require_review")
    if bar_hole_event_rows > 0:
        reasons.append("bar_holes_require_review")
    return {
        "status": "blocked" if reasons else "review_required",
        "reasons": reasons,
        "distinct_market_cutoff_count_5m": distinct_5m,
        "distinct_market_cutoff_count_1h": distinct_1h,
        "covered_event_rows": covered_event_rows,
        "covered_observed_event_rows": covered_observed_event_rows,
        "covered_proxy_event_rows": covered_proxy_event_rows,
        "direction_conflict_rows": direction_conflict_rows,
        "bar_hole_event_rows": bar_hole_event_rows,
    }


def build_signal_registry(
    robustness: pd.DataFrame,
    registration_gate: dict[str, object] | None = None,
) -> pd.DataFrame:
    """Build an explicit, non-trading signal readiness registry.

    The registry is intentionally conservative.  ``status`` is retained for
    compatibility, while explicit statistical and execution fields prevent an
    ``exploratory`` row from being mistaken for a tradable signal.
    """
    columns = [
        "signal_id",
        "primary_event_type",
        "resolved_impact_direction",
        "horizon",
        "status",
        "statistical_gates_passed",
        "sample_tier",
        "registration_state",
        "registered_for_trading_signal",
        "trading_execution_eligible",
        "global_registration_gate_status",
        "global_registration_gate_reasons",
        "stale_archive_event_rows",
        "stale_archive_missing_event_rows",
        "stale_archive_covered_event_rows",
        "covered_event_rows",
        "covered_observed_event_rows",
        "covered_proxy_event_rows",
        "direction_conflict_rows",
        "bar_hole_event_rows",
        "n_type_clusters",
        "n_announcement_dates",
        "pit_observed_share",
        "pit_quality",
        "mean_abnormal_return",
        "median_abnormal_return",
        "winsorized_1pct_mean",
        "mean_after_30bps_scenario",
        "event_level_t_stat",
        "announcement_date_cluster_t_stat",
        "median_mean_ratio",
        "sample_gate",
        "date_gate",
        "t_stat_gate",
        "distribution_gate",
        "cost_direction_gate",
        "reason",
    ]
    if robustness.empty:
        return pd.DataFrame(columns=columns)
    direction_column = _direction_column(robustness)
    rows: list[dict[str, object]] = []
    for source in robustness.to_dict(orient="records"):
        mean = float(source["mean_abnormal_return"])
        median = float(source["median_abnormal_return"])
        cost_mean = float(source["mean_after_30bps_scenario"])
        median_mean_ratio = None if mean == 0 else median / mean
        sample_gate = int(source["n_type_clusters"]) >= MIN_SIGNAL_CLUSTERS
        date_gate = int(source["n_announcement_dates"]) >= MIN_SIGNAL_DATES
        t_stat = source["announcement_date_cluster_t_stat"]
        t_stat_gate = t_stat is not None and not pd.isna(t_stat) and abs(float(t_stat)) >= MIN_SIGNAL_T_STAT
        distribution_gate = (
            median_mean_ratio is not None
            and median_mean_ratio >= MIN_MEDIAN_MEAN_RATIO
            and median * mean > 0
        )
        cost_direction_gate = cost_mean * mean > 0
        gates = {
            "sample": sample_gate,
            "dates": date_gate,
            "date-cluster t-stat": t_stat_gate,
            "median/mean distribution": distribution_gate,
            "30bps scenario direction": cost_direction_gate,
        }
        failed = [name for name, passed in gates.items() if not passed]
        evidence_n = int(source["n_type_clusters"])
        statistical_gates_passed = not failed
        sample_tier = (
            "sufficient_sample"
            if evidence_n >= MIN_SIGNAL_CLUSTERS
            else "insufficient_sample"
        )
        status = "candidate_review" if statistical_gates_passed else (
            "blocked" if sample_tier == "insufficient_sample" else "exploratory"
        )
        registered_for_trading_signal = False
        global_gate_status = (
            "not_assessed" if registration_gate is None else registration_gate["status"]
        )
        trading_execution_eligible = bool(
            registered_for_trading_signal
            and statistical_gates_passed
            and status == "candidate_review"
            and global_gate_status == "passed"
        )
        rows.append(
            {
                "signal_id": (
                    f"hkex.{str(source['primary_event_type']).lower()}"
                    f".{str(source[direction_column]).lower()}.{source['horizon']}"
                ),
                "primary_event_type": source["primary_event_type"],
                "resolved_impact_direction": source[direction_column],
                "horizon": source["horizon"],
                "status": status,
                "statistical_gates_passed": statistical_gates_passed,
                "sample_tier": sample_tier,
                "registration_state": "not_registered",
                "registered_for_trading_signal": registered_for_trading_signal,
                "trading_execution_eligible": trading_execution_eligible,
                "global_registration_gate_status": global_gate_status,
                "global_registration_gate_reasons": (
                    "not_assessed" if registration_gate is None else "; ".join(registration_gate["reasons"])
                ),
                "stale_archive_event_rows": (
                    None if registration_gate is None else registration_gate.get("stale_archive_event_rows", 0)
                ),
                "stale_archive_missing_event_rows": (
                    None if registration_gate is None else registration_gate.get("stale_archive_missing_event_rows", 0)
                ),
                "stale_archive_covered_event_rows": (
                    None if registration_gate is None else registration_gate.get("stale_archive_covered_event_rows", 0)
                ),
                "covered_event_rows": (
                    None if registration_gate is None else registration_gate.get("covered_event_rows", 0)
                ),
                "covered_observed_event_rows": (
                    None if registration_gate is None else registration_gate.get("covered_observed_event_rows", 0)
                ),
                "covered_proxy_event_rows": (
                    None if registration_gate is None else registration_gate.get("covered_proxy_event_rows", 0)
                ),
                "direction_conflict_rows": (
                    None if registration_gate is None else registration_gate.get("direction_conflict_rows", 0)
                ),
                "bar_hole_event_rows": (
                    None if registration_gate is None else registration_gate.get("bar_hole_event_rows", 0)
                ),
                "n_type_clusters": evidence_n,
                "n_announcement_dates": int(source["n_announcement_dates"]),
                "pit_observed_share": float(source["pit_observed_share"]),
                "pit_quality": (
                    "observed"
                    if float(source["pit_observed_share"]) >= 0.8
                    else (
                        "proxy_only"
                        if float(source["pit_observed_share"]) == 0
                        else "mixed_proxy_observed"
                    )
                ),
                "mean_abnormal_return": mean,
                "median_abnormal_return": median,
                "winsorized_1pct_mean": source["winsorized_1pct_mean"],
                "mean_after_30bps_scenario": cost_mean,
                "event_level_t_stat": source["event_level_t_stat"],
                "announcement_date_cluster_t_stat": source["announcement_date_cluster_t_stat"],
                "median_mean_ratio": median_mean_ratio,
                "sample_gate": sample_gate,
                "date_gate": date_gate,
                "t_stat_gate": t_stat_gate,
                "distribution_gate": distribution_gate,
                "cost_direction_gate": cost_direction_gate,
                "reason": "all gates passed; manual review required" if not failed else "failed: " + "; ".join(failed),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["horizon", "status", "primary_event_type", "resolved_impact_direction"]
    ).reset_index(drop=True)


def validate_evidence_outputs(
    result: pd.DataFrame,
    summary: pd.DataFrame,
    robustness: pd.DataFrame,
    registry: pd.DataFrame,
    stratified: pd.DataFrame | None = None,
    gap_drift: pd.DataFrame | None = None,
    direction_conflicts: pd.DataFrame | None = None,
    native_1h: pd.DataFrame | None = None,
) -> None:
    """Fail fast on invariants required by the dashboard evidence contract."""
    if result["event_id"].duplicated().any():
        raise ValueError("event_returns event_id must be unique")
    if result["primary_event_type"].isna().any() or result["primary_event_type"].eq("UNKNOWN").any():
        raise ValueError("all events must have a primary_event_type")
    covered = result["market_data_status"].eq("covered")
    entry = pd.to_datetime(result.loc[covered, "entry_bar_at"], errors="coerce", utc=True)
    available = pd.to_datetime(result.loc[covered, "available_at"], errors="coerce", utc=True)
    if not (entry > available).all():
        raise ValueError("covered entry_bar_at must be strictly later than available_at")
    if (result["1h_return"].notna() & result["30m_return"].isna()).any():
        raise ValueError("1h return coverage must imply 30m return coverage")
    if (result["30m_return"].notna() & result["5m_return"].isna()).any():
        raise ValueError("30m return coverage must imply 5m return coverage")
    if not summary.empty and int(summary["event_clusters"].sum()) != int(result["is_type_cluster_representative"].sum()):
        raise ValueError("summary event_clusters do not reconcile to type representatives")
    if not robustness.empty and robustness.duplicated(
        ["primary_event_type", "resolved_impact_direction", "horizon"]
    ).any():
        raise ValueError("robustness summary grain must be unique")
    if not registry.empty and registry["signal_id"].duplicated().any():
        raise ValueError("signal registry signal_id must be unique")
    if stratified is not None and not stratified.empty and stratified.duplicated(
        [
            "availability_basis", "market_data_status", "liquidity_bucket",
            "primary_event_type", "resolved_impact_direction", "horizon",
        ]
    ).any():
        raise ValueError("stratified summary grain must be unique")
    if gap_drift is not None and not gap_drift.empty and gap_drift.duplicated(
        ["availability_basis", "primary_event_type", "resolved_impact_direction", "horizon"]
    ).any():
        raise ValueError("gap/drift summary grain must be unique")
    valid_raw = {"unknown", "positive", "negative", "mixed"}
    if "impact_direction" in result and not result["impact_direction"].fillna("unknown").isin(valid_raw).all():
        raise ValueError("raw impact_direction contains an unsupported value")
    if "impact_direction_reconciled" in result and not result["impact_direction_reconciled"].fillna("unknown").isin(valid_raw).all():
        raise ValueError("reconciled impact direction contains an unsupported value")
    if "impact_direction_reconciliation_basis" in result and not result[
        "impact_direction_reconciliation_basis"
    ].isin({"source_parser_raw", "category_generic_title_override"}).all():
        raise ValueError("impact direction reconciliation basis contains an unsupported value")
    if "derived_impact_direction" in result and not result["derived_impact_direction"].isin(
        {"neutral_unknown", "positive", "negative", "mixed"}
    ).all():
        raise ValueError("derived impact direction contains an unsupported value")
    if "resolved_impact_direction" in result and not result["resolved_impact_direction"].isin(
        {"unknown", "positive", "negative", "mixed", "review_required"}
    ).all():
        raise ValueError("resolved impact direction contains an unsupported value")
    if direction_conflicts is not None and not direction_conflicts.empty:
        if direction_conflicts["event_id"].duplicated().any():
            raise ValueError("direction conflict event_id must be unique")
        if not direction_conflicts["impact_direction"].isin({"positive", "negative", "mixed"}).all():
            raise ValueError("direction conflict raw labels must be non-unknown")
        if (
            (direction_conflicts["impact_direction"].str.lower() == direction_conflicts["derived_impact_direction"])
            | ~direction_conflicts["derived_impact_direction"].isin({"positive", "negative", "mixed"})
        ).any():
            raise ValueError("direction conflict queue contains a non-conflict row")
    if native_1h is not None and not native_1h.empty and native_1h.duplicated(
        ["session", "primary_event_type", "resolved_impact_direction"]
    ).any():
        raise ValueError("native 1h sensitivity grain must be unique")
    if not result["native_1h_status"].isin(
        {"missing", "covered", "benchmark_missing", "bar_hole"}
    ).all():
        raise ValueError("native 1h status contains an unsupported value")
    native_covered = result["native_1h_status"].eq("covered")
    native_entry = pd.to_datetime(result.loc[native_covered, "native_1h_entry_bar_at"], errors="coerce", utc=True)
    native_available = pd.to_datetime(result.loc[native_covered, "available_at"], errors="coerce", utc=True)
    if not (native_entry > native_available).all():
        raise ValueError("covered native 1h entry_bar_at must be strictly later than available_at")


def run(args: argparse.Namespace) -> dict[str, object]:
    archive_audit: dict[str, object] | None = None
    if args.snapshot_root is not None:
        archive_audit = load_archive_audit(args.snapshot_root)
    candidate_tickers = None
    candidate_archive_expansion_tickers: list[str] = []
    candidate_archive_unavailable_tickers: list[str] = []
    if getattr(args, "candidate_inventory", None) is not None and archive_audit is not None:
        canonical_archive_tickers = set(archive_audit.get("requested_symbols", []))
        candidate_tickers = resolve_candidate_tickers(
            args.candidate_inventory,
            canonical_archive_tickers,
            args.snapshot_root,
        )
        candidate_archive_expansion_tickers = sorted(candidate_tickers - canonical_archive_tickers)
    events = load_events(
        args.financial_db,
        top_tickers=args.top_tickers,
        candidate_inventory=getattr(args, "candidate_inventory", None),
        candidate_tickers=candidate_tickers,
    )
    tickers = sorted(events["ticker"].unique())
    symbols = tickers + [BENCHMARK]
    if args.snapshot_root is None:
        bars_5m = download_bars(symbols, period=args.period_5m, interval="5m")
        bars_1h = download_bars(symbols, period=args.period_1h, interval="1h")
        market_data_source = "yfinance_live"
        archive_quality = {"archive_file_count": 0, "archive_duplicate_rows": 0, "archive_conflict_keys": 0}
        data_source_mode = "live_only"
        reproducibility_level = "live_download_not_archived"
        archive_symbols_by_interval = {"5m": [], "1h": []}
        archive_symbol_earliest_by_interval = {"5m": {}, "1h": {}}
        archive_symbol_latest_by_interval = {"5m": {}, "1h": {}}
        archive_missing_symbols_by_interval = {"5m": [], "1h": []}
        live_fallback_symbols: list[str] = []
    else:
        allow_partial_candidate_archive = getattr(args, "candidate_inventory", None) is not None
        require_all_archive_symbols = not args.allow_live_fallback and not allow_partial_candidate_archive
        try:
            bars_5m = load_archived_bars(
                args.snapshot_root,
                interval="5m",
                symbols=symbols,
                require_all=require_all_archive_symbols,
                capture_id=getattr(args, "capture_id", None),
            )
        except FileNotFoundError:
            if not args.allow_live_fallback:
                raise
            bars_5m = pd.DataFrame()
        try:
            bars_1h = load_archived_bars(
                args.snapshot_root,
                interval="1h",
                symbols=symbols,
                require_all=require_all_archive_symbols,
                capture_id=getattr(args, "capture_id", None),
            )
        except FileNotFoundError:
            if not args.allow_live_fallback:
                raise
            bars_1h = pd.DataFrame()
        archive_quality = {
            "archive_file_count": int(bars_5m.attrs.get("archive_file_count", 0) + bars_1h.attrs.get("archive_file_count", 0)),
            "archive_duplicate_rows": int(bars_5m.attrs.get("archive_duplicate_rows", 0) + bars_1h.attrs.get("archive_duplicate_rows", 0)),
            "archive_conflict_keys": int(bars_5m.attrs.get("archive_conflict_keys", 0) + bars_1h.attrs.get("archive_conflict_keys", 0)),
        }
        archive_symbols_by_interval = {
            "5m": sorted(bars_5m.attrs.get("archive_symbols", [])),
            "1h": sorted(bars_1h.attrs.get("archive_symbols", [])),
        }
        archive_missing_symbols_by_interval = {
            "5m": sorted(bars_5m.attrs.get("archive_missing_symbols", [])),
            "1h": sorted(bars_1h.attrs.get("archive_missing_symbols", [])),
        }
        candidate_archive_unavailable_tickers = sorted(
            set(candidate_archive_expansion_tickers)
            & (
                set(archive_missing_symbols_by_interval["5m"])
                | set(archive_missing_symbols_by_interval["1h"])
            )
        )
        archive_symbol_earliest_by_interval = {
            "5m": bars_5m.attrs.get("archive_symbol_earliest_utc", {}),
            "1h": bars_1h.attrs.get("archive_symbol_earliest_utc", {}),
        }
        archive_symbol_latest_by_interval = {
            "5m": bars_5m.attrs.get("archive_symbol_latest_utc", {}),
            "1h": bars_1h.attrs.get("archive_symbol_latest_utc", {}),
        }
        live_fallback_symbols = sorted(
            _needs_live_fallback(events, symbols, bars_5m, bars_1h)
        ) if args.allow_live_fallback else []
        if live_fallback_symbols:
            live_5m = download_bars(live_fallback_symbols, period=args.period_5m, interval="5m")
            live_1h = download_bars(live_fallback_symbols, period=args.period_1h, interval="1h")
            bars_5m = merge_bar_frames(bars_5m, live_5m)
            bars_1h = merge_bar_frames(bars_1h, live_1h)
            market_data_source = "yfinance_archive_plus_live_fallback"
            data_source_mode = "hybrid_archive_live"
            reproducibility_level = "live_fallback_active"
        else:
            market_data_source = "yfinance_snapshot_archive"
            data_source_mode = "archive_only"
            reproducibility_level = "strict_guaranteed"
    result = calculate_event_returns(events, bars_5m, bars_1h)
    candidate_archive_unavailable_set = set(candidate_archive_unavailable_tickers)
    if candidate_archive_unavailable_set:
        missing_5m = set(archive_missing_symbols_by_interval.get("5m", []))
        missing_1h = set(archive_missing_symbols_by_interval.get("1h", []))
        for ticker in candidate_archive_unavailable_set:
            if ticker in missing_5m and ticker in missing_1h:
                reason = "missing_5m_and_1h_bars_in_snapshot"
            elif ticker in missing_5m:
                reason = "missing_5m_bars_in_snapshot"
            else:
                reason = "missing_1h_bars_in_snapshot"
            mask = result["ticker"].eq(ticker) & result["market_data_status"].eq("missing")
            result.loc[mask, "data_gap_reason"] = reason
    archive_stale_event_tickers: list[str] = []
    if archive_audit:
        stale_symbols = set(
            archive_audit.get("intervals", {}).get("5m", {}).get("stale_symbols", [])
        )
        stale_mask = result["ticker"].isin(stale_symbols) & result["market_data_status"].eq("missing")
        archive_stale_event_tickers = sorted(result.loc[stale_mask, "ticker"].unique().tolist())
        if stale_mask.any():
            result.loc[stale_mask, "data_gap_reason"] = result.loc[stale_mask, "data_gap_reason"].map(
                lambda value: f"{value}; archive_stale_symbol" if value else "archive_stale_symbol"
            )
    pending_market_cutoff_event_rows = 0
    if archive_audit:
        reference_latest_bar_utc = archive_audit.get("intervals", {}).get("5m", {}).get(
            "reference_latest_bar_utc"
        )
        result, pending_market_cutoff_event_rows = mark_pending_market_cutoff_events(
            result, reference_latest_bar_utc
        )
    stale_archive_symbols = set()
    if archive_audit:
        stale_archive_symbols = set(
            archive_audit.get("intervals", {}).get("5m", {}).get("stale_symbols", [])
        )
    stale_event_mask = result["ticker"].isin(stale_archive_symbols)
    summary = summarize(result)
    robustness = robustness_summary(result)
    stratified = stratified_event_summary(result)
    gap_drift = gap_drift_summary(result)
    direction_conflicts = direction_conflict_frame(result)
    native_1h = native_1h_sensitivity(result)
    signal_registration_gate = build_signal_registration_gate(
        archive_audit,
        evidence={
            "covered_event_rows": int(result["market_data_status"].eq("covered").sum()),
            "covered_observed_event_rows": int(
                (result["market_data_status"].eq("covered")
                 & result["availability_basis"].eq("observed_collection")).sum()
            ),
            "covered_proxy_event_rows": int(
                (result["market_data_status"].eq("covered")
                 & result["availability_basis"].eq("source_timestamp_proxy")).sum()
            ),
            "direction_conflict_rows": int(len(direction_conflicts)),
            "bar_hole_event_rows": int(result["bar_hole_horizons"].fillna("").ne("").sum()),
        },
    )
    signal_registration_gate.update(
        {
            "stale_archive_event_rows": int(stale_event_mask.sum()),
            "stale_archive_missing_event_rows": int(
                (stale_event_mask & result["market_data_status"].eq("missing")).sum()
            ),
            "stale_archive_covered_event_rows": int(
                (stale_event_mask & result["market_data_status"].eq("covered")).sum()
            ),
        }
    )
    registry = build_signal_registry(robustness, signal_registration_gate)
    validate_evidence_outputs(
        result, summary, robustness, registry, stratified, gap_drift, direction_conflicts, native_1h
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output_dir / "event_returns.csv", index=False)
    summary.to_csv(args.output_dir / "event_type_summary.csv", index=False)
    robustness.to_csv(args.output_dir / "event_robustness_summary.csv", index=False)
    stratified.to_csv(args.output_dir / "event_stratified_summary.csv", index=False)
    gap_drift.to_csv(args.output_dir / "event_gap_drift_summary.csv", index=False)
    direction_conflicts.to_csv(args.output_dir / "event_direction_conflicts.csv", index=False)
    native_1h.to_csv(args.output_dir / "event_native_1h_sensitivity.csv", index=False)
    registry.to_csv(args.output_dir / "signal_registry.csv", index=False)
    raw_direction_counts = (
        result["impact_direction"].value_counts(dropna=False).to_dict()
        if "impact_direction" in result
        else {}
    )
    derived_direction_counts = result["derived_impact_direction"].value_counts(dropna=False).to_dict()
    resolved_direction_counts = result["resolved_impact_direction"].value_counts(dropna=False).to_dict()
    primary_type_counts = result["primary_event_type"].value_counts(dropna=False).to_dict()
    cluster_rows = result.loc[result["cluster_key"].notna()].drop_duplicates("cluster_key")
    native_comparable = result.loc[
        result["native_1h_abnormal_return"].notna()
        & result["1h_abnormal_return"].notna()
    ].copy()
    native_agreement = None
    native_mean_abs_difference = None
    if not native_comparable.empty:
        native_agreement = float(
            (
                (native_comparable["native_1h_abnormal_return"] == 0)
                & (native_comparable["1h_abnormal_return"] == 0)
                | (
                    native_comparable["native_1h_abnormal_return"]
                    * native_comparable["1h_abnormal_return"]
                    > 0
                )
            ).mean()
        )
        native_mean_abs_difference = float(
            (
                native_comparable["native_1h_abnormal_return"]
                - native_comparable["1h_abnormal_return"]
            ).abs().mean()
        )
    raw_direction = result["impact_direction"].fillna("unknown").astype(str).str.lower()
    derived_direction = result["derived_impact_direction"].fillna("neutral_unknown").astype(str)
    raw_labeled = raw_direction.isin({"positive", "negative", "mixed"})
    raw_derived_conflicts = (
        pd.DataFrame({"raw": raw_direction[raw_labeled], "derived": derived_direction[raw_labeled]})
        .loc[lambda frame: frame["derived"].isin({"positive", "negative", "mixed"})]
        .value_counts()
        .to_dict()
    )
    raw_derived_conflict_counts = {
        f"{raw}->{derived}": int(count)
        for (raw, derived), count in raw_derived_conflicts.items()
        if raw != derived
    }
    coverage = {
        "requested_tickers": tickers,
        "ticker_count": len(tickers),
        "event_rows": int(len(result)),
        "canonical_event_rows": int((~result["event_id"].astype(str).str.startswith("filing:")).sum())
        if not result.empty
        else 0,
        "candidate_event_rows": int(result["event_id"].astype(str).str.startswith("filing:").sum())
        if not result.empty
        else 0,
        "candidate_inventory": (
            None if getattr(args, "candidate_inventory", None) is None
            else str(args.candidate_inventory)
        ),
        "candidate_ticker_filter_applied": bool(
            getattr(args, "candidate_inventory", None) is not None and candidate_tickers is not None
        ),
        "candidate_archive_expansion_tickers": candidate_archive_expansion_tickers,
        "candidate_archive_expansion_ticker_count": int(len(candidate_archive_expansion_tickers)),
        "candidate_archive_unavailable_tickers": candidate_archive_unavailable_tickers,
        "candidate_archive_unavailable_ticker_count": int(len(candidate_archive_unavailable_tickers)),
        "archive_missing_symbols_by_interval": archive_missing_symbols_by_interval,
        "event_clusters": int(result["cluster_key"].nunique()) if not result.empty else 0,
        "deduped_event_rows": int(result["is_cluster_representative"].sum()) if not result.empty else 0,
        "event_type_cluster_rows": int(result["is_type_cluster_representative"].sum()) if not result.empty else 0,
        "multi_document_cluster_count": int(cluster_rows["is_multi_document_cluster"].sum()),
        "pure_event_cluster_count": int(cluster_rows["is_pure_event_type"].sum()),
        "contaminated_type_cluster_rows": int(
            (result["is_type_cluster_representative"] & ~result["is_pure_event_type"]).sum()
        ),
        "robustness_summary_rows": int(len(robustness)),
        "stratified_summary_rows": int(len(stratified)),
        "gap_drift_summary_rows": int(len(gap_drift)),
        "direction_conflict_rows": int(len(direction_conflicts)),
        "raw_direction_conflict_rows": int(
            sum(raw_derived_conflict_counts.values())
        ),
        "direction_override_rows": int(
            result["impact_direction_reconciliation_basis"].eq(
                "category_generic_title_override"
            ).sum()
        ),
        "native_1h_sensitivity_rows": int(len(native_1h)),
        "native_1h_return_coverage": int(
            pd.to_numeric(result["native_1h_abnormal_return"], errors="coerce").notna().sum()
        ),
        "native_1h_comparable_rows": int(len(native_comparable)),
        "native_1h_global_directional_agreement_rate": native_agreement,
        "native_1h_mean_absolute_difference": native_mean_abs_difference,
        "bar_hole_event_rows": int(result["bar_hole_horizons"].fillna("").ne("").sum()),
        "pending_market_cutoff_event_rows": int(pending_market_cutoff_event_rows),
        "native_1h_bar_hole_rows": int(result["native_1h_status"].eq("bar_hole").sum()),
        "signal_registry_rows": int(len(registry)),
        "signal_registry_status_counts": registry["status"].value_counts(dropna=False).to_dict()
        if not registry.empty
        else {},
        "signal_registration_gate": signal_registration_gate,
        "evidence_contract": {
            "version": EVIDENCE_CONTRACT_VERSION,
            "artifacts": {
                "event_returns.csv": {
                    "grain": "one row per source announcement event_id",
                    "key": "event_id",
                    "role": "event detail and audit trail",
                },
                "event_type_summary.csv": {
                    "grain": "one row per primary_event_type",
                    "key": "primary_event_type",
                    "role": "cluster-level descriptive summary",
                },
                "event_robustness_summary.csv": {
                    "grain": "one row per primary_event_type x resolved_impact_direction x horizon",
                    "key": "primary_event_type,resolved_impact_direction,horizon",
                    "role": "robustness and readiness evidence",
                },
                "event_stratified_summary.csv": {
                    "grain": "one row per PIT basis x market status x liquidity bucket x primary event x resolved direction x horizon",
                    "key": "availability_basis,market_data_status,liquidity_bucket,primary_event_type,resolved_impact_direction,horizon",
                    "role": "PIT and liquidity sensitivity evidence",
                },
                "event_gap_drift_summary.csv": {
                    "grain": "one row per PIT basis x primary event x resolved direction x horizon",
                    "key": "availability_basis,primary_event_type,resolved_impact_direction,horizon",
                    "role": "opening-gap versus post-entry drift sensitivity",
                },
                "event_direction_conflicts.csv": {
                    "grain": "one row per raw-versus-title-derived direction conflict",
                    "key": "event_id",
                    "role": "manual audit queue; not a trading signal input",
                },
                "event_native_1h_sensitivity.csv": {
                    "grain": "one row per session x primary event type x resolved direction",
                    "key": "session,primary_event_type,resolved_impact_direction",
                    "role": "native 1h versus 5m-derived 1h sensitivity",
                },
                "signal_registry.csv": {
                    "grain": "one row per evidence group and horizon",
                    "key": "signal_id",
                    "role": "explicit statistical and execution eligibility evidence; not automatic trading registration",
                },
            },
            "field_semantics": {
                "*_return": "legacy alias for entry-bar open-to-open drift",
                "*_drift_return": "explicit entry-bar open-to-open drift, excluding opening gap",
                "opening_gap_return": "previous close to first eligible entry open when non-intraday",
                "opening_gap_benchmark_return": "synchronous previous HSI close to entry open gap; used for abnormal total-return decomposition",
                "opening_gap_abnormal_return": "opening gap return minus synchronous HSI opening gap return",
                "*_abnormal_drift_return": "stock drift minus synchronous HSI drift",
                "total_*_return": "opening gap compounded with post-entry drift; intraday events use zero gap",
                "total_*_abnormal_return": "total stock return minus total synchronous HSI return",
                "signed_*_abnormal_return": "abnormal drift return signed positive for positive direction and negative for negative direction; review/unknown rows are null",
                "signed_total_*_abnormal_return": "direction-signed total abnormal return; review/unknown rows are null",
                "native_1h_abnormal_return": "native 1h-bar stock return minus synchronous native 1h HSI return; sensitivity only",
                "bar_hole_horizons": "comma-separated horizons rejected because an unexpected same-session bar gap was detected; no interpolation is used",
                "native_1h_bar_hole_reason": "unexpected same-session gap in the native 1h stock or benchmark window",
                "zero_volume_ratio_1h": "share of observed active 5m bars with zero volume in entry plus next 1h window; missing volume is not counted as zero",
                "statistical_gates_passed": "true only when all five per-signal sample/date/t-stat/distribution/cost gates pass",
                "sample_tier": "sufficient_sample or insufficient_sample based on the minimum cluster threshold; it is not a pass/fail result",
                "trading_execution_eligible": "true only when the signal is explicitly registered, all statistical gates pass, the global gate is passed, and status is candidate_review",
                "impact_direction": "canonical parser label; retained for audit and not treated as ground truth",
                "impact_direction_reconciled": "raw label after the narrow generic EARNINGS_WARNING/title override; source label remains available separately",
                "impact_direction_reconciliation_basis": "source_parser_raw or category_generic_title_override",
                "impact_confidence": "canonical parser confidence for the raw label",
                "derived_impact_direction": "title-text classification for exploratory display, not earnings surprise",
                "impact_direction_basis": "audit label for the title rule: high-precision positive/negative match, conflicting matches, or no high-precision title match",
                "resolved_impact_direction": "conservative dashboard-facing direction; raw and title conflicts resolve to review_required, while neutral title evidence leaves a valid raw label intact",
                "resolved_impact_direction_basis": "resolution provenance: raw_and_title_agree, raw_only_title_neutral, title_only, category_generic_title_override, raw_derived_conflict, or insufficient_direction_evidence",
                "cluster_document_count": "distinct source documents sharing the same eligible entry bar",
                "cluster_co_occurring_types": "sorted comma-separated primary event types sharing the eligible entry bar",
                "is_multi_document_cluster": "true when a cluster contains more than one distinct source document",
                "is_pure_event_type": "true when a non-missing cluster contains only one primary event type",
            },
        },
        "document_count": int(result["document_key"].nunique()) if not result.empty else 0,
        "duplicate_document_rows": int((~result["is_document_representative"]).sum()) if not result.empty else 0,
        "duplicate_cluster_rows": int((~result["is_cluster_representative"]).sum()) if not result.empty else 0,
        "raw_impact_direction_counts": raw_direction_counts,
        "raw_derived_direction_conflict_counts": raw_derived_conflict_counts,
        "derived_impact_direction_counts": derived_direction_counts,
        "resolved_impact_direction_counts": resolved_direction_counts,
        "resolved_impact_direction_review_rows": int(
            result["resolved_impact_direction"].eq("review_required").sum()
        ),
        "primary_event_type_counts": primary_type_counts,
        "availability_basis_counts": result["availability_basis"].value_counts(dropna=False).to_dict(),
        "session_counts": result["session"].value_counts(dropna=False).to_dict(),
        "source_delay_minutes_summary": _numeric_summary(result["source_delay_minutes"]),
        "opening_gap_summary": _numeric_summary(result["gap_return"]),
        "opening_gap_positive_rate": (
            float(pd.to_numeric(result["gap_return"], errors="coerce").dropna().gt(0).mean())
            if pd.to_numeric(result["gap_return"], errors="coerce").notna().any()
            else None
        ),
        "zero_volume_ratio_1h_summary": _numeric_summary(result["zero_volume_ratio_1h"]),
        "zero_volume_events_1h": int(
            pd.to_numeric(result["zero_volume_ratio_1h"], errors="coerce").dropna().gt(0).sum()
        ),
        "market_data_gap_reason_counts": result.loc[
            result["market_data_status"].eq("missing"), "data_gap_reason"
        ].value_counts(dropna=False).to_dict(),
        "archive_stale_event_tickers": archive_stale_event_tickers,
        "stale_archive_event_rows": int(stale_event_mask.sum()),
        "stale_archive_missing_event_rows": int(
            (stale_event_mask & result["market_data_status"].eq("missing")).sum()
        ),
        "stale_archive_covered_event_rows": int(
            (stale_event_mask & result["market_data_status"].eq("covered")).sum()
        ),
        "missing_market_data_tickers": sorted(
            result.loc[result["market_data_status"].eq("missing"), "ticker"].unique().tolist()
        ),
        "market_data_status_counts": result["market_data_status"].value_counts(dropna=False).to_dict()
        if not result.empty
        else {},
        "cluster_return_coverage": {
            label: int(
                pd.to_numeric(
                    result.loc[result["is_cluster_representative"], f"{label}_abnormal_return"],
                    errors="coerce",
                ).notna().sum()
            )
            for label in ("5m", "30m", "1h")
        },
        "event_row_return_coverage": {
            label: int(pd.to_numeric(result[f"{label}_abnormal_return"], errors="coerce").notna().sum())
            for label in ("5m", "30m", "1h")
        },
        "period_5m": args.period_5m,
        "period_1h": args.period_1h,
        "market_data_source": market_data_source,
        "data_source_mode": data_source_mode,
        "reproducibility_level": reproducibility_level,
        "live_fallback_symbols": live_fallback_symbols,
        "archive_symbols_by_interval": archive_symbols_by_interval,
        "archive_symbol_earliest_by_interval": archive_symbol_earliest_by_interval,
        "archive_symbol_latest_by_interval": archive_symbol_latest_by_interval,
        "snapshot_root": None if args.snapshot_root is None else str(args.snapshot_root),
        "archive_capture_id": getattr(args, "capture_id", None),
        "archive_quality": archive_quality,
        "archive_audit": archive_audit,
        "hourly_bar_rows_downloaded": int(len(bars_1h)),
        "benchmark": BENCHMARK,
        "method": "next eligible bar open-to-open; lunch/overnight bars skip non-trading time",
        "limitations": [
            "yfinance intraday history is rolling and not a permanent historical archive",
            "returns use bar opens and are not executable fills; slippage and bid-ask spread are excluded",
            "abnormal return is the simple stock return minus synchronous HSI return, not a fitted market model",
            "events with source_timestamp_proxy are historical timing proxies rather than observed live availability",
            "same cluster documents share one market reaction and are not independent observations",
        ],
        "production_database_modified": False,
    }
    (args.output_dir / "coverage.json").write_text(
        json.dumps(coverage, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return coverage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--financial-db", type=Path, default=default_financial_db())
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/hkex_event_study_yfinance"))
    parser.add_argument(
        "--top-tickers",
        type=int,
        default=0,
        help="restrict to the tickers with the most events; 0 means the full event universe",
    )
    parser.add_argument(
        "--candidate-inventory",
        type=Path,
        help="optional exploratory filing inventory; only PIT-complete non-composite named families are added",
    )
    parser.add_argument("--period-5m", default="60d")
    parser.add_argument("--period-1h", default="2y")
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        help="read manifest-backed normalized yfinance bars instead of downloading live data",
    )
    parser.add_argument(
        "--capture-id",
        help="replay one manifest capture instead of merging all archive captures",
    )
    parser.add_argument(
        "--allow-live-fallback",
        action="store_true",
        help="explicitly allow yfinance live bars to fill archive gaps; disables strict reproducibility",
    )
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), indent=2, ensure_ascii=False, default=str))
