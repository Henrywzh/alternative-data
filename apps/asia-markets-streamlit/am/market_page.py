"""ETF monitor: scoped index sections and page assembly.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from .config import SECTORS

from .core import section_heading, tr

from .market import _format_observed_premium, _market_etf_activity_frame, _market_etf_price_frame, _market_exposure_label_map, _market_label, _market_pair_history_frame, _market_premium_history_frame, _market_price_frame, render_market_index_detail, render_market_leadership_chart, render_market_ratio_chart, render_relative_regime

from .market_us import STYLE_CATEGORIES, STYLE_CATEGORY_LABELS, STYLE_FALLBACK_KEY, _STYLE_RULES, render_southbound_market_flow, render_us_sector_tab


def index_style_key(raw_style: str) -> str | None:
    """The category for a config ``style``, or None if nothing matched."""
    s = str(raw_style or "").strip()
    for needles, key in _STYLE_RULES:
        if any(needle in s for needle in needles):
            return key
    return None


def normalize_index_style(raw_style: str) -> str:
    """Map a config ``style`` string onto one of STYLE_CATEGORIES' keys.

    Rendering must not fail on an unknown style, so this falls back to
    "broad". That fallback is a guess, and used to be indistinguishable from a
    real match -- a new style such as "Commodity" would have rendered under
    宽基大盘 with nothing to notice. test_every_config_style_maps_explicitly
    fails instead, so the rule gets added here deliberately.
    """
    return index_style_key(raw_style) or STYLE_FALLBACK_KEY


def render_scoped_index_section(
    scoped_eids: set[str],
    label_by_exposure: dict[str, str],
    prices: pd.DataFrame,
    technicals: pd.DataFrame,
    wrappers: pd.DataFrame,
    language: str,
    window: str,
    etf_prices: pd.DataFrame | None = None,
    premium_history: pd.DataFrame | None = None,
    fund_activity: pd.DataFrame | None = None,
    key_prefix: str = "market",
    show_wrappers: bool = True,
    show_premium: bool | None = None,
) -> None:
    """Render single-index technical detail and ETF wrappers with dynamic sub-category filtering."""
    from market_monitor.config import EXPOSURES, market_tab_exposure_order

    if show_premium is None:
        show_premium = show_wrappers

    scoped_ids = {str(exposure_id) for exposure_id in scoped_eids}
    price_exposures = (
        set(prices["exposure_id"].astype(str))
        if prices is not None
        and not prices.empty
        and "exposure_id" in prices.columns
        else set()
    )
    try:
        preferred_order = market_tab_exposure_order(key_prefix)
    except KeyError:
        preferred_order = tuple(
            str(spec.get("exposure_id"))
            for spec in EXPOSURES
            if spec.get("exposure_id")
        )
    ordered_price_ids = scoped_ids & price_exposures
    available = [exposure_id for exposure_id in preferred_order if exposure_id in ordered_price_ids]
    available.extend(sorted(ordered_price_ids - set(available)))
    if not available:
        if (
            wrappers is not None
            and not wrappers.empty
            and show_wrappers
            and "exposure_id" in wrappers.columns
        ):
            wrapper_ids = {
                str(exposure_id)
                for exposure_id in wrappers["exposure_id"].dropna().astype(str).unique()
            }
            ordered_wrapper_ids = scoped_ids & wrapper_ids
            available = [
                exposure_id
                for exposure_id in preferred_order
                if exposure_id in ordered_wrapper_ids
            ]
            available.extend(sorted(ordered_wrapper_ids - set(available)))
    if not available:
        return

    section_heading(
        language,
        "By Index",
        "按指数查看",
        "Inspect price, 20D/60D trend, and RSI for a selected index.",
        "选择一个指数，查看其收盘价、均线趋势及 RSI 技术指标。",
    )

    # 构建元数据映射 (style / risk_character)
    meta_by_eid = {e["exposure_id"]: e for e in EXPOSURES}

    # 建立当前可用标的的分类映射
    members_by_key: dict[str, list[str]] = {}
    for eid in available:
        spec = meta_by_eid.get(eid, {})
        members_by_key.setdefault(normalize_index_style(spec.get("style", "Broad")), []).append(eid)
    # Iterate STYLE_CATEGORIES, not the data, so the pill row is stable.
    style_groups: dict[str, tuple[str, str, list[str]]] = {
        key: (STYLE_CATEGORY_LABELS[key][0], STYLE_CATEGORY_LABELS[key][1], members_by_key[key])
        for key, _en, _zh in STYLE_CATEGORIES
        if key in members_by_key
    }

    filtered_available = available
    if len(available) > 4 and len(style_groups) > 1:
        # 当标的大于4个且分类多样时，生成无重复的胶囊按钮
        cat_keys = ["all"] + list(style_groups.keys())
        cat_labels = [tr(language, "All Types", "全部类型")] + [
            tr(language, style_groups[k][0], style_groups[k][1]) for k in style_groups
        ]
        label_to_key = dict(zip(cat_labels, cat_keys))

        if hasattr(st, "segmented_control"):
            choice_label = st.segmented_control(
                tr(language, "Filter Type", "指数类型筛选"),
                cat_labels,
                default=cat_labels[0],
                key=f"{key_prefix}_index_filter_pills",
                label_visibility="collapsed",
            ) or cat_labels[0]
        elif hasattr(st, "pills"):
            choice_label = st.pills(
                tr(language, "Filter Type", "指数类型筛选"),
                cat_labels,
                default=cat_labels[0],
                key=f"{key_prefix}_index_filter_pills",
                label_visibility="collapsed",
            ) or cat_labels[0]
        else:
            choice_label = cat_labels[0]

        selected_key = label_to_key.get(choice_label, "all")
        if selected_key != "all":
            filtered_available = style_groups[selected_key][2]
            if not filtered_available:
                filtered_available = available

    wrapper_counts = (
        wrappers.groupby("exposure_id").size().to_dict()
        if wrappers is not None
        and not wrappers.empty
        and show_wrappers
        and "exposure_id" in wrappers.columns
        else {}
    )

    def _fmt_name(e):
        lbl = label_by_exposure.get(e, e)
        if show_wrappers and wrapper_counts.get(e, 0) > 0:
            return f"{lbl} ({wrapper_counts[e]} 只场内ETF)" if language == "zh" else f"{lbl} ({wrapper_counts[e]} ETF)"
        return lbl

    selected = st.selectbox(
        tr(language, "Select Index", "选择指数标的"),
        filtered_available,
        key=f"{key_prefix}_index_select",
        format_func=_fmt_name,
    )

    with st.expander(tr(language, "Indicator settings", "指标参数"), expanded=False):
        setting_columns = st.columns(4)
        rsi_window = setting_columns[0].number_input(
            tr(language, "RSI period", "RSI 周期"),
            min_value=2, max_value=100, value=14, step=1, key=f"{key_prefix}_rsi_window",
        )
        ma_window = setting_columns[1].number_input(
            tr(language, "MA period", "均线周期"),
            min_value=2, max_value=250, value=20, step=1, key=f"{key_prefix}_ma_window",
        )
        rsi_upper = setting_columns[2].number_input(
            tr(language, "Overbought", "超买线"),
            min_value=50.0, max_value=95.0, value=70.0, step=1.0, key=f"{key_prefix}_rsi_upper",
        )
        rsi_lower = setting_columns[3].number_input(
            tr(language, "Oversold", "超卖线"),
            min_value=5.0, max_value=50.0, value=30.0, step=1.0, key=f"{key_prefix}_rsi_lower",
        )

    scoped_wrappers = wrappers if show_wrappers else pd.DataFrame()
    render_market_index_detail(
        selected,
        label_by_exposure.get(selected, selected),
        prices,
        technicals,
        scoped_wrappers,
        language,
        window,
        etf_prices=etf_prices if show_wrappers else None,
        premium_history=premium_history if show_wrappers else None,
        fund_activity=fund_activity if show_wrappers else None,
        rsi_window=rsi_window,
        ma_window=ma_window,
        rsi_upper=rsi_upper,
        rsi_lower=rsi_lower,
        key_prefix=key_prefix,
        show_premium=show_premium,
    )


def render_market(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    """Index & ETF Allocation Monitor with one isolated regional view."""
    from market_monitor.config import market_tab_exposures

    st.markdown(f'<div class="am-page-title">{tr(language, SECTORS["market"]["name_en"], SECTORS["market"]["name_zh"])}</div>', unsafe_allow_html=True)
    st.caption(tr(language, "Global Multi-Asset & ETF Monitor. Regional segmentation with clean data separation.", "全球多资产与 ETF 监控看板。按地域严格分层，无跨区干扰。"))

    datasets = artifact.get("snapshot", {}).get("datasets", {})

    technicals = pd.DataFrame(datasets.get("exposure_technicals", []))
    regime = datasets.get("relative_regime", [])
    wrappers = pd.DataFrame(datasets.get("wrapper_metrics", []))
    prices = _market_price_frame(datasets)
    etf_prices = _market_etf_price_frame(datasets)
    premium_history = _market_premium_history_frame(datasets)
    fund_activity = _market_etf_activity_frame(datasets)
    pair_summary = pd.DataFrame(datasets.get("relative_pairs", []))
    pair_history = _market_pair_history_frame(datasets)
    southbound = pd.DataFrame(datasets.get("southbound_market_flow", []))

    regime_available = isinstance(regime, list) and bool(regime)
    if technicals.empty and not regime_available and wrappers.empty:
        st.info(tr(language, "This chart is not available in the current artifact snapshot.", "当前数据快照未包含此图表。"))
        return

    # Bilingual label map. Prefer the central exposure registry over a
    # snapshot-provided label: it is the stable presentation contract and it
    # keeps a rebuilt English artifact from leaking English names into the
    # Chinese page when a localized label was omitted upstream.
    label_by_exposure = _market_exposure_label_map(language)
    if not technicals.empty and "exposure_id" in technicals.columns:
        for _, row in technicals.iterrows():
            eid = str(row["exposure_id"])
            label_by_exposure.setdefault(eid, _market_label(row, language) or eid)

    # Tab membership lives in market_monitor.config.MARKET_TABS; it was also
    # written out in the artifact builder, and the two had drifted.  Keep one
    # selected region in state instead of using st.tabs: Streamlit evaluates
    # every tab body, so hidden regions still created charts, widgets and the
    # live US-sector fallback on every run.
    china_eids = market_tab_exposures("china")
    china_core_eids = market_tab_exposures("china_core")
    us_broad_eids = market_tab_exposures("us")
    apac_eids = market_tab_exposures("apac")
    emea_eids = market_tab_exposures("emea")
    global_eids = market_tab_exposures("global")

    region_keys = ("china", "us", "apac", "emea", "global")
    region_labels = {
        "china": tr(language, "🇨🇳 China & HK", "🇨🇳 泛中国 (A股/港股/出海QDII)"),
        "us": tr(language, "🇺🇸 United States", "🇺🇸 美国市场 (大盘基准/11大行业)"),
        "apac": tr(language, "🌏 APAC ex-CN/HK", "🌏 亚太除中港 (日经/韩国/台湾)"),
        "emea": tr(language, "🌍 EMEA", "🌍 欧洲与中东 (英/德/法/沙特)"),
        "global": tr(language, "🌐 Global & All", "🌐 全球大类基准 / 全部"),
    }
    if hasattr(st, "segmented_control"):
        selected_region = st.segmented_control(
            tr(language, "Market region", "市场区域"),
            region_keys,
            default=region_keys[0],
            key="market_region",
            format_func=lambda key: region_labels.get(key, key),
            label_visibility="collapsed",
        ) or region_keys[0]
    elif hasattr(st, "pills"):
        selected_region = st.pills(
            tr(language, "Market region", "市场区域"),
            region_keys,
            default=region_keys[0],
            key="market_region",
            format_func=lambda key: region_labels.get(key, key),
            label_visibility="collapsed",
        ) or region_keys[0]
    else:
        selected_region = st.radio(
            tr(language, "Market region", "市场区域"),
            region_keys,
            horizontal=True,
            key="market_region",
            format_func=lambda key: region_labels.get(key, key),
        ) or region_keys[0]

    def _render_leadership_block(
        sub_prices,
        sub_tech,
        sub_labels,
        tab_key,
        *,
        show_premium: bool = False,
    ):
        view_options = [tr(language, "All (rebased)", "全部（归一）"), tr(language, "Ratio (A/B)", "比值 (A/B)")]
        if hasattr(st, "segmented_control"):
            view_mode = st.segmented_control(
                tr(language, "View", "视图"),
                view_options,
                default=view_options[0],
                key=f"market_leadership_mode_{tab_key}",
                label_visibility="collapsed",
            ) or view_options[0]
        else:
            view_mode = st.radio(
                tr(language, "View", "视图"),
                view_options,
                horizontal=True,
                key=f"market_leadership_mode_{tab_key}",
            )

        if not sub_prices.empty:
            if view_mode == tr(language, "Ratio (A/B)", "比值 (A/B)"):
                render_market_ratio_chart(sub_prices, sub_tech, language, window, key_prefix=f"market_{tab_key}")
            else:
                render_market_leadership_chart(
                    sub_prices,
                    sub_labels,
                    language,
                    window,
                    key_prefix=f"market_{tab_key}",
                )

        if not sub_tech.empty:
            display_tech = sub_tech.copy()
            if language == "zh" and "label_zh" in display_tech.columns:
                display_tech["_label_display"] = display_tech["label_zh"]
            else:
                display_tech["_label_display"] = display_tech.get("label", display_tech.get("exposure_id"))

            def _rsi_desc(v):
                if pd.isna(v): return "—"
                val = float(v)
                if val >= 70: return f"{val:.1f} (超买过热)" if language == "zh" else f"{val:.1f} (Overbought)"
                if val <= 35: return f"{val:.1f} (超卖低估)" if language == "zh" else f"{val:.1f} (Oversold)"
                return f"{val:.1f} (中性健康)" if language == "zh" else f"{val:.1f} (Neutral)"

            display_tech["_rsi_display"] = display_tech["rsi"].apply(_rsi_desc) if "rsi" in display_tech.columns else "—"
            display_tech["_ma20_display"] = display_tech["ma20_pct"].apply(
                lambda v: f"{float(v):+.2f}%" if pd.notna(v) else "—"
            ) if "ma20_pct" in display_tech.columns else "—"
            display_tech["_dd_display"] = display_tech["drawdown_60d"].apply(
                lambda v: f"{float(v):.2f}%" if pd.notna(v) else "—"
            ) if "drawdown_60d" in display_tech.columns else "—"
            if show_premium:
                display_tech["_prem_display"] = display_tech.apply(
                    lambda row: _format_observed_premium(
                        row.get("avg_premium_30d"),
                        row.get("avg_premium_days"),
                        language,
                    ),
                    axis=1,
                )

            col_map_zh = {
                "_label_display": "指数标的",
                "_ma20_display": "相对20日线",
                "_rsi_display": "RSI情绪状态",
                "_dd_display": "60日最大回撤",
                "_prem_display": "挂钩ETF平均溢价（实际观测）",
            }
            col_map_en = {
                "_label_display": "Index",
                "_ma20_display": "vs MA20",
                "_rsi_display": "RSI Status",
                "_dd_display": "60D Drawdown",
                "_prem_display": "Avg wrapper premium (observed days)",
            }
            mapping = col_map_zh if language == "zh" else col_map_en
            final_cols = [c for c in mapping.keys() if c in display_tech.columns]
            table_to_show = display_tech[final_cols].rename(columns=mapping).sort_values(mapping["_label_display"])
            st.dataframe(table_to_show, hide_index=True, width="stretch")

    def _region_frames(exposure_ids: set[str]):
        sub_prices = (
            prices[prices["exposure_id"].astype(str).isin(exposure_ids)].copy()
            if prices is not None
            and not prices.empty
            and "exposure_id" in prices.columns
            else pd.DataFrame()
        )
        sub_tech = (
            technicals[technicals["exposure_id"].astype(str).isin(exposure_ids)].copy()
            if technicals is not None
            and not technicals.empty
            and "exposure_id" in technicals.columns
            else pd.DataFrame()
        )
        sub_labels = {key: value for key, value in label_by_exposure.items() if key in exposure_ids}
        return sub_prices, sub_tech, sub_labels

    def _pairs_for_regions(region_names: set[str]) -> pd.DataFrame:
        """Filter optional pair data without assuming a complete artifact schema."""
        if pair_summary.empty or "region" not in pair_summary.columns:
            return pd.DataFrame()
        return pair_summary[
            pair_summary["region"].astype(str).isin(region_names)
        ].copy()

    # ==================== 1. 🇨🇳 泛中国 (A股 / 港股 / QDII出海工具) ====================
    if selected_region == "china":
        sub_cn_prices, sub_cn_tech, sub_cn_labels = _region_frames(china_core_eids)
        _render_leadership_block(
            sub_cn_prices,
            sub_cn_tech,
            sub_cn_labels,
            "china",
            show_premium=True,
        )

        # 港股通南向资金
        if not southbound.empty:
            st.markdown(
                f'<div class="am-chart-title" style="margin-top:24px;">{tr(language, "Southbound Stock Connect Flow", "港股通南向资金全市场流向")}</div>',
                unsafe_allow_html=True,
            )
            render_southbound_market_flow(southbound, language, window)

        # A股与港股风格轮动配对 (Relative Regime)
        cn_pairs = _pairs_for_regions({"China", "HK"})
        if not cn_pairs.empty:
            section_heading(
                language,
                "China & HK Relative Regime",
                "A股与港股相对风格轮动",
                "Style pair spreads and rolling 20D/1Y z-score.",
                "风格轮动价差及滚动 z-score。",
            )
            render_relative_regime(cn_pairs, pair_history, language, window, key_prefix="china")

        # 场内可投资 ETF 包装（含国内宽基、港股通与QDII出海工具）
        render_scoped_index_section(
            china_eids,
            label_by_exposure,
            prices,
            technicals,
            wrappers,
            language,
            window,
            etf_prices=etf_prices,
            premium_history=premium_history,
            fund_activity=fund_activity,
            key_prefix="china",
            show_wrappers=True,
        )

    # ==================== 2. 🇺🇸 美国市场 (实际指数 + 11大行业与纯度细分) ====================
    elif selected_region == "us":
        sub_us_prices, sub_us_tech, sub_us_labels = _region_frames(us_broad_eids)
        _render_leadership_block(sub_us_prices, sub_us_tech, sub_us_labels, "us")

        # 11大行业板块热力与细分赛道下钻
        render_us_sector_tab(language)

        # 美股实际指数单指数详情 (不混杂国内QDII折溢价)
        render_scoped_index_section(
            us_broad_eids,
            label_by_exposure,
            prices,
            technicals,
            wrappers,
            language,
            window,
            key_prefix="us",
            show_wrappers=False,
        )

    # ==================== 3. 🌏 亚太除中港 (日经 / 韩国 / 台湾) ====================
    elif selected_region == "apac":
        sub_apac_prices, sub_apac_tech, sub_apac_labels = _region_frames(apac_eids)
        _render_leadership_block(sub_apac_prices, sub_apac_tech, sub_apac_labels, "apac")

        # 亚太主要市场单指数详情
        render_scoped_index_section(
            apac_eids,
            label_by_exposure,
            prices,
            technicals,
            wrappers,
            language,
            window,
            key_prefix="apac",
            show_wrappers=False,
        )

    # ==================== 4. 🌍 欧洲与中东 (英国 / 德国 / 法国 / 沙特) ====================
    elif selected_region == "emea":
        sub_emea_prices, sub_emea_tech, sub_emea_labels = _region_frames(emea_eids)
        _render_leadership_block(sub_emea_prices, sub_emea_tech, sub_emea_labels, "emea")

        # 欧洲与中东单指数详情
        render_scoped_index_section(
            emea_eids,
            label_by_exposure,
            prices,
            technicals,
            wrappers,
            language,
            window,
            key_prefix="emea",
            show_wrappers=False,
        )

    # ==================== 5. 🌐 全球大类基准 / 全部 ====================
    elif selected_region == "global":
        sub_glob_prices, sub_glob_tech, sub_glob_labels = _region_frames(global_eids)
        _render_leadership_block(sub_glob_prices, sub_glob_tech, sub_glob_labels, "global")

        # 全球宏观跨市场相对强弱 (如 China vs US)
        cross_pairs = _pairs_for_regions({"Cross", "US"})
        if not cross_pairs.empty:
            section_heading(
                language,
                "Cross-Market Relative Regime",
                "全球宏观跨市场比值",
                "Cross-market pair spreads and rolling 20D/1Y z-score.",
                "跨市场资产比值及滚动 z-score。",
            )
            render_relative_regime(cross_pairs, pair_history, language, window, key_prefix="global")

        # 全球只看实际指数；QDII wrapper premiums remain in China & HK.
        render_scoped_index_section(
            global_eids,
            label_by_exposure,
            prices,
            technicals,
            wrappers,
            language,
            window,
            etf_prices=etf_prices,
            premium_history=premium_history,
            key_prefix="global",
            show_wrappers=False,
            show_premium=False,
        )
