"""China macro exploration: artifact reads only, never live fetch on navigation."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .artifacts import load_auxiliary_artifact
from .config import HISTORY_WINDOWS, PALETTE
from .core import chart_theme, frame_for_dataset, tr

TITLES_ZH = {
    "PMI": "官方 PMI：制造业、服务业与建筑业",
    "PMI details": "制造业 PMI：生产、订单与库存",
    "Orders / inventory": "新订单与产成品库存差",
    "Production / consumption": "生产与消费：月度同比",
    "Production / consumption spread": "工业与零售同比差",
    "GDP (YTD)": "GDP：季度累计同比",
    "Consumer / producer prices": "消费与生产端通胀",
    "CPI MoM": "CPI：月度环比",
    "Industrial profits (YTD)": "规上工业利润：累计同比",
    "Money growth (new M1 definition)": "货币供应同比：M1 新口径与 M2",
    "M1 / M2 spread": "M1 − M2 同比差（可比口径）",
    "Legacy M1 (not comparable)": "M1 旧口径历史（不与新口径拼接）",
    "Financing flows": "社会融资与新增人民币贷款",
    "Financing stock growth": "社融存量同比",
    "Borrower balances": "住户与企业贷款余额",
    "Borrower balance changes": "住户与企业贷款余额月度变化（非官方新增贷款）",
    "Property (YTD)": "房地产：销售、投资与建设累计同比",
    "Investment (YTD)": "固定资产投资：累计同比",
    "Trade growth": "出口与进口：美元口径同比",
    "Trade growth: 3-month averages": "进出口同比：3个月均值",
    "Trade balance": "贸易差额",
    "Trade value": "进出口金额",
    "Money-market rates": "货币市场利率",
    "Loan prime rates": "贷款市场报价利率（LPR）",
    "Government yields": "中国国债收益率",
    "Yield curve": "中国国债期限利差：10年 − 1年",
    "RMB fixing": "人民币汇率：美元兑人民币中间价",
}
UNITS_ZH = {"CNY bn": "十亿元人民币", "USD bn": "十亿美元", "pp": "百分点", "bp": "基点", "index": "指数点", "CNY/USD": "人民币／美元", "%": "%"}
STATUSES_ZH = {"Available": "可用", "Stale": "过期／发布延迟", "Retained": "本轮未取得，保留历史", "Unavailable": "尚未取得", "Historical": "历史归档（旧口径）"}
NOTES = {
    "activity": ("PMI 50 separates expansion from contraction. January/February activity is commonly a combined release. GDP is year-to-date, not standalone quarterly growth. Differences are descriptive, not trading forecasts.", "PMI 的50线区分扩张与收缩；工业和零售的1–2月常合并发布，缺月不填0。GDP为累计同比，并非单季增速。差值是描述性观察，不是交易预测。"),
    "inflation": ("CPI/core CPI/PPI are published YoY rates; industrial profits are cumulative YTD. The heatmap shows published observations, not simulated prices.", "CPI／核心CPI／PPI是官方同比；工业利润为年内累计同比。热图展示原始公布值，不是模拟价格。"),
    "credit": ("M1 changed definition in January 2025; official comparable 2024 history is separate from legacy M1. AFRE excluding government bonds is not a private-sector-credit proxy. RMB bank lending and AFRE RMB lending have different coverage.", "M1自2025年1月更改定义，使用官方2024年可比回溯值；旧口径单独显示。社融扣除政府债券不等于私人部门信贷。银行新增贷款与社融口径人民币贷款覆盖不同。"),
    "property": ("These are cumulative YTD growth rates, not individual-month growth. January is not published separately. The 2026 infrastructure definition includes utilities and is shown separately from the legacy ex-utilities series. Missing months are not interpolated.", "这些是年内累计同比，不是当月同比；1月不单独发布，不能相减累计增速来还原单月增速。2026年基建含公用事业，与旧的不含电力口径分开显示。缺月不做插值。"),
    "trade": ("Trade uses USD values. The 3-month lines are arithmetic averages of published monthly YoY rates. No missing months are bridged.", "贸易使用美元口径；3个月线为已公布单月同比的算术均值，缺月不会跳过计算。"),
    "rates": ("FX is the official central parity, not an executable spot close. Weekly/monthly rates use the mean; FX uses the last available fixing. DR007 is not FDR007. No substitutes are mislabeled.", "汇率为官方中间价，并非可交易现货收盘价。周／月视图：利率取均值，汇率取最后一次中间价。DR007不等于FDR007，不用其他指标冒充。"),
}


def _history(frame, window):
    if frame.empty:
        return frame
    years = HISTORY_WINDOWS.get(window, 10)
    if years is None:
        return frame
    cutoff = pd.Timestamp(frame["date"].max()) - pd.DateOffset(years=years)
    return frame[frame["date"] >= cutoff]


def render_chart(frame, series, ids, title, key, language, window, frequency="daily"):
    with st.container(border=True):
        st.markdown(f"#### {TITLES_ZH.get(title, title) if language == 'zh' else title}")
        chosen = st.multiselect(tr(language, "Visible series", "显示序列"), ids, default=ids,
                                format_func=lambda metric: series[metric][language], key="china_series_" + key)
        shown = _history(frame[frame["metric"].isin(chosen)], window)
        if shown.empty:
            st.info(tr(language, "No observations available for the selected series. See coverage below.", "所选序列尚无可用数据；缺失原因见下方覆盖表。"))
            return
        missing = [series[metric][language] for metric in chosen if metric not in shown["metric"].unique()]
        if missing:
            st.caption(tr(language, "Not available: ", "尚未取得：") + "、".join(missing))
        unit = series[shown.iloc[0]["metric"]]["unit"]
        unit_label = UNITS_ZH.get(unit, unit) if language == "zh" else unit
        st.caption(f"{shown['date'].min():%Y-%m} – {shown['date'].max():%Y-%m} · {unit_label}")
        figure = go.Figure()
        for index, metric in enumerate(chosen):
            metric_rows = shown[shown["metric"].eq(metric)].sort_values("date").set_index("date")
            history = metric_rows["value"]
            if history.empty:
                continue
            # Insert explicit gaps in monthly series. No diagonal bridging of Jan/Feb gaps.
            if series[metric]["frequency"] == "M" and series[metric]["scope"] != "day":
                history = history.reindex(pd.date_range(history.index.min(), history.index.max(), freq="MS"))
            elif frequency != "daily" and series[metric]["frequency"] == "D":
                resample = history.resample("W-MON" if frequency == "weekly" else "MS", closed="left", label="left")
                history = resample.last() if metric == "usdcny_fix" else resample.mean()
            label = series[metric][language]
            scopes = metric_rows["scope"].reindex(history.index)
            scope_labels = {"month": tr(language, "Individual month", "当月"),
                            "jan_feb": tr(language, "January–February combined", "1–2月合并"),
                            "ytd": tr(language, "Year-to-date", "年内累计"), "day": tr(language, "Daily observation", "当日观察")}
            periods = scopes.map(scope_labels).fillna(tr(language, "No observation", "无观察值"))
            if series[metric]["frequency"] == "D" and frequency != "daily":
                periods[:] = (tr(language, "Last fixing in period", "期内最后一次中间价") if metric == "usdcny_fix"
                              else tr(language, "Mean rate in period", "期内利率均值"))
            if series[metric]["frequency"] == "M" and series[metric]["scope"] != "day":
                exempt = metric in {"industrial_yoy", "retail", "retail_yoy", "production_consumption"} or series[metric]["scope"] == "ytd"
                january = history.index.month == 1
                january &= history.index.year >= 2012
                if exempt and january.any():
                    st.caption(label + " · " + tr(language, "January is not published separately; February covers January–February. Gaps are not zero.", "1月不单独发布；2月代表1–2月合并期。留白不代表0。"))
                gaps = history.isna()
                if exempt:
                    gaps &= ~january
                if gaps.any():
                    st.caption(label + " · " + tr(language, "Uncollected reference months: ", "尚未取得的观察月：") + ", ".join(history.index[gaps].strftime("%Y-%m")))
            figure.add_trace(go.Scatter(x=history.index, y=history.values, name=label, mode="lines", connectgaps=False,
                                       customdata=periods.to_numpy(),
                                       line={"color": PALETTE[index % len(PALETTE)]},
                                       hovertemplate="%{y:.2f} " + unit_label + "<br>%{customdata}<extra>" + label + "</extra>"))
        if title.startswith("PMI"):
            figure.add_hline(y=50, line_dash="dot", line_color="#94a3b8")
        elif unit in ["%", "pp", "bp", "USD bn"]:
            figure.add_hline(y=0, line_dash="dot", line_color="#94a3b8")
        chart_theme(figure, height=420)
        figure.update_xaxes(tickformat="%Y-%m", title=None)
        figure.update_yaxes(title=unit_label)
        figure.update_layout(margin={"b": 110}, legend={"y": -.28}, hovermode="x unified")
        st.plotly_chart(figure, width="stretch", key="china_chart_" + key)


def inflation_heatmap(frame, series, language):
    ids = ["cpi_yoy", "core_cpi_yoy", "ppi_yoy"]
    selected = frame[frame["metric"].isin(ids)]
    if selected.empty:
        return
    end = selected["date"].max().to_period("M")
    months = pd.period_range(end - 11, end, freq="M").to_timestamp()
    values = selected.pivot(index="metric", columns="date", values="value").reindex(index=ids, columns=months)
    st.markdown("#### " + tr(language, "Inflation — last 12 reference months", "通胀：最近12个观察月份"))
    figure = go.Figure(go.Heatmap(z=values.to_numpy(), x=[date.strftime("%Y-%m") for date in months],
                                y=[series[metric][language] for metric in ids], zmid=0, colorscale="RdBu_r",
                                text=values.round(1).astype(object).where(values.notna(), "").to_numpy(), texttemplate="%{text}",
                                hovertemplate="%{y}<br>%{x}: %{z:.1f}%<extra></extra>", colorbar={"title": "%"}))
    figure.update_layout(height=280, margin={"t": 15, "b": 65}, template="plotly_white")
    st.plotly_chart(figure, width="stretch", key="china_inflation_heatmap")


def render_china_macro(language, window):
    artifact, _, errors = load_auxiliary_artifact("china-macro", language, title_en="China Macro", title_zh="中国宏观经济")
    for error in errors:
        st.warning(error)
    frame = frame_for_dataset(artifact, "observations")
    series = artifact.get("series", {})
    if frame.empty or not series:
        st.info(tr(language, "China macro snapshot is not available yet.", "中国宏观数据快照尚未接入。"))
        return
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["unit"] = frame["metric"].map(lambda metric: series[metric]["unit"])
    urls = artifact.get("source_urls", [])
    frame["source_url"] = frame["source_ref"].map(lambda value: urls[int(value)] if pd.notna(value) and 0 <= int(value) < len(urls) else "")
    frame = frame.dropna(subset=["date", "value"])
    st.subheader(tr(language, "China macro research", "中国宏观经济研究"))
    st.caption(tr(language, "Local source snapshot; observation dates vary by release. No live fetch when switching tabs.", "来源本地快照，各指标保留各自观察日期；切换页面不会实时抓取。"))
    st.caption(tr(language, "This independent China snapshot does not enter the US/global risk scoring or alerts shown above.", "本节中国宏观使用独立快照，不参与上方美国／全球模块的风险评分与预警。"))
    health = frame_for_dataset(artifact, "source_health")
    if not health.empty:
        affected = health[health["status"].isin(["Unavailable", "Retained", "Stale"])]
        if not affected.empty:
            st.warning(tr(language, f"{len(affected)} series are missing, retained or delayed. Check their dates and the coverage table; retained history is not a new fetch.", f"{len(affected)} 个序列缺失、本轮未取得或发布延迟；请核对各自日期及覆盖表，保留历史不代表本轮采集成功。"))
    st.caption(tr(language, "Snapshot built: ", "快照构建：") + str(artifact.get("snapshot", {}).get("generatedAt", "—")))
    columns = st.columns(4)
    for column, metric in zip(columns, ["pmi", "cpi_yoy", "m2_yoy", "exports_yoy"]):
        history = frame[frame["metric"].eq(metric)].sort_values("date")
        with column:
            with st.container(border=True):
                st.markdown("**" + series[metric][language] + "**")
                st.subheader((f"{history.iloc[-1]['value']:.1f}" + ("%" if series[metric]["unit"] == "%" else "")) if not history.empty else "—")
                st.caption(history.iloc[-1]["date"].strftime("%Y-%m") if not history.empty else tr(language, "Unavailable", "尚未取得"))
    groups = artifact["groups"]
    tabs = st.tabs([group[1] if language == "zh" else group[2] for group in groups])
    for tab, (group_id, _, _, charts) in zip(tabs, groups):
        with tab:
            st.caption(NOTES[group_id][1 if language == "zh" else 0])
            frequency = "daily"
            if group_id == "rates":
                frequency = st.radio(tr(language, "Frequency", "数据粒度"), ["daily", "weekly", "monthly"],
                                     format_func=lambda value: {"daily": "日度", "weekly": "周度", "monthly": "月度"}[value] if language == "zh" else value.title(),
                                     horizontal=True, key="china_rates_frequency")
            if group_id == "inflation":
                inflation_heatmap(frame, series, language)
            for index, (title, ids) in enumerate(charts):
                render_chart(frame, series, ids, title, f"{group_id}_{index}", language, window, frequency)
            with st.expander(tr(language, "Data table & definitions", "数据表与指标口径")):
                ids = [metric for _, metrics in charts for metric in metrics]
                table = frame[frame["metric"].isin(ids)].copy()
                table["metric"] = table["metric"].map(lambda metric: series[metric][language])
                table["unit"] = table["unit"].map(lambda value: UNITS_ZH.get(value, value) if language == "zh" else value)
                scope_labels = {"month": "当月", "jan_feb": "1–2月合并", "ytd": "年内累计", "day": "当日"}
                if language == "zh":
                    table["scope"] = table["scope"].map(scope_labels)
                table = table[["metric", "date", "value", "unit", "scope", "source_url"]].sort_values("date", ascending=False)
                st.dataframe(table.rename(columns={"metric": tr(language, "Metric", "指标"), "date": tr(language, "Reference date", "观察日期"), "value": tr(language, "Value", "数值"), "unit": tr(language, "Unit", "单位"), "scope": tr(language, "Period scope", "周期口径"), "source_url": tr(language, "Source", "来源链接")}), hide_index=True, width="stretch")
    st.subheader(tr(language, "Source health & coverage", "来源健康与覆盖范围"))
    st.caption(tr(language, "Capture time is not a release time. Missing or stale inputs remain visible; no fabricated values.", "采集时间不是发布日期；缺失及过期输入保留在表内，不造数、不用构建日期充当数据日期。"))
    if not health.empty:
        gaps = health[health["missing_reference_months"].map(bool)] if "missing_reference_months" in health else pd.DataFrame()
        if not gaps.empty:
            st.caption(tr(language, f"{len(gaps)} series have internal historical gaps (unpublished January excluded).", f"{len(gaps)} 个序列仍有历史缺口（已排除官方不单独发布的1月）。"))
            with st.expander(tr(language, "Historical coverage gaps", "历史缺口明细")):
                st.dataframe(gaps[["name_zh" if language == "zh" else "name_en", "missing_reference_months"]], hide_index=True, width="stretch")
        show = health.reindex(columns=["name_zh" if language == "zh" else "name_en", "status", "earliest_observation", "latest_observation", "expected_reference", "retrieved_at", "records", "source_url"]).copy()
        if language == "zh":
            show["status"] = show["status"].map(STATUSES_ZH)
        show.columns = [tr(language, en, zh) for en, zh in [("Metric", "指标"), ("Status", "状态"), ("History starts", "历史起点"), ("Latest observation", "最新观察"), ("Expected by release calendar", "按日程应有观察月"), ("Last fetched (UTC)", "上次采集（UTC）"), ("Observations", "观察数"), ("Source URL", "来源链接")]]
        st.dataframe(show, hide_index=True, width="stretch")
    with st.expander(tr(language, "Pipeline run & fetch results", "管道运行与采集结果")):
        st.caption(f"Run: {artifact.get('run_id', '—')}")
        st.dataframe(frame_for_dataset(artifact, "fetch_results"), hide_index=True, width="stretch")
        warnings = frame_for_dataset(artifact, "fetch_warnings")
        if not warnings.empty:
            st.warning(tr(language, f"{len(warnings)} individual source requests failed; successful requests were retained. Group success does not guarantee complete historical coverage.", f"{len(warnings)} 次单独来源请求失败，已保留成功请求的数据；采集组成功不代表历史覆盖完整。"))
            st.dataframe(warnings, hide_index=True, width="stretch")
