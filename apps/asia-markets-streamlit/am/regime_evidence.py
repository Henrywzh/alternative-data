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

from .core import apply_line_hover, chart_theme, frame_for_dataset, render_line_chart, tr

from .regime_labels import REGIME_EXPOSURE_LABELS, REGIME_INDICATOR_LABELS, REGIME_RETURN_HORIZONS, REGIME_SERIES_LABELS, REGIME_SERIES_LABELS_ZH

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
    available = list(dict.fromkeys(prices["exposure_id"].astype(str).tolist()))
    selected = st.multiselect(
        tr(language, "Series", "显示序列"),
        available,
        default=available,
        format_func=lambda value: REGIME_EXPOSURE_LABELS.get(value, (value, value))[1 if language == "zh" else 0],
        key=f"regime_cross_asset_series_{language}",
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
