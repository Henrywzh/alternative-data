"""Shared artifact loading, formatting helpers and chart primitives.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

import json
import re
from html import escape
from typing import Any, Iterable

import pandas as pd
import plotly.express as px
import streamlit as st

from .paths import ARTIFACT_ROOT

from .config import HISTORY_WINDOWS, MONTH_LABELS_ZH, PALETTE, REGIME_STATE_LABELS_ZH, SECTORS


def tr(language: str, english: str, chinese: str) -> str:
    return chinese if language == "zh" else english


def view_label(language: str, view: str) -> str:
    labels = {
        "Level": ("Level", "水平"),
        "MoM %": ("MoM %", "环比 %"),
        "QoQ %": ("QoQ %", "环比 %"),
        "YoY %": ("YoY %", "同比 %"),
        "WoW %": ("WoW %", "周环比 %"),
        "Day %": ("Day %", "日变化 %"),
        "MoM Δpp": ("MoM Δpp", "环比 Δ百分点"),
        "YoY Δpp": ("YoY Δpp", "同比 Δ百分点"),
        "Half-year Δ": ("Half-year Δ", "半年变化"),
        "YoY Δ": ("YoY Δ", "同比变化"),
    }
    english, chinese = labels.get(view, (view, view))
    return tr(language, english, chinese)


@st.cache_data(show_spinner=False)
def load_artifact(slug: str, language: str, artifact_mtime_ns: int = 0) -> dict[str, Any]:
    """Load a local artifact, invalidating the cache when its JSON changes.

    The mtime is deliberately a cache-key argument rather than a hidden
    underscore argument. This keeps the no-network local-artifact model while
    allowing a running Streamlit process to pick up a freshly rebuilt package.
    """
    suffix = "-zh" if language == "zh" else ""
    path = ARTIFACT_ROOT / f"{slug}-artifact{suffix}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(artifact, dict):
        raise ValueError(f"Artifact root must be an object: {path.name}")
    manifest = artifact.get("manifest")
    snapshot = artifact.get("snapshot")
    if not isinstance(manifest, dict) or not isinstance(snapshot, dict):
        raise ValueError(
            f"Artifact is missing manifest/snapshot objects: {path.name}"
        )
    datasets = snapshot.get("datasets")
    if not isinstance(datasets, dict):
        raise ValueError(
            f"Artifact snapshot datasets must be an object: {path.name}"
        )
    invalid_datasets = [
        dataset_id
        for dataset_id, rows in datasets.items()
        if not isinstance(rows, list)
        or any(not isinstance(row, dict) for row in rows)
    ]
    if invalid_datasets:
        raise ValueError(
            "Artifact snapshot datasets must each be a row array: "
            f"{path.name} ({', '.join(map(str, invalid_datasets[:5]))})"
        )
    return artifact


def unavailable_artifact(slug: str, reason: str) -> dict[str, Any]:
    """Keep the terminal usable when one local artifact is missing or corrupt."""
    return {
        "manifest": {
            "title": slug,
            "description": reason,
            "charts": [],
            "tables": [],
            "metrics": [],
        },
        "snapshot": {
            "status": "blocked",
            "generatedAt": None,
            "datasets": {"source_health": []},
        },
        "sources": [],
        "source_health": [],
        "package_info": {"runConsistent": False},
    }


def artifact_mtime_ns(slug: str, language: str) -> int:
    suffix = "-zh" if language == "zh" else ""
    path = ARTIFACT_ROOT / f"{slug}-artifact{suffix}.json"
    return path.stat().st_mtime_ns if path.exists() else 0


def find_manifest_item(artifact: dict[str, Any], kind: str, item_id: str) -> dict[str, Any] | None:
    for item in artifact.get("manifest", {}).get(kind, []):
        if item.get("id") == item_id:
            return item
    return None


def manifest_item(artifact: dict[str, Any], kind: str, item_id: str) -> dict[str, Any]:
    item = find_manifest_item(artifact, kind, item_id)
    if item is not None:
        return item
    raise KeyError(f"Missing {kind} item: {item_id}")


def frame_for_dataset(artifact: dict[str, Any], dataset_id: str) -> pd.DataFrame:
    rows = artifact.get("snapshot", {}).get("datasets", {}).get(dataset_id, [])
    if not isinstance(rows, list):
        return pd.DataFrame()
    return pd.DataFrame(rows)


def source_health_frame(artifact: dict[str, Any]) -> pd.DataFrame:
    """Read source health from either the snapshot dataset or artifact root."""
    snapshot_health = frame_for_dataset(artifact, "source_health")
    if not snapshot_health.empty:
        return snapshot_health
    root_health = artifact.get("source_health", [])
    return pd.DataFrame(root_health) if isinstance(root_health, list) else pd.DataFrame()


def localized_source_health_frame(
    artifact: dict[str, Any],
    label_artifact: dict[str, Any],
    language: str,
) -> pd.DataFrame:
    """Use current EN health values with ZH presentation labels when aligned.

    Data and status must always come from the current EN read contract.
    Localized artifacts are presentation-only; if a ZH artifact ever drifts,
    it must not make an old source date or status look current.
    """
    current = source_health_frame(artifact).reset_index(drop=True)
    if language != "zh" or current.empty:
        return current
    localized = source_health_frame(label_artifact).reset_index(drop=True)
    current_generated = artifact.get("snapshot", {}).get("generatedAt")
    localized_generated = label_artifact.get("snapshot", {}).get("generatedAt")
    if (
        localized.empty
        or len(localized) != len(current)
        or not current_generated
        or current_generated != localized_generated
    ):
        return current
    current = current.copy()
    localized = localized.copy()
    if "series_id" in current.columns and "series_id" in localized.columns:
        if (
            current["series_id"].duplicated().any()
            or localized["series_id"].duplicated().any()
            or set(current["series_id"].astype(str))
            != set(localized["series_id"].astype(str))
        ):
            return current
        current["series_id"] = current["series_id"].astype(str)
        localized["series_id"] = localized["series_id"].astype(str)
        result = (
            localized.set_index("series_id")
            .reindex(current["series_id"].tolist())
            .reset_index()
        )
    else:
        # Older sector artifacts have no stable source key. Retain their
        # established same-length positional localization until migrated.
        result = localized
    for field in ("status", "latest_observation", "records"):
        if field in current.columns:
            result[field] = current[field].to_numpy()
    if "status" in result.columns:
        result["status"] = result["status"].replace(
            {
                "Healthy": "健康",
                "Ready": "可用",
                "Degraded": "需留意",
                "Stale": "陈旧",
                "Partial": "部分可用",
                "Unavailable": "不可用",
                "Missing": "缺失",
            }
        )
    return result


def parse_period(value: Any) -> pd.Timestamp | pd.NaT:
    if pd.isna(value):
        return pd.NaT
    text = str(value)
    quarter = re.fullmatch(r"(\d{4})-Q([1-4])", text)
    if quarter:
        year, q = int(quarter.group(1)), int(quarter.group(2))
        return pd.Timestamp(year=year, month=q * 3, day=1) + pd.offsets.MonthEnd(0)
    academic_year = re.fullmatch(r"(\d{4})/(\d{2,4})", text)
    if academic_year:
        return pd.Timestamp(year=int(academic_year.group(1)), month=8, day=1)
    parsed = pd.to_datetime(text, errors="coerce")
    return parsed if not pd.isna(parsed) else pd.NaT


def add_date_column(frame: pd.DataFrame, field: str) -> pd.DataFrame:
    output = frame.copy()
    if field not in output.columns:
        return output
    output["_date"] = output[field].map(parse_period)
    return output.dropna(subset=["_date"]).sort_values("_date")


def history_window(frame: pd.DataFrame, field: str, window: str) -> tuple[pd.DataFrame, str]:
    dated = add_date_column(frame, field)
    if dated.empty or HISTORY_WINDOWS[window] is None:
        return dated, "Full available history"
    latest = dated["_date"].max()
    earliest = dated["_date"].min()
    cutoff = latest - pd.DateOffset(years=HISTORY_WINDOWS[window])
    filtered = dated[dated["_date"] >= cutoff].copy()
    if filtered.empty:
        filtered = dated.copy()
    coverage = f"{filtered['_date'].min():%b %Y} – {filtered['_date'].max():%b %Y}"
    if earliest >= cutoff:
        coverage += " · all available"
    return filtered, coverage


def resample_line_frame(
    frame: pd.DataFrame,
    value_field: str,
    series_field: str | None,
    frequency: str,
) -> pd.DataFrame:
    """Aggregate a daily series without changing the stored source artifact."""
    if frequency == "Daily" or frame.empty:
        return frame
    rule = {"Weekly": "W-SUN", "Monthly": "MS", "Quarterly": "QS"}[frequency]
    if series_field and series_field in frame.columns:
        parts: list[pd.DataFrame] = []
        for series_name, group in frame.groupby(series_field, dropna=False, sort=False):
            values = (
                group.set_index("_date")[value_field]
                .sort_index()
                .resample(rule)
                .sum(min_count=1)
                .dropna()
                .rename(value_field)
                .reset_index()
            )
            values[series_field] = series_name
            parts.append(values)
        return pd.concat(parts, ignore_index=True) if parts else frame.iloc[0:0].copy()
    values = (
        frame.set_index("_date")[value_field]
        .sort_index()
        .resample(rule)
        .sum(min_count=1)
        .dropna()
        .rename(value_field)
        .reset_index()
    )
    return values


def localize_coverage(coverage: str, language: str) -> str:
    if language == "en":
        return coverage
    if coverage == "Full available history":
        return "全部可用历史"
    output = coverage.replace(" · all available", " · 全部可用")
    for english, chinese in MONTH_LABELS_ZH.items():
        output = re.sub(rf"{english} (\d{{4}})", rf"\1年{chinese}", output)
    return output


def latest_row(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}
    date_fields = ["date", "observation_date", "month", "period", "quarter", "academic_year"]
    for field in date_fields:
        if field in frame.columns:
            ordered = add_date_column(frame, field)
            if not ordered.empty:
                return ordered.iloc[-1].to_dict()
    return frame.iloc[-1].to_dict()


def is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value))


def format_number(value: Any) -> str:
    if is_missing(value):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"{number:,.0f}"
    return f"{number:,.1f}"


def _regime_state_label(state: Any, language: str) -> str:
    text = str(state or "Unavailable")
    return REGIME_STATE_LABELS_ZH.get(text, text) if language == "zh" else text


def _regime_history_window(frame: pd.DataFrame, window: str) -> pd.DataFrame:
    if frame.empty or "date" not in frame.columns:
        return frame
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result = result.dropna(subset=["date"])
    years = HISTORY_WINDOWS.get(window)
    if years is not None and not result.empty:
        result = result[result["date"] >= result["date"].max() - pd.DateOffset(years=years)]
    return result


def _regime_has_columns(frame: pd.DataFrame, columns: Iterable[str]) -> bool:
    return not frame.empty and set(columns).issubset(frame.columns)


def format_metric(value: Any, fmt: str = "number") -> str:
    if is_missing(value):
        return "—"
    if fmt == "percent":
        try:
            # Value is already in percentage units (e.g. 87.2 -> "87.2%").
            return f"{float(value):,.1f}%"
        except (TypeError, ValueError):
            return str(value)
    if fmt == "fraction":
        try:
            # Value is stored as a 0-1 ratio (e.g. 0.038 -> "3.8%").
            return f"{float(value) * 100:,.1f}%"
        except (TypeError, ValueError):
            return str(value)
    if fmt == "text":
        return str(value)
    if fmt == "usd":
        try:
            return f"${float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)
    return format_number(value)


def observation_date_label(value: Any, language: str) -> str:
    if is_missing(value):
        return "—"
    text = str(value)
    if re.fullmatch(r"\d{4}-Q[1-4]", text) or re.fullmatch(r"\d{4}/\d{2,4}", text):
        return text
    parsed = parse_period(value)
    if pd.isna(parsed):
        return text
    if language == "zh":
        return f"{parsed.year}年{parsed.month}月{parsed.day}日"
    return parsed.strftime("%d %b %Y")


def latest_metric_reading(
    artifact: dict[str, Any],
    dataset_id: str,
    field: str,
    fmt: str,
    *,
    label_en: str,
    label_zh: str,
    language: str,
) -> tuple[str, str, str]:
    frame = frame_for_dataset(artifact, dataset_id)
    if frame.empty or field not in frame.columns:
        return (label_zh if language == "zh" else label_en, "—", "—")
    row = latest_row(frame)
    date_field = next(
        (candidate for candidate in ["observation_date", "date", "month", "period", "quarter", "academic_year"] if candidate in row),
        None,
    )
    label = label_zh if language == "zh" else label_en
    value = (
        _regime_state_label(row.get(field), language)
        if fmt == "regime_state"
        else format_metric(row.get(field), fmt)
    )
    return label, value, observation_date_label(row.get(date_field), language)


def latest_series_reading(
    artifact: dict[str, Any],
    chart_id: str,
    series_name: str,
    fmt: str,
    language: str,
) -> tuple[str, str]:
    spec = manifest_item(artifact, "charts", chart_id)
    frame = frame_for_dataset(artifact, spec["dataset"])
    series_field = spec.get("encodings", {}).get("color", {}).get("field")
    value_field = spec.get("encodings", {}).get("y", {}).get("field")
    date_field = spec.get("encodings", {}).get("x", {}).get("field")
    if frame.empty or not series_field or not value_field or not date_field or series_field not in frame.columns:
        return "—", "—"
    filtered = frame[frame[series_field].astype(str).eq(series_name)].copy()
    if filtered.empty or value_field not in filtered.columns or date_field not in filtered.columns:
        return "—", "—"
    ordered = add_date_column(filtered, date_field)
    if ordered.empty:
        return "—", "—"
    row = ordered.iloc[-1]
    return format_metric(row.get(value_field), fmt), observation_date_label(row.get(date_field), language)


def series_for_sparkline(artifact: dict[str, Any], chart_id: str, series_name: str | None) -> pd.DataFrame:
    spec = manifest_item(artifact, "charts", chart_id)
    frame = frame_for_dataset(artifact, spec["dataset"])
    series_field = spec.get("encodings", {}).get("color", {}).get("field")
    value_field = spec.get("encodings", {}).get("y", {}).get("field")
    date_field = spec.get("encodings", {}).get("x", {}).get("field")
    if frame.empty or not value_field or not date_field:
        return pd.DataFrame()
    if series_field and series_field in frame.columns:
        filtered = frame[frame[series_field].astype(str).eq(str(series_name))].copy()
    else:
        filtered = frame.copy()
    if filtered.empty:
        return pd.DataFrame()
    ordered = add_date_column(filtered, date_field)
    if ordered.empty:
        return pd.DataFrame()
    ordered["_spark_value"] = pd.to_numeric(ordered[value_field], errors="coerce")
    return ordered.dropna(subset=["_spark_value"]).tail(36)


def observation_period_label(value: Any, language: str) -> str:
    if is_missing(value):
        return "—"
    parsed = parse_period(value)
    if pd.isna(parsed):
        return str(value)
    if language == "zh":
        return f"{parsed.year}年{parsed.month}月"
    return parsed.strftime("%b %Y")


def sparkline_context(
    artifact: dict[str, Any],
    sparkline: dict[str, Any],
    language: str,
) -> tuple[pd.DataFrame, str, str, str, str]:
    frame = series_for_sparkline(artifact, sparkline["chart_id"], sparkline["series"])
    if frame.empty:
        return frame, "—", "—", "—", "—"
    title = sparkline["title_zh"] if language == "zh" else sparkline["title_en"]
    note = sparkline["note_zh"] if language == "zh" else sparkline["note_en"]
    latest_value = format_metric(frame.iloc[-1]["_spark_value"], sparkline.get("format", "number"))
    start = observation_period_label(frame.iloc[0]["_date"], language)
    end = observation_period_label(frame.iloc[-1]["_date"], language)
    date_range = f"{start} – {end}"
    return frame, title, latest_value, date_range, note


def sparkline_svg(frame: pd.DataFrame, color: str = PALETTE[0]) -> str:
    if frame.empty or len(frame) < 2:
        return ""
    values = frame["_spark_value"].astype(float).tolist()
    low, high = min(values), max(values)
    span = high - low
    if span == 0:
        span = 1.0
    width, height, pad = 160, 36, 3
    points = []
    for index, value in enumerate(values):
        x = pad + (width - 2 * pad) * index / max(1, len(values) - 1)
        y = height - pad - (height - 2 * pad) * (value - low) / span
        points.append(f"{x:.1f},{y:.1f}")
    return (
        f'<svg class="am-pulse-sparkline" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Trend sparkline"><polyline points="{" ".join(points)}" '
        f'fill="none" stroke="{escape(color)}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


def metric_from_card(
    artifact: dict[str, Any],
    label_artifact: dict[str, Any],
    card_id: str,
    field: str,
    fmt: str,
) -> tuple[str, str, str]:
    """Read a KPI card metric, degrading to a visible dash when the artifact is out of sync.

    A bare next() lookup used to crash the whole page with StopIteration whenever
    the live artifact and the app revision drifted apart -- the same failure mode
    as the manifest_item KeyError previously seen on Streamlit Cloud. Missing
    data is rendered as an em dash instead.
    """
    def find_card(manifest: dict[str, Any], cid: str) -> dict[str, Any] | None:
        return next(
            (item for item in manifest.get("cards", []) if item.get("id") == cid),
            None,
        )

    card = find_card(artifact.get("manifest", {}), card_id)
    label_card = find_card(label_artifact.get("manifest", {}), card_id)
    if card is None or label_card is None:
        return (card_id, "—", "")
    dataset = frame_for_dataset(artifact, card.get("dataset", ""))
    row = latest_row(dataset)
    metric = next(
        (item for item in label_card.get("metrics", []) if item.get("field") == field),
        None,
    )
    description = label_card.get("description", card.get("description", ""))
    if metric is None:
        return (card_id, "—", description)
    return metric["label"], format_metric(row.get(field), fmt), description


def style_app() -> None:
    st.markdown(
        """
        <style>
        :root { --am-blue: #2563eb; --am-ink: #111827; --am-muted: #667085; }
        .stApp { background: #ffffff; color: var(--am-ink); }
        [data-testid="stSidebar"] { background: #f7f8fa; border-right: 1px solid #e5e7eb; }
        [data-testid="stSidebar"] > div:first-child { padding-top: 1.2rem; }
        [data-testid="stSidebar"] .am-sidebar-group-label { color: #6b7280; font-size: .68rem; font-weight: 750; letter-spacing: .1em; text-transform: uppercase; margin: 1rem 0 .3rem .65rem; }
        [data-testid="stSidebar"] .stButton { margin-bottom: .12rem; }
        [data-testid="stSidebar"] .stButton > button { justify-content: flex-start; min-height: 2.25rem; padding: .4rem .65rem; border: 0 !important; border-radius: 7px; background: transparent !important; box-shadow: none !important; color: #111827 !important; font-size: .86rem; font-weight: 520; }
        [data-testid="stSidebar"] .stButton > button > div,
        [data-testid="stSidebar"] .stButton > button > div > span,
        [data-testid="stSidebar"] .stButton > button [data-testid="stMarkdownContainer"] { width: 100% !important; max-width: none !important; flex: 1 1 auto !important; }
        [data-testid="stSidebar"] .stButton > button p { width: 100%; margin: 0; text-align: left; }
        [data-testid="stSidebar"] .stButton > button:hover { background: rgba(37, 99, 235, .07) !important; color: #2563eb !important; transform: none; }
        [data-testid="stSidebar"] .stButton > button:hover p { color: #2563eb !important; }
        [data-testid="stSidebar"] .stButton > button[kind="primary"] { background: rgba(37, 99, 235, .13) !important; color: #2563eb !important; font-weight: 700; box-shadow: inset 3px 0 0 #2563eb !important; }
        [data-testid="stSidebar"] .stButton > button[kind="primary"] p { color: #2563eb !important; }
        [data-testid="stSidebar"] .stSelectbox label { color: #6b7280 !important; font-size: .75rem; font-weight: 700; }
        [data-testid="stMetric"] { border: 1px solid #e5e7eb; border-radius: 10px; padding: .8rem .9rem; background: #ffffff; }
        [data-testid="stMetricLabel"] { color: #667085; }
        [data-testid="stMetricValue"] { color: #111827; }
        .am-kicker { color: #4b5563; font-size: 1.02rem; letter-spacing: .05em; text-transform: uppercase; font-weight: 750; }
        .am-section .am-kicker { color: #374151; font-size: 1.12rem; }
        .am-meta { color: #667085; font-size: .96rem; }
        .am-page-title { margin: 0 0 .25rem; color: #111827; font-size: 2rem; line-height: 1.15; letter-spacing: -.035em; font-weight: 800; }
        .am-chart-title { margin: .15rem 0 .15rem; color: #111827; font-size: 1.08rem; line-height: 1.25; font-weight: 750; }
        .am-section { margin-top: 1.2rem; margin-bottom: .55rem; }
        .am-section h2 { margin-bottom: .15rem; }
        .am-note { color: #667085; font-size: .8rem; }
        .am-brand { display: flex; align-items: center; gap: .6rem; margin: .15rem 0 1.1rem; }
        .am-brand-mark { display: grid; width: 2rem; height: 2rem; place-items: center; border-radius: .5rem; background: #2563eb; color: white; font-weight: 800; }
        .am-brand-name { font-weight: 800; line-height: 1.1; }
        .am-brand-sub { color: #667085; font-size: .68rem; margin-top: .15rem; }
        .am-overview-status { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .85rem; margin: .9rem 0 1.45rem; }
        .am-overview-status-item { min-height: 7.2rem; padding: 1.1rem 1.15rem; border: 1px solid #e5e7eb; border-radius: 10px; background: #f9fafb; display: flex; flex-direction: column; justify-content: center; }
        .am-overview-status-label { color: #667085; font-size: .96rem; font-weight: 750; letter-spacing: .04em; text-transform: uppercase; }
        .am-overview-status-value { margin-top: .34rem; color: #111827; font-size: 1.55rem; font-weight: 750; line-height: 1.15; white-space: nowrap; }
        .am-overview-status-note { margin-top: .2rem; color: #9ca3af; font-size: .9rem; line-height: 1.25; }
        .am-pulse-title { margin: .1rem 0 .3rem; color: #111827; font-size: 1.38rem; font-weight: 750; line-height: 1.25; }
        .am-pulse-meta { color: #667085; font-size: .96rem; }
        .am-pulse-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .7rem; margin-top: 1.05rem; }
        .am-pulse-metric { min-width: 0; padding: .9rem .9rem; border: 1px solid #eef1f5; border-radius: 9px; background: #fafbfc; }
        .am-pulse-label { min-height: 1.55em; color: #667085; font-size: .86rem; font-weight: 700; line-height: 1.2; white-space: normal; }
        .am-pulse-value { margin-top: .24rem; color: #111827; font-size: 1.42rem; font-weight: 750; line-height: 1.1; }
        .am-pulse-asof { margin-top: .24rem; color: #9ca3af; font-size: .82rem; }
        .am-pulse-sparkline-title { margin-top: .9rem; color: #374151; font-size: .86rem; font-weight: 750; }
        .am-pulse-sparkline-meta { margin-top: .18rem; color: #667085; font-size: .8rem; }
        .am-pulse-sparkline-note { margin-top: .14rem; color: #9ca3af; font-size: .76rem; }
        .am-pulse-sparkline { display: block; width: 100%; height: 44px; margin: .9rem 0 .25rem; }
        .am-health-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .7rem; align-items: center; }
        .am-health-value { color: #111827; font-size: 1.15rem; font-weight: 750; }
        .am-health-label { color: #667085; font-size: .72rem; }
        .am-regime-summary { margin: 1rem 0 1.35rem; padding: 1.15rem 1.25rem; border: 1px solid #dbe4f0; border-left: 5px solid #2563eb; border-radius: 10px; background: #f8fafc; }
        .am-regime-summary[data-state="watch"] { border-left-color: #f59e0b; background: #fffbeb; }
        .am-regime-summary[data-state="confirmed"],
        .am-regime-summary[data-state="escalating"] { border-left-color: #ef4444; background: #fef2f2; }
        .am-regime-summary[data-state="improving"] { border-left-color: #10b981; background: #ecfdf5; }
        .am-regime-summary[data-state="unavailable"] { border-left-color: #94a3b8; background: #f8fafc; }
        .am-regime-summary-title { color: #111827; font-size: 1.35rem; font-weight: 800; line-height: 1.2; }
        .am-regime-summary-body { margin-top: .35rem; color: #374151; font-size: .96rem; line-height: 1.45; }
        .am-regime-summary-meta { margin-top: .45rem; color: #667085; font-size: .78rem; }
        .am-regime-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .75rem; margin: .7rem 0 1.1rem; }
        .am-regime-card { min-width: 0; min-height: 10.4rem; padding: 1rem; border: 1px solid #e5e7eb; border-top: 4px solid #94a3b8; border-radius: 10px; background: #fff; }
        .am-regime-card[data-state="watch"] { border-top-color: #f59e0b; }
        .am-regime-card[data-state="confirmed"],
        .am-regime-card[data-state="escalating"] { border-top-color: #ef4444; }
        .am-regime-card[data-state="improving"] { border-top-color: #10b981; }
        .am-regime-card[data-state="unavailable"] { border-top-color: #94a3b8; background: #f8fafc; }
        .am-regime-card-title { min-height: 2.45em; color: #374151; font-size: .83rem; font-weight: 750; line-height: 1.25; }
        .am-regime-card-reading { display: flex; align-items: baseline; justify-content: space-between; gap: .5rem; margin-top: .45rem; }
        .am-regime-card-value { color: #111827; font-size: 1.45rem; font-weight: 800; line-height: 1.1; white-space: nowrap; }
        .am-regime-card-state { color: #475569; font-size: .78rem; font-weight: 750; white-space: nowrap; }
        .am-regime-card-rule { margin-top: .55rem; color: #667085; font-size: .76rem; line-height: 1.35; }
        .am-regime-card-detail { margin-top: .42rem; color: #667085; font-size: .76rem; line-height: 1.35; }
        .am-regime-card-detail-label { color: #475569; font-weight: 750; }
        .am-regime-card-meta { margin-top: .45rem; color: #94a3b8; font-size: .7rem; line-height: 1.3; }
        .am-regime-brief-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .75rem; margin: .65rem 0 1.15rem; }
        .am-regime-brief-card { min-width: 0; min-height: 8.5rem; padding: .9rem 1rem; border: 1px solid #e5e7eb; border-left: 4px solid #94a3b8; border-radius: 10px; background: #fff; }
        .am-regime-brief-card[data-state="watch"] { border-left-color: #f59e0b; background: #fffbeb; }
        .am-regime-brief-card[data-state="confirmed"],
        .am-regime-brief-card[data-state="escalating"] { border-left-color: #ef4444; background: #fef2f2; }
        .am-regime-brief-card[data-state="improving"] { border-left-color: #10b981; background: #ecfdf5; }
        .am-regime-brief-card[data-state="unavailable"] { border-left-color: #94a3b8; background: #f8fafc; }
        .am-regime-brief-label { color: #667085; font-size: .76rem; font-weight: 750; line-height: 1.25; }
        .am-regime-brief-value { margin-top: .35rem; color: #111827; font-size: 1.28rem; font-weight: 800; line-height: 1.15; }
        .am-regime-brief-note { margin-top: .42rem; color: #667085; font-size: .74rem; line-height: 1.35; }
        .am-alert-decision { margin: .65rem 0 1.2rem; padding: 1rem 1.1rem; border: 1px solid #dbe4f0; border-left: 5px solid #10b981; border-radius: 10px; background: #f8fafc; }
        .am-alert-decision[data-state="watch"] { border-left-color: #f59e0b; background: #fffbeb; }
        .am-alert-decision[data-state="confirmed"] { border-left-color: #ef4444; background: #fef2f2; }
        .am-alert-decision[data-state="unavailable"] { border-left-color: #94a3b8; background: #f8fafc; }
        .am-alert-decision-grid { display: grid; grid-template-columns: 1.25fr .7fr .8fr 1fr; gap: .75rem; }
        .am-alert-decision-item { min-width: 0; }
        .am-alert-decision-label { color: #667085; font-size: .72rem; font-weight: 750; letter-spacing: .025em; text-transform: uppercase; }
        .am-alert-decision-value { margin-top: .24rem; color: #111827; font-size: 1.04rem; font-weight: 800; line-height: 1.25; }
        .am-alert-decision-reason { margin-top: .75rem; color: #374151; font-size: .85rem; line-height: 1.45; }
        .am-alert-transition-list { margin-top: .55rem; padding-top: .55rem; border-top: 1px solid rgba(148, 163, 184, .28); color: #475569; font-size: .79rem; line-height: 1.55; }
        @media (max-width: 900px) {
            .am-overview-status { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .am-pulse-metrics { grid-template-columns: 1fr; }
            .am-regime-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .am-regime-brief-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .am-alert-decision-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 620px) {
            .am-regime-grid { grid-template-columns: 1fr; }
            .am-regime-brief-grid { grid-template-columns: 1fr; }
            .am-alert-decision-grid { grid-template-columns: 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def chart_theme(fig: Any, value_format: str = "number", date_axis: bool = True, height: int = 380) -> Any:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin={"l": 10, "r": 18, "t": 10, "b": 62},
        colorway=PALETTE,
        hovermode="x unified" if date_axis else "closest",
        legend={"orientation": "h", "y": -0.18, "x": 0, "title": ""},
        hoverlabel={"bgcolor": "#FFFFFF", "bordercolor": "#E5E7EB", "font": {"color": "#111827", "size": 12}, "namelength": -1},
        font={"family": "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif", "size": 12, "color": "#374151"},
    )
    fig.update_xaxes(showgrid=False, automargin=True)
    fig.update_yaxes(showgrid=True, gridcolor="#eef1f5", automargin=True)
    if value_format == "percent":
        fig.update_yaxes(tickformat=".1%")
    return fig


def date_hover_format(dates: pd.Series) -> str:
    """Tooltip date format for a series, chosen by its grain.

    Keyed off the spacing between observations, not the total span. The old
    rule dropped the day from the tooltip once a series ran longer than 550
    days, which is backwards: axis *ticks* have to coarsen as the span grows
    because they collide with each other, but a tooltip shows one point and
    never collides. A daily series needs its day at any span -- which is why
    two years of daily ETF prices hovered as a bare "Aug 2026".
    """
    ordered = pd.Series(pd.to_datetime(dates, errors="coerce")).dropna().drop_duplicates().sort_values()
    if len(ordered) < 2:
        return "%d %b %Y"
    spacing = ordered.diff().dropna().median()
    if spacing >= pd.Timedelta(days=350):
        return "%Y"
    if spacing >= pd.Timedelta(days=25):
        return "%b %Y"
    return "%d %b %Y"


def date_tick_format(dates: pd.Series) -> str:
    """Axis tick format: coarse enough not to collide, fine enough to place.

    A short daily window labelled "%b %Y" repeats one month across every tick,
    which is what the premium chart showed on its first two days of history.
    """
    ordered = pd.Series(pd.to_datetime(dates, errors="coerce")).dropna().sort_values()
    if ordered.empty:
        return "%b %Y"
    span = ordered.max() - ordered.min()
    if span <= pd.Timedelta(days=120):
        return "%d %b"
    if span <= pd.Timedelta(days=1100):
        return "%b %Y"
    return "%Y"


def apply_line_hover(fig: Any, frame: pd.DataFrame, value_format: str) -> None:
    x_format = date_hover_format(frame["_date"])
    y_format = ".1%" if value_format == "percent" else ",.1f"
    for trace in fig.data:
        series_name = trace.name or "Value"
        trace.hovertemplate = f"<b>%{{x|{x_format}}}</b><br>{series_name}: %{{y:{y_format}}}<extra></extra>"


def apply_bar_hover(fig: Any, value_label: str, horizontal: bool) -> None:
    for trace in fig.data:
        series_name = trace.name or value_label
        if horizontal:
            trace.hovertemplate = f"<b>%{{y}}</b><br>{value_label}: %{{x:,.1f}}<extra></extra>"
        else:
            trace.hovertemplate = f"<b>%{{x}}</b><br>{series_name}: %{{y:,.1f}}<extra></extra>"


def line_view_frame(
    frame: pd.DataFrame,
    value_field: str,
    series_field: str | None,
    view: str,
    periods_per_year: int,
    change_mode: str,
    value_format: str,
) -> tuple[pd.DataFrame, str, str]:
    output = frame.copy()
    group_fields = [series_field] if series_field and series_field in output.columns else []
    output = output.sort_values(group_fields + ["_date"] if group_fields else ["_date"])
    if view == "Level":
        output["_value"] = output[value_field]
        return output, "Level", value_format
    grouped = output.groupby(group_fields, dropna=False)[value_field] if group_fields else output[value_field]
    if change_mode == "delta":
        changed = grouped.diff(periods_per_year if "YoY" in view else 1)
        if value_format == "percent":
            changed = changed * 100
        output["_value"] = changed
        suffix = "Δpp" if value_format == "percent" else "Δ"
        if "YoY" in view:
            label = f"YoY {suffix}"
        elif "MoM" in view:
            label = f"MoM {suffix}"
        elif "QoQ" in view:
            label = f"QoQ {suffix}"
        elif "WoW" in view:
            label = f"WoW {suffix}"
        else:
            label = suffix
        return output.dropna(subset=["_value"]), label, "number"
    changed = grouped.pct_change(periods_per_year if "YoY" in view else 1) * 100
    output["_value"] = changed
    if "YoY" in view:
        label = "YoY %"
    elif "MoM" in view:
        label = "MoM %"
    elif "QoQ" in view:
        label = "QoQ %"
    elif "WoW" in view:
        label = "WoW %"
    elif "Day" in view:
        label = "Day %"
    else:
        label = "Period %"
    return output.dropna(subset=["_value"]), label, "number"


def render_line_chart(
    artifact: dict[str, Any],
    labels: dict[str, Any],
    chart_id: str,
    language: str,
    history_window_name: str,
    *,
    series_selection: Iterable[str] | None = None,
    views: tuple[str, ...] = ("Level",),
    periods_per_year: int = 12,
    change_mode: str = "pct",
    height: int = 380,
    resample_frequency: str | None = None,
    series_label_map: dict[str, str] | None = None,
    reference_bands: tuple[tuple[float, float, str], ...] = (),
    title_override: str | None = None,
    subtitle_override: str | None = None,
) -> None:
    spec = find_manifest_item(artifact, "charts", chart_id)
    if spec is None:
        st.info(tr(language, "This chart is not available in the current artifact snapshot.", "当前数据快照未包含此图表。"))
        return
    label_spec = find_manifest_item(labels, "charts", chart_id) or spec
    x_field = spec["encodings"]["x"]["field"]
    y_field = spec["encodings"]["y"]["field"]
    series_field = spec.get("encodings", {}).get("color", {}).get("field")
    frame = frame_for_dataset(artifact, spec["dataset"])
    frame, coverage = history_window(frame, x_field, history_window_name)
    if series_selection is not None and series_field and series_field in frame.columns:
        frame = frame[frame[series_field].isin(list(series_selection))].copy()
    if resample_frequency:
        frame = resample_line_frame(frame, y_field, series_field, resample_frequency)
    if frame.empty:
        st.info(tr(language, "No rows are available for this selection.", "这个选择没有可用数据。"))
        return

    title = title_override or label_spec.get("title", spec["title"])
    subtitle = (
        subtitle_override
        if subtitle_override is not None
        else label_spec.get("subtitle", spec.get("subtitle", ""))
    )
    if resample_frequency and chart_id == "immd_net_flow_chart":
        frequency_label = {
            "Daily": tr(language, "Daily", "日度"),
            "Weekly": tr(language, "Weekly", "周度"),
            "Monthly": tr(language, "Monthly", "月度"),
        }[resample_frequency]
        title = re.sub(r"\s*[（(](?:Daily|日度)[）)]$", "", title).strip()
        title = f"{title} ({frequency_label})" if language == "en" else f"{title}（{frequency_label}）"
    st.markdown(f'<div class="am-chart-title">{escape(title)}</div>', unsafe_allow_html=True)
    frequency_note = {
        "Daily": tr(language, "Daily source observations", "日度来源观察值"),
        "Weekly": tr(language, "Weekly sums of underlying observations", "按周合计原始观察值"),
        "Monthly": tr(language, "Monthly sums of underlying observations", "按月合计原始观察值"),
        "Quarterly": tr(language, "Quarterly sums of underlying observations", "按季度合计原始观察值"),
    }.get(resample_frequency or "", "")
    caption_parts = [subtitle]
    if frequency_note:
        caption_parts.append(frequency_note)
    caption_parts.append(localize_coverage(coverage, language))
    st.caption(" · ".join(caption_parts))
    view = views[0]
    if len(views) > 1:
        view = st.radio(
            tr(language, "View", "视图"),
            views,
            horizontal=True,
            key=f"view_{chart_id}",
            format_func=lambda item: view_label(language, item),
        )
    transformed, value_label, transformed_format = line_view_frame(
        frame, y_field, series_field, view, periods_per_year, change_mode, spec.get("valueFormat", "number")
    )
    if transformed.empty:
        st.info(tr(language, "Not enough observations for this comparison window.", "这个比较视图没有足够的观察值。"))
        return
    if series_label_map and series_field and series_field in transformed.columns:
        transformed[series_field] = transformed[series_field].map(
            lambda value: series_label_map.get(str(value), str(value))
        )
    fig = px.line(
        transformed,
        x="_date",
        y="_value",
        color=series_field if series_field and series_field in transformed.columns else None,
        markers=False,
        color_discrete_sequence=PALETTE,
    )
    fig.update_yaxes(title=value_label)
    # Date ticks already carry the time context; removing the redundant
    # "Month"/"Quarter" title leaves room for the legend in compact cards.
    fig.update_xaxes(title=None, tickformat="%b %Y")
    if transformed["_date"].max() - transformed["_date"].min() > pd.Timedelta(days=365 * 7):
        fig.update_xaxes(dtick="M12")
    elif transformed["_date"].max() - transformed["_date"].min() > pd.Timedelta(days=365 * 3):
        fig.update_xaxes(dtick="M6")
    if reference_bands:
        for lower, upper, color in reference_bands:
            fig.add_hrect(
                y0=lower,
                y1=upper,
                fillcolor=color,
                opacity=0.12,
                line_width=0,
                layer="below",
            )
        fig.update_yaxes(range=[0, 100])
    apply_line_hover(fig, transformed, transformed_format)
    fig = chart_theme(fig, transformed_format, date_axis=True, height=height)
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})


def render_fear_greed_daily_chart(
    artifact: dict[str, Any],
    language: str,
    history_window_name: str,
) -> None:
    """Render the raw daily Fear & Greed score and its trailing seven-day mean."""
    frame = frame_for_dataset(artifact, "fear_greed_daily")
    frame, coverage = history_window(frame, "date", history_window_name)
    if frame.empty:
        st.info(tr(language, "Daily Fear & Greed data is not available in this artifact yet.", "这个数据快照暂时没有日度恐惧与贪婪数据。"))
        return

    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    frame["score_7d_avg"] = pd.to_numeric(frame["score_7d_avg"], errors="coerce")
    frame = frame.dropna(subset=["_date", "score"]).sort_values("_date")
    if frame.empty:
        st.info(tr(language, "Daily Fear & Greed data is not available in this artifact yet.", "这个数据快照暂时没有日度恐惧与贪婪数据。"))
        return

    options = ["Both", "Daily score", "7-day rolling average"]
    view = st.radio(
        tr(language, "Metric", "指标"),
        options,
        horizontal=True,
        key="fear_greed_daily_metric_view",
        format_func=lambda item: {
            "Both": tr(language, "Both", "两者"),
            "Daily score": tr(language, "Daily score", "日度分数"),
            "7-day rolling average": tr(language, "7-day rolling average", "7日滚动平均"),
        }[item],
    )
    fields = {
        "Daily score": ["score"],
        "7-day rolling average": ["score_7d_avg"],
        "Both": ["score", "score_7d_avg"],
    }[view]
    plot = frame[["_date", *fields]].melt(
        id_vars=["_date"],
        var_name="series",
        value_name="_value",
    ).dropna(subset=["_value"])
    series_labels = {
        "score": tr(language, "Daily score", "日度分数"),
        "score_7d_avg": tr(language, "7-day rolling average", "7日滚动平均"),
    }
    plot["series"] = plot["series"].map(series_labels)

    st.markdown(
        f'<div class="am-chart-title">{tr(language, "Crypto Fear & Greed: daily signal", "加密恐惧与贪婪：日度信号")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        " · ".join(
            [
                tr(
                    language,
                    "Daily Alternative.me observations; the rolling average is derived from the trailing seven calendar days.",
                    "Alternative.me 日度观察值；滚动平均由最近七个日历日派生。",
                ),
                localize_coverage(coverage, language),
            ]
        )
    )
    fig = px.line(
        plot,
        x="_date",
        y="_value",
        color="series",
        color_discrete_map={
            series_labels["score"]: PALETTE[0],
            series_labels["score_7d_avg"]: PALETTE[1],
        },
    )
    fig.update_yaxes(title=tr(language, "Score", "分数"), range=[0, 100])
    fig.update_xaxes(title=None, tickformat="%d %b %Y")
    span = plot["_date"].max() - plot["_date"].min()
    if span > pd.Timedelta(days=365 * 7):
        fig.update_xaxes(dtick="M12")
    elif span > pd.Timedelta(days=365 * 3):
        fig.update_xaxes(dtick="M6")
    for trace in fig.data:
        trace.line.width = 1.4 if trace.name == series_labels["score"] else 3.0
    apply_line_hover(fig, plot, "number")
    fig = chart_theme(fig, "number", date_axis=True, height=430)
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})


def render_bar_chart(
    artifact: dict[str, Any],
    labels: dict[str, Any],
    chart_id: str,
    language: str,
    *,
    height: int | None = None,
) -> None:
    spec = find_manifest_item(artifact, "charts", chart_id)
    if spec is None:
        st.info(tr(language, "This chart is not available in the current artifact snapshot.", "当前数据快照未包含此图表。"))
        return
    label_spec = find_manifest_item(labels, "charts", chart_id) or spec
    x_field = spec["encodings"]["x"]["field"]
    y_field = spec["encodings"]["y"]["field"]
    color_field = spec.get("encodings", {}).get("color", {}).get("field")
    frame = frame_for_dataset(artifact, spec["dataset"])
    title = label_spec.get("title", spec["title"])
    subtitle = label_spec.get("subtitle", spec.get("subtitle", ""))
    st.markdown(f'<div class="am-chart-title">{escape(title)}</div>', unsafe_allow_html=True)
    st.caption(subtitle)
    if frame.empty:
        st.info(tr(language, "No rows are available.", "没有可用数据。"))
        return
    if spec.get("type") == "horizontalBar":
        frame = frame.dropna(subset=[x_field, y_field]).sort_values(y_field)
        fig = px.bar(frame, x=y_field, y=x_field, orientation="h", color_discrete_sequence=[PALETTE[0]])
        fig.update_yaxes(title=spec["encodings"]["x"].get("label", ""))
        fig.update_xaxes(title=spec["encodings"]["y"].get("label", ""))
        computed_height = max(340, min(700, 100 + len(frame) * 30))
        apply_bar_hover(fig, spec["encodings"]["y"].get("label", y_field), horizontal=True)
    else:
        x = x_field
        frame = frame.dropna(subset=[x_field, y_field])
        fig = px.bar(
            frame,
            x=x,
            y=y_field,
            color=color_field if color_field and color_field in frame.columns else None,
            barmode="group",
            color_discrete_sequence=PALETTE,
        )
        fig.update_xaxes(title=spec["encodings"]["x"].get("label", ""))
        fig.update_yaxes(title=spec["encodings"]["y"].get("label", ""))
        computed_height = 400
        apply_bar_hover(fig, spec["encodings"]["y"].get("label", y_field), horizontal=False)
    fig = chart_theme(fig, spec.get("valueFormat", "number"), date_axis=False, height=height or computed_height)
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})


def render_table(
    artifact: dict[str, Any],
    labels: dict[str, Any],
    table_id: str,
    language: str,
    *,
    value_maps: dict[str, dict[str, str]] | None = None,
    max_rows: int | None = None,
) -> None:
    spec = find_manifest_item(artifact, "tables", table_id)
    if spec is None:
        st.info(tr(language, "This table is not available in the current artifact snapshot.", "当前数据快照未包含此表格。"))
        return
    label_spec = find_manifest_item(labels, "tables", table_id) or spec
    frame = frame_for_dataset(artifact, spec["dataset"])
    title = label_spec.get("title", spec["title"])
    subtitle = label_spec.get("subtitle", spec.get("subtitle", ""))
    st.markdown(f'<div class="am-chart-title">{escape(title)}</div>', unsafe_allow_html=True)
    st.caption(subtitle)
    if frame.empty:
        st.info(tr(language, "No rows are available.", "没有可用数据。"))
        return
    if max_rows is not None and len(frame) > max_rows:
        date_field = next(
            (field for field in ["launch_date", "date_time", "issue_date", "date"] if field in frame.columns),
            None,
        )
        if date_field:
            frame = frame.assign(_sort_date=pd.to_datetime(frame[date_field], errors="coerce"))
            frame = frame.sort_values("_sort_date", ascending=False, na_position="last")
        frame = frame.head(max_rows).copy()
    fields = [column["field"] for column in spec.get("columns", []) if column["field"] in frame.columns]
    labels_by_field = {
        column["field"]: column.get("label", column["field"])
        for column in spec.get("columns", [])
    }
    display = frame[fields].copy()
    for field, mapping in (value_maps or {}).items():
        if field in display.columns:
            display[field] = display[field].map(lambda value: mapping.get(str(value), value))
    display = display.rename(columns=labels_by_field)
    st.dataframe(display, hide_index=True, width="stretch")


def series_options(
    artifact: dict[str, Any],
    chart_id: str,
    language: str,
    default_count: int = 4,
    series_label_map: dict[str, str] | None = None,
) -> list[str]:
    spec = find_manifest_item(artifact, "charts", chart_id)
    if spec is None:
        return []
    frame = frame_for_dataset(artifact, spec["dataset"])
    field = spec.get("encodings", {}).get("color", {}).get("field")
    if not field or field not in frame.columns:
        return []
    raw_values = [str(value) for value in frame[field].dropna().drop_duplicates().tolist()]
    if series_label_map:
        display_values = [series_label_map.get(value, value) for value in raw_values]
        selected_display = st.multiselect(
            tr(language, "Series to show", "显示序列"),
            display_values,
            default=display_values,
            key=f"series_all_{chart_id}",
        )
        raw_by_display = dict(zip(display_values, raw_values))
        return [raw_by_display.get(value, value) for value in selected_display]
    return st.multiselect(
        tr(language, "Series to show", "显示序列"),
        raw_values,
        default=raw_values,
        key=f"series_all_{chart_id}",
    )


def frequency_control(language: str) -> str:
    options = ["Daily", "Weekly", "Monthly"]
    formatter = lambda item: {
        "Daily": tr(language, "Daily", "日度"),
        "Weekly": tr(language, "Weekly", "周度"),
        "Monthly": tr(language, "Monthly", "月度"),
    }[item]
    if hasattr(st, "segmented_control"):
        selected = st.segmented_control(
            tr(language, "Granularity", "数据粒度"),
            options,
            default="Daily",
            format_func=formatter,
            key="immd_frequency",
        )
    else:
        selected = st.selectbox(
            tr(language, "Granularity", "数据粒度"),
            options,
            index=0,
            format_func=formatter,
            key="immd_frequency",
        )
    return selected or "Daily"


def monthly_quarterly_control(language: str, key: str) -> str:
    options = ["Monthly", "Quarterly"]
    formatter = lambda item: {
        "Monthly": tr(language, "Monthly", "月度"),
        "Quarterly": tr(language, "Quarterly", "季度"),
    }[item]
    if hasattr(st, "segmented_control"):
        selected = st.segmented_control(
            tr(language, "Granularity", "数据粒度"),
            options,
            default="Quarterly",
            format_func=formatter,
            key=key,
        )
    else:
        selected = st.selectbox(
            tr(language, "Granularity", "数据粒度"),
            options,
            index=1,
            format_func=formatter,
            key=key,
        )
    return selected or "Quarterly"


def section_heading(language: str, english: str, chinese: str, note_en: str = "", note_zh: str = "") -> None:
    st.markdown(f'<div class="am-section"><div class="am-kicker">{tr(language, english, chinese)}</div></div>', unsafe_allow_html=True)
    if note_en or note_zh:
        st.caption(tr(language, note_en, note_zh))


def render_header(
    artifact: dict[str, Any],
    labels: dict[str, Any],
    language: str,
    sector_key: str,
    *,
    title_override: str | None = None,
    description_override: str | None = None,
) -> None:
    manifest = labels["manifest"]
    title = title_override or manifest.get("title", SECTORS[sector_key]["name_en"])
    description = description_override or manifest.get("description", "")
    st.markdown(f'<div class="am-page-title">{escape(title)}</div>', unsafe_allow_html=True)
    st.caption(description)
    region_en, region_zh = ("Global", "全球") if sector_key == "regime" else ("Hong Kong", "香港")
    region = escape(tr(language, region_en, region_zh))
    snapshot_label = escape(tr(language, "Snapshot as of", "数据截至"))
    data_as_of = escape(str(artifact.get("package_info", {}).get("dataAsOf", "—")))
    source_label = escape(
        tr(
            language,
            "Source-backed local artifact",
            "基于来源的本地数据快照",
        )
    )
    st.markdown(
        f'<div class="am-meta">{region} · {snapshot_label} {data_as_of} · {source_label}</div>',
        unsafe_allow_html=True,
    )
