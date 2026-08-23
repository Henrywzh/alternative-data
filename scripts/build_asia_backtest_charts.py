#!/usr/bin/env python3
"""Render the four default chart views for the unified KPI backtest engine.

This is the only file in the visualization layer allowed to import
matplotlib. ``src/common/backtest/views.py`` reshapes the published
artifacts into chart-ready DataFrames; this script turns those frames into
PNGs. It never computes a metric itself -- every number on a chart traces
back to ``asia_backtest_long_form`` / ``asia_backtest_metrics`` /
``asia_backtest_metric_intervals`` via ``views.py``.

Reads (read-only):
  data/registries/asia_backtest_long_form.{parquet,csv}
  data/registries/asia_backtest_metrics.{parquet,csv}
  data/registries/asia_backtest_metric_intervals.{parquet,csv}
  data/registries/asia_backtest_latest.json

Writes:
  data/registries/runs/<run_id>/charts/<view>/<slug>.png

Chart PNGs are versioned with the run directory referenced by the current
``asia_backtest_latest.json`` pointer, matching the run-directory convention
in ``src/common/backtest/storage.py``. This script never writes into the
top-level ``data/registries/`` artifacts and never invokes the engine
(``scripts/run_backtest_engine.py``) or any other ``build_asia_backtest_*``
script -- it only reads what they have already published.

Usage:
  python3 scripts/build_asia_backtest_charts.py --all
  python3 scripts/build_asia_backtest_charts.py --view model_leaderboard \\
      --target attributable_profit --track fiscal_year
  python3 scripts/build_asia_backtest_charts.py --view sequential_actual_vs_pred \\
      --entity "Air China" --target revenue --track half_year_non_overlapping
  python3 scripts/build_asia_backtest_charts.py --registry-id \\
      "airline_h1_kpi_backtest:H1:revenue:flat_ask_v1" --entity "Air China"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.backtest import views as v  # noqa: E402

def _registry_dir() -> Path:
    """The backtest registry directory, overridable for tests.

    build_registry() and build_long_form() write their outputs here as part of
    building, so a test that only wants the returned frame still rewrote the
    tracked files -- and their manifests carry a build timestamp, so every run
    showed a diff. tests/conftest.py points ASIA_BACKTEST_REGISTRY_DIR at a
    session-scoped copy, keeping reads intact while writes land outside the
    repository.
    """
    override = os.environ.get("ASIA_BACKTEST_REGISTRY_DIR", "").strip()
    return Path(override) if override else ROOT / "data" / "registries"


REGISTRY_DIR = _registry_dir()
LONG_FORM_PARQUET = REGISTRY_DIR / "asia_backtest_long_form.parquet"
LONG_FORM_CSV = REGISTRY_DIR / "asia_backtest_long_form.csv"
METRICS_PARQUET = REGISTRY_DIR / "asia_backtest_metrics.parquet"
METRICS_CSV = REGISTRY_DIR / "asia_backtest_metrics.csv"
INTERVALS_PARQUET = REGISTRY_DIR / "asia_backtest_metric_intervals.parquet"
INTERVALS_CSV = REGISTRY_DIR / "asia_backtest_metric_intervals.csv"
LATEST_POINTER = REGISTRY_DIR / "asia_backtest_latest.json"

# Deterministic, small-footprint output: fixed size/DPI, no timestamps in the
# image or filenames. See docs/asia-markets/unified-kpi-backtest-v1.md's run
# directory retention section -- a previous round of work pruned 188MB of
# accumulated run artifacts, so chart images stay intentionally modest.
DPI = 100
FIGSIZE = (8.0, 4.5)
LEADERBOARD_FIGSIZE = (8.0, 5.5)
PNG_METADATA = {"Software": "asia_backtest_charts"}

VIEW_CHOICES = (
    "sequential_actual_vs_pred",
    "error_over_time",
    "model_leaderboard",
    "coverage_grade_strip",
)

FORECAST_MARKER_KWARGS = {"marker": "o", "facecolors": "none", "s": 46, "linewidths": 1.6, "zorder": 5}
ACTUAL_LINE_KWARGS = {"linewidth": 2.2, "color": "#1a1a1a", "marker": "o", "markersize": 4.5}


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _read(parquet_path: Path, csv_path: Path) -> pd.DataFrame:
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    if csv_path.exists():
        return pd.read_csv(csv_path, low_memory=False)
    raise FileNotFoundError(f"missing artifact: {parquet_path} (or {csv_path})")


def load_artifacts() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    long_form = _read(LONG_FORM_PARQUET, LONG_FORM_CSV)
    metrics = _read(METRICS_PARQUET, METRICS_CSV)
    intervals = _read(INTERVALS_PARQUET, INTERVALS_CSV)
    return long_form, metrics, intervals


def resolve_charts_dir() -> Path:
    """Return the charts directory inside the run the latest pointer names.

    Mirrors ``RunArtifactStore``'s run-directory convention
    (``data/registries/runs/<run_id>/``) so images stay versioned with the
    exact data snapshot that produced them, without writing a second,
    parallel output location.
    """
    if not LATEST_POINTER.exists():
        raise FileNotFoundError(
            f"missing latest-run pointer: {LATEST_POINTER}. Run the engine first."
        )
    pointer = json.loads(LATEST_POINTER.read_text(encoding="utf-8"))
    run_id = pointer.get("run_id")
    if not run_id:
        raise ValueError(f"latest-run pointer is missing run_id: {LATEST_POINTER}")
    run_dir = REGISTRY_DIR / "runs" / run_id
    if not run_dir.is_dir():
        raise FileNotFoundError(
            f"run directory referenced by the latest pointer does not exist: {run_dir}"
        )
    return run_dir / "charts"


def _slug(*parts: Any) -> str:
    text = "__".join(str(part) for part in parts)
    out = []
    for ch in text:
        out.append(ch if (ch.isalnum() or ch in "-_") else "_")
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_").lower()


def _save(fig: "plt.Figure", path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches="tight", metadata=PNG_METADATA)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Title/status helpers -- every chart must be interpretable standing alone
# ---------------------------------------------------------------------------

_STATUS_ABBREV = {
    "valid_headline": "OK",
    "valid_diagnostic": "diagnostic",
    "insufficient_sample": "insufficient sample",
    "insufficient_baseline_coverage": "insufficient baseline coverage",
    "diagnostic_only": "diagnostic only",
    "not_applicable": "n/a",
    "degenerate": "DEGENERATE",
    "reference_only": "reference only",
    "eligible": "eligible",
}


def _status_text(status: object) -> str:
    return _STATUS_ABBREV.get(str(status), str(status))


def _worst_status(statuses: pd.Series) -> str:
    """Pick the single most concerning status to headline a multi-series chart.

    Ranked so a degenerate/insufficient reading can never be hidden behind a
    healthier status elsewhere on the same chart.
    """
    priority = [
        "degenerate",
        "insufficient_sample",
        "insufficient_baseline_coverage",
        "diagnostic_only",
        "valid_diagnostic",
        "reference_only",
        "not_applicable",
        "eligible",
        "valid_headline",
    ]
    present = set(str(s) for s in statuses.dropna())
    for status in priority:
        if status in present:
            return status
    return "not_applicable"


def _track_label(track_id: str) -> str:
    return {
        "fiscal_year": "FY",
        "half_year_non_overlapping": "H1/H2",
        "ytd_current": "YTD (current forecast)",
        "monthly_sparse": "monthly",
    }.get(track_id, track_id)


# ---------------------------------------------------------------------------
# Renderers -- one per default view
# ---------------------------------------------------------------------------


def render_sequential_actual_vs_pred(
    frame: pd.DataFrame, *, entity_id: str, target_id: str, track_id: str
) -> plt.Figure | None:
    if frame.empty:
        return None
    order = (
        frame[["period_label", "target_period_start"]]
        .drop_duplicates()
        .sort_values("target_period_start")["period_label"]
        .tolist()
    )
    x_pos = {label: i for i, label in enumerate(order)}
    n_periods = len(order)
    worst_status = _worst_status(frame.loc[frame["series_type"] != v.SERIES_ACTUAL, "metric_status"])
    has_forecast = bool(frame["is_forecast"].any())

    fig, ax = plt.subplots(figsize=FIGSIZE)
    for series_id, series in frame.groupby("series_id", sort=True):
        series = series.sort_values("target_period_start")
        xs = [x_pos[p] for p in series["period_label"]]
        ys = series["value"].tolist()
        if series_id == v.SERIES_ACTUAL:
            ax.plot(xs, ys, label="Actual", **ACTUAL_LINE_KWARGS)
            continue
        status = _status_text(series["metric_status"].iloc[0])
        label = f"{series_id} ({status})"
        line = ax.plot(xs, ys, marker="o", markersize=4, linewidth=1.4, linestyle="--", label=label)
        color = line[0].get_color()
        forecast_pts = series[series["is_forecast"] & series["value"].notna()]
        if not forecast_pts.empty:
            fx = [x_pos[p] for p in forecast_pts["period_label"]]
            fy = forecast_pts["value"].tolist()
            ax.scatter(fx, fy, edgecolors=color, **FORECAST_MARKER_KWARGS)

    ax.set_xticks(range(n_periods))
    ax.set_xticklabels(order, rotation=45, ha="right", fontsize=8)
    ax.axhline(0, color="#cccccc", linewidth=0.8, zorder=0)
    ax.set_ylabel("value")
    forecast_note = " | includes forecast (hollow marker)" if has_forecast else ""
    ax.set_title(
        f"{entity_id} - {target_id} - {_track_label(track_id)}\n"
        f"n_periods={n_periods} | worst series status: {_status_text(worst_status)}{forecast_note}",
        fontsize=10,
    )
    ax.legend(fontsize=7, loc="best", framealpha=0.9)
    fig.tight_layout()
    return fig


def render_error_over_time(
    frame: pd.DataFrame, *, entity_id: str, target_id: str, track_id: str
) -> plt.Figure | None:
    if frame.empty:
        return None
    order = (
        frame[["period_label", "target_period_start"]]
        .drop_duplicates()
        .sort_values("target_period_start")["period_label"]
        .tolist()
    )
    x_pos = {label: i for i, label in enumerate(order)}
    n_periods = len(order)
    worst_status = _worst_status(frame["metric_status"])

    fig, ax = plt.subplots(figsize=FIGSIZE)
    for series_id, series in frame.groupby("series_id", sort=True):
        series = series.sort_values("target_period_start")
        xs = [x_pos[p] for p in series["period_label"]]
        ys = series["signed_error"].tolist()
        status = _status_text(series["metric_status"].iloc[0])
        ax.plot(xs, ys, marker="o", markersize=4, linewidth=1.4, label=f"{series_id} ({status})")

    ax.axhline(0, color="#333333", linewidth=1.0, zorder=0)
    ax.set_xticks(range(n_periods))
    ax.set_xticklabels(order, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("signed error (predicted - actual)")
    ax.set_title(
        f"{entity_id} - {target_id} - {_track_label(track_id)}\n"
        f"n_periods={n_periods} | worst series status: {_status_text(worst_status)}",
        fontsize=10,
    )
    ax.legend(fontsize=7, loc="best", framealpha=0.9)
    fig.tight_layout()
    return fig


def render_model_leaderboard(frame: pd.DataFrame, *, target_id: str, track_id: str) -> plt.Figure | None:
    if frame.empty:
        return None
    plot_frame = frame.dropna(subset=["skill_vs_baseline"]).copy()
    if plot_frame.empty:
        return None
    plot_frame["bar_label"] = plot_frame["entity_id"].astype(str) + " / " + plot_frame["model_id"].astype(str)
    plot_frame = plot_frame.sort_values(["skill_vs_baseline"], ascending=True).reset_index(drop=True)
    reference_only = bool(plot_frame["is_reference_only"].any())
    worst_status = _worst_status(plot_frame["metric_status"])

    fig, ax = plt.subplots(figsize=LEADERBOARD_FIGSIZE)
    colors = ["#c0392b" if val < 0 else "#1e8449" for val in plot_frame["skill_vs_baseline"]]
    y_pos = range(len(plot_frame))
    ax.barh(y_pos, plot_frame["skill_vs_baseline"], color=colors)
    ax.set_yticks(list(y_pos))
    labels = [
        f"{row.bar_label} [{_status_text(row.metric_status)}]" for row in plot_frame.itertuples()
    ]
    ax.set_yticklabels(labels, fontsize=7)
    ax.axvline(0, color="#333333", linewidth=1.0)
    ax.set_xlabel("skill_vs_baseline (negative = worse than same-period-last-year)")
    grain_note = " | POOLED reference only" if reference_only else " | grain: per_entity"
    ax.set_title(
        f"Model leaderboard - {target_id} - {_track_label(track_id)}\n"
        f"n={len(plot_frame)} contracts | worst status: {_status_text(worst_status)}{grain_note}",
        fontsize=10,
    )
    fig.tight_layout()
    return fig


def render_coverage_grade_strip(
    frame: pd.DataFrame, *, entity_id: str, target_id: str, track_id: str
) -> plt.Figure | None:
    if frame.empty:
        return None
    frame = frame.copy()
    frame["group"] = frame["pit_grade"].astype(str) + " / " + frame["evaluation_status"].astype(str)
    order = (
        frame[["period_label", "target_period_start"]]
        .drop_duplicates()
        .sort_values("target_period_start")["period_label"]
        .tolist()
    )
    pivot = frame.pivot_table(
        index="period_label", columns="group", values="n_rows", aggfunc="sum", fill_value=0
    ).reindex(order)
    n_periods = len(order)

    fig, ax = plt.subplots(figsize=FIGSIZE)
    bottom = pd.Series(0, index=pivot.index, dtype=float)
    for group in sorted(pivot.columns):
        values = pivot[group]
        ax.bar(range(n_periods), values, bottom=bottom, label=group)
        bottom = bottom + values
    ax.set_xticks(range(n_periods))
    ax.set_xticklabels(order, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("row count")
    ax.set_title(
        f"{entity_id} - {target_id} - {_track_label(track_id)}\n"
        f"coverage composition | n_periods={n_periods}",
        fontsize=10,
    )
    ax.legend(fontsize=6, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def render_one(
    view: str,
    *,
    long_form: pd.DataFrame,
    metrics: pd.DataFrame,
    intervals: pd.DataFrame,
    entity_id: str | None,
    target_id: str | None,
    track_id: str | None,
    charts_dir: Path,
) -> Path | None:
    if view in ("sequential_actual_vs_pred", "error_over_time", "coverage_grade_strip"):
        if not (entity_id and target_id and track_id):
            raise ValueError(f"{view} requires --entity, --target, and --track")
        if view == "sequential_actual_vs_pred":
            data = v.sequential_actual_vs_pred(
                long_form, metrics, intervals, entity_id=entity_id, target_id=target_id, track_id=track_id
            )
            fig = render_sequential_actual_vs_pred(
                data, entity_id=entity_id, target_id=target_id, track_id=track_id
            )
        elif view == "error_over_time":
            data = v.error_over_time(
                long_form, metrics, intervals, entity_id=entity_id, target_id=target_id, track_id=track_id
            )
            fig = render_error_over_time(data, entity_id=entity_id, target_id=target_id, track_id=track_id)
        else:
            data = v.coverage_grade_strip(long_form, entity_id=entity_id, target_id=target_id, track_id=track_id)
            fig = render_coverage_grade_strip(data, entity_id=entity_id, target_id=target_id, track_id=track_id)
        if fig is None:
            print(f"no data for {view}: entity={entity_id!r} target={target_id!r} track={track_id!r}")
            return None
        path = charts_dir / view / f"{_slug(entity_id, target_id, track_id)}.png"
        return _save(fig, path)

    if view == "model_leaderboard":
        if not (target_id and track_id):
            raise ValueError("model_leaderboard requires --target and --track")
        data = v.model_leaderboard(
            metrics, intervals, target_id=target_id, track_id=track_id, entity_id=entity_id
        )
        fig = render_model_leaderboard(data, target_id=target_id, track_id=track_id)
        if fig is None:
            print(f"no data for model_leaderboard: target={target_id!r} track={track_id!r}")
            return None
        path = charts_dir / view / f"{_slug(target_id, track_id)}.png"
        return _save(fig, path)

    raise ValueError(f"unknown view: {view!r}")


def render_all(
    *,
    long_form: pd.DataFrame,
    metrics: pd.DataFrame,
    intervals: pd.DataFrame,
    charts_dir: Path,
    entity_filter: str | None,
) -> tuple[list[Path], list[str]]:
    written: list[Path] = []
    skipped: list[str] = []

    axes = v.available_chart_axes(long_form)
    if entity_filter is not None:
        axes = axes[axes["entity_id"] == entity_filter]
    axis_keys = axes[["entity_id", "target_id", "track_id"]].drop_duplicates()
    for row in axis_keys.itertuples(index=False):
        for view in ("sequential_actual_vs_pred", "error_over_time", "coverage_grade_strip"):
            try:
                path = render_one(
                    view,
                    long_form=long_form,
                    metrics=metrics,
                    intervals=intervals,
                    entity_id=row.entity_id,
                    target_id=row.target_id,
                    track_id=row.track_id,
                    charts_dir=charts_dir,
                )
            except ValueError as exc:
                skipped.append(f"{view}/{row.entity_id}/{row.target_id}/{row.track_id}: {exc}")
                continue
            if path is None:
                skipped.append(f"{view}/{row.entity_id}/{row.target_id}/{row.track_id}: no data")
            else:
                written.append(path)

    leaderboard_axes = (
        metrics.loc[
            (metrics["metric_grain"] == "per_entity") & (metrics["is_baseline"] == False),  # noqa: E712
            ["target_id", "track_id"],
        ]
        .drop_duplicates()
        .sort_values(["target_id", "track_id"])
    )
    for row in leaderboard_axes.itertuples(index=False):
        path = render_one(
            "model_leaderboard",
            long_form=long_form,
            metrics=metrics,
            intervals=intervals,
            entity_id=entity_filter,
            target_id=row.target_id,
            track_id=row.track_id,
            charts_dir=charts_dir,
        )
        if path is None:
            skipped.append(f"model_leaderboard/{row.target_id}/{row.track_id}: no data")
        else:
            written.append(path)

    return written, skipped


def _footprint_mb(paths: list[Path]) -> float:
    return sum(p.stat().st_size for p in paths if p.exists()) / (1024 * 1024)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--view", choices=VIEW_CHOICES, help="render exactly one view")
    parser.add_argument("--all", action="store_true", help="render the default set for every available selection")
    parser.add_argument("--registry-id", dest="registry_id", help="narrow to one model contract's target/track")
    parser.add_argument("--entity", dest="entity_id", help="entity_id filter, e.g. 'Air China' or 'MTR'")
    parser.add_argument("--target", dest="target_id", help="target_id filter, e.g. 'revenue'")
    parser.add_argument("--track", dest="track_id", help="track_id filter, e.g. 'half_year_non_overlapping'")
    args = parser.parse_args()

    if not args.all and not args.view:
        parser.error("pass --all or --view <name>")

    long_form, metrics, intervals = load_artifacts()

    target_id, track_id = args.target_id, args.track_id
    if args.registry_id:
        matches = long_form.loc[long_form["registry_id"] == args.registry_id]
        if matches.empty:
            print(f"no long-form rows found for registry_id={args.registry_id!r}")
            return 1
        target_id = target_id or str(matches["target_id"].iloc[0])
        track_id = track_id or str(matches["track_id"].iloc[0])

    charts_dir = resolve_charts_dir()

    if args.all:
        written, skipped = render_all(
            long_form=long_form,
            metrics=metrics,
            intervals=intervals,
            charts_dir=charts_dir,
            entity_filter=args.entity_id,
        )
        print(f"wrote {len(written)} chart(s) to {charts_dir}")
        print(f"total footprint: {_footprint_mb(written):.2f} MB")
        if skipped:
            print(f"skipped {len(skipped)} selection(s) with no data:")
            for line in skipped[:25]:
                print(f"  - {line}")
            if len(skipped) > 25:
                print(f"  ... and {len(skipped) - 25} more")
        return 0

    try:
        path = render_one(
            args.view,
            long_form=long_form,
            metrics=metrics,
            intervals=intervals,
            entity_id=args.entity_id,
            target_id=target_id,
            track_id=track_id,
            charts_dir=charts_dir,
        )
    except ValueError as exc:
        parser.error(str(exc))
        return 2
    if path is None:
        return 1
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
