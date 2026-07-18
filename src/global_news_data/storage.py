import json
import logging
from pathlib import Path
from typing import Any, Iterable
import pandas as pd
from .models import UnifiedNewsRecord

logger = logging.getLogger(__name__)

class NewsStorage:
    UNIFIED_COLS = [
        "article_id",
        "source",
        "published_at",
        "title",
        "summary",
        "body_text",
        "url",
        "entities",
        "sentiment_score",
        "language",
        "fetched_at",
    ]

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "global_news"
        self.normalized_root = base_dir / "data" / "normalized" / "global_news"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_payload(self, run_id: str, name: str, data: Any) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return path

    def load_unified(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "news_unified.parquet"
        csv_path = self.normalized_root / "news_unified.csv"
        if parquet_path.exists():
            df = pd.read_parquet(parquet_path)
        elif csv_path.exists():
            df = pd.read_csv(csv_path)
        else:
            return pd.DataFrame(columns=self.UNIFIED_COLS)

        for col in self.UNIFIED_COLS:
            if col not in df.columns:
                df[col] = None
        return df[self.UNIFIED_COLS]

    def upsert_records(self, records: Iterable[UnifiedNewsRecord]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.UNIFIED_COLS)
        if incoming.empty:
            return self.load_unified()

        existing = self.load_unified()
        if not existing.empty:
            merged = pd.concat([existing, incoming], ignore_index=True)
        else:
            merged = incoming.copy()

        merged["sentiment_score"] = pd.to_numeric(merged["sentiment_score"], errors="coerce")
        merged = merged.drop_duplicates(subset=["source", "article_id"], keep="last")

        merged = merged.sort_values(by=["published_at", "source", "article_id"], ascending=[False, True, True]).reset_index(drop=True)

        parquet_path = self.normalized_root / "news_unified.parquet"
        csv_path = self.normalized_root / "news_unified.csv"
        merged.to_parquet(parquet_path, index=False)
        merged.to_csv(csv_path, index=False)
        return merged
