"""Compare HKEX event-study replays across manifest-backed yfinance captures.

This is a research audit utility.  It replays the same event universe against
selected immutable captures, compares event-level returns, and explicitly
distinguishes same-cutoff replay consistency from independent market-cutoff
robustness.  It never writes to the financial-data database.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
from pathlib import Path

import pandas as pd


def _load_study_module():
    path = Path(__file__).with_name("run_hkex_event_study_yfinance.py")
    spec = importlib.util.spec_from_file_location("hkex_event_study_yfinance", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load event-study module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest_capture_metadata(snapshot_root: Path) -> dict[str, dict[str, object]]:
    manifest = json.loads((snapshot_root / "manifest.json").read_text(encoding="utf-8"))
    return {
        str(capture["capture_id"]): capture
        for capture in manifest.get("captures", [])
        if capture.get("capture_id")
    }


def _cutoff_key(value: object) -> str | None:
    """Normalize cutoff labels before comparing captures across serializers."""
    if value is None or str(value).strip() in {"", "None", "NaT"}:
        return None
    timestamp = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(timestamp):
        return None
    return timestamp.isoformat()


def compare_event_frames(left: pd.DataFrame, right: pd.DataFrame) -> dict[str, object]:
    """Compare event-level coverage and return columns at the same event grain."""
    left = left.set_index("event_id").sort_index()
    right = right.set_index("event_id").sort_index()
    common = left.index.intersection(right.index)
    return_columns = [
        "5m_return", "30m_return", "1h_return",
        "5m_abnormal_return", "30m_abnormal_return", "1h_abnormal_return",
        "native_1h_return", "native_1h_abnormal_return",
    ]
    equal_counts: dict[str, int] = {}
    max_abs_differences: dict[str, float | None] = {}
    for column in return_columns:
        if column not in left or column not in right:
            continue
        left_values = pd.to_numeric(left.loc[common, column], errors="coerce")
        right_values = pd.to_numeric(right.loc[common, column], errors="coerce")
        both_missing = left_values.isna() & right_values.isna()
        differences = (left_values - right_values).abs()
        equal_counts[column] = int((both_missing | differences.eq(0)).sum())
        max_abs_differences[column] = None if differences.dropna().empty else float(differences.max())
    coverage_columns = ["market_data_status", "native_1h_status", "bar_hole_horizons"]
    coverage_equal_counts: dict[str, int] = {}
    for column in coverage_columns:
        if column not in left or column not in right:
            continue
        left_values = left.loc[common, column].fillna("__MISSING__").astype(str)
        right_values = right.loc[common, column].fillna("__MISSING__").astype(str)
        coverage_equal_counts[column] = int(left_values.eq(right_values).sum())
    compared_fields = len(equal_counts) + len(coverage_equal_counts)
    return {
        "left_event_rows": int(len(left)),
        "right_event_rows": int(len(right)),
        "common_event_rows": int(len(common)),
        "event_overlap_rate_left": None if left.empty else float(len(common) / len(left)),
        "event_overlap_rate_right": None if right.empty else float(len(common) / len(right)),
        "return_equal_rows": equal_counts,
        "return_max_abs_differences": max_abs_differences,
        "coverage_equal_rows": coverage_equal_counts,
        "exact_replay_consistent": bool(
            len(common) == len(left) == len(right)
            and compared_fields > 0
            and all(value == len(common) for value in equal_counts.values())
            and all(value == len(common) for value in coverage_equal_counts.values())
        ),
    }


def compare_captures(
    *,
    financial_db: Path,
    snapshot_root: Path,
    output_dir: Path,
    top_tickers: int,
    capture_ids: list[str] | None = None,
) -> dict[str, object]:
    study = _load_study_module()
    audit = study.load_archive_audit(snapshot_root)
    if audit is None:
        raise ValueError("archive_audit.json is required for capture comparison")
    metadata = _manifest_capture_metadata(snapshot_root)
    selected = capture_ids or sorted(metadata)
    missing = sorted(set(selected).difference(metadata))
    if missing:
        raise ValueError(f"capture_id not found in archive manifest: {missing}")
    output_dir.mkdir(parents=True, exist_ok=True)
    replays: list[dict[str, object]] = []
    frames: dict[str, pd.DataFrame] = {}
    for capture_id in selected:
        capture_output = output_dir / capture_id
        args = argparse.Namespace(
            financial_db=financial_db,
            output_dir=capture_output,
            top_tickers=top_tickers,
            period_5m="60d",
            period_1h="2y",
            snapshot_root=snapshot_root,
            allow_live_fallback=False,
            capture_id=capture_id,
        )
        try:
            coverage = study.run(args)
            frame = pd.read_csv(capture_output / "event_returns.csv")
            frames[capture_id] = frame
            replays.append(
                {
                    "capture_id": capture_id,
                    "status": "ok",
                    "captured_at": metadata[capture_id].get("captured_at"),
                    "event_rows": coverage["event_rows"],
                    "event_clusters": coverage["event_clusters"],
                    "market_cutoff_5m": metadata[capture_id].get("intervals", {}).get("5m", {}).get("latest_utc"),
                    "market_cutoff_1h": metadata[capture_id].get("intervals", {}).get("1h", {}).get("latest_utc"),
                }
            )
        except Exception as exc:  # report a capture-specific failure without hiding others
            replays.append({"capture_id": capture_id, "status": "error", "error": str(exc)})

    pairs: list[dict[str, object]] = []
    for left_id, right_id in itertools.combinations(frames, 2):
        left_meta = metadata[left_id]
        right_meta = metadata[right_id]
        left_cutoff = left_meta.get("intervals", {}).get("5m", {}).get("latest_utc")
        right_cutoff = right_meta.get("intervals", {}).get("5m", {}).get("latest_utc")
        left_cutoff_1h = left_meta.get("intervals", {}).get("1h", {}).get("latest_utc")
        right_cutoff_1h = right_meta.get("intervals", {}).get("1h", {}).get("latest_utc")
        comparison = compare_event_frames(frames[left_id], frames[right_id])
        five_min_distinct = _cutoff_key(left_cutoff) != _cutoff_key(right_cutoff)
        one_hour_distinct = _cutoff_key(left_cutoff_1h) != _cutoff_key(right_cutoff_1h)
        cutoff_status = (
            "distinct_both_intervals"
            if five_min_distinct and one_hour_distinct
            else "partial_interval_difference"
            if five_min_distinct or one_hour_distinct
            else "same"
        )
        pairs.append(
            {
                "left_capture_id": left_id,
                "right_capture_id": right_id,
                "market_cutoff_status": cutoff_status,
                "left_market_cutoff_5m": left_cutoff,
                "right_market_cutoff_5m": right_cutoff,
                "left_market_cutoff_1h": left_cutoff_1h,
                "right_market_cutoff_1h": right_cutoff_1h,
                **comparison,
            }
        )
    distinct_pairs = sum(pair["market_cutoff_status"] == "distinct_both_intervals" for pair in pairs)
    partial_pairs = sum(pair["market_cutoff_status"] == "partial_interval_difference" for pair in pairs)
    result = {
        "version": "hkex_event_study_capture_comparison.v1",
        "top_tickers": top_tickers,
        "selected_capture_ids": selected,
        "replays": replays,
        "pairs": pairs,
        "pair_count": len(pairs),
        "distinct_market_cutoff_pair_count": int(distinct_pairs),
        "partial_market_cutoff_pair_count": int(partial_pairs),
        "robustness_status": (
            "insufficient_distinct_market_cutoffs"
            if distinct_pairs == 0
            else "distinct_cutoff_comparison_available"
        ),
        "archive_audit_manifest_sha256": audit.get("manifest_sha256"),
        "production_database_modified": False,
    }
    (output_dir / "comparison.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--financial-db", type=Path, default=Path(__file__).resolve().parents[2] / "financial-data" / "data" / "databases" / "hk_financials.duckdb")
    parser.add_argument("--snapshot-root", type=Path, default=Path("data/raw/market_data/yfinance"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/hkex_event_study_capture_comparison"))
    parser.add_argument("--top-tickers", type=int, default=30)
    parser.add_argument("--capture-ids", nargs="+")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(compare_captures(**vars(parse_args())), indent=2, ensure_ascii=False, default=str))
