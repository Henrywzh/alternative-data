from __future__ import annotations

from pathlib import Path

import pandas as pd


class SignalStorage:
    def __init__(self, base_dir: Path) -> None:
        self.normalized_root = base_dir / "data" / "normalized" / "ai_news_signal"
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def append_guard_log(self, rows: list[dict]) -> None:
        self._append("ai_news_signal_guard.parquet", rows, keys=["item_id"])

    def append_brief(self, rows: list[dict]) -> None:
        self._append("ai_news_signal_brief.parquet", rows, keys=["run_date", "item_id"])

    def _append(self, filename: str, rows: list[dict], keys: list[str]) -> None:
        if not rows:
            return
        path = self.normalized_root / filename
        incoming = pd.DataFrame(rows)
        if path.exists():
            existing = pd.read_parquet(path)
            combined = pd.concat([existing, incoming]).drop_duplicates(subset=keys, keep="last")
        else:
            combined = incoming
        combined.to_parquet(path, index=False)
