"""Global market regime page assembly and regime UI.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .config import PALETTE

from .core import _regime_has_columns, _regime_history_window, _regime_state_label, chart_theme, frame_for_dataset, is_missing, observation_date_label, render_header, render_line_chart, section_heading, source_health_frame, tr

from .explorer import render_source_coverage

from .regime_labels import COT_LABELS_ZH, FOMC_DIST_LABELS_ZH, REGIME_DIST_LABELS_ZH, REGIME_DOMAIN_LABELS, REGIME_EXPOSURE_LABELS, REGIME_FRESHNESS_LABELS_ZH, REGIME_FRESHNESS_OK, REGIME_SERIES_LABELS, REGIME_SERIES_LABELS_ZH

from .regime_evidence import render_cot_history, render_credit_vix_evidence, render_cross_asset_context, render_regime_validation


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
            "Defensive radar for oil, Treasuries, CFTC positioning, Polymarket FOMC odds, Atlanta Fed SOFR odds, credit and VIX. Polymarket is a prediction-market price; Atlanta Fed is 3-month average SOFR odds. Neither is CME FedWatch.",
            "原油、美债、CFTC 持仓、Polymarket 下次 FOMC 赔率、Atlanta Fed SOFR 分布、信用利差和 VIX 的防守雷达。Polymarket 是预测市场价格；Atlanta Fed 是三个月平均 SOFR 概率。两者都不是 CME FedWatch。",
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

    section_heading(
        language,
        "Threshold evidence",
        "门槛证据",
        "Thresholds and true state-transition markers are overlaid on the history.",
        "历史走势同时标出门槛和真实状态转折点。",
    )
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            render_regime_threshold_chart(artifact, "brent", language, window)
    with right:
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
        "Credit and volatility",
        "信用与波动",
        "The decision rule uses same-date 20-day z-scores and five-day direction. Raw levels remain available for audit.",
        "决策规则使用同日20日z分数和5日方向；原始水平保留供核查。",
    )
    with st.container(border=True):
        render_credit_vix_evidence(artifact, language, window)

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
        "US Treasuries",
        "美国国债",
        "The curve compares four published sessions. The table is yield change in basis points, not bond returns. The 4.82% 10-year rule stays on the threshold cards; this tab only shows the surrounding structure.",
        "曲线比较四个已公布交易日。表格是收益率基点变化，不是债券回报。4.82% 的10年期规则仍在门槛卡上；这一页只展示周围的曲线结构。",
    )
    with st.container(border=True):
        render_treasury_curve_chart(artifact, language)
    with st.container(border=True):
        render_treasury_yield_table(artifact, language)

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
        "Cross-asset context",
        "跨资产背景",
        "Existing market-monitor index closes reused as context, not a second price database.",
        "复用现有 ETF 监控的指数收盘价作为背景，不再单独保存第二套价格。",
    )
    with st.container(border=True):
        render_cross_asset_context(artifact, language, window)

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
