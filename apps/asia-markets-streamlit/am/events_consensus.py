"""Interactive Events / Consensus mode for the private Market Monitor."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .core import chart_theme, section_heading, tr
from .paths import REPO_ROOT


TIMEZONE_OPTIONS = {
    "Asia/Taipei": ("Taipei / Hong Kong", "台北 / 香港"),
    "Europe/London": ("London", "伦敦"),
    "America/New_York": ("New York", "纽约"),
    "UTC": ("UTC", "UTC"),
}

STAGE_LABELS = {
    "watch": ("Watch", "观察"),
    "t_minus_5d": ("T-5d", "T-5日"),
    "t_minus_1d": ("T-1d", "T-1日"),
    "t_minus_60m": ("T-60m", "T-60分钟"),
    "t_plus_2m": ("T+2m", "T+2分钟"),
    "t_plus_30m": ("T+30m", "T+30分钟"),
    "end_of_day": ("EOD", "收盘"),
    "t_plus_1d": ("T+1d", "T+1日"),
    "unknown": ("Unknown", "未知"),
}


def _artifact_path() -> Path:
    from event_consensus.config import LATEST_ARTIFACT_PATH

    return LATEST_ARTIFACT_PATH


@st.cache_data(show_spinner=False)
def _read_artifact(path_text: str, mtime_ns: int) -> dict[str, Any] | None:
    del mtime_ns
    from event_consensus.storage import load_artifact

    return load_artifact(Path(path_text))


def load_event_consensus_artifact() -> dict[str, Any] | None:
    path = _artifact_path()
    return _read_artifact(str(path), path.stat().st_mtime_ns if path.exists() else 0)


def _run_manual_refresh() -> dict[str, Any]:
    # Deliberately imported only after a button click. Page navigation itself
    # remains a local read and cannot mutate a PIT ledger.
    from event_consensus.pipeline import run_pipeline

    result = run_pipeline(trigger_type="manual", write=True)
    _read_artifact.clear()
    return result["artifact"]


def _local_time(value: Any, timezone_name: str) -> str:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        return "—"
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp.tz_convert(ZoneInfo(timezone_name)).strftime("%a %d %b · %H:%M")


def _number(value: Any, unit: Any = None) -> str:
    if value is None or pd.isna(value):
        return "—"
    if isinstance(value, (int, float)):
        rendered = f"{float(value):,.2f}".rstrip("0").rstrip(".")
    else:
        rendered = str(value)
    suffix = str(unit or "").strip()
    return f"{rendered}{suffix}" if suffix in {"%", "pp", "bps"} else (
        f"{rendered} {suffix}" if suffix else rendered
    )


def _event_label(row: pd.Series, timezone_name: str) -> str:
    return (
        f"{_local_time(row.get('scheduled_at_utc'), timezone_name)} · "
        f"{row.get('country', '—')} · {row.get('title', '—')}"
    )


def _timeline_frame(
    events: pd.DataFrame,
    *,
    language: str,
    timezone_name: str,
) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    output = events.copy()
    output["time"] = output["scheduled_at_utc"].map(
        lambda value: _local_time(value, timezone_name)
    )
    output["checkpoint"] = output.get(
        "snapshot_stage",
        pd.Series("unknown", index=output.index),
    ).map(lambda value: tr(language, *STAGE_LABELS.get(str(value), (str(value), str(value)))))
    output["consensus"] = output.apply(
        lambda row: _number(row.get("forecast"), row.get("unit")),
        axis=1,
    )
    output["prior"] = output.apply(
        lambda row: _number(row.get("previous"), row.get("unit")),
        axis=1,
    )
    output["actual"] = output.apply(
        lambda row: _number(row.get("actual"), row.get("unit")),
        axis=1,
    )
    columns = [
        "time",
        "country",
        "title",
        "checkpoint",
        "consensus",
        "prior",
        "actual",
        "risk_score",
        "verification_status",
    ]
    labels_en = {
        "time": f"Time ({timezone_name})",
        "country": "Country",
        "title": "Event",
        "checkpoint": "Checkpoint",
        "consensus": "Consensus",
        "prior": "Prior",
        "actual": "Actual",
        "risk_score": "Risk / Catalyst",
        "verification_status": "Evidence",
    }
    labels_zh = {
        "time": f"时间（{timezone_name}）",
        "country": "国家",
        "title": "事件",
        "checkpoint": "检查点",
        "consensus": "市场预期",
        "prior": "前值",
        "actual": "实际值",
        "risk_score": "风险 / 催化评分",
        "verification_status": "证据状态",
    }
    return output[[column for column in columns if column in output]].rename(
        columns=labels_zh if language == "zh" else labels_en
    )


def _render_status(
    artifact: dict[str, Any],
    language: str,
    timezone_name: str,
) -> None:
    health = pd.DataFrame(artifact.get("source_health", []))
    healthy = int(health["status"].isin(["Healthy", "Ready"]).sum()) if not health.empty and "status" in health else 0
    total = int(len(health))
    generated = _local_time(artifact.get("generated_at_utc"), timezone_name)
    columns = st.columns(4)
    columns[0].metric(
        tr(language, "Artifact", "数据快照"),
        str(artifact.get("status") or "unavailable").title(),
    )
    columns[1].metric(
        tr(language, "Sources", "数据源"),
        f"{healthy}/{total}",
    )
    columns[2].metric(
        tr(language, "Events", "事件数"),
        len(artifact.get("events", [])),
    )
    columns[3].metric(
        tr(language, "Last refresh", "最近刷新"),
        generated,
    )
    if not health.empty and "source_id" in health.columns:
        futu = health[health["source_id"].astype(str).eq("futu_opend")]
        if not futu.empty:
            row = futu.iloc[0]
            st.caption(
                f"Futu OpenD: {row.get('status', 'Unavailable')} · "
                f"{row.get('notes', '')}"
            )


def _render_consensus(
    selected: pd.Series,
    artifact: dict[str, Any],
    language: str,
    timezone_name: str,
) -> None:
    unit = selected.get("unit")
    columns = st.columns(4)
    columns[0].metric(tr(language, "Consensus", "市场预期"), _number(selected.get("forecast"), unit))
    columns[1].metric(tr(language, "Prior", "前值"), _number(selected.get("previous"), unit))
    columns[2].metric(tr(language, "Actual", "实际值"), _number(selected.get("actual"), unit))
    columns[3].metric(tr(language, "Surprise", "预期差"), _number(selected.get("surprise"), unit))

    risk_fields = (
        ("risk_importance", "Importance", "重要性"),
        ("risk_proximity", "Proximity", "时间接近度"),
        ("risk_consensus", "Consensus available", "预期可用性"),
        ("risk_forecast_gap", "Forecast vs prior", "预期与前值差距"),
        ("risk_actual_surprise", "Actual surprise", "实际预期差"),
        ("risk_watchlist", "Watchlist relevance", "关注资产相关性"),
    )
    risk = pd.DataFrame(
        [
            {
                tr(language, "Factor", "评分因子"): tr(language, en, zh),
                tr(language, "Points", "分数"): selected.get(field),
            }
            for field, en, zh in risk_fields
        ]
    )
    st.caption(
        tr(
            language,
            "The score is descriptive and decomposed below. Consensus dispersion and event beta are not imputed.",
            "评分为描述性指标并在下方拆分；不会虚构预期分布或历史事件 beta。",
        )
    )
    st.dataframe(risk, hide_index=True, width="stretch")

    history = pd.DataFrame(artifact.get("consensus_history", []))
    if not history.empty and "event_id" in history.columns:
        history = history[
            history["event_id"].astype(str).eq(str(selected.get("event_id")))
        ].copy()
    if history.empty:
        st.info(tr(language, "No earlier PIT snapshots for this event.", "该事件尚无更早的 PIT 快照。"))
        return
    history["_time"] = history["retrieved_at_utc"].map(
        lambda value: _local_time(value, timezone_name)
    )
    chart = history.dropna(subset=["forecast"]).copy()
    if len(chart) >= 2:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=pd.to_datetime(chart["retrieved_at_utc"], utc=True),
                y=chart["forecast"],
                mode="lines+markers",
                name=tr(language, "Consensus", "市场预期"),
            )
        )
        fig.update_yaxes(title=str(unit or "value"))
        st.plotly_chart(
            chart_theme(fig, "number", date_axis=True, height=280),
            width="stretch",
            config={"displaylogo": False},
            key=f"event_consensus_history_{selected.get('event_id')}",
        )
    history_view = history[
        [
            column
            for column in (
                "_time",
                "snapshot_stage",
                "forecast",
                "previous",
                "actual",
                "trigger_type",
                "verification_status",
            )
            if column in history.columns
        ]
    ]
    st.dataframe(history_view, hide_index=True, width="stretch")


def _render_components(
    selected: pd.Series,
    artifact: dict[str, Any],
    language: str,
) -> None:
    family = str(selected.get("event_family") or "other")
    components = pd.DataFrame(artifact.get("component_contracts", []))
    if not components.empty:
        components = components[components["event_family"].astype(str).eq(family)].copy()
    if components.empty:
        st.info(
            tr(
                language,
                "No event-specific component contract is registered yet.",
                "目前尚未登记该事件的专属分项分析模板。",
            )
        )
        return
    official = pd.DataFrame(artifact.get("official_components", []))
    if not official.empty:
        official = official[
            official["event_family"].astype(str).eq(family)
        ].copy()
        available_columns = [
            column
            for column in (
                "component_id",
                "series_id",
                "reference_period",
                "latest_value",
                "mom_change",
                "payroll_change",
                "mom_change_pp",
                "mom_pct",
                "yoy_change_pp",
                "yoy_pct",
                "source_url",
                "verification_status",
            )
            if column in official.columns
        ]
        components = components.merge(
            official[available_columns],
            on="component_id",
            how="left",
        )
    label = "label_zh" if language == "zh" else "label_en"
    notes = "notes_zh" if language == "zh" else "notes_en"
    display = components[
        [
            column
            for column in (
                label,
                "group",
                "behavior",
                "weight",
                "weight_as_of",
                "weight_source_url",
                "reference_period",
                "latest_value",
                "payroll_change",
                "mom_change_pp",
                "mom_pct",
                "yoy_change_pp",
                "yoy_pct",
                "series_id",
                notes,
            )
            if column in components
        ]
    ].copy()
    display["weight"] = display.get("weight", pd.Series(index=display.index)).map(
        lambda value: (
            tr(language, "Awaiting dated official weight", "等待带日期的官方权重")
            if value is None or pd.isna(value)
            else f"{float(value):.3f}%"
        )
    )
    display = display.rename(
        columns={
            label: tr(language, "Component", "分项"),
            "group": tr(language, "Group", "类别"),
            "behavior": tr(language, "Behaviour", "性质"),
            "weight": tr(language, "Weight", "权重"),
            "weight_as_of": tr(language, "Weight as of", "权重日期"),
            "weight_source_url": tr(language, "Weight source", "权重来源"),
            "reference_period": tr(language, "Official period", "官方数据期"),
            "latest_value": tr(language, "Official level", "官方水平"),
            "payroll_change": tr(language, "Payroll change", "就业人数变化"),
            "mom_change_pp": tr(language, "MoM Δpp", "环比 Δ百分点"),
            "mom_pct": tr(language, "MoM %", "环比 %"),
            "yoy_change_pp": tr(language, "YoY Δpp", "同比 Δ百分点"),
            "yoy_pct": tr(language, "YoY %", "同比 %"),
            "series_id": tr(language, "Official series", "官方序列"),
            notes: tr(language, "Interpretation", "解读要点"),
        }
    )
    st.dataframe(display, hide_index=True, width="stretch")
    weight_urls = sorted(
        {
            str(value)
            for value in components.get("weight_source_url", pd.Series(dtype=object)).dropna()
            if str(value).strip()
        }
    )
    if weight_urls:
        st.caption(
            tr(language, "Reference-weight sources: ", "参考权重来源：")
            + " · ".join(weight_urls)
        )
    st.caption(
        tr(
            language,
            "This is the decomposition contract. Coarse dated reference weights are shown where available; current-month weights and missing component actuals remain unavailable rather than being backfilled with old assumptions.",
            "这里展示分项分析合同；有资料时显示带日期的粗粒度参考权重；当月权重或分项实际值缺失时保持不可用，不会用陈旧假设补齐。",
        )
    )
    if family == "cpi":
        st.caption(
            tr(
                language,
                "Aggregate rows such as core services ex shelter overlap; do not add every displayed weight as if the buckets were mutually exclusive.",
                "核心服务（剔除住房）等聚合项存在重叠；不要把表内所有权重当作互斥篮子直接相加。",
            )
        )


def _render_market_pricing(artifact: dict[str, Any], language: str, timezone_name: str) -> None:
    quotes = pd.DataFrame(artifact.get("quotes", []))
    if quotes.empty:
        st.info(tr(language, "No current cross-asset quote snapshot.", "目前没有跨资产行情快照。"))
        return
    quote_columns = st.columns(min(5, len(quotes)))
    for column, (_, row) in zip(quote_columns, quotes.head(5).iterrows()):
        delta = row.get("percent_change")
        column.metric(
            str(row.get("label") or row.get("symbol")),
            _number(row.get("current")),
            None if delta is None or pd.isna(delta) else f"{float(delta):+.2f}%",
        )
    display = quotes.copy()
    if "market_timestamp_utc" in display.columns:
        display["observed"] = display["market_timestamp_utc"].map(
            lambda value: _local_time(value, timezone_name)
        )
    columns = [
        column
        for column in (
            "symbol",
            "label",
            "asset_class",
            "current",
            "percent_change",
            "high",
            "low",
            "observed",
            "provider",
        )
        if column in display.columns
    ]
    st.dataframe(display[columns], hide_index=True, width="stretch")
    st.caption(
        tr(
            language,
            "This is a current cross-asset pulse, not yet an event-specific implied move or event beta.",
            "这是当前跨资产脉冲，不是事件专属的隐含波动或历史 event beta。",
        )
    )


def _render_scenarios(selected: pd.Series, artifact: dict[str, Any], language: str) -> None:
    family = str(selected.get("event_family") or "other")
    rows = artifact.get("scenario_templates", {}).get(family, [])
    if not rows:
        st.info(tr(language, "No scenario template is registered for this event.", "该事件尚无情景模板。"))
        return
    frame = pd.DataFrame(rows)
    label = "label_zh" if language == "zh" else "label_en"
    invalidation = "invalidation_zh" if language == "zh" else "invalidation_en"
    columns = [
        column
        for column in (
            label,
            "rates",
            "usd",
            "spy",
            "qqq",
            "soxx",
            "sk_hynix",
            "gold",
            invalidation,
        )
        if column in frame.columns
    ]
    st.dataframe(
        frame[columns].rename(
            columns={
                label: tr(language, "Scenario", "情景"),
                "rates": tr(language, "Rates", "利率资产"),
                "usd": tr(language, "USD", "美元"),
                "spy": "SPY",
                "qqq": "QQQ",
                "soxx": "SOXX",
                "sk_hynix": tr(language, "SK Hynix", "SK 海力士"),
                "gold": tr(language, "Gold", "黄金"),
                invalidation: tr(language, "Invalidation", "失效条件"),
            }
        ),
        hide_index=True,
        width="stretch",
    )
    st.warning(
        tr(
            language,
            "Conditional research template only. Confirm the component mix and live market pricing before using it.",
            "这里只是条件式研究模板；使用前必须确认分项结构与实时市场定价。",
        )
    )


def _render_post_release(selected: pd.Series, language: str) -> None:
    actual = selected.get("actual")
    if actual is None or pd.isna(actual):
        st.info(
            tr(
                language,
                "The event has not produced an actual in the current source snapshot.",
                "当前来源快照尚未提供该事件的实际值。",
            )
        )
        return
    st.metric(
        tr(language, "Third-party reported actual", "第三方报告实际值"),
        _number(actual, selected.get("unit")),
        _number(selected.get("surprise"), selected.get("unit")),
    )
    st.warning(
        tr(
            language,
            "Verification status: "
            + str(selected.get("verification_status") or "unknown")
            + ". Do not treat this as official until the official adapter confirms it.",
            "验证状态："
            + str(selected.get("verification_status") or "unknown")
            + "。在官方 adapter 确认前，不得视为官方实际值。",
        )
    )
    if selected.get("official_value") is not None and not pd.isna(selected.get("official_value")):
        st.metric(
            tr(language, "Official cross-check", "官方交叉核验"),
            _number(selected.get("official_value"), selected.get("unit")),
        )
        st.caption(
            " · ".join(
                (
                    str(selected.get("official_series_id") or "—"),
                    str(selected.get("official_reference_period") or "—"),
                    str(selected.get("verification_status") or "—"),
                )
            )
        )


def render_events_consensus(language: str) -> None:
    section_heading(
        language,
        "Events / Consensus",
        "事件 / 市场预期",
        "A point-in-time timeline for macro catalysts, expectation revisions and conditional risk responses.",
        "以 PIT 快照跟踪宏观催化点、预期变化及条件式风险应对。",
    )

    controls = st.columns([2, 1, 1])
    timezone_name = controls[0].selectbox(
        tr(language, "Display timezone", "显示时区"),
        list(TIMEZONE_OPTIONS),
        index=0,
        key="event_consensus_timezone",
        format_func=lambda name: tr(language, *TIMEZONE_OPTIONS[name]),
    )
    refresh = controls[1].button(
        tr(language, "Refresh all now", "立即刷新全部"),
        type="primary",
        width="stretch",
        key="event_consensus_refresh_all",
    )
    controls[2].caption(
        tr(
            language,
            "Navigation is read-only. This button appends a manual PIT snapshot.",
            "页面浏览只读；该按钮会追加一份手动 PIT 快照。",
        )
    )

    artifact = load_event_consensus_artifact()
    if refresh:
        try:
            with st.spinner(tr(language, "Fetching calendar, consensus and quotes…", "正在抓取事件、预期与行情…")):
                artifact = _run_manual_refresh()
            st.success(tr(language, "Manual snapshot appended.", "已追加手动快照。"))
        except Exception as exc:
            st.error(
                tr(
                    language,
                    f"Refresh failed: {type(exc).__name__}. The previous artifact was kept.",
                    f"刷新失败：{type(exc).__name__}。已保留上一份有效快照。",
                )
            )

    if not artifact:
        st.info(
            tr(
                language,
                "No local event artifact exists yet. Use Refresh all now; no remote request is made merely by opening this page.",
                "目前尚无本地事件快照。请点击“立即刷新全部”；仅打开页面不会发起远程请求。",
            )
        )
        return

    _render_status(artifact, language, timezone_name)
    events = pd.DataFrame(artifact.get("events", []))
    if events.empty:
        st.warning(tr(language, "No usable events in the current window.", "当前窗口没有可用事件。"))
        return

    filter_columns = st.columns([3, 1])
    country_options = sorted(events["country"].dropna().astype(str).unique())
    selected_countries = filter_columns[0].multiselect(
        tr(language, "Countries", "国家"),
        country_options,
        default=country_options,
        key="event_consensus_countries",
    )
    major_only = filter_columns[1].toggle(
        tr(language, "Medium/high only", "仅中高重要性"),
        value=True,
        key="event_consensus_major_only",
        help=tr(
            language,
            "Hide the provider's low-importance events from the default decision view.",
            "默认决策视图隐藏数据商标记为低重要性的事件。",
        ),
    )
    filtered = events[events["country"].astype(str).isin(selected_countries)].copy()
    if major_only and "importance" in filtered.columns:
        filtered = filtered[
            pd.to_numeric(filtered["importance"], errors="coerce").fillna(-1).ge(0)
        ]
    filtered["_scheduled"] = pd.to_datetime(
        filtered["scheduled_at_utc"],
        errors="coerce",
        utc=True,
    )
    now = pd.Timestamp(datetime.now(timezone.utc))
    upcoming = filtered[filtered["_scheduled"].ge(now)].copy()
    recent = filtered[filtered["_scheduled"].lt(now)].copy()
    upcoming = upcoming.sort_values(
        ["risk_score", "scheduled_at_utc"],
        ascending=[False, True],
    )
    recent = recent.sort_values(
        ["scheduled_at_utc", "risk_score"],
        ascending=[False, False],
    )

    st.markdown(
        f"#### {tr(language, 'Next 7–14 days', '未来 7–14 天')}"
    )
    st.dataframe(
        _timeline_frame(upcoming, language=language, timezone_name=timezone_name),
        hide_index=True,
        width="stretch",
        height=min(520, 38 + max(1, len(upcoming)) * 35),
    )
    if not recent.empty:
        with st.expander(
            tr(
                language,
                f"Recent releases ({len(recent)})",
                f"最近已公布事件（{len(recent)}）",
            ),
            expanded=False,
        ):
            st.dataframe(
                _timeline_frame(
                    recent,
                    language=language,
                    timezone_name=timezone_name,
                ),
                hide_index=True,
                width="stretch",
            )

    console_events = upcoming if not upcoming.empty else recent
    if console_events.empty:
        return
    event_ids = console_events["event_id"].astype(str).tolist()
    selected_id = st.selectbox(
        tr(language, "Open event console", "打开事件控制台"),
        event_ids,
        key="event_consensus_selected_event",
        format_func=lambda value: _event_label(
            console_events[
                console_events["event_id"].astype(str).eq(value)
            ].iloc[0],
            timezone_name,
        ),
    )
    selected = console_events[
        console_events["event_id"].astype(str).eq(str(selected_id))
    ].iloc[0]

    console_heading, console_refresh = st.columns([4, 1])
    console_heading.markdown(f"### {selected.get('title', '—')}")
    refresh_selected = console_refresh.button(
        tr(language, "Refresh selected", "刷新所选事件"),
        width="stretch",
        key="event_consensus_refresh_selected",
        help=tr(
            language,
            "The free calendar endpoint returns the current window; only the selected event console is kept open.",
            "免费日历接口会返回当前窗口；刷新后仍保持所选事件控制台。",
        ),
    )
    if refresh_selected:
        try:
            with st.spinner(tr(language, "Refreshing selected event…", "正在刷新所选事件…")):
                _run_manual_refresh()
            st.rerun()
        except Exception as exc:
            st.error(
                tr(
                    language,
                    f"Selected-event refresh failed: {type(exc).__name__}.",
                    f"所选事件刷新失败：{type(exc).__name__}。",
                )
            )
    st.caption(
        " · ".join(
            (
                str(selected.get("country") or "—"),
                _local_time(selected.get("scheduled_at_utc"), timezone_name),
                tr(language, *STAGE_LABELS.get(str(selected.get("snapshot_stage")), ("Unknown", "未知"))),
                f"{tr(language, 'score', '评分')} {selected.get('risk_score', '—')}",
            )
        )
    )

    tabs = st.tabs(
        [
            tr(language, "Consensus", "市场预期"),
            tr(language, "Components", "分项"),
            tr(language, "Market pricing", "市场定价"),
            tr(language, "Scenarios", "情景"),
            tr(language, "Post-release", "公布后"),
            tr(language, "Sources", "来源"),
        ]
    )
    with tabs[0]:
        _render_consensus(selected, artifact, language, timezone_name)
    with tabs[1]:
        _render_components(selected, artifact, language)
    with tabs[2]:
        _render_market_pricing(artifact, language, timezone_name)
    with tabs[3]:
        _render_scenarios(selected, artifact, language)
    with tabs[4]:
        _render_post_release(selected, language)
    with tabs[5]:
        health = pd.DataFrame(artifact.get("source_health", []))
        if not health.empty:
            st.dataframe(health, hide_index=True, width="stretch")
        lineage = pd.DataFrame(
            [
                {
                    tr(language, "Provider", "提供方"): selected.get("provider"),
                    tr(language, "Source", "来源"): selected.get("source_name"),
                    tr(language, "Source URL", "来源 URL"): selected.get("source_url"),
                    tr(language, "First observed", "首次观察"): selected.get("first_observed_at_utc"),
                    tr(language, "Retrieved", "抓取时间"): selected.get("retrieved_at_utc"),
                    tr(language, "Provider published", "提供方发布时间"): selected.get("provider_published_at"),
                    tr(language, "Payload checksum", "Payload 校验和"): selected.get("payload_checksum"),
                    tr(language, "Trigger", "触发类型"): selected.get("trigger_type"),
                }
            ]
        )
        st.dataframe(lineage, hide_index=True, width="stretch")
        for caveat in artifact.get("caveats", []):
            st.caption(f"• {caveat}")
        st.caption(
            tr(
                language,
                f"Local artifact: {_artifact_path().relative_to(REPO_ROOT)}",
                f"本地快照：{_artifact_path().relative_to(REPO_ROOT)}",
            )
        )
