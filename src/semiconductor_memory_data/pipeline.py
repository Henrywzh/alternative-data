from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from semiconductor_memory_data.models import (
    AdataImagePoint,
    DatasetRecord,
    FredPoint,
    PipelineResult,
    RunContext,
    Snapshot,
)
from semiconductor_memory_data.sources.adata import AdataEDMSource
from semiconductor_memory_data.sources.fred import FredSource
from semiconductor_memory_data.storage import StorageManager


PARSER_VERSION = "0.1.0"


class SemiconductorMemoryPipeline:
    def __init__(
        self,
        base_dir: Path,
        *,
        adata_source: AdataEDMSource | None = None,
        fred_source: FredSource | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.storage = StorageManager(base_dir)
        self.adata_source = adata_source or AdataEDMSource()
        self.fred_source = fred_source or FredSource()

    # ------------------------------------------------------------------
    # Public run methods
    # ------------------------------------------------------------------

    def run_adata_update(self, *, month: str | None = None) -> PipelineResult:
        """Fetch one ADATA monthly report (default: latest)."""
        context = self._create_context()
        # _latest_only=True when month is not specified, so we get most recent only
        snapshots = self.adata_source.fetch_snapshots(month=month, _latest_only=(month is None))
        if not snapshots:
            return PipelineResult(
                run_id=context.run_id,
                datasets_written={},
                raw_run_dir=str(self.storage.raw_root / context.run_id),
            )

        raw_pts, image_pts, monthly_pts = self.adata_source.extract(snapshots)

        # Fill raw_html_path on raw points using run_id
        run_rel = f"data/raw/semiconductor_memory/{context.run_id}"
        raw_pts_filled = [
            pt.__class__(
                month=pt.month,
                url=pt.url,
                fetch_time=pt.fetch_time,
                title=pt.title,
                raw_text=pt.raw_text,
                raw_html_path=f"{run_rel}/{pt.month.replace('-','')}.html",
            )
            for pt in raw_pts
        ]

        # Download images and fill local_path
        image_pts = self._download_images(image_pts)

        manifest = self._build_manifest(
            "adata-update",
            context,
            months_fetched=[p.month for p in raw_pts],
            reports_count=len(raw_pts),
            images_downloaded=len(image_pts),
        )
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)

        raw_records = self._build_adata_raw_records(context, raw_pts_filled)
        image_records = self._build_adata_image_records(context, image_pts)
        monthly_records = self._build_adata_monthly_records(context, monthly_pts)

        existing_raw = self.storage.load_dataset("adata_marketwatch_raw")
        existing_img = self.storage.load_dataset("adata_marketwatch_images")
        existing_monthly = self.storage.load_dataset("adata_marketwatch_monthly")

        written_raw = self.storage.upsert_dataset("adata_marketwatch_raw", raw_records)
        written_img = self.storage.upsert_dataset("adata_marketwatch_images", image_records)
        written_monthly = self.storage.upsert_dataset("adata_marketwatch_monthly", monthly_records)

        return PipelineResult(
            run_id=context.run_id,
            datasets_written={
                "adata_marketwatch_raw": len(written_raw),
                "adata_marketwatch_images": len(written_img),
                "adata_marketwatch_monthly": len(written_monthly),
            },
            raw_run_dir=str(raw_run_dir),
            dataset_row_deltas={
                "adata_marketwatch_raw": max(len(written_raw) - len(existing_raw), 0),
                "adata_marketwatch_images": max(len(written_img) - len(existing_img), 0),
                "adata_marketwatch_monthly": max(len(written_monthly) - len(existing_monthly), 0),
            },
        )

    def run_adata_backfill(
        self,
        *,
        start_month: str | None = None,
        end_month: str | None = None,
    ) -> PipelineResult:
        """Fetch the full ADATA archive (or a month range) and upsert all 3 tables."""
        context = self._create_context()
        snapshots = self.adata_source.fetch_snapshots(
            start_month=start_month,
            end_month=end_month,
            _rate_limit=True,
        )
        if not snapshots:
            return PipelineResult(
                run_id=context.run_id,
                datasets_written={},
                raw_run_dir=str(self.storage.raw_root / context.run_id),
            )

        raw_pts, image_pts, monthly_pts = self.adata_source.extract(snapshots)

        run_rel = f"data/raw/semiconductor_memory/{context.run_id}"
        raw_pts_filled = [
            pt.__class__(
                month=pt.month,
                url=pt.url,
                fetch_time=pt.fetch_time,
                title=pt.title,
                raw_text=pt.raw_text,
                raw_html_path=f"{run_rel}/{pt.month.replace('-','')}.html",
            )
            for pt in raw_pts
        ]

        image_pts = self._download_images(image_pts)

        manifest = self._build_manifest(
            "adata-backfill",
            context,
            months_fetched=[p.month for p in raw_pts],
            reports_count=len(raw_pts),
            images_downloaded=len(image_pts),
        )
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)

        raw_records = self._build_adata_raw_records(context, raw_pts_filled)
        image_records = self._build_adata_image_records(context, image_pts)
        monthly_records = self._build_adata_monthly_records(context, monthly_pts)

        existing_raw = self.storage.load_dataset("adata_marketwatch_raw")
        existing_img = self.storage.load_dataset("adata_marketwatch_images")
        existing_monthly = self.storage.load_dataset("adata_marketwatch_monthly")

        written_raw = self.storage.upsert_dataset("adata_marketwatch_raw", raw_records)
        written_img = self.storage.upsert_dataset("adata_marketwatch_images", image_records)
        written_monthly = self.storage.upsert_dataset("adata_marketwatch_monthly", monthly_records)

        return PipelineResult(
            run_id=context.run_id,
            datasets_written={
                "adata_marketwatch_raw": len(written_raw),
                "adata_marketwatch_images": len(written_img),
                "adata_marketwatch_monthly": len(written_monthly),
            },
            raw_run_dir=str(raw_run_dir),
            dataset_row_deltas={
                "adata_marketwatch_raw": max(len(written_raw) - len(existing_raw), 0),
                "adata_marketwatch_images": max(len(written_img) - len(existing_img), 0),
                "adata_marketwatch_monthly": max(len(written_monthly) - len(existing_monthly), 0),
            },
        )

    def run_fred_update(self) -> PipelineResult:
        """Fetch all FRED series and upsert fred_semiconductor_ppi."""
        context = self._create_context()
        snapshots = self.fred_source.fetch_snapshots()
        points = self.fred_source.extract(snapshots)

        manifest = self._build_manifest(
            "fred-update",
            context,
            series_fetched=list({p.series_id for p in points}),
            observations_count=len(points),
        )
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)

        records = [
            DatasetRecord(
                dataset_id="fred_semiconductor_ppi",
                source_url=next(
                    (s.source_url for s in snapshots if p.series_id.lower() in s.name),
                    "",
                ),
                source_run_id=context.run_id,
                scraped_at=context.scraped_at_iso,
                date=p.date,
                series_id=p.series_id,
                series_name=p.series_name,
                value=p.value,
            )
            for p in points
        ]

        existing = self.storage.load_dataset("fred_semiconductor_ppi")
        written = self.storage.upsert_dataset("fred_semiconductor_ppi", records)

        return PipelineResult(
            run_id=context.run_id,
            datasets_written={"fred_semiconductor_ppi": len(written)},
            raw_run_dir=str(raw_run_dir),
            dataset_row_deltas={"fred_semiconductor_ppi": max(len(written) - len(existing), 0)},
        )

    def run_derive(self) -> PipelineResult:
        """Join adata_marketwatch_monthly + fred_semiconductor_ppi → regime_monthly."""
        context = self._create_context()
        adata = self.storage.load_dataset("adata_marketwatch_monthly")
        fred = self.storage.load_dataset("fred_semiconductor_ppi")

        now = datetime.now(timezone.utc)

        # Build fred_monthly: aggregate FRED observations to month granularity
        fred_monthly: pd.DataFrame = pd.DataFrame()
        if not fred.empty:
            fred = fred.copy()
            fred["month"] = fred["date"].astype(str).str[:7]
            fred["value"] = pd.to_numeric(fred["value"], errors="coerce")
            fred_sorted = fred.sort_values("date").reset_index(drop=True)
            fred_sorted["fred_ppi_mom_pct"] = fred_sorted["value"].pct_change() * 100
            fred_sorted["fred_ppi_3m_trend"] = fred_sorted["value"].rolling(3, min_periods=1).mean()
            # Latest observation per month
            fred_monthly = (
                fred_sorted
                .drop_duplicates(subset=["month"], keep="last")
                [["month", "date", "value", "fred_ppi_mom_pct", "fred_ppi_3m_trend"]]
                .rename(columns={"value": "fred_ppi_value"})
            )

        # All months from ADATA
        adata_months: pd.DataFrame = pd.DataFrame()
        if not adata.empty:
            adata_months = adata[["month", "scraped_at", "nand_regime_label", "dram_regime_label",
                                  "mentions_hbm", "mentions_server", "mentions_csp",
                                  "source_url"]].copy()

        # Outer join
        if not adata_months.empty and not fred_monthly.empty:
            merged = pd.merge(adata_months, fred_monthly, on="month", how="outer")
        elif not adata_months.empty:
            merged = adata_months.copy()
            merged["fred_ppi_value"] = pd.NA
            merged["fred_ppi_mom_pct"] = pd.NA
            merged["fred_ppi_3m_trend"] = pd.NA
            merged["date"] = pd.NA
        elif not fred_monthly.empty:
            merged = fred_monthly.copy()
        else:
            merged = pd.DataFrame(columns=["month"])

        if merged.empty:
            return PipelineResult(
                run_id=context.run_id,
                datasets_written={"semiconductor_memory_regime_monthly": 0},
                raw_run_dir=str(self.storage.raw_root / context.run_id),
            )

        # Freshness calculations
        def _adata_freshness(scraped_at_val: Any) -> float | None:
            try:
                t = datetime.fromisoformat(str(scraped_at_val).replace("Z", "+00:00"))
                return (now - t).days
            except Exception:
                return None

        def _fred_lag(date_val: Any) -> float | None:
            try:
                t = datetime.fromisoformat(str(date_val) + "T00:00:00+00:00")
                return (now - t).days
            except Exception:
                return None

        if "scraped_at" in merged.columns:
            merged["adata_freshness_days"] = merged["scraped_at"].apply(_adata_freshness)
        else:
            merged["adata_freshness_days"] = pd.NA

        if "date" in merged.columns:
            merged["fred_release_lag_days"] = merged["date"].apply(_fred_lag)
        else:
            merged["fred_release_lag_days"] = pd.NA

        # data_completeness
        def _completeness(row: pd.Series) -> str:
            has_adata = pd.notna(row.get("nand_regime_label")) and row.get("nand_regime_label") not in (None, "")
            has_fred = pd.notna(row.get("fred_ppi_value"))
            if has_adata and has_fred:
                return "full"
            if has_adata:
                return "adata_only"
            if has_fred:
                return "fred_only"
            return "empty"

        merged["data_completeness"] = merged.apply(_completeness, axis=1)

        # Build DatasetRecord list
        records: list[DatasetRecord] = []
        for _, row in merged.iterrows():
            records.append(
                DatasetRecord(
                    dataset_id="semiconductor_memory_regime_monthly",
                    source_url=str(row.get("source_url", "")),
                    source_run_id=context.run_id,
                    scraped_at=context.scraped_at_iso,
                    month=str(row.get("month", "")),
                    nand_regime_label=_str_or_none(row.get("nand_regime_label")),
                    dram_regime_label=_str_or_none(row.get("dram_regime_label")),
                    mentions_hbm=_bool_or_none(row.get("mentions_hbm")),
                    mentions_server=_bool_or_none(row.get("mentions_server")),
                    mentions_csp=_bool_or_none(row.get("mentions_csp")),
                    fred_ppi_value=_float_or_none(row.get("fred_ppi_value")),
                    fred_ppi_mom_pct=_float_or_none(row.get("fred_ppi_mom_pct")),
                    fred_ppi_3m_trend=_float_or_none(row.get("fred_ppi_3m_trend")),
                    adata_freshness_days=_float_or_none(row.get("adata_freshness_days")),
                    fred_release_lag_days=_float_or_none(row.get("fred_release_lag_days")),
                    data_completeness=_str_or_none(row.get("data_completeness")),
                )
            )

        existing = self.storage.load_dataset("semiconductor_memory_regime_monthly")
        written = self.storage.upsert_dataset("semiconductor_memory_regime_monthly", records)

        return PipelineResult(
            run_id=context.run_id,
            datasets_written={"semiconductor_memory_regime_monthly": len(written)},
            raw_run_dir=str(self.storage.raw_root / context.run_id),
            dataset_row_deltas={"semiconductor_memory_regime_monthly": max(len(written) - len(existing), 0)},
        )

    def run_validate(self) -> dict[str, Any]:
        """Spot-check all 5 tables and return a summary dict."""
        results: dict[str, Any] = {}
        dataset_ids = [
            "adata_marketwatch_raw",
            "adata_marketwatch_images",
            "adata_marketwatch_monthly",
            "fred_semiconductor_ppi",
            "semiconductor_memory_regime_monthly",
        ]
        for ds in dataset_ids:
            df = self.storage.load_dataset(ds)
            results[f"{ds}_rows"] = len(df)

        # Regime distribution
        monthly = self.storage.load_dataset("adata_marketwatch_monthly")
        if not monthly.empty and "nand_regime_label" in monthly.columns:
            results["nand_regime_distribution"] = monthly["nand_regime_label"].value_counts().to_dict()
            results["dram_regime_distribution"] = monthly["dram_regime_label"].value_counts().to_dict()
            results["latest_adata_month"] = str(monthly["month"].max())

        fred = self.storage.load_dataset("fred_semiconductor_ppi")
        if not fred.empty and "date" in fred.columns:
            results["latest_fred_date"] = str(fred["date"].max())

        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _download_images(self, image_points: list[AdataImagePoint]) -> list[AdataImagePoint]:
        """Download images to local storage; skip if already present. Returns updated points."""
        updated: list[AdataImagePoint] = []
        for pt in image_points:
            try:
                dest = self.storage.images_root / pt.month / Path(pt.image_url.split("/")[-1].split("?")[0])
                if dest.exists():
                    local_path = str(dest.relative_to(self.base_dir))
                else:
                    # verify=False: industrial-ad.adata.com CDN has a chain cert issue
                    # on some macOS/Linux Python builds; images are fetched for local research only
                    response = self.adata_source.session.get(pt.image_url, timeout=30, verify=False)
                    response.raise_for_status()
                    saved = self.storage.save_image(pt.month, pt.image_url, response.content)
                    local_path = str(saved.relative_to(self.base_dir))
            except Exception as exc:
                print(f"[adata] image download failed {pt.image_url}: {exc}")
                local_path = ""
            updated.append(
                AdataImagePoint(
                    month=pt.month,
                    page_url=pt.page_url,
                    image_url=pt.image_url,
                    local_path=local_path,
                    image_type=pt.image_type,
                    vision_extracted=pt.vision_extracted,
                    vision_result_json=pt.vision_result_json,
                    extracted_at=pt.extracted_at,
                )
            )
        return updated

    def _build_adata_raw_records(self, context: RunContext, pts: list) -> list[DatasetRecord]:
        return [
            DatasetRecord(
                dataset_id="adata_marketwatch_raw",
                source_url=pt.url,
                source_run_id=context.run_id,
                scraped_at=context.scraped_at_iso,
                month=pt.month,
                fetch_time=pt.fetch_time,
                title=pt.title,
                raw_text=pt.raw_text,
                raw_html_path=pt.raw_html_path,
            )
            for pt in pts
        ]

    def _build_adata_image_records(self, context: RunContext, pts: list[AdataImagePoint]) -> list[DatasetRecord]:
        return [
            DatasetRecord(
                dataset_id="adata_marketwatch_images",
                source_url=pt.page_url,
                source_run_id=context.run_id,
                scraped_at=context.scraped_at_iso,
                month=pt.month,
                page_url=pt.page_url,
                image_url=pt.image_url,
                local_path=pt.local_path,
                image_type=pt.image_type,
                vision_extracted=pt.vision_extracted,
                vision_result_json=pt.vision_result_json,
                extracted_at=pt.extracted_at,
            )
            for pt in pts
        ]

    def _build_adata_monthly_records(self, context: RunContext, pts: list) -> list[DatasetRecord]:
        return [
            DatasetRecord(
                dataset_id="adata_marketwatch_monthly",
                source_url=pt.source_url,
                source_run_id=context.run_id,
                scraped_at=context.scraped_at_iso,
                month=pt.month,
                title=pt.title,
                narrative_nand_supply=pt.narrative_nand_supply,
                narrative_nand_price=pt.narrative_nand_price,
                narrative_dram_supply=pt.narrative_dram_supply,
                narrative_dram_price=pt.narrative_dram_price,
                mentions_hbm=pt.mentions_hbm,
                mentions_csp=pt.mentions_csp,
                mentions_server=pt.mentions_server,
                mentions_ddr4=pt.mentions_ddr4,
                mentions_reallocate_capacity=pt.mentions_reallocate_capacity,
                mentions_shortage=pt.mentions_shortage,
                mentions_oversupply=pt.mentions_oversupply,
                nand_regime_label=pt.nand_regime_label,
                dram_regime_label=pt.dram_regime_label,
            )
            for pt in pts
        ]

    def _create_context(self) -> RunContext:
        now = datetime.now(timezone.utc)
        run_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        return RunContext(run_id=run_id, scraped_at=now)

    def _build_manifest(self, mode: str, context: RunContext, **kwargs: Any) -> dict[str, Any]:
        return {
            "run_id": context.run_id,
            "mode": mode,
            "scraped_at": context.scraped_at_iso,
            "parser_version": PARSER_VERSION,
            **kwargs,
        }


# ---------------------------------------------------------------------------
# Tiny coercion helpers used in run_derive
# ---------------------------------------------------------------------------

def _str_or_none(val: Any) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val)
    return None if s in ("", "nan", "None", "<NA>") else s


def _float_or_none(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if pd.isna(f) else f
    except (ValueError, TypeError):
        return None


def _bool_or_none(val: Any) -> bool | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() == "true"
