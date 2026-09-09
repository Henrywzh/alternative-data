"""ETF monitor: US sector ETFs and southbound flow views.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from .config import HISTORY_WINDOWS, PALETTE

from .core import tr


def render_us_sector_tab(language: str) -> None:
    """Render US 11 GICS Sectors and pure-play sub-industries from R2 / remote artifact."""
    # ``streamlit run`` puts this script's directory on sys.path; AppTest and
    # any other import path do not, so the tab raised ModuleNotFoundError
    # everywhere except a live server. Resolve the sibling module explicitly.
    app_dir = str(Path(__file__).resolve().parents[1])
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    from remote_us_etf import load_us_sector_artifact


    artifact = load_us_sector_artifact()
    sectors = artifact.get("sectors", [])
    sub_map = artifact.get("sub_industries", {})
    as_of = artifact.get("as_of", "—")

    if not sectors:
        message = artifact.get("freshness_message")
        if artifact.get("freshness_status") == "Stale":
            st.warning(
                tr(
                    language,
                    "US sector data is stale; no old snapshot is displayed.",
                    "美股行业数据已过期；页面不会显示旧快照。",
                )
            )
        else:
            st.info(tr(language, "US sector data is updating or unavailable.", "美股行业数据正在更新或暂不可用。"))
        if message and language != "zh":
            st.caption(str(message))
        return

    coverage = artifact.get("coverage") or {}
    source = artifact.get("source", "r2")
    source_label = {
        "r2": tr(language, "R2", "R2 云端"),
        "local_cache": tr(language, "local cache", "本地缓存"),
        "live": tr(language, "generated live", "本次会话现算"),
    }.get(source, source)
    age = artifact.get("cache_age_hours")
    if age is not None:
        source_label += tr(language, f", {age:.0f}h old", f"，{age:.0f} 小时前")
    st.caption(
        tr(
            language,
            f"Data as of {as_of} · 11 GICS Level-1 Sectors + Pure-play Sub-industries · source: {source_label}",
            f"数据截至 {as_of} · 11大GICS核心行业板块 + 高纯度细分主题 · 数据来源：{source_label}",
        )
    )

    # Partial coverage is stated, not hidden: four sectors must not read as
    # though four were all there is.
    missing = coverage.get("sectors_missing") or []
    if missing:
        st.warning(
            tr(
                language,
                f"{coverage.get('sectors_delivered', len(sectors))} of "
                f"{coverage.get('sectors_expected', 11)} sectors available; "
                f"missing: {', '.join(missing)}",
                f"仅取到 {coverage.get('sectors_delivered', len(sectors))}/"
                f"{coverage.get('sectors_expected', 11)} 个板块，"
                f"缺失：{'、'.join(missing)}",
            )
        )
    excluded = [t for t in (coverage.get("rebase_excluded") or []) if t not in missing]
    if excluded:
        st.caption(
            tr(
                language,
                f"Excluded from the relative-performance chart (short history): {', '.join(excluded)}",
                f"未纳入相对表现图（历史长度不足，无法与其他序列共用基准日）：{'、'.join(excluded)}",
            )
        )

    # 1. 11大板块相对表现折线图 (60D rebased)
    plot_rows = []
    for s in sectors:
        sp = s.get("sparkline_60d", [])
        sec_name = s.get("name_zh" if language == "zh" else "name_en", s["ticker"])
        lbl = f"{s['ticker']} {sec_name}"
        # A series without a rebased track does not share the common base date
        # and must not be drawn on the same axis as those that do.
        for pt in sp:
            plot_rows.append({"date": pd.to_datetime(pt["d"]), "rebased": pt["rebased"], "series": lbl})

    if plot_rows:
        df_plot = pd.DataFrame(plot_rows)
        fig = px.line(
            df_plot,
            x="date",
            y="rebased",
            color="series",
            color_discrete_sequence=PALETTE,
            render_mode="svg",
        )
        fig.add_hline(y=100.0, line_dash="dot", line_color="#9CA3AF", line_width=1)
        base_date = coverage.get("rebase_base_date")
        fig.update_yaxes(
            title=tr(
                language,
                f"Rebased to 100 at {base_date}" if base_date else "Rebased level",
                f"归一走势（{base_date} = 100）" if base_date else "归一走势 (基准100)",
            )
        )
        fig.update_xaxes(title=None, tickformat="%b %d")
        fig.update_layout(
            legend=dict(
                title="",
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0,
                font=dict(size=10),
            ),
            margin=dict(l=10, r=10, t=30, b=10),
            hovermode="x unified",
        )
        st.plotly_chart(
            fig,
            width="stretch",
            config={"displaylogo": False, "responsive": True},
            key="us_sector_relative_performance_chart",
        )

    # 2. 11大核心板块技术面表格
    st.markdown(
        f'<div class="am-chart-title">{tr(language, "US 11 GICS Sector Heatmap & Metrics", "美股 11 大行业板块技术面看板")}</div>',
        unsafe_allow_html=True,
    )

    sec_df = pd.DataFrame(sectors)
    sec_df["_label_show"] = sec_df.apply(
        lambda r: f"{r['ticker']} {r.get('name_zh' if language == 'zh' else 'name_en')}", axis=1
    )
    sec_df["_ret_20d"] = sec_df["ret_20d_pct"].apply(lambda v: f"{v:+.2f}%" if pd.notna(v) else "—")
    sec_df["_ret_60d"] = sec_df["ret_60d_pct"].apply(lambda v: f"{v:+.2f}%" if pd.notna(v) else "—")
    sec_df["_ma20"] = sec_df["ma20_pct"].apply(lambda v: f"{v:+.2f}%" if pd.notna(v) else "—")
    sec_df["_dd60"] = sec_df["drawdown_60d"].apply(lambda v: f"{v:.2f}%" if pd.notna(v) else "—")

    def _rsi_label(v):
        if pd.isna(v) or v is None: return "—"
        val = float(v)
        if val >= 70: return f"{val:.1f} (超买过热)" if language == "zh" else f"{val:.1f} (Overbought)"
        if val <= 35: return f"{val:.1f} (超卖低估)" if language == "zh" else f"{val:.1f} (Oversold)"
        return f"{val:.1f} (中性健康)" if language == "zh" else f"{val:.1f} (Neutral)"

    sec_df["_rsi_show"] = sec_df["rsi"].apply(_rsi_label)

    col_map_us = {
        "_label_show": "板块代码与名称" if language == "zh" else "Sector Ticker & Name",
        "_ret_20d": "近20日收益" if language == "zh" else "20D Return",
        "_ret_60d": "近60日收益" if language == "zh" else "60D Return",
        "_ma20": "相对20日均线" if language == "zh" else "vs MA20",
        "_rsi_show": "RSI情绪状态" if language == "zh" else "RSI Status",
        "_dd60": "60日最大回撤" if language == "zh" else "60D Drawdown",
        "expense_ratio_str": "费率" if language == "zh" else "Expense",
    }

    st.dataframe(
        sec_df[[c for c in col_map_us.keys() if c in sec_df.columns]].rename(columns=col_map_us),
        hide_index=True,
        width="stretch",
    )

    # 3. 细分子行业与主题下钻 (Pure-play Sub-industries)
    if sub_map:
        st.markdown(
            f'<div class="am-chart-title" style="margin-top:20px;">{tr(language, "🔍 Pure-Play Sub-Industry & Thematic ETFs", "🔍 专属细分子行业与主题 ETF 下钻")}</div>',
            unsafe_allow_html=True,
        )
        sec_names = list(sub_map.keys())
        parent_labels = {
            str(item.get("sector")): str(item.get("sector_zh") or item.get("sector"))
            for item in sectors
            if item.get("sector")
        }
        selected_parent = st.selectbox(
            tr(language, "Select Parent Sector", "选择所属大类行业"),
            sec_names,
            key="us_etf_parent_select",
            format_func=lambda sector: (
                parent_labels.get(sector, sector) if language == "zh" else sector
            ),
        )

        subs = sub_map.get(selected_parent, [])
        if subs:
            sub_df = pd.DataFrame(subs)
            sub_df["_sub_show"] = sub_df.apply(
                lambda r: f"{r['ticker']} {r.get('name_zh' if language == 'zh' else 'name_en')}", axis=1
            )
            theme_col = "sub_industry_zh" if language == "zh" else "sub_industry"
            sub_df["_theme_show"] = sub_df[theme_col] if theme_col in sub_df.columns else "—"
            sub_df["_ret_20d"] = sub_df["ret_20d_pct"].apply(lambda v: f"{v:+.2f}%" if pd.notna(v) else "—")
            sub_df["_ret_60d"] = sub_df["ret_60d_pct"].apply(lambda v: f"{v:+.2f}%" if pd.notna(v) else "—")
            sub_df["_ma20"] = sub_df["ma20_pct"].apply(lambda v: f"{v:+.2f}%" if pd.notna(v) else "—")
            sub_df["_rsi_show"] = sub_df["rsi"].apply(_rsi_label)

            col_map_sub = {
                "_sub_show": "细分ETF标的" if language == "zh" else "Sub ETF",
                "_theme_show": "所属细分赛道" if language == "zh" else "Sub-Industry",
                "_ret_20d": "20日收益" if language == "zh" else "20D Ret",
                "_ret_60d": "60日收益" if language == "zh" else "60D Ret",
                "_ma20": "相对20日线" if language == "zh" else "vs MA20",
                "_rsi_show": "RSI情绪" if language == "zh" else "RSI",
                "expense_ratio_str": "管理费率" if language == "zh" else "Expense",
            }
            st.dataframe(
                sub_df[[c for c in col_map_sub.keys() if c in sub_df.columns]].rename(columns=col_map_sub),
                hide_index=True,
                width="stretch",
            )



def render_southbound_market_flow(frame: pd.DataFrame, language: str, window: str) -> None:
    if frame is None or frame.empty:
        st.info(tr(language, "Aggregate southbound Stock Connect history is not in this artifact yet.", "当前快照尚未包含全市场南向资金历史。"))
        return
    plot = frame.copy()
    date_col = "trade_date" if "trade_date" in plot.columns else "date"
    if date_col not in plot.columns:
        st.info(
            tr(
                language,
                "Southbound history has no usable date column.",
                "南向资金历史缺少可用的日期列。",
            )
        )
        return
    plot[date_col] = pd.to_datetime(plot[date_col], errors="coerce")
    plot = plot.dropna(subset=[date_col]).sort_values(date_col)
    years = HISTORY_WINDOWS.get(window)
    if years:
        cutoff = plot[date_col].max() - pd.DateOffset(years=years)
        plot = plot[plot[date_col] >= cutoff]
    if plot.empty:
        st.info(
            tr(
                language,
                "No southbound observations are available in this window.",
                "该时间范围内没有可用的南向资金观察值。",
            )
        )
        return
    latest = plot.iloc[-1]
    net = pd.to_numeric(pd.Series([latest.get("net_buy_yi")]), errors="coerce").iloc[0]
    mv = pd.to_numeric(pd.Series([latest.get("holding_market_value")]), errors="coerce").iloc[0]
    bal = pd.to_numeric(pd.Series([latest.get("balance_yi")]), errors="coerce").iloc[0]
    asof = pd.Timestamp(latest[date_col]).strftime("%Y-%m-%d")
    c1, c2, c3 = st.columns(3)
    c1.metric(
        tr(language, "Latest net buy", "最新净买入"),
        f"{float(net):,.1f} 亿" if pd.notna(net) else "—",
    )
    # Passing the observation date as ``delta`` makes Streamlit add an
    # up/down arrow based on whether the date string parses as positive. That
    # produced a green up-arrow next to a negative net buy in the dashboard.
    # A date is metadata, not a directional change, so render it as a caption.
    c1.caption(f"{tr(language, 'Observation date', '观察日')}：{asof}")
    c2.metric(tr(language, "Holding market value", "持股市值"), f"HK$ {float(mv)/1e12:,.2f}T" if pd.notna(mv) else "—")
    c3.metric(
        tr(language, "Same-day balance", "当日余额"),
        f"{float(bal):,.1f} 亿" if pd.notna(bal) else tr(language, "Unavailable", "不可用"),
    )

    net_series = (
        pd.to_numeric(plot["net_buy_yi"], errors="coerce")
        if "net_buy_yi" in plot.columns
        else pd.Series(pd.NA, index=plot.index, dtype="float64")
    )
    holding_series = (
        pd.to_numeric(plot["holding_market_value"], errors="coerce")
        if "holding_market_value" in plot.columns
        else pd.Series(pd.NA, index=plot.index, dtype="float64")
    )
    # Missing source values stay missing. A null net-buy row must not become a
    # visually meaningful zero-height bar, which would imply that the source
    # actually reported no flow on that date.
    bar_colors = [
        "#1d4ed8" if pd.notna(value) and value >= 0
        else "#dc2626" if pd.notna(value)
        else "#cbd5e1"
        for value in net_series
    ]
    net_ma20 = net_series.rolling(20, min_periods=5).mean()

    if pd.isna(net) or pd.isna(mv) or mv <= 0:
        st.warning(
            tr(
                language,
                f"The latest source row ({asof}) is incomplete; missing values are left blank and are not filled from an older session.",
                f"最新来源记录（{asof}）不完整；缺失值会保留为空，不会用较早交易日的数据填补。",
            )
        )

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    net_label = tr(language, "Daily net buy", "当日净买入")
    holding_label = tr(language, "Holding market value", "持股市值")
    fig.add_trace(
        go.Bar(
            x=plot[date_col],
            y=net_series,
            name=tr(language, "Daily net buy (CNY 100m)", "当日净买入（亿元）"),
            marker=dict(color=bar_colors, line=dict(width=0)),
            hovertemplate=f"<b>%{{x|%Y-%m-%d}}</b><br>{net_label}: %{{y:,.1f}} {tr(language, 'CNY 100m', '亿元')}<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=plot[date_col],
            y=net_ma20,
            name=tr(language, "20D MA flow (CNY 100m)", "净买入20日均线（亿元）"),
            mode="lines",
            line=dict(width=1.8, color="#f59e0b", dash="solid"),
            hovertemplate=f"<b>%{{x|%Y-%m-%d}}</b><br>{tr(language, '20D MA flow', '20日均线净买入')}: %{{y:,.1f}} {tr(language, 'CNY 100m', '亿元')}<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=plot[date_col],
            y=holding_series / 1e12,
            name=tr(language, "Holding MV (HK$ tn)", "累计持股市值（万亿港元）"),
            mode="lines",
            line=dict(width=2.5, color="#0f172a"),
            hovertemplate=f"<b>%{{x|%Y-%m-%d}}</b><br>{holding_label}: HK$ %{{y:,.2f}} {tr(language, 'tn', '万亿')}<extra></extra>",
        ),
        secondary_y=True,
    )
    fig.update_layout(
        template="plotly_white",
        height=380,
        bargap=0.0,
        bargroupgap=0.0,
        legend=dict(orientation="h", y=-0.22, x=0),
        margin=dict(l=0, r=8, t=12, b=45),
        hovermode="x unified",
    )
    fig.update_xaxes(tickformat="%b %Y", showgrid=False)
    fig.update_yaxes(title_text=tr(language, "Net buy (CNY 100m)", "净买入（亿元）"), secondary_y=False, gridcolor="#F3F4F6", zeroline=True, zerolinecolor="#94A3B8")
    fig.update_yaxes(title_text=tr(language, "Holding MV (HK$ tn)", "持股市值（万亿港元）"), secondary_y=True, showgrid=False)
    st.plotly_chart(
        fig,
        width="stretch",
        config={"displaylogo": False, "responsive": True},
        key="market_southbound_flow_chart",
    )
    st.caption(tr(
        language,
        "Market-wide southbound Stock Connect from Eastmoney/akshare stock_hsgt_hist_em. This is not per-stock 0700.HK ownership.",
        "全市场南向资金来自东财/akshare stock_hsgt_hist_em，不是 0700.HK 个股持股。",
    ))


# Canonical index-style categories for the "By Index" filter pills.
#
# config.py records styles as free text -- "Tech / Growth", "Growth" and
# "Tech / Semis" are three spellings of one idea -- and the pills used the raw
# strings as their identity while translating them to the same Chinese label,
# so the row showed 科技成长 and 红利价值 twice. Collapsing to these keys is
# what makes each pill appear once.
#
# The order here is the order the pills render in. Deriving it from the data
# instead made the row reshuffle between sections of the same page, because it
# followed whichever exposure happened to come first.
STYLE_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("broad", "Broad Benchmark", "宽基大盘"),
    ("tech_growth", "Tech & Growth", "科技成长"),
    ("value_dividend", "Dividend / Value", "红利价值"),
    ("sector", "Sector / Thematic", "行业主题"),
)

STYLE_CATEGORY_LABELS: dict[str, tuple[str, str]] = {
    key: (label_en, label_zh) for key, label_en, label_zh in STYLE_CATEGORIES
}


# The vocabulary config.py actually uses, most specific first. Keeping it here
# rather than inline is what lets a test tell the difference between "this
# style maps to broad" and "this style matched nothing and defaulted to broad".
_STYLE_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("Dividend", "Value"), "value_dividend"),
    (("Tech", "Growth", "Semis"), "tech_growth"),
    (("Sector", "Thematic"), "sector"),
    (("Broad", "Core"), "broad"),
)

STYLE_FALLBACK_KEY = "broad"
