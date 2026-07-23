import logging
import pandas as pd
from datetime import datetime, timezone
from typing import Optional

from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

def fetch_sge_gold_benchmark() -> pd.DataFrame:
    """Fetch Shanghai Gold Exchange benchmark via akshare or baseline fallback."""
    raw_path = None
    source_url = "akshare.spot_golden_benchmark_sge"
    try:
        import akshare as ak
        df_ak = ak.spot_golden_benchmark_sge()
        if not df_ak.empty:
            raw_path = save_raw_snapshot("sge_gold_benchmark", df_ak.to_dict(orient="records"), file_ext="json", source_url=source_url)
            
            # Map columns
            col_map = {c.lower(): c for c in df_ak.columns}
            date_col = col_map.get("date") or col_map.get("交易日期") or col_map.get("日期") or df_ak.columns[0]
            pm_col = col_map.get("close") or col_map.get("晚盘价") or col_map.get("午盘价") or df_ak.columns[1]
            am_col = col_map.get("open") or col_map.get("早盘价") or df_ak.columns[-1]

            records = []
            for _, row in df_ak.iterrows():
                obs_date = str(row[date_col])[:10]
                pm_val = pd.to_numeric(row[pm_col], errors="coerce")
                am_val = pd.to_numeric(row[am_col], errors="coerce")
                records.append({
                    "date": obs_date,
                    "gold_benchmark_pm_rmb_gram": float(pm_val) if pd.notna(pm_val) else 0.0,
                    "gold_benchmark_am_rmb_gram": float(am_val) if pd.notna(am_val) else float(pm_val or 0.0),
                    "currency": "RMB/g",
                })
            df_norm = pd.DataFrame(records)
            df_norm.attrs["raw_snapshot"] = str(raw_path)
            df_norm.attrs["source_url"] = source_url
            return df_norm
    except Exception as exc:
        logger.warning(f"Akshare SGE fetch failed ({exc}).")

    logger.error("SGE gold benchmark unavailable; returning empty dataset (no fabricated data).")
    df_empty = pd.DataFrame(columns=["date", "gold_benchmark_pm_rmb_gram", "gold_benchmark_am_rmb_gram", "currency"])
    df_empty.attrs["raw_snapshot"] = str(raw_path) if raw_path else None
    df_empty.attrs["source_url"] = source_url
    return df_empty
