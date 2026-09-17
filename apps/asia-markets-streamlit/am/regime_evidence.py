"""Regime evidence: validation, credit/VIX, COT and cross-asset heatmap.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from global_market_regime.presentation import rebase_price_history

from .config import PALETTE

from .core import apply_line_hover, chart_theme, frame_for_dataset, latest_row, render_line_chart, tr

from .regime_labels import (
    REGIME_CROSS_ASSET_CORE,
    REGIME_EXPOSURE_LABELS,
    REGIME_INDICATOR_LABELS,
    REGIME_RETURN_HORIZONS,
    REGIME_SERIES_LABELS,
    REGIME_SERIES_LABELS_ZH,
    REGIME_US_SECTOR_AUX,
)

from .core import _regime_has_columns, _regime_history_window, _regime_state_label


def render_regime_validation(artifact: dict[str, Any], language: str) -> None:
    """Show descriptive historical diagnostics without implying causality."""
    episodes = frame_for_dataset(artifact, "signal_episodes")
    forward = frame_for_dataset(artifact, "event_forward_summary")
    sensitivity = frame_for_dataset(artifact, "threshold_sensitivity")
    episode_tab, reaction_tab, threshold_tab = st.tabs(
        [
            tr(language, "Signal episodes", "信号事件"),
            tr(language, "Forward reactions", "后续市场表现"),
            tr(language, "Threshold sensitivity", "门槛敏感度"),
        ]
    )
    with episode_tab:
        if not _regime_has_columns(
            episodes,
            (
                "indicator_id",
                "start_date",
                "end_date",
                "max_state",
                "observation_count",
                "open_episode",
                "duration_calendar_days",
            ),
        ):
            st.info(tr(language, "No historical episodes are available.", "暂无历史信号事件。"))
        else:
            options = list(dict.fromkeys(episodes["indicator_id"].astype(str).tolist()))
            selected = st.selectbox(
                tr(language, "Indicator", "指标"),
                options,
                format_func=lambda value: REGIME_INDICATOR_LABELS.get(
                    value, (value, value)
                )[1 if language == "zh" else 0],
                key=f"regime_episode_indicator_{language}",
            )
            show = episodes[episodes["indicator_id"].astype(str).eq(selected)].copy()
            show = show.sort_values("start_date", ascending=False)
            show["State"] = show["max_state"].map(
                lambda value: _regime_state_label(value, language)
            )
            show["Open"] = show["open_episode"].map(
                lambda value: tr(language, "Open", "进行中")
                if bool(value)
                else tr(language, "Closed", "已结束")
            )
            table = show[
                [
                    "start_date",
                    "end_date",
                    "State",
                    "observation_count",
                    "duration_calendar_days",
                    "Open",
                ]
            ].rename(
                columns={
                    "start_date": tr(language, "Start", "开始"),
                    "end_date": tr(language, "End", "结束"),
                    "State": tr(language, "Maximum state", "最高状态"),
                    "observation_count": tr(language, "Observations", "观察数"),
                    "duration_calendar_days": tr(language, "Calendar days", "自然日"),
                    "Open": tr(language, "Status", "状态"),
                }
            )
            st.caption(
                tr(
                    language,
                    f"{len(show)} non-Normal episode(s) under the current state definitions.",
                    f"按当前状态定义识别出{len(show)}段非正常事件。",
                )
            )
            st.dataframe(table, hide_index=True, width="stretch")

    with reaction_tab:
        st.caption(
            tr(
                language,
                "Descriptive post-event returns, not causal estimates or trading recommendations. Always read the sample size.",
                "以下为事件后的描述性回报，不是因果估计或交易建议；必须同时查看样本数。",
            )
        )
        if not _regime_has_columns(
            forward,
            (
                "indicator_id",
                "state",
                "exposure_id",
                "horizon_sessions",
                "event_count",
                "median_forward_return_pct",
                "mean_forward_return_pct",
                "positive_share_pct",
            ),
        ):
            st.info(tr(language, "No forward-reaction sample is available.", "暂无后续市场表现样本。"))
        else:
            indicator_options = list(
                dict.fromkeys(forward["indicator_id"].astype(str).tolist())
            )
            selected_indicator = st.selectbox(
                tr(language, "Trigger", "触发指标"),
                indicator_options,
                format_func=lambda value: REGIME_INDICATOR_LABELS.get(
                    value, (value, value)
                )[1 if language == "zh" else 0],
                key=f"regime_forward_indicator_{language}",
            )
            filtered = forward[
                forward["indicator_id"].astype(str).eq(selected_indicator)
            ].copy()
            state_options = list(
                dict.fromkeys(filtered["state"].dropna().astype(str).tolist())
            )
            if len(state_options) > 1:
                selected_state = st.selectbox(
                    tr(language, "Trigger state", "触发状态"),
                    state_options,
                    format_func=lambda value: _regime_state_label(value, language),
                    key=f"regime_forward_state_{language}",
                )
                filtered = filtered[filtered["state"].astype(str).eq(selected_state)]
            horizon_options = sorted(
                pd.to_numeric(filtered["horizon_sessions"], errors="coerce")
                .dropna()
                .astype(int)
                .unique()
                .tolist()
            )
            if not horizon_options:
                st.info(
                    tr(
                        language,
                        "No complete forward-return window is available.",
                        "暂无完整的后续回报窗口。",
                    )
                )
                horizon_options = [20]
            selected_horizon = st.selectbox(
                tr(language, "Forward window", "后续窗口"),
                horizon_options,
                index=horizon_options.index(20) if 20 in horizon_options else 0,
                format_func=lambda value: tr(
                    language, f"{value} sessions", f"{value}个交易日"
                ),
                key=f"regime_forward_horizon_{language}",
            )
            filtered = filtered[
                pd.to_numeric(
                    filtered["horizon_sessions"], errors="coerce"
                ).eq(selected_horizon)
            ]
            if filtered.empty:
                st.info(tr(language, "No matching sample.", "没有符合条件的样本。"))
            else:
                filtered["Exposure"] = filtered["exposure_id"].map(
                    lambda value: REGIME_EXPOSURE_LABELS.get(
                        str(value), (str(value), str(value))
                    )[1 if language == "zh" else 0]
                )
                filtered["Median"] = pd.to_numeric(
                    filtered["median_forward_return_pct"], errors="coerce"
                )
                fig = go.Figure(
                    go.Bar(
                        x=filtered["Exposure"],
                        y=filtered["Median"],
                        marker_color=[
                            PALETTE[0] if value >= 0 else PALETTE[1]
                            for value in filtered["Median"].fillna(0)
                        ],
                        customdata=filtered[
                            ["event_count", "mean_forward_return_pct", "positive_share_pct"]
                        ].to_numpy(),
                        hovertemplate=(
                            "<b>%{x}</b><br>"
                            + tr(language, "Median", "中位数")
                            + ": %{y:.2f}%<br>"
                            + tr(language, "Events", "事件数")
                            + ": %{customdata[0]}<br>"
                            + tr(language, "Mean", "平均值")
                            + ": %{customdata[1]:.2f}%<br>"
                            + tr(language, "Positive share", "正回报占比")
                            + ": %{customdata[2]:.1f}%<extra></extra>"
                        ),
                    )
                )
                chart_theme(fig, height=360)
                fig.update_yaxes(
                    title=tr(
                        language,
                        "Median forward return %",
                        "后续回报中位数%",
                    )
                )
                st.plotly_chart(
                    fig,
                    width="stretch",
                    config={"displaylogo": False, "responsive": True},
                )
                table = filtered[
                    [
                        "Exposure",
                        "state",
                        "event_count",
                        "median_forward_return_pct",
                        "mean_forward_return_pct",
                        "positive_share_pct",
                    ]
                ].copy()
                table["state"] = table["state"].map(
                    lambda value: _regime_state_label(value, language)
                )
                st.dataframe(
                    table.rename(
                        columns={
                            "Exposure": tr(language, "Exposure", "市场"),
                            "state": tr(language, "Trigger state", "触发状态"),
                            "event_count": tr(language, "Events", "事件数"),
                            "median_forward_return_pct": tr(
                                language, "Median return %", "回报中位数%"
                            ),
                            "mean_forward_return_pct": tr(
                                language, "Mean return %", "平均回报%"
                            ),
                            "positive_share_pct": tr(
                                language, "Positive share %", "正回报占比%"
                            ),
                        }
                    ),
                    hide_index=True,
                    width="stretch",
                )

    with threshold_tab:
        if not _regime_has_columns(
            sensitivity,
            (
                "indicator_id",
                "threshold",
                "above_share_pct",
                "raw_hit_episode_count",
                "is_current_threshold",
                "observation_count",
                "start_date",
                "end_date",
            ),
        ):
            st.info(tr(language, "No threshold sensitivity history is available.", "暂无门槛敏感度历史。"))
        else:
            options = list(
                dict.fromkeys(sensitivity["indicator_id"].astype(str).tolist())
            )
            selected = st.selectbox(
                tr(language, "Indicator", "指标"),
                options,
                format_func=lambda value: REGIME_INDICATOR_LABELS.get(
                    value, (value, value)
                )[1 if language == "zh" else 0],
                key=f"regime_sensitivity_indicator_{language}",
            )
            show = sensitivity[
                sensitivity["indicator_id"].astype(str).eq(selected)
            ].copy()
            show["Current"] = show["is_current_threshold"].map(
                lambda value: "●" if bool(value) else ""
            )
            st.dataframe(
                show[
                    [
                        "threshold",
                        "Current",
                        "above_share_pct",
                        "raw_hit_episode_count",
                        "observation_count",
                        "start_date",
                        "end_date",
                    ]
                ].rename(
                    columns={
                        "threshold": tr(language, "Threshold", "门槛"),
                        "Current": tr(language, "Current rule", "当前规则"),
                        "above_share_pct": tr(
                            language, "Observations above %", "高于门槛的观察占比%"
                        ),
                        "raw_hit_episode_count": tr(
                            language, "Raw hit episodes", "原始命中事件数"
                        ),
                        "observation_count": tr(
                            language, "Observations", "观察数"
                        ),
                        "start_date": tr(language, "Start", "开始"),
                        "end_date": tr(language, "End", "结束"),
                    }
                ),
                hide_index=True,
                width="stretch",
            )


def render_credit_vix_evidence(artifact: dict[str, Any], language: str, window: str) -> None:
    frame = _regime_history_window(
        frame_for_dataset(artifact, "credit_vix_signal_history"),
        window,
    )
    if not _regime_has_columns(frame, ("date", "hy_z", "vix_z")):
        st.info(tr(language, "No credit/VIX history is available.", "暂无信用利差／VIX历史数据。"))
        return
    fig = go.Figure()
    for field, label, color in (
        ("hy_z", tr(language, "HY OAS 20D z-score", "高收益债利差20日z分数"), PALETTE[0]),
        ("vix_z", tr(language, "VIX 20D z-score", "VIX 20日z分数"), PALETTE[1]),
    ):
        values = pd.to_numeric(frame[field], errors="coerce")
        fig.add_trace(
            go.Scatter(
                x=frame["date"],
                y=values,
                mode="lines",
                name=label,
                line={"color": color, "width": 2},
            )
        )
    fig.add_hline(y=1.0, line_dash="dash", line_color="#ef4444")
    chart_theme(fig, height=410)
    apply_line_hover(fig, frame.rename(columns={"date": "_date"}), "number")
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})
    with st.expander(tr(language, "Show raw HY OAS and VIX levels", "查看高收益债利差与VIX原始水平")):
        render_line_chart(
            artifact,
            artifact,
            "credit_vix_chart",
            language,
            window,
            series_selection=("hy_oas", "vix"),
            views=("Level",),
            periods_per_year=252,
            height=360,
            series_label_map=REGIME_SERIES_LABELS_ZH if language == "zh" else REGIME_SERIES_LABELS,
            title_override=tr(language, "High-yield OAS and VIX", "高收益债利差与VIX"),
            subtitle_override=tr(
                language,
                "Raw ICE BofA US High Yield OAS and CBOE VIX levels.",
                "ICE BofA美国高收益债利差与CBOE VIX原始水平。",
            ),
        )



CNN_RATING_LABELS_ZH = {
    "extreme fear": "极度恐惧",
    "fear": "恐惧",
    "neutral": "中性",
    "greed": "贪婪",
    "extreme greed": "极度贪婪",
}
CNN_RATING_COLORS = {
    "extreme fear": "#7f1d1d",
    "fear": "#b45309",
    "neutral": "#64748b",
    "greed": "#047857",
    "extreme greed": "#065f46",
}
CNN_COMPONENT_ORDER = (
    "momentum",
    "strength",
    "breadth",
    "put_call",
    "vix",
    "junk_bond",
    "safe_haven",
)
CNN_COMPONENT_UNITS = {
    "momentum": ("S&P 500 level", "标普500水平"),
    "strength": ("Net new highs %", "净新高占比"),
    "breadth": ("McClellan oscillator", "麦氏振荡指标"),
    "put_call": ("Put/call ratio", "看跌／看涨比"),
    "vix": ("VIX level", "VIX水平"),
    "junk_bond": ("HY vs IG spread", "高收益相对投资级利差"),
    "safe_haven": ("Stocks vs bonds return gap", "股票相对债券回报差"),
}
CNN_COMPONENT_DIRECTION = {
    "momentum": 1,
    "strength": 1,
    "breadth": 1,
    "safe_haven": 1,
    "put_call": -1,
    "vix": -1,
    "junk_bond": -1,
}
CNN_MOMENTUM_MA_WINDOW = 125


def _cnn_rating_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _cnn_rating_label(value: Any, language: str) -> str:
    key = _cnn_rating_key(value)
    if not key:
        return "—"
    if language == "zh":
        return CNN_RATING_LABELS_ZH.get(key, str(value))
    return key.replace("_", " ").title()


def _cnn_rating_color(value: Any) -> str:
    return CNN_RATING_COLORS.get(_cnn_rating_key(value), "#2563eb")


def _cnn_official_score_hovertemplate(official_label: str) -> str:
    """Return a Plotly tooltip with a rendered official 0-100 score."""
    return f"<b>%{{x|%d %b %Y}}</b><br>{official_label}: %{{y:.0f}}<extra></extra>"


def cnn_component_proxy_percentile(full_frame: pd.DataFrame, component_id: str) -> pd.DataFrame:
    """Direction-adjusted percentile-of-history proxy for one CNN component.

    CNN publishes 0-100 component scores only for the latest day, so the
    component charts cannot reuse the composite scored history. Instead each
    raw input is ranked against all available history (0-100) and flipped for
    components where a high raw value means fear (VIX, put/call ratio,
    junk-bond spread). Momentum is first converted to price versus its
    125-day average, matching CNN's own definition, because its raw level is
    an index point value rather than a sentiment input.
    """
    empty = pd.DataFrame(columns=["date", "proxy"])
    if full_frame is None or full_frame.empty:
        return empty
    if "component_id" not in full_frame.columns or "raw_value" not in full_frame.columns:
        return empty
    frame = full_frame[full_frame["component_id"].astype(str).eq(str(component_id))].copy()
    if frame.empty:
        return empty
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["raw_value"] = pd.to_numeric(frame["raw_value"], errors="coerce")
    frame = frame.dropna(subset=["date", "raw_value"]).sort_values("date", kind="mergesort")
    if frame.empty:
        return empty
    if str(component_id) == "momentum":
        values = frame["raw_value"] / frame["raw_value"].rolling(CNN_MOMENTUM_MA_WINDOW).mean()
        direction = 1
    else:
        direction = CNN_COMPONENT_DIRECTION.get(str(component_id))
        if direction is None:
            return empty
        values = frame["raw_value"]
    values = pd.to_numeric(values, errors="coerce")
    ranked = values.rank(method="average", pct=True) * 100.0
    if direction < 0:
        ranked = 100.0 - ranked
    frame["proxy"] = ranked
    return frame.dropna(subset=["proxy"])[["date", "proxy"]].reset_index(drop=True)


CNN_RATING_ORDER = ("extreme fear", "fear", "neutral", "greed", "extreme greed")


def _cnn_band_label(key: str, language: str) -> str:
    if key == "extreme fear":
        return tr(language, "0-24 Extreme Fear", "0–24 极度恐惧")
    if key == "fear":
        return tr(language, "25-44 Fear", "25–44 恐惧")
    if key == "neutral":
        return tr(language, "45-55 Neutral", "45–55 中性")
    if key == "greed":
        return tr(language, "56-74 Greed", "56–74 贪婪")
    return tr(language, "75-100 Extreme Greed", "75–100 极度贪婪")


def _add_cnn_rating_legend(fig: Any, language: str, *, include_score_bands: bool) -> None:
    for key in CNN_RATING_ORDER:
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                name=_cnn_band_label(key, language) if include_score_bands else _cnn_rating_label(key, language),
                marker={"color": CNN_RATING_COLORS[key], "size": 8},
                hoverinfo="skip",
                showlegend=True,
            )
        )


def render_vix_history(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    render_line_chart(
        artifact,
        labels,
        "vix_history_chart",
        language,
        window,
        series_selection=("vix",),
        views=("Level",),
        periods_per_year=252,
        height=390,
        series_label_map=REGIME_SERIES_LABELS_ZH if language == "zh" else REGIME_SERIES_LABELS,
        title_override=tr(language, "CBOE VIX", "CBOE VIX"),
        subtitle_override=tr(
            language,
            "Daily CBOE Volatility Index via FRED. This is the raw VIX level, not the credit/VIX sync-stress rule.",
            "FRED 提供的 CBOE 波动率指数日度水平。这是原始 VIX，不是信用／VIX 同步压力规则。",
        ),
    )


def render_cnn_fear_greed(artifact: dict[str, Any], language: str, window: str) -> None:
    frame = _regime_history_window(frame_for_dataset(artifact, "cnn_fear_greed_history"), window)
    if not _regime_has_columns(frame, ("date", "component_id", "score")):
        st.info(
            tr(
                language,
                "CNN Fear & Greed is not in this artifact yet.",
                "这个数据快照还没有 CNN 恐惧与贪婪指数。",
            )
        )
        return
    composite = frame[frame["component_id"].astype(str).eq("composite")].copy()
    composite["score"] = pd.to_numeric(composite["score"], errors="coerce")
    composite = composite.dropna(subset=["date", "score"]).sort_values("date")
    if composite.empty:
        st.info(
            tr(
                language,
                "CNN Fear & Greed is not in this artifact yet.",
                "这个数据快照还没有 CNN 恐惧与贪婪指数。",
            )
        )
        return
    latest = latest_row(composite)
    score = pd.to_numeric(pd.Series([latest.get("score")]), errors="coerce").iloc[0]
    rating = _cnn_rating_label(latest.get("rating"), language)
    as_of = pd.to_datetime(latest.get("date"), errors="coerce")
    as_of_label = as_of.strftime("%Y-%m-%d") if not pd.isna(as_of) else "—"
    score_label = "—" if pd.isna(score) else f"{score:.0f}"
    st.markdown(
        f'<div class="am-chart-title">{tr(language, "CNN Fear & Greed", "CNN恐惧与贪婪")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        tr(
            language,
            f"Latest {score_label} ({rating}) as of {as_of_label}. Bands: 0-24 extreme fear, 25-44 fear, 45-55 neutral, 56-74 greed, 75-100 extreme greed. Not crypto Fear & Greed.",
            f"最新 {score_label}（{rating}），截至 {as_of_label}。色带：0–24 极度恐惧，25–44 恐惧，45–55 中性，56–74 贪婪，75–100 极度贪婪。不是加密恐惧与贪婪。",
        )
    )
    fig = go.Figure(
        go.Scatter(
            x=composite["date"],
            y=composite["score"],
            mode="lines",
            name=tr(language, "CNN Fear & Greed", "CNN恐惧与贪婪"),
            line={"color": PALETTE[0], "width": 2},
            hovertemplate="<b>%{x|%d %b %Y}</b><br>%{y:.1f}<extra></extra>",
        )
    )
    fig.add_hrect(y0=0, y1=25, fillcolor="#7f1d1d", opacity=0.10, line_width=0)
    fig.add_hrect(y0=25, y1=45, fillcolor="#b45309", opacity=0.08, line_width=0)
    fig.add_hrect(y0=45, y1=55, fillcolor="#64748b", opacity=0.06, line_width=0)
    fig.add_hrect(y0=55, y1=75, fillcolor="#047857", opacity=0.08, line_width=0)
    fig.add_hrect(y0=75, y1=100, fillcolor="#065f46", opacity=0.10, line_width=0)
    fig.update_yaxes(
        range=[0, 100],
        title=tr(language, "Score", "分数"),
        tickvals=[0, 25, 45, 55, 75, 100],
    )
    _add_cnn_rating_legend(fig, language, include_score_bands=True)
    fig.update_layout(legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0})
    chart_theme(fig, height=430)
    apply_line_hover(fig, composite.rename(columns={"date": "_date", "score": "_value"}), "number")
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})


def render_cnn_fear_greed_components(artifact: dict[str, Any], language: str, window: str) -> None:
    full_frame = frame_for_dataset(artifact, "cnn_fear_greed_history")
    frame = _regime_history_window(full_frame, window)
    if not _regime_has_columns(frame, ("date", "component_id")):
        st.info(
            tr(
                language,
                "CNN Fear & Greed components are not in this artifact yet.",
                "这个数据快照还没有 CNN 恐惧与贪婪分项。",
            )
        )
        return
    components = frame[frame["component_id"].astype(str).ne("composite")].copy()
    if components.empty:
        st.info(
            tr(
                language,
                "CNN Fear & Greed components are not in this artifact yet.",
                "这个数据快照还没有 CNN 恐惧与贪婪分项。",
            )
        )
        return
    components["score"] = pd.to_numeric(components.get("score"), errors="coerce")
    latest_components = (
        components.dropna(subset=["score"])
        .sort_values("date")
        .drop_duplicates("component_id", keep="last")
    )
    if latest_components.empty:
        latest_components = components.sort_values("date").drop_duplicates("component_id", keep="last")
    label_field = "label_zh" if language == "zh" else "label_en"
    latest_components = latest_components.copy()
    latest_components["_order"] = latest_components["component_id"].map(
        {key: idx for idx, key in enumerate(CNN_COMPONENT_ORDER)}
    )
    latest_components = latest_components.sort_values(["_order", "component_id"], kind="mergesort")
    with st.container(border=True):
        st.markdown(
            f'<div class="am-chart-title">{tr(language, "CNN component snapshot", "CNN分项快照")}</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            tr(
                language,
                "Latest 0-100 component scores. CNN only publishes these scores for the most recent day.",
                "各分项最新 0–100 分数。CNN 只对最新一天公布这些分数。",
            )
        )
        table = pd.DataFrame(
            {
                tr(language, "Component", "分项"): latest_components.get(label_field, latest_components["component_id"]),
                tr(language, "Score", "分数"): latest_components["score"].map(
                    lambda value: "—" if pd.isna(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]) else f"{float(value):.0f}"
                ),
                tr(language, "Reading", "读法"): [
                    _cnn_rating_label(value, language) for value in latest_components.get("rating", [])
                ],
            }
        )
        st.dataframe(table, hide_index=True, width="stretch")
    _render_cnn_component_charts(components, full_frame, latest_components, language)


def _render_cnn_component_charts(
    history: pd.DataFrame,
    full_history: pd.DataFrame,
    latest_components: pd.DataFrame,
    language: str,
) -> None:
    if history.empty or "component_id" not in history.columns:
        return
    frame = history.copy()
    frame["raw_value"] = pd.to_numeric(frame.get("raw_value"), errors="coerce")
    frame = frame.dropna(subset=["date", "raw_value"])
    if frame.empty:
        st.caption(
            tr(
                language,
                "CNN publishes a 0-100 score for each component only on the latest day. The charts below use CNN's raw historical inputs.",
                "CNN 只对最新一天公布各分项的 0–100 分数。下面的图使用 CNN 实际保存的原始输入。",
            )
        )
        return
    view = st.radio(
        tr(language, "Chart view", "图表视图"),
        options=["percentile", "raw"],
        format_func=lambda value: (
            tr(language, "Percentile proxy (banded)", "分位代理（含色带）")
            if value == "percentile"
            else tr(language, "Raw inputs", "原始输入")
        ),
        horizontal=True,
        key=f"cnn_component_chart_view_{language}",
    )
    if view == "percentile":
        st.caption(
            tr(
                language,
                "Blue line: each raw input ranked 0-100 against available history, flipped where a high value means fear; momentum uses price vs its 125-day average. Diamond: CNN's official latest score. CNN's historical per-day rating field is mostly constant, so it is not charted. Bands: 0-24 extreme fear, 25-44 fear, 45-55 neutral, 56-74 greed, 75-100 extreme greed.",
                "蓝线：各分项原始输入在全部历史中的 0–100 分位，高值代表恐惧的分项已反向；动量先换算为相对125日均线。菱形为 CNN 官方最新分数。CNN 历史逐点评级字段长期恒定，不予采用。色带：0–24 极度恐惧，25–44 恐惧，45–55 中性，56–74 贪婪，75–100 极度贪婪。",
            )
        )
    else:
        st.caption(
            tr(
                language,
                "CNN's raw historical inputs. CNN publishes 0-100 component scores only for the latest day (shown beside each title).",
                "CNN 实际保存的原始输入。CNN 只对最新一天公布分项 0–100 分数（写在各标题旁）。",
            )
        )
    ordered = [
        component_id
        for component_id in CNN_COMPONENT_ORDER
        if component_id in set(frame["component_id"].astype(str))
    ]
    remaining = [
        component_id
        for component_id in frame["component_id"].astype(str).drop_duplicates()
        if component_id not in ordered
    ]
    latest_by_id = (
        latest_components.set_index("component_id")
        if not latest_components.empty and "component_id" in latest_components.columns
        else pd.DataFrame()
    )
    proxies_by_id: dict[str, pd.DataFrame] = {}
    if view == "percentile":
        for component_id in set(frame["component_id"].astype(str)):
            proxies_by_id[component_id] = cnn_component_proxy_percentile(full_history, component_id)
    sequence = ordered + remaining
    for start in range(0, len(sequence), 2):
        pair = sequence[start:start + 2]
        columns = st.columns(len(pair))
        for column, component_id in zip(columns, pair):
            subset = frame[frame["component_id"].astype(str).eq(component_id)].sort_values("date")
            if subset.empty:
                continue
            label_field = "label_zh" if language == "zh" else "label_en"
            title = subset.iloc[-1].get(label_field) or component_id
            unit_en, unit_zh = CNN_COMPONENT_UNITS.get(component_id, ("Raw input", "原始输入"))
            latest = latest_by_id.loc[component_id] if component_id in latest_by_id.index else None
            latest_score = pd.to_numeric(
                pd.Series([None if latest is None else latest.get("score")]),
                errors="coerce",
            ).iloc[0]
            latest_rating = _cnn_rating_label(None if latest is None else latest.get("rating"), language)
            score_bit = "" if pd.isna(latest_score) else f" · {latest_score:.0f}"
            with column:
                with st.container(border=True):
                    st.markdown(
                        f'<div class="am-chart-title">{title}</div>',
                        unsafe_allow_html=True,
                    )
                    st.caption(
                        tr(language, unit_en, unit_zh)
                        + (f"{score_bit} ({latest_rating})" if latest_rating != "—" else score_bit)
                    )
                    if view == "percentile":
                        subset_dates = pd.to_datetime(subset["date"], errors="coerce")
                        proxy = proxies_by_id.get(
                            component_id, pd.DataFrame(columns=["date", "proxy"])
                        )
                        if not proxy.empty:
                            proxy = proxy.drop_duplicates("date", keep="last")
                            window_start = subset_dates.min()
                            if not pd.isna(window_start):
                                proxy = proxy[proxy["date"] >= window_start]
                        fig = go.Figure()
                        for band_y0, band_y1, band_color, band_opacity in (
                            (0, 25, "#7f1d1d", 0.10),
                            (25, 45, "#b45309", 0.08),
                            (45, 55, "#64748b", 0.06),
                            (55, 75, "#047857", 0.08),
                            (75, 100, "#065f46", 0.10),
                        ):
                            fig.add_hrect(
                                y0=band_y0,
                                y1=band_y1,
                                fillcolor=band_color,
                                opacity=band_opacity,
                                line_width=0,
                            )
                        if len(proxy) >= 2:
                            hover_proxy = tr(language, "Proxy percentile", "分位代理")
                            hover_raw = tr(language, "Raw input", "原始输入")
                            raw_by_date = pd.DataFrame(
                                {
                                    "date": subset_dates,
                                    "raw_value": subset["raw_value"].to_numpy(),
                                }
                            ).drop_duplicates("date", keep="last")
                            merged = proxy.merge(raw_by_date, on="date", how="left")
                            fig.add_trace(
                                go.Scatter(
                                    x=merged["date"],
                                    y=merged["proxy"],
                                    mode="lines",
                                    name=title,
                                    line={"color": PALETTE[0], "width": 2},
                                    customdata=merged["raw_value"],
                                    hovertemplate=(
                                        f"<b>%{{x|%d %b %Y}}</b><br>{hover_proxy}: %{{y:.0f}}"
                                        f"<br>{hover_raw}: %{{customdata:.2f}}<extra></extra>"
                                    ),
                                    showlegend=False,
                                )
                            )
                        else:
                            st.caption(
                                tr(
                                    language,
                                    "History is too short for a percentile proxy; showing CNN's official score only.",
                                    "历史长度暂不足以计算分位代理；仅显示官方分数。",
                                )
                            )
                        latest_date = pd.to_datetime(
                            None if latest is None else latest.get("date"),
                            errors="coerce",
                        )
                        if not pd.isna(latest_score) and not pd.isna(latest_date):
                            official_label = tr(language, "CNN official score", "CNN官方分数")
                            fig.add_trace(
                                go.Scatter(
                                    x=[latest_date],
                                    y=[float(latest_score)],
                                    mode="markers",
                                    name=official_label,
                                    marker={
                                        "color": _cnn_rating_color(
                                            None if latest is None else latest.get("rating")
                                        ),
                                        "size": 11,
                                        "symbol": "diamond",
                                        "line": {"color": "#ffffff", "width": 1.5},
                                    },
                                    hovertemplate=_cnn_official_score_hovertemplate(official_label),
                                    showlegend=False,
                                )
                            )
                        fig.update_yaxes(
                            range=[0, 100],
                            title=None,
                            tickvals=[0, 25, 45, 55, 75, 100],
                        )
                        chart_theme(fig, height=310)
                        st.plotly_chart(
                            fig,
                            width="stretch",
                            config={"displaylogo": False, "responsive": True},
                        )
                    else:
                        fig = go.Figure(
                            go.Scatter(
                                x=subset["date"],
                                y=subset["raw_value"],
                                mode="lines",
                                name=title,
                                line={"color": "#94a3b8", "width": 1.6},
                                hovertemplate="<b>%{x|%d %b %Y}</b><br>%{y:.2f}<extra></extra>",
                            )
                        )
                        fig.update_yaxes(title=None)
                        chart_theme(fig, height=310)
                        apply_line_hover(
                            fig,
                            subset.rename(columns={"date": "_date", "raw_value": "_value"}),
                            "number",
                        )
                        st.plotly_chart(
                            fig,
                            width="stretch",
                            config={"displaylogo": False, "responsive": True},
                        )



def render_cot_history(artifact: dict[str, Any], language: str, window: str) -> None:
    history = _regime_history_window(frame_for_dataset(artifact, "cot_history"), window)
    label_field = "label_zh" if language == "zh" else "label_en"
    if not _regime_has_columns(history, ("date", "contract_id", label_field, "percentile")):
        return
    labels = (
        history[["contract_id", label_field]]
        .drop_duplicates("contract_id")
        .set_index("contract_id")
        .iloc[:, 0]
        .to_dict()
    )
    options = sorted(labels)
    selected = st.selectbox(
        tr(language, "Positioning contract", "持仓合约"),
        options,
        format_func=lambda value: labels.get(value, value),
        key=f"regime_cot_contract_{language}",
    )
    selected_history = history[history["contract_id"].astype(str).eq(selected)].copy()
    selected_history["percentile"] = pd.to_numeric(selected_history["percentile"], errors="coerce")
    fig = go.Figure(
        go.Scatter(
            x=selected_history["date"],
            y=selected_history["percentile"],
            mode="lines",
            name=tr(language, "Historical percentile", "历史分位"),
            line={"color": PALETTE[0], "width": 2},
        )
    )
    fig.add_hrect(y0=90, y1=100, fillcolor="#fef2f2", opacity=0.5, line_width=0)
    fig.add_hrect(y0=0, y1=10, fillcolor="#eff6ff", opacity=0.5, line_width=0)
    fig.update_yaxes(range=[0, 100], ticksuffix="%")
    chart_theme(fig, height=330)
    apply_line_hover(fig, selected_history.rename(columns={"date": "_date"}), "number")
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})


def cross_asset_return_heatmap_frame(
    returns: pd.DataFrame,
    exposure_ids: Iterable[str],
    language: str,
) -> pd.DataFrame:
    """Return a complete exposure-by-horizon grid without imputing missing returns."""
    selected = list(dict.fromkeys(str(value) for value in exposure_ids))
    columns = [
        "exposure_id",
        "exposure",
        "horizon",
        "return_pct",
        "as_of",
    ]
    if returns is None or returns.empty or "exposure_id" not in returns.columns:
        return pd.DataFrame(columns=columns)

    latest = returns.copy()
    latest["exposure_id"] = latest["exposure_id"].astype(str)
    if "date" in latest.columns:
        latest["_date"] = pd.to_datetime(latest["date"], errors="coerce")
        latest = latest.dropna(subset=["_date"])
        latest = latest.sort_values("_date", kind="mergesort")
    latest = latest.drop_duplicates("exposure_id", keep="last").set_index("exposure_id")

    rows: list[dict[str, Any]] = []
    label_index = 1 if language == "zh" else 0
    for exposure_id in selected:
        source = latest.loc[exposure_id] if exposure_id in latest.index else pd.Series(dtype=object)
        as_of = pd.to_datetime(source.get("date"), errors="coerce")
        as_of_label = as_of.strftime("%Y-%m-%d") if not pd.isna(as_of) else "—"
        exposure_label = REGIME_EXPOSURE_LABELS.get(
            exposure_id,
            (exposure_id, exposure_id),
        )[label_index]
        for field, label_en, label_zh in REGIME_RETURN_HORIZONS:
            value = pd.to_numeric(source.get(field), errors="coerce")
            rows.append(
                {
                    "exposure_id": exposure_id,
                    "exposure": exposure_label,
                    "horizon": tr(language, label_en, label_zh),
                    "return_pct": value,
                    "as_of": as_of_label,
                }
            )
    return pd.DataFrame(rows, columns=columns)


def build_cross_asset_return_heatmap_figure(
    returns: pd.DataFrame,
    exposure_ids: Iterable[str],
    language: str,
) -> go.Figure | None:
    heatmap = cross_asset_return_heatmap_frame(returns, exposure_ids, language)
    if heatmap.empty or heatmap["return_pct"].notna().sum() == 0:
        return None

    exposure_order = heatmap["exposure"].drop_duplicates().tolist()
    horizon_order = heatmap["horizon"].drop_duplicates().tolist()
    values = heatmap.pivot(index="exposure", columns="horizon", values="return_pct").reindex(
        index=exposure_order,
        columns=horizon_order,
    )
    dates = heatmap.pivot(index="exposure", columns="horizon", values="as_of").reindex(
        index=exposure_order,
        columns=horizon_order,
    )
    scale = values.abs().max().max()
    scale = max(1.0, float(scale)) if not pd.isna(scale) else 1.0
    fig = go.Figure(
        go.Heatmap(
            z=values.to_numpy(),
            x=horizon_order,
            y=exposure_order,
            customdata=dates.to_numpy(),
            zmin=-scale,
            zmax=scale,
            zmid=0,
            colorscale=[
                [0.0, "#FCA5A5"],
                [0.5, "#F8FAFC"],
                [1.0, "#93C5FD"],
            ],
            showscale=False,
            hoverongaps=False,
            xgap=3,
            ygap=3,
            hovertemplate=(
                "<b>%{y}</b><br>"
                + tr(language, "Window", "窗口")
                + ": %{x}<br>"
                + tr(language, "Return", "回报")
                + ": %{z:+.2f}%<br>"
                + tr(language, "As of", "截至")
                + ": %{customdata}<extra></extra>"
            ),
        )
    )
    for exposure in exposure_order:
        for horizon in horizon_order:
            value = values.loc[exposure, horizon]
            if pd.isna(value):
                continue
            fig.add_annotation(
                x=horizon,
                y=exposure,
                text=f"{float(value):+.1f}%",
                showarrow=False,
                font={
                    "color": "#111827",
                    "size": 12,
                },
            )
    chart_theme(fig, date_axis=False, height=max(340, 38 * len(exposure_order) + 110))
    fig.update_layout(
        margin={"l": 10, "r": 10, "t": 16, "b": 20},
        hovermode="closest",
    )
    fig.update_xaxes(side="top", showgrid=False, title=None)
    fig.update_yaxes(showgrid=False, title=None, autorange="reversed")
    return fig


def render_cross_asset_return_heatmap(
    returns: pd.DataFrame,
    exposure_ids: Iterable[str],
    language: str,
) -> None:
    fig = build_cross_asset_return_heatmap_figure(returns, exposure_ids, language)
    if fig is None:
        st.info(tr(language, "No recent cross-asset returns are available.", "暂无近期跨资产回报。"))
        return
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})


def render_cross_asset_context(artifact: dict[str, Any], language: str, window: str) -> None:
    prices = _regime_history_window(frame_for_dataset(artifact, "cross_asset_prices"), window)
    returns = frame_for_dataset(artifact, "cross_asset_returns")
    if not _regime_has_columns(prices, ("date", "exposure_id", "close")):
        st.info(tr(language, "No cross-asset history is available.", "暂无跨资产历史数据。"))
        return
    observed = list(dict.fromkeys(prices["exposure_id"].astype(str).tolist()))
    core_order = [value for value in REGIME_CROSS_ASSET_CORE if value in observed]
    sector_order = [value for value in REGIME_US_SECTOR_AUX if value in observed]
    unknown_order = [value for value in observed if value not in REGIME_CROSS_ASSET_CORE and value not in REGIME_US_SECTOR_AUX]
    available = core_order + sector_order + unknown_order
    selected = st.multiselect(
        tr(language, "Series", "显示序列"),
        available,
        default=core_order,
        format_func=lambda value: REGIME_EXPOSURE_LABELS.get(value, (value, value))[1 if language == "zh" else 0],
        key=f"regime_cross_asset_series_{language}",
    )
    st.caption(
        tr(
            language,
            "Core cross-asset indices are selected by default; US sector ETFs are optional overlays (SPY duplicates S&P 500 above).",
            "默认仅勾选核心跨资产指数；美国行业 ETF 为可选叠加（SPY 与上方标普500重复）。",
        )
    )
    if not selected:
        st.info(tr(language, "Select at least one series.", "请至少选择一个序列。"))
        return
    st.markdown(
        f"#### {tr(language, 'Cross-asset return heatmap', '跨资产回报热图')}"
    )
    st.caption(
        tr(
            language,
            "Latest close-to-close returns across 1, 5 and 20 trading sessions. Each index keeps its own observation date; missing windows remain blank.",
            "各指数最近1、5及20个交易日的收盘至收盘回报；每个指数保留自身观察日期，缺失窗口保持空白。",
        )
    )
    render_cross_asset_return_heatmap(returns, selected, language)

    st.markdown(
        f"#### {tr(language, 'Rebased performance history', '净值化历史走势')}"
    )
    st.caption(
        tr(
            language,
            "Selected indices are rebased to 100 at the beginning of the chosen display window.",
            "所选指数在当前显示窗口起点统一重设为100。",
        )
    )
    rebased = rebase_price_history(prices, exposure_ids=selected)
    fig = go.Figure()
    for index, exposure_id in enumerate(selected):
        subset = rebased[rebased["exposure_id"].astype(str).eq(exposure_id)]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset["date"],
                y=subset["rebased"],
                mode="lines",
                name=REGIME_EXPOSURE_LABELS.get(exposure_id, (exposure_id, exposure_id))[1 if language == "zh" else 0],
                line={"color": PALETTE[index % len(PALETTE)], "width": 2},
            )
        )
    chart_theme(fig, height=430)
    apply_line_hover(fig, rebased.rename(columns={"date": "_date"}), "number")
    fig.update_yaxes(title=tr(language, "Rebased to 100", "起点重设为100"))
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})
    return_columns = (
        "exposure_id",
        "date",
        "return_1d_pct",
        "return_5d_pct",
        "return_20d_pct",
        "return_60d_pct",
    )
    if _regime_has_columns(returns, return_columns):
        table = returns[returns["exposure_id"].astype(str).isin(selected)].copy()
        table["Exposure"] = table["exposure_id"].map(
            lambda value: REGIME_EXPOSURE_LABELS.get(str(value), (str(value), str(value)))[1 if language == "zh" else 0]
        )
        table["date"] = pd.to_datetime(table["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        table = table[
            [
                "Exposure",
                "date",
                "return_1d_pct",
                "return_5d_pct",
                "return_20d_pct",
                "return_60d_pct",
            ]
        ]
        table = table.rename(
            columns={
                "Exposure": tr(language, "Exposure", "指数"),
                "date": tr(language, "As of", "截至日期"),
                "return_1d_pct": tr(language, "1-session return %", "1个交易日回报%"),
                "return_5d_pct": tr(language, "5-session return %", "5个交易日回报%"),
                "return_20d_pct": tr(language, "20-session return %", "20个交易日回报%"),
                "return_60d_pct": tr(language, "60-session return %", "60个交易日回报%"),
            }
        )
        st.dataframe(table, hide_index=True, width="stretch")


def _signed_pct(value: Any) -> str:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        return "—"
    return f"{number:+.2f}%"


def render_macro_commodity_table(artifact: dict[str, Any], language: str) -> None:
    frame = frame_for_dataset(artifact, "macro_commodity_returns")
    required = ("asset_id", "close", "return_1d_pct", "return_1w_pct", "return_1m_pct", "return_3m_pct", "return_ytd_pct")
    if not _regime_has_columns(frame, required):
        st.info(tr(language, "Commodity proxies are not in this artifact yet.", "这个数据快照还没有商品代理价格。"))
        return
    show = frame.copy()
    label_field = "label_zh" if language == "zh" else "label_en"
    show["Asset"] = show.get(label_field, show["asset_id"])
    table = pd.DataFrame(
        {
            tr(language, "Asset", "资产"): show["Asset"],
            tr(language, "Price", "价格"): pd.to_numeric(show["close"], errors="coerce").map(lambda value: "—" if pd.isna(value) else f"{value:,.2f}"),
            tr(language, "1D", "1日"): show["return_1d_pct"].map(_signed_pct),
            tr(language, "1W", "1周"): show["return_1w_pct"].map(_signed_pct),
            tr(language, "1M", "1月"): show["return_1m_pct"].map(_signed_pct),
            tr(language, "3M", "3月"): show["return_3m_pct"].map(_signed_pct),
            tr(language, "YTD", "年初至今"): show["return_ytd_pct"].map(_signed_pct),
        }
    )
    st.caption(
        tr(
            language,
            "Front-month futures and the URA ETF via Yahoo Finance. These are not LBMA/EIA spot prints. WTI here is the futures proxy, not the FRED EIA spot used by the oil threshold.",
            "Yahoo Finance 的近月期货和 URA ETF。这些不是 LBMA／EIA 现货。这里的 WTI 是期货代理，不是油价门槛使用的 FRED EIA 现货。",
        )
    )
    st.dataframe(table, hide_index=True, width="stretch")


def render_inflation_heatmap(artifact: dict[str, Any], language: str) -> None:
    frame = frame_for_dataset(artifact, "inflation_release_panel")
    required = ("indicator_id", "period", "value", "unit")
    if not _regime_has_columns(frame, required):
        st.info(tr(language, "Inflation prints are not in this artifact yet.", "这个数据快照还没有通胀月报。"))
        return
    show = frame.copy()
    show["value"] = pd.to_numeric(show["value"], errors="coerce")
    show = show.dropna(subset=["period", "value"])
    if show.empty:
        st.info(tr(language, "Inflation prints are not in this artifact yet.", "这个数据快照还没有通胀月报。"))
        return
    label_field = "label_zh" if language == "zh" else "label_en"
    show["Metric"] = show.get(label_field, show["indicator_id"])
    periods = sorted(show["period"].astype(str).unique())[-12:]
    order = list(dict.fromkeys(show["indicator_id"].astype(str).tolist()))
    labels = (
        show.drop_duplicates("indicator_id").set_index("indicator_id")["Metric"].to_dict()
    )
    units = (
        show.drop_duplicates("indicator_id").set_index("indicator_id")["unit"].to_dict()
    )
    pivot = (
        show[show["period"].astype(str).isin(periods)]
        .pivot_table(index="indicator_id", columns="period", values="value", aggfunc="last")
        .reindex(order)
        .reindex(columns=periods)
    )
    z = pivot.to_numpy(dtype=float)
    text_values = [
        ["" if pd.isna(value) else f"{value:.2f}" for value in row]
        for row in z
    ]
    y_labels = [
        f"{labels.get(idx, idx)}  {units.get(idx, '')}".strip()
        for idx in pivot.index.astype(str)
    ]
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=list(pivot.columns),
            y=y_labels,
            colorscale=[
                [0.0, "#1d4ed8"],
                [0.5, "#e5e7eb"],
                [1.0, "#b91c1c"],
            ],
            zmid=2.5,
            text=text_values,
            texttemplate="%{text}",
            hovertemplate="<b>%{y}</b><br>%{x}: %{z:.2f}<extra></extra>",
            colorbar={"title": "%"},
        )
    )
    fig.update_yaxes(autorange="reversed")
    chart_theme(fig, height=max(320, 70 * len(y_labels)))
    st.caption(
        tr(
            language,
            "Last 12 monthly releases. Headline and core PCE are year-over-year percent changes of the price index; trimmed-mean series are used as published; income and spending are month-over-month percent changes of the dollar level.",
            "最近12次月度发布。PCE物价与核心PCE为价格指数同比；截尾均值使用原始公布值；收入和支出为美元水平的环比。",
        )
    )
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})
