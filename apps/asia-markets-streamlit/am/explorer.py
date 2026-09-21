"""Data explorer and source-coverage pages.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from .config import SECTORS, SOURCE_DATASETS

from .core import add_date_column, frame_for_dataset, latest_row, localized_source_health_frame, section_heading, tr


def render_source_coverage(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    language: str,
) -> None:
    section_heading(language, "Source & coverage", "来源与覆盖范围", "Build-time lineage and observation dates stay visible.", "保留构建时来源链路和观察日期。")
    rows: list[dict[str, Any]] = []
    source_links: list[tuple[str, str, str]] = []
    for sector_key, artifact in artifacts.items():
        label_artifact = labels.get(sector_key, artifact)
        sector_config = SECTORS.get(sector_key)
        if sector_config is not None:
            sector_name = sector_config["name_en"] if language == "en" else sector_config["name_zh"]
        else:
            sector_name = str(label_artifact.get("manifest", {}).get("title") or sector_key)
        health = localized_source_health_frame(
            artifact,
            label_artifact,
            language,
        )
        if not health.empty:
            health.insert(0, tr(language, "Sector", "板块"), sector_name)
            rows.extend(health.to_dict("records"))
        else:
            # Population/migration has an authoritative source manifest but
            # does not yet publish a normalized source_health dataset. Build
            # the same visible coverage contract from those sources and the
            # actual snapshot datasets instead of rendering an empty panel.
            for source in label_artifact.get("sources", []):
                source_id = source.get("id", "")
                dataset_id = SOURCE_DATASETS.get(source_id, "")
                source_frame = frame_for_dataset(artifact, dataset_id) if dataset_id else pd.DataFrame()
                latest = latest_row(source_frame)
                latest_field = next(
                    (field for field in ["date", "observation_date", "month", "period", "quarter", "academic_year"] if field in latest),
                    None,
                )
                source_description = source.get("query", {}).get("description", "")
                rows.append(
                    {
                        tr(language, "Sector", "板块"): sector_name,
                        "source": source.get("label", source_id),
                        "dataset": dataset_id or "—",
                        "type": tr(language, "Measure", "指标"),
                        "status": tr(language, "Ready", "可用"),
                        "latest_observation": str(latest.get(latest_field, "—")) if latest_field else "—",
                        "records": len(source_frame),
                        "freshness": tr(language, "Artifact snapshot", "数据快照"),
                        "notes": source_description,
                    }
                )
        # FactSet is an optional supplemental lane attached to the regime
        # artifact rather than the core global-regime source_health table. It
        # still belongs on the generic health page so its article coverage and
        # sparse core-field fill are visible without pretending it is a core
        # threshold input.
        factset_health = frame_for_dataset(artifact, "factset_earnings_health")
        if not factset_health.empty:
            for factset_row in factset_health.to_dict("records"):
                core_fill = pd.to_numeric(
                    pd.Series([factset_row.get("core_fill_rate_last_24")]), errors="coerce"
                ).iloc[0]
                supported_fill = pd.to_numeric(
                    pd.Series([factset_row.get("supported_fill_rate_last_24")]), errors="coerce"
                ).iloc[0]
                fill_text = (
                    tr(language, "core", "核心")
                    + f" {float(core_fill) * 100:.0f}% / "
                    + tr(language, "supported", "支持字段")
                    + f" {float(supported_fill) * 100:.0f}%"
                    if pd.notna(core_fill) and pd.notna(supported_fill)
                    else "—"
                )
                factset_status = str(factset_row.get("status", "Unavailable"))
                factset_status = {
                    "Healthy": tr(language, "Healthy", "健康"),
                    "Partial": tr(language, "Partial", "部分可用"),
                    "Unavailable": tr(language, "Unavailable", "不可用"),
                }.get(factset_status, factset_status)
                rows.append(
                    {
                        tr(language, "Sector", "板块"): sector_name,
                        "source": tr(language, "FactSet Earnings Insight", "FactSet Earnings Insight 盈利洞察"),
                        "series_id": factset_row.get("series_id", "factset_earnings_regime"),
                        "dataset": "factset_article_catalog",
                        "type": tr(language, "Supplemental", "补充数据"),
                        "status": factset_status,
                        "latest_observation": factset_row.get("latest_supported_observation")
                        or factset_row.get("latest_observation")
                        or "—",
                        "records": factset_row.get("article_records") or factset_row.get("records", 0),
                        "freshness": fill_text,
                        "notes": factset_row.get("notes", ""),
                    }
                )
        for source in label_artifact.get("sources", []):
            source_links.append((sector_name, source.get("label", source.get("id", "")), source.get("href", "")))
    if rows:
        health_frame = pd.DataFrame(rows)
        if language == "zh":
            health_frame = health_frame.rename(
                columns={
                    "source": "来源",
                    "series_id": "序列编号",
                    "dataset": "数据集",
                    "type": "类型",
                    "status": "状态",
                    "latest_observation": "最新观察日",
                    "records": "记录数",
                    "freshness": "新鲜度",
                    "notes": "说明",
                }
            )
        st.dataframe(health_frame, hide_index=True, width="stretch")
    with st.expander(tr(language, "Source links", "来源链接")):
        for sector_name, label, href in source_links:
            if href:
                st.markdown(f"- **{sector_name}** · [{label}]({href})")
            else:
                st.markdown(f"- **{sector_name}** · {label}")


def combined_dataset_index(artifacts: dict[str, dict[str, Any]], language: str) -> list[tuple[str, str, str]]:
    options: list[tuple[str, str, str]] = []
    for sector_key, artifact in artifacts.items():
        sector_config = SECTORS.get(sector_key)
        if sector_config is not None:
            sector_name = sector_config["name_en"] if language == "en" else sector_config["name_zh"]
        else:
            sector_name = str(artifact.get("manifest", {}).get("title") or sector_key)
        datasets = artifact.get("snapshot", {}).get("datasets", {})
        if not isinstance(datasets, dict):
            continue
        for dataset_id, rows in datasets.items():
            if not isinstance(rows, list):
                continue
            options.append((f"{sector_key}:{dataset_id}", f"{sector_name} · {dataset_id} · {len(rows):,} rows", sector_key))
    return options


def render_data_explorer(artifacts: dict[str, dict[str, Any]], language: str) -> None:
    st.markdown(f'<div class="am-page-title">{tr(language, "Data Explorer", "数据探索器")}</div>', unsafe_allow_html=True)
    st.caption(tr(language, "Inspect the actual rows behind the connected sectors.", "查看目前已接入板块的实际数据行。"))
    options = combined_dataset_index(artifacts, language)
    if not options:
        st.info(tr(language, "No datasets are available.", "目前没有可用数据集。"))
        return
    labels = [label for _, label, _ in options]
    selected_label = st.selectbox(tr(language, "Dataset", "数据集"), labels)
    selected_id, _, sector_key = next(item for item in options if item[1] == selected_label)
    dataset_id = selected_id.split(":", 1)[1]
    frame = frame_for_dataset(artifacts[sector_key], dataset_id)
    st.markdown(
        f'<div class="am-meta">{escape(tr(language, "Read-only local snapshot", "只读本地数据快照"))} · '
        f'{len(frame):,} rows · {escape(dataset_id)}</div>',
        unsafe_allow_html=True,
    )
    if frame.empty:
        st.info(tr(language, "This dataset is empty.", "这个数据集为空。"))
        return
    date_field = next((field for field in ["date", "observation_date", "month", "period", "quarter", "academic_year"] if field in frame.columns), None)
    if date_field:
        ordered = add_date_column(frame, date_field)
        if not ordered.empty:
            st.caption(f"{tr(language, 'Coverage', '覆盖范围')}: {ordered['_date'].min():%d %b %Y} – {ordered['_date'].max():%d %b %Y}")
    st.dataframe(frame, hide_index=True, width="stretch")
