"""Global market regime page assembly and regime UI.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

from html import escape
import json
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .config import PALETTE

from .core import _regime_has_columns, _regime_history_window, _regime_state_label, chart_theme, frame_for_dataset, is_missing, observation_date_label, render_header, render_line_chart, section_heading, source_health_frame, tr

from .explorer import render_source_coverage

from .regime_labels import COT_LABELS_ZH, FOMC_DIST_LABELS_ZH, REGIME_DIST_LABELS_ZH, REGIME_DOMAIN_LABELS, REGIME_EXPOSURE_LABELS, REGIME_FRESHNESS_LABELS_ZH, REGIME_FRESHNESS_OK, REGIME_SERIES_LABELS, REGIME_SERIES_LABELS_ZH

from .regime_evidence import (
    render_cnn_fear_greed,
    render_cnn_fear_greed_components,
    render_cot_history,
    render_credit_vix_evidence,
    render_cross_asset_context,
    render_inflation_heatmap,
    render_macro_commodity_table,
    render_regime_validation,
    render_vix_history,
)


def _strict_contract_true(value: Any) -> bool:
    """Treat malformed artifact booleans as false instead of using truthiness."""
    return type(value) is bool and value


def _regime_evaluation_time_label(value: Any, language: str) -> str:
    if is_missing(value):
        return "—"
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return str(value)
    local = parsed.tz_convert("Asia/Taipei")
    if language == "zh":
        return (
            f"{local.year}年{local.month}月{local.day}日 "
            f"{local.strftime('%H:%M')}（UTC+8）"
        )
    return f"{local.strftime('%d %b %Y %H:%M')} (UTC+8)"


def _regime_value_text(row: dict[str, Any], language: str) -> str:
    indicator = str(row.get("indicator_id") or "")
    if indicator == "credit_vix":
        hy_z = pd.to_numeric(pd.Series([row.get("hy_z")]), errors="coerce").iloc[0]
        vix_z = pd.to_numeric(pd.Series([row.get("vix_z")]), errors="coerce").iloc[0]
        if pd.isna(hy_z) or pd.isna(vix_z):
            return "—"
        return f"HY {hy_z:.2f}σ / VIX {vix_z:.2f}σ"
    value = pd.to_numeric(pd.Series([row.get("value")]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "—"
    if indicator == "brent":
        return f"${value:.2f}"
    if indicator == "us10y":
        return f"{value:.2f}%"
    if indicator in {"hike_prob", "fomc_hike"}:
        return f"{value:.1f}%"
    return f"{value:.2f}"


def _regime_distance_text(row: dict[str, Any], language: str) -> str:
    distance = pd.to_numeric(pd.Series([row.get("distance")]), errors="coerce").iloc[0]
    if pd.isna(distance):
        return tr(language, "Distance unavailable", "距离不可用")
    unit = str(row.get("distance_unit") or "")
    unit_label = {
        "bp": "bp",
        "pp": tr(language, "pp", "百分点"),
        "USD/bbl": tr(language, "USD/bbl", "美元/桶"),
        "z": "σ",
    }.get(unit, unit)
    if abs(float(distance)) < 1e-9:
        return tr(language, "at threshold", "位于门槛")
    relation = tr(language, "above", "高于") if distance >= 0 else tr(language, "below", "低于")
    return f"{relation} {abs(distance):.1f} {unit_label}"


def regime_visual_state(row: dict[str, Any]) -> str:
    """Do not color stale or invalid observations as active current risk."""
    freshness = str(row.get("freshness") or "")
    if freshness and freshness not in REGIME_FRESHNESS_OK:
        return "Unavailable"
    return str(row.get("state") or "Unavailable")


def _regime_threshold_value_text(row: dict[str, Any]) -> str:
    indicator = str(row.get("indicator_id") or "")
    threshold = pd.to_numeric(pd.Series([row.get("threshold")]), errors="coerce").iloc[0]
    if pd.isna(threshold):
        return "—"
    if indicator == "brent":
        return f"${threshold:.2f}"
    if indicator == "us10y":
        return f"{threshold:.2f}%"
    if indicator in {"hike_prob", "fomc_hike"}:
        return f"{threshold:.1f}%"
    if indicator == "credit_vix":
        return f"{threshold:.1f}σ"
    return f"{threshold:.2f}"


def regime_daily_brief_items(
    artifact: dict[str, Any],
    language: str,
) -> list[dict[str, str]]:
    """Compress current monitor rows into a small decision-first briefing."""
    monitor = frame_for_dataset(artifact, "threshold_monitor")
    summary = frame_for_dataset(artifact, "regime_summary")
    if monitor.empty or summary.empty or "indicator_id" not in monitor.columns:
        return []
    monitor = monitor.copy()
    monitor["indicator_id"] = monitor["indicator_id"].astype(str)
    by_id = {
        str(row["indicator_id"]): row
        for row in monitor.to_dict("records")
    }
    summary_row = summary.iloc[-1].to_dict()
    items: list[dict[str, str]] = []

    primary_ids = summary_row.get("primary_driver_ids")
    if isinstance(primary_ids, list) and primary_ids:
        primary = by_id.get(str(primary_ids[0]))
        if primary and str(primary.get("freshness") or "") in REGIME_FRESHNESS_OK:
            progress = int(
                pd.to_numeric(
                    pd.Series([primary.get("confirmation_progress")]),
                    errors="coerce",
                )
                .fillna(0)
                .iloc[0]
            )
            required = int(
                pd.to_numeric(
                    pd.Series([primary.get("confirmation_required")]),
                    errors="coerce",
                )
                .fillna(0)
                .iloc[0]
            )
            label = primary.get(
                "label_zh" if language == "zh" else "label_en"
            ) or primary.get("indicator_id")
            items.append(
                {
                    "id": "primary_driver",
                    "label": tr(
                        language,
                        f"Primary driver · {label}",
                        f"主导风险 · {label}",
                    ),
                    "value": _regime_value_text(primary, language),
                    "note": (
                        f"{_regime_distance_text(primary, language)} · "
                        + tr(
                            language,
                            f"confirmed {progress}/{required}",
                            f"连续确认 {progress}/{required}",
                        )
                    ),
                    "state": str(primary.get("state") or "Unavailable"),
                }
            )

    nearest_candidates: list[tuple[float, dict[str, Any]]] = []
    for row in monitor.to_dict("records"):
        indicator = str(row.get("indicator_id") or "")
        if indicator not in {"brent", "us10y", "hike_prob", "fomc_hike"}:
            continue
        state = str(row.get("state") or "Unavailable")
        freshness = str(row.get("freshness") or "")
        value = pd.to_numeric(pd.Series([row.get("value")]), errors="coerce").iloc[0]
        threshold = pd.to_numeric(
            pd.Series([row.get("threshold")]), errors="coerce"
        ).iloc[0]
        distance = pd.to_numeric(
            pd.Series([row.get("distance")]), errors="coerce"
        ).iloc[0]
        if (
            state == "Normal"
            and freshness in REGIME_FRESHNESS_OK
            and not pd.isna(value)
            and not pd.isna(threshold)
            and threshold > 0
            and not pd.isna(distance)
            and distance <= 0
        ):
            nearest_candidates.append((float(value / threshold), row))
    if nearest_candidates:
        _, nearest = max(nearest_candidates, key=lambda item: item[0])
        label = nearest.get(
            "label_zh" if language == "zh" else "label_en"
        ) or nearest.get("indicator_id")
        items.append(
            {
                "id": "nearest_gate",
                "label": tr(language, "Nearest inactive gate", "最接近触发门槛"),
                "value": _regime_distance_text(nearest, language),
                "note": tr(
                    language,
                    f"{label} · current {_regime_value_text(nearest, language)} / threshold {_regime_threshold_value_text(nearest)}",
                    f"{label} · 当前 {_regime_value_text(nearest, language)}／门槛 {_regime_threshold_value_text(nearest)}",
                ),
                "state": str(nearest.get("state") or "Normal"),
            }
        )

    fomc = by_id.get("fomc_hike")
    if fomc and str(fomc.get("freshness") or "") in REGIME_FRESHNESS_OK:
        latest_change = pd.to_numeric(
            pd.Series([fomc.get("change_1obs_pp")]), errors="coerce"
        ).iloc[0]
        if not pd.isna(latest_change):
            change_text = tr(
                language,
                f"{latest_change:+.1f} pp",
                f"{latest_change:+.1f} 百分点",
            )
            items.append(
                {
                    "id": "rate_odds_change",
                    "label": tr(
                        language,
                        "Latest policy-odds move",
                        "最新利率赔率变化",
                    ),
                    "value": change_text,
                    "note": tr(
                        language,
                        f"Next-meeting hike odds now {_regime_value_text(fomc, language)}",
                        f"下次会议加息赔率现为 {_regime_value_text(fomc, language)}",
                    ),
                    "state": str(fomc.get("state") or "Unavailable"),
                }
            )

    breadth = summary_row.get(
        "breadth_zh" if language == "zh" else "breadth_en"
    ) or tr(language, "Unavailable", "不可用")
    active_domains = int(
        pd.to_numeric(
            pd.Series([summary_row.get("active_domain_count")]), errors="coerce"
        )
        .fillna(0)
        .iloc[0]
    )
    total_domains = int(
        pd.to_numeric(
            pd.Series([summary_row.get("total_domain_count")]), errors="coerce"
        )
        .fillna(0)
        .iloc[0]
    )
    credit_vix = by_id.get("credit_vix")
    financial_state = (
        _regime_state_label(regime_visual_state(credit_vix), language)
        if credit_vix
        else tr(language, "Unavailable", "不可用")
    )
    items.append(
        {
            "id": "risk_breadth",
            "label": tr(language, "Risk breadth", "风险扩散"),
            "value": str(breadth),
            "note": tr(
                language,
                f"{active_domains}/{total_domains} domains active · credit/VIX {financial_state}",
                f"{active_domains}/{total_domains}个领域异常 · 信用／VIX为{financial_state}",
            ),
            "state": str(summary_row.get("overall_state") or "Unavailable"),
        }
    )
    return items


def regime_data_warnings(
    artifact: dict[str, Any],
    language: str,
) -> list[str]:
    """Return reader-facing warnings for incomplete or stale decision inputs."""
    warnings: list[str] = []
    snapshot_status = str(artifact.get("snapshot", {}).get("status") or "")
    run_consistent = bool(artifact.get("package_info", {}).get("runConsistent"))
    if snapshot_status != "ready" or not run_consistent:
        warnings.append(
            tr(
                language,
                "This is a degraded or run-inconsistent snapshot; visible values are audit context, not a complete current reading.",
                "当前数据快照已降级或并非来自同一次完整运行；可见数值仅供核查，不代表完整的当前状态。",
            )
        )

    monitor = frame_for_dataset(artifact, "threshold_monitor")
    if monitor.empty or not {"freshness", "indicator_id"}.issubset(monitor.columns):
        warnings.append(
            tr(
                language,
                "Decision-input freshness metadata is unavailable.",
                "决策输入的新鲜度元数据不可用。",
            )
        )
    else:
        stale = monitor[~monitor["freshness"].astype(str).isin(REGIME_FRESHNESS_OK)]
        if not stale.empty:
            label_field = "label_zh" if language == "zh" else "label_en"
            labels = stale.get(label_field, stale["indicator_id"]).fillna(
                stale["indicator_id"]
            )
            warnings.append(
                tr(
                    language,
                    f"Stale or unavailable decision inputs: {', '.join(labels.astype(str))}.",
                    f"以下决策输入已过期或不可用：{'、'.join(labels.astype(str))}。",
                )
            )

    health = source_health_frame(artifact)
    if health.empty or not {"source", "status"}.issubset(health.columns):
        warnings.append(
            tr(
                language,
                "Source-health metadata is unavailable.",
                "来源健康度元数据不可用。",
            )
        )
    else:
        degraded = health[
            ~health["status"].astype(str).isin({"Healthy", "Ready"})
        ]
        if not degraded.empty:
            sources = degraded["source"].dropna().astype(str).drop_duplicates()
            warnings.append(
                tr(
                    language,
                    f"Source checks need attention: {', '.join(sources)}.",
                    f"以下来源健康检查需要留意：{'、'.join(sources)}。",
                )
            )
    return warnings


def render_regime_daily_brief(
    artifact: dict[str, Any],
    language: str,
) -> None:
    items = regime_daily_brief_items(artifact, language)
    if not items:
        return
    section_heading(
        language,
        "Today at a glance",
        "今日监测摘要",
        "The active driver, nearest inactive gate, latest rate-odds move and breadth in one scan.",
        "一眼查看主导风险、最近门槛、最新利率赔率变化及风险扩散范围。",
    )
    cards = "".join(
        (
            f'<div class="am-regime-brief-card" data-state="{escape(item["state"].lower())}">'
            f'<div class="am-regime-brief-label">{escape(item["label"])}</div>'
            f'<div class="am-regime-brief-value">{escape(item["value"])}</div>'
            f'<div class="am-regime-brief-note">{escape(item["note"])}</div>'
            "</div>"
        )
        for item in items
    )
    st.markdown(
        f'<div class="am-regime-brief-grid">{cards}</div>',
        unsafe_allow_html=True,
    )


def render_regime_summary_banner(artifact: dict[str, Any], language: str) -> None:
    summary = frame_for_dataset(artifact, "regime_summary")
    if summary.empty:
        return
    row = summary.iloc[-1].to_dict()
    state = str(row.get("overall_state") or "Unavailable")
    breadth = row.get("breadth_zh" if language == "zh" else "breadth_en") or tr(
        language, "Unavailable", "不可用"
    )
    domain_ids = row.get("active_domain_ids")
    if not isinstance(domain_ids, list):
        domain_ids = []
    domain_text = " / ".join(
        REGIME_DOMAIN_LABELS.get(str(domain_id), (str(domain_id), str(domain_id)))[
            1 if language == "zh" else 0
        ]
        for domain_id in domain_ids
    )
    explanation = row.get("explanation_zh" if language == "zh" else "explanation_en") or "—"
    observation_start = row.get("observation_start") or "—"
    observation_end = row.get("observation_end") or "—"
    active = int(pd.to_numeric(pd.Series([row.get("active_driver_count")]), errors="coerce").fillna(0).iloc[0])
    alert_ready = _strict_contract_true(row.get("alert_eligible"))
    defensive_ready = _strict_contract_true(row.get("defensive_alert_eligible"))
    alert_status = frame_for_dataset(artifact, "alert_status")
    alert_mode = (
        str(alert_status.iloc[-1].get("alert_mode") or "preview")
        if not alert_status.empty
        else "preview"
    )
    evaluation_current = (
        _strict_contract_true(alert_status.iloc[-1].get("evaluation_current"))
        if not alert_status.empty
        else False
    )
    if not evaluation_current:
        alert_note = tr(
            language,
            "Alert decision unavailable for this data run",
            "当前数据运行没有可用的预警决策",
        )
    elif not alert_ready:
        alert_note = tr(
            language,
            "Alert held because one or more inputs are stale or unavailable",
            "因部分输入过期或不可用，暂不评估预警",
        )
    elif alert_mode == "preview":
        alert_note = tr(
            language,
            "Preview only; no automatic email",
            "仅记录预览，不自动发送邮件",
        )
    elif defensive_ready:
        alert_note = tr(
            language,
            "Defensive alert eligible",
            "符合防守预警条件",
        )
    else:
        alert_note = tr(
            language,
            "Monitoring; defensive breadth not met",
            "持续监测；尚未达到防守扩散门槛",
        )
    last_sent = row.get("last_sent_at")
    if last_sent:
        alert_note += tr(language, f" · last sent {last_sent}", f" · 上次发送 {last_sent}")
    st.markdown(
        (
            f'<div class="am-regime-summary" data-state="{escape(state.lower())}">'
            f'<div class="am-regime-summary-title">{escape(tr(language, "Current state", "当前状态"))}: '
            f'{escape(_regime_state_label(state, language))} · {escape(str(breadth))}'
            f'{(" · " + escape(domain_text)) if domain_text else ""}</div>'
            f'<div class="am-regime-summary-body">{escape(str(explanation))}</div>'
            f'<div class="am-regime-summary-meta">{escape(str(active))} '
            f'{escape(tr(language, "active fresh driver(s)", "个新鲜的非正常驱动"))} · '
            f'{escape(str(observation_start))} – {escape(str(observation_end))} · {escape(alert_note)}</div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def regime_alert_decision_view(
    artifact: dict[str, Any],
    language: str,
) -> dict[str, Any]:
    """Localize the persisted alert decision; never recompute policy in the UI."""
    status = frame_for_dataset(artifact, "alert_status")
    if status.empty:
        row: dict[str, Any] = {}
    else:
        row = status.iloc[-1].to_dict()
    decision_id = str(row.get("decision_id") or "unavailable")
    evaluation_current = _strict_contract_true(row.get("evaluation_current"))
    if not evaluation_current:
        decision_id = "unavailable"

    title_by_decision = {
        "quiet": tr(language, "No alert needed", "无需提醒"),
        "component_preview": tr(language, "Change recorded", "记录变化"),
        "defensive_eligible": tr(
            language,
            "Defensive alert eligible",
            "符合防守预警",
        ),
        "manual": tr(
            language,
            "Manual digest sent",
            "已发送手动摘要",
        ),
        "unavailable": tr(
            language,
            "Alert decision unavailable",
            "预警决策不可用",
        ),
    }
    visual_state_by_decision = {
        "quiet": "normal",
        "component_preview": "watch",
        "defensive_eligible": "confirmed",
        "manual": "normal",
        "unavailable": "unavailable",
    }
    if decision_id not in title_by_decision:
        decision_id = "unavailable"

    raw_events = row.get("component_events")
    events = (
        [event for event in raw_events if isinstance(event, dict)]
        if isinstance(raw_events, list)
        else []
    )
    transitions: list[str] = []
    for event in events:
        label_field = "label_zh" if language == "zh" else "label_en"
        label = str(
            event.get(label_field)
            or event.get("label_en")
            or event.get("indicator_id")
            or "—"
        )
        before = _regime_state_label(event.get("from_state"), language)
        after = _regime_state_label(event.get("to_state"), language)
        date = observation_date_label(event.get("observation_date"), language)
        transitions.append(f"{label}: {before} → {after} · {date}")

    confirmed = int(
        pd.to_numeric(
            pd.Series([row.get("confirmed_domain_count")]),
            errors="coerce",
        )
        .fillna(0)
        .iloc[0]
    )
    total = int(
        pd.to_numeric(
            pd.Series([row.get("total_domain_count")]),
            errors="coerce",
        )
        .fillna(0)
        .iloc[0]
    )
    transition_count = int(
        pd.to_numeric(
            pd.Series([row.get("new_transition_count")]),
            errors="coerce",
        )
        .fillna(len(transitions))
        .iloc[0]
    )
    financial_exception = _strict_contract_true(
        row.get("financial_stress_exception")
    )
    if decision_id == "quiet":
        reason = tr(
            language,
            "The latest evaluation found no new state transition.",
            "本次评估未发现新的状态转折。",
        )
    elif decision_id == "component_preview":
        reason = tr(
            language,
            f"{transition_count} new transition(s) were recorded, but the defensive breadth gate is not met.",
            f"已记录{transition_count}项新变化，但尚未达到防守预警的扩散门槛。",
        )
    elif decision_id == "defensive_eligible":
        if financial_exception:
            reason = tr(
                language,
                "A fresh transition occurred and financial stress independently meets the defensive-alert exception.",
                "出现新状态变化，且金融压力领域单独满足防守预警例外条件。",
            )
        else:
            reason = tr(
                language,
                "A fresh transition occurred and at least two risk domains are Confirmed or worse.",
                "出现新状态变化，且至少两个风险领域达到确认或更高等级。",
            )
    elif decision_id == "manual":
        reason = tr(
            language,
            "This digest was sent manually via --force-report; component states reflect the latest automatic evaluation.",
            "此摘要经 --force-report 手动发送；各指标状态以最近一次自动评估为准。",
        )
    else:
        reason = tr(
            language,
            "Alert evaluation metadata is missing or does not match the current data run.",
            "预警评估记录缺失，或与当前数据运行不一致。",
        )

    alert_mode = str(row.get("alert_mode") or "preview")
    if alert_mode == "preview":
        mode_note = tr(
            language,
            "Preview mode · no email is sent",
            "预览模式 · 不发送邮件",
        )
    else:
        mode_note = tr(
            language,
            "Defensive mode · email only on a fresh, qualified transition",
            "防守模式 · 仅在出现符合条件的新变化时发送邮件",
        )
    evaluation_at = row.get("last_evaluation_at")
    evaluated = _regime_evaluation_time_label(evaluation_at, language)
    return {
        "decision_id": decision_id,
        "title": title_by_decision[decision_id],
        "visual_state": visual_state_by_decision[decision_id],
        "reason": reason,
        "transition_count": transition_count,
        "transitions": transitions,
        "breadth": f"{confirmed}/{total}" if total else "—",
        "financial_stress_exception": financial_exception,
        "mode_note": mode_note,
        "evaluated": evaluated,
    }


def render_regime_alert_decision(
    artifact: dict[str, Any],
    language: str,
) -> None:
    view = regime_alert_decision_view(artifact, language)
    transition_text = ""
    if view["transitions"]:
        rows = "".join(
            f"<div>{escape(transition)}</div>"
            for transition in view["transitions"]
        )
        transition_text = (
            f'<div class="am-alert-transition-list">'
            f'{escape(tr(language, "New transitions", "最新状态变化"))}'
            f"{rows}</div>"
        )
    st.markdown(
        (
            f'<div class="am-alert-decision" data-state="{escape(view["visual_state"])}">'
            '<div class="am-alert-decision-grid">'
            '<div class="am-alert-decision-item">'
            f'<div class="am-alert-decision-label">{escape(tr(language, "Decision", "决策"))}</div>'
            f'<div class="am-alert-decision-value">{escape(view["title"])}</div>'
            "</div>"
            '<div class="am-alert-decision-item">'
            f'<div class="am-alert-decision-label">{escape(tr(language, "New transitions", "新变化"))}</div>'
            f'<div class="am-alert-decision-value">{escape(str(view["transition_count"]))}</div>'
            "</div>"
            '<div class="am-alert-decision-item">'
            f'<div class="am-alert-decision-label">{escape(tr(language, "Confirmed domains", "确认领域"))}</div>'
            f'<div class="am-alert-decision-value">{escape(view["breadth"])}</div>'
            "</div>"
            '<div class="am-alert-decision-item">'
            f'<div class="am-alert-decision-label">{escape(tr(language, "Mode / evaluated", "模式／评估时间"))}</div>'
            f'<div class="am-alert-decision-value">{escape(view["mode_note"])}</div>'
            f'<div class="am-regime-card-meta">{escape(view["evaluated"])}</div>'
            "</div>"
            "</div>"
            f'<div class="am-alert-decision-reason">{escape(view["reason"])}</div>'
            f"{transition_text}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_regime_domain_cards(artifact: dict[str, Any], language: str) -> None:
    domains = frame_for_dataset(artifact, "domain_summary")
    if not _regime_has_columns(
        domains,
        ("domain_id", "state", "available_indicator_count", "expected_indicator_count"),
    ):
        return
    cards: list[str] = []
    for row in domains.to_dict("records"):
        domain_id = str(row.get("domain_id") or "")
        state = regime_visual_state(row)
        label = REGIME_DOMAIN_LABELS.get(domain_id, (domain_id, domain_id))[
            1 if language == "zh" else 0
        ]
        available = int(
            pd.to_numeric(
                pd.Series([row.get("available_indicator_count")]), errors="coerce"
            )
            .fillna(0)
            .iloc[0]
        )
        expected = int(
            pd.to_numeric(
                pd.Series([row.get("expected_indicator_count")]), errors="coerce"
            )
            .fillna(0)
            .iloc[0]
        )
        active = int(
            pd.to_numeric(
                pd.Series([row.get("active_indicator_count")]), errors="coerce"
            )
            .fillna(0)
            .iloc[0]
        )
        cards.append(
            (
                f'<div class="am-regime-card" data-state="{escape(state.lower())}">'
                f'<div class="am-regime-card-title">{escape(label)}</div>'
                f'<div class="am-regime-card-reading"><div class="am-regime-card-value">'
                f'{escape(_regime_state_label(state, language))}</div></div>'
                f'<div class="am-regime-card-rule">{escape(tr(language, f"{active} active indicator(s)", f"{active}个非正常指标"))}</div>'
                f'<div class="am-regime-card-meta">{escape(tr(language, f"{available}/{expected} fresh inputs", f"{available}/{expected}个新鲜输入"))}</div>'
                "</div>"
            )
        )
    st.markdown(f'<div class="am-regime-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_regime_threshold_cards(artifact: dict[str, Any], language: str) -> None:
    monitor = frame_for_dataset(artifact, "threshold_monitor")
    if monitor.empty or "indicator_id" not in monitor.columns:
        return
    preferred = ["brent", "us10y", "fomc_hike", "hike_prob", "credit_vix"]
    monitor["_order"] = monitor["indicator_id"].map(
        lambda value: preferred.index(value) if value in preferred else 99
    )
    cards: list[str] = []
    for row in monitor.sort_values(["_order", "indicator_id"]).to_dict("records"):
        state = regime_visual_state(row)
        label = row.get("label_zh" if language == "zh" else "label_en") or row.get("indicator_id")
        rule = row.get("rule_zh" if language == "zh" else "rule_en") or "—"
        progress = int(pd.to_numeric(pd.Series([row.get("confirmation_progress")]), errors="coerce").fillna(0).iloc[0])
        required = int(pd.to_numeric(pd.Series([row.get("confirmation_required")]), errors="coerce").fillna(0).iloc[0])
        progress_text = tr(
            language,
            f"confirmation {progress}/{required}",
            f"连续确认 {progress}/{required}",
        )
        persistence = pd.to_numeric(pd.Series([row.get("persistence_count")]), errors="coerce").iloc[0]
        persistence_required = pd.to_numeric(
            pd.Series([row.get("persistence_required")]), errors="coerce"
        ).iloc[0]
        if not pd.isna(persistence) and not pd.isna(persistence_required):
            progress_text += tr(
                language,
                f" · window {int(persistence)}/{int(persistence_required)}",
                f" · 窗口命中 {int(persistence)}/{int(persistence_required)}",
            )
        cards.append(
            (
                f'<div class="am-regime-card" data-state="{escape(state.lower())}">'
                f'<div class="am-regime-card-title">{escape(str(label))}</div>'
                f'<div class="am-regime-card-reading"><div class="am-regime-card-value">'
                f'{escape(_regime_value_text(row, language))}</div><div class="am-regime-card-state">'
                f'{escape(_regime_state_label(state, language))}</div></div>'
                f'<div class="am-regime-card-detail"><span class="am-regime-card-detail-label">'
                f'{escape(tr(language, "Rule", "规则"))}：</span>{escape(str(rule))}</div>'
                f'<div class="am-regime-card-detail"><span class="am-regime-card-detail-label">'
                f'{escape(tr(language, "Distance", "距离"))}：</span>'
                f'{escape(_regime_distance_text(row, language))}</div>'
                f'<div class="am-regime-card-detail"><span class="am-regime-card-detail-label">'
                f'{escape(tr(language, "Confirmation", "确认"))}：</span>'
                f'{escape(progress_text)}</div>'
                f'<div class="am-regime-card-meta">{escape(str(row.get("observation_date") or "—"))} · '
                f'{escape(REGIME_FRESHNESS_LABELS_ZH.get(str(row.get("freshness")), str(row.get("freshness") or "—")) if language == "zh" else str(row.get("freshness") or "—"))}</div></div>'
            )
        )
    st.markdown(f'<div class="am-regime-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_regime_threshold_chart(
    artifact: dict[str, Any],
    indicator_id: str,
    language: str,
    window: str,
) -> None:
    history = frame_for_dataset(artifact, "condition_state_history")
    monitor = frame_for_dataset(artifact, "threshold_monitor")
    transitions = frame_for_dataset(artifact, "state_transition_history")
    if not _regime_has_columns(history, ("date", "indicator_id", "value")):
        st.info(tr(language, "No threshold history is available.", "暂无门槛历史数据。"))
        return
    history = _regime_history_window(
        history[history["indicator_id"].astype(str).eq(indicator_id)],
        window,
    )
    history["value"] = pd.to_numeric(history["value"], errors="coerce")
    history = history.dropna(subset=["value"])
    if history.empty:
        st.info(tr(language, "No threshold history is available.", "暂无门槛历史数据。"))
        return
    metadata = monitor[monitor["indicator_id"].astype(str).eq(indicator_id)]
    threshold = (
        pd.to_numeric(metadata.iloc[-1].get("threshold"), errors="coerce")
        if not metadata.empty
        else None
    )
    title_map = {
        "brent": tr(language, "Brent vs $100 threshold", "布伦特原油与100美元门槛"),
        "us10y": tr(language, "US 10-year yield vs 4.82% threshold", "美国10年期收益率与4.82%门槛"),
    }
    st.markdown(
        f'<div class="am-chart-title">{escape(title_map.get(indicator_id, indicator_id))}</div>',
        unsafe_allow_html=True,
    )
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=history["date"],
            y=history["value"],
            mode="lines",
            name=REGIME_SERIES_LABELS_ZH.get(indicator_id, indicator_id)
            if language == "zh"
            else REGIME_SERIES_LABELS.get(indicator_id, indicator_id),
            line={"color": PALETTE[0], "width": 2},
            hovertemplate="<b>%{x|%d %b %Y}</b><br>%{y:.2f}<extra></extra>",
        )
    )
    if threshold is not None and not pd.isna(threshold):
        fig.add_hline(
            y=float(threshold),
            line_dash="dash",
            line_color="#ef4444",
            annotation_text=tr(language, "Threshold", "门槛"),
            annotation_position="top left",
        )
    if _regime_has_columns(transitions, ("date", "indicator_id", "value", "prior_state", "state")):
        marks = transitions[transitions["indicator_id"].astype(str).eq(indicator_id)].copy()
        marks["date"] = pd.to_datetime(marks["date"], errors="coerce")
        marks["value"] = pd.to_numeric(marks["value"], errors="coerce")
        marks = marks[
            marks["date"].between(history["date"].min(), history["date"].max())
        ].dropna(subset=["date", "value"])
        if not marks.empty:
            labels = [
                f"{_regime_state_label(row.prior_state, language)} → "
                f"{_regime_state_label(row.state, language)}"
                for row in marks.itertuples()
            ]
            fig.add_trace(
                go.Scatter(
                    x=marks["date"],
                    y=marks["value"],
                    mode="markers",
                    name=tr(language, "State change", "状态转折"),
                    text=labels,
                    hovertemplate="<b>%{x|%d %b %Y}</b><br>%{text}<br>%{y:.2f}<extra></extra>",
                    marker={"color": "#ef4444", "size": 7, "symbol": "diamond"},
                )
            )
    chart_theme(fig, height=390)
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})


def render_regime_transitions(artifact: dict[str, Any], language: str) -> None:
    transitions = frame_for_dataset(artifact, "state_transition_history")
    if not _regime_has_columns(
        transitions,
        ("date", "indicator_id", "prior_state", "state", "value"),
    ):
        st.info(tr(language, "No state changes are available.", "暂无状态转折记录。"))
        return
    transitions = transitions.copy()
    transitions["date"] = pd.to_datetime(transitions["date"], errors="coerce")
    transitions = transitions.dropna(subset=["date"]).sort_values("date", ascending=False).head(15)
    transitions["Indicator"] = transitions.get(
        "label_zh" if language == "zh" else "label_en",
        transitions["indicator_id"],
    )
    transitions["Transition"] = transitions.apply(
        lambda row: f"{_regime_state_label(row.get('prior_state'), language)} → "
        f"{_regime_state_label(row.get('state'), language)}",
        axis=1,
    )
    transitions["Date"] = transitions["date"].dt.strftime("%Y-%m-%d")
    transitions["Value"] = pd.to_numeric(transitions.get("value"), errors="coerce").round(2)
    table = transitions[["Date", "Indicator", "Transition", "Value"]].rename(
        columns={
            "Date": tr(language, "Date", "日期"),
            "Indicator": tr(language, "Indicator", "指标"),
            "Transition": tr(language, "Transition", "状态变化"),
            "Value": tr(language, "Reading", "读数"),
        }
    )
    st.dataframe(table, hide_index=True, width="stretch")



def _format_yield_value(value, *, spread: bool) -> str:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        return "—"
    if spread:
        return f"{number:+.1f} bps"
    return f"{number:.2f}%"


def _format_bp_change(value) -> str:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        return "—"
    return f"{number:+.1f}"



def render_sector_leadership(artifact: dict[str, Any], language: str) -> None:
    frame = frame_for_dataset(artifact, "sector_leadership")
    required = ("exposure_id", "rel_20d_pct", "rel_60d_pct", "return_20d_pct")
    if not _regime_has_columns(frame, required):
        st.info(tr(language, "Sector leadership is not in this artifact yet.", "这个数据快照还没有行业相对强弱。"))
        return
    show = frame.copy()
    show["Sector"] = show["exposure_id"].map(
        lambda value: REGIME_EXPOSURE_LABELS.get(str(value), (str(value), str(value)))[1 if language == "zh" else 0]
    )
    def _pct(value):
        number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        if pd.isna(number):
            return "—"
        return f"{number:+.2f}%"
    table = pd.DataFrame(
        {
            tr(language, "Sector", "行业"): show["Sector"],
            tr(language, "Rank", "排名"): show.get("rank_20d"),
            tr(language, "20D vs SPY", "20日相对标普"): show["rel_20d_pct"].map(_pct),
            tr(language, "60D vs SPY", "60日相对标普"): show["rel_60d_pct"].map(_pct),
            tr(language, "20D return", "20日回报"): show["return_20d_pct"].map(_pct),
            tr(language, "200D slope", "200日均线斜率"): show.get("sma200_slope_ann_pct", pd.Series([None] * len(show))).map(_pct),
            tr(language, "As of", "截至"): pd.to_datetime(show.get("date"), errors="coerce").dt.strftime("%Y-%m-%d"),
        }
    )
    st.caption(
        tr(
            language,
            "US sector ETFs versus SPY. Relative return is sector window return minus SPY window return, not a contribution attribution. 200D slope is annualized from the last five 200-day SMA observations.",
            "美股行业 ETF 相对 SPY。相对回报是行业窗口回报减去 SPY 窗口回报，不是权重贡献。200日斜率由最近五个200日均线观察值年化。",
        )
    )
    st.dataframe(table, hide_index=True, width="stretch")


def render_treasury_curve_chart(artifact: dict[str, Any], language: str) -> None:
    frame = frame_for_dataset(artifact, "treasury_curve_snapshots")
    required = ("tenor_months", "yield_pct", "snapshot_id", "as_of")
    if not _regime_has_columns(frame, required):
        st.info(tr(language, "Treasury curve snapshot is not in this artifact yet.", "这个数据快照还没有国债收益率曲线。"))
        return
    show = frame.copy()
    show["tenor_months"] = pd.to_numeric(show["tenor_months"], errors="coerce")
    show["yield_pct"] = pd.to_numeric(show["yield_pct"], errors="coerce")
    show = show.dropna(subset=["tenor_months", "yield_pct", "snapshot_id"]).sort_values(["snapshot_id", "tenor_months"])
    if show.empty:
        st.info(tr(language, "Treasury curve snapshot is not in this artifact yet.", "这个数据快照还没有国债收益率曲线。"))
        return
    label_field = "label_zh" if language == "zh" and "label_zh" in show.columns else "label_en"
    if label_field not in show.columns:
        label_field = "snapshot_id"
    tickvals = sorted({int(value) for value in show["tenor_months"].tolist()})
    ticktext = []
    maturity_map = {
        int(row["tenor_months"]):
        str(row["maturity_zh"] if language == "zh" else row["maturity_en"])
        for row in show.to_dict("records")
        if pd.notna(row.get("tenor_months"))
    }
    ticktext = [maturity_map.get(value, str(value)) for value in tickvals]
    fig = go.Figure()
    palette = {
        "latest": PALETTE[0],
        "week_ago": PALETTE[5],
        "month_ago": PALETTE[9],
        "year_start": PALETTE[2],
    }
    order = ["latest", "week_ago", "month_ago", "year_start"]
    for snapshot_id in order:
        subset = show[show["snapshot_id"].astype(str).eq(snapshot_id)]
        if subset.empty:
            continue
        as_of = subset["as_of"].iloc[0]
        label = str(subset[label_field].iloc[0])
        if as_of and str(as_of) not in {"—", "nan"}:
            label = f"{label} ({as_of})"
        fig.add_trace(
            go.Scatter(
                x=subset["tenor_months"],
                y=subset["yield_pct"],
                mode="lines+markers",
                name=label,
                line={"color": palette.get(snapshot_id, PALETTE[0]), "width": 2},
                hovertemplate="%{text}<br>%{fullData.name}: %{y:.2f}%<extra></extra>",
                text=subset["maturity_zh" if language == "zh" else "maturity_en"],
            )
        )
    fig.update_xaxes(
        title=tr(language, "Maturity", "期限"),
        tickmode="array",
        tickvals=tickvals,
        ticktext=ticktext,
    )
    fig.update_yaxes(title=tr(language, "Yield %", "收益率 %"), ticksuffix="%")
    fig = chart_theme(fig, "number", date_axis=False, height=430)
    fig.update_layout(hovermode="x unified")
    st.markdown(
        f'<div class="am-chart-title">{tr(language, "US Treasury yield curve", "美国国债收益率曲线")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        tr(
            language,
            "Latest published constant-maturity yields versus one week ago, one month ago and the start of the year. Missing tenors stay blank; the chart does not interpolate. Treasury may publish after the US cash close, so a same-day refresh can still show the previous session.",
            "最新公布的固定期限收益率，对比一周前、一个月前和年初。缺数据的期限留空，不做插值。财政部有时在美股收盘后才公布，所以当天刷新仍可能显示上一交易日。",
        )
    )
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})


def render_treasury_yield_table(artifact: dict[str, Any], language: str) -> None:
    frame = frame_for_dataset(artifact, "treasury_yield_changes")
    required = ("maturity_en", "yield_pct", "change_1d_bp", "change_1w_bp", "change_1m_bp", "change_ytd_bp")
    if not _regime_has_columns(frame, required):
        st.info(tr(language, "Treasury yield-change table is not in this artifact yet.", "这个数据快照还没有国债收益率变化表。"))
        return
    show = frame.copy()
    maturity = show["maturity_zh"] if language == "zh" and "maturity_zh" in show.columns else show["maturity_en"]
    spread = show.get("row_kind", pd.Series(["tenor"] * len(show))).astype(str).eq("spread")
    table = pd.DataFrame(
        {
            tr(language, "Maturity", "期限"): maturity,
            tr(language, "Yield", "收益率"): [
                _format_yield_value(value, spread=is_spread)
                for value, is_spread in zip(show["yield_pct"], spread)
            ],
            tr(language, "1D (bps)", "1日（基点）"): show["change_1d_bp"].map(_format_bp_change),
            tr(language, "1W (bps)", "1周（基点）"): show["change_1w_bp"].map(_format_bp_change),
            tr(language, "1M (bps)", "1月（基点）"): show["change_1m_bp"].map(_format_bp_change),
            tr(language, "YTD (bps)", "年初至今（基点）"): show["change_ytd_bp"].map(_format_bp_change),
        }
    )
    ten_year = show[show["indicator_id"].astype(str).eq("us10y")]
    caption = tr(
        language,
        "Changes are in yield basis points, not bond returns. Green in the source convention means yields rose.",
        "变化单位是收益率基点，不是债券回报。源数据惯例中绿色表示收益率上升。",
    )
    if not ten_year.empty:
        distance = pd.to_numeric(ten_year.iloc[0].get("us10y_vs_threshold_bp"), errors="coerce")
        as_of = ten_year.iloc[0].get("as_of") or "—"
        if not pd.isna(distance):
            caption = (
                tr(
                    language,
                    f"10-year is {distance:+.1f} bp from the 4.82% threshold as of {as_of}. " + caption,
                    f"10年期相对 4.82% 门槛为 {distance:+.1f} 基点，数据截至 {as_of}。" + caption,
                )
            )
    st.caption(caption)
    st.dataframe(table, hide_index=True, width="stretch")


def _factset_display_number(value: Any, suffix: str = "") -> str:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return "—"
    return f"{float(parsed):,.1f}{suffix}"


def _factset_display_count(value: Any) -> str:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return "—"
    return f"{int(parsed):,}" if float(parsed).is_integer() else f"{float(parsed):,.1f}"


def _factset_sector_revision_rows(value: Any) -> list[dict[str, Any]]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, dict):
        return []
    rows: list[dict[str, Any]] = []
    for sector, revision in parsed.items():
        number = pd.to_numeric(pd.Series([revision]), errors="coerce").iloc[0]
        if pd.isna(number):
            continue
        rows.append({"sector": str(sector), "revision_pct": float(number)})
    return sorted(rows, key=lambda row: row["revision_pct"], reverse=True)


FACTSET_CORE_FIELDS = (
    "blended_earnings_growth_yoy",
    "eps_beat_rate",
    "forward_12m_pe",
)
FACTSET_REVISION_FIELDS = (
    "quarterly_eps_revision_pct",
    "annual_eps_revision_pct",
    "positive_eps_guidance_count",
    "negative_eps_guidance_count",
    "eps_guidance_total_count",
    "sector_revision_json",
)
FACTSET_PE_AVERAGE_DISPLAY_RANGE = (8.0, 26.0)


def _factset_field_present(frame: pd.DataFrame, field: str) -> pd.Series:
    if field not in frame.columns:
        return pd.Series(False, index=frame.index)
    if field == "sector_revision_json":
        return frame[field].map(lambda value: bool(_factset_sector_revision_rows(value)))
    return pd.to_numeric(frame[field], errors="coerce").notna()


def _factset_latest_with_any(frame: pd.DataFrame, fields: tuple[str, ...]) -> pd.Series:
    """Latest article that actually published one of the requested fields."""
    if frame.empty:
        return pd.Series(dtype="object")
    work = frame.copy()
    work["_date"] = pd.to_datetime(work.get("report_date"), errors="coerce")
    work = work.dropna(subset=["_date"]).sort_values("_date")
    if work.empty:
        return pd.Series(dtype="object")
    mask = pd.Series(False, index=work.index)
    for field in fields:
        mask = mask | _factset_field_present(work, field)
    subset = work.loc[mask]
    if subset.empty:
        return pd.Series(dtype="object")
    return subset.iloc[-1]


def _factset_article_label(row: pd.Series, language: str) -> str:
    if row.empty:
        return "—"
    date_label = observation_date_label(row.get("report_date"), language)
    article_type = str(row.get("article_type") or "").strip()
    title = str(row.get("article_title") or "").strip()
    parts = [part for part in (date_label, article_type, title) if part and part != "—"]
    return " · ".join(parts) if parts else "—"


def _factset_latest_sector_board(frame: pd.DataFrame) -> pd.DataFrame:
    """Most recent named sector revision, not a simultaneous 11-sector print."""
    empty = pd.DataFrame(columns=["sector", "revision_pct", "report_date", "article_type"])
    if frame.empty:
        return empty
    work = frame.copy()
    work["_date"] = pd.to_datetime(work.get("report_date"), errors="coerce")
    work = work.dropna(subset=["_date"]).sort_values("_date")
    rows: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        for item in _factset_sector_revision_rows(row.get("sector_revision_json")):
            rows.append(
                {
                    "sector": item["sector"],
                    "revision_pct": item["revision_pct"],
                    "report_date": row["_date"],
                    "article_type": row.get("article_type"),
                }
            )
    if not rows:
        return empty
    return (
        pd.DataFrame(rows)
        .sort_values("report_date")
        .drop_duplicates("sector", keep="last")
        .sort_values("revision_pct", ascending=False)
        .reset_index(drop=True)
    )


def _factset_valuation_history(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["report_date"] = pd.to_datetime(work.get("report_date"), errors="coerce")
    work["forward_12m_pe"] = pd.to_numeric(work.get("forward_12m_pe"), errors="coerce")
    work["forward_12m_pe_10y_avg"] = pd.to_numeric(
        work.get("forward_12m_pe_10y_avg"), errors="coerce"
    )
    work = work.dropna(subset=["report_date"]).sort_values("report_date").tail(104)
    average = work["forward_12m_pe_10y_avg"]
    low, high = FACTSET_PE_AVERAGE_DISPLAY_RANGE
    work.loc[~average.between(low, high), "forward_12m_pe_10y_avg"] = pd.NA
    return work

FACTSET_REVISION_NOTE_BY_URL = {
    "https://insight.factset.com/analysts-increasing-eps-estimates-for-sp-500-companies-for-2nd-straight-quarter": {
        "window_en": "June 30–August 31 (first two months of Q3)",
        "window_zh": "6月30日至8月31日（三季度前两个月）",
        "question_en": "Given concerns about higher oil and gas prices, have analysts cut Q3 EPS more than normal?",
        "question_zh": "市场担心油价和气价走高，分析师是否把三季度EPS下调得比正常更多？",
        "answer_en": "No. The Q3 bottom-up EPS estimate rose 1.2% to $89.69 from $88.64. Analysts usually cut during the first two months of a quarter.",
        "answer_zh": "没有。三季度自下而上EPS预估从88.64美元上调1.2%至89.69美元。正常季度的前两个月通常是下调。",
        "typical": [
            ("5Y avg first 2 months", "近5年前两个月均值", -1.7),
            ("10Y avg", "近10年均值", -2.1),
            ("15Y avg", "近15年均值", -2.6),
            ("20Y avg", "近20年均值", -3.1),
        ],
        "breadth_en": "4 of 11 sectors were revised up, led by Energy; 7 were revised down, led by Materials.",
        "breadth_zh": "11个行业里4个上调（能源领先），7个下调（材料领先）。",
    },
    "https://insight.factset.com/analysts-increasing-in-quarterly-eps-estimates-for-sp-500-for-2nd-straight-quarter": {
        "window_en": "June 30–July 30 (first month of Q3)",
        "window_zh": "6月30日至7月30日（三季度第一个月）",
        "question_en": "Given concerns about higher oil prices, have analysts cut Q3 EPS more than normal?",
        "question_zh": "市场担心油价走高，分析师是否把三季度EPS下调得比正常更多？",
        "answer_en": "No. The Q3 bottom-up EPS estimate rose 0.3% to $88.95 from $88.67. Analysts usually cut during the first month of a quarter.",
        "answer_zh": "没有。三季度自下而上EPS预估从88.67美元上调0.3%至88.95美元。正常季度的第一个月通常是下调。",
        "typical": [
            ("5Y avg first month", "近5年第一个月均值", -1.0),
            ("10Y avg", "近10年均值", -1.3),
            ("15Y avg", "近15年均值", -1.7),
            ("20Y avg", "近20年均值", -1.9),
        ],
        "breadth_en": "5 of 11 sectors were revised up, led by Energy and Financials; 6 were revised down, led by Materials.",
        "breadth_zh": "11个行业里5个上调（能源、金融领先），6个下调（材料领先）。",
    },
}


def _factset_is_revision_note(row: pd.Series) -> bool:
    article_type = str(row.get("article_type") or "").strip().lower()
    title = str(row.get("article_title") or "").strip().lower()
    if article_type in {"earnings_calls", "podcast", "infographic"}:
        return False
    if any(token in title for token in ("citing", "ratings", "guidance", "surprise", "infographic")):
        return False
    if article_type == "revision":
        return True
    return "eps estimate" in title


def _factset_revision_prints(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    work = frame.copy()
    work["_date"] = pd.to_datetime(work.get("report_date"), errors="coerce")
    work["quarterly_eps_revision_pct"] = pd.to_numeric(
        work.get("quarterly_eps_revision_pct"), errors="coerce"
    )
    work["annual_eps_revision_pct"] = pd.to_numeric(
        work.get("annual_eps_revision_pct"), errors="coerce"
    )
    keep = work["_date"].notna() & (
        work["quarterly_eps_revision_pct"].notna() | work["annual_eps_revision_pct"].notna()
    )
    work = work.loc[keep].copy()
    if work.empty:
        return work
    work = work[work.apply(_factset_is_revision_note, axis=1)].copy()
    return work.sort_values("_date").reset_index(drop=True)


def _factset_revision_comparison(frame: pd.DataFrame) -> dict[str, Any]:
    prints = _factset_revision_prints(frame)
    empty = {
        "current": pd.Series(dtype="object"),
        "previous": pd.Series(dtype="object"),
        "prints": prints,
        "quarterly_median": pd.NA,
        "annual_median": pd.NA,
    }
    if prints.empty:
        return empty
    current = prints.iloc[-1]
    previous = prints.iloc[-2] if len(prints) > 1 else pd.Series(dtype="object")
    return {
        "current": current,
        "previous": previous,
        "prints": prints,
        "quarterly_median": prints["quarterly_eps_revision_pct"].median(),
        "annual_median": prints["annual_eps_revision_pct"].median(),
    }


def _factset_revision_note(row: pd.Series) -> dict[str, Any] | None:
    url = str(row.get("source_url") or "").strip()
    return FACTSET_REVISION_NOTE_BY_URL.get(url)


def _factset_latest_article_sectors(row: pd.Series) -> list[dict[str, Any]]:
    if row.empty:
        return []
    return _factset_sector_revision_rows(row.get("sector_revision_json"))


def _factset_named_sector_prints(frame: pd.DataFrame) -> pd.DataFrame:
    """Revision notes that actually named one or more sectors."""
    prints = _factset_revision_prints(frame)
    if prints.empty:
        return prints
    keep = prints.apply(
        lambda row: bool(_factset_sector_revision_rows(row.get("sector_revision_json"))),
        axis=1,
    )
    return prints.loc[keep].reset_index(drop=True)




def render_factset_earnings_context(
    artifact: dict[str, Any],
    language: str,
) -> None:
    """Render aggregate FactSet context without implying security consensus."""
    frame = frame_for_dataset(artifact, "factset_earnings_regime")
    health = frame_for_dataset(artifact, "factset_earnings_health")
    if frame.empty:
        status = str(health.iloc[-1].get("status") if not health.empty else "Unavailable")
        st.info(
            tr(
                language,
                f"FactSet Earnings Insight is {status.lower()} in the current local snapshot; no numeric observation is published.",
                f"当前本地快照中的 FactSet Earnings Insight 状态为“{status}”，暂时没有可发布的数值观察。",
            )
        )
        return

    show = frame.copy()
    show["report_date"] = pd.to_datetime(show["report_date"], errors="coerce")
    show = show.dropna(subset=["report_date"]).sort_values("report_date")
    if show.empty:
        st.info(tr(language, "No valid FactSet report dates are available.", "没有有效的 FactSet 报告日期。"))
        return
    newest = show.iloc[-1]
    core = _factset_latest_with_any(show, FACTSET_CORE_FIELDS)
    health_row = health.iloc[-1].to_dict() if not health.empty else {}
    status = str(health_row.get("status") or "Partial")
    status_label = {
        "Healthy": tr(language, "Ready", "可用"),
        "Partial": tr(language, "Partial coverage", "部分覆盖"),
        "Unavailable": tr(language, "Unavailable", "不可用"),
    }.get(status, status)
    fill_floor = pd.to_numeric(pd.Series([health_row.get("fill_rate_last_24")]), errors="coerce").iloc[0]
    core_fill = pd.to_numeric(
        pd.Series([health_row.get("core_fill_rate_last_24", fill_floor)]), errors="coerce"
    ).iloc[0]
    supported_fill = pd.to_numeric(
        pd.Series([health_row.get("supported_fill_rate_last_24")]), errors="coerce"
    ).iloc[0]
    fill_text = "—" if pd.isna(core_fill) else f"{float(core_fill) * 100:.0f}%"
    supported_fill_text = "—" if pd.isna(supported_fill) else f"{float(supported_fill) * 100:.0f}%"
    article_records = _factset_display_count(health_row.get("article_records"))
    metric_records = _factset_display_count(health_row.get("supported_records"))
    usable_records = _factset_display_count(health_row.get("usable_records"))
    coverage_note = tr(
        language,
        f"{status_label} · newest article {observation_date_label(newest.get('report_date'), language)} · last earnings snapshot {_factset_article_label(core, language)} · core fill floor {fill_text} · supported payload fill {supported_fill_text} · article catalog {article_records} · metric-bearing {metric_records} · usable {usable_records}",
        f"{status_label} · 最新文章 {observation_date_label(newest.get('report_date'), language)} · 最近盈利快照 {_factset_article_label(core, language)} · 核心字段最低填充率 {fill_text} · 支持字段填充率 {supported_fill_text} · 文章目录 {article_records} · 含指标 {metric_records} · 可用 {usable_records}",
    )
    st.caption(coverage_note)
    core_report_date = (
        pd.to_datetime(core.get("report_date"), errors="coerce").date().isoformat()
        if not core.empty and pd.notna(core.get("report_date"))
        else None
    )
    newest_report_date = (
        newest["report_date"].date().isoformat() if pd.notna(newest.get("report_date")) else None
    )
    if newest_report_date and newest_report_date != core_report_date:
        st.warning(
            tr(
                language,
                f"The newest article ({_factset_article_label(newest, language)}) is an estimate-revision note, not a full earnings snapshot. Growth, beat-rate and P/E below come from the latest article that actually printed those fields.",
                f"最新文章（{_factset_article_label(newest, language)}）是盈利预估修正，不是完整盈利快照。下方增长、超预期比例和市盈率来自最近一篇真正刊出这些字段的文章。",
            )
        )

    st.markdown(f"**{tr(language, 'Latest earnings snapshot', '最新盈利快照')}**")
    st.caption(
        tr(
            language,
            f"Source: {_factset_article_label(core, language)}. These four numbers are reprinted together in earnings-season updates; revision notes usually omit them.",
            f"来源：{_factset_article_label(core, language)}。这四个数字通常一起出现在盈利季更新里；预估修正文章一般不会重印它们。",
        )
    )
    metric_specs = (
        ("Earnings growth YoY", "盈利同比增长", "blended_earnings_growth_yoy", "%"),
        ("EPS beat rate", "EPS超预期比例", "eps_beat_rate", "%"),
        ("Forward 12M P/E", "未来12个月市盈率", "forward_12m_pe", "x"),
        ("P/E vs 10Y average", "市盈率相对10年均值", "pe_premium_pct", "%"),
    )
    latest_metrics = core.to_dict() if not core.empty else {}
    latest_forward = pd.to_numeric(pd.Series([latest_metrics.get("forward_12m_pe")]), errors="coerce").iloc[0]
    latest_average = pd.to_numeric(pd.Series([latest_metrics.get("forward_12m_pe_10y_avg")]), errors="coerce").iloc[0]
    latest_metrics["pe_premium_pct"] = (
        (latest_forward / latest_average - 1) * 100
        if pd.notna(latest_forward) and pd.notna(latest_average) and latest_average != 0
        else pd.NA
    )
    metric_columns = st.columns(len(metric_specs))
    for column, (label_en, label_zh, field, suffix) in zip(metric_columns, metric_specs):
        with column:
            st.metric(
                tr(language, label_en, label_zh),
                _factset_display_number(latest_metrics.get(field), suffix),
            )

    FACTSET_UP = PALETTE[2]
    FACTSET_DOWN = PALETTE[1]
    FACTSET_NOW = PALETTE[0]
    FACTSET_HIST = PALETTE[9]

    def _signed_color(value: Any, *, positive=FACTSET_UP, negative=FACTSET_DOWN, empty=FACTSET_HIST) -> str:
        parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        if pd.isna(parsed):
            return empty
        return positive if float(parsed) >= 0 else negative

    comparison = _factset_revision_comparison(show)
    revision = comparison["current"] if not comparison["current"].empty else _factset_latest_with_any(
        show, FACTSET_REVISION_FIELDS
    )
    previous = comparison["previous"]
    prints = comparison["prints"]
    revision_note = _factset_revision_note(revision) if not revision.empty else None

    st.markdown(f"**{tr(language, 'What changed', '现在到底什么情况')}**")
    st.caption(
        tr(
            language,
            "Teal = estimate raised. Red = estimate cut. Blue = this FactSet print. Gray = historical typical cut. Mixed sector colors are the story, not a missing 11-sector board.",
            "青绿=预估上调，红=预估下调，蓝=本篇 FactSet，灰=历史常态下调。行业颜色不一致才是重点，不是缺了11个行业。",
        )
    )
    if revision.empty:
        st.info(tr(language, "No FactSet estimate-revision print is available.", "没有可用的 FactSet 预估修正。"))
    else:
        q_now = pd.to_numeric(pd.Series([revision.get("quarterly_eps_revision_pct")]), errors="coerce").iloc[0]
        a_now = pd.to_numeric(pd.Series([revision.get("annual_eps_revision_pct")]), errors="coerce").iloc[0]
        q_prev = (
            pd.to_numeric(pd.Series([previous.get("quarterly_eps_revision_pct")]), errors="coerce").iloc[0]
            if not previous.empty
            else pd.NA
        )
        a_prev = (
            pd.to_numeric(pd.Series([previous.get("annual_eps_revision_pct")]), errors="coerce").iloc[0]
            if not previous.empty
            else pd.NA
        )
        q_delta = q_now - q_prev if pd.notna(q_now) and pd.notna(q_prev) else pd.NA
        a_delta = a_now - a_prev if pd.notna(a_now) and pd.notna(a_prev) else pd.NA
        typical_5y = revision_note["typical"][0][2] if revision_note else None
        vs_typical = q_now - typical_5y if pd.notna(q_now) and typical_5y is not None else pd.NA
        source_url = str(revision.get("source_url") or "").strip()
        direction = tr(language, "up", "上调") if pd.notna(q_now) and q_now >= 0 else tr(language, "down", "下调")
        st.write(
            tr(
                language,
                f"Q3 EPS estimates were revised {direction} {_factset_display_number(q_now, '%')} in the latest FactSet print. That is unusual: analysts typically cut early in the quarter.",
                f"最新一篇 FactSet 显示，三季度EPS预估{direction}{_factset_display_number(q_now, '%')}。这不寻常：正常季度前段通常是下调。",
            )
        )
        if source_url:
            st.markdown(
                f"[{tr(language, 'Open the FactSet note', '打开 FactSet 原文')}]({source_url}) · {_factset_article_label(revision, language)}"
            )
        k1, k2, k3, k4 = st.columns(4)
        with k1:
            st.metric(
                tr(language, "This print · quarterly", "本篇 · 季度修正"),
                _factset_display_number(q_now, "%"),
                None if pd.isna(q_delta) else f"{_factset_display_number(q_delta, 'pp')} vs prior",
            )
        with k2:
            st.metric(
                tr(language, "This print · full year", "本篇 · 年度修正"),
                _factset_display_number(a_now, "%"),
                None if pd.isna(a_delta) else f"{_factset_display_number(a_delta, 'pp')} vs prior",
            )
        with k3:
            st.metric(
                tr(language, "Prior print", "上一篇修正"),
                _factset_display_number(q_prev, "%") if not previous.empty else "—",
                _factset_article_label(previous, language) if not previous.empty else None,
            )
        with k4:
            st.metric(
                tr(language, "Gap vs 5Y typical cut", "相对近5年常态下调"),
                _factset_display_number(vs_typical, "pp") if pd.notna(vs_typical) else "—",
            )

        if revision_note:
            st.info(
                tr(
                    language,
                    f"FactSet asked: {revision_note['question_en']} {revision_note['answer_en']} Window: {revision_note['window_en']}. {revision_note['breadth_en']}",
                    f"FactSet 问的是：{revision_note['question_zh']} {revision_note['answer_zh']} 窗口：{revision_note['window_zh']}。{revision_note['breadth_zh']}",
                )
            )
            st.caption(
                tr(
                    language,
                    "FactSet answered a yes/no versus history. It did not publish a causal attribution for Energy vs Materials, and this panel does not invent one.",
                    "FactSet 回答的是‘相对历史是否异常’，没有给出能源 vs 材料的因果解释；本面板也不会编一个原因。",
                )
            )
            bars = pd.DataFrame(
                [
                    {"label": tr(language, "This print", "本篇"), "value": (float(q_now) if pd.notna(q_now) else None), "role": "now"},
                    *[{"label": tr(language, en, zh), "value": value, "role": "hist"} for en, zh, value in revision_note["typical"]],
                ]
            )
            colors = [
                _signed_color(value) if role == "now" else FACTSET_HIST
                for value, role in zip(bars["value"], bars["role"])
            ]
            figure = go.Figure(
                go.Bar(
                    x=bars["label"],
                    y=bars["value"],
                    marker_color=colors,
                    text=[_factset_display_number(value, "%") for value in bars["value"]],
                    textposition="outside",
                    hovertemplate="%{x}<br>%{y:+.1f}%<extra></extra>",
                )
            )
            figure.add_hline(y=0, line_color=FACTSET_HIST, line_width=1)
            figure.update_layout(
                height=300,
                margin={"l": 12, "r": 12, "t": 28, "b": 12},
                yaxis_title=tr(language, "EPS revision %", "EPS修正 %"),
                showlegend=False,
                title=tr(
                    language,
                    "This print versus typical early-quarter cut",
                    "本篇 vs 季度前段历史常态下调",
                ),
            )
            st.plotly_chart(chart_theme(figure, height=300, date_axis=False), width="stretch", config={"displayModeBar": False})

        if not prints.empty:
            st.caption(
                tr(
                    language,
                    "Index-level estimate drift over time. Marker color follows the sign: teal raised, red cut. This is not a daily consensus series.",
                    "指数层面预估漂移。点的颜色跟着方向走：青绿=上调，红=下调。这不是日频共识序列。",
                )
            )
            history_fig = go.Figure()
            history_fig.add_hline(y=0, line_color=FACTSET_HIST, line_width=1)
            q_hist = prints.dropna(subset=["quarterly_eps_revision_pct"])
            a_hist = prints.dropna(subset=["annual_eps_revision_pct"])
            if not q_hist.empty:
                history_fig.add_trace(
                    go.Scatter(
                        x=q_hist["_date"],
                        y=q_hist["quarterly_eps_revision_pct"],
                        mode="lines+markers",
                        name=tr(language, "Quarterly EPS revision", "季度EPS修正"),
                        line={"color": FACTSET_NOW, "width": 2},
                        marker={
                            "color": [_signed_color(value) for value in q_hist["quarterly_eps_revision_pct"]],
                            "size": 9,
                            "line": {"width": 1, "color": "#FFFFFF"},
                        },
                    )
                )
            if not a_hist.empty:
                history_fig.add_trace(
                    go.Scatter(
                        x=a_hist["_date"],
                        y=a_hist["annual_eps_revision_pct"],
                        mode="lines+markers",
                        name=tr(language, "Full-year EPS revision", "年度EPS修正"),
                        line={"color": FACTSET_HIST, "width": 2, "dash": "dot"},
                        marker={"color": FACTSET_HIST, "size": 7},
                    )
                )
            history_fig.update_layout(
                height=320,
                margin={"l": 12, "r": 12, "t": 8, "b": 12},
                yaxis_title="%",
            )
            st.plotly_chart(chart_theme(history_fig, height=320), width="stretch", config={"displayModeBar": False})

    named_prints = _factset_named_sector_prints(show)
    if not named_prints.empty:
        st.markdown(f"**{tr(language, 'Named sectors by print', '按篇幅查看点名行业')}**")
        st.caption(
            tr(
                language,
                "Each FactSet revision note names only a few sectors. The slider walks those prints; it does not create a full 11-sector board. Teal was raised, red was cut.",
                "每篇 FactSet 修正文章只会点名少数行业。用滑条切换篇幅，不会拼出完整的11个行业面板。青绿=上调，红=下调。",
            )
        )
        print_count = int(len(named_prints))
        selected_number = st.slider(
            tr(language, "Older prints ← → Newer prints", "更早篇幅 ← → 更新篇幅"),
            min_value=1,
            max_value=print_count,
            value=print_count,
            key="factset_named_sector_print",
        )
        selected_print = named_prints.iloc[selected_number - 1]
        named_now = _factset_latest_article_sectors(selected_print)
        selected_url = str(selected_print.get("source_url") or "").strip()
        selected_q = pd.to_numeric(
            pd.Series([selected_print.get("quarterly_eps_revision_pct")]), errors="coerce"
        ).iloc[0]
        selected_a = pd.to_numeric(
            pd.Series([selected_print.get("annual_eps_revision_pct")]), errors="coerce"
        ).iloc[0]
        heading = tr(
            language,
            f"Print {selected_number} of {print_count}: {_factset_article_label(selected_print, language)}",
            f"第 {selected_number} / {print_count} 篇：{_factset_article_label(selected_print, language)}",
        )
        if selected_url:
            st.markdown(
                f"{heading} · [{tr(language, 'Open this note', '打开这篇原文')}]({selected_url})"
            )
        else:
            st.markdown(heading)
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric(
                tr(language, "This print · quarterly", "本篇 · 季度修正"),
                _factset_display_number(selected_q, "%"),
            )
        with c2:
            st.metric(
                tr(language, "This print · full year", "本篇 · 年度修正"),
                _factset_display_number(selected_a, "%"),
            )
        with c3:
            st.metric(
                tr(language, "Sectors named", "点名行业数"),
                str(len(named_now)),
            )
        if named_now:
            sector_fig = go.Figure(
                go.Bar(
                    x=[row["revision_pct"] for row in named_now],
                    y=[row["sector"] for row in named_now],
                    orientation="h",
                    marker_color=[_signed_color(row["revision_pct"]) for row in named_now],
                    text=[_factset_display_number(row["revision_pct"], "%") for row in named_now],
                    textposition="outside",
                    hovertemplate="%{y}<br>%{x:+.1f}%<extra></extra>",
                )
            )
            sector_fig.add_vline(x=0, line_color=FACTSET_HIST, line_width=1)
            sector_fig.update_layout(
                height=max(220, 88 + 36 * len(named_now)),
                margin={"l": 12, "r": 28, "t": 8, "b": 12},
                xaxis_title=tr(language, "EPS revision %", "EPS修正 %"),
                yaxis={"autorange": "reversed"},
                showlegend=False,
            )
            st.plotly_chart(
                chart_theme(sector_fig, height=max(220, 88 + 36 * len(named_now)), date_axis=False),
                width="stretch",
                config={"displayModeBar": False},
            )
        else:
            st.info(
                tr(
                    language,
                    "This print did not name any sectors.",
                    "这篇没有点名任何行业。",
                )
            )
    valuation = _factset_valuation_history(show)
    pe_points = valuation.dropna(subset=["forward_12m_pe"])
    avg_points = valuation.dropna(subset=["forward_12m_pe_10y_avg"])
    if not pe_points.empty or not avg_points.empty:
        st.markdown(
            f"**{tr(language, 'S&P 500 forward 12-month P/E', '标普500未来12个月市盈率')}**"
        )
        st.caption(
            tr(
                language,
                "Each marker is a FactSet article that printed a valuation, not a daily series. The dotted line is the 10-year average when FactSet published a plausible value; a few parse outliers are omitted.",
                "每个点是一篇刊出估值的 FactSet 文章，不是日频序列。虚线是 FactSet 给出的10年均值（已去掉明显解析异常值）。",
            )
        )
        figure = go.Figure()
        if not pe_points.empty:
            figure.add_trace(
                go.Scatter(
                    x=pe_points["report_date"],
                    y=pe_points["forward_12m_pe"],
                    mode="lines+markers",
                    connectgaps=False,
                    name=tr(language, "Forward 12M P/E", "未来12个月市盈率"),
                    line={"color": PALETTE[0], "width": 2},
                    marker={"color": PALETTE[0], "size": 8},
                )
            )
        if not avg_points.empty:
            figure.add_trace(
                go.Scatter(
                    x=avg_points["report_date"],
                    y=avg_points["forward_12m_pe_10y_avg"],
                    mode="lines+markers",
                    connectgaps=False,
                    name=tr(language, "10Y average P/E", "10年平均市盈率"),
                    line={"color": PALETTE[9], "width": 2, "dash": "dot"},
                    marker={"color": PALETTE[9], "size": 7},
                )
            )
        figure.update_layout(
            height=340,
            margin={"l": 12, "r": 12, "t": 8, "b": 12},
            yaxis_title="P/E",
            xaxis_title=tr(language, "FactSet report date", "FactSet报告日期"),
            legend={"orientation": "h", "y": 1.12},
            yaxis={"range": [10, 25]},
        )
        st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})

    table = show.tail(24).copy()
    for column in (
        "reference_quarter",
        "blended_earnings_growth_yoy",
        "eps_beat_rate",
        "forward_12m_pe",
        "forward_12m_pe_10y_avg",
        "quarterly_eps_revision_pct",
        "annual_eps_revision_pct",
        "positive_eps_guidance_count",
        "negative_eps_guidance_count",
        "article_type",
    ):
        if column not in table.columns:
            table[column] = pd.NA
    table[tr(language, "Report date", "报告日")] = table["report_date"].map(
        lambda value: observation_date_label(value, language)
    )
    quarter_label = tr(language, "Quarter", "季度")
    table[quarter_label] = table.get("reference_quarter", pd.Series(index=table.index)).map(
        lambda value: "—" if pd.isna(value) else str(value)
    )
    table[tr(language, "Earnings growth YoY", "盈利同比增长")] = table[
        "blended_earnings_growth_yoy"
    ].map(lambda value: _factset_display_number(value, "%"))
    table[tr(language, "EPS beat rate", "EPS超预期比例")] = table["eps_beat_rate"].map(
        lambda value: _factset_display_number(value, "%")
    )
    table[tr(language, "Forward 12M P/E", "未来12个月市盈率")] = table["forward_12m_pe"].map(
        lambda value: _factset_display_number(value, "x")
    )
    table[tr(language, "10Y average P/E", "10年平均市盈率")] = table[
        "forward_12m_pe_10y_avg"
    ].map(lambda value: _factset_display_number(value, "x"))
    table[tr(language, "Quarterly EPS revision", "季度 EPS 修正")] = table[
        "quarterly_eps_revision_pct"
    ].map(lambda value: _factset_display_number(value, "%"))
    table[tr(language, "Annual EPS revision", "年度 EPS 修正")] = table[
        "annual_eps_revision_pct"
    ].map(lambda value: _factset_display_number(value, "%"))
    table[tr(language, "Positive guidance", "正面指引")] = table[
        "positive_eps_guidance_count"
    ].map(_factset_display_count)
    table[tr(language, "Negative guidance", "负面指引")] = table[
        "negative_eps_guidance_count"
    ].map(_factset_display_count)
    table[tr(language, "Article type", "文章类型")] = table["article_type"].map(
        lambda value: "—" if pd.isna(value) or not str(value).strip() else str(value)
    )
    columns = [
        tr(language, "Report date", "报告日"),
        tr(language, "Quarter", "季度"),
        tr(language, "Article type", "文章类型"),
        tr(language, "Earnings growth YoY", "盈利同比增长"),
        tr(language, "EPS beat rate", "EPS超预期比例"),
        tr(language, "Forward 12M P/E", "未来12个月市盈率"),
        tr(language, "10Y average P/E", "10年平均市盈率"),
        tr(language, "Quarterly EPS revision", "季度 EPS 修正"),
        tr(language, "Annual EPS revision", "年度 EPS 修正"),
        tr(language, "Positive guidance", "正面指引"),
        tr(language, "Negative guidance", "负面指引"),
    ]
    st.dataframe(
        table[[column for column in columns if column in table.columns]].iloc[::-1],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        tr(
            language,
            "FactSet Earnings Insight is an aggregate S&P 500 earnings-season, valuation and estimate-revision context feed. Different article types print different fields; blank cells are unpublished, not zero. This is not company-level consensus.",
            "FactSet Earnings Insight 是标普500整体盈利季、估值及盈利修正背景数据流。不同类型文章刊出的字段不同；空单元格是未发布，不是零。这不是个股共识。",
        )
    )


def render_regime(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    """Defensive global-conditions radar. Not an allocation or buy-the-dip cockpit."""
    render_header(
        artifact,
        labels,
        language,
        "regime",
        title_override=tr(language, "Global Market Regime", "全球市场状态"),
        description_override=tr(
            language,
            "Defensive radar for oil, Treasuries, CFTC positioning, Polymarket FOMC odds, Atlanta Fed SOFR odds, credit, VIX and CNN US-equity Fear & Greed. Polymarket is a prediction-market price; Atlanta Fed is 3-month average SOFR odds. Neither is CME FedWatch. CNN Fear & Greed is not the crypto index.",
            "原油、美债、CFTC 持仓、Polymarket 下次 FOMC 赔率、Atlanta Fed SOFR 分布、信用利差、VIX 和 CNN 美股恐惧与贪婪的防守雷达。Polymarket 是预测市场价格；Atlanta Fed 是三个月平均 SOFR 概率。两者都不是 CME FedWatch。CNN 恐惧与贪婪不是加密情绪指数。",
        ),
    )
    for warning in regime_data_warnings(artifact, language):
        st.warning(warning)
    monitor = frame_for_dataset(artifact, "threshold_monitor")
    if not _regime_has_columns(monitor, ("indicator_id", "state", "value", "freshness")):
        st.info(tr(language, "No regime snapshot is available yet.", "暂时没有市场状态快照。"))
        render_regime_source_coverage(artifact, labels, language)
        return
    render_regime_summary_banner(artifact, language)
    render_regime_daily_brief(artifact, language)
    section_heading(
        language,
        "Alert decision",
        "预警决策",
        "A persisted pipeline decision: fresh transitions, breadth qualification and alert mode. The Streamlit app does not recompute it.",
        "展示 pipeline 已保存的判断：最新状态变化、扩散门槛及预警模式；Streamlit 不会自行重算。",
    )
    render_regime_alert_decision(artifact, language)
    section_heading(
        language,
        "Risk breadth",
        "风险扩散",
        "The headline keeps the highest-severity state, while these domains show whether pressure is isolated or spreading.",
        "总状态保留最高严重度；领域卡片用来区分压力是局部出现，还是正在扩散。",
    )
    render_regime_domain_cards(artifact, language)
    section_heading(
        language,
        "Decision thresholds",
        "决策门槛",
        "Each card shows the current state, declared rule, distance to threshold, confirmation progress and observation date.",
        "每张卡同时显示当前状态、明确规则、距门槛距离、确认进度和观察日期。",
    )
    render_regime_threshold_cards(artifact, language)

    equity_tab, rates_tab, macro_tab = st.tabs(
        [
            tr(language, "Equity", "股市"),
            tr(language, "Fixed income", "固收"),
            tr(language, "Macro", "宏观"),
        ]
    )
    with equity_tab:
        section_heading(
            language,
            "Volatility and sentiment",
            "波动与情绪",
            "VIX is the raw CBOE level. CNN Fear & Greed is the US-equity sentiment gauge, not Alternative.me crypto Fear & Greed.",
            "VIX 是 CBOE 原始水平。CNN 恐惧与贪婪是美股情绪指数，不是 Alternative.me 加密恐惧与贪婪。",
        )
        vol_left, vol_right = st.columns(2)
        with vol_left:
            with st.container(border=True):
                render_vix_history(artifact, labels, language, window)
        with vol_right:
            with st.container(border=True):
                render_cnn_fear_greed(artifact, language, window)
        section_heading(
            language,
            "CNN Fear & Greed components",
            "CNN恐惧与贪婪分项",
            "Each component is its own card. CNN only publishes a 0-100 score for the latest day; the charts use raw historical inputs on their own scales.",
            "每个分项单独一张卡。CNN 只对最新一天公布 0–100 分数；图使用各自量纲的原始历史输入。",
        )
        render_cnn_fear_greed_components(artifact, language, window)
        section_heading(
            language,
            "US sector leadership",
            "美股行业相对强弱",
            "Sector ETFs versus SPY over 20 and 60 sessions. This is relative performance, not official SPY weight contribution.",
            "行业 ETF 相对 SPY 的20日和60日表现。这是相对强弱，不是官方权重贡献。",
        )
        with st.container(border=True):
            render_sector_leadership(artifact, language)
        section_heading(
            language,
            "Earnings and valuation context",
            "盈利与估值背景",
            "FactSet articles print different fields. Earnings snapshots and estimate-revision notes are shown separately; missing cells are unpublished, not zero.",
            "FactSet 不同类型文章刊出的字段不同。盈利快照和预估修正分开展示；空单元格是未发布，不是零。",
        )
        with st.container(border=True):
            render_factset_earnings_context(artifact, language)
        section_heading(
            language,
            "Cross-asset context",
            "跨资产背景",
            "Existing market-monitor index closes reused as context, not a second price database.",
            "复用现有 ETF 监控的指数收盘价作为背景，不再单独保存第二套价格。",
        )
        with st.container(border=True):
            render_cross_asset_context(artifact, language, window)

    with rates_tab:
        section_heading(
            language,
            "Threshold evidence",
            "门槛证据",
            "The 4.82% 10-year rule stays on the cards above; the chart overlays true state-transition markers.",
            "4.82% 的10年期规则仍在上方门槛卡；图上叠加真实状态转折点。",
        )
        with st.container(border=True):
            render_regime_threshold_chart(artifact, "us10y", language, window)
        section_heading(
            language,
            "Policy expectations",
            "政策预期",
            "Atlanta Fed estimates the distribution of 3-month average SOFR; Polymarket prices the next scheduled FOMC decision. They answer different questions.",
            "Atlanta Fed 估算三个月平均 SOFR 的分布；Polymarket 定价下一次 FOMC 决议。两者回答不同问题。",
        )
        policy_left, policy_right = st.columns(2)
        with policy_left:
            with st.container(border=True):
                render_line_chart(
                    artifact,
                    labels,
                    "hike_probability_chart",
                    language,
                    window,
                    views=("Level",),
                    periods_per_year=252,
                    height=390,
                    series_label_map=REGIME_DIST_LABELS_ZH if language == "zh" else None,
                    title_override=tr(
                        language,
                        "Near-term SOFR vs current FOMC target",
                        "近端SOFR相对当前FOMC目标区间",
                    ),
                    subtitle_override=tr(
                        language,
                        "Probability distribution for 3-month average SOFR; not meeting-by-meeting FedWatch odds.",
                        "三个月平均SOFR的概率分布；不是逐次会议的FedWatch赔率。",
                    ),
                )
        with policy_right:
            with st.container(border=True):
                fomc_row = monitor[monitor["indicator_id"].astype(str).eq("fomc_hike")]
                if not fomc_row.empty:
                    current = fomc_row.iloc[-1]
                    one_obs = pd.to_numeric(current.get("change_1obs_pp"), errors="coerce")
                    seven_day = pd.to_numeric(current.get("change_7d_pp"), errors="coerce")
                    meeting = current.get("meeting_date") or current.get("target_range") or "—"
                    deltas = []
                    if not pd.isna(one_obs):
                        deltas.append(tr(language, f"latest change {one_obs:+.1f} pp", f"最新变化 {one_obs:+.1f} 个百分点"))
                    if not pd.isna(seven_day):
                        deltas.append(tr(language, f"7-day change {seven_day:+.1f} pp", f"7日变化 {seven_day:+.1f} 个百分点"))
                    st.caption(
                        tr(language, f"Meeting: {meeting}", f"会议：{meeting}")
                        + (f" · {' · '.join(deltas)}" if deltas else "")
                    )
                render_line_chart(
                    artifact,
                    labels,
                    "fomc_odds_chart",
                    language,
                    window,
                    views=("Level",),
                    periods_per_year=252,
                    height=350,
                    series_label_map=FOMC_DIST_LABELS_ZH if language == "zh" else None,
                    title_override=tr(
                        language,
                        "Next FOMC meeting odds",
                        "下次FOMC会议赔率",
                    ),
                    subtitle_override=tr(
                        language,
                        "Polymarket prices for the currently selected open meeting; V1 is not a continuous archive across past meetings.",
                        "当前所选开放会议的Polymarket预测市场价格；V1尚未形成跨历次会议的连续档案。",
                    ),
                )
        section_heading(
            language,
            "US Treasuries",
            "美国国债",
            "The curve compares four published sessions. The table is yield change in basis points, not bond returns.",
            "曲线比较四个已公布交易日。表格是收益率基点变化，不是债券回报。",
        )
        with st.container(border=True):
            render_treasury_curve_chart(artifact, language)
        with st.container(border=True):
            render_treasury_yield_table(artifact, language)
        section_heading(
            language,
            "Credit and volatility",
            "信用与波动",
            "The decision rule uses same-date 20-day z-scores and five-day direction. Raw levels remain available for audit.",
            "决策规则使用同日20日z分数和5日方向；原始水平保留供核查。",
        )
        with st.container(border=True):
            render_credit_vix_evidence(artifact, language, window)

    with macro_tab:
        section_heading(
            language,
            "Commodities",
            "商品",
            "1D / 1W / 1M / 3M / YTD returns on Yahoo Finance futures and ETF proxies, not LBMA/EIA spot.",
            "Yahoo Finance 期货与 ETF 代理的1日／1周／1月／3月／年初至今回报，不是 LBMA／EIA 现货。",
        )
        with st.container(border=True):
            render_macro_commodity_table(artifact, language)
        section_heading(
            language,
            "Inflation — last 12 monthly releases",
            "通胀 — 最近12次月度发布",
            "FRED PCE and Dallas Fed trimmed-mean prints. Headline/core PCE are YoY percent changes of the price index.",
            "FRED PCE 与达拉斯联储截尾均值。PCE物价与核心PCE为价格指数同比。",
        )
        with st.container(border=True):
            render_inflation_heatmap(artifact, language)
        section_heading(
            language,
            "Oil threshold evidence",
            "油价门槛证据",
            "Persistent Brent closes above $100 remain the V1 inflation/supply gate. This uses FRED EIA spot, not the futures proxy in the table above.",
            "布伦特现货持续收于100美元上方仍是 V1 通胀／供给门槛。这里用的是 FRED EIA 现货，不是上方表格的期货代理。",
        )
        with st.container(border=True):
            render_regime_threshold_chart(artifact, "brent", language, window)
        section_heading(
            language,
            "CFTC positioning",
            "CFTC 持仓",
            "Latest net positions are paired with their own historical percentile; financials use leveraged-money, while gold and WTI use managed-money.",
            "最新净头寸同时配有自身历史分位；金融期货用杠杆资金，黄金和WTI用管理资金。",
        )
        cot = frame_for_dataset(artifact, "cot_latest")
        cot_required = (
            "label_zh" if language == "zh" else "label_en",
            "net",
            "weekly_change",
            "percentile",
            "position_label",
            "report",
        )
        if not _regime_has_columns(cot, cot_required):
            st.info(tr(language, "CFTC snapshot is not in this artifact yet.", "这个数据快照还没有CFTC持仓。"))
        else:
            show = cot.copy()
            show["Contract"] = show.get("label_zh" if language == "zh" else "label_en")
            show["Reading"] = show.get("position_label").map(
                lambda value: COT_LABELS_ZH.get(str(value), str(value)) if language == "zh" else str(value)
            )
            show["Report"] = show.get("report").map(
                lambda value: COT_LABELS_ZH.get(str(value), str(value)) if language == "zh" else str(value)
            )
            show["net"] = pd.to_numeric(show["net"], errors="coerce")
            show["weekly_change"] = pd.to_numeric(show["weekly_change"], errors="coerce")
            show["percentile"] = pd.to_numeric(show["percentile"], errors="coerce")
            keep = ["Contract", "net", "weekly_change", "percentile", "Reading", "Report", "date"]
            st.dataframe(
                show[[column for column in keep if column in show.columns]].rename(
                    columns={
                        "Contract": tr(language, "Contract", "合约"),
                        "net": tr(language, "Net", "净头寸"),
                        "weekly_change": tr(language, "Weekly change", "当周变化"),
                        "percentile": tr(language, "Percentile", "历史分位"),
                        "Reading": tr(language, "Reading", "读法"),
                        "Report": tr(language, "Report", "报告口径"),
                        "date": tr(language, "Report date", "报告日"),
                    }
                ),
                hide_index=True,
                width="stretch",
            )
            with st.container(border=True):
                render_cot_history(artifact, language, window)

    section_heading(
        language,
        "Historical validation",
        "历史验证",
        "Descriptive, non-PIT replay of current rules using today's revised FRED history; inspect 5/20/60-session reactions before enabling formal alerts.",
        "使用当前修订版FRED历史进行描述性、非PIT规则回放；检查信号后5／20／60个交易日表现，再决定是否启用正式预警。",
    )
    render_regime_validation(artifact, language)

    section_heading(
        language,
        "Recent state transitions",
        "近期状态转折",
        "Only actual state changes are listed; unchanged daily observations are omitted.",
        "只列出真实状态变化，不显示状态未变的日常观察。",
    )
    render_regime_transitions(artifact, language)
    render_regime_source_coverage(artifact, labels, language)


def render_regime_source_coverage(
    artifact: dict[str, Any],
    labels: dict[str, Any],
    language: str,
) -> None:
    """Fail closed when the regime pipeline has no measured health contract."""
    if source_health_frame(artifact).empty:
        section_heading(
            language,
            "Source & coverage",
            "来源与覆盖范围",
            "Build-time lineage and observation dates stay visible.",
            "保留构建时来源链路和观察日期。",
        )
        st.warning(
            tr(
                language,
                "Source-health metadata is unavailable. No source should be interpreted as Ready.",
                "来源健康度元数据不可用；此时任何来源都不应被视为“可用”。",
            )
        )
        return
    render_source_coverage(
        {"regime": artifact},
        {"regime": labels},
        language,
    )
