"""Commercial aerospace sector page.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from .config import AEROSPACE_ATTENTION_PAGE_LABELS, AEROSPACE_ATTENTION_PAGE_LABELS_ZH, AEROSPACE_OBJECT_TYPE_LABELS, AEROSPACE_OBJECT_TYPE_LABELS_ZH, AEROSPACE_PROGRAM_LABELS, AEROSPACE_PROGRAM_LABELS_ZH, CRYPTO_ATTENTION_AGENT_LABELS, CRYPTO_ATTENTION_AGENT_LABELS_ZH

from .core import frame_for_dataset, render_bar_chart, render_header, render_line_chart, render_table, section_heading, tr

from .explorer import render_source_coverage


def render_aerospace(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    """Render the bounded V1 commercial-aerospace research page."""
    render_header(
        artifact,
        labels,
        language,
        "aerospace",
        title_override=tr(language, "Commercial Aerospace Monitor", "商业航天监测"),
        description_override=tr(
            language,
            "Verified China launch activity, constellation inventory, catalogued space objects and aerospace attention signals.",
            "已核验的中国发射活动、商业星座库存、已编目空间物体及航天关注度信号。",
        ),
    )

    section_heading(
        language,
        "China launch pulse",
        "中国发射脉搏",
        "The primary series separates national-program, state-owned commercial and commercial-provider launches; the commercial-only dataset remains available in Data Explorer.",
        "主序列分开显示国家队项目、国企商业化和商业发射服务商；仅商业发射数据仍保留在数据探索器。",
    )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "china_launch_monthly_chart",
            language,
            window,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=430,
            series_label_map=AEROSPACE_PROGRAM_LABELS_ZH if language == "zh" else AEROSPACE_PROGRAM_LABELS,
        )

    section_heading(
        language,
        "Verified mission detail",
        "已核验任务明细",
        "Latest 30 official-baseline events are shown here; the complete canonical history remains in the artifact and Data Explorer.",
        "此处显示最新 30 条官方基准任务；完整规范化历史保留在 artifact 和数据探索器。",
    )
    with st.container(border=True):
        render_table(artifact, labels, "china_launch_events_table", language, max_rows=30)

    section_heading(
        language,
        "Constellation inventory & object catalog",
        "星座库存与空间物体目录",
        "Constellation counts are tracked/catalogued inventory, not guaranteed operational satellites. SATCAT is a separate global launch-month catalog.",
        "星座数量是追踪／编目库存，不保证等同于正在运行的卫星；SATCAT 是独立的全球发射月份目录。",
    )
    with st.container(border=True):
        render_bar_chart(artifact, labels, "satellite_count_chart", language, height=360)

    satellite_history = frame_for_dataset(artifact, "satellite_history")
    snapshot_count = satellite_history["as_of"].nunique() if "as_of" in satellite_history.columns else 0
    if snapshot_count >= 8:
        with st.container(border=True):
            render_line_chart(
                artifact,
                labels,
                "satellite_history_chart",
                language,
                window,
                views=("Level", "WoW %"),
                periods_per_year=1,
                height=400,
                series_label_map=(
                    {"Qianfan": "千帆", "Jilin1": "吉林一号", "Guowang": "国网"}
                    if language == "zh"
                    else {"Qianfan": "Qianfan", "Jilin1": "Jilin-1", "Guowang": "Guowang"}
                ),
            )
    else:
        st.info(
            tr(
                language,
                f"Inventory history is withheld until 8 distinct snapshots are available; current coverage is {snapshot_count}.",
                f"库存历史图将在累计 8 个独立快照后显示；当前有 {snapshot_count} 个。",
            )
        )

    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "global_object_catalog_monthly_chart",
            language,
            window,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=430,
            series_label_map=(
                AEROSPACE_OBJECT_TYPE_LABELS_ZH
                if language == "zh"
                else AEROSPACE_OBJECT_TYPE_LABELS
            ),
        )

    section_heading(
        language,
        "Aerospace attention",
        "航天关注度",
        "Wikipedia pageviews are an attention proxy, not launch activity, search volume or unique people.",
        "Wikipedia 页面访问量是关注度代理，不是发射活动、搜索量或独立人数。",
    )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "wikipedia_attention_agent_weekly_chart",
            language,
            window,
            views=("Level", "WoW %", "YoY %"),
            periods_per_year=52,
            height=430,
            series_label_map=(
                CRYPTO_ATTENTION_AGENT_LABELS_ZH
                if language == "zh"
                else CRYPTO_ATTENTION_AGENT_LABELS
            ),
        )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "wikipedia_user_attention_monthly_chart",
            language,
            window,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=430,
            series_label_map=(
                AEROSPACE_ATTENTION_PAGE_LABELS_ZH
                if language == "zh"
                else AEROSPACE_ATTENTION_PAGE_LABELS
            ),
        )

    with st.expander(tr(language, "Annual benchmark context", "年度 benchmark 背景"), expanded=False):
        st.caption(
            tr(
                language,
                "The annual World/China/United States objects-launched series counts objects or payloads, not rocket launches; it is context rather than a high-frequency signal.",
                "年度全球／中国／美国进入太空物体序列统计物体或有效载荷，不是火箭发射次数；这里只作为背景，不是高频信号。",
            )
        )
        render_line_chart(
            artifact,
            labels,
            "global_space_benchmark_chart",
            language,
            "Full history",
            views=("Level",),
            periods_per_year=1,
            height=380,
        )

    render_source_coverage({"aerospace": artifact}, {"aerospace": labels}, language)
