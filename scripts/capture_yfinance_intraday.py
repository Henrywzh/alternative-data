"""Capture append-only yfinance intraday snapshots for the HKEX event study.

This is a local research archive, not a production market-data database.  Each
run writes a new capture directory containing normalized Parquet bars and adds
one provenance entry to a manifest.  The source is intentionally limited to
yfinance and the supported intervals are 5m, 1h, and 1d.

NOTE: the 1d interval is canonical in the sibling ``financial-data`` DuckDB
(``market_data_bars``, 2016-01-04+, imported from the legacy research archives
and extended to the full HSCI universe).  Prefer
``financial-data run-market-data-bars --include-hsci`` for daily bars; the 1d
lane here is kept only as an offline/emergency fallback, while 5m/1h remain
this archive's responsibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


SUPPORTED_INTERVALS = ("5m", "1h", "1d")
DEFAULT_CAPTURE_INTERVALS = ("5m", "1h")
MANIFEST_VERSION = "yfinance_snapshot_archive.v1"
DEFAULT_MIN_SYMBOL_COVERAGE = 0.90


def default_output_root() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "raw" / "market_data" / "yfinance"


def default_financial_db() -> Path:
    return Path(__file__).resolve().parents[2] / "financial-data" / "data" / "databases" / "hk_financials.duckdb"


def resolve_event_universe(
    financial_db: Path,
    *,
    top_tickers: int = 0,
    benchmark: str = "^HSI",
) -> list[str]:
    """Resolve the current canonical event universe without writing to it."""
    if top_tickers < 0:
        raise ValueError("top_tickers must be non-negative; zero means all")
    import duckdb

    with duckdb.connect(str(financial_db), read_only=True) as connection:
        counts = connection.execute(
            """
            SELECT ticker, COUNT(*) AS event_rows
            FROM hkex_announcement_events
            WHERE ticker IS NOT NULL AND available_at IS NOT NULL
            GROUP BY ticker
            ORDER BY event_rows DESC, ticker
            """
        ).fetchall()
    if not counts:
        raise ValueError("canonical hkex_announcement_events has no available tickers")
    tickers = [str(ticker) for ticker, _ in counts]
    if top_tickers:
        tickers = tickers[:top_tickers]
    if benchmark and benchmark not in tickers:
        tickers.append(benchmark)
    return tickers


def _as_utc(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _field_series(frame: pd.DataFrame, ticker: str, field: str) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype="float64")
    if isinstance(frame.columns, pd.MultiIndex):
        candidates = ((ticker, field), (field, ticker))
        column = next((candidate for candidate in candidates if candidate in frame.columns), None)
        if column is None:
            return pd.Series(dtype="float64")
        series = frame[column]
    elif field in frame.columns:
        series = frame[field]
    else:
        return pd.Series(dtype="float64")
    index = pd.to_datetime(series.index, errors="coerce", utc=True)
    series = pd.to_numeric(series, errors="coerce")
    series.index = index
    return series.loc[~series.index.isna()].groupby(level=0).last().sort_index()


def normalize_yfinance_download(
    frame: pd.DataFrame,
    symbols: Iterable[str],
    *,
    interval: str,
    captured_at: object,
) -> pd.DataFrame:
    """Convert yfinance's wide/MultiIndex response into a stable long schema."""
    if interval not in SUPPORTED_INTERVALS:
        raise ValueError(f"unsupported interval: {interval}")
    captured = _as_utc(captured_at)
    rows: list[pd.DataFrame] = []
    for ticker in dict.fromkeys(str(symbol) for symbol in symbols):
        fields = {
            "open": _field_series(frame, ticker, "Open"),
            "high": _field_series(frame, ticker, "High"),
            "low": _field_series(frame, ticker, "Low"),
            "close": _field_series(frame, ticker, "Close"),
            "adj_close": _field_series(frame, ticker, "Adj Close"),
            "volume": _field_series(frame, ticker, "Volume"),
        }
        available = [series for series in fields.values() if not series.empty]
        if not available:
            continue
        index = available[0].index
        for series in available[1:]:
            index = index.union(series.index)
        table = pd.DataFrame({name: series.reindex(index) for name, series in fields.items()})
        table = table.dropna(subset=["open", "close"]).reset_index(names="timestamp_utc")
        if table.empty:
            continue
        table.insert(0, "ticker", ticker)
        table.insert(1, "interval", interval)
        table["captured_at"] = captured
        rows.append(table)
    if not rows:
        return pd.DataFrame(
            columns=[
                "ticker", "interval", "timestamp_utc", "open", "high", "low",
                "close", "adj_close", "volume", "captured_at",
            ]
        )
    result = pd.concat(rows, ignore_index=True)
    return validate_snapshot_frame(result)


def validate_snapshot_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "ticker", "interval", "timestamp_utc", "open", "high", "low",
        "close", "adj_close", "volume", "captured_at",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"snapshot missing columns: {sorted(missing)}")
    result = frame.copy()
    result["timestamp_utc"] = pd.to_datetime(result["timestamp_utc"], errors="coerce", utc=True)
    result["captured_at"] = pd.to_datetime(result["captured_at"], errors="coerce", utc=True)
    if result["timestamp_utc"].isna().any() or result["captured_at"].isna().any():
        raise ValueError("snapshot timestamps must be valid UTC timestamps")
    if not result["interval"].isin(SUPPORTED_INTERVALS).all():
        raise ValueError("snapshot contains an unsupported interval")
    if result.duplicated(["ticker", "interval", "timestamp_utc"]).any():
        raise ValueError("snapshot primary key is not unique")
    for column in ("open", "high", "low", "close"):
        values = pd.to_numeric(result[column], errors="coerce")
        if values.isna().any() or (values <= 0).any():
            raise ValueError(f"snapshot {column} values must be positive")
        result[column] = values
    result["adj_close"] = pd.to_numeric(result["adj_close"], errors="coerce")
    result["volume"] = pd.to_numeric(result["volume"], errors="coerce")
    if result["volume"].notna().any() and (result.loc[result["volume"].notna(), "volume"] < 0).any():
        raise ValueError("snapshot volume cannot be negative")
    return result.sort_values(["interval", "ticker", "timestamp_utc"]).reset_index(drop=True)


def validate_capture_coverage(
    frame: pd.DataFrame,
    requested_symbols: Iterable[str],
    intervals: Iterable[str],
    *,
    benchmark: str | None = "^HSI",
    min_symbol_coverage: float = DEFAULT_MIN_SYMBOL_COVERAGE,
) -> dict[str, dict[str, object]]:
    """Require benchmark coverage and a minimum per-interval symbol ratio."""
    if not 0 < min_symbol_coverage <= 1:
        raise ValueError("min_symbol_coverage must be in (0, 1]")
    requested = sorted(set(str(symbol) for symbol in requested_symbols))
    result: dict[str, dict[str, object]] = {}
    for interval in intervals:
        captured = sorted(
            set(frame.loc[frame["interval"].eq(interval), "ticker"].astype(str))
        ) if not frame.empty else []
        coverage = len(set(captured).intersection(requested)) / len(requested) if requested else 0.0
        if benchmark and benchmark not in captured:
            raise ValueError(f"benchmark {benchmark} missing from {interval} capture")
        if coverage < min_symbol_coverage:
            raise ValueError(
                f"{interval} symbol coverage {coverage:.1%} below minimum "
                f"{min_symbol_coverage:.1%}"
            )
        result[interval] = {
            "requested_symbols": requested,
            "captured_symbols": captured,
            "coverage_ratio": coverage,
        }
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": MANIFEST_VERSION, "captures": []}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != MANIFEST_VERSION:
        raise ValueError(f"unsupported manifest version: {manifest.get('version')}")
    if not isinstance(manifest.get("captures"), list):
        raise ValueError("manifest captures must be a list")
    return manifest


def _interval_symbol_coverage(
    output_root: Path,
    interval_info: dict[str, object],
) -> dict[str, dict[str, object]]:
    """Read per-symbol coverage, falling back for pre-v1.1 manifest entries."""
    coverage = interval_info.get("symbol_coverage")
    if isinstance(coverage, dict) and coverage:
        return coverage
    path = output_root / str(interval_info["path"])
    if not path.exists():
        return {}
    frame = pd.read_parquet(path, columns=["ticker", "timestamp_utc"])
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], errors="coerce", utc=True)
    return {
        str(ticker): {
            "rows": int(group.shape[0]),
            "earliest_utc": group["timestamp_utc"].min().isoformat(),
            "latest_utc": group["timestamp_utc"].max().isoformat(),
        }
        for ticker, group in frame.dropna(subset=["timestamp_utc"]).groupby("ticker", sort=True)
    }


def audit_snapshot_archive(
    output_root: Path,
    *,
    requested_symbols: Iterable[str] | None = None,
    intervals: Iterable[str] = DEFAULT_CAPTURE_INTERVALS,
    benchmark: str | None = "^HSI",
    as_of: object | None = None,
    max_capture_age_hours: float = 30.0,
    max_capture_gap_hours: float = 30.0,
    max_bar_lag_hours: dict[str, float] | None = None,
) -> dict[str, object]:
    """Audit append-only captures without changing the archive or production DB.

    The audit is deliberately relative to the archive's latest bar.  This makes
    stale-symbol detection useful even when the wall clock is outside HKEX
    trading hours or on a weekend.  ``as_of`` is used only for capture-age
    reporting, not for pretending that a market bar should exist while closed.
    """
    if max_capture_age_hours <= 0 or max_capture_gap_hours <= 0:
        raise ValueError("capture age and gap thresholds must be positive")
    selected_intervals = list(dict.fromkeys(str(interval) for interval in intervals))
    invalid = set(selected_intervals).difference(SUPPORTED_INTERVALS)
    if invalid:
        raise ValueError(f"unsupported intervals: {sorted(invalid)}")
    root = Path(output_root)
    manifest_path = root / "manifest.json"
    manifest = _read_manifest(manifest_path)
    as_of_utc = _as_utc(as_of or datetime.now(timezone.utc))
    bar_lag_limits = {"5m": 6.0, "1h": 24.0, "1d": 120.0}
    if max_bar_lag_hours:
        bar_lag_limits.update({str(key): float(value) for key, value in max_bar_lag_hours.items()})
    if any(value <= 0 for value in bar_lag_limits.values()):
        raise ValueError("bar lag thresholds must be positive")

    manifest_symbols: set[str] = set()
    for capture in manifest["captures"]:
        request = capture.get("request") or {}
        manifest_symbols.update(str(symbol) for symbol in request.get("symbols", []))
        for info in (capture.get("intervals") or {}).values():
            manifest_symbols.update(str(symbol) for symbol in (info or {}).get("requested_symbols", []))
    symbols = sorted(set(str(symbol) for symbol in requested_symbols)) if requested_symbols else sorted(manifest_symbols)
    if benchmark and benchmark not in symbols:
        symbols.append(benchmark)
        symbols.sort()

    interval_reports: dict[str, object] = {}
    all_integrity_errors: list[str] = []
    for interval in selected_intervals:
        entries = [
            capture
            for capture in manifest["captures"]
            if interval in (capture.get("intervals") or {})
        ]
        entries.sort(key=lambda capture: str(capture.get("captured_at", "")))
        capture_times = pd.to_datetime(
            [capture.get("captured_at") for capture in entries], errors="coerce", utc=True
        ).dropna()
        capture_gaps = capture_times.to_series().sort_values().diff().dropna().dt.total_seconds().div(3600)
        symbol_stats: dict[str, dict[str, object]] = {
            symbol: {"rows": 0, "earliest_utc": None, "latest_utc": None, "latest_capture_at": None}
            for symbol in symbols
        }
        integrity_errors: list[str] = []
        capture_records: list[dict[str, object]] = []
        for capture in entries:
            info = (capture.get("intervals") or {}).get(interval) or {}
            path = root / str(info.get("path", ""))
            if not path.exists():
                integrity_errors.append(f"missing_file:{path}")
                continue
            expected_hash = info.get("sha256")
            if expected_hash and _sha256(path) != expected_hash:
                integrity_errors.append(f"sha256_mismatch:{path}")
            coverage = _interval_symbol_coverage(root, info)
            requested_for_capture = sorted(
                set(str(symbol) for symbol in info.get("requested_symbols", []))
                or set(str(symbol) for symbol in (capture.get("request") or {}).get("symbols", []))
            )
            captured_for_capture = sorted(str(symbol) for symbol in coverage)
            capture_records.append(
                {
                    "capture_id": capture.get("capture_id"),
                    "captured_at": capture.get("captured_at"),
                    "requested_symbol_count": len(requested_for_capture),
                    "captured_symbol_count": len(captured_for_capture),
                    "coverage_ratio": (
                        len(set(captured_for_capture).intersection(requested_for_capture))
                        / len(requested_for_capture)
                        if requested_for_capture else None
                    ),
                    "rows": int(info.get("rows", 0)),
                    "earliest_bar_utc": info.get("earliest_utc"),
                    "latest_bar_utc": info.get("latest_utc"),
                }
            )
            for ticker, values in coverage.items():
                if ticker not in symbol_stats:
                    continue
                stat = symbol_stats[ticker]
                stat["rows"] = int(stat["rows"]) + int(values.get("rows", 0))
                earliest = values.get("earliest_utc")
                latest = values.get("latest_utc")
                if earliest and (stat["earliest_utc"] is None or earliest < stat["earliest_utc"]):
                    stat["earliest_utc"] = earliest
                if latest and (stat["latest_utc"] is None or latest > stat["latest_utc"]):
                    stat["latest_utc"] = latest
                    stat["latest_capture_at"] = capture.get("captured_at")
        all_integrity_errors.extend(integrity_errors)

        latest_values = [
            pd.Timestamp(stat["latest_utc"])
            for stat in symbol_stats.values()
            if stat["latest_utc"]
        ]
        reference_latest = max(latest_values).isoformat() if latest_values else None
        reference_timestamp = max(latest_values) if latest_values else None
        missing_symbols = [symbol for symbol, stat in symbol_stats.items() if stat["latest_utc"] is None]
        stale_symbols: list[str] = []
        for symbol, stat in symbol_stats.items():
            if not stat["latest_utc"] or reference_timestamp is None:
                continue
            lag_hours = (reference_timestamp - pd.Timestamp(stat["latest_utc"])).total_seconds() / 3600
            stat["bar_lag_hours_vs_reference"] = round(max(0.0, lag_hours), 3)
            if lag_hours > bar_lag_limits[interval]:
                stale_symbols.append(symbol)
        latest_capture = capture_times.max().isoformat() if len(capture_times) else None
        capture_age = (
            (as_of_utc - capture_times.max()).total_seconds() / 3600
            if len(capture_times) else None
        )
        coverage_ratio = (
            (len(symbols) - len(missing_symbols)) / len(symbols)
            if symbols else 0.0
        )
        cutoff_values = [
            _as_utc(record["latest_bar_utc"]).isoformat()
            for record in capture_records
            if record["latest_bar_utc"]
        ]
        unique_cutoffs = sorted(set(cutoff_values))
        if len(entries) < 2:
            cutoff_status = "insufficient_captures"
        elif len(unique_cutoffs) < 2:
            cutoff_status = "non_independent_same_market_cutoff"
        else:
            cutoff_status = "distinct_market_cutoffs_present"
        interval_status = "ok"
        if not entries or missing_symbols or stale_symbols or integrity_errors:
            interval_status = "degraded"
        interval_reports[interval] = {
            "status": interval_status,
            "capture_count": len(entries),
            "latest_capture_at": latest_capture,
            "capture_age_hours": None if capture_age is None else round(max(0.0, capture_age), 3),
            "capture_age_status": (
                "unknown" if capture_age is None else
                "fresh" if capture_age <= max_capture_age_hours else "stale"
            ),
            "max_capture_gap_hours": None if capture_gaps.empty else round(float(capture_gaps.max()), 3),
            "capture_cadence_status": (
                "no_history" if capture_gaps.empty and len(entries) < 2 else
                "ok" if capture_gaps.empty or float(capture_gaps.max()) <= max_capture_gap_hours else "gapped"
            ),
            "capture_cutoff_status": cutoff_status,
            "distinct_market_cutoff_count": len(unique_cutoffs),
            "capture_records": capture_records,
            "reference_latest_bar_utc": reference_latest,
            "coverage_ratio": coverage_ratio,
            "missing_symbols": missing_symbols,
            "stale_symbols": stale_symbols,
            "bar_lag_threshold_hours": bar_lag_limits[interval],
            "integrity_errors": integrity_errors,
            "symbol_coverage": symbol_stats,
        }
    return {
        "version": "yfinance_snapshot_archive_audit.v1",
        "archive_root": str(root),
        "manifest_version": manifest.get("version"),
        "manifest_sha256": _sha256(manifest_path),
        "as_of_utc": as_of_utc.isoformat(),
        "benchmark": benchmark,
        "requested_symbols": symbols,
        "requested_symbol_count": len(symbols),
        "max_capture_age_hours": max_capture_age_hours,
        "max_capture_gap_hours": max_capture_gap_hours,
        "intervals": interval_reports,
        "integrity_error_count": len(all_integrity_errors),
        "integrity_errors": all_integrity_errors,
        "production_database_modified": False,
    }


def build_refresh_readiness(
    financial_db: Path,
    output_root: Path,
    *,
    intervals: Iterable[str] = DEFAULT_CAPTURE_INTERVALS,
    top_tickers: int = 0,
    benchmark: str = "^HSI",
) -> dict[str, object]:
    """Check the existing archive against today's canonical event universe."""
    symbols = resolve_event_universe(
        financial_db,
        top_tickers=top_tickers,
        benchmark=benchmark,
    )
    audit = audit_snapshot_archive(
        output_root,
        requested_symbols=symbols,
        intervals=intervals,
        benchmark=benchmark,
    )
    reasons: list[str] = []
    for interval, report in audit["intervals"].items():
        if report["missing_symbols"]:
            reasons.append(f"{interval}_missing_current_event_symbols")
        if report["stale_symbols"]:
            reasons.append(f"{interval}_stale_symbols")
        if report["integrity_errors"]:
            reasons.append(f"{interval}_integrity_errors")
    return {
        "version": "yfinance_snapshot_refresh_readiness.v1",
        "financial_db": str(financial_db),
        "archive_root": str(output_root),
        "event_universe_count": len(symbols),
        "event_universe_symbols": symbols,
        "status": "needs_capture" if reasons else "archive_coverage_ready",
        "reasons": reasons,
        "archive_audit": audit,
        "production_database_modified": False,
    }


def write_snapshot(
    frame: pd.DataFrame,
    output_root: Path,
    *,
    captured_at: object,
    capture_id: str | None = None,
    request: dict[str, object] | None = None,
) -> dict[str, object]:
    """Write one immutable capture and atomically update the manifest."""
    frame = validate_snapshot_frame(frame)
    if frame.empty:
        raise ValueError("refusing to archive an empty yfinance capture")
    captured = _as_utc(captured_at)
    capture_id = capture_id or captured.strftime("%Y%m%dT%H%M%SZ")
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "manifest.json"
    manifest = _read_manifest(manifest_path)
    if any(entry.get("capture_id") == capture_id for entry in manifest["captures"]):
        raise FileExistsError(f"capture_id already exists: {capture_id}")
    capture_dir = output_root / capture_id
    if capture_dir.exists():
        raise FileExistsError(f"capture directory already exists: {capture_dir}")
    capture_dir.mkdir(parents=True)
    interval_entries: dict[str, object] = {}
    try:
        for interval, group in frame.groupby("interval", sort=True):
            path = capture_dir / f"bars_{interval}.parquet"
            group.to_parquet(path, index=False)
            requested_symbols = sorted(
                set(str(symbol) for symbol in (request or {}).get("symbols", []))
            )
            captured_symbols = sorted(group["ticker"].astype(str).unique().tolist())
            symbol_coverage = {
                ticker: {
                    "rows": int(symbol_group.shape[0]),
                    "earliest_utc": symbol_group["timestamp_utc"].min().isoformat(),
                    "latest_utc": symbol_group["timestamp_utc"].max().isoformat(),
                }
                for ticker, symbol_group in group.groupby("ticker", sort=True)
            }
            coverage_ratio = (
                len(set(captured_symbols).intersection(requested_symbols)) / len(requested_symbols)
                if requested_symbols else None
            )
            interval_entries[interval] = {
                "path": str(path.relative_to(output_root)),
                "rows": int(len(group)),
                "symbols": captured_symbols,
                "requested_symbols": requested_symbols,
                "captured_symbols": captured_symbols,
                "coverage_ratio": coverage_ratio,
                "symbol_coverage": symbol_coverage,
                "earliest_utc": group["timestamp_utc"].min().isoformat(),
                "latest_utc": group["timestamp_utc"].max().isoformat(),
                "sha256": _sha256(path),
            }
        entry = {
            "capture_id": capture_id,
            "captured_at": captured.isoformat(),
            "request": request or {},
            "intervals": interval_entries,
        }
        manifest["captures"].append(entry)
        temporary_manifest = manifest_path.with_suffix(".json.tmp")
        temporary_manifest.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        temporary_manifest.replace(manifest_path)
    except Exception:
        for child in capture_dir.glob("*"):
            child.unlink()
        capture_dir.rmdir()
        raise
    entry["manifest_sha256"] = _sha256(manifest_path)
    return entry


def fetch_and_write_snapshot(
    symbols: Iterable[str],
    *,
    intervals: Iterable[str],
    period_5m: str = "60d",
    period_1h: str = "2y",
    period_1d: str = "5y",
    output_root: Path,
    capture_id: str | None = None,
    captured_at: object | None = None,
    benchmark: str | None = "^HSI",
    min_symbol_coverage: float = DEFAULT_MIN_SYMBOL_COVERAGE,
) -> dict[str, object]:
    import yfinance as yf

    symbols = list(dict.fromkeys(str(symbol) for symbol in symbols))
    if not symbols:
        raise ValueError("at least one symbol is required")
    intervals = list(dict.fromkeys(intervals))
    invalid = set(intervals).difference(SUPPORTED_INTERVALS)
    if invalid:
        raise ValueError(f"unsupported intervals: {sorted(invalid)}")
    captured = _as_utc(captured_at or datetime.now(timezone.utc))
    frames: list[pd.DataFrame] = []
    for interval in intervals:
        if interval == "5m":
            period = period_5m
        elif interval == "1h":
            period = period_1h
        elif interval == "1d":
            period = period_1d
        else:
            period = "5y"
        raw = yf.download(
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
        frames.append(normalize_yfinance_download(raw, symbols, interval=interval, captured_at=captured))
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    coverage = validate_capture_coverage(
        frame,
        symbols,
        intervals,
        benchmark=benchmark,
        min_symbol_coverage=min_symbol_coverage,
    )
    return write_snapshot(
        frame,
        output_root,
        captured_at=captured,
        capture_id=capture_id,
        request={
            "source": "yfinance",
            "symbols": symbols,
            "intervals": intervals,
            "period_5m": period_5m,
            "period_1h": period_1h,
            "period_1d": period_1d,
            "benchmark": benchmark,
            "min_symbol_coverage": min_symbol_coverage,
            "coverage": coverage,
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+")
    parser.add_argument(
        "--from-event-universe",
        action="store_true",
        help="read tickers from canonical hkex_announcement_events instead of listing them",
    )
    parser.add_argument("--financial-db", type=Path, default=default_financial_db())
    parser.add_argument("--top-tickers", type=int, default=0, help="event-universe size; zero means all")
    parser.add_argument(
        "--audit",
        action="store_true",
        help="audit the existing append-only archive instead of downloading bars",
    )
    parser.add_argument(
        "--readiness",
        action="store_true",
        help="check the archive against the current canonical event universe without downloading",
    )
    parser.add_argument(
        "--intervals",
        nargs="+",
        choices=SUPPORTED_INTERVALS,
        default=list(DEFAULT_CAPTURE_INTERVALS),
    )
    parser.add_argument("--period-5m", default="60d")
    parser.add_argument("--period-1h", default="2y")
    parser.add_argument("--period-1d", default="5y", help="daily period for yfinance download")
    parser.add_argument("--output-root", type=Path, default=default_output_root())
    parser.add_argument("--capture-id")
    parser.add_argument("--benchmark", default="^HSI")
    parser.add_argument("--min-symbol-coverage", type=float, default=DEFAULT_MIN_SYMBOL_COVERAGE)
    parser.add_argument("--as-of", help="UTC timestamp used for capture-age reporting in --audit")
    parser.add_argument("--max-capture-age-hours", type=float, default=30.0)
    parser.add_argument("--max-capture-gap-hours", type=float, default=30.0)
    parser.add_argument("--audit-output", type=Path)
    parser.add_argument("--readiness-output", type=Path)
    parser.add_argument(
        "--audit-after",
        action="store_true",
        help="run archive audit and write archive_audit.json after a successful capture",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.readiness:
        result = build_refresh_readiness(
            args.financial_db,
            args.output_root,
            intervals=args.intervals,
            top_tickers=args.top_tickers,
            benchmark=args.benchmark,
        )
        readiness_path = args.readiness_output or (args.output_root / "refresh_readiness.json")
        readiness_path.parent.mkdir(parents=True, exist_ok=True)
        readiness_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        raise SystemExit(0)
    if args.audit:
        result = audit_snapshot_archive(
            args.output_root,
            requested_symbols=args.tickers,
            intervals=args.intervals,
            benchmark=args.benchmark,
            as_of=args.as_of,
            max_capture_age_hours=args.max_capture_age_hours,
            max_capture_gap_hours=args.max_capture_gap_hours,
        )
        audit_path = args.audit_output or (args.output_root / "archive_audit.json")
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        raise SystemExit(0)
    if args.from_event_universe and args.tickers:
        raise SystemExit("use either --tickers or --from-event-universe, not both")
    if args.from_event_universe:
        symbols = resolve_event_universe(
            args.financial_db,
            top_tickers=args.top_tickers,
            benchmark=args.benchmark,
        )
    elif args.tickers:
        symbols = args.tickers
    else:
        raise SystemExit("--tickers or --from-event-universe is required unless --audit is used")
    result = fetch_and_write_snapshot(
        symbols,
        intervals=args.intervals,
        period_5m=args.period_5m,
        period_1h=args.period_1h,
        period_1d=args.period_1d,
        output_root=args.output_root,
        capture_id=args.capture_id,
        benchmark=args.benchmark,
        min_symbol_coverage=args.min_symbol_coverage,
    )
    if args.audit_after:
        audit = audit_snapshot_archive(
            args.output_root,
            requested_symbols=symbols,
            intervals=args.intervals,
            benchmark=args.benchmark,
        )
        audit_path = args.audit_output or (args.output_root / "archive_audit.json")
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(
            json.dumps(audit, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        result["archive_audit"] = audit
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
