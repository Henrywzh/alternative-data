"""Asia Markets private Streamlit research terminal — V1.

V1 connects the reviewed Hong Kong labour, population, transport, commercial
aerospace and global crypto-context sectors.
The app reads existing, source-backed artifacts as a compact local data
contract; it does not fetch during navigation or duplicate the source
pipelines.
"""

from __future__ import annotations

import json
import re
from html import escape
import sys
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = REPO_ROOT / "apps" / "asia-markets-dashboard" / ".generated"

SECTORS: dict[str, dict[str, str]] = {
    "labour": {
        "slug": "hk-labour-market",
        "name_en": "Hong Kong Labour Market & Talent Policy",
        "name_zh": "香港劳动力市场与人才政策",
        "short_en": "Labour Market",
        "short_zh": "劳动力市场",
    },
    "population": {
        "slug": "hk-population-migration",
        "name_en": "Hong Kong Population & Migration",
        "name_zh": "香港人口与迁移流动",
        "short_en": "Population & Migration",
        "short_zh": "人口与迁移",
    },
    "real_estate": {
        "slug": "hk-real-estate",
        "name_en": "Hong Kong Real Estate",
        "name_zh": "香港地产",
        "short_en": "Real Estate",
        "short_zh": "地产",
    },
    "transport": {
        "slug": "hk-transport",
        "name_en": "Hong Kong Transport & Aviation",
        "name_zh": "香港交通与航空",
        "short_en": "Transport & Aviation",
        "short_zh": "交通与航空",
    },
    "crypto": {
        "slug": "hk-stablecoin-crypto",
        "name_en": "Hong Kong Stablecoin & Crypto",
        "name_zh": "香港稳定币与加密资产",
        "short_en": "Stablecoin & Crypto",
        "short_zh": "稳定币与加密资产",
    },
    "aerospace": {
        "slug": "hk-commercial-aerospace",
        "name_en": "Hong Kong Commercial Aerospace",
        "name_zh": "香港商业航天",
        "short_en": "Commercial Aerospace",
        "short_zh": "商业航天",
    },
    "market": {
        "slug": "market-monitor",
        "name_en": "Index & ETF Allocation Monitor",
        "name_zh": "指数与ETF配置监控",
        "short_en": "ETF Monitor",
        "short_zh": "ETF监控",
    },
}

HISTORY_WINDOWS = {
    "10 years": 10,
    "5 years": 5,
    "3 years": 3,
    "1 year": 1,
    "Full history": None,
}

MONTH_LABELS_ZH = {
    "Jan": "1月",
    "Feb": "2月",
    "Mar": "3月",
    "Apr": "4月",
    "May": "5月",
    "Jun": "6月",
    "Jul": "7月",
    "Aug": "8月",
    "Sep": "9月",
    "Oct": "10月",
    "Nov": "11月",
    "Dec": "12月",
}

PALETTE = [
    "#4285F4",
    "#FF6B6B",
    "#00B5A4",
    "#FF7849",
    "#8B5CF6",
    "#EC4899",
    "#84CC16",
    "#F59E0B",
    "#06B6D4",
    "#9CA3AF",
]

SOURCE_DATASETS = {
    "immd": "immd_daily_traffic",
    "csd": "csd_population",
    "mpfa": "mpfa_claims",
    "ugc": "ugc_students",
    "td": "td_cross_border",
}

CHINA_AIRLINE_SERIES_LABELS = {
    "AC": "Air China",
    "CS": "China Southern",
    "CE": "China Eastern",
    "Spring": "Spring Airlines",
    "Hainan": "Hainan Airlines Holdings",
    "Juneyao": "Juneyao Airlines",
}

CHINA_AIRLINE_SERIES_LABELS_ZH = {
    "AC": "中国国际航空",
    "CS": "中国南方航空",
    "CE": "中国东方航空",
    "Spring": "春秋航空",
    "Hainan": "海航控股",
    "Juneyao": "吉祥航空",
}

CHINA_AIRLINE_REGION_SERIES_LABELS = {
    f"{short} · {region}": f"{label} · {region}"
    for short, label in CHINA_AIRLINE_SERIES_LABELS.items()
    for region in ("Domestic", "International", "Regional")
}
CHINA_AIRLINE_REGION_SERIES_LABELS_ZH = {
    f"{short} · {region}": f"{label} · {region_zh}"
    for short, label in CHINA_AIRLINE_SERIES_LABELS_ZH.items()
    for region, region_zh in (
        ("Domestic", "国内"),
        ("International", "国际"),
        ("Regional", "地区"),
    )
}

CHINA_AIRLINE_TABLE_LABELS_ZH = {
    "airline": {
        "Air China": "中国国航",
        "China Southern": "南方航空",
        "China Eastern": "东方航空",
        "Spring Airlines": "春秋航空",
        "Hainan Airlines Holdings": "海航控股",
        "Juneyao Airlines": "吉祥航空",
    },
    "reporting_scope": {
        "Group-consolidated operating data": "集团合并运营数据",
        "Company and subsidiaries": "公司及子公司",
        "Hainan group consolidated; includes eight operating carriers": "海航集团合并；包括八家运营航司",
        "Company and Jiuyuan Airlines consolidated": "公司及九元航空合并",
    },
    "event_type": {
        "fleet_added_aircraft": "引进飞机",
        "fleet_retired_aircraft": "退出／退租飞机",
        "fleet_total_aircraft": "机队总数",
        "new_route_event_count": "新航线事件数",
    },
}

MTR_SERIES_LABELS = {
    "Domestic": "Domestic heavy rail",
    "X-Boundary": "Cross-boundary",
    "HSR": "HSR",
    "Airport Exp": "Airport Express",
    "LR & Bus": "Light Rail / Bus",
}

MTR_SERIES_LABELS_ZH = {
    "Domestic": "本地重铁",
    "X-Boundary": "跨境",
    "HSR": "高铁",
    "Airport Exp": "机场快线",
    "LR & Bus": "轻铁／巴士",
}

CRYPTO_ATTENTION_AGENT_LABELS = {
    "user": "User",
    "spider": "Search-engine spider",
    "automated": "Automated",
    "all-agents": "All agents",
}

CRYPTO_ATTENTION_AGENT_LABELS_ZH = {
    "user": "用户",
    "spider": "搜索引擎爬虫",
    "automated": "自动化程序",
    "all-agents": "全部代理",
}

CRYPTO_PAGE_LABELS = {
    "Bitcoin": "Bitcoin",
    "Ethereum": "Ethereum",
    "Cryptocurrency": "Cryptocurrency",
    "Stablecoin": "Stablecoin",
    "Tether": "Tether",
    "USD Coin": "USD Coin",
    "Decentralized finance": "Decentralized finance",
    "Decentralized exchange": "Decentralized exchange",
}

CRYPTO_PAGE_LABELS_ZH = {
    "Bitcoin": "比特币",
    "Ethereum": "以太坊",
    "Cryptocurrency": "加密货币",
    "Stablecoin": "稳定币",
    "Tether": "Tether",
    "USD Coin": "USD Coin",
    "Decentralized finance": "去中心化金融",
    "Decentralized exchange": "去中心化交易所",
}

AEROSPACE_PROGRAM_LABELS = {
    "national_program": "National program",
    "state_owned_commercial": "State-owned commercial",
    "commercial_provider": "Commercial provider",
}

AEROSPACE_PROGRAM_LABELS_ZH = {
    "national_program": "国家队项目",
    "state_owned_commercial": "国企商业化",
    "commercial_provider": "商业发射服务商",
}

AEROSPACE_OBJECT_TYPE_LABELS = {
    "Payload": "Payload",
    "Rocket body": "Rocket body",
    "Debris": "Debris",
    "Unknown": "Unknown",
}

AEROSPACE_OBJECT_TYPE_LABELS_ZH = {
    "Payload": "有效载荷",
    "Rocket body": "火箭体",
    "Debris": "碎片",
    "Unknown": "未知",
}

AEROSPACE_ATTENTION_PAGE_LABELS = {
    "SpaceX": "SpaceX",
    "Starlink": "Starlink",
    "Rocket Lab": "Rocket Lab",
    "Falcon 9": "Falcon 9",
    "New Glenn": "New Glenn",
    "Long March": "Long March",
    "Chinese space program": "Chinese space program",
    "Satellite constellation": "Satellite constellation",
    "Commercial spaceflight": "Commercial spaceflight",
}

AEROSPACE_ATTENTION_PAGE_LABELS_ZH = {
    "SpaceX": "SpaceX",
    "Starlink": "Starlink",
    "Rocket Lab": "Rocket Lab",
    "Falcon 9": "猎鹰9号",
    "New Glenn": "新格伦",
    "Long March": "长征系列运载火箭",
    "Chinese space program": "中国航天计划",
    "Satellite constellation": "卫星星座",
    "Commercial spaceflight": "商业航天飞行",
}

PAIR_CARD_HEIGHT = 700

def get_pair_heights(h1: int | None, h2: int | None, type1: str = "line", type2: str = "line") -> tuple[int, int]:
    # Default heights if not specified
    def_h1 = h1 if h1 is not None else (400 if type1 == "bar" else 380)
    def_h2 = h2 if h2 is not None else (400 if type2 == "bar" else 380)
    max_h = max(def_h1, def_h2)
    # Card container height = max chart height + padding for header/title/etc.
    # We will use 180px padding which is perfect for headers and radio buttons.
    return max_h + 180, max_h


# Overview is intentionally capped. A new sector can contribute a compact
# pulse row by adding metadata here, but it does not automatically add another
# full chart section to the page.
OVERVIEW_PULSE_CONFIG: dict[str, dict[str, Any]] = {
    "market": {
        "metrics": (
            {
                "dataset": "kpi_market",
                "field": "csi300_rsi",
                "format": "number",
                "label_en": "CSI 300 RSI",
                "label_zh": "沪深300 RSI",
            },
            {
                "dataset": "kpi_market",
                "field": "sp500_rsi",
                "format": "number",
                "label_en": "S&P 500 RSI",
                "label_zh": "标普500 RSI",
            },
            {
                "dataset": "kpi_market",
                "field": "small_large_z",
                "format": "number",
                "label_en": "Small / Large z",
                "label_zh": "小盘/大盘 z",
            },
        ),
        "sparkline": {
            "chart_id": "small_large_regime_chart",
            "series": "Small / Large",
            "title_en": "Small vs Large relative strength",
            "title_zh": "小盘 vs 大盘相对强度",
            "note_en": "20D z-score of the rolling spread",
            "note_zh": "滚动价差的 20 日 z 得分",
            "format": "number",
        },
    },
    "labour": {
        "metrics": (
            {
                "dataset": "kpi_labour_force",
                "field": "unemployment_rate",
                "format": "percent",
                "label_en": "Unemployment rate",
                "label_zh": "失业率",
            },
            {
                "dataset": "kpi_labour_demand",
                "field": "vacancies",
                "format": "number",
                "label_en": "Vacancies",
                "label_zh": "职位空缺",
            },
            {
                "dataset": "kpi_income",
                "field": "median_monthly_earnings",
                "format": "number",
                "label_en": "Median earnings (HK$)",
                "label_zh": "就业收入中位数（港元）",
            },
        ),
        "sparkline": {
            "chart_id": "labour_rates_chart",
            "series": "Unemployment rate",
            "title_en": "Unemployment rate history",
            "title_zh": "失业率历史",
            "note_en": "Monthly rolling-three-month rate",
            "note_zh": "每月三个月移动平均",
            "format": "percent",
        },
    },
    "population": {
        "metrics": (
            {
                "dataset": "csd_population",
                "field": "mid_year_population_thousands",
                "format": "number",
                "label_en": "Population ('000)",
                "label_zh": "人口（千人）",
            },
            {
                "dataset": "immd_net_flow_history",
                "field": "HK Resident Net Flow",
                "format": "number",
                "series": True,
                "label_en": "HK resident net flow",
                "label_zh": "香港居民净流量",
            },
            {
                "dataset": "immd_net_flow_history",
                "field": "Mainland Visitor Net Retention",
                "format": "number",
                "series": True,
                "label_en": "Mainland visitor net retention",
                "label_zh": "内地访客净留存",
            },
        ),
        "sparkline": {
            "chart_id": "csd_population_chart",
            "series": "Population",
            "title_en": "Population history",
            "title_zh": "人口历史",
            "note_en": "Half-yearly mid/end-year estimate",
            "note_zh": "半年年中／年终估算",
            "format": "number",
        },
    },
    "transport": {
        "metrics": (
            {
                "dataset": "kpi_mtr",
                "field": "latest",
                "format": "number",
                "label_en": "MTR patronage ('000s)",
                "label_zh": "港铁客运量（千人次）",
            },
            {
                "dataset": "kpi_cathay",
                "field": "latest",
                "format": "number",
                "label_en": "Cathay passengers",
                "label_zh": "国泰航空客运量",
            },
            {
                "dataset": "kpi_cathay",
                "field": "load_factor_pct",
                "format": "percent",
                "label_en": "Cathay load factor",
                "label_zh": "国泰航空客座率",
            },
        ),
        "sparkline": {
            "chart_id": "mtr_service_breakdown_chart",
            "series": "Domestic",
            "title_en": "MTR domestic patronage",
            "title_zh": "港铁本地客运量",
            "note_en": "Monthly service breakdown",
            "note_zh": "按月服务类型分拆",
            "format": "number",
        },
    },
    "crypto": {
        "metrics": (
            {
                "dataset": "stablecoin_history",
                "field": "circulating_usd_bn",
                "format": "number",
                "label_en": "Stablecoin supply ($B)",
                "label_zh": "稳定币供应量（十亿美元）",
            },
            {
                "dataset": "dex_volume_history",
                "field": "dex_volume_usd_bn",
                "format": "number",
                "label_en": "DEX volume ($B/day)",
                "label_zh": "DEX 交易量（十亿美元／日）",
            },
            {
                "dataset": "fear_greed_history",
                "field": "score",
                "format": "number",
                "label_en": "Fear & Greed monthly avg",
                "label_zh": "恐惧与贪婪（月均）",
            },
        ),
        "sparkline": {
            "chart_id": "stablecoin_history_chart",
            "series": None,
            "title_en": "Global stablecoin supply",
            "title_zh": "全球稳定币供应量",
            "note_en": "Monthly average of daily circulating supply",
            "note_zh": "每日流通供应量月均值",
            "format": "number",
        },
    },
    "real_estate": {
        "metrics": (
            {
                "dataset": "kpi_ccl",
                "field": "latest",
                "format": "number",
                "label_en": "Centaline CCL",
                "label_zh": "中原城市领先指数（CCL）",
            },
            {
                "dataset": "kpi_mhpi",
                "field": "latest",
                "format": "number",
                "label_en": "Midland MHPI",
                "label_zh": "美联物业价格指数（MHPI）",
            },
            {
                "field": "Overall",
                "format": "number",
                "series": True,
                "chart_id": "rvd_office_trend",
                "label_en": "RVD office rental (Overall)",
                "label_zh": "RVD 写字楼租金（整体）",
            },
        ),
        "sparkline": {
            "chart_id": "ccl_trend",
            "series": None,
            "title_en": "Centaline CCL history",
            "title_zh": "中原城市领先指数历史",
            "note_en": "Weekly publisher-level index",
            "note_zh": "发布者周度指数",
            "format": "number",
        },
    },
    "aerospace": {
        "metrics": (
            {
                "field": "national_program",
                "format": "number",
                "series": True,
                "chart_id": "china_launch_monthly_chart",
                "label_en": "Latest national-program launches",
                "label_zh": "国家队项目最新发射次数",
            },
            {
                "field": "commercial_provider",
                "format": "number",
                "series": True,
                "chart_id": "china_launch_monthly_chart",
                "label_en": "Latest commercial-provider launches",
                "label_zh": "商业发射服务商最新发射次数",
            },
            {
                "field": "Qianfan",
                "format": "number",
                "series": True,
                "chart_id": "satellite_history_chart",
                "label_en": "Qianfan tracked inventory",
                "label_zh": "千帆跟踪目标数",
            },
        ),
        "sparkline": {
            "chart_id": "china_launch_monthly_chart",
            "series": "national_program",
            "title_en": "National launch cadence",
            "title_zh": "国家队发射节奏",
            "note_en": "Monthly verified launch events",
            "note_zh": "每月已核验发射任务",
            "format": "number",
        },
    },
}

# Keep the featured-trend budget explicit, but leave it empty until higher-
# frequency inputs and derived signals have been ingested and validated.
OVERVIEW_FEATURED_CHARTS: tuple[dict[str, Any], ...] = ()


def tr(language: str, english: str, chinese: str) -> str:
    return chinese if language == "zh" else english


def view_label(language: str, view: str) -> str:
    labels = {
        "Level": ("Level", "水平"),
        "MoM %": ("MoM %", "环比 %"),
        "QoQ %": ("QoQ %", "环比 %"),
        "YoY %": ("YoY %", "同比 %"),
        "WoW %": ("WoW %", "周环比 %"),
        "Day %": ("Day %", "日变化 %"),
        "MoM Δpp": ("MoM Δpp", "环比 Δ百分点"),
        "YoY Δpp": ("YoY Δpp", "同比 Δ百分点"),
        "Half-year Δ": ("Half-year Δ", "半年变化"),
        "YoY Δ": ("YoY Δ", "同比变化"),
    }
    english, chinese = labels.get(view, (view, view))
    return tr(language, english, chinese)


@st.cache_data(show_spinner=False)
def load_artifact(slug: str, language: str, artifact_mtime_ns: int = 0) -> dict[str, Any]:
    """Load a local artifact, invalidating the cache when its JSON changes.

    The mtime is deliberately a cache-key argument rather than a hidden
    underscore argument. This keeps the no-network local-artifact model while
    allowing a running Streamlit process to pick up a freshly rebuilt package.
    """
    suffix = "-zh" if language == "zh" else ""
    path = ARTIFACT_ROOT / f"{slug}-artifact{suffix}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def artifact_mtime_ns(slug: str, language: str) -> int:
    suffix = "-zh" if language == "zh" else ""
    path = ARTIFACT_ROOT / f"{slug}-artifact{suffix}.json"
    return path.stat().st_mtime_ns if path.exists() else 0


def find_manifest_item(artifact: dict[str, Any], kind: str, item_id: str) -> dict[str, Any] | None:
    for item in artifact.get("manifest", {}).get(kind, []):
        if item.get("id") == item_id:
            return item
    return None


def manifest_item(artifact: dict[str, Any], kind: str, item_id: str) -> dict[str, Any]:
    item = find_manifest_item(artifact, kind, item_id)
    if item is not None:
        return item
    raise KeyError(f"Missing {kind} item: {item_id}")


def frame_for_dataset(artifact: dict[str, Any], dataset_id: str) -> pd.DataFrame:
    rows = artifact.get("snapshot", {}).get("datasets", {}).get(dataset_id, [])
    if not isinstance(rows, list):
        return pd.DataFrame()
    return pd.DataFrame(rows)


def source_health_frame(artifact: dict[str, Any]) -> pd.DataFrame:
    """Read source health from either the snapshot dataset or artifact root."""
    snapshot_health = frame_for_dataset(artifact, "source_health")
    if not snapshot_health.empty:
        return snapshot_health
    root_health = artifact.get("source_health", [])
    return pd.DataFrame(root_health) if isinstance(root_health, list) else pd.DataFrame()


def parse_period(value: Any) -> pd.Timestamp | pd.NaT:
    if pd.isna(value):
        return pd.NaT
    text = str(value)
    quarter = re.fullmatch(r"(\d{4})-Q([1-4])", text)
    if quarter:
        year, q = int(quarter.group(1)), int(quarter.group(2))
        return pd.Timestamp(year=year, month=q * 3, day=1) + pd.offsets.MonthEnd(0)
    academic_year = re.fullmatch(r"(\d{4})/(\d{2,4})", text)
    if academic_year:
        return pd.Timestamp(year=int(academic_year.group(1)), month=8, day=1)
    parsed = pd.to_datetime(text, errors="coerce")
    return parsed if not pd.isna(parsed) else pd.NaT


def add_date_column(frame: pd.DataFrame, field: str) -> pd.DataFrame:
    output = frame.copy()
    if field not in output.columns:
        return output
    output["_date"] = output[field].map(parse_period)
    return output.dropna(subset=["_date"]).sort_values("_date")


def history_window(frame: pd.DataFrame, field: str, window: str) -> tuple[pd.DataFrame, str]:
    dated = add_date_column(frame, field)
    if dated.empty or HISTORY_WINDOWS[window] is None:
        return dated, "Full available history"
    latest = dated["_date"].max()
    earliest = dated["_date"].min()
    cutoff = latest - pd.DateOffset(years=HISTORY_WINDOWS[window])
    filtered = dated[dated["_date"] >= cutoff].copy()
    if filtered.empty:
        filtered = dated.copy()
    coverage = f"{filtered['_date'].min():%b %Y} – {filtered['_date'].max():%b %Y}"
    if earliest >= cutoff:
        coverage += " · all available"
    return filtered, coverage


def resample_line_frame(
    frame: pd.DataFrame,
    value_field: str,
    series_field: str | None,
    frequency: str,
) -> pd.DataFrame:
    """Aggregate a daily series without changing the stored source artifact."""
    if frequency == "Daily" or frame.empty:
        return frame
    rule = {"Weekly": "W-SUN", "Monthly": "MS", "Quarterly": "QS"}[frequency]
    if series_field and series_field in frame.columns:
        parts: list[pd.DataFrame] = []
        for series_name, group in frame.groupby(series_field, dropna=False, sort=False):
            values = (
                group.set_index("_date")[value_field]
                .sort_index()
                .resample(rule)
                .sum(min_count=1)
                .dropna()
                .rename(value_field)
                .reset_index()
            )
            values[series_field] = series_name
            parts.append(values)
        return pd.concat(parts, ignore_index=True) if parts else frame.iloc[0:0].copy()
    values = (
        frame.set_index("_date")[value_field]
        .sort_index()
        .resample(rule)
        .sum(min_count=1)
        .dropna()
        .rename(value_field)
        .reset_index()
    )
    return values


def localize_coverage(coverage: str, language: str) -> str:
    if language == "en":
        return coverage
    if coverage == "Full available history":
        return "全部可用历史"
    output = coverage.replace(" · all available", " · 全部可用")
    for english, chinese in MONTH_LABELS_ZH.items():
        output = re.sub(rf"{english} (\d{{4}})", rf"\1年{chinese}", output)
    return output


def latest_row(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}
    date_fields = ["date", "observation_date", "month", "period", "quarter", "academic_year"]
    for field in date_fields:
        if field in frame.columns:
            ordered = add_date_column(frame, field)
            if not ordered.empty:
                return ordered.iloc[-1].to_dict()
    return frame.iloc[-1].to_dict()


def is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value))


def format_number(value: Any) -> str:
    if is_missing(value):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"{number:,.0f}"
    return f"{number:,.1f}"


def format_metric(value: Any, fmt: str = "number") -> str:
    if is_missing(value):
        return "—"
    if fmt == "percent":
        try:
            number = float(value)
            if abs(number) <= 1.5:
                number *= 100
            return f"{number:,.1f}%"
        except (TypeError, ValueError):
            return str(value)
    if fmt == "text":
        return str(value)
    return format_number(value)


def observation_date_label(value: Any, language: str) -> str:
    if is_missing(value):
        return "—"
    text = str(value)
    if re.fullmatch(r"d{4}-Q[1-4]", text) or re.fullmatch(r"d{4}/d{2,4}", text):
        return text
    parsed = parse_period(value)
    if pd.isna(parsed):
        return text
    if language == "zh":
        return f"{parsed.year}年{parsed.month}月{parsed.day}日"
    return parsed.strftime("%d %b %Y")


def latest_metric_reading(
    artifact: dict[str, Any],
    dataset_id: str,
    field: str,
    fmt: str,
    *,
    label_en: str,
    label_zh: str,
    language: str,
) -> tuple[str, str, str]:
    frame = frame_for_dataset(artifact, dataset_id)
    if frame.empty or field not in frame.columns:
        return (label_zh if language == "zh" else label_en, "—", "—")
    row = latest_row(frame)
    date_field = next(
        (candidate for candidate in ["observation_date", "date", "month", "period", "quarter", "academic_year"] if candidate in row),
        None,
    )
    label = label_zh if language == "zh" else label_en
    return label, format_metric(row.get(field), fmt), observation_date_label(row.get(date_field), language)


def latest_series_reading(
    artifact: dict[str, Any],
    chart_id: str,
    series_name: str,
    fmt: str,
    language: str,
) -> tuple[str, str]:
    spec = manifest_item(artifact, "charts", chart_id)
    frame = frame_for_dataset(artifact, spec["dataset"])
    series_field = spec.get("encodings", {}).get("color", {}).get("field")
    value_field = spec.get("encodings", {}).get("y", {}).get("field")
    date_field = spec.get("encodings", {}).get("x", {}).get("field")
    if frame.empty or not series_field or not value_field or not date_field or series_field not in frame.columns:
        return "—", "—"
    filtered = frame[frame[series_field].astype(str).eq(series_name)].copy()
    if filtered.empty or value_field not in filtered.columns or date_field not in filtered.columns:
        return "—", "—"
    ordered = add_date_column(filtered, date_field)
    if ordered.empty:
        return "—", "—"
    row = ordered.iloc[-1]
    return format_metric(row.get(value_field), fmt), observation_date_label(row.get(date_field), language)


def series_for_sparkline(artifact: dict[str, Any], chart_id: str, series_name: str | None) -> pd.DataFrame:
    spec = manifest_item(artifact, "charts", chart_id)
    frame = frame_for_dataset(artifact, spec["dataset"])
    series_field = spec.get("encodings", {}).get("color", {}).get("field")
    value_field = spec.get("encodings", {}).get("y", {}).get("field")
    date_field = spec.get("encodings", {}).get("x", {}).get("field")
    if frame.empty or not value_field or not date_field:
        return pd.DataFrame()
    if series_field and series_field in frame.columns:
        filtered = frame[frame[series_field].astype(str).eq(str(series_name))].copy()
    else:
        filtered = frame.copy()
    if filtered.empty:
        return pd.DataFrame()
    ordered = add_date_column(filtered, date_field)
    if ordered.empty:
        return pd.DataFrame()
    ordered["_spark_value"] = pd.to_numeric(ordered[value_field], errors="coerce")
    return ordered.dropna(subset=["_spark_value"]).tail(36)


def observation_period_label(value: Any, language: str) -> str:
    if is_missing(value):
        return "—"
    parsed = parse_period(value)
    if pd.isna(parsed):
        return str(value)
    if language == "zh":
        return f"{parsed.year}年{parsed.month}月"
    return parsed.strftime("%b %Y")


def sparkline_context(
    artifact: dict[str, Any],
    sparkline: dict[str, Any],
    language: str,
) -> tuple[pd.DataFrame, str, str, str, str]:
    frame = series_for_sparkline(artifact, sparkline["chart_id"], sparkline["series"])
    if frame.empty:
        return frame, "—", "—", "—", "—"
    title = sparkline["title_zh"] if language == "zh" else sparkline["title_en"]
    note = sparkline["note_zh"] if language == "zh" else sparkline["note_en"]
    latest_value = format_metric(frame.iloc[-1]["_spark_value"], sparkline.get("format", "number"))
    start = observation_period_label(frame.iloc[0]["_date"], language)
    end = observation_period_label(frame.iloc[-1]["_date"], language)
    date_range = f"{start} – {end}"
    return frame, title, latest_value, date_range, note


def sparkline_svg(frame: pd.DataFrame, color: str = PALETTE[0]) -> str:
    if frame.empty or len(frame) < 2:
        return ""
    values = frame["_spark_value"].astype(float).tolist()
    low, high = min(values), max(values)
    span = high - low
    if span == 0:
        span = 1.0
    width, height, pad = 160, 36, 3
    points = []
    for index, value in enumerate(values):
        x = pad + (width - 2 * pad) * index / max(1, len(values) - 1)
        y = height - pad - (height - 2 * pad) * (value - low) / span
        points.append(f"{x:.1f},{y:.1f}")
    return (
        f'<svg class="am-pulse-sparkline" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Trend sparkline"><polyline points="{" ".join(points)}" '
        f'fill="none" stroke="{escape(color)}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


def metric_from_card(
    artifact: dict[str, Any],
    label_artifact: dict[str, Any],
    card_id: str,
    field: str,
    fmt: str,
) -> tuple[str, str, str]:
    card = next(item for item in artifact["manifest"]["cards"] if item["id"] == card_id)
    label_card = next(item for item in label_artifact["manifest"]["cards"] if item["id"] == card_id)
    dataset = frame_for_dataset(artifact, card["dataset"])
    row = latest_row(dataset)
    metric = next(item for item in label_card["metrics"] if item["field"] == field)
    return metric["label"], format_metric(row.get(field), fmt), label_card.get("description", card.get("description", ""))


def style_app() -> None:
    st.markdown(
        """
        <style>
        :root { --am-blue: #2563eb; --am-ink: #111827; --am-muted: #667085; }
        .stApp { background: #ffffff; color: var(--am-ink); }
        [data-testid="stSidebar"] { background: #f7f8fa; border-right: 1px solid #e5e7eb; }
        [data-testid="stSidebar"] > div:first-child { padding-top: 1.2rem; }
        [data-testid="stSidebar"] .am-sidebar-group-label { color: #6b7280; font-size: .68rem; font-weight: 750; letter-spacing: .1em; text-transform: uppercase; margin: 1rem 0 .3rem .65rem; }
        [data-testid="stSidebar"] .stButton { margin-bottom: .12rem; }
        [data-testid="stSidebar"] .stButton > button { justify-content: flex-start; min-height: 2.25rem; padding: .4rem .65rem; border: 0 !important; border-radius: 7px; background: transparent !important; box-shadow: none !important; color: #111827 !important; font-size: .86rem; font-weight: 520; }
        [data-testid="stSidebar"] .stButton > button > div,
        [data-testid="stSidebar"] .stButton > button > div > span,
        [data-testid="stSidebar"] .stButton > button [data-testid="stMarkdownContainer"] { width: 100% !important; max-width: none !important; flex: 1 1 auto !important; }
        [data-testid="stSidebar"] .stButton > button p { width: 100%; margin: 0; text-align: left; }
        [data-testid="stSidebar"] .stButton > button:hover { background: rgba(37, 99, 235, .07) !important; color: #2563eb !important; transform: none; }
        [data-testid="stSidebar"] .stButton > button:hover p { color: #2563eb !important; }
        [data-testid="stSidebar"] .stButton > button[kind="primary"] { background: rgba(37, 99, 235, .13) !important; color: #2563eb !important; font-weight: 700; box-shadow: inset 3px 0 0 #2563eb !important; }
        [data-testid="stSidebar"] .stButton > button[kind="primary"] p { color: #2563eb !important; }
        [data-testid="stSidebar"] .stSelectbox label { color: #6b7280 !important; font-size: .75rem; font-weight: 700; }
        [data-testid="stMetric"] { border: 1px solid #e5e7eb; border-radius: 10px; padding: .8rem .9rem; background: #ffffff; }
        [data-testid="stMetricLabel"] { color: #667085; }
        [data-testid="stMetricValue"] { color: #111827; }
        .am-kicker { color: #4b5563; font-size: 1.02rem; letter-spacing: .05em; text-transform: uppercase; font-weight: 750; }
        .am-section .am-kicker { color: #374151; font-size: 1.12rem; }
        .am-meta { color: #667085; font-size: .96rem; }
        .am-page-title { margin: 0 0 .25rem; color: #111827; font-size: 2rem; line-height: 1.15; letter-spacing: -.035em; font-weight: 800; }
        .am-chart-title { margin: .15rem 0 .15rem; color: #111827; font-size: 1.08rem; line-height: 1.25; font-weight: 750; }
        .am-section { margin-top: 1.2rem; margin-bottom: .55rem; }
        .am-section h2 { margin-bottom: .15rem; }
        .am-note { color: #667085; font-size: .8rem; }
        .am-brand { display: flex; align-items: center; gap: .6rem; margin: .15rem 0 1.1rem; }
        .am-brand-mark { display: grid; width: 2rem; height: 2rem; place-items: center; border-radius: .5rem; background: #2563eb; color: white; font-weight: 800; }
        .am-brand-name { font-weight: 800; line-height: 1.1; }
        .am-brand-sub { color: #667085; font-size: .68rem; margin-top: .15rem; }
        .am-overview-status { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .85rem; margin: .9rem 0 1.45rem; }
        .am-overview-status-item { min-height: 7.2rem; padding: 1.1rem 1.15rem; border: 1px solid #e5e7eb; border-radius: 10px; background: #f9fafb; display: flex; flex-direction: column; justify-content: center; }
        .am-overview-status-label { color: #667085; font-size: .96rem; font-weight: 750; letter-spacing: .04em; text-transform: uppercase; }
        .am-overview-status-value { margin-top: .34rem; color: #111827; font-size: 1.55rem; font-weight: 750; line-height: 1.15; white-space: nowrap; }
        .am-overview-status-note { margin-top: .2rem; color: #9ca3af; font-size: .9rem; line-height: 1.25; }
        .am-pulse-title { margin: .1rem 0 .3rem; color: #111827; font-size: 1.38rem; font-weight: 750; line-height: 1.25; }
        .am-pulse-meta { color: #667085; font-size: .96rem; }
        .am-pulse-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .7rem; margin-top: 1.05rem; }
        .am-pulse-metric { min-width: 0; padding: .9rem .9rem; border: 1px solid #eef1f5; border-radius: 9px; background: #fafbfc; }
        .am-pulse-label { min-height: 1.55em; color: #667085; font-size: .86rem; font-weight: 700; line-height: 1.2; white-space: normal; }
        .am-pulse-value { margin-top: .24rem; color: #111827; font-size: 1.42rem; font-weight: 750; line-height: 1.1; }
        .am-pulse-asof { margin-top: .24rem; color: #9ca3af; font-size: .82rem; }
        .am-pulse-sparkline-title { margin-top: .9rem; color: #374151; font-size: .86rem; font-weight: 750; }
        .am-pulse-sparkline-meta { margin-top: .18rem; color: #667085; font-size: .8rem; }
        .am-pulse-sparkline-note { margin-top: .14rem; color: #9ca3af; font-size: .76rem; }
        .am-pulse-sparkline { display: block; width: 100%; height: 44px; margin: .9rem 0 .25rem; }
        .am-health-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .7rem; align-items: center; }
        .am-health-value { color: #111827; font-size: 1.15rem; font-weight: 750; }
        .am-health-label { color: #667085; font-size: .72rem; }
        @media (max-width: 900px) {
            .am-overview-status { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .am-pulse-metrics { grid-template-columns: 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def chart_theme(fig: Any, value_format: str = "number", date_axis: bool = True, height: int = 380) -> Any:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin={"l": 10, "r": 18, "t": 10, "b": 62},
        colorway=PALETTE,
        hovermode="x unified" if date_axis else "closest",
        legend={"orientation": "h", "y": -0.18, "x": 0, "title": ""},
        hoverlabel={"bgcolor": "#FFFFFF", "bordercolor": "#E5E7EB", "font": {"color": "#111827", "size": 12}, "namelength": -1},
        font={"family": "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif", "size": 12, "color": "#374151"},
    )
    fig.update_xaxes(showgrid=False, automargin=True)
    fig.update_yaxes(showgrid=True, gridcolor="#eef1f5", automargin=True)
    if value_format == "percent":
        fig.update_yaxes(tickformat=".1%")
    return fig


def date_hover_format(dates: pd.Series) -> str:
    """Tooltip date format for a series, chosen by its grain.

    Keyed off the spacing between observations, not the total span. The old
    rule dropped the day from the tooltip once a series ran longer than 550
    days, which is backwards: axis *ticks* have to coarsen as the span grows
    because they collide with each other, but a tooltip shows one point and
    never collides. A daily series needs its day at any span -- which is why
    two years of daily ETF prices hovered as a bare "Aug 2026".
    """
    ordered = pd.Series(pd.to_datetime(dates, errors="coerce")).dropna().drop_duplicates().sort_values()
    if len(ordered) < 2:
        return "%d %b %Y"
    spacing = ordered.diff().dropna().median()
    if spacing >= pd.Timedelta(days=350):
        return "%Y"
    if spacing >= pd.Timedelta(days=25):
        return "%b %Y"
    return "%d %b %Y"


def date_tick_format(dates: pd.Series) -> str:
    """Axis tick format: coarse enough not to collide, fine enough to place.

    A short daily window labelled "%b %Y" repeats one month across every tick,
    which is what the premium chart showed on its first two days of history.
    """
    ordered = pd.Series(pd.to_datetime(dates, errors="coerce")).dropna().sort_values()
    if ordered.empty:
        return "%b %Y"
    span = ordered.max() - ordered.min()
    if span <= pd.Timedelta(days=120):
        return "%d %b"
    if span <= pd.Timedelta(days=1100):
        return "%b %Y"
    return "%Y"


def apply_line_hover(fig: Any, frame: pd.DataFrame, value_format: str) -> None:
    x_format = date_hover_format(frame["_date"])
    y_format = ".1%" if value_format == "percent" else ",.1f"
    for trace in fig.data:
        series_name = trace.name or "Value"
        trace.hovertemplate = f"<b>%{{x|{x_format}}}</b><br>{series_name}: %{{y:{y_format}}}<extra></extra>"


def apply_bar_hover(fig: Any, value_label: str, horizontal: bool) -> None:
    for trace in fig.data:
        series_name = trace.name or value_label
        if horizontal:
            trace.hovertemplate = f"<b>%{{y}}</b><br>{value_label}: %{{x:,.1f}}<extra></extra>"
        else:
            trace.hovertemplate = f"<b>%{{x}}</b><br>{series_name}: %{{y:,.1f}}<extra></extra>"


def line_view_frame(
    frame: pd.DataFrame,
    value_field: str,
    series_field: str | None,
    view: str,
    periods_per_year: int,
    change_mode: str,
    value_format: str,
) -> tuple[pd.DataFrame, str, str]:
    output = frame.copy()
    group_fields = [series_field] if series_field and series_field in output.columns else []
    output = output.sort_values(group_fields + ["_date"] if group_fields else ["_date"])
    if view == "Level":
        output["_value"] = output[value_field]
        return output, "Level", value_format
    grouped = output.groupby(group_fields, dropna=False)[value_field] if group_fields else output[value_field]
    if change_mode == "delta":
        changed = grouped.diff(periods_per_year if "YoY" in view else 1)
        if value_format == "percent":
            changed = changed * 100
        output["_value"] = changed
        suffix = "Δpp" if value_format == "percent" else "Δ"
        if "YoY" in view:
            label = f"YoY {suffix}"
        elif "MoM" in view:
            label = f"MoM {suffix}"
        elif "QoQ" in view:
            label = f"QoQ {suffix}"
        elif "WoW" in view:
            label = f"WoW {suffix}"
        else:
            label = suffix
        return output.dropna(subset=["_value"]), label, "number"
    changed = grouped.pct_change(periods_per_year if "YoY" in view else 1) * 100
    output["_value"] = changed
    if "YoY" in view:
        label = "YoY %"
    elif "MoM" in view:
        label = "MoM %"
    elif "QoQ" in view:
        label = "QoQ %"
    elif "WoW" in view:
        label = "WoW %"
    elif "Day" in view:
        label = "Day %"
    else:
        label = "Period %"
    return output.dropna(subset=["_value"]), label, "number"


def render_line_chart(
    artifact: dict[str, Any],
    labels: dict[str, Any],
    chart_id: str,
    language: str,
    history_window_name: str,
    *,
    series_selection: Iterable[str] | None = None,
    views: tuple[str, ...] = ("Level",),
    periods_per_year: int = 12,
    change_mode: str = "pct",
    height: int = 380,
    resample_frequency: str | None = None,
    series_label_map: dict[str, str] | None = None,
    reference_bands: tuple[tuple[float, float, str], ...] = (),
) -> None:
    spec = find_manifest_item(artifact, "charts", chart_id)
    if spec is None:
        st.info(tr(language, "This chart is not available in the current artifact snapshot.", "当前数据快照未包含此图表。"))
        return
    label_spec = find_manifest_item(labels, "charts", chart_id) or spec
    x_field = spec["encodings"]["x"]["field"]
    y_field = spec["encodings"]["y"]["field"]
    series_field = spec.get("encodings", {}).get("color", {}).get("field")
    frame = frame_for_dataset(artifact, spec["dataset"])
    frame, coverage = history_window(frame, x_field, history_window_name)
    if series_selection is not None and series_field and series_field in frame.columns:
        frame = frame[frame[series_field].isin(list(series_selection))].copy()
    if resample_frequency:
        frame = resample_line_frame(frame, y_field, series_field, resample_frequency)
    if frame.empty:
        st.info(tr(language, "No rows are available for this selection.", "这个选择没有可用数据。"))
        return

    title = label_spec.get("title", spec["title"])
    subtitle = label_spec.get("subtitle", spec.get("subtitle", ""))
    if resample_frequency and chart_id == "immd_net_flow_chart":
        frequency_label = {
            "Daily": tr(language, "Daily", "日度"),
            "Weekly": tr(language, "Weekly", "周度"),
            "Monthly": tr(language, "Monthly", "月度"),
        }[resample_frequency]
        title = re.sub(r"\s*[（(](?:Daily|日度)[）)]$", "", title).strip()
        title = f"{title} ({frequency_label})" if language == "en" else f"{title}（{frequency_label}）"
    st.markdown(f'<div class="am-chart-title">{title}</div>', unsafe_allow_html=True)
    frequency_note = {
        "Daily": tr(language, "Daily source observations", "日度来源观察值"),
        "Weekly": tr(language, "Weekly sums of underlying observations", "按周合计原始观察值"),
        "Monthly": tr(language, "Monthly sums of underlying observations", "按月合计原始观察值"),
        "Quarterly": tr(language, "Quarterly sums of underlying observations", "按季度合计原始观察值"),
    }.get(resample_frequency or "", "")
    caption_parts = [subtitle]
    if frequency_note:
        caption_parts.append(frequency_note)
    caption_parts.append(localize_coverage(coverage, language))
    st.caption(" · ".join(caption_parts))
    view = views[0]
    if len(views) > 1:
        view = st.radio(
            tr(language, "View", "视图"),
            views,
            horizontal=True,
            key=f"view_{chart_id}",
            format_func=lambda item: view_label(language, item),
        )
    transformed, value_label, transformed_format = line_view_frame(
        frame, y_field, series_field, view, periods_per_year, change_mode, spec.get("valueFormat", "number")
    )
    if transformed.empty:
        st.info(tr(language, "Not enough observations for this comparison window.", "这个比较视图没有足够的观察值。"))
        return
    if series_label_map and series_field and series_field in transformed.columns:
        transformed[series_field] = transformed[series_field].map(
            lambda value: series_label_map.get(str(value), str(value))
        )
    fig = px.line(
        transformed,
        x="_date",
        y="_value",
        color=series_field if series_field and series_field in transformed.columns else None,
        markers=False,
        color_discrete_sequence=PALETTE,
    )
    fig.update_yaxes(title=value_label)
    # Date ticks already carry the time context; removing the redundant
    # "Month"/"Quarter" title leaves room for the legend in compact cards.
    fig.update_xaxes(title=None, tickformat="%b %Y")
    if transformed["_date"].max() - transformed["_date"].min() > pd.Timedelta(days=365 * 7):
        fig.update_xaxes(dtick="M12")
    elif transformed["_date"].max() - transformed["_date"].min() > pd.Timedelta(days=365 * 3):
        fig.update_xaxes(dtick="M6")
    if reference_bands:
        for lower, upper, color in reference_bands:
            fig.add_hrect(
                y0=lower,
                y1=upper,
                fillcolor=color,
                opacity=0.12,
                line_width=0,
                layer="below",
            )
        fig.update_yaxes(range=[0, 100])
    apply_line_hover(fig, transformed, transformed_format)
    fig = chart_theme(fig, transformed_format, date_axis=True, height=height)
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})


def render_fear_greed_daily_chart(
    artifact: dict[str, Any],
    language: str,
    history_window_name: str,
) -> None:
    """Render the raw daily Fear & Greed score and its trailing seven-day mean."""
    frame = frame_for_dataset(artifact, "fear_greed_daily")
    frame, coverage = history_window(frame, "date", history_window_name)
    if frame.empty:
        st.info(tr(language, "Daily Fear & Greed data is not available in this artifact yet.", "这个数据快照暂时没有日度恐惧与贪婪数据。"))
        return

    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    frame["score_7d_avg"] = pd.to_numeric(frame["score_7d_avg"], errors="coerce")
    frame = frame.dropna(subset=["_date", "score"]).sort_values("_date")
    if frame.empty:
        st.info(tr(language, "Daily Fear & Greed data is not available in this artifact yet.", "这个数据快照暂时没有日度恐惧与贪婪数据。"))
        return

    options = ["Both", "Daily score", "7-day rolling average"]
    view = st.radio(
        tr(language, "Metric", "指标"),
        options,
        horizontal=True,
        key="fear_greed_daily_metric_view",
        format_func=lambda item: {
            "Both": tr(language, "Both", "两者"),
            "Daily score": tr(language, "Daily score", "日度分数"),
            "7-day rolling average": tr(language, "7-day rolling average", "7日滚动平均"),
        }[item],
    )
    fields = {
        "Daily score": ["score"],
        "7-day rolling average": ["score_7d_avg"],
        "Both": ["score", "score_7d_avg"],
    }[view]
    plot = frame[["_date", *fields]].melt(
        id_vars=["_date"],
        var_name="series",
        value_name="_value",
    ).dropna(subset=["_value"])
    series_labels = {
        "score": tr(language, "Daily score", "日度分数"),
        "score_7d_avg": tr(language, "7-day rolling average", "7日滚动平均"),
    }
    plot["series"] = plot["series"].map(series_labels)

    st.markdown(
        f'<div class="am-chart-title">{tr(language, "Crypto Fear & Greed: daily signal", "加密恐惧与贪婪：日度信号")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        " · ".join(
            [
                tr(
                    language,
                    "Daily Alternative.me observations; the rolling average is derived from the trailing seven calendar days.",
                    "Alternative.me 日度观察值；滚动平均由最近七个日历日派生。",
                ),
                localize_coverage(coverage, language),
            ]
        )
    )
    fig = px.line(
        plot,
        x="_date",
        y="_value",
        color="series",
        color_discrete_map={
            series_labels["score"]: PALETTE[0],
            series_labels["score_7d_avg"]: PALETTE[1],
        },
    )
    fig.update_yaxes(title=tr(language, "Score", "分数"), range=[0, 100])
    fig.update_xaxes(title=None, tickformat="%d %b %Y")
    span = plot["_date"].max() - plot["_date"].min()
    if span > pd.Timedelta(days=365 * 7):
        fig.update_xaxes(dtick="M12")
    elif span > pd.Timedelta(days=365 * 3):
        fig.update_xaxes(dtick="M6")
    for trace in fig.data:
        trace.line.width = 1.4 if trace.name == series_labels["score"] else 3.0
    apply_line_hover(fig, plot, "number")
    fig = chart_theme(fig, "number", date_axis=True, height=430)
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})


def render_bar_chart(
    artifact: dict[str, Any],
    labels: dict[str, Any],
    chart_id: str,
    language: str,
    *,
    height: int | None = None,
) -> None:
    spec = find_manifest_item(artifact, "charts", chart_id)
    if spec is None:
        st.info(tr(language, "This chart is not available in the current artifact snapshot.", "当前数据快照未包含此图表。"))
        return
    label_spec = find_manifest_item(labels, "charts", chart_id) or spec
    x_field = spec["encodings"]["x"]["field"]
    y_field = spec["encodings"]["y"]["field"]
    color_field = spec.get("encodings", {}).get("color", {}).get("field")
    frame = frame_for_dataset(artifact, spec["dataset"])
    title = label_spec.get("title", spec["title"])
    subtitle = label_spec.get("subtitle", spec.get("subtitle", ""))
    st.markdown(f'<div class="am-chart-title">{title}</div>', unsafe_allow_html=True)
    st.caption(subtitle)
    if frame.empty:
        st.info(tr(language, "No rows are available.", "没有可用数据。"))
        return
    if spec.get("type") == "horizontalBar":
        frame = frame.dropna(subset=[x_field, y_field]).sort_values(y_field)
        fig = px.bar(frame, x=y_field, y=x_field, orientation="h", color_discrete_sequence=[PALETTE[0]])
        fig.update_yaxes(title=spec["encodings"]["x"].get("label", ""))
        fig.update_xaxes(title=spec["encodings"]["y"].get("label", ""))
        computed_height = max(340, min(700, 100 + len(frame) * 30))
        apply_bar_hover(fig, spec["encodings"]["y"].get("label", y_field), horizontal=True)
    else:
        x = x_field
        frame = frame.dropna(subset=[x_field, y_field])
        fig = px.bar(
            frame,
            x=x,
            y=y_field,
            color=color_field if color_field and color_field in frame.columns else None,
            barmode="group",
            color_discrete_sequence=PALETTE,
        )
        fig.update_xaxes(title=spec["encodings"]["x"].get("label", ""))
        fig.update_yaxes(title=spec["encodings"]["y"].get("label", ""))
        computed_height = 400
        apply_bar_hover(fig, spec["encodings"]["y"].get("label", y_field), horizontal=False)
    fig = chart_theme(fig, spec.get("valueFormat", "number"), date_axis=False, height=height or computed_height)
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})


def render_table(
    artifact: dict[str, Any],
    labels: dict[str, Any],
    table_id: str,
    language: str,
    *,
    value_maps: dict[str, dict[str, str]] | None = None,
    max_rows: int | None = None,
) -> None:
    spec = find_manifest_item(artifact, "tables", table_id)
    if spec is None:
        st.info(tr(language, "This table is not available in the current artifact snapshot.", "当前数据快照未包含此表格。"))
        return
    label_spec = find_manifest_item(labels, "tables", table_id) or spec
    frame = frame_for_dataset(artifact, spec["dataset"])
    title = label_spec.get("title", spec["title"])
    subtitle = label_spec.get("subtitle", spec.get("subtitle", ""))
    st.markdown(f'<div class="am-chart-title">{title}</div>', unsafe_allow_html=True)
    st.caption(subtitle)
    if frame.empty:
        st.info(tr(language, "No rows are available.", "没有可用数据。"))
        return
    if max_rows is not None and len(frame) > max_rows:
        date_field = next(
            (field for field in ["launch_date", "date_time", "issue_date", "date"] if field in frame.columns),
            None,
        )
        if date_field:
            frame = frame.assign(_sort_date=pd.to_datetime(frame[date_field], errors="coerce"))
            frame = frame.sort_values("_sort_date", ascending=False, na_position="last")
        frame = frame.head(max_rows).copy()
    fields = [column["field"] for column in spec.get("columns", []) if column["field"] in frame.columns]
    labels_by_field = {
        column["field"]: column.get("label", column["field"])
        for column in spec.get("columns", [])
    }
    display = frame[fields].copy()
    for field, mapping in (value_maps or {}).items():
        if field in display.columns:
            display[field] = display[field].map(lambda value: mapping.get(str(value), value))
    display = display.rename(columns=labels_by_field)
    st.dataframe(display, hide_index=True, width="stretch")


def series_options(
    artifact: dict[str, Any],
    chart_id: str,
    language: str,
    default_count: int = 4,
    series_label_map: dict[str, str] | None = None,
) -> list[str]:
    spec = find_manifest_item(artifact, "charts", chart_id)
    if spec is None:
        return []
    frame = frame_for_dataset(artifact, spec["dataset"])
    field = spec.get("encodings", {}).get("color", {}).get("field")
    if not field or field not in frame.columns:
        return []
    raw_values = [str(value) for value in frame[field].dropna().drop_duplicates().tolist()]
    if series_label_map:
        display_values = [series_label_map.get(value, value) for value in raw_values]
        selected_display = st.multiselect(
            tr(language, "Series to show", "显示序列"),
            display_values,
            default=display_values,
            key=f"series_all_{chart_id}",
        )
        raw_by_display = dict(zip(display_values, raw_values))
        return [raw_by_display.get(value, value) for value in selected_display]
    return st.multiselect(
        tr(language, "Series to show", "显示序列"),
        raw_values,
        default=raw_values,
        key=f"series_all_{chart_id}",
    )


def frequency_control(language: str) -> str:
    options = ["Daily", "Weekly", "Monthly"]
    formatter = lambda item: {
        "Daily": tr(language, "Daily", "日度"),
        "Weekly": tr(language, "Weekly", "周度"),
        "Monthly": tr(language, "Monthly", "月度"),
    }[item]
    if hasattr(st, "segmented_control"):
        selected = st.segmented_control(
            tr(language, "Granularity", "数据粒度"),
            options,
            default="Daily",
            format_func=formatter,
            key="immd_frequency",
        )
    else:
        selected = st.selectbox(
            tr(language, "Granularity", "数据粒度"),
            options,
            index=0,
            format_func=formatter,
            key="immd_frequency",
        )
    return selected or "Daily"


def monthly_quarterly_control(language: str, key: str) -> str:
    options = ["Monthly", "Quarterly"]
    formatter = lambda item: {
        "Monthly": tr(language, "Monthly", "月度"),
        "Quarterly": tr(language, "Quarterly", "季度"),
    }[item]
    if hasattr(st, "segmented_control"):
        selected = st.segmented_control(
            tr(language, "Granularity", "数据粒度"),
            options,
            default="Quarterly",
            format_func=formatter,
            key=key,
        )
    else:
        selected = st.selectbox(
            tr(language, "Granularity", "数据粒度"),
            options,
            index=1,
            format_func=formatter,
            key=key,
        )
    return selected or "Quarterly"


def section_heading(language: str, english: str, chinese: str, note_en: str = "", note_zh: str = "") -> None:
    st.markdown(f'<div class="am-section"><div class="am-kicker">{tr(language, english, chinese)}</div></div>', unsafe_allow_html=True)
    if note_en or note_zh:
        st.caption(tr(language, note_en, note_zh))


def render_header(
    artifact: dict[str, Any],
    labels: dict[str, Any],
    language: str,
    sector_key: str,
    *,
    title_override: str | None = None,
    description_override: str | None = None,
) -> None:
    manifest = labels["manifest"]
    title = title_override or manifest.get("title", SECTORS[sector_key]["name_en"])
    description = description_override or manifest.get("description", "")
    st.markdown(f'<div class="am-page-title">{title}</div>', unsafe_allow_html=True)
    st.caption(description)
    st.markdown(
        f'<div class="am-meta">{tr(language, "Hong Kong", "香港")} · {tr(language, "Snapshot as of", "数据截至")} {artifact.get("package_info", {}).get("dataAsOf", "—")} · {tr(language, "Source-backed local artifact", "基于来源的本地数据快照")}</div>',
        unsafe_allow_html=True,
    )


def render_labour(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    render_header(artifact, labels, language, "labour")
    section_heading(language, "Summary", "摘要", "Latest headline measures", "最新核心指标")
    income_card = metric_from_card(artifact, labels, "income_card", "median_monthly_earnings", "number")
    cards = [
        metric_from_card(artifact, labels, "labour_force_card", "labour_force_thousands", "number"),
        metric_from_card(artifact, labels, "labour_force_card", "unemployment_rate", "percent"),
        (
            tr(language, "Median earnings (HK$)", "就业收入中位数（港元）"),
            income_card[1],
            income_card[2],
        ),
        metric_from_card(artifact, labels, "labour_demand_card", "vacancies", "number"),
    ]
    columns = st.columns(len(cards))
    for column, (label, value, help_text) in zip(columns, cards):
        with column:
            st.metric(label, value, help=help_text)

    section_heading(
        language,
        "Core labour pulse",
        "劳动力核心走势",
        "The main series stays visible together; use the local view controls for Level, period change or YoY.",
        "主要序列同时显示；可用每张图的视图控制切换水平、期间变化或同比。",
    )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "labour_force_chart",
            language,
            window,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=390,
        )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "labour_rates_chart",
            language,
            window,
            views=("Level", "MoM Δpp", "YoY Δpp"),
            periods_per_year=12,
            change_mode="delta",
            height=360,
        )

    section_heading(language, "Labour demand", "劳动力需求", "Latest cross-section plus historical context.", "最新横截面对比及历史背景。")
    card_h, chart_h = get_pair_heights(520, 520, 'bar', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_bar_chart(artifact, labels, "vacancies_by_industry_chart", language, height=chart_h)
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "vacancy_rate_chart",
                language,
                window,
                views=("Level", "QoQ %", "YoY %"),
                periods_per_year=4,
                height=520,
            )
    with st.container(border=True):
        selected = series_options(artifact, "vacancy_industry_history_chart", language, default_count=4)
        render_line_chart(
            artifact,
            labels,
            "vacancy_industry_history_chart",
            language,
            window,
            series_selection=selected,
            views=("Level", "QoQ %", "YoY %"),
            periods_per_year=4,
            height=390,
        )

    section_heading(language, "Earnings & pay", "就业收入与工资", "Median earnings are separate from wage and payroll indices.", "就业收入中位数与工资／薪金指数分开显示。")
    card_h, chart_h = get_pair_heights(480, 480, 'bar', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_bar_chart(artifact, labels, "earnings_by_industry_chart", language, height=chart_h)
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "wage_yoy_chart",
                language,
                window,
                views=("Level",),
                height=480,
            )
    with st.container(border=True):
        selected = series_options(artifact, "earnings_industry_history_chart", language, default_count=4)
        render_line_chart(
            artifact,
            labels,
            "earnings_industry_history_chart",
            language,
            window,
            series_selection=selected,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=390,
        )
    with st.container(border=True):
        selected = series_options(artifact, "occupation_earnings_history_chart", language, default_count=4)
        render_line_chart(
            artifact,
            labels,
            "occupation_earnings_history_chart",
            language,
            window,
            series_selection=selected,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=390,
        )
    with st.container(border=True):
        render_table(artifact, labels, "earnings_by_occupation_table", language)

    section_heading(language, "Talent policy flows", "人才政策流量", "Applications and approvals are policy-flow indicators, not arrivals or employment.", "申请数和批准数是政策流量指标，不等于抵港人数或就业人数。")
    card_h, chart_h = get_pair_heights(350, 350, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(artifact, labels, "talent_policy_received_chart", language, window, views=("Level",), height=chart_h)
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(artifact, labels, "talent_policy_approved_chart", language, window, views=("Level",), height=chart_h)
    with st.container(border=True):
        render_table(artifact, labels, "talent_policy_latest_table", language)

    render_source_coverage({"labour": artifact}, {"labour": labels}, language)


def render_population(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    render_header(artifact, labels, language, "population")
    section_heading(language, "Summary", "摘要", "Population, movement, departure claims and student pipeline.", "人口、迁移、离港申索和学生流量。")
    population_card = metric_from_card(artifact, labels, "kpi_total_pop", "latest_pop", "number")
    movement_card = metric_from_card(artifact, labels, "kpi_net_mov", "latest_net_mov", "number")
    mpf_card = metric_from_card(artifact, labels, "kpi_mpfa_claims", "latest_mpfa", "number")
    student_card = metric_from_card(artifact, labels, "kpi_ugc_students", "latest_ugc", "number")
    cards = [
        (tr(language, "Population ('000)", "人口（千人）"), population_card[1], population_card[2]),
        (tr(language, "Net movement ('000)", "净人口移动（千人）"), movement_card[1], movement_card[2]),
        (tr(language, "MPF claims (HK$m)", "强积金申索（百万港元）"), mpf_card[1], mpf_card[2]),
        (tr(language, "Mainland students", "在港内地生"), student_card[1], student_card[2]),
    ]
    columns = st.columns(len(cards))
    for column, (label, value, help_text) in zip(columns, cards):
        with column:
            st.metric(label, value, help=help_text)

    section_heading(
        language,
        "High-frequency movement",
        "高频人口流动",
        "Daily ImmD data is shown at source grain; a one-year source history is not silently presented as a long-run trend.",
        "入境处日度数据保留来源粒度；只有约一年历史时不会伪装成长周期趋势。",
    )
    with st.container(border=True):
        frequency = frequency_control(language)
        render_line_chart(
            artifact,
            labels,
            "immd_net_flow_chart",
            language,
            window,
            views=("Level", "Day %", "YoY %"),
            periods_per_year=30,
            height=400,
            resample_frequency=frequency,
        )

    section_heading(language, "Population and migration signals", "人口与迁移信号", "Long-run official population series plus permanent-departure claims.", "长期官方人口序列及永久离港强积金申索。")
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "csd_population_chart",
            language,
            window,
            views=("Level", "Half-year Δ", "YoY Δ"),
            periods_per_year=2,
            change_mode="delta",
            height=400,
        )
    card_h, chart_h = get_pair_heights(None, None, 'bar', 'bar')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_bar_chart(artifact, labels, "mpfa_claims_chart", language, height=chart_h)
    with right:
        with st.container(height=card_h, border=True):
            render_bar_chart(artifact, labels, "mpfa_claims_count_chart", language, height=chart_h)

    section_heading(language, "Student and cross-border flows", "学生与跨境流量", "Education and transport indicators provide complementary migration signals.", "教育及交通指标提供互补的迁移信号。")
    card_h, chart_h = get_pair_heights(None, 400, 'bar', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_bar_chart(artifact, labels, "ugc_students_chart", language, height=chart_h)
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "td_cross_border_chart",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=400,
            )

    render_source_coverage({"population": artifact}, {"population": labels}, language)


def latest_period_signal(
    frame: pd.DataFrame,
    date_field: str,
    value_field: str,
    *,
    aggregation: str = "sum",
    change_mode: str = "pct",
) -> dict[str, Any]:
    """Return the latest monthly reading and its same-month-prior-year change."""
    if frame.empty or date_field not in frame.columns or value_field not in frame.columns:
        return {"value": None, "change": None, "date": None}
    output = add_date_column(frame, date_field)
    if output.empty:
        return {"value": None, "change": None, "date": None}
    output["_signal_value"] = pd.to_numeric(output[value_field], errors="coerce")
    output = output.dropna(subset=["_signal_value"])
    if output.empty:
        return {"value": None, "change": None, "date": None}
    grouped = output.groupby("_date")["_signal_value"]
    if aggregation == "mean":
        values = grouped.mean()
    else:
        values = grouped.sum(min_count=1)
    values = values.dropna().sort_index()
    if values.empty:
        return {"value": None, "change": None, "date": None}
    latest_date = values.index.max()
    latest_value = float(values.loc[latest_date])
    prior_target = latest_date - pd.DateOffset(months=12)
    prior_values = values[values.index <= prior_target]
    prior_value = float(prior_values.iloc[-1]) if not prior_values.empty else None
    if prior_value is None:
        change = None
    elif change_mode == "delta":
        change = latest_value - prior_value
    elif prior_value == 0:
        change = None
    else:
        change = (latest_value / prior_value - 1) * 100
    return {"value": latest_value, "change": change, "date": latest_date}


def latest_daily_signal(frame: pd.DataFrame, value_field: str) -> dict[str, Any]:
    """Return the latest daily value without applying a monthly comparison."""
    if frame.empty or value_field not in frame.columns or "date" not in frame.columns:
        return {"value": None, "date": None, "classification": None}
    output = add_date_column(frame, "date")
    output["_signal_value"] = pd.to_numeric(output[value_field], errors="coerce")
    output = output.dropna(subset=["_signal_value"]).sort_values("_date")
    if output.empty:
        return {"value": None, "date": None, "classification": None}
    row = output.iloc[-1]
    return {
        "value": float(row["_signal_value"]),
        "date": row["_date"],
        "classification": row.get("classification"),
    }


def transport_metric_delta(signal: dict[str, Any], change_mode: str = "pct") -> str | None:
    change = signal.get("change")
    if change is None:
        return None
    if abs(change) < 0.05:
        change = 0.0
    suffix = "pp YoY" if change_mode == "delta" else "% YoY"
    return f"{change:+,.1f}{suffix}"


def render_transport_metric(
    column: Any,
    label: str,
    signal: dict[str, Any],
    fmt: str,
    *,
    language: str = "en",
    change_mode: str = "pct",
    volume_unit: str | None = None,
) -> None:
    value = signal.get("value")
    if fmt == "number" and value is not None and volume_unit == "million":
        display_value = f"{float(value) / 1_000_000:,.2f}m"
    elif fmt == "number" and value is not None and volume_unit == "million_from_thousands":
        display_value = f"{float(value) / 1_000:,.1f}m"
    else:
        display_value = format_metric(value, fmt)
    with column:
        st.metric(
            label,
            display_value,
            delta=transport_metric_delta(signal, change_mode),
        )
        st.caption(observation_date_label(signal.get("date"), language))


def render_airline_h1_backtest(
    artifact: dict[str, Any], labels: dict[str, Any], language: str
) -> None:
    """Render source-recovery coverage and the H1 KPI calibration evidence."""
    if not frame_for_dataset(artifact, "airline_h1_backtest_summary").empty:
        section_heading(
            language,
            "H1 2026 earnings calibration",
            "2026 年上半年财报校准",
            "Historical KPI calibration and source-recovery sensitivity for the pre-report earnings view. This is calibration evidence, not a strict point-in-time trading backtest.",
            "用于财报前盈利判断的历史 KPI 校准及数据恢复敏感性；这是校准证据，不是严格的点时交易回测。",
        )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_bar_chart(artifact, labels, "airline_h1_revenue_mae_chart", language, height=390)
        with right:
            with st.container(border=True):
                render_bar_chart(artifact, labels, "airline_h1_cost_mae_chart", language, height=390)
        with st.container(border=True):
            render_table(artifact, labels, "airline_h1_backtest_summary_table", language)

    if not frame_for_dataset(artifact, "airline_period_backtest_summary").empty:
        section_heading(
            language,
            "H1 / H2 / FY calibration and Spring error diagnosis",
            "H1 / H2 / FY 校准与春秋误差诊断",
            "The period view separates first half, derived second half and full-year calibration. The table keeps logical-assumption coverage visible instead of treating it as observed data.",
            "期间视图分开上半年、由 FY 减 H1 推导的下半年及全年校准；表格保留逻辑假设覆盖，不把它当作观测数据。",
        )
        with st.container(border=True):
            render_bar_chart(artifact, labels, "airline_period_revenue_mae_chart", language, height=430)
        with st.container(border=True):
            render_table(artifact, labels, "airline_period_backtest_summary_table", language)

    if not frame_for_dataset(artifact, "airline_source_recovery_summary").empty:
        section_heading(
            language,
            "Recovered-source audit",
            "恢复数据源审计",
            "Monthly airline charts prefer verified official-PDF recoveries. Rows confirmed as absent from the source PDF remain missing; research interpolation is not silently displayed as observed data.",
            "月度航司图表优先使用已核验的官方 PDF 恢复值；确认源 PDF 未披露的行仍保持缺失，研究插值不会被静默当作观测值显示。",
        )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_bar_chart(artifact, labels, "airline_source_recovery_chart", language, height=360)
        with right:
            with st.container(border=True):
                render_table(artifact, labels, "airline_source_recovery_audit_table", language, max_rows=100)

    if not frame_for_dataset(artifact, "airline_h1_revenue_nowcast_comparison").empty:
        section_heading(
            language,
            "Current H1 2026 nowcast",
            "当前 2026 年上半年预测",
            "Spring and Juneyao flat-ASK baselines versus the analyst overlay, shown in USD million. Formal interim actuals remain the eventual event test.",
            "春秋与吉祥的 flat-ASK 基准与分析师调整项，单位为百万美元；正式中报实际值将是最终检验。",
        )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_bar_chart(artifact, labels, "airline_h1_revenue_nowcast_chart", language, height=370)
        with right:
            with st.container(border=True):
                render_bar_chart(artifact, labels, "airline_h1_profit_nowcast_chart", language, height=370)


def render_transport_tabs(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    """Render transport as separate Hong Kong aviation, China aviation and MTR tabs."""
    render_header(
        artifact,
        labels,
        language,
        "transport",
        title_override=tr(language, "Hong Kong Transport & Aviation", "香港交通与航空"),
        description_override=tr(
            language,
            "Company-level airline passenger, cargo, fleet and network-event signals plus MTR passenger demand. Other transport datasets remain outside this V1 page.",
            "航空公司客运、货运、机队与航线事件信号，以及港铁客运需求。其他交通数据暂不纳入此 V1 页面。",
        ),
    )

    cathay = frame_for_dataset(artifact, "cathay_history")
    cathay_fleet = frame_for_dataset(artifact, "cathay_fleet_total_history")
    mtr = frame_for_dataset(artifact, "mtr_history")
    airline_passengers = frame_for_dataset(artifact, "china_airline_passengers_history")
    airline_load_factor = frame_for_dataset(artifact, "china_airline_load_factor_history")

    hk_airline_tab, china_airline_tab, mtr_tab = st.tabs(
        [
            tr(language, "Hong Kong airline · Cathay", "香港航空 · 国泰"),
            tr(language, "China listed airlines", "中国上市航司"),
            tr(language, "MTR", "港铁"),
        ]
    )

    with hk_airline_tab:
        section_heading(
            language,
            "Hong Kong airline",
            "香港航空",
            "Cathay Group operating signals and Hong Kong International Airport demand context.",
            "国泰集团运营信号，以及香港国际机场需求背景。",
        )
        cathay_cards = [
            (
                tr(language, "Cathay passengers (m)", "国泰航空客运量（百万）"),
                latest_period_signal(cathay, "date", "cathay_passengers"),
                "number",
                "pct",
                "million",
            ),
            (
                tr(language, "Cathay load factor", "国泰航空客座率"),
                latest_period_signal(cathay, "date", "cathay_passenger_load_factor_pct", aggregation="mean", change_mode="delta"),
                "percent",
                "delta",
                None,
            ),
            (
                tr(language, "HKIA passengers (m)", "香港机场客运量（百万）"),
                latest_period_signal(cathay, "date", "hkia_passengers"),
                "number",
                "pct",
                "million",
            ),
            (
                tr(language, "HKIA movements", "香港机场飞机升降量"),
                latest_period_signal(cathay, "date", "hkia_aircraft_movements"),
                "number",
                "pct",
                None,
            ),
        ]
        columns = st.columns(len(cathay_cards))
        for column, (label, signal, fmt, change_mode, volume_unit) in zip(columns, cathay_cards):
            render_transport_metric(
                column,
                label,
                signal,
                fmt,
                language=language,
                change_mode=change_mode,
                volume_unit=volume_unit,
            )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "cathay_passengers_chart", language, window,
                views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
            )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "cathay_load_factor_chart", language, window,
                    views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
                )
        with right:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "cathay_capacity_demand_chart", language, window,
                    views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
                )
        section_heading(
            language,
            "Cathay cargo, flight operations and fleet",
            "国泰货运、航班运营与机队",
            "Cargo tonnage, freight load factor, reported flight sectors and official report-period fleet totals. Fleet is semiannual/annual and is not interpolated to monthly frequency.",
            "货运量、货运载运率、公告航班架次／航段，以及官方报告期末机队总数。机队为半年／年度频率，不插值成月度数据。",
        )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "cathay_cargo_tonnage_chart", language, window,
                    views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
                )
        with right:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "cathay_freight_load_factor_chart", language, window,
                    views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
                )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "cathay_cargo_capacity_demand_chart", language, window,
                    views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
                )
        with right:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "cathay_flight_sectors_chart", language, window,
                    views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
                )
        if not cathay_fleet.empty:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "cathay_fleet_total_chart", language, window,
                    views=("Level",), periods_per_year=2, height=390,
                    series_label_map=(
                        {
                            "Company": "国泰航空公司",
                            "HK Express": "香港快运",
                            "Air Hong Kong": "国泰航空货运（Air Hong Kong）",
                            "Grand total": "集团合计",
                        }
                        if language == "zh"
                        else None
                    ),
                )
        st.caption(
            tr(
                language,
                "Cathay cargo metrics are Cathay Group disclosures. HKIA freight tonnage shown in the airport context series is airport-wide and should not be read as Cathay cargo.",
                "国泰货运指标来自国泰集团公告；机场背景图中的香港国际机场货运量是全机场合计，不应解读为国泰货运量。",
            )
        )

    with china_airline_tab:
        section_heading(
            language,
            "China listed airlines",
            "中国上市航空公司",
            "All six available listed groups are selected by default; deselect only when comparing a smaller peer set.",
            "默认显示六家上市航司集团；只有需要缩小同业组时才取消选择。",
        )
        china_series_labels = CHINA_AIRLINE_SERIES_LABELS_ZH if language == "zh" else CHINA_AIRLINE_SERIES_LABELS
        selected_airlines = series_options(
            artifact,
            "china_airline_passengers_chart",
            language,
            series_label_map=china_series_labels,
        )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "china_airline_passengers_chart", language, window,
                series_selection=selected_airlines, views=("Level", "MoM %", "YoY %"),
                periods_per_year=12, height=400, series_label_map=china_series_labels,
            )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "china_airline_ask_chart", language, window,
                    series_selection=selected_airlines, views=("Level", "MoM %", "YoY %"),
                    periods_per_year=12, height=390, series_label_map=china_series_labels,
                )
        with right:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "china_airline_rpk_chart", language, window,
                    series_selection=selected_airlines, views=("Level", "MoM %", "YoY %"),
                    periods_per_year=12, height=390, series_label_map=china_series_labels,
                )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "china_airline_load_factor_chart", language, window,
                series_selection=selected_airlines, views=("Level", "MoM %", "YoY %"),
                periods_per_year=12, height=390, series_label_map=china_series_labels,
            )

        regional_options = selected_airlines or list(CHINA_AIRLINE_SERIES_LABELS)
        regional_display_options = [china_series_labels.get(value, value) for value in regional_options]
        regional_display = st.selectbox(
            tr(language, "Carrier for regional drill-down", "地区客运量查看航司"),
            regional_display_options,
            key="china_airline_regional_carrier",
        )
        regional_airline = dict(zip(regional_display_options, regional_options))[regional_display]
        regional_series = [f"{regional_airline} · {region}" for region in ("Domestic", "International", "Regional")]
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "china_airline_region_by_carrier_chart", language, window,
                series_selection=regional_series, views=("Level", "MoM %", "YoY %"),
                periods_per_year=12, height=410,
                series_label_map=(
                    CHINA_AIRLINE_REGION_SERIES_LABELS_ZH
                    if language == "zh" else CHINA_AIRLINE_REGION_SERIES_LABELS
                ),
            )
            st.caption(
                tr(
                    language,
                    "Regional blanks in the issuer PDF remain missing; an explicit dash is shown as zero. This preserves the difference between undisclosed data and no reported regional traffic.",
                    "公司公告 PDF 中留空的地区数据会保持缺失；明确标示的横线会显示为 0，从而区分未披露数据与没有报告地区客运量。",
                )
            )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "china_airline_region_split_chart", language, window,
                views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
            )
        with st.container(border=True):
            render_table(artifact, labels, "china_airline_latest_snapshot_table", language)

        section_heading(
            language,
            "Cargo operating signals",
            "货运运营信号",
            "Monthly cargo/mail demand and utilization, with issuer units normalized in the shared artifact.",
            "月度货邮需求与运力使用率；来源单位已在共享 artifact 中统一换算。",
        )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "china_airline_cargo_chart", language, window,
                series_selection=selected_airlines, views=("Level", "MoM %", "YoY %"),
                periods_per_year=12, height=400, series_label_map=china_series_labels,
            )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "china_airline_freight_load_factor_chart", language, window,
                series_selection=selected_airlines, views=("Level", "MoM %", "YoY %"),
                periods_per_year=12, height=400, series_label_map=china_series_labels,
            )
            st.caption(
                tr(
                    language,
                    "Spring Airlines has a small number of official freight-load-factor observations above 100%; those source anomalies are retained and not clipped.",
                    "春秋航空少数官方货邮载运率观测超过 100%；这些源数据异常会保留，不会人为截断。",
                )
            )
        with st.container(border=True):
            render_table(
                artifact, labels, "china_airline_cargo_latest_snapshot_table", language,
                value_maps=CHINA_AIRLINE_TABLE_LABELS_ZH if language == "zh" else None,
            )

        section_heading(
            language,
            "Fleet and network events",
            "机队与网络事件",
            "Fleet totals are monthly capacity context; net changes and route counts are disclosed event signals, not interpolated series.",
            "机队总数提供月度运力背景；净变化和航线数量是公告披露的事件信号，不做插值。",
        )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "china_airline_fleet_total_chart", language, window,
                series_selection=selected_airlines, views=("Level", "MoM %", "YoY %"),
                periods_per_year=12, height=420, series_label_map=china_series_labels,
            )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "china_airline_fleet_net_change_chart", language, window,
                    series_selection=selected_airlines, views=("Level", "MoM %"),
                    periods_per_year=12, height=390, series_label_map=china_series_labels,
                )
        with right:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "china_airline_new_route_chart", language, window,
                    series_selection=selected_airlines, views=("Level", "MoM %"),
                    periods_per_year=12, height=390, series_label_map=china_series_labels,
                )
        with st.container(border=True):
            render_table(
                artifact, labels, "china_airline_operating_events_latest_table", language,
                value_maps=CHINA_AIRLINE_TABLE_LABELS_ZH if language == "zh" else None,
            )

        render_airline_h1_backtest(artifact, labels, language)

    with mtr_tab:
        section_heading(
            language,
            "MTR",
            "港铁",
            "Long-run patronage plus service-level demand context.",
            "长期客运量历史及服务类型需求背景。",
        )
        mtr_cards = [
            (
                tr(language, "Total patronage (m)", "总客运量（百万）"),
                latest_period_signal(mtr, "date", "total_mtr_patronage_thousands"),
                "number", "pct", "million_from_thousands",
            ),
            (
                tr(language, "Domestic service (m)", "本地服务（百万）"),
                latest_period_signal(mtr, "date", "domestic_service_thousands"),
                "number", "pct", "million_from_thousands",
            ),
            (
                tr(language, "Cross-boundary (m)", "跨境服务（百万）"),
                latest_period_signal(mtr, "date", "cross_boundary_thousands"),
                "number", "pct", "million_from_thousands",
            ),
            (
                tr(language, "HSR (m)", "高铁（百万）"),
                latest_period_signal(mtr, "date", "hsr_thousands"),
                "number", "pct", "million_from_thousands",
            ),
        ]
        columns = st.columns(len(mtr_cards))
        for column, (label, signal, fmt, change_mode, volume_unit) in zip(columns, mtr_cards):
            render_transport_metric(
                column, label, signal, fmt, language=language,
                change_mode=change_mode, volume_unit=volume_unit,
            )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "mtr_total_patronage_chart", language, window,
                views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=420,
            )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "mtr_service_breakdown_chart", language, window,
                views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=420,
                series_label_map=MTR_SERIES_LABELS_ZH if language == "zh" else MTR_SERIES_LABELS,
            )

    render_source_coverage({"transport": artifact}, {"transport": labels}, language)


def render_transport(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    """Render the deliberately narrow V1 transport page: airlines plus MTR."""
    render_header(
        artifact,
        labels,
        language,
        "transport",
        title_override=tr(language, "Hong Kong Transport & Aviation", "香港交通与航空"),
        description_override=tr(
            language,
            "Company-level airline passenger, cargo, fleet and network-event signals plus MTR passenger demand. Other transport datasets remain outside this V1 page.",
            "航空公司客运、货运、机队与航线事件信号，以及港铁客运需求。其他交通数据暂不纳入此 V1 页面。",
        ),
    )

    cathay = frame_for_dataset(artifact, "cathay_history")
    mtr = frame_for_dataset(artifact, "mtr_history")
    airline_passengers = frame_for_dataset(artifact, "china_airline_passengers_history")
    airline_load_factor = frame_for_dataset(artifact, "china_airline_load_factor_history")

    section_heading(
        language,
        "Airlines",
        "航空公司",
        "Company-level operating signals: traffic, capacity, demand and load factor.",
        "公司层面的运营信号：客运量、运力、需求和客座率。",
    )
    airline_cards = [
        (
            tr(language, "Cathay passengers (m)", "国泰航空客运量（百万）"),
            latest_period_signal(cathay, "date", "cathay_passengers"),
            "number",
            "pct",
            "million",
        ),
        (
            tr(language, "Cathay load factor", "国泰航空客座率"),
            latest_period_signal(cathay, "date", "cathay_passenger_load_factor_pct", aggregation="mean", change_mode="delta"),
            "percent",
            "delta",
            None,
        ),
        (
            tr(language, "Mainland passengers (m)", "内地客运量（百万）"),
            latest_period_signal(airline_passengers, "date", "value"),
            "number",
            "pct",
            "million_from_thousands",
        ),
        (
            tr(language, "Mainland LF avg", "内地平均客座率"),
            latest_period_signal(airline_load_factor, "date", "value", aggregation="mean", change_mode="delta"),
            "percent",
            "delta",
            None,
        ),
    ]
    columns = st.columns(len(airline_cards))
    for column, (label, signal, fmt, change_mode, volume_unit) in zip(columns, airline_cards):
        render_transport_metric(
            column,
            label,
            signal,
            fmt,
            language=language,
            change_mode=change_mode,
            volume_unit=volume_unit,
        )

    with st.container(border=True):
        st.markdown(
            f'<div class="am-chart-title">{tr(language, "How to read the transport KPIs", "交通 KPI 指标说明")}</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            tr(
                language,
                "Top cards convert passenger counts to millions for readability; charts keep the source units shown in each subtitle.",
                "顶部卡片为了易读性把客运量换算为百万；图表则保留副标题所注明的来源单位。",
            )
        )
        left, right = st.columns(2)
        passengers_note = tr(
            language,
            "Passengers carried during the period; airline source tables may report thousands ('000s).",
            "期间承运的乘客人数；航空公司来源表可能以千人（'000s）报告。",
        )
        mtr_note = tr(
            language,
            "Passenger journeys, not unique people; source tables report thousands ('000s).",
            "乘客人次，不是去重后的乘客人数；来源表以千人次（'000s）报告。",
        )
        with left:
            st.markdown(
                f"**ASK** — {tr(language, 'Available Seat Kilometres: the seat capacity flown by the airline.', '可用座位公里：航空公司实际提供的座位运力。')}"
            )
            st.markdown(
                f"**RPK** — {tr(language, 'Revenue Passenger Kilometres: passenger demand carried, measured by passengers × kilometres flown.', '收入客公里：实际承运的客运需求，以乘客人数乘飞行公里数计算。')}"
            )
            st.markdown(
                f"**{tr(language, 'Load factor', '客座率')}** — {tr(language, 'RPK ÷ ASK; a utilization measure, not a passenger count.', 'RPK ÷ ASK；反映运力使用率，不是乘客人数。')}"
            )
        with right:
            st.markdown(
                f"**{tr(language, 'Passengers', '客运量')}** — {passengers_note}"
            )
            st.markdown(
                f"**{tr(language, 'MTR patronage', '港铁客运量')}** — {mtr_note}"
            )
            st.markdown(
                f"**MoM / YoY** — {tr(language, 'Month-on-month / year-on-year change versus the prior month / same month last year.', '环比／同比：相对于上月／去年同月的变化。')}"
            )

    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "cathay_passengers_chart",
            language,
            window,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=390,
        )
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            render_line_chart(
                artifact,
                labels,
                "cathay_load_factor_chart",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=390,
            )
    with right:
        with st.container(border=True):
            render_line_chart(
                artifact,
                labels,
                "cathay_capacity_demand_chart",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=390,
            )

    section_heading(
        language,
        "Mainland listed airlines",
        "内地上市航空公司",
        "All six available listed groups are selected by default; deselect only when comparing a smaller peer set.",
        "默认显示六家上市航司集团；只有需要缩小同业组时才取消选择。",
    )
    china_series_labels = CHINA_AIRLINE_SERIES_LABELS_ZH if language == "zh" else CHINA_AIRLINE_SERIES_LABELS
    selected_airlines = series_options(
        artifact,
        "china_airline_passengers_chart",
        language,
        series_label_map=china_series_labels,
    )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "china_airline_passengers_chart",
            language,
            window,
            series_selection=selected_airlines,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=400,
            series_label_map=china_series_labels,
        )
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            render_line_chart(
                artifact,
                labels,
                "china_airline_ask_chart",
                language,
                window,
                series_selection=selected_airlines,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=390,
                series_label_map=china_series_labels,
            )
    with right:
        with st.container(border=True):
            render_line_chart(
                artifact,
                labels,
                "china_airline_rpk_chart",
                language,
                window,
                series_selection=selected_airlines,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=390,
                series_label_map=china_series_labels,
            )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "china_airline_load_factor_chart",
            language,
            window,
            series_selection=selected_airlines,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=390,
            series_label_map=china_series_labels,
        )
    mtr_series_labels = MTR_SERIES_LABELS_ZH if language == "zh" else MTR_SERIES_LABELS
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "china_airline_region_split_chart",
            language,
            window,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=390,
        )
    with st.container(border=True):
        render_table(artifact, labels, "china_airline_latest_snapshot_table", language)

    section_heading(
        language,
        "Cargo operating signals",
        "货运运营信号",
        "Monthly cargo/mail demand and utilization, with issuer units normalized in the shared artifact.",
        "月度货邮需求与运力使用率；来源单位已在共享 artifact 中统一换算。",
    )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "china_airline_cargo_chart",
            language,
            window,
            series_selection=selected_airlines,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=400,
            series_label_map=china_series_labels,
        )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "china_airline_freight_load_factor_chart",
            language,
            window,
            series_selection=selected_airlines,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=400,
            series_label_map=china_series_labels,
        )
        st.caption(
            tr(
                language,
                "Spring Airlines has a small number of official freight-load-factor observations above 100%; those source anomalies are retained and not clipped.",
                "春秋航空少数官方货邮载运率观测超过 100%；这些源数据异常会保留，不会人为截断。",
            )
        )
    with st.container(border=True):
        render_table(
            artifact,
            labels,
            "china_airline_cargo_latest_snapshot_table",
            language,
            value_maps=CHINA_AIRLINE_TABLE_LABELS_ZH if language == "zh" else None,
        )

    section_heading(
        language,
        "Fleet and network events",
        "机队与网络事件",
        "Fleet totals are monthly capacity context; net changes and route counts are disclosed event signals, not interpolated series.",
        "机队总数提供月度运力背景；净变化和航线数量是公告披露的事件信号，不做插值。",
    )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "china_airline_fleet_total_chart",
            language,
            window,
            series_selection=selected_airlines,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=420,
            series_label_map=china_series_labels,
        )
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            render_line_chart(
                artifact,
                labels,
                "china_airline_fleet_net_change_chart",
                language,
                window,
                series_selection=selected_airlines,
                views=("Level", "MoM %"),
                periods_per_year=12,
                height=390,
                series_label_map=china_series_labels,
            )
    with right:
        with st.container(border=True):
            render_line_chart(
                artifact,
                labels,
                "china_airline_new_route_chart",
                language,
                window,
                series_selection=selected_airlines,
                views=("Level", "MoM %"),
                periods_per_year=12,
                height=390,
                series_label_map=china_series_labels,
            )
    with st.container(border=True):
        render_table(
            artifact,
            labels,
            "china_airline_operating_events_latest_table",
            language,
            value_maps=CHINA_AIRLINE_TABLE_LABELS_ZH if language == "zh" else None,
        )

    render_airline_h1_backtest(artifact, labels, language)

    section_heading(
        language,
        "MTR",
        "港铁",
        "Long-run patronage plus service-level demand context.",
        "长期客运量历史及服务类型需求背景。",
    )
    mtr_cards = [
        (
            tr(language, "Total patronage (m)", "总客运量（百万）"),
            latest_period_signal(mtr, "date", "total_mtr_patronage_thousands"),
            "number",
            "pct",
            "million_from_thousands",
        ),
        (
            tr(language, "Domestic service (m)", "本地服务（百万）"),
            latest_period_signal(mtr, "date", "domestic_service_thousands"),
            "number",
            "pct",
            "million_from_thousands",
        ),
        (
            tr(language, "Cross-boundary (m)", "跨境服务（百万）"),
            latest_period_signal(mtr, "date", "cross_boundary_thousands"),
            "number",
            "pct",
            "million_from_thousands",
        ),
        (
            tr(language, "HSR (m)", "高铁（百万）"),
            latest_period_signal(mtr, "date", "hsr_thousands"),
            "number",
            "pct",
            "million_from_thousands",
        ),
    ]
    columns = st.columns(len(mtr_cards))
    for column, (label, signal, fmt, change_mode, volume_unit) in zip(columns, mtr_cards):
        render_transport_metric(
            column,
            label,
            signal,
            fmt,
            language=language,
            change_mode=change_mode,
            volume_unit=volume_unit,
        )

    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "mtr_total_patronage_chart",
            language,
            window,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=420,
        )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "mtr_service_breakdown_chart",
            language,
            window,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=420,
            series_label_map=mtr_series_labels,
        )

    render_source_coverage({"transport": artifact}, {"transport": labels}, language)


def crypto_metric_delta(signal: dict[str, Any]) -> str | None:
    change = signal.get("change")
    if change is None:
        return None
    if abs(change) < 0.05:
        change = 0.0
    return f"{change:+,.1f}% YoY"


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


def render_crypto_policy_pulse(
    artifact: dict[str, Any],
    labels: dict[str, Any],
    language: str,
) -> None:
    """Render official Hong Kong crypto policy facts separately from forecasts."""
    section_heading(
        language,
        "Hong Kong regulatory & policy pulse",
        "香港监管与政策脉搏",
        "Official HKMA and SFC registers provide the status layer; the news pulse shows regulatory activity, not market sentiment.",
        "金管局和证监会官方登记册提供状态层；新闻脉搏反映监管活动度，不代表市场情绪。",
    )

    kpi = latest_row(frame_for_dataset(artifact, "market_kpi_summary"))
    status_metrics = (
        ("hkma_count", "hkma_issuers", "number", tr(language, "HKMA stablecoin issuers", "金管局稳定币发行人")),
        ("sfc_licensed_count", "sfc_vatps", "number", tr(language, "SFC licensed VATPs", "证监会持牌 VATP")),
        ("sfc_pending_count", "sfc_vatps", "number", tr(language, "SFC pending VATPs", "证监会申请中 VATP")),
    )
    register_available = any(
        not frame_for_dataset(artifact, dataset_id).empty
        for _, dataset_id, _, _ in status_metrics
    )
    with st.container(border=True):
        columns = st.columns(len(status_metrics))
        for column, (field, dataset_id, fmt, label) in zip(columns, status_metrics):
            with column:
                register_rows = frame_for_dataset(artifact, dataset_id)
                value = format_metric(kpi.get(field), fmt) if not register_rows.empty else "—"
                st.metric(label, value)
                st.caption(
                    tr(language, "Current register snapshot", "当前登记册快照")
                    if value != "—"
                    else tr(
                        language,
                        "Register unavailable in this artifact build",
                        "本次 artifact 构建没有可用登记册记录",
                    )
                )
    if not register_available:
        st.caption(
            tr(
                language,
                "A blank status is different from zero: the latest local build did not contain register rows, so no licensing count is inferred.",
                "空白状态不等于零：最新本地构建没有登记册记录，因此不推断持牌数量。",
            )
        )

    news = frame_for_dataset(artifact, "regulatory_news").copy()
    if news.empty or "issue_date" not in news.columns:
        st.info(tr(language, "No official regulatory news is available.", "没有可用的官方监管新闻。"))
    else:
        news["_date"] = pd.to_datetime(news["issue_date"], errors="coerce")
        news = news.dropna(subset=["_date"]).sort_values("_date", ascending=False).copy()
        latest_news_date = news["_date"].max()
        recent = news[news["_date"] >= latest_news_date - pd.Timedelta(days=90)]
        source_counts = recent["source"].astype(str).str.upper().value_counts()
        source_cards = (
            ("HKMA", tr(language, "HKMA releases", "金管局新闻")),
            ("SFC", tr(language, "SFC releases", "证监会新闻")),
            ("__total__", tr(language, "Official releases", "官方新闻合计")),
        )
        with st.container(border=True):
            columns = st.columns(len(source_cards))
            for column, (source, label) in zip(columns, source_cards):
                with column:
                    count = len(recent) if source == "__total__" else int(source_counts.get(source, 0))
                    st.metric(label, f"{count:,}")
                    st.caption(
                        tr(
                            language,
                            f"Trailing 90 days through {latest_news_date:%d %b %Y}",
                            f"截至 {latest_news_date.year}年{latest_news_date.month}月{latest_news_date.day}日的最近90日",
                        )
                    )

        monthly = news.assign(month=news["_date"].dt.to_period("M").dt.to_timestamp())
        monthly["source_display"] = monthly["source"].astype(str).str.upper().map(
            {
                "HKMA": tr(language, "HKMA", "金管局"),
                "SFC": tr(language, "SFC", "证监会"),
            }
        ).fillna(monthly["source"].astype(str).str.upper())
        monthly = (
            monthly.groupby(["month", "source_display"], as_index=False)
            .size()
            .rename(columns={"size": "count"})
            .sort_values("month")
        )
        st.markdown(
            f'<div class="am-chart-title">{tr(language, "Official regulatory news activity", "官方监管新闻活动度")}</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            tr(
                language,
                "Monthly count of crypto-relevant HKMA and SFC releases retained by the artifact; this is an activity count, not a policy score.",
                "artifact 保留的金管局及证监会加密相关新闻月度数量；这是活动度统计，不是政策评分。",
            )
        )
        fig = px.bar(
            monthly,
            x="month",
            y="count",
            color="source_display",
            barmode="stack",
            color_discrete_sequence=PALETTE,
        )
        fig.update_xaxes(title=None, tickformat="%b %Y")
        fig.update_yaxes(title=tr(language, "Official releases", "官方新闻数"), dtick=1)
        for trace in fig.data:
            trace.hovertemplate = f"<b>%{{x|%b %Y}}</b><br>{trace.name}: %{{y:,.0f}}<extra></extra>"
        fig = chart_theme(fig, date_axis=True, height=370)
        st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})

    section_heading(
        language,
        "Policy timeline",
        "政策时间线",
        "The table is an official-source timeline, not a media sentiment feed.",
        "以下是官方来源时间线，不是媒体情绪新闻流。",
    )
    with st.container(border=True):
        render_table(artifact, labels, "regulatory_news_table", language)

    with st.expander(
        tr(language, "Market expectations — separate from official policy facts", "市场预期——与官方政策事实分开"),
        expanded=False,
    ):
        st.caption(
            tr(
                language,
                "Polymarket probabilities are prediction-market observations, not HKMA or SFC positions.",
                "Polymarket 概率是预测市场观察值，不代表金管局或证监会立场。",
            )
        )
        render_table(artifact, labels, "polymarket_table", language)

    with st.expander(tr(language, "Company disclosures on HKEXnews", "港交所披露易公司公告"), expanded=False):
        st.caption(
            tr(
                language,
                "Recent announcements from the tracked Hong Kong crypto/stablecoin company watchlist; these are company disclosures, not regulatory decisions.",
                "香港加密／稳定币观察名单公司的近期公告；这是公司披露，不是监管决定。",
            )
        )
        render_table(artifact, labels, "hkexnews_announcements_table", language)


def render_crypto(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    """Render V1 as global crypto context plus an official HK policy pulse.

    Local adoption and on-chain Hong Kong activity remain outside this first
    page until a recurring data series is validated.
    """
    render_header(
        artifact,
        labels,
        language,
        "crypto",
        title_override=tr(language, "Global Crypto Market Context", "全球加密市场背景"),
        description_override=tr(
            language,
            "V1 combines global stablecoin liquidity, decentralized-exchange activity and crypto sentiment with an official Hong Kong regulatory and policy pulse. Local adoption signals remain a later data track.",
            "V1 结合全球稳定币流动性、去中心化交易所活动、加密市场情绪，以及香港官方监管与政策脉搏。本地采用度信号待后续数据验证后接入。",
        ),
    )

    stablecoin = frame_for_dataset(artifact, "stablecoin_history")
    dex_volume = frame_for_dataset(artifact, "dex_volume_history")
    fear_greed = frame_for_dataset(artifact, "fear_greed_history")
    fear_greed_daily = frame_for_dataset(artifact, "fear_greed_daily")

    section_heading(
        language,
        "Global market pulse",
        "全球市场脉搏",
        "Stablecoin supply and DEX volume remain monthly long-history series; Fear & Greed also has a daily research view below.",
        "稳定币供应量及 DEX 交易量保留月度长期序列；下方另提供恐惧与贪婪的日度研究视图。",
    )
    stablecoin_signal = latest_period_signal(stablecoin, "date", "circulating_usd_bn", aggregation="mean")
    dex_signal = latest_period_signal(dex_volume, "date", "dex_volume_usd_bn", aggregation="mean")
    fear_greed_signal = latest_period_signal(fear_greed, "date", "score", aggregation="mean")
    daily_fear_greed_signal = latest_daily_signal(fear_greed_daily, "score")
    rolling_fear_greed_signal = latest_daily_signal(fear_greed_daily, "score_7d_avg")
    if daily_fear_greed_signal["value"] is None:
        daily_fear_greed_signal = fear_greed_signal
    cards = [
        (
            tr(language, "Stablecoin supply ($B)", "稳定币供应量（十亿美元）"),
            stablecoin_signal,
            "number",
            tr(language, "Monthly average of daily circulating supply", "每日流通供应量月均值"),
            True,
        ),
        (
            tr(language, "DEX volume ($B/day)", "DEX 交易量（十亿美元／日）"),
            dex_signal,
            "number",
            tr(language, "Monthly average daily volume, not monthly total", "月均每日交易量，不是当月总额"),
            True,
        ),
        (
            tr(language, "Fear & Greed daily", "恐惧与贪婪（日度）"),
            daily_fear_greed_signal,
            "number",
            tr(language, "Daily score from 0 (fear) to 100 (greed)", "日度分数，0 代表恐惧，100 代表贪婪"),
            False,
        ),
        (
            tr(language, "Fear & Greed 7-day avg", "恐惧与贪婪（7日均值）"),
            rolling_fear_greed_signal,
            "number",
            tr(language, "Trailing seven-calendar-day average", "最近七个日历日的滚动平均"),
            False,
        ),
    ]
    columns = st.columns(len(cards))
    for column, (label, signal, fmt, note, show_delta) in zip(columns, cards):
        with column:
            st.metric(
                label,
                format_metric(signal.get("value"), fmt),
                delta=crypto_metric_delta(signal) if show_delta else None,
            )
            st.caption(f"{note} · {observation_date_label(signal.get('date'), language)}")

    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "stablecoin_history_chart",
            language,
            window,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=430,
        )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "dex_volume_history_chart",
            language,
            window,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=430,
        )
    with st.container(border=True):
        render_fear_greed_daily_chart(artifact, language, window)
    with st.container(border=True):
        st.caption(
            tr(
                language,
                "Long-run monthly average for context.",
                "长期月度平均，用于长期背景比较。",
            )
        )
        st.caption(
            tr(
                language,
                "Reference bands: 0–24 Extreme Fear · 25–49 Fear · 50–74 Greed · 75–100 Extreme Greed.",
                "参考区间：0–24 极度恐惧 · 25–49 恐惧 · 50–74 贪婪 · 75–100 极度贪婪。",
            )
        )
        render_line_chart(
            artifact,
            labels,
            "fear_greed_history_chart",
            language,
            window,
            views=("Level",),
            periods_per_year=12,
            height=430,
            reference_bands=(
                (0, 25, "#ef4444"),
                (25, 50, "#f59e0b"),
                (50, 75, "#84cc16"),
                (75, 100, "#16a34a"),
            ),
        )

    section_heading(
        language,
        "Crypto attention",
        "加密资产关注度",
        "Wikipedia pageviews are an attention proxy, not trading activity. The weekly view separates traffic agents; the monthly view keeps user pageviews by topic page.",
        "Wikipedia 页面访问量是关注度代理，不是交易活动。周度图按流量代理拆分，月度图按主题页面保留用户访问量。",
    )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "wikipedia_crypto_attention_agent_weekly_chart",
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
            "wikipedia_crypto_user_attention_monthly_chart",
            language,
            window,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=430,
            series_label_map=CRYPTO_PAGE_LABELS_ZH if language == "zh" else CRYPTO_PAGE_LABELS,
        )
    st.caption(
        tr(
            language,
            "Coverage: curated English Wikipedia pages for Bitcoin, Ethereum, stablecoins and DeFi. Automated/spider traffic is retained for transparency; use the user series for the cleaner attention signal.",
            "覆盖范围：精选英文 Wikipedia 比特币、以太坊、稳定币及 DeFi 页面。自动化程序和爬虫流量为透明度而保留；如需较干净的关注度信号，应优先查看用户序列。",
        )
    )

    with st.container(border=True):
        st.markdown(
            f'<div class="am-chart-title">{tr(language, "V1 scope note", "V1 范围说明")}</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            tr(
                language,
                "These global indicators are not Hong Kong trading-volume or stablecoin-adoption measures. The official HKMA/SFC policy layer below is a separate fact stream; HKEX ETF activity and local on-chain metrics remain separate data tracks.",
                "这些全球指标不代表香港交易量或本地稳定币采用度。下方的金管局／证监会政策层是独立的事实流；港交所 ETF 活动及本地链上指标仍是独立数据路径。",
            )
        )

    render_crypto_policy_pulse(artifact, labels, language)
    render_source_coverage({"crypto": artifact}, {"crypto": labels}, language)


def render_source_coverage(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    language: str,
) -> None:
    section_heading(language, "Source & coverage", "来源与覆盖范围", "Build-time lineage and observation dates stay visible.", "保留构建时来源链路和观察日期。")
    rows: list[dict[str, Any]] = []
    source_links: list[tuple[str, str, str]] = []
    for sector_key, artifact in artifacts.items():
        sector_name = SECTORS[sector_key]["name_en"] if language == "en" else SECTORS[sector_key]["name_zh"]
        label_artifact = labels.get(sector_key, artifact)
        health = source_health_frame(label_artifact)
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
        for source in label_artifact.get("sources", []):
            source_links.append((sector_name, source.get("label", source.get("id", "")), source.get("href", "")))
    if rows:
        health_frame = pd.DataFrame(rows)
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
        sector_name = SECTORS[sector_key]["name_en"] if language == "en" else SECTORS[sector_key]["name_zh"]
        for dataset_id, rows in artifact.get("snapshot", {}).get("datasets", {}).items():
            options.append((f"{sector_key}:{dataset_id}", f"{sector_name} · {dataset_id} · {len(rows):,} rows", sector_key))
    return options


def render_data_explorer(artifacts: dict[str, dict[str, Any]], language: str) -> None:
    st.markdown(f'<div class="am-page-title">{tr(language, "Data Explorer", "数据探索器")}</div>', unsafe_allow_html=True)
    st.caption(tr(language, "Inspect the actual rows behind the five connected V1 sectors.", "查看目前已接入的五个 V1 板块的实际数据行。"))
    options = combined_dataset_index(artifacts, language)
    labels = [label for _, label, _ in options]
    selected_label = st.selectbox(tr(language, "Dataset", "数据集"), labels)
    selected_id, _, sector_key = next(item for item in options if item[1] == selected_label)
    dataset_id = selected_id.split(":", 1)[1]
    frame = frame_for_dataset(artifacts[sector_key], dataset_id)
    st.markdown(f'<div class="am-meta">{tr(language, "Read-only local snapshot", "只读本地数据快照")} · {len(frame):,} rows · {dataset_id}</div>', unsafe_allow_html=True)
    if frame.empty:
        st.info(tr(language, "This dataset is empty.", "这个数据集为空。"))
        return
    date_field = next((field for field in ["date", "observation_date", "month", "period", "quarter", "academic_year"] if field in frame.columns), None)
    if date_field:
        ordered = add_date_column(frame, date_field)
        if not ordered.empty:
            st.caption(f"{tr(language, 'Coverage', '覆盖范围')}: {ordered['_date'].min():%d %b %Y} – {ordered['_date'].max():%d %b %Y}")
    st.dataframe(frame, hide_index=True, width="stretch")


def _market_price_frame(datasets: dict[str, Any]) -> pd.DataFrame:
    """Daily index closes from the artifact, typed and sorted."""
    rows = datasets.get("index_price_daily_tail", [])
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if "date" not in frame.columns or "close" not in frame.columns:
        return pd.DataFrame()
    frame["_date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame.dropna(subset=["_date", "close"]).sort_values("_date")


def _market_label(technical_row: pd.Series, language: str) -> str:
    """Return the bilingual label for an exposure row."""
    if language == "zh":
        zh = technical_row.get("label_zh")
        if pd.notna(zh) and str(zh).strip():
            return str(zh)
    return str(technical_row.get("label", ""))


def _market_etf_price_frame(datasets: dict[str, Any]) -> pd.DataFrame:
    """Daily ETF closes from the artifact, typed and sorted."""
    rows = datasets.get("etf_price_daily_tail", [])
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if "date" not in frame.columns or "close" not in frame.columns:
        return pd.DataFrame()
    frame["_date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame.dropna(subset=["_date", "close"]).sort_values("_date")


def _market_pair_history_frame(datasets: dict[str, Any]) -> pd.DataFrame:
    """Relative-pair ratio history from the artifact, typed and sorted."""
    rows = datasets.get("relative_pair_history", [])
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if "date" not in frame.columns or "ratio" not in frame.columns:
        return pd.DataFrame()
    frame["_date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ("ratio", "ratio_ma", "zscore"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["_date", "ratio"]).sort_values("_date")


def _pair_label(row: pd.Series, language: str) -> str:
    if language == "zh":
        zh = row.get("label_zh")
        if pd.notna(zh) and str(zh).strip():
            return str(zh)
    return str(row.get("label", row.get("pair_id", "")))


REGION_NAMES = {
    "China": ("China A-shares", "A股"),
    "HK": ("Hong Kong", "港股"),
    "US": ("United States", "美股"),
    "Cross": ("Cross-region", "跨区域"),
}


def render_relative_regime(
    summary: pd.DataFrame,
    history: pd.DataFrame,
    language: str,
    history_window_name: str,
) -> None:
    """One pair at a time: the ratio, its 60D trend, and its z-score.

    Replaces a bar chart of one z-score per pair. That chart could not say
    whether -0.3 was the end of a year-long slide or the end of a bounce,
    which is most of what a relative-strength reading is for.
    """
    frame = summary.copy()
    frame["_label"] = frame.apply(lambda row: _pair_label(row, language), axis=1)
    regions = [r for r in ("China", "HK", "US", "Cross") if r in set(frame.get("region", pd.Series(dtype=str)))]
    if not regions:
        regions = sorted(set(frame.get("region", pd.Series(dtype=str)).dropna()))

    if hasattr(st, "segmented_control"):
        region_choice = st.segmented_control(
            tr(language, "Market", "市场"),
            regions,
            default=regions[0] if regions else None,
            key="market_pair_region",
            format_func=lambda r: tr(language, *REGION_NAMES.get(r, (r, r))),
            label_visibility="collapsed",
        ) or (regions[0] if regions else None)
    elif hasattr(st, "pills"):
        region_choice = st.pills(
            tr(language, "Market", "市场"),
            regions,
            default=regions[0] if regions else None,
            key="market_pair_region",
            format_func=lambda r: tr(language, *REGION_NAMES.get(r, (r, r))),
            label_visibility="collapsed",
        ) or (regions[0] if regions else None)
    else:
        region_choice = st.radio(
            tr(language, "Market", "市场"),
            regions,
            horizontal=True,
            key="market_pair_region",
            format_func=lambda r: tr(language, *REGION_NAMES.get(r, (r, r))),
        )
    cohort = frame[frame["region"].eq(region_choice)]
    if cohort.empty:
        return

    # Scoreboard first: every pair in the region at a glance, then one chart.
    columns = st.columns(min(4, len(cohort)))
    for column, (_, row) in zip(columns, cohort.iterrows()):
        zscore = row.get("zscore")
        display = "—" if zscore is None or pd.isna(zscore) else f"{float(zscore):+.2f}"
        trend = row.get("trend")
        delta = None if trend in (None, "") or pd.isna(trend) else (
            tr(language, "above 60D mean", "高于60日均值") if trend == "UP"
            else tr(language, "below 60D mean", "低于60日均值")
        )
        column.metric(
            row["_label"],
            display,
            delta,
            delta_color="normal" if trend == "UP" else ("inverse" if trend == "DOWN" else "off"),
            help=tr(language, "z-score of the ratio vs its trailing year", "比值相对过去一年的 z-score"),
        )

    selected_label = st.selectbox(
        tr(language, "Pair", "配对"),
        cohort["_label"].tolist(),
        key="market_pair_select",
    )
    row = cohort[cohort["_label"].eq(selected_label)].iloc[0]
    pair_id = str(row["pair_id"])
    series = history[history["pair_id"].eq(pair_id)] if not history.empty else pd.DataFrame()
    if series.empty:
        st.info(tr(language, "No ratio history in the current snapshot.", "当前快照未包含该比值历史。"))
        return

    windowed, coverage = history_window(series, "date", history_window_name)
    if windowed.empty:
        return

    has_z = "zscore" in windowed.columns and windowed["zscore"].notna().any()
    rows_count = 2 if has_z else 1
    fig = make_subplots(
        rows=rows_count, cols=1, shared_xaxes=True, vertical_spacing=0.06,
        row_heights=[0.68, 0.32] if has_z else [1.0],
    )
    numerator = tr(language, "numerator", "分子")
    denominator = tr(language, "denominator", "分母")
    fig.add_trace(
        go.Scatter(
            x=windowed["_date"], y=windowed["ratio"], mode="lines",
            name=tr(language, "Ratio", "比值"), line=dict(width=1.8),
            hovertemplate=tr(language, "Ratio", "比值") + ": %{y:.3f}<extra></extra>",
        ),
        row=1, col=1,
    )
    if "ratio_ma" in windowed.columns and windowed["ratio_ma"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=windowed["_date"], y=windowed["ratio_ma"], mode="lines",
                name=tr(language, "60D mean", "60日均值"), line=dict(width=1.0),
                hovertemplate=tr(language, "60D mean", "60日均值") + ": %{y:.3f}<extra></extra>",
            ),
            row=1, col=1,
        )
    fig.update_yaxes(title=tr(language, "Ratio (rebased)", "比值（归一）"), row=1, col=1)

    if has_z:
        fig.add_trace(
            go.Scatter(
                x=windowed["_date"], y=windowed["zscore"], mode="lines",
                name="z", line=dict(width=1.4),
                hovertemplate="z: %{y:+.2f}<extra></extra>",
            ),
            row=2, col=1,
        )
        fig.add_hrect(y0=1.0, y1=4.0, fillcolor="#10B981", opacity=0.06, line_width=0, row=2, col=1)
        fig.add_hrect(y0=-4.0, y1=-1.0, fillcolor="#EF4444", opacity=0.06, line_width=0, row=2, col=1)
        for level in (-1.0, 0.0, 1.0):
            fig.add_hline(y=level, line_dash="dot", line_color="#D1D5DB", line_width=0.5, row=2, col=1)
        fig.update_yaxes(title=tr(language, "z-score (1Y)", "z-score（1年）"), row=2, col=1)

    tick_format = date_tick_format(windowed["_date"])
    fig.update_xaxes(
        title=None, tickformat=tick_format,
        hoverformat=date_hover_format(windowed["_date"]),
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikethickness=1, spikedash="dot", spikecolor="#9CA3AF",
    )
    fig.update_layout(hovermode="x unified", hoverlabel=dict(namelength=-1),
                      spikedistance=-1, hoverdistance=100)

    left = str(row.get("left", "")).replace("+", " + ")
    right = str(row.get("right", "")).replace("+", " + ")
    st.markdown(
        f'<div class="am-chart-title">{escape(selected_label)} — '
        f'{escape(left)} / {escape(right)}</div>',
        unsafe_allow_html=True,
    )
    regime_text = str(row.get("regime_zh" if language == "zh" else "regime", ""))
    st.caption(
        " · ".join(
            part for part in (
                coverage,
                regime_text,
                tr(language, f"rising = {numerator} outperforming", f"上行 = {numerator}跑赢"),
            ) if part
        )
    )
    st.plotly_chart(
        chart_theme(fig, "number", date_axis=True, height=440 if has_z else 320),
        width="stretch",
        config={"displaylogo": False, "responsive": True},
    )

    display = cohort.copy()
    
    # 标签优化
    if language == "zh" and "label_zh" in display.columns:
        display["_label_show"] = display["label_zh"]
    else:
        display["_label_show"] = display.get("label", display.get("pair_id"))

    # 组合标的清晰展示: left / right
    display["_pair_show"] = display.apply(lambda r: f"{r.get('left','')} / {r.get('right','')}", axis=1)

    # 当前比值与60日均线
    display["_ratio_show"] = display["ratio"].apply(lambda v: f"{float(v):.4f}" if pd.notna(v) else "—") if "ratio" in display.columns else "—"
    display["_ratio_ma_show"] = display["ratio_ma60"].apply(lambda v: f"{float(v):.4f}" if pd.notna(v) else "—") if "ratio_ma60" in display.columns else "—"

    # Z-Score 格式化
    display["_zscore_show"] = display["zscore"].apply(lambda v: f"{float(v):+.2f}σ" if pd.notna(v) else "—") if "zscore" in display.columns else "—"

    # 动量趋势
    trend_map = {"UP": "▲ 向上占优", "DOWN": "▼ 向下转弱"} if language == "zh" else {"UP": "▲ Bullish", "DOWN": "▼ Bearish"}
    display["_trend_show"] = display["trend"].map(trend_map).fillna(display.get("trend", "—")) if "trend" in display.columns else "—"

    # 当前强弱状态说明
    if language == "zh" and "regime_zh" in display.columns:
        display["_regime_show"] = display["regime_zh"]
    else:
        display["_regime_show"] = display.get("regime", "—")

    col_map_reg_zh = {
        "_label_show": "配置风格对",
        "_pair_show": "底层组合 (分子/分母)",
        "_ratio_show": "当前比值",
        "_ratio_ma_show": "60日均线",
        "_zscore_show": "1年Z-Score",
        "_trend_show": "动量趋势",
        "_regime_show": "相对强弱状态",
    }
    col_map_reg_en = {
        "_label_show": "Style Pair",
        "_pair_show": "Basket (A/B)",
        "_ratio_show": "Ratio",
        "_ratio_ma_show": "60D MA",
        "_zscore_show": "1Y Z-Score",
        "_trend_show": "Trend",
        "_regime_show": "Regime",
    }
    mapping_reg = col_map_reg_zh if language == "zh" else col_map_reg_en
    final_reg_cols = [c for c in mapping_reg.keys() if c in display.columns]
    table_to_show_reg = display[final_reg_cols].rename(columns=mapping_reg)
    st.dataframe(table_to_show_reg, hide_index=True, width="stretch")


def _market_premium_history_frame(datasets: dict[str, Any]) -> pd.DataFrame:
    """Daily premium history from the artifact."""
    rows = datasets.get("premium_history", [])
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if "date" not in frame.columns or "premium_pct" not in frame.columns:
        return pd.DataFrame()
    frame["_date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["premium_pct"] = pd.to_numeric(frame["premium_pct"], errors="coerce")
    return frame.dropna(subset=["_date"]).sort_values("_date")


def _compute_rsi_series(close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder RSI for a close series."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, float("nan"))
    return 100.0 - 100.0 / (1.0 + rs)


def render_market_leadership_chart(
    prices: pd.DataFrame,
    label_by_exposure: dict[str, str],
    language: str,
    history_window_name: str,
) -> None:
    """Every exposure rebased to 100, which is the only way to read leadership.

    Rebasing is anchored to the latest first-observation across the series, not
    to each series' own first point. CSI and S&P 500 histories start days apart
    and run on different trading calendars, so rebasing each to its own start
    would silently hand the later-starting series a different measurement
    period and read as performance.
    """
    windowed, coverage = history_window(prices, "date", history_window_name)
    if windowed.empty:
        st.info(tr(language, "No rows are available for this selection.", "这个选择没有可用数据。"))
        return
    common_start = windowed.groupby("exposure_id")["_date"].min().max()
    aligned = windowed[windowed["_date"] >= common_start].copy()
    if aligned.empty:
        st.info(tr(language, "No overlapping history across exposures.", "各指数没有重叠的历史区间。"))
        return
    base = aligned.sort_values("_date").groupby("exposure_id")["close"].transform("first")
    aligned["_value"] = aligned["close"] / base * 100.0
    aligned["series"] = aligned["exposure_id"].map(label_by_exposure).fillna(aligned["exposure_id"])

    st.markdown(
        f'<div class="am-chart-title">{tr(language, "Relative Performance (rebased to 100)", "相对表现（归一至 100）")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        " · ".join(
            [
                tr(
                    language,
                    f"All exposures rebased at {common_start:%d %b %Y}, the first date every series covers.",
                    f"全部指数以 {common_start:%Y-%m-%d} 归一，该日期是所有序列共同覆盖的最早一天。",
                ),
                tr(
                    language,
                    "CN, HK and US sessions run on different calendars; lines are plotted on their own trading days.",
                    "中国内地、香港与美国的交易日历不同，各线按各自的交易日绘制。",
                ),
                coverage,
            ]
        )
    )
    fig = px.line(
        aligned.sort_values(["series", "_date"]),
        x="_date",
        y="_value",
        color="series",
        color_discrete_sequence=PALETTE,
    )
    fig.add_hline(y=100.0, line_dash="dot", line_color="#9CA3AF", line_width=1)
    fig.update_yaxes(title=tr(language, "Rebased level", "归一水平"))
    fig.update_xaxes(title=None, tickformat="%b %Y")
    apply_line_hover(fig, aligned, "number")
    st.plotly_chart(
        chart_theme(fig, "number", date_axis=True, height=420),
        width="stretch",
        config={"displaylogo": False, "responsive": True},
    )


def render_market_ratio_chart(
    prices: pd.DataFrame,
    technicals: pd.DataFrame,
    language: str,
    history_window_name: str,
) -> None:
    """Reindexed ratio of two exposures: A / B rebased to its own first value."""
    if technicals.empty:
        return

    labels = {}
    for _, row in technicals.iterrows():
        eid = str(row["exposure_id"])
        labels[eid] = _market_label(row, language) if language == "zh" else str(row.get("label", eid))

    eids = sorted(labels.keys())
    col1, col2 = st.columns(2)
    with col1:
        numerator = st.selectbox(
            tr(language, "Numerator (A)", "分子 (A)"),
            eids,
            index=eids.index("csi1000") if "csi1000" in eids else 0,
            key="market_ratio_num",
            format_func=lambda e: labels.get(e, e),
        )
    with col2:
        denominator = st.selectbox(
            tr(language, "Denominator (B)", "分母 (B)"),
            eids,
            index=eids.index("csi300") if "csi300" in eids else min(1, len(eids) - 1),
            key="market_ratio_den",
            format_func=lambda e: labels.get(e, e),
        )
    if numerator == denominator:
        st.caption(tr(language, "Select two different indices to see their ratio.", "选择两个不同指数以查看比值。"))
        return

    left = prices[prices["exposure_id"].eq(numerator)].sort_values("_date").set_index("_date")["close"]
    right = prices[prices["exposure_id"].eq(denominator)].sort_values("_date").set_index("_date")["close"]
    joined = pd.concat([left.rename("a"), right.rename("b")], axis=1, join="inner").dropna()
    if joined.empty:
        st.info(tr(language, "No overlapping history for this pair.", "该配对没有重叠的历史区间。"))
        return

    ratio = (joined["a"] / joined["b"]).dropna()
    if ratio.empty:
        return

    # Use existing history_window via the prices frame approach
    ratio_frame = pd.DataFrame({"date": ratio.index, "ratio": ratio.values})
    ratio_frame["_date"] = pd.to_datetime(ratio_frame["date"])
    windowed, coverage = history_window(ratio_frame, "date", history_window_name)
    if windowed.empty:
        st.info(tr(language, "No rows in this window.", "该时间窗口没有数据。"))
        return
    series = windowed.set_index("_date")["ratio"].dropna()
    if series.empty:
        return

    title = f"{labels.get(numerator, numerator)} / {labels.get(denominator, denominator)}"
    st.markdown(
        f'<div class="am-chart-title">{escape(title)} — {tr(language, "ratio", "比值")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        " · ".join(
            [
                tr(language, "Rising = A outperforming B.", "上升 = A 跑赢 B。"),
                coverage,
            ]
        )
    )

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=series.index, y=series.values, mode="lines", name=title, line=dict(color=PALETTE[0], width=2)))
    ma20 = series.rolling(20).mean()
    ma60 = series.rolling(60).mean()
    fig.add_trace(go.Scatter(x=ma20.index, y=ma20.values, mode="lines", name=tr(language, "20D MA", "20日均线"), line=dict(color=PALETTE[1], width=1, dash="dot")))
    fig.add_trace(go.Scatter(x=ma60.index, y=ma60.values, mode="lines", name=tr(language, "60D MA", "60日均线"), line=dict(color=PALETTE[2], width=1, dash="dash")))
    fig.update_yaxes(title=tr(language, "Ratio", "比值"))
    fig.update_xaxes(title=None, tickformat="%b %Y")
    st.plotly_chart(
        chart_theme(fig, "number", date_axis=True, height=380),
        width="stretch",
        config={"displaylogo": False, "responsive": True},
    )


def render_market_index_detail(
    exposure_id: str,
    label: str,
    prices: pd.DataFrame,
    technicals: pd.DataFrame,
    wrappers: pd.DataFrame,
    language: str,
    history_window_name: str,
    etf_prices: pd.DataFrame | None = None,
    premium_history: pd.DataFrame | None = None,
    rsi_window: int = 14,
    ma_window: int = 20,
    rsi_upper: float = 70.0,
    rsi_lower: float = 30.0,
) -> None:
    """One index: price and RSI on a shared axis, its ETF wrappers, premiums."""
    series = prices[prices["exposure_id"].eq(exposure_id)].sort_values("_date").copy()
    windowed, coverage = history_window(series, "date", history_window_name)

    # --- Metric cards: RSI, MA20, avg premium, drawdown (no MA60) ---
    tech_row = technicals[technicals["exposure_id"].eq(exposure_id)]
    if not tech_row.empty:
        row = tech_row.iloc[0]
        columns = st.columns(4)
        # Name the window the mean was actually taken over. The premium series
        # accumulates one observation per run, so a fresh deployment has a
        # single day of it; labelling that "30D" states a month of averaging
        # that did not happen.
        premium_days = row.get("avg_premium_days")
        premium_days = 0 if premium_days is None or pd.isna(premium_days) else int(premium_days)
        if premium_days <= 1:
            premium_en, premium_zh = "Premium (today)", "溢价（当日）"
        elif premium_days >= 30:
            premium_en, premium_zh = "Avg premium 30D", "平均溢价 30日"
        else:
            premium_en, premium_zh = f"Avg premium {premium_days}D", f"平均溢价 {premium_days}日"
        readings = (
            ("RSI", "RSI", row.get("rsi"), "{:.0f}"),
            ("vs MA20", "相对20日均线", row.get("ma20_pct"), "{:+.2f}%"),
            (premium_en, premium_zh, row.get("avg_premium_30d"), "{:+.2f}%"),
            ("60D drawdown", "60日回撤", row.get("drawdown_60d"), "{:+.2f}%"),
        )
        for column, (en, zh, value, fmt) in zip(columns, readings):
            display = "—" if value is None or pd.isna(value) else fmt.format(float(value))
            column.metric(tr(language, en, zh), display)

    # --- Index price + RSI, one figure, one shared date axis ---
    # Price and RSI used to be two figures. Reading "what was RSI on the day
    # of that drawdown" then meant matching two x-axes by eye; on a shared
    # axis with unified hover the crosshair answers it directly.
    if not windowed.empty:
        tick_format = date_tick_format(windowed["_date"])
        hover_format = date_hover_format(windowed["_date"])

        # RSI is computed on the full series and only then windowed, so the
        # first plotted day already carries its warm-up rather than starting
        # from an undefined average.
        rsi_full = _compute_rsi_series(series.set_index("_date")["close"], window=rsi_window)
        rsi = rsi_full.reindex(windowed["_date"]).dropna()
        has_rsi = not rsi.empty

        rows = 2 if has_rsi else 1
        fig = make_subplots(
            rows=rows,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.06,
            row_heights=[0.72, 0.28] if has_rsi else [1.0],
        )
        ma_label = tr(language, f"MA{ma_window}", f"{ma_window}日均线")
        ma = windowed.set_index("_date")["close"].rolling(ma_window).mean()
        for name, values, width in (
            (tr(language, "Close", "收盘"), windowed.set_index("_date")["close"], 1.8),
            (ma_label, ma, 1.0),
        ):
            fig.add_trace(
                go.Scatter(
                    x=values.index,
                    y=values.values,
                    mode="lines",
                    name=name,
                    line=dict(width=width),
                    hovertemplate=f"{name}: %{{y:,.2f}}<extra></extra>",
                ),
                row=1,
                col=1,
            )
        fig.update_yaxes(title=tr(language, "Index level", "指数点位"), row=1, col=1)

        if has_rsi:
            fig.add_trace(
                go.Scatter(
                    x=rsi.index,
                    y=rsi.values,
                    mode="lines",
                    name=f"RSI({rsi_window})",
                    line=dict(width=1.4),
                    hovertemplate=f"RSI({rsi_window}): %{{y:.1f}}<extra></extra>",
                ),
                row=2,
                col=1,
            )
            fig.add_hrect(y0=rsi_upper, y1=100, fillcolor="#EF4444", opacity=0.06, line_width=0, row=2, col=1)
            fig.add_hrect(y0=0, y1=rsi_lower, fillcolor="#10B981", opacity=0.06, line_width=0, row=2, col=1)
            fig.add_hline(y=rsi_upper, line_dash="dot", line_color="#D1D5DB", line_width=0.5, row=2, col=1)
            fig.add_hline(y=rsi_lower, line_dash="dot", line_color="#D1D5DB", line_width=0.5, row=2, col=1)
            fig.update_yaxes(title="RSI", range=[0, 100], row=2, col=1)

        fig.update_xaxes(title=None, tickformat=tick_format, row=rows, col=1)
        fig.update_layout(hovermode="x unified", hoverlabel=dict(namelength=-1))
        # One crosshair spanning both panels. "across" draws the spike over
        # the whole plotting area rather than only the subplot under the
        # cursor, so reading the RSI at a price move is one glance instead of
        # matching two axes by eye. spikedistance=-1 keeps the line alive
        # anywhere on the row, not only within snapping range of a point.
        fig.update_xaxes(
            hoverformat=hover_format,
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikethickness=1,
            spikedash="dot",
            spikecolor="#9CA3AF",
        )
        fig.update_layout(spikedistance=-1, hoverdistance=100)

        st.markdown(
            f'<div class="am-chart-title">{escape(label)} — '
            f'{tr(language, "price and RSI", "价格与 RSI")}</div>',
            unsafe_allow_html=True,
        )
        st.caption(coverage)
        st.plotly_chart(
            chart_theme(fig, "number", date_axis=True, height=460 if has_rsi else 340),
            width="stretch",
            config={"displaylogo": False, "responsive": True},
        )

    # --- All ETF prices on this index (rebased to 100) ---
    cohort_tickers: list[str] = []
    if wrappers is not None and not wrappers.empty and "exposure_id" in wrappers.columns:
        cohort = wrappers[wrappers["exposure_id"].eq(exposure_id)]
        if not cohort.empty and "ticker" in cohort.columns:
            cohort_tickers = cohort["ticker"].astype(str).str.zfill(6).tolist()

    if etf_prices is not None and not etf_prices.empty and cohort_tickers:
        ep = etf_prices[etf_prices["ticker"].astype(str).str.zfill(6).isin(cohort_tickers)].copy()
        if not ep.empty:
            ep_windowed, ep_cov = history_window(ep, "date", history_window_name)
            if not ep_windowed.empty:
                # Rebase each ETF to 100 at the common first date
                common = ep_windowed.groupby("ticker")["_date"].min().max()
                ep_al = ep_windowed[ep_windowed["_date"] >= common].copy()
                if not ep_al.empty:
                    base = ep_al.sort_values("_date").groupby("ticker")["close"].transform("first")
                    ep_al["_value"] = ep_al["close"] / base * 100.0
                    name_map = {}
                    if not wrappers.empty:
                        for _, w in wrappers[wrappers["exposure_id"].eq(exposure_id)].iterrows():
                            name_map[str(w["ticker"]).zfill(6)] = f"{w['ticker']} {str(w.get('fund_name', ''))[:12]}"
                    ep_al["series"] = ep_al["ticker"].astype(str).str.zfill(6).map(name_map).fillna(ep_al["ticker"])
                    st.markdown(
                        f'<div class="am-chart-title">{escape(label)} — {tr(language, "ETF prices (rebased to 100)", "ETF价格（归一至 100）")}</div>',
                        unsafe_allow_html=True,
                    )
                    st.caption(ep_cov)
                    fig_etf = px.line(
                        ep_al.sort_values(["series", "_date"]),
                        x="_date",
                        y="_value",
                        color="series",
                        color_discrete_sequence=PALETTE,
                    )
                    fig_etf.add_hline(y=100.0, line_dash="dot", line_color="#9CA3AF", line_width=1)
                    fig_etf.update_yaxes(title=tr(language, "Rebased level", "归一水平"))
                    fig_etf.update_xaxes(title=None, tickformat=date_tick_format(ep_al["_date"]))
                    fig_etf.update_xaxes(hoverformat=date_hover_format(ep_al["_date"]))
                    apply_line_hover(fig_etf, ep_al, "number")
                    st.plotly_chart(
                        chart_theme(fig_etf, "number", date_axis=True, height=300),
                        width="stretch",
                        config={"displaylogo": False, "responsive": True},
                    )

    # --- Premium history ---
    if premium_history is not None and not premium_history.empty and cohort_tickers:
        ph = premium_history[premium_history["ticker"].astype(str).str.zfill(6).isin(cohort_tickers)].copy()
        if not ph.empty:
            ph_windowed, ph_cov = history_window(ph, "date", history_window_name)
            if not ph_windowed.empty:
                name_map_ph = {}
                if not wrappers.empty:
                    for _, w in wrappers[wrappers["exposure_id"].eq(exposure_id)].iterrows():
                        name_map_ph[str(w["ticker"]).zfill(6)] = str(w["ticker"])
                ph_windowed["series"] = ph_windowed["ticker"].astype(str).str.zfill(6).map(name_map_ph).fillna(ph_windowed["ticker"])
                st.markdown(
                    f'<div class="am-chart-title">{escape(label)} — {tr(language, "premium history", "溢价历史")}</div>',
                    unsafe_allow_html=True,
                )
                # The series mixes two measurements of the same quantity:
                # published NAV for the history, IOPV for the days NAV has not
                # caught up to. Say which, rather than labelling the whole
                # line with one of them.
                bases = (
                    set(ph_windowed["basis"].dropna().astype(str))
                    if "basis" in ph_windowed.columns
                    else set()
                )
                if bases == {"nav"}:
                    basis_note = tr(language, "Close vs published NAV.", "收盘价对已公布净值。")
                elif bases == {"iopv"}:
                    basis_note = tr(language, "Close vs intraday IOPV.", "收盘价对盘中 IOPV。")
                elif bases:
                    basis_note = tr(
                        language,
                        "Close vs published NAV, with IOPV for the most recent days NAV has not reached.",
                        "收盘价对已公布净值；净值尚未公布的最近几日以 IOPV 补足。",
                    )
                else:
                    basis_note = ""
                st.caption(" · ".join(part for part in (ph_cov, basis_note) if part))
                fig_ph = px.line(
                    ph_windowed.sort_values(["series", "_date"]),
                    x="_date",
                    y="premium_pct",
                    color="series",
                    color_discrete_sequence=PALETTE,
                )
                fig_ph.add_hline(y=0.0, line_dash="dot", line_color="#9CA3AF", line_width=1)
                # A premium only means something against its own history: 7%
                # is cheap for a wrapper that usually trades at 10% and dear
                # for one that usually trades at 3%.
                median_premium = pd.to_numeric(ph_windowed["premium_pct"], errors="coerce").median()
                if pd.notna(median_premium) and len(ph_windowed) >= 20:
                    fig_ph.add_hline(
                        y=float(median_premium),
                        line_dash="dash",
                        line_color="#9CA3AF",
                        line_width=1,
                        annotation_text=tr(language, "cohort median", "同组中位数")
                        + f" {median_premium:+.2f}%",
                        annotation_position="top left",
                        annotation_font_size=10,
                    )
                fig_ph.update_yaxes(title=tr(language, "Premium %", "溢价率 %"))
                fig_ph.update_xaxes(title=None, tickformat=date_tick_format(ph_windowed["_date"]))
                fig_ph.update_xaxes(hoverformat=date_hover_format(ph_windowed["_date"]))
                st.plotly_chart(
                    chart_theme(fig_ph, "number", date_axis=True, height=280),
                    width="stretch",
                    config={"displaylogo": False, "responsive": True},
                )

    # --- ETF wrapper table ---
    if wrappers is None or wrappers.empty or "exposure_id" not in wrappers.columns:
        return
    cohort = wrappers[wrappers["exposure_id"].eq(exposure_id)].copy()
    if cohort.empty:
        return
    st.markdown(
        f'<div class="am-chart-title">{tr(language, "ETF wrappers on this index", "追踪该指数的 ETF")}</div>',
        unsafe_allow_html=True,
    )

    if "peer_rank" in cohort.columns:
        cohort = cohort.sort_values("peer_rank")

    # Format human-readable columns
    display_df = cohort.copy()
    
    # 费率格式化 (如 0.0015 -> 0.15%/年)。管理费 + 托管费，与 hold_score
    # 的计分口径和邮件快报保持一致：单列管理费会把持有成本报低,
    # 日经 225 的 0.20% 实际是 0.25%。
    if "management_fee" in display_df.columns:
        _total_fee = pd.to_numeric(display_df["management_fee"], errors="coerce")
        if "custody_fee" in display_df.columns:
            _total_fee = _total_fee.add(
                pd.to_numeric(display_df["custody_fee"], errors="coerce").fillna(0.0)
            )
        display_df["_fee_display"] = _total_fee.apply(
            lambda v: f"{float(v)*100:.2f}%/年" if pd.notna(v) else "—"
        )
    else:
        display_df["_fee_display"] = "—"
        
    # 溢价率格式化 (如 -0.01 -> -0.01%)
    if "premium_pct" in display_df.columns:
        display_df["_prem_display"] = display_df["premium_pct"].apply(
            lambda v: f"{float(v):+.2f}%" if pd.notna(v) else "—"
        )
    else:
        display_df["_prem_display"] = "—"

    # 同类相对溢价
    if "relative_premium_pct" in display_df.columns:
        display_df["_rel_prem_display"] = display_df["relative_premium_pct"].apply(
            lambda v: f"{float(v):+.2f}%" if pd.notna(v) else "—"
        )
    else:
        display_df["_rel_prem_display"] = "—"

    # 规模格式化 (如 30628289962 -> 306.3 亿)
    if "aum_proxy" in display_df.columns:
        display_df["_aum_display"] = display_df["aum_proxy"].apply(
            lambda v: f"{float(v)/1e8:.1f} 亿元" if pd.notna(v) and float(v) > 0 else "—"
        )
    else:
        display_df["_aum_display"] = "—"

    # 入场成本 (bp)
    if "entry_cost_bp" in display_df.columns:
        display_df["_cost_display"] = display_df["entry_cost_bp"].apply(
            lambda v: f"{float(v):.1f} bp" if pd.notna(v) else "—"
        )
    else:
        display_df["_cost_display"] = "—"

    # 状态翻译与徽章化
    status_map_zh = {
        "ATTRACTIVE": "折价机会 (优先)",
        "FAIR": "估值合理 (正常)",
        "AVOID": "高溢警惕 (慎入)",
        "EXPENSIVE": "偏贵",
    }
    if "entry_status" in display_df.columns:
        if language == "zh":
            display_df["_status_display"] = display_df["entry_status"].map(status_map_zh).fillna(display_df["entry_status"])
        else:
            display_df["_status_display"] = display_df["entry_status"]
    else:
        display_df["_status_display"] = "—"

    # 买入优选排名
    if "peer_rank" in display_df.columns:
        display_df["_rank_display"] = display_df["peer_rank"].apply(
            lambda v: f"#{int(round(v))}" if pd.notna(v) else "—"
        )
    else:
        display_df["_rank_display"] = "—"

    # 列映射定义
    col_mapping_zh = {
        "ticker": "代码",
        "fund_name": "ETF简称",
        "_status_display": "建仓建议",
        "_prem_display": "折溢价率",
        "_rel_prem_display": "同类相对溢价",
        "_fee_display": "总费率",
        "_aum_display": "基金规模",
        "_cost_display": "综合买入成本",
        "_rank_display": "买入优选",
    }
    col_mapping_en = {
        "ticker": "Ticker",
        "fund_name": "Fund Name",
        "_status_display": "Status",
        "_prem_display": "Premium",
        "_rel_prem_display": "Rel Premium",
        "_fee_display": "Total Fee",
        "_aum_display": "AUM",
        "_cost_display": "Entry Cost",
        "_rank_display": "Peer Rank",
    }

    mapping = col_mapping_zh if language == "zh" else col_mapping_en
    final_cols = [c for c in mapping.keys() if c in display_df.columns]
    table_to_show = display_df[final_cols].rename(columns=mapping)

    st.dataframe(table_to_show, hide_index=True, width="stretch")

    if "entry_cost_bp" in cohort.columns and cohort["entry_cost_bp"].notna().any():
        render_market_entry_cost_chart(cohort, language)

    if "premium_caveat" in cohort.columns:
        caveats = [str(x) for x in cohort["premium_caveat"].dropna().unique().tolist() if x]
        if caveats:
            st.caption(" · ".join(caveats))


def render_market_entry_cost_chart(cohort: pd.DataFrame, language: str) -> None:
    """Entry cost & premium per wrapper with clear contextual axis limits."""
    frame = cohort.dropna(subset=["entry_cost_bp"]).copy()
    if frame.empty:
        return
    frame["_label"] = frame.get("ticker", pd.Series(dtype=str)).astype(str)
    if "fund_name" in frame.columns:
        frame["_label"] = frame["_label"] + " " + frame["fund_name"].astype(str).str.slice(0, 16)
    frame = frame.sort_values("entry_cost_bp")

    # Determine colors based on cost/premium
    colors = []
    for _, r in frame.iterrows():
        c = r.get("entry_cost_bp", 0)
        if c < 0:
            colors.append("#16a34a") # green for discount
        elif c > 100:
            colors.append("#dc2626") # red for high premium
        else:
            colors.append("#3b82f6") # blue

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=frame["entry_cost_bp"],
            y=frame["_label"],
            orientation="h",
            marker=dict(color=colors),
            text=[f"{v:.1f} bp ({v/100:+.2f}%)" for v in frame["entry_cost_bp"]],
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>综合入场成本: %{x:.2f} bp<extra></extra>",
        )
    )

    # Smart X-axis range so bars are not squished against 100bp
    min_x = min(frame["entry_cost_bp"].min(), 0) - 5
    max_x = max(frame["entry_cost_bp"].max() * 1.35, 10)
    fig.update_xaxes(
        title=tr(language, "Entry Cost (bp = 0.01%) — Premium + Half-Spread", "综合买入成本 (bp，1bp=0.01%) = 折溢价 + 0.5×买卖价差"),
        range=[min_x, max_x],
        zeroline=True,
        zerolinewidth=1.5,
        zerolinecolor="#94a3b8",
    )
    fig.update_yaxes(title=None, automargin=True)

    st.plotly_chart(
        chart_theme(fig, "number", date_axis=False, height=max(180, 50 * len(frame))),
        width="stretch",
        config={"displaylogo": False, "responsive": True},
    )


def render_us_sector_tab(language: str) -> None:
    """Render US 11 GICS Sectors and pure-play sub-industries from R2 / remote artifact."""
    # ``streamlit run`` puts this script's directory on sys.path; AppTest and
    # any other import path do not, so the tab raised ModuleNotFoundError
    # everywhere except a live server. Resolve the sibling module explicitly.
    app_dir = str(Path(__file__).resolve().parent)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    from remote_us_etf import load_us_sector_artifact

    
    artifact = load_us_sector_artifact()
    sectors = artifact.get("sectors", [])
    sub_map = artifact.get("sub_industries", {})
    as_of = artifact.get("as_of", "—")
    
    if not sectors:
        st.info(tr(language, "US sector data is updating...", "美股行业数据加载中..."))
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
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=10)),
            margin=dict(l=10, r=10, t=30, b=10),
            hovermode="x unified",
        )
        st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})

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
        selected_parent = st.selectbox(
            tr(language, "Select Parent Sector", "选择所属大类行业"),
            sec_names,
            key="us_etf_parent_select",
        )
        
        subs = sub_map.get(selected_parent, [])
        if subs:
            sub_df = pd.DataFrame(subs)
            sub_df["_sub_show"] = sub_df.apply(
                lambda r: f"{r['ticker']} {r.get('name_zh' if language == 'zh' else 'name_en')}", axis=1
            )
            sub_df["_theme_show"] = sub_df.get("sub_industry_zh" if language == "zh" else "sub_industry")
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
    plot[date_col] = pd.to_datetime(plot[date_col], errors="coerce")
    plot = plot.dropna(subset=[date_col]).sort_values(date_col)
    years = HISTORY_WINDOWS.get(window)
    if years:
        cutoff = plot[date_col].max() - pd.DateOffset(years=years)
        plot = plot[plot[date_col] >= cutoff]
    latest = plot.iloc[-1]
    net = pd.to_numeric(pd.Series([latest.get("net_buy_yi")]), errors="coerce").iloc[0]
    mv = pd.to_numeric(pd.Series([latest.get("holding_market_value")]), errors="coerce").iloc[0]
    bal = pd.to_numeric(pd.Series([latest.get("balance_yi")]), errors="coerce").iloc[0]
    asof = pd.Timestamp(latest[date_col]).strftime("%Y-%m-%d")
    c1, c2, c3 = st.columns(3)
    c1.metric(tr(language, "Latest net buy", "最新净买入"), f"{float(net):,.1f} 亿" if pd.notna(net) else "—", asof)
    c2.metric(tr(language, "Holding market value", "持股市值"), f"HK$ {float(mv)/1e12:,.2f}T" if pd.notna(mv) else "—")
    c3.metric(tr(language, "Same-day balance", "当日余额"), f"{float(bal):,.1f} 亿" if pd.notna(bal) else "Unavailable")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=plot[date_col],
            y=pd.to_numeric(plot.get("net_buy_yi"), errors="coerce"),
            name=tr(language, "Net buy (CNY 100m)", "当日净买入（亿元）"),
            marker_color="#93c5fd",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=plot[date_col],
            y=pd.to_numeric(plot.get("holding_market_value"), errors="coerce") / 1e12,
            name=tr(language, "Holding MV (HK$ tn)", "持股市值（万亿）"),
            mode="lines",
            line=dict(width=2.5, color="#2563EB"),
        ),
        secondary_y=True,
    )
    fig.update_layout(template="plotly_white", height=360, legend=dict(orientation="h", y=-0.2), margin=dict(l=0, r=8, t=12, b=40), hovermode="x unified")
    fig.update_xaxes(tickformat="%b %Y", showgrid=False)
    fig.update_yaxes(title_text=tr(language, "Net buy (CNY 100m)", "净买入（亿元）"), secondary_y=False, gridcolor="#F3F4F6")
    fig.update_yaxes(title_text=tr(language, "Holding MV (HK$ tn)", "持股市值（万亿）"), secondary_y=True, showgrid=False)
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})
    st.caption(tr(
        language,
        "Market-wide southbound Stock Connect from Eastmoney/akshare stock_hsgt_hist_em. This is not per-stock 0700.HK ownership.",
        "全市场南向资金来自东财/akshare stock_hsgt_hist_em，不是 0700.HK 个股持股。",
    ))


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
    key_prefix: str = "market",
    show_wrappers: bool = True,
) -> None:
    """Render single-index technical detail and (optionally) domestic ETF wrappers strictly within a scoped list."""
    available = [e for e in label_by_exposure if e in scoped_eids and not prices.empty and e in set(prices["exposure_id"])]
    if not available:
        if not wrappers.empty and show_wrappers:
            available = [e for e in sorted(wrappers["exposure_id"].astype(str).unique()) if e in scoped_eids]
    if not available:
        return

    section_heading(
        language,
        "By Index",
        "按指数查看",
        "Inspect price, 20D/60D trend, and RSI for a selected index.",
        "选择一个指数，查看其收盘价、均线趋势及 RSI 技术指标。",
    )
    
    wrapper_counts = (
        wrappers.groupby("exposure_id").size().to_dict() if not wrappers.empty and show_wrappers else {}
    )
    
    def _fmt_name(e):
        lbl = label_by_exposure.get(e, e)
        if show_wrappers and wrapper_counts.get(e, 0) > 0:
            return f"{lbl} ({wrapper_counts[e]} 只场内ETF)" if language == "zh" else f"{lbl} ({wrapper_counts[e]} ETF)"
        return lbl

    selected = st.selectbox(
        tr(language, "Select Index", "选择指数标的"),
        available,
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
        rsi_window=rsi_window,
        ma_window=ma_window,
        rsi_upper=rsi_upper,
        rsi_lower=rsi_lower,
    )


def render_market(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    """Index & ETF Allocation Monitor: fully modular regional tabs."""
    st.markdown(f'<div class="am-page-title">{tr(language, SECTORS["market"]["name_en"], SECTORS["market"]["name_zh"])}</div>', unsafe_allow_html=True)
    st.caption(tr(language, "Global Multi-Asset & ETF Monitor. Regional segmentation with clean data separation.", "全球多资产与 ETF 监控看板。按地域严格分层，无跨区干扰。"))

    datasets = artifact.get("snapshot", {}).get("datasets", {})

    technicals = pd.DataFrame(datasets.get("exposure_technicals", []))
    regime = datasets.get("relative_regime", [])
    wrappers = pd.DataFrame(datasets.get("wrapper_metrics", []))
    prices = _market_price_frame(datasets)
    etf_prices = _market_etf_price_frame(datasets)
    premium_history = _market_premium_history_frame(datasets)
    pair_summary = pd.DataFrame(datasets.get("relative_pairs", []))
    pair_history = _market_pair_history_frame(datasets)
    southbound = pd.DataFrame(datasets.get("southbound_market_flow", []))

    if technicals.empty and not regime and wrappers.empty:
        st.info(tr(language, "This chart is not available in the current artifact snapshot.", "当前数据快照未包含此图表。"))
        return

    # Bilingual label map
    label_by_exposure: dict[str, str] = {}
    if not technicals.empty and "exposure_id" in technicals.columns:
        for _, row in technicals.iterrows():
            eid = str(row["exposure_id"])
            label_by_exposure[eid] = _market_label(row, language)

    # 采用顶级原生下划线 Tab 栏 (st.tabs) - 按全球大区清晰划分
    tab_china_label = tr(language, "🇨🇳 China & HK", "🇨🇳 泛中国 (A股/港股/出海QDII)")
    tab_us_label = tr(language, "🇺🇸 United States", "🇺🇸 美国市场 (大盘基准/11大行业)")
    tab_apac_label = tr(language, "🌏 APAC ex-CN/HK", "🌏 亚太除中港 (日经/韩国/台湾)")
    tab_emea_label = tr(language, "🌍 EMEA", "🌍 欧洲与中东 (英/德/法/沙特)")
    tab_global_label = tr(language, "🌐 Global & All", "🌐 全球大类基准 / 全部")

    china_tab, us_tab, apac_tab, emea_tab, global_tab = st.tabs([
        tab_china_label, tab_us_label, tab_apac_label, tab_emea_label, tab_global_label
    ])

    china_eids = {
        "csi300", "csi500", "csi1000", "chinext", "growth", "dividend",
        "hsi", "hstech", "hk_dividend", "hk_internet", "hk_midcap", "hk_hshares",
        "cn_infotech", "cn_staples", "sp500", "ndx", "nikkei225", "dax", "saudi",
    }
    china_core_eids = {
        "csi300", "csi500", "csi1000", "chinext", "growth", "dividend",
        "hsi", "hstech", "hk_dividend", "hk_internet", "hk_midcap", "hk_hshares",
        "cn_infotech", "cn_staples",
    }
    us_broad_eids = {"sp500", "ndx", "dow", "russell2000", "us_small", "us_growth", "us_value"}
    apac_eids = {"nikkei225", "kospi", "twii", "kr_semis"}
    emea_eids = {"dax", "ftse100", "cac40", "saudi"}
    global_eids = {"csi300", "sp500", "ndx", "dow", "russell2000", "hsi", "nikkei225", "kospi", "twii", "dax", "ftse100", "cac40", "saudi"}

    def _render_leadership_block(sub_prices, sub_tech, sub_labels, tab_key):
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
                render_market_ratio_chart(sub_prices, sub_tech, language, window)
            else:
                render_market_leadership_chart(sub_prices, sub_labels, language, window)

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
            display_tech["_prem_display"] = display_tech["avg_premium_30d"].apply(
                lambda v: f"{float(v):+.2f}%" if pd.notna(v) else "—"
            ) if "avg_premium_30d" in display_tech.columns else "—"

            col_map_zh = {
                "_label_display": "指数标的",
                "_ma20_display": "相对20日线",
                "_rsi_display": "RSI情绪状态",
                "_dd_display": "60日最大回撤",
                "_prem_display": "挂钩ETF平均溢价(30D)",
            }
            col_map_en = {
                "_label_display": "Index",
                "_ma20_display": "vs MA20",
                "_rsi_display": "RSI Status",
                "_dd_display": "60D Drawdown",
                "_prem_display": "Avg Premium (30D)",
            }
            mapping = col_map_zh if language == "zh" else col_map_en
            final_cols = [c for c in mapping.keys() if c in display_tech.columns]
            table_to_show = display_tech[final_cols].rename(columns=mapping).sort_values(mapping["_label_display"])
            st.dataframe(table_to_show, hide_index=True, width="stretch")

    # ==================== 1. 🇨🇳 泛中国 (A股 / 港股 / QDII出海工具) ====================
    with china_tab:
        sub_cn_prices = prices[prices["exposure_id"].isin(china_core_eids)].copy() if not prices.empty else prices
        sub_cn_tech = technicals[technicals["exposure_id"].isin(china_core_eids)].copy() if not technicals.empty else technicals
        sub_cn_labels = {k: v for k, v in label_by_exposure.items() if k in china_core_eids}
        _render_leadership_block(sub_cn_prices, sub_cn_tech, sub_cn_labels, "china")

        # 港股通南向资金
        if not southbound.empty:
            st.markdown(
                f'<div class="am-chart-title" style="margin-top:24px;">{tr(language, "Southbound Stock Connect Flow", "港股通南向资金全市场流向")}</div>',
                unsafe_allow_html=True,
            )
            render_southbound_market_flow(southbound, language, window)

        # A股与港股风格轮动配对 (Relative Regime)
        if not pair_summary.empty:
            cn_pairs = pair_summary[pair_summary.get("region", "").isin(["China", "HK"])].copy()
            if not cn_pairs.empty:
                section_heading(
                    language,
                    "China & HK Relative Regime",
                    "A股与港股相对风格轮动",
                    "Style pair spreads and rolling 20D/1Y z-score.",
                    "风格轮动价差及滚动 z-score。",
                )
                render_relative_regime(cn_pairs, pair_history, language, window)

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
            key_prefix="china",
            show_wrappers=True,
        )

    # ==================== 2. 🇺🇸 美国市场 (实际指数 + 11大行业与纯度细分) ====================
    with us_tab:
        sub_us_prices = prices[prices["exposure_id"].isin(us_broad_eids)].copy() if not prices.empty else prices
        sub_us_tech = technicals[technicals["exposure_id"].isin(us_broad_eids)].copy() if not technicals.empty else technicals
        sub_us_labels = {k: v for k, v in label_by_exposure.items() if k in us_broad_eids}
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
    with apac_tab:
        sub_apac_prices = prices[prices["exposure_id"].isin(apac_eids)].copy() if not prices.empty else prices
        sub_apac_tech = technicals[technicals["exposure_id"].isin(apac_eids)].copy() if not technicals.empty else technicals
        sub_apac_labels = {k: v for k, v in label_by_exposure.items() if k in apac_eids}
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
    with emea_tab:
        sub_emea_prices = prices[prices["exposure_id"].isin(emea_eids)].copy() if not prices.empty else prices
        sub_emea_tech = technicals[technicals["exposure_id"].isin(emea_eids)].copy() if not technicals.empty else technicals
        sub_emea_labels = {k: v for k, v in label_by_exposure.items() if k in emea_eids}
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
    with global_tab:
        sub_glob_prices = prices[prices["exposure_id"].isin(global_eids)].copy() if not prices.empty else prices
        sub_glob_tech = technicals[technicals["exposure_id"].isin(global_eids)].copy() if not technicals.empty else technicals
        sub_glob_labels = {k: v for k, v in label_by_exposure.items() if k in global_eids}
        _render_leadership_block(sub_glob_prices, sub_glob_tech, sub_glob_labels, "global")

        # 全球宏观跨市场相对强弱 (如 China vs US)
        if not pair_summary.empty:
            cross_pairs = pair_summary[pair_summary.get("region", "").isin(["Cross", "US"])].copy()
            if not cross_pairs.empty:
                section_heading(
                    language,
                    "Cross-Market Relative Regime",
                    "全球宏观跨市场比值",
                    "Cross-market pair spreads and rolling 20D/1Y z-score.",
                    "跨市场资产比值及滚动 z-score。",
                )
                render_relative_regime(cross_pairs, pair_history, language, window)

        # 全量指数单指数详情
        render_scoped_index_section(
            set(label_by_exposure.keys()),
            label_by_exposure,
            prices,
            technicals,
            wrappers,
            language,
            window,
            etf_prices=etf_prices,
            premium_history=premium_history,
            key_prefix="global",
            show_wrappers=True,
        )


def set_app_page(page_key: str) -> None:
    st.session_state["page"] = page_key


def overview_source_summary(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
) -> dict[str, int]:
    total = healthy = attention = problem = 0
    for sector_key, artifact in artifacts.items():
        health = source_health_frame(artifact)
        if health.empty:
            status_values = ["Ready"] * len(labels.get(sector_key, artifact).get("sources", []))
        else:
            status_values = health.get("status", pd.Series(dtype="object")).astype(str).tolist()
        for value in status_values:
            normalized = value.casefold()
            total += 1
            if normalized in {"healthy", "ready", "live", "success"}:
                healthy += 1
            elif normalized in {"partial", "warning", "degraded", "stale"}:
                attention += 1
            else:
                problem += 1
    return {"total": total, "healthy": healthy, "attention": attention, "problem": problem}


def sector_source_status(artifact: dict[str, Any], label_artifact: dict[str, Any], language: str) -> str:
    health = source_health_frame(artifact)
    if health.empty:
        statuses = ["ready"] * len(label_artifact.get("sources", []))
    else:
        statuses = health.get("status", pd.Series(dtype="object")).astype(str).str.casefold().tolist()
    if not statuses:
        return tr(language, "Snapshot", "数据快照")
    if all(value in {"healthy", "ready", "live", "success"} for value in statuses):
        return tr(language, "Ready", "可用")
    if any(value in {"partial", "warning", "degraded", "stale"} for value in statuses):
        return tr(language, "Attention", "需留意")
    return tr(language, "Problem", "有问题")


def latest_artifact_date(artifacts: dict[str, dict[str, Any]], language: str) -> str:
    values = [
        artifact.get("package_info", {}).get("dataAsOf")
        for artifact in artifacts.values()
        if artifact.get("package_info", {}).get("dataAsOf")
    ]
    if not values:
        return "—"
    parsed = [parse_period(value) for value in values]
    parsed = [value for value in parsed if not pd.isna(value)]
    if not parsed:
        return str(max(values))
    return observation_date_label(max(parsed), language)


def render_overview_header(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    language: str,
) -> None:
    summary = overview_source_summary(artifacts, labels)
    latest = latest_artifact_date(artifacts, language)
    status_items = [
        (
            tr(language, "Connected sectors", "已接入板块"),
            f"{len(artifacts)}",
            tr(language, "Detailed pages available", "已有详细板块页面"),
        ),
        (
            tr(language, "Source feeds", "来源数据流"),
            f"{summary['total']}",
            tr(language, "Across current sectors", "覆盖当前板块"),
        ),
        (
            tr(language, "Ready feeds", "可用数据流"),
            f"{summary['healthy']}/{summary['total']}" if summary["total"] else "—",
            tr(language, "Build-validated", "已通过构建验证"),
        ),
        (
            tr(language, "Latest artifact", "最新数据快照"),
            latest,
            tr(language, "Individual metrics have their own dates", "各指标仍保留自己的观察日期"),
        ),
    ]
    cards = "".join(
        f'<div class="am-overview-status-item"><div class="am-overview-status-label">{escape(label)}</div>'
        f'<div class="am-overview-status-value">{escape(value)}</div>'
        f'<div class="am-overview-status-note">{escape(note)}</div></div>'
        for label, value, note in status_items
    )
    st.markdown(f'<div class="am-overview-status">{cards}</div>', unsafe_allow_html=True)


def render_sector_pulse(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    language: str,
) -> None:
    section_heading(
        language,
        "Sector pulse",
        "板块脉搏",
        "A compact reading for each connected sector; open the sector page for full detail.",
        "每个已接入板块只保留一组核心读数；完整细节请进入板块页面。",
    )
    columns = st.columns(2 if len(artifacts) > 1 else 1)
    for index, (sector_key, artifact) in enumerate(artifacts.items()):
        config = OVERVIEW_PULSE_CONFIG.get(sector_key, {})
        sector = SECTORS.get(sector_key, {})
        label_artifact = labels.get(sector_key, artifact)
        name = sector.get("name_zh" if language == "zh" else "name_en", sector_key)
        status = sector_source_status(artifact, label_artifact, language)
        as_of = artifact.get("package_info", {}).get("dataAsOf", "—")
        as_of = observation_date_label(as_of, language)
        metric_blocks: list[str] = []
        for metric in config.get("metrics", ())[:3]:
            if metric.get("series"):
                value, date = latest_series_reading(
                    artifact,
                    metric.get("chart_id", "immd_net_flow_chart"),
                    metric["field"],
                    metric.get("format", "number"),
                    language,
                )
                label = metric["label_zh"] if language == "zh" else metric["label_en"]
            else:
                label, value, date = latest_metric_reading(
                    artifact,
                    metric["dataset"],
                    metric["field"],
                    metric.get("format", "number"),
                    label_en=metric["label_en"],
                    label_zh=metric["label_zh"],
                    language=language,
                )
            if value == "—":
                continue
            metric_blocks.append(
                f'<div class="am-pulse-metric"><div class="am-pulse-label">{escape(label)}</div>'
                f'<div class="am-pulse-value">{escape(value)}</div>'
                f'<div class="am-pulse-asof">{escape(date)}</div></div>'
            )
        sparkline = config.get("sparkline")
        sparkline_markup = ""
        sparkline_context_markup = ""
        if sparkline:
            sparkline_frame, sparkline_title, sparkline_latest, sparkline_range, sparkline_note = sparkline_context(
                artifact,
                sparkline,
                language,
            )
            if not sparkline_frame.empty:
                sparkline_context_markup = (
                    f'<div class="am-pulse-sparkline-title">{escape(sparkline_title)}</div>'
                    f'<div class="am-pulse-sparkline-meta">'
                    f'{escape(tr(language, "Latest", "最新"))} {escape(sparkline_latest)} · '
                    f'{escape(str(len(sparkline_frame)))} '
                    f'{escape(tr(language, "plotted observations", "个观察值"))} · '
                    f'{escape(sparkline_range)}</div>'
                    f'<div class="am-pulse-sparkline-note">{escape(sparkline_note)}</div>'
                )
                sparkline_markup = sparkline_svg(
                    sparkline_frame,
                    color=PALETTE[index % len(PALETTE)],
                )
        with columns[index % len(columns)]:
            with st.container(border=True):
                st.markdown(
                    f'<div class="am-pulse-title">{escape(name)}</div>'
                    f'<div class="am-pulse-meta">{escape(tr(language, "Hong Kong", "香港"))} · '
                    f'{escape(status)} · {escape(tr(language, "artifact through", "数据截至"))} {escape(as_of)}</div>',
                    unsafe_allow_html=True,
                )
                if metric_blocks:
                    st.markdown(
                        f'<div class="am-pulse-metrics">{"".join(metric_blocks)}</div>',
                        unsafe_allow_html=True,
                    )
                if sparkline_markup:
                    st.markdown(f"{sparkline_context_markup}{sparkline_markup}", unsafe_allow_html=True)
                st.button(
                    tr(language, f"Open {sector.get('short_en', name)}", f"打开{sector.get('short_zh', name)}"),
                    key=f"overview_open_{sector_key}",
                    width="stretch",
                    on_click=set_app_page,
                    args=(sector_key,),
                )


def render_featured_trends(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    language: str,
    window: str,
) -> None:
    _ = (artifacts, labels, window)
    section_heading(
        language,
        "Featured trends",
        "精选走势",
        "Reserved for higher-frequency derived signals after data ingestion and validation.",
        "待高频数据接入及派生信号验证后再展示。",
    )
    if not OVERVIEW_FEATURED_CHARTS:
        return
    columns = st.columns(2)
    for index, chart in enumerate(OVERVIEW_FEATURED_CHARTS[:2]):
        sector_key = chart["sector"]
        if sector_key not in artifacts:
            continue
        with columns[index]:
            with st.container(height=PAIR_CARD_HEIGHT, border=True):
                sector = SECTORS[sector_key]
                st.markdown(
                    f'<div class="am-kicker">{escape(sector["short_zh" if language == "zh" else "short_en"])}</div>',
                    unsafe_allow_html=True,
                )
                st.caption(tr(language, chart["note_en"], chart["note_zh"]))
                render_line_chart(
                    artifacts[sector_key],
                    labels[sector_key],
                    chart["chart_id"],
                    language,
                    window,
                    views=chart["views"],
                    periods_per_year=chart["periods_per_year"],
                    change_mode=chart["change_mode"],
                    height=chart["height"],
                )
                st.button(
                    tr(language, f"Open {sector['short_en']}", f"打开{sector['short_zh']}"),
                    key=f"overview_featured_open_{sector_key}",
                    width="stretch",
                    on_click=set_app_page,
                    args=(sector_key,),
                )


def render_overview_health_summary(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    language: str,
) -> None:
    section_heading(
        language,
        "Source health",
        "来源健康度",
        "Overview shows only the compact status; the full source table stays on Source Health.",
        "总览只显示摘要；完整来源表保留在来源健康度页面。",
    )
    summary = overview_source_summary(artifacts, labels)
    with st.container(border=True):
        columns = st.columns(4)
        values = [
            (tr(language, "Total feeds", "数据流总数"), summary["total"]),
            (tr(language, "Ready", "可用"), summary["healthy"]),
            (tr(language, "Attention", "需留意"), summary["attention"]),
            (tr(language, "Problem", "有问题"), summary["problem"]),
        ]
        for column, (label, value) in zip(columns, values):
            with column:
                st.markdown(
                    f'<div class="am-health-value">{escape(str(value))}</div>'
                    f'<div class="am-health-label">{escape(label)}</div>',
                    unsafe_allow_html=True,
                )
        st.caption(
            tr(
                language,
                "Source observation dates remain mixed by cadence; inspect Source Health for dataset-level detail.",
                "不同来源的观察日期按各自频率更新；请到来源健康度查看数据集详情。",
            )
        )
        st.button(
            tr(language, "Open Source Health", "打开来源健康度"),
            key="overview_open_health",
            width="stretch",
            on_click=set_app_page,
            args=("health",),
        )



def render_ccl_mhpi_combined_chart(
    artifact: dict[str, Any],
    language: str,
    history_window_name: str,
    *,
    height: int = 380,
) -> None:
    """Overlay CCL and MHPI on one plot — both are weekly residential price indices on a comparable scale."""
    ccl = frame_for_dataset(artifact, "ccl_history").assign(series=tr(language, "Centaline CCL", "中原城市领先指数（CCL）"))
    mhpi = frame_for_dataset(artifact, "mhpi_history").assign(series=tr(language, "Midland MHPI", "美联物业价格指数（MHPI）"))
    combined = pd.concat([ccl, mhpi], ignore_index=True)
    combined, coverage = history_window(combined, "date", history_window_name)

    title = tr(language, "Centaline CCL & Midland MHPI", "中原城市领先指数（CCL）与美联物业价格指数（MHPI）")
    st.markdown(f'<div class="am-chart-title">{title}</div>', unsafe_allow_html=True)
    subtitle = tr(
        language,
        "Two independently published weekly residential price indices, plotted together for comparison.",
        "两个独立发布的住宅价格周度指数，一并显示以便比较。",
    )
    st.caption(" · ".join([subtitle, localize_coverage(coverage, language)]))
    if combined.empty:
        st.info(tr(language, "No rows are available for this selection.", "这个选择没有可用数据。"))
        return

    view = st.radio(
        tr(language, "View", "视图"),
        ("Level", "WoW %", "YoY %"),
        horizontal=True,
        key="view_ccl_mhpi_combined",
        format_func=lambda item: view_label(language, item),
    )
    transformed, value_label, transformed_format = line_view_frame(combined, "value", "series", view, 52, "pct", "number")
    if transformed.empty:
        st.info(tr(language, "Not enough observations for this comparison window.", "这个比较视图没有足够的观察值。"))
        return
    fig = px.line(transformed, x="_date", y="_value", color="series", markers=False, color_discrete_sequence=PALETTE)
    fig.update_yaxes(title=value_label)
    fig.update_xaxes(title=None, tickformat="%b %Y")
    if transformed["_date"].max() - transformed["_date"].min() > pd.Timedelta(days=365 * 7):
        fig.update_xaxes(dtick="M12")
    elif transformed["_date"].max() - transformed["_date"].min() > pd.Timedelta(days=365 * 3):
        fig.update_xaxes(dtick="M6")
    apply_line_hover(fig, transformed, transformed_format)
    fig = chart_theme(fig, transformed_format, date_axis=True, height=height)
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})


def render_real_estate_residential(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    cards = [
        metric_from_card(artifact, labels, "ccl_card", "latest", "number"),
        metric_from_card(artifact, labels, "mhpi_card", "latest", "number"),
        metric_from_card(artifact, labels, "rvd_price_card", "latest", "number"),
        metric_from_card(artifact, labels, "rvd_rent_card", "latest", "number"),
    ]
    columns = st.columns(len(cards))
    for column, (label, value, help_text) in zip(columns, cards):
        with column:
            st.metric(label, value, help=help_text)

    section_heading(
        language,
        "Price & rental core",
        "价格与租金核心走势",
        "CCL and MHPI are publisher-level weekly indices; RVD is the official monthly benchmark.",
        "CCL 与 MHPI 为发布者周度指数；RVD 为官方月度基准指数。",
    )
    with st.container(border=True):
        render_ccl_mhpi_combined_chart(artifact, language, window, height=420)

    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "rvd_trend",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "rvd_rent_trend",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=chart_h,
            )

    section_heading(
        language,
        "Mortgage & credit",
        "按揭与信贷",
        "HKMA residential mortgage survey: rate mix, LTV, credit quality, applications and loan amounts.",
        "金管局住宅按揭调查：利率组合、按揭成数、信贷质素、申请宗数及贷款金额。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "hkma_mortgage_rate_mix_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "hkma_ltv_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )

    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "hkma_credit_quality_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "hkma_applications_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )

    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "hkma_loan_amount_chart",
            language,
            window,
            views=("Level",),
            periods_per_year=12,
            height=390,
        )

    with st.container(border=True):
        render_table(artifact, labels, "hkma_mortgage_activity_table", language, max_rows=24)

    section_heading(
        language,
        "Transactions & new supply",
        "成交与新盘供应",
        "Land Registry ASP counts, agency transaction pulse, new project launches and 28Hse EPI/ERI.",
        "土地注册处买卖合约宗数、代理行成交脉搏、新盘推售及 28Hse 楼价/租金指数。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "landreg_asp_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "epi_eri_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )

    card_h, chart_h = get_pair_heights(400, 400, 'bar', 'bar')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_table(artifact, labels, "agency_transactions_pulse_table", language, max_rows=25)
    with right:
        with st.container(height=card_h, border=True):
            render_table(artifact, labels, "hse28_new_projects_table", language, max_rows=25)

    section_heading(
        language,
        "Government supply pipeline (Buildings Department)",
        "政府房屋供应管道（屋宇署）",
        "Demolition-to-occupation project lifecycle, from the official monthly digest archive.",
        "由拆卸至入伙的项目生命周期，来自屋宇署月报档案。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            selected_units = series_options(artifact, "bd_supply_history_units_chart", language, default_count=4)
            units_frequency = monthly_quarterly_control(language, "bd_supply_units_freq")
            render_line_chart(
                artifact,
                labels,
                "bd_supply_history_units_chart",
                language,
                window,
                series_selection=selected_units,
                views=("Level", "YoY %"),
                periods_per_year=12 if units_frequency == "Monthly" else 4,
                resample_frequency=units_frequency,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            selected_counts = series_options(artifact, "bd_supply_history_counts_chart", language, default_count=4)
            counts_frequency = monthly_quarterly_control(language, "bd_supply_counts_freq")
            render_line_chart(
                artifact,
                labels,
                "bd_supply_history_counts_chart",
                language,
                window,
                series_selection=selected_counts,
                views=("Level", "YoY %"),
                periods_per_year=12 if counts_frequency == "Monthly" else 4,
                resample_frequency=counts_frequency,
                height=chart_h,
            )

    with st.container(border=True):
        render_table(artifact, labels, "bd_supply_detail_table", language, max_rows=30)


def render_real_estate_cross_source(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    section_heading(
        language,
        "Rebased comparisons",
        "重新基准化比较",
        "Each series rebased to 100 at its first available month in the window; price and rent are kept on separate scales.",
        "各序列在窗口内首个可用月份重新基准化为 100；价格与租金分开显示，避免混合比较。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "residential_price_rebased_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "residential_rent_rebased_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )

    section_heading(
        language,
        "Centaline price & rental indices",
        "中原价格与租金指数",
        "CCI and CRI are separate Centaline index products from the CCL headline series; rental yield is a companion series, not a rent level.",
        "CCI 与 CRI 为中原独立指数产品，有别于 CCL headline 序列；租金回报率为配套序列，并非租金水平。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "cci_trend",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "cri_trend",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=chart_h,
            )

    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "cri_yield_trend",
            language,
            window,
            views=("Level",),
            periods_per_year=12,
            height=360,
        )

    section_heading(
        language,
        "Market sentiment",
        "市场情绪",
        "Two independent sentiment reads: Centaline CSI (weekly) and Midland's own confidence index.",
        "两个独立的情绪指标：中原 CSI（周度）及美联物业信心指数。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "csi_trend",
                language,
                window,
                views=("Level",),
                periods_per_year=52,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "confidence_trend",
                language,
                window,
                views=("Level",),
                periods_per_year=52,
                height=chart_h,
            )


def render_real_estate_commercial(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    section_heading(
        language,
        "Office & retail rents",
        "写字楼与零售租金",
        "Official RVD rental/price indices for commercial property, separate from the residential series.",
        "官方 RVD 商业地产租金／价格指数，与住宅序列分开显示。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "rvd_office_trend",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "rvd_retail_trend",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=chart_h,
            )

    section_heading(
        language,
        "Supply-side macro signals",
        "供应端宏观信号",
        "Economy-wide construction activity and government land disposed by method — leading indicators for future commercial and residential supply.",
        "全经济建筑活动及政府卖地（按方式划分）——未来商业及住宅供应的领先指标。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "cnsd_construction_value_chart",
                language,
                window,
                views=("Level", "QoQ %", "YoY %"),
                periods_per_year=4,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "censtatd_land_disposals_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=4,
                height=chart_h,
            )


def render_real_estate_tabs(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    """Render Hong Kong real estate as residential, cross-source/sentiment and commercial/land-supply tabs.

    Company-level bottom-up analysis (e.g. individual developer deep dives) is
    tracked separately and intentionally has no tab here yet.
    """
    render_header(
        artifact,
        labels,
        language,
        "real_estate",
        title_override=tr(language, "Hong Kong Real Estate", "香港地产"),
        description_override=tr(
            language,
            "Sector-level residential, cross-source/sentiment and commercial/land-supply signals. Company-level bottom-up analysis is tracked separately and is not part of this page.",
            "板块级住宅、跨来源／情绪指标及商业地产／土地供应信号。个股自下而上分析另行追踪，不在此页面内。",
        ),
    )
    residential_tab, cross_source_tab, commercial_tab = st.tabs([
        tr(language, "Residential Market", "住宅市场"),
        tr(language, "Cross-Source & Sentiment", "跨来源与市场情绪"),
        tr(language, "Commercial & Land Supply", "商业地产与土地供应"),
    ])
    with residential_tab:
        render_real_estate_residential(artifact, labels, language, window)
    with cross_source_tab:
        render_real_estate_cross_source(artifact, labels, language, window)
    with commercial_tab:
        render_real_estate_commercial(artifact, labels, language, window)
    render_source_coverage({"real_estate": artifact}, {"real_estate": labels}, language)



def render_overview(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    language: str,
    window: str,
) -> None:
    st.markdown(f'<div class="am-page-title">{tr(language, "Asia Markets Overview", "亚洲市场总览")}</div>', unsafe_allow_html=True)
    st.caption(
        tr(
            language,
            "A bounded Hong Kong market pulse across the connected sectors; detailed analysis stays on sector pages.",
            "香港市场脉搏总览；详细分析保留在各板块页面。",
        )
    )
    st.markdown(
        f'<div class="am-meta">{escape(tr(language, "Hong Kong", "香港"))} · '
        f'{escape(tr(language, "artifact snapshots, not live browser connections", "artifact 数据快照，不是浏览器实时连接"))}</div>',
        unsafe_allow_html=True,
    )
    render_overview_header(artifacts, labels, language)
    render_sector_pulse(artifacts, labels, language)
    render_featured_trends(artifacts, labels, language, window)
    render_overview_health_summary(artifacts, labels, language)


def make_sidebar(language: str) -> tuple[str, str, str]:
    with st.sidebar:
        st.markdown(
            '<div class="am-brand"><div class="am-brand-mark">AM</div><div><div class="am-brand-name">Asia Markets</div><div class="am-brand-sub">Private research terminal</div></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(f'<div class="am-sidebar-group-label">{tr(language, "Preferences", "偏好设置")}</div>', unsafe_allow_html=True)
        language_choice = st.selectbox(
            "Language / 语言",
            ["English", "中文"],
            index=1 if language == "zh" else 0,
            key="language_choice",
        )
        active_language = "zh" if language_choice == "中文" else "en"
        page_labels = {
            "overview": tr(active_language, "Overview", "总览"),
            "market": tr(active_language, "ETF Monitor", "ETF监控"),
            "labour": tr(active_language, "Labour Market", "劳动力市场"),
            "population": tr(active_language, "Population & Migration", "人口与迁移"),
            "real_estate": tr(active_language, "Hong Kong Real Estate", "地产"),
            "transport": tr(active_language, "Transport & Aviation", "交通与航空"),
            "aerospace": tr(active_language, "Commercial Aerospace", "商业航天"),
            "crypto": tr(active_language, "Stablecoin & Crypto", "稳定币与加密资产"),
            "data": tr(active_language, "Data Explorer", "数据探索器"),
            "health": tr(active_language, "Source Health", "来源健康度"),
        }
        current_page = str(st.session_state.get("page", "overview"))
        if current_page not in page_labels:
            current_page = "overview"
            st.session_state["page"] = current_page

        def set_page(page_key: str) -> None:
            st.session_state["page"] = page_key

        def nav_button(page_key: str) -> None:
            st.button(
                page_labels[page_key],
                key=f"sidebar_nav_{page_key}",
                type="primary" if current_page == page_key else "secondary",
                width="stretch",
                on_click=set_page,
                args=(page_key,),
            )

        st.markdown(f'<div class="am-sidebar-group-label">{tr(active_language, "Workspace", "工作台")}</div>', unsafe_allow_html=True)
        nav_button("overview")
        st.markdown(f'<div class="am-sidebar-group-label">{tr(active_language, "Markets", "市场")}</div>', unsafe_allow_html=True)
        nav_button("market")
        st.markdown(f'<div class="am-sidebar-group-label">{tr(active_language, "Hong Kong", "香港")}</div>', unsafe_allow_html=True)
        nav_button("labour")
        nav_button("population")
        nav_button("real_estate")
        nav_button("transport")
        nav_button("aerospace")
        nav_button("crypto")
        st.markdown(f'<div class="am-sidebar-group-label">{tr(active_language, "Data", "数据")}</div>', unsafe_allow_html=True)
        nav_button("data")
        nav_button("health")
        st.divider()
        history_window_name = st.selectbox(
            tr(active_language, "Default history window", "默认历史范围"),
            list(HISTORY_WINDOWS),
            index=0,
            key="history_window",
            help=tr(active_language, "The source grain is preserved; shorter source histories show all available rows.", "保留来源粒度；来源历史较短时显示全部可用数据。"),
        )
        st.divider()
        st.caption(tr(active_language, "V1 scope", "V1 范围"))
        st.caption(tr(active_language, "Hong Kong · 5 sectors", "香港 · 5 个板块"))
    return active_language, current_page, history_window_name


def main() -> None:
    st.set_page_config(page_title="Asia Markets", page_icon="🌏", layout="wide", initial_sidebar_state="expanded")
    style_app()
    language_hint = st.session_state.get("language_choice", "English")
    initial_language = "zh" if language_hint == "中文" else "en"
    language, page, window = make_sidebar(initial_language)
    artifacts: dict[str, dict[str, Any]] = {}
    labels: dict[str, dict[str, Any]] = {}
    try:
        for key, config in SECTORS.items():
            artifacts[key] = load_artifact(
                config["slug"], "en", artifact_mtime_ns(config["slug"], "en")
            )
            labels[key] = load_artifact(
                config["slug"], language, artifact_mtime_ns(config["slug"], language)
            )
    except FileNotFoundError as error:
        st.error(f"Missing local dashboard artifact: {error}")
        st.stop()

    if page == "overview":
        render_overview(artifacts, labels, language, window)
    elif page == "market":
        render_market(artifacts["market"], labels["market"], language, window)
    elif page == "labour":
        render_labour(artifacts["labour"], labels["labour"], language, window)
    elif page == "population":
        render_population(artifacts["population"], labels["population"], language, window)
    elif page == "transport":
        render_transport_tabs(artifacts["transport"], labels["transport"], language, window)
    elif page == "aerospace":
        render_aerospace(artifacts["aerospace"], labels["aerospace"], language, window)
    elif page == "real_estate":
        render_real_estate_tabs(artifacts["real_estate"], labels["real_estate"], language, window)
    elif page == "crypto":
        render_crypto(artifacts["crypto"], labels["crypto"], language, window)
    elif page == "data":
        render_data_explorer(artifacts, language)
    elif page == "health":
        st.markdown(f'<div class="am-page-title">{tr(language, "Source Health", "来源健康度")}</div>', unsafe_allow_html=True)
        st.caption(tr(language, "Freshness and coverage for the five connected V1 sectors.", "五个已接入 V1 板块的更新时间和覆盖情况。"))
        render_source_coverage(artifacts, labels, language)


if __name__ == "__main__":
    main()
