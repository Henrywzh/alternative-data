"""Build the Streamlit artifact for the global market-regime radar.

This is a Streamlit-only research-terminal surface. Cloudflare packaging is
intentionally out of V1 scope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = ROOT / "src"
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from src.global_market_regime.config import (
    DERIVED_DIR,
    FRED_SERIES,
    NORMALIZED_DIR,
    STATE_SEVERITY,
)
from src.global_market_regime.alerts import load_alert_state
from src.global_market_regime.presentation import (
    build_cross_asset_returns,
    build_domain_summary,
    build_regime_summary,
    build_state_transitions,
    build_threshold_monitor,
)
from src.global_market_regime.storage import atomic_write_texts, load_latest_with_lineage
from src.global_market_regime.validation import (
    build_event_forward_returns,
    build_signal_episodes,
    build_threshold_sensitivity,
    summarize_event_forward_returns,
)
from history_policy import history_window

CHART_HISTORY_YEARS = 5


def _records(frame: pd.DataFrame, columns: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    out = frame.copy()
    if columns:
        keep = [name for name in columns if name in out.columns]
        out = out[keep]
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
        elif col in {"date", "observation_date", "reference_start", "meeting_date"}:
            parsed = pd.to_datetime(out[col], errors="coerce")
            out[col] = parsed.dt.strftime("%Y-%m-%d").where(parsed.notna(), None)
    # Round bulky floats so the committed JSON stays compact.
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].round(4)
    return json.loads(out.to_json(orient="records", date_format="iso", default_handler=str))


def _load(name: str, *, derived: bool = False) -> tuple[pd.DataFrame, dict[str, Any] | None]:
    root = DERIVED_DIR if derived else NORMALIZED_DIR
    return load_latest_with_lineage(root, name, scope="full")


def _normalize_fomc_columns(latest: pd.DataFrame) -> pd.DataFrame:
    """Migrate legacy snapshots that overloaded reference_start/target_range.

    Older runs stored the Polymarket event slug in reference_start and the FOMC
    meeting date in target_range. Atlanta MPT hike_prob rows legitimately use
    both columns with their original meanings (SOFR window start date, current
    target-range string), so only fomc_hike rows are migrated.
    """
    if latest is None or latest.empty or "indicator_id" not in latest.columns:
        return latest
    out = latest.copy()
    mask = out["indicator_id"].astype(str).eq("fomc_hike")
    if not mask.any():
        return out
    for column in ("meeting_date", "event_slug"):
        if column not in out.columns:
            out[column] = None
    if "reference_start" not in out.columns:
        out["reference_start"] = None
    if "target_range" not in out.columns:
        out["target_range"] = None
    legacy_slug = out.loc[mask, "reference_start"]
    legacy_meeting = out.loc[mask, "target_range"]
    out.loc[mask, "event_slug"] = out.loc[mask, "event_slug"].fillna(legacy_slug)
    out.loc[mask, "meeting_date"] = out.loc[mask, "meeting_date"].fillna(legacy_meeting)
    out.loc[mask, "reference_start"] = None
    out.loc[mask, "target_range"] = None
    return out


def _strict_true(value: Any) -> bool:
    """Accept only an actual boolean true from internal contracts."""
    return type(value) is bool and value


def _build_alert_status(
    summary: dict[str, Any],
    domains: pd.DataFrame,
    alert_state: dict[str, Any],
    *,
    latest_run_id: str | None,
) -> dict[str, Any]:
    """Expose the persisted pipeline decision without recomputing it in the UI."""
    last_evaluation_at = alert_state.get("last_evaluation_at")
    last_decision = alert_state.get("last_decision")
    evaluation_run_id = alert_state.get("last_run_id")
    evaluation_available = bool(last_evaluation_at and last_decision)
    evaluated_at = pd.to_datetime(last_evaluation_at, errors="coerce", utc=True)
    evaluation_current = bool(
        evaluation_available
        and pd.notna(evaluated_at)
        and evaluation_run_id
        and latest_run_id
        and str(evaluation_run_id) == str(latest_run_id)
    )

    raw_events = alert_state.get("last_component_events")
    component_events = (
        [dict(event) for event in raw_events if isinstance(event, dict)][-16:]
        if isinstance(raw_events, list) and evaluation_current
        else []
    )
    confirmed_domain_ids: list[str] = []
    if (
        domains is not None
        and not domains.empty
        and {"domain_id", "state"}.issubset(domains.columns)
    ):
        confirmed_domain_ids = (
            domains.loc[
                domains["state"]
                .astype(str)
                .map(lambda value: STATE_SEVERITY.get(value, 0))
                .ge(STATE_SEVERITY["Confirmed"]),
                "domain_id",
            ]
            .dropna()
            .astype(str)
            .tolist()
        )
    defensive_eligible = _strict_true(summary.get("defensive_alert_eligible"))
    alert_eligible = _strict_true(summary.get("alert_eligible"))
    persisted_decision = str(last_decision or "")
    if not alert_eligible or not evaluation_current:
        decision_id = "unavailable"
    elif (
        persisted_decision in {"defensive", "defensive_eligible"}
        and component_events
        and defensive_eligible
    ):
        decision_id = "defensive_eligible"
    elif (
        persisted_decision == "component_preview"
        and component_events
        and not defensive_eligible
    ):
        decision_id = "component_preview"
    elif persisted_decision == "quiet" and not component_events:
        decision_id = "quiet"
    elif persisted_decision == "manual":
        decision_id = "manual"
    else:
        decision_id = "unavailable"
        component_events = []
    alert_mode = str(alert_state.get("alert_mode") or "preview")
    would_send = bool(
        decision_id == "defensive_eligible" and alert_eligible and evaluation_current
    )
    return {
        "decision_id": decision_id,
        "evaluation_current": evaluation_current,
        "evaluation_run_id": evaluation_run_id,
        "latest_run_id": latest_run_id,
        "new_transition_count": len(component_events),
        "component_events": component_events,
        "confirmed_domain_count": int(summary.get("confirmed_domain_count") or 0),
        "confirmed_domain_ids": confirmed_domain_ids,
        "total_domain_count": int(summary.get("total_domain_count") or 0),
        "financial_stress_exception": "financial_stress" in confirmed_domain_ids,
        "would_send_in_defensive_mode": would_send,
        "should_send": bool(
            would_send
            and alert_mode == "defensive"
            and persisted_decision == "defensive"
        ),
        "alert_eligible": alert_eligible,
        "defensive_alert_eligible": defensive_eligible,
        "breadth_id": summary.get("breadth_id"),
        "active_domain_ids": summary.get("active_domain_ids"),
        "last_sent_at": summary.get("last_sent_at"),
        "last_evaluation_at": last_evaluation_at,
        "last_decision": last_decision,
        "alert_mode": alert_mode,
        "overall_state": summary.get("overall_state"),
    }


def _localized_zh_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    """Localize reader-facing metadata while preserving the EN data contract."""
    localized = json.loads(json.dumps(artifact, ensure_ascii=False, default=str))
    localized["manifest"]["title"] = "全球市场状态"
    localized["manifest"]["description"] = (
        "原油、长端利率、政策预期、信用与波动的防守雷达。"
    )
    source_names = {
        "FRED / EIA": "FRED／美国能源信息署",
        "FRED / Treasury H.15": "FRED／美国财政部 H.15",
        "FRED / CBOE": "FRED／芝加哥期权交易所",
        "FRED / ICE BofA": "FRED／ICE 美银",
        "FRED / Federal Reserve": "FRED／美联储",
        "Atlanta Fed Market Probability Tracker": "亚特兰大联储市场概率追踪器",
        "CFTC Commitments of Traders": "美国商品期货交易委员会持仓报告",
        "Polymarket FOMC": "Polymarket FOMC 预测市场",
        "Asia Markets index monitor": "Asia Markets 指数监控",
    }
    note_templates = {
        "DCOILBRENTEU": "布伦特原油日度数据，截至{date}。",
        "DGS10": "美国10年期国债收益率日度数据，截至{date}。",
        "DGS2": "美国2年期国债收益率日度数据，截至{date}。",
        "VIXCLS": "VIX日度数据，截至{date}。",
        "BAMLH0A0HYM2": "美国高收益债期权调整利差日度数据，截至{date}。",
        "DCOILWTICO": "WTI原油日度数据，截至{date}。",
        "DTWEXAFEGS": "美元发达经济体指数日度数据，截至{date}。",
        "atlanta_mpt": "最近剩余三个月SOFR窗口的概率分布，截至{date}。",
        "cftc_cot": "CFTC杠杆／管理资金净头寸，截至{date}；已覆盖全部7个注册合约。",
        "polymarket_fomc": "下次FOMC会议加息／维持／降息预测市场价格；不是CME FedWatch。",
        "market_monitor_prices": "复用Asia Markets市场监控的日度指数收盘价，截至{date}；已覆盖全部8个预期指数。",
    }
    health_rows = localized.get("snapshot", {}).get("datasets", {}).get(
        "source_health", []
    )
    for row in health_rows:
        row["source"] = source_names.get(str(row.get("source")), row.get("source"))
        template = note_templates.get(str(row.get("series_id")))
        if template and str(row.get("status")) == "Healthy":
            row["notes"] = template.format(
                date=row.get("latest_observation") or "—"
            )
        elif str(row.get("status")) != "Healthy" and row.get("notes"):
            row["notes"] = f"来源状态异常：{row['notes']}"
    source_labels = {
        spec["indicator_id"]: f"{source_names.get(spec['source'], spec['source'])} · {spec['label_zh']}"
        for spec in FRED_SERIES
    }
    source_labels.update(
        {
            "atlanta_mpt": "亚特兰大联储市场概率追踪器",
            "cftc_cot": "美国商品期货交易委员会持仓报告",
            "polymarket_fomc": "Polymarket FOMC 预测市场",
            "market_monitor_prices": "Asia Markets 指数监控",
        }
    )
    for source in localized.get("sources", []):
        source_id = str(source.get("id") or "")
        if source_id in source_labels:
            source["label"] = source_labels[source_id]
    chart_meta = {
        "brent_history_chart": (
            "布伦特原油",
            "FRED 提供的 EIA 欧洲布伦特现货价。持续收于 100 美元上方是 V1 原油压力门槛。",
        ),
        "us10y_history_chart": (
            "美国10年期国债收益率",
            "美国财政部固定期限 10 年期收益率（%）。V1 关注是否持续突破 4.82%。",
        ),
        "hike_probability_chart": (
            "近端 SOFR 相对当前 FOMC 目标",
            "亚特兰大联储市场概率追踪器：三个月平均 SOFR 高于当前目标区间收尾的概率。不是 CME FedWatch 逐次会议赔率。",
        ),
        "fomc_odds_chart": (
            "下次 FOMC 会议赔率",
            "下一次美联储决议事件的 Polymarket 价格。这是预测市场价格，不是 CME FedWatch，也不是亚特兰大联储 SOFR 概率。",
        ),
        "credit_vix_chart": (
            "高收益债利差与 VIX",
            "ICE 美银美国高收益债 OAS 与 CBOE VIX。同步压力要求两者 5 日变化同为正，且 20 日 z 分数在同一天均高于 +1。",
        ),
        "cross_asset_chart": (
            "跨资产表现背景",
            "复用现有市场监控指数收盘价作为背景参考，不作为第二价格存储。",
        ),
    }
    for chart in localized.get("manifest", {}).get("charts", []):
        meta = chart_meta.get(str(chart.get("id")))
        if meta:
            chart["title"], chart["subtitle"] = meta
    table_titles = {
        "regime_state_table": "当前防守状态",
        "cot_latest_table": "CFTC 管理／杠杆资金持仓",
    }
    for table in localized.get("manifest", {}).get("tables", []):
        title = table_titles.get(str(table.get("id")))
        if title:
            table["title"] = title
    return localized


def build_artifact() -> tuple[dict[str, Any], dict[str, Any]]:
    now = datetime.now(timezone.utc)
    generated_at = now.isoformat().replace("+00:00", "Z")
    fred, fred_lineage = _load("fred_observations")
    hike, hike_lineage = _load("hike_probability")
    states, states_lineage = _load("condition_states", derived=True)
    latest, latest_lineage = _load("latest_conditions", derived=True)
    latest = _normalize_fomc_columns(latest)
    health, health_lineage = _load("source_health", derived=True)
    prices, prices_lineage = _load("cross_asset_prices", derived=True)
    cot_history, cot_history_lineage = _load("cot_history")
    cot, cot_lineage = _load("cot_latest", derived=True)
    if cot.empty and not cot_history.empty:
        cot = cot_history.sort_values("date").groupby("contract_id", as_index=False).tail(1)
        cot_lineage = cot_history_lineage
    fomc, fomc_lineage = _load("fomc_history")

    required_lineages = (
        fred_lineage,
        hike_lineage,
        states_lineage,
        latest_lineage,
        health_lineage,
        prices_lineage,
        cot_lineage,
        cot_history_lineage,
        fomc_lineage,
    )
    run_ids = {
        lineage.get("run_id")
        for lineage in required_lineages
        if lineage and lineage.get("run_id")
    }
    run_consistent = bool(run_ids) and len(run_ids) == 1 and all(
        lineage and lineage.get("run_id") for lineage in required_lineages
    )
    latest_run_id = next(iter(run_ids)) if len(run_ids) == 1 else None

    fred_chart = history_window(fred, "date", years=CHART_HISTORY_YEARS) if not fred.empty else fred
    prices_chart = history_window(prices, "date", years=CHART_HISTORY_YEARS) if not prices.empty else prices
    hike_windowed = history_window(hike, "date", years=CHART_HISTORY_YEARS) if not hike.empty else hike
    if not hike_windowed.empty:
        dist_rows = []
        for field, series in (("value", "Above target"), ("hold_prob", "Inside target"), ("cut_prob", "Below target")):
            if field in hike_windowed.columns:
                part = hike_windowed[["date", field]].copy()
                part["series"] = series
                part["value"] = pd.to_numeric(part[field], errors="coerce")
                dist_rows.append(part[["date", "series", "value"]])
        hike_dist = pd.concat(dist_rows, ignore_index=True) if dist_rows else pd.DataFrame()
    else:
        hike_dist = pd.DataFrame()
    latest_slim_cols = (
        "indicator_id",
        "label_en",
        "label_zh",
        "state",
        "value",
        "observation_date",
        "freshness",
        "reference_start",
        "target_range",
        "meeting_date",
        "event_slug",
        "cut_prob",
        "hold_prob",
        "hy_z",
        "vix_z",
        "consecutive_breach",
    )
    monitor = build_threshold_monitor(latest, states, fomc_history=fomc)
    alert_state = load_alert_state()
    summary = build_regime_summary(monitor, alert_state=alert_state)
    domain_summary = build_domain_summary(monitor)
    transitions = build_state_transitions(states)
    label_columns = [
        column
        for column in ("indicator_id", "label_en", "label_zh")
        if column in latest.columns
    ]
    if not transitions.empty and len(label_columns) > 1:
        transitions = transitions.merge(
            latest[label_columns].drop_duplicates("indicator_id"),
            on="indicator_id",
            how="left",
        )
    states_windowed = (
        history_window(states, "date", years=CHART_HISTORY_YEARS)
        if not states.empty
        else states
    )
    credit_vix = (
        states_windowed[
            states_windowed["indicator_id"].astype(str).eq("credit_vix")
        ].copy()
        if not states_windowed.empty and "indicator_id" in states_windowed.columns
        else pd.DataFrame()
    )
    cot_windowed = (
        history_window(cot_history, "date", years=CHART_HISTORY_YEARS)
        if not cot_history.empty
        else cot_history
    )
    cross_asset_returns = build_cross_asset_returns(prices)
    signal_episodes = build_signal_episodes(states)
    threshold_sensitivity = build_threshold_sensitivity(states)
    event_forward_returns = build_event_forward_returns(states, prices)
    event_forward_summary = summarize_event_forward_returns(event_forward_returns)
    fomc_windowed = history_window(fomc, "date", years=CHART_HISTORY_YEARS) if not fomc.empty else fomc
    if not fomc_windowed.empty:
        fomc_rows = []
        for field, series in (("hike_prob", "Hike"), ("hold_prob", "Hold"), ("cut_prob", "Cut")):
            if field in fomc_windowed.columns:
                part = fomc_windowed[["date", field]].copy()
                part["series"] = series
                part["value"] = pd.to_numeric(part[field], errors="coerce")
                fomc_rows.append(part[["date", "series", "value"]])
        fomc_dist = pd.concat(fomc_rows, ignore_index=True) if fomc_rows else pd.DataFrame()
    else:
        fomc_dist = pd.DataFrame()
    datasets: dict[str, Any] = {
        "fred_observations": _records(fred_chart, ("date", "indicator_id", "value", "unit")),
        "hike_distribution": _records(hike_dist, ("date", "series", "value")),
        "fomc_distribution": _records(fomc_dist, ("date", "series", "value")),
        "cot_latest": _records(
            cot,
            ("date", "contract_id", "label_en", "label_zh", "group", "report", "net", "weekly_change", "percentile", "position_label", "long_pos", "short_pos"),
        ),
        "cot_history": _records(
            cot_windowed,
            ("date", "contract_id", "label_en", "label_zh", "net", "percentile"),
        ),
        "latest_conditions": _records(latest, latest_slim_cols),
        "threshold_monitor": _records(monitor),
        "domain_summary": _records(domain_summary),
        "regime_summary": [summary],
        "condition_state_history": _records(
            states_windowed,
            (
                "date",
                "indicator_id",
                "value",
                "state",
                "breached",
                "consecutive_breach",
                "hy_oas",
                "vix",
                "hy_change_5d",
                "vix_change_5d",
                "hy_z",
                "vix_z",
            ),
        ),
        "state_transition_history": _records(
            transitions.tail(200),
            (
                "date",
                "indicator_id",
                "label_en",
                "label_zh",
                "prior_state",
                "state",
                "value",
            ),
        ),
        "credit_vix_signal_history": _records(
            credit_vix,
            (
                "date",
                "hy_z",
                "vix_z",
                "hy_change_5d",
                "vix_change_5d",
                "hy_oas",
                "vix",
                "state",
            ),
        ),
        "source_health": _records(health, ("source", "series_id", "status", "latest_observation", "records", "notes")),
        "cross_asset_prices": _records(prices_chart, ("date", "exposure_id", "close")),
        "cross_asset_returns": _records(cross_asset_returns),
        "signal_episodes": _records(signal_episodes),
        "threshold_sensitivity": _records(threshold_sensitivity),
        "event_forward_returns": _records(event_forward_returns),
        "event_forward_summary": _records(event_forward_summary),
        "alert_status": [
            _build_alert_status(
                summary,
                domain_summary,
                alert_state,
                latest_run_id=latest_run_id,
            )
        ],
        "kpi_regime": [],
    }
    data_as_of = None
    for frame in (latest, hike, fred):
        if frame is not None and not frame.empty and "date" in frame.columns:
            data_as_of = pd.to_datetime(frame["date"], errors="coerce").max()
            break
        if frame is not None and not frame.empty and "observation_date" in frame.columns:
            data_as_of = pd.to_datetime(frame["observation_date"], errors="coerce").max()
            break
    data_as_of_text = data_as_of.strftime("%Y-%m-%d") if data_as_of is not None and not pd.isna(data_as_of) else now.date().isoformat()
    if latest is not None and not latest.empty:
        kpi_row = {"observation_date": data_as_of_text, "overall_state": "Normal"}
        for row in latest.to_dict("records"):
            indicator = str(row.get("indicator_id") or "")
            if not indicator:
                continue
            if indicator == "hike_prob":
                kpi_row["hike_prob"] = row.get("value")
                kpi_row["hike_state"] = row.get("state")
            elif indicator == "brent":
                kpi_row["brent"] = row.get("value")
                kpi_row["brent_state"] = row.get("state")
            elif indicator == "us10y":
                kpi_row["us10y"] = row.get("value")
            elif indicator == "credit_vix":
                kpi_row["credit_vix_state"] = row.get("state")
            elif indicator == "fomc_hike":
                kpi_row["fomc_hike"] = row.get("value")
                kpi_row["fomc_state"] = row.get("state")
        kpi_row["overall_state"] = summary.get("overall_state") or "Unavailable"
        kpi_row["breadth_en"] = summary.get("breadth_en")
        kpi_row["breadth_zh"] = summary.get("breadth_zh")
        kpi_row["active_domain_count"] = summary.get("active_domain_count")
        datasets["kpi_regime"] = [kpi_row]


    charts = [
        {
            "id": "brent_history_chart",
            "title": "Brent crude",
            "subtitle": "EIA Europe Brent spot via FRED. Persistent closes above $100 are the V1 oil stress gate.",
            "type": "line",
            "dataset": "fred_observations",
            "sourceId": "brent",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Date"},
                "y": {"field": "value", "type": "quantitative", "label": "USD/bbl"},
                "color": {"field": "indicator_id", "type": "nominal", "label": "Series"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "us10y_history_chart",
            "title": "US 10-year yield",
            "subtitle": "Treasury constant-maturity 10-year yield, in percent. V1 watches a sustained break above 4.82%.",
            "type": "line",
            "dataset": "fred_observations",
            "sourceId": "us10y",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Date"},
                "y": {"field": "value", "type": "quantitative", "label": "Percent"},
                "color": {"field": "indicator_id", "type": "nominal", "label": "Series"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "hike_probability_chart",
            "title": "Near-term SOFR vs current FOMC target",
            "subtitle": "Atlanta Fed Market Probability Tracker: probability that 3-month average SOFR finishes above the current target range. This is not CME FedWatch meeting odds.",
            "type": "line",
            "dataset": "hike_distribution",
            "sourceId": "atlanta_mpt",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Date"},
                "y": {"field": "value", "type": "quantitative", "label": "Probability %"},
                "color": {"field": "series", "type": "nominal", "label": "Bucket"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "fomc_odds_chart",
            "title": "Next FOMC meeting odds",
            "subtitle": "Polymarket prices for the next scheduled Fed Decision event. This is a prediction-market price, not CME FedWatch and not Atlanta Fed SOFR odds.",
            "type": "line",
            "dataset": "fomc_distribution",
            "sourceId": "polymarket_fomc",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Date"},
                "y": {"field": "value", "type": "quantitative", "label": "Probability %"},
                "color": {"field": "series", "type": "nominal", "label": "Outcome"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "credit_vix_chart",
            "title": "High-yield OAS and VIX",
            "subtitle": "ICE BofA US High Yield OAS and CBOE VIX. Sync stress requires both 5-day changes positive and both 20-day z-scores above +1 on a shared date.",
            "type": "line",
            "dataset": "fred_observations",
            "sourceId": "hy_oas",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Date"},
                "y": {"field": "value", "type": "quantitative", "label": "Level"},
                "color": {"field": "indicator_id", "type": "nominal", "label": "Series"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "cross_asset_chart",
            "title": "Cross-asset performance context",
            "subtitle": "Existing market-monitor index closes reused as context, not as a second price store.",
            "type": "line",
            "dataset": "cross_asset_prices",
            "sourceId": "market_monitor_prices",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Date"},
                "y": {"field": "close", "type": "quantitative", "label": "Index level"},
                "color": {"field": "exposure_id", "type": "nominal", "label": "Exposure"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
    ]
    tables = [
        {
            "id": "regime_state_table",
            "title": "Current defensive states",
            "dataset": "latest_conditions",
            "columns": [
                {"field": "label_en", "label": "Indicator", "format": "text"},
                {"field": "state", "label": "State", "format": "text"},
                {"field": "value", "label": "Latest", "format": "number"},
                {"field": "observation_date", "label": "Observation", "format": "text"},
                {"field": "freshness", "label": "Freshness", "format": "text"},
            ],
        },
        {
            "id": "cot_latest_table",
            "title": "CFTC managed / leveraged-money positioning",
            "dataset": "cot_latest",
            "columns": [
                {"field": "label_en", "label": "Contract", "format": "text"},
                {"field": "net", "label": "Net",
                 "format": "number"},
                {"field": "weekly_change", "label": "Weekly change", "format": "number"},
                {"field": "percentile", "label": "History percentile", "format": "number"},
                {"field": "position_label", "label": "Reading", "format": "text"},
                {"field": "report", "label": "Report", "format": "text"},
            ],
        }
    ]
    fomc_slug = ""
    if latest is not None and not latest.empty and "indicator_id" in latest.columns:
        fomc_rows = latest[latest["indicator_id"].astype(str).eq("fomc_hike")]
        if not fomc_rows.empty:
            fomc_slug = str(fomc_rows.iloc[-1].get("event_slug") or "").strip()
    polymarket_href = (
        f"https://polymarket.com/event/{fomc_slug}"
        if fomc_slug and all(char.isalnum() or char in {"-", "_"} for char in fomc_slug)
        else "https://polymarket.com"
    )
    sources = [
        {
            "id": spec["indicator_id"],
            "label": spec["source"] + " · " + spec["label_en"],
            "href": spec["href"],
            "query": {"engine": "FRED API", "series_id": spec["series_id"]},
        }
        for spec in FRED_SERIES
    ] + [
        {
            "id": "atlanta_mpt",
            "label": "Atlanta Fed Market Probability Tracker",
            "href": "https://www.atlantafed.org/research-and-data/data/market-probability-tracker",
            "query": {"engine": "official Excel historical file", "description": "3-month average SOFR option-implied distribution, not meeting-by-meeting FedWatch odds."},
        },
        {
            "id": "cftc_cot",
            "label": "CFTC Commitments of Traders",
            "href": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
            "query": {"engine": "CFTC Socrata TFF + disaggregated reports", "description": "Financials use leveraged-money; gold/WTI use managed-money. Weekly, usually published Friday for the prior Tuesday."},
        },
        {
            "id": "polymarket_fomc",
            "label": "Polymarket Fed Decision",
            "href": polymarket_href,
            "query": {"engine": "Gamma search + CLOB prices-history", "description": "Prediction-market prices for the next open Fed Decision event; not CME FedWatch."},
        },
        {
            "id": "market_monitor_prices",
            "label": "Asia Markets index monitor",
            "href": "",
            "query": {"engine": "existing normalized market-monitor prices", "description": "Shared daily index closes used only for cross-asset context."},
        }
    ]
    all_sources_healthy = bool(
        not health.empty
        and "status" in health.columns
        and health["status"].astype(str).eq("Healthy").all()
    )
    expected_health_series = {
        *(str(spec["series_id"]) for spec in FRED_SERIES),
        "atlanta_mpt",
        "cftc_cot",
        "polymarket_fomc",
        "market_monitor_prices",
    }
    observed_health_series = (
        set(health["series_id"].dropna().astype(str))
        if not health.empty and "series_id" in health.columns
        else set()
    )
    expected_conditions = {"brent", "us10y", "hike_prob", "fomc_hike", "credit_vix"}
    observed_conditions = (
        set(monitor["indicator_id"].dropna().astype(str))
        if not monitor.empty and "indicator_id" in monitor.columns
        else set()
    )
    required_frames_present = all(
        frame is not None and not frame.empty
        for frame in (fred, hike, states, latest, health, prices, cot_history, fomc)
    )
    overall_status = (
        "Healthy"
        if (
            run_consistent
            and required_frames_present
            and all_sources_healthy
            and expected_health_series <= observed_health_series
            and expected_conditions <= observed_conditions
        )
        else "Degraded"
    )
    snapshot_id = hashlib.sha1(json.dumps(datasets, sort_keys=True, default=str).encode()).hexdigest()[:16]
    artifact = {
        "manifest": {
            "version": 1,
            "generatedAt": generated_at,
            "title": "Global Market Regime",
            "description": "Defensive radar for oil, Treasury yields, SOFR-implied policy odds, credit spreads and VIX.",
            "sector": "global-market-regime",
            "cards": [],
            "charts": charts,
            "tables": tables,
            "blocks": [{"id": "regime_state_block", "type": "table", "tableId": "regime_state_table"}],
            "sources": [row["id"] for row in sources],
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready" if overall_status == "Healthy" else "partial",
            "datasets": datasets,
        },
        "sources": sources,
        "package_info": {
            "snapshotId": snapshot_id,
            "dataAsOf": data_as_of_text,
            "pipelineRunId": latest_run_id,
            "runConsistent": run_consistent,
            "upstreamMarketMonitorRunId": (
                (prices_lineage or {}).get("upstream_market_monitor_run_id")
            ),
        },
    }
    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": data_as_of_text,
        "overall_status": overall_status,
        "live_sources": 0 if health.empty else int(health["status"].eq("Healthy").sum()),
        "sources": _records(health),
    }
    return artifact, status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact, status = build_artifact()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(artifact, separators=(",", ":"), ensure_ascii=False, default=str)
    zh_path = args.output.with_name(args.output.name.replace("-artifact.json", "-artifact-zh.json"))
    zh_payload = json.dumps(
        _localized_zh_artifact(artifact),
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    atomic_write_texts(
        {
            args.output: payload,
            zh_path: zh_payload,
        }
    )
    print(json.dumps({"ok": True, "artifact": str(args.output), "snapshot_id": status["snapshot_id"], "data_as_of": status["data_as_of"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
