from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .models import HkexDailyFlowObservation


def _last_valid(values: pd.Series) -> object:
    """Most recent non-null value in a same-day group, else null."""
    present = values.dropna()
    return present.iloc[-1] if not present.empty else pd.NA



class HkexMarketFlowStorage:
    COLS = [
        "trade_date", "southbound_buy_turnover_hkd_mln", "southbound_sell_turnover_hkd_mln",
        "southbound_net_inflow_hkd_mln", "northbound_buy_turnover_rmb_mln",
        "northbound_sell_turnover_rmb_mln", "northbound_net_inflow_rmb_mln",
        "total_market_turnover_hkd_mln", "southbound_turnover_share_pct",
        "short_selling_turnover_hkd_mln", "short_selling_ratio_pct", "fetched_at",
        "northbound_total_turnover_rmb_mln", "short_selling_turnover_rmb_mln",
        "short_selling_security_count", "short_selling_turnover_shares",
        "short_selling_shares_available",
    ]

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "hkex_market_flow"
        self.normalized_root = base_dir / "data" / "normalized" / "hkex_market_flow"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_payload(self, run_id: str, name: str, data: Any) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def load_observations(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "hkex_market_flow_daily.parquet"
        csv_path = self.normalized_root / "hkex_market_flow_daily.csv"
        if parquet_path.exists():
            return pd.read_parquet(parquet_path).reindex(columns=self.COLS)
        if csv_path.exists():
            return pd.read_csv(csv_path).reindex(columns=self.COLS)
        return pd.DataFrame(columns=self.COLS)

    def upsert_observations(self, records: Iterable[HkexDailyFlowObservation]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.COLS)
        if incoming.empty:
            return self.load_observations()
        existing = self.load_observations()
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        for col in [
            "southbound_buy_turnover_hkd_mln", "southbound_sell_turnover_hkd_mln",
            "southbound_net_inflow_hkd_mln", "total_market_turnover_hkd_mln",
            "southbound_turnover_share_pct", "short_selling_turnover_hkd_mln",
            "short_selling_ratio_pct",
            "northbound_total_turnover_rmb_mln", "short_selling_turnover_rmb_mln",
            "short_selling_security_count", "short_selling_turnover_shares",
            "short_selling_shares_available",
        "short_selling_shares_available",
        ]:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")
        # Combine same-day rows field by field instead of letting the last one
        # win outright. The daily flow file and the short-selling file are
        # fetched and parsed separately, so a plain keep="last" replaced a row
        # that already held southbound turnover with one that only holds
        # short-selling data -- silently nulling the flow columns for that day.
        merged = merged.sort_values(by=["trade_date"], kind="stable")
        merged = merged.groupby("trade_date", as_index=False, sort=True).agg(
            {column: _last_valid for column in self.COLS if column != "trade_date"}
        )
        merged = merged.reindex(columns=self.COLS)
        merged = merged.sort_values(by=["trade_date"]).reset_index(drop=True)
        # No CSV twin: `*.csv` is gitignored repo-wide, so the twin was never
        # published -- it only cost local disk (151 MB against a 12 MB parquet
        # for the largest lane) and doubled the write on every refresh.
        merged.to_parquet(self.normalized_root / "hkex_market_flow_daily.parquet", index=False)
        return merged
