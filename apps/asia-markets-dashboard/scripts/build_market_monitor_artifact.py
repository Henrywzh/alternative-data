"""Build the Index & ETF Allocation Monitor dashboard artifact.

Read-only: consumes latest normalized/derived market_monitor snapshots and
packages them into the shared Asia Markets artifact contract so the same
portable renderer / Streamlit surface can display the exposure and wrapper
views without touching the live data sources at build time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.market_monitor.config import DERIVED_DIR, EXPOSURES, NORMALIZED_DIR
from src.market_monitor.metadata import build_metadata_frame
from src.market_monitor.storage import load_latest_with_lineage  # noqa: E402


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    out = frame.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
    return json.loads(out.to_json(orient="records", date_format="iso", default_handler=str))


def build_artifact() -> tuple[dict[str, Any], dict[str, Any]]:
    now = datetime.now(timezone.utc)
    generated_at = now.isoformat()
    technicals, tech_lineage = load_latest_with_lineage(DERIVED_DIR, "exposure_technicals", scope="full")
    regime, regime_lineage = load_latest_with_lineage(DERIVED_DIR, "relative_regime", scope="full")
    wrappers, wrap_lineage = load_latest_with_lineage(DERIVED_DIR, "wrapper_metrics", scope="full")
    index_px, index_lineage = load_latest_with_lineage(NORMALIZED_DIR, "index_price_daily", scope="full")

    # --- Run consistency check: all datasets must come from the same run ---
    lineages = {
        "exposure_technicals": tech_lineage,
        "relative_regime": regime_lineage,
        "wrapper_metrics": wrap_lineage,
        "index_price_daily": index_lineage,
    }
    run_ids = {name: (li or {}).get("run_id") for name, li in lineages.items()}
    unique_run_ids = {rid for rid in run_ids.values() if rid}
    run_consistent = len(unique_run_ids) == 1 and all(run_ids.values())
    latest_run_id = max(unique_run_ids, key=str) if unique_run_ids else None
    if not run_consistent:
        stale_datasets = [name for name, rid in run_ids.items() if not rid or rid != latest_run_id]
    else:
        stale_datasets = []

    data_as_of = "—"
    if not technicals.empty and "date" in technicals.columns:
        data_as_of = str(pd.to_datetime(technicals["date"], errors="coerce").max().date())

    datasets: dict[str, list[dict[str, Any]]] = {
        "exposure_technicals": _records(technicals),
        "relative_regime": _records(regime),
        "wrapper_metrics": _records(wrappers),
        # Keep up to 250 trailing trading days per exposure, not 250 global
        # rows (which with 8 indexes collapses to ~1 month of history).
        "index_price_daily_tail": _records(index_px.sort_values("date").groupby("exposure_id", sort=False).tail(250)) if not index_px.empty else [],
    }
    # Source-specific latest observations (do not share across sources)
    if not index_px.empty and "date" in index_px.columns:
        cn_index = index_px[index_px["exposure_id"].ne("sp500")]
        sina_latest = str(pd.to_datetime(cn_index["date"], errors="coerce").max().date()) if not cn_index.empty else "—"
        us_index = index_px[index_px["exposure_id"].eq("sp500")]
        yahoo_latest = str(pd.to_datetime(us_index["date"], errors="coerce").max().date()) if not us_index.empty else "—"
        latest_obs = str(pd.to_datetime(index_px["date"], errors="coerce").max().date())
    else:
        sina_latest = yahoo_latest = latest_obs = "—"
    spot_latest = (wrap_lineage or {}).get("created_at", "—")[:10] if wrap_lineage else "—"

    # Compact KPI rows for the Overview pulse card (kept separate from the
    # full technicals table so the overview contract stays small).
    kpi_rows: list[dict[str, Any]] = []
    if not technicals.empty and "exposure_id" in technicals.columns:
        for exposure_id, label, key in (
            ("csi300", "CSI 300", "rsi"),
            ("sp500", "S&P 500", "rsi"),
        ):
            row = technicals[technicals["exposure_id"].eq(exposure_id)]
            if row.empty:
                continue
            latest = row.iloc[-1]
            kpi_rows.append(
                {
                    "exposure_id": exposure_id,
                    "label": label,
                    "metric": key,
                    "value": float(latest[key]) if latest.get(key) is not None else None,
                    "date": latest.get("date"),
                }
            )
    if regime is not None and not regime.empty:
        small_large = regime[regime["label"].eq("Small / Large")]
        if not small_large.empty:
            row = small_large.iloc[-1]
            kpi_rows.append(
                {
                    "exposure_id": "relative",
                    "label": "Small / Large z",
                    "metric": "spread_20d_zscore",
                    "value": float(row["spread_20d_zscore"]) if row.get("spread_20d_zscore") is not None else None,
                    "date": None,
                }
            )
    datasets["kpi_market"] = kpi_rows
    if not index_px.empty and "date" in index_px.columns:
        latest_obs = str(pd.to_datetime(index_px["date"], errors="coerce").max().date())
    else:
        latest_obs = "—"

    # Source ownership: Sina owns CN/HK indexes; Yahoo owns SP500.
    # Sina health must not count SP500 toward its own coverage.
    sina_expected = [e["exposure_id"] for e in EXPOSURES if e["exposure_id"] != "sp500"]
    sina_actual_count = (
        technicals[technicals["exposure_id"].isin(sina_expected)]["exposure_id"].nunique()
        if not technicals.empty and "exposure_id" in technicals.columns
        else 0
    )
    expected_count = len(EXPOSURES)
    actual_exposures = technicals["exposure_id"].nunique() if not technicals.empty and "exposure_id" in technicals.columns else 0
    expected_wrappers = len(build_metadata_frame())
    if not wrappers.empty and "market_price" in wrappers.columns and "premium_pct" in wrappers.columns:
        spot_observed = int((wrappers["market_price"].notna() & wrappers["premium_pct"].notna()).sum())
    else:
        spot_observed = 0
    sp500_ok = not index_px.empty and "exposure_id" in index_px.columns and not index_px[index_px["exposure_id"].eq("sp500")].empty

    if spot_observed == expected_wrappers and expected_wrappers > 0:
        spot_status = "Healthy"
        spot_notes = f"Eastmoney ETF spot: all {spot_observed} / {expected_wrappers} wrappers observed."
    elif spot_observed > 0:
        spot_status = "Degraded"
        spot_notes = f"Eastmoney ETF spot: {spot_observed} / {expected_wrappers} wrappers observed."
    else:
        spot_status = "Unavailable"
        spot_notes = f"Eastmoney ETF spot snapshot failed (0 / {expected_wrappers} wrappers observed)."

    sina_status = "Healthy" if sina_actual_count >= len(sina_expected) else "Degraded"
    sina_records = (
        len(index_px[index_px["exposure_id"].isin(sina_expected)])
        if not index_px.empty and "exposure_id" in index_px.columns
        else 0
    )
    yfinance_status = "Healthy" if sp500_ok else "Degraded"
    overall_healthy = (
        actual_exposures >= expected_count
        and spot_status == "Healthy"
        and sp500_ok
        and run_consistent
    )

    datasets["source_health"] = [
        {
            "source": "Eastmoney ETF spot (premium / turnover / IOPV)",
            "status": spot_status,
            "latest_observation": spot_latest,
            "records": spot_observed,
            "notes": spot_notes,
        },
        {
            "source": "Sina index daily (CN/HK)",
            "status": sina_status,
            "latest_observation": sina_latest,
            "records": sina_records,
            "notes": f"Covering {sina_actual_count} of {len(sina_expected)} Sina-owned exposures (CN/HK)." if sina_actual_count < len(sina_expected) else f"Daily OHLCV for all {sina_actual_count} Sina-owned exposures (CN/HK).",
        },
        {
            "source": "Yahoo Finance (S&P 500 index)",
            "status": yfinance_status,
            "latest_observation": yahoo_latest,
            "records": len(index_px[index_px["exposure_id"].eq("sp500")]) if sp500_ok else 0,
            "notes": "US session history for the S&P 500 exposure." if sp500_ok else "S&P 500 index data missing.",
        },
    ]
    if stale_datasets:
        datasets["source_health"].append(
            {
                "source": "Pipeline run consistency",
                "status": "Degraded",
                "latest_observation": "—",
                "records": 0,
                "notes": f"Datasets from different pipeline runs: {', '.join(sorted(stale_datasets))}. Do not mix timelines.",
            }
        )
    sources = [
        {"id": "eastmoney_etf_spot", "label": "Eastmoney ETF snapshot (premium / spread / turnover / IOPV)", "href": "https://quote.eastmoney.com/center/gridlist.html#fund_etf", "query": {"engine": "akshare fund_etf_spot_em"}},
        {"id": "sina_index_daily", "label": "Sina Finance index / ETF daily OHLCV", "href": "https://finance.sina.com.cn/", "query": {"engine": "akshare stock_zh_index_daily / fund_etf_hist_sina"}},
        {"id": "yfinance_spx", "label": "Yahoo Finance S&P 500 index", "href": "https://finance.yahoo.com/quote/%5EGSPC/", "query": {"engine": "yfinance ^GSPC"}},
    ]

    charts: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []

    # --- Market Leadership table (exposure technicals) ---
    tables.append(
        {
            "id": "market_leadership_table",
            "title": "Exposure Leadership",
            "dataset": "exposure_technicals",
            "columns": [
                {"field": "label", "label": "Exposure", "format": "text"},
                {"field": "rsi", "label": "RSI", "format": "number"},
                {"field": "ma20_pct", "label": "MA20 %", "format": "pct"},
                {"field": "ma60_pct", "label": "MA60 %", "format": "pct"},
                {"field": "drawdown_60d", "label": "DD60 %", "format": "pct"},
            ],
        }
    )
    blocks.append({"id": "market_leadership_block", "type": "table", "tableId": "market_leadership_table"})

    # --- Relative regime table ---
    tables.append(
        {
            "id": "relative_regime_table",
            "title": "Relative Regime",
            "dataset": "relative_regime",
            "columns": [
                {"field": "label", "label": "Spread", "format": "text"},
                {"field": "spread_20d_zscore", "label": "20D z", "format": "number"},
                {"field": "spread_5d_pct", "label": "5D %", "format": "pct"},
                {"field": "spread_20d_pct", "label": "20D %", "format": "pct"},
                {"field": "trend", "label": "Trend", "format": "text"},
            ],
        }
    )
    blocks.append({"id": "relative_regime_block", "type": "table", "tableId": "relative_regime_table"})

    # --- Sparkline data for the Overview pulse card (Small vs Large spread) ---
    charts.append(
        {
            "id": "small_large_regime_chart",
            "title": "Small vs Large relative strength",
            "dataset": "relative_regime",
            "encodings": {
                "x": {"field": "label", "type": "nominal", "label": "Spread"},
                "y": {"field": "spread_20d_zscore", "type": "quantitative", "label": "20D z"},
                "color": {"field": "label", "type": "nominal"},
            },
        }
    )

    # --- Wrapper selection table ---
    tables.append(
        {
            "id": "wrapper_selection_table",
            "title": "Wrapper Selection (Entry Status / Peer Rank / Hold Rank)",
            "dataset": "wrapper_metrics",
            "columns": [
                {"field": "ticker", "label": "Ticker", "format": "text"},
                {"field": "fund_name", "label": "Fund", "format": "text"},
                {"field": "premium_pct", "label": "Premium %", "format": "pct"},
                {"field": "relative_premium_pct", "label": "Rel Premium %", "format": "pct"},
                {"field": "entry_status", "label": "Entry Status", "format": "text"},
                {"field": "entry_cost_bp", "label": "Entry Cost (bp)", "format": "number"},
                {"field": "spread_bp", "label": "Spread (bp)", "format": "number"},
                {"field": "liquidity_score", "label": "Liquidity", "format": "number"},
                {"field": "aum_proxy", "label": "Market Cap Proxy (CNY)", "format": "number"},
                {"field": "peer_rank", "label": "Peer Rank", "format": "number"},
                {"field": "hold_rank", "label": "Hold Rank", "format": "number"},
            ],
        }
    )
    blocks.append({"id": "wrapper_selection_block", "type": "table", "tableId": "wrapper_selection_table"})

    snapshot_id = hashlib.sha1(json.dumps(datasets, sort_keys=True, default=str).encode()).hexdigest()[:16]
    artifact: dict[str, Any] = {
        "manifest": {"version": 1, "generatedAt": generated_at, "cards": [], "charts": charts, "tables": tables, "blocks": blocks},
        "snapshot": {"version": 1, "generatedAt": generated_at, "status": "ready", "datasets": datasets},
        "sources": sources,
        "package_info": {"snapshotId": snapshot_id, "dataAsOf": data_as_of, "pipelineRunId": latest_run_id, "runConsistent": run_consistent},
    }
    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": data_as_of,
        "overall_status": "Healthy" if overall_healthy else "Degraded",
        "live_sources": 3,
        "planned_sources": 0,
        "sources": datasets["source_health"],
        "attachment_filename": f"market-monitor-dashboard-{now.date().isoformat()}.html",
    }
    return artifact, status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--status-output", type=Path, default=None, help="Optional status JSON (Cloudflare surface only; Streamlit does not use this)")
    args = parser.parse_args()
    artifact, status = build_artifact()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    # Streamlit loads per-language artifacts (english default + *-zh.json for
    # the Chinese UI) and crashes with FileNotFoundError when the zh file is
    # absent. The market-monitor tables are bilingual by id already, so emit
    # an identical -zh.json alongside the english artifact. The later
    # package-dashboard.mjs pass may produce a fancier localized copy; this
    # guarantees a usable artifact for the Streamlit surface either way.
    zh_path = args.output.with_name(args.output.name.replace("-artifact.json", "-artifact-zh.json"))
    zh_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    if args.status_output:
        args.status_output.parent.mkdir(parents=True, exist_ok=True)
        args.status_output.write_text(json.dumps(status, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "artifact": str(args.output), "snapshot_id": status["snapshot_id"], "data_as_of": status["data_as_of"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
