from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import pandas as pd

from .models import FACTSET_NUMERIC_FIELDS, FactsetArticleRecord, FactsetEarningsObservation


class FactsetEarningsStorage:
    COLS = [
        "report_date",
        "reference_quarter",
        "blended_earnings_growth_yoy",
        "blended_revenue_growth_yoy",
        "eps_beat_rate",
        "eps_surprise_pct",
        "revenue_beat_rate",
        "revenue_surprise_pct",
        "forward_12m_pe",
        "forward_12m_pe_10y_avg",
        "revision_breadth_score",
        "sector_growth_json",
        "fetched_at",
        "source_url",
        "quarterly_eps_revision_pct",
        "annual_eps_revision_pct",
        "positive_eps_guidance_count",
        "negative_eps_guidance_count",
        "eps_guidance_total_count",
        "sector_revision_json",
    ]
    ARTICLE_COLS = [
        "article_url",
        "title",
        "report_date",
        "reference_quarter",
        "article_type",
        "raw_run_id",
        "ocr_image_count",
        "body_char_count",
        "supported_field_count",
        "extraction_status",
        "fetched_at",
        "narrative_json",
    ]

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "factset_earnings"
        self.normalized_root = base_dir / "data" / "normalized" / "factset_earnings"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_payload(self, run_id: str, name: str, data: Any) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _read_frame(path: Path, columns: list[str]) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame(columns=columns)
        frame = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
        out = frame.copy()
        for column in columns:
            if column not in out.columns:
                out[column] = pd.NA
        return out[columns]

    @staticmethod
    def _is_topic_url(value: object) -> bool:
        if value is None or pd.isna(value):
            return False
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null"}:
            return False
        return urlparse(text).path.strip("/").lower().startswith("topic/")

    @classmethod
    def _clean_observations(cls, frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        for column in cls.COLS:
            if column not in out.columns:
                out[column] = pd.NA
        out = out[cls.COLS]
        if out.empty:
            return out

        out["report_date"] = pd.to_datetime(out["report_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        out["report_date"] = out["report_date"].where(out["report_date"].notna(), pd.NA)
        for column in FACTSET_NUMERIC_FIELDS + ("revision_breadth_score",):
            out[column] = pd.to_numeric(out[column], errors="coerce")
        out["source_url"] = out["source_url"].where(out["source_url"].notna(), pd.NA)

        # `topic/earnings/page/N` rows came from the navigation page, not a
        # public article.  They are not observations and should not survive a
        # cleanup-only upsert.
        topic_mask = out["source_url"].map(cls._is_topic_url)
        out = out.loc[~topic_mask].copy()
        if out.empty:
            return pd.DataFrame(columns=cls.COLS)

        payload_count = out[list(FACTSET_NUMERIC_FIELDS)].notna().sum(axis=1)
        sector_payload = out["sector_revision_json"].fillna("").astype(str).str.strip()
        payload_count = payload_count + sector_payload.ne("").astype(int)
        out["supported_field_count"] = payload_count
        reference_quarter = out["reference_quarter"].fillna("").astype(str).str.strip()
        reference_quarter = reference_quarter.mask(
            reference_quarter.str.lower().isin({"nan", "none", "null"}), ""
        )
        out = out[
            out["report_date"].notna()
            & reference_quarter.ne("")
            & out["supported_field_count"].gt(0)
        ].copy()
        if out.empty:
            return pd.DataFrame(columns=cls.COLS)

        real_source = out["source_url"].fillna("").astype(str).str.strip()
        article_mask = real_source.str.startswith("https://insight.factset.com/") & ~real_source.eq(
            "https://insight.factset.com/"
        )
        article_rows = out.loc[article_mask].drop_duplicates(subset=["source_url"], keep="last")
        non_article_rows = out.loc[~article_mask].drop_duplicates(
            subset=["report_date", "reference_quarter"], keep="last"
        )
        out = pd.concat([non_article_rows, article_rows], ignore_index=True)
        out = out.drop(columns=["supported_field_count"], errors="ignore")
        return out.sort_values(by=["report_date", "source_url"], na_position="last").reset_index(drop=True)

    def load_observations(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "factset_sp500_earnings_regime.parquet"
        csv_path = self.normalized_root / "factset_sp500_earnings_regime.csv"
        if parquet_path.exists():
            return self._clean_observations(self._read_frame(parquet_path, self.COLS))
        if csv_path.exists():
            return self._clean_observations(self._read_frame(csv_path, self.COLS))
        return pd.DataFrame(columns=self.COLS)

    def upsert_observations(self, records: Iterable[FactsetEarningsObservation]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.COLS)
        existing = self.load_observations()
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        merged = self._clean_observations(merged)
        # No CSV twin: `*.csv` is gitignored repo-wide, so the twin was never
        # published -- it only cost local disk (151 MB against a 12 MB parquet
        # for the largest lane) and doubled the write on every refresh.
        merged.to_parquet(self.normalized_root / "factset_sp500_earnings_regime.parquet", index=False)
        return merged

    def replace_observations(self, records: Iterable[FactsetEarningsObservation]) -> pd.DataFrame:
        """Replace the normalized table with one deterministic replay result.

        Live collection uses ``upsert_observations`` so a failed fetch can
        retain the last known good lane.  Offline replay of a selected raw run
        is different: additive persistence would leave rows from an older run
        that the replay no longer supports, making the result falsely appear
        complete.  Replacement keeps the table an exact projection of that
        replay.
        """
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.COLS)
        cleaned = self._clean_observations(incoming)
        cleaned.to_parquet(self.normalized_root / "factset_sp500_earnings_regime.parquet", index=False)
        return cleaned

    @classmethod
    def _clean_article_catalog(cls, frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        for column in cls.ARTICLE_COLS:
            if column not in out.columns:
                out[column] = pd.NA
        out = out[cls.ARTICLE_COLS]
        if out.empty:
            return out
        out["article_url"] = out["article_url"].fillna("").astype(str).str.strip()
        out = out[out["article_url"].ne("") & ~out["article_url"].str.lower().isin({"nan", "none", "null"})].copy()
        if out.empty:
            return pd.DataFrame(columns=cls.ARTICLE_COLS)
        out["report_date"] = pd.to_datetime(out["report_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        out["report_date"] = out["report_date"].where(out["report_date"].notna(), pd.NA)
        for column in ("ocr_image_count", "body_char_count", "supported_field_count"):
            out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0).astype(int)
        out = out.drop_duplicates(subset=["article_url"], keep="last")
        return out.sort_values(by=["report_date", "article_url"], na_position="last").reset_index(drop=True)

    def load_article_catalog(self) -> pd.DataFrame:
        path = self.normalized_root / "factset_article_catalog.parquet"
        return self._clean_article_catalog(self._read_frame(path, self.ARTICLE_COLS))

    def upsert_article_catalog(self, records: Iterable[FactsetArticleRecord]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.ARTICLE_COLS)
        existing = self.load_article_catalog()
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        merged = self._clean_article_catalog(merged)
        merged.to_parquet(self.normalized_root / "factset_article_catalog.parquet", index=False)
        return merged

    def replace_article_catalog(self, records: Iterable[FactsetArticleRecord]) -> pd.DataFrame:
        """Replace the catalog with the exact articles recovered from a run."""
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.ARTICLE_COLS)
        cleaned = self._clean_article_catalog(incoming)
        cleaned.to_parquet(self.normalized_root / "factset_article_catalog.parquet", index=False)
        return cleaned
